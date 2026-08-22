-- Multi-tenancy rebuild.
--
-- DESTRUCTIVE: drops and recreates every table. Safe because nothing is in
-- production and the only rows are test data. Doing this now rather than as a
-- series of ALTERs is the whole advantage of catching it early.
--
-- The central idea: org isolation is enforced by the database, not by
-- remembering to filter. Every child table carries org_id and references its
-- parent through a COMPOSITE foreign key (org_id, parent_id). A row whose
-- org_id disagrees with its parent's cannot be inserted — Postgres rejects it.
-- Forgetting a WHERE clause becomes a bug you can see, not a cross-tenant leak.

drop view  if exists job_pipeline_stats;
drop table if exists outreach_message, recruiter_chat_session,
                     integrity_event, question_instance, interview,
                     interview_invite, application, candidate, job,
                     membership, organization cascade;

create extension if not exists "pgcrypto";
create extension if not exists "citext";

create or replace function set_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end;
$$;

-- ==================================================================== TENANCY

create table organization (
  id   uuid primary key default gen_random_uuid(),
  name text not null,
  slug citext not null unique,

  plan text not null default 'free'
    check (plan in ('free','pro','enterprise')),

  -- NULL means "use the plan default" (resolved in shared/plans.py). Changing
  -- a tier's limit is then a one-line config edit rather than an UPDATE across
  -- every row on that tier. The column exists for the exceptions — enterprise
  -- deals, temporarily bumping an evaluating customer.
  max_concurrent_interviews int,   -- protects infrastructure
  monthly_interview_limit   int,   -- the commercial lever; minutes are the cost

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger organization_updated_at before update on organization
  for each row execute function set_updated_at();

-- A join table rather than organization_id on the user: recruiting agencies and
-- consultants work across companies. The UI can still assume one org and skip
-- the switcher when a user has exactly one membership.
create table membership (
  id         uuid primary key default gen_random_uuid(),
  org_id     uuid not null references organization(id) on delete cascade,
  user_id    uuid not null,                    -- auth.users
  role       text not null default 'recruiter'
               check (role in ('owner','recruiter')),
  created_at timestamptz not null default now(),
  unique (org_id, user_id)
);
create index membership_user_idx on membership (user_id);

-- ==================================================================== LANE 1

create table job (
  id     uuid primary key default gen_random_uuid(),
  org_id uuid not null references organization(id) on delete cascade,

  title       text not null,
  role_family text,
  seniority   text not null,
  jd_text     text not null,

  -- Closed roles keep their leaderboard, transcripts and scores. A filled role
  -- is still an asset to the company, and compliance.md requires decision
  -- records for 24 months regardless.
  status    text not null default 'open'
              check (status in ('draft','open','closed','archived')),
  closed_at timestamptz,

  -- Hard requirements, optionally extracted from the JD by Gemini. NOT gated on
  -- human approval: the meaningful review happens at the leaderboard, and
  -- blocking the pipeline would defeat its purpose. The safety valve is that
  -- screen-rejected candidates stay visible and reversible (see application).
  screening_profile             jsonb not null default '{}'::jsonb,
  screening_profile_source      text  not null default 'manual'
                                  check (screening_profile_source in ('ai','manual')),
  screening_profile_model_id    text,
  screening_profile_reviewed_at timestamptz,
  screening_profile_reviewed_by uuid,

  -- Generated once per job; every candidate for the role gets the identical set
  -- (D16). Survives closure so reopening a similar role can reuse it.
  question_bank        jsonb,
  question_bank_status text not null default 'pending'
                         check (question_bank_status in
                                ('pending','building','ready','failed')),
  question_bank_error  text,
  rubric_version       text not null default 'v1',

  created_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- Target for the composite foreign keys below.
  unique (org_id, id)
);
create trigger job_updated_at before update on job
  for each row execute function set_updated_at();
create index job_org_status_idx on job (org_id, status, created_at desc);

-- Per-org, not global. The same person applying to two of your customers gets
-- two rows, deliberately: a global candidate would let company A infer that
-- someone also applied to company B.
create table candidate (
  id     uuid primary key default gen_random_uuid(),
  org_id uuid not null references organization(id) on delete cascade,

  email     citext not null,
  full_name text,
  phone     text,
  location  text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  unique (org_id, email),
  unique (org_id, id)
);
create trigger candidate_updated_at before update on candidate
  for each row execute function set_updated_at();

create table application (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null,
  job_id       uuid not null,
  candidate_id uuid not null,

  -- Every stage the dashboard needs to count separately. `rejected_screen` and
  -- `rejected_post` are distinct because a candidate filtered by hard checks
  -- never reached a leaderboard, and that difference matters when someone asks
  -- why they were rejected.
  status text not null default 'received'
    check (status in (
      'received','parsing','screening',
      'rejected_screen','review','invited',
      'interviewing','interviewed','scored',
      'advanced','rejected_post',
      'failed'
    )),

  resume_url    text not null,
  parsed_resume jsonb,
  hard_checks   jsonb not null default '[]'::jsonb,
  screening     jsonb,

  screening_model_id       text,
  screening_prompt_version text,

  consent_given_at timestamptz not null,

  -- compliance.md promises a human reviews every rejection. Without recording
  -- which human, that promise cannot be evidenced when a candidate disputes it.
  decided_by    uuid,
  decided_at    timestamptz,
  decision_note text,

  -- Set when the pipeline throws. Previously a failure left the row at
  -- 'received', indistinguishable from one that had just arrived — invisible
  -- stuck work is the worst kind.
  failure_reason text,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  foreign key (org_id, job_id)       references job(org_id, id)       on delete cascade,
  foreign key (org_id, candidate_id) references candidate(org_id, id) on delete cascade,
  unique (job_id, candidate_id),
  unique (org_id, id)
);
create trigger application_updated_at before update on application
  for each row execute function set_updated_at();
create index application_job_status_idx on application (org_id, job_id, status);
create index application_org_status_idx on application (org_id, status);

create table interview_invite (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null,
  application_id uuid not null,

  -- Only the hash. A database leak must not hand out working interview links.
  token_hash  text        not null unique,
  expires_at  timestamptz not null,
  redeemed_at timestamptz,
  interview_id uuid,

  created_at timestamptz not null default now(),

  foreign key (org_id, application_id) references application(org_id, id) on delete cascade,
  unique (org_id, id)
);
create index interview_invite_application_idx on interview_invite (application_id);

-- ==================================================================== LANE 2

create table interview (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null,
  application_id uuid not null,
  job_id         uuid not null,

  status text not null default 'pending'
    check (status in ('pending','in_progress','completed','abandoned','flagged')),

  room_name  text unique,
  started_at timestamptz,
  ended_at   timestamptz,

  transcript jsonb not null default '[]'::jsonb,
  audio_url  text,

  model_id       text,
  prompt_version text,

  overall           numeric(3,2),
  percentile        numeric(5,2),
  recommendation    text check (recommendation in ('advance','hold','reject')),
  hard_gate_applied boolean not null default false,
  role_fit          numeric(3,2),
  holistic          jsonb,
  integrity         jsonb,
  rubric_version    text,
  scored_at         timestamptz,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  foreign key (org_id, application_id) references application(org_id, id) on delete cascade,
  foreign key (org_id, job_id)         references job(org_id, id)         on delete cascade,
  unique (org_id, id)
);
create trigger interview_updated_at before update on interview
  for each row execute function set_updated_at();

-- Serves both the "interview ongoing" dashboard tile and the concurrency check
-- at redeem time.
create index interview_org_status_idx on interview (org_id, status);
create index interview_leaderboard_idx
  on interview (org_id, job_id, overall desc nulls last);

create table question_instance (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null,
  interview_id uuid not null,

  question_id text not null,
  order_index int  not null,

  transcript_segment text,

  -- Each DimensionScore carries a verbatim evidence quote. Lane 3's chat cannot
  -- explain a score it has no quote for, so this is not optional.
  dimension_scores jsonb,
  weighted_score   numeric(3,2),
  followed_up      boolean not null default false,

  model_id       text,
  prompt_version text,

  created_at timestamptz not null default now(),

  foreign key (org_id, interview_id) references interview(org_id, id) on delete cascade,
  unique (interview_id, question_id),
  unique (org_id, id)
);
create index question_instance_interview_idx
  on question_instance (interview_id, order_index);

create table integrity_event (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null,
  interview_id uuid not null,

  type       text         not null,
  severity   numeric(3,2) not null check (severity between 0 and 1),
  at_ms      integer      not null,
  detail     jsonb        not null default '{}'::jsonb,
  created_at timestamptz  not null default now(),

  foreign key (org_id, interview_id) references interview(org_id, id) on delete cascade
);
create index integrity_event_interview_idx on integrity_event (interview_id);

-- ==================================================================== LANE 3

create table recruiter_chat_session (
  id           uuid primary key default gen_random_uuid(),
  org_id       uuid not null,
  interview_id uuid not null,
  recruiter_id uuid not null,

  messages jsonb not null default '[]'::jsonb,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  foreign key (org_id, interview_id) references interview(org_id, id) on delete cascade
);
create trigger recruiter_chat_session_updated_at before update on recruiter_chat_session
  for each row execute function set_updated_at();
create index recruiter_chat_session_interview_idx
  on recruiter_chat_session (interview_id);

create table outreach_message (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null,
  application_id uuid not null,

  channel text not null check (channel in ('email','sms')),
  subject text,
  body    text not null,
  sent_at timestamptz,
  sent_by uuid,

  created_at timestamptz not null default now(),

  foreign key (org_id, application_id) references application(org_id, id) on delete cascade
);
create index outreach_message_application_idx on outreach_message (application_id);

-- ================================================================= DASHBOARD

-- One grouped count answers every tile. security_invoker so the view respects
-- the caller's RLS rather than the definer's.
create view job_pipeline_stats
with (security_invoker = true) as
select
  org_id,
  job_id,
  count(*)                                                          as total,
  count(*) filter (where status in ('received','parsing','screening')) as processing,
  count(*) filter (where status = 'review')                          as needs_review,
  count(*) filter (where status = 'rejected_screen')                 as rejected_screen,
  count(*) filter (where status = 'rejected_post')                   as rejected_post,
  count(*) filter (where status = 'invited')                         as interview_remaining,
  count(*) filter (where status = 'interviewing')                    as interview_ongoing,
  count(*) filter (where status = 'interviewed')                     as scoring,
  count(*) filter (where status = 'scored')                          as scored,
  count(*) filter (where status = 'advanced')                        as advanced,
  count(*) filter (where status = 'failed')                          as failed
from application
group by org_id, job_id;

-- ======================================================================= RLS

-- Enabled with no permissive policy: the browser never queries these directly.
-- Every read and write goes through FastAPI, which holds the secret key and has
-- already resolved the caller's org from membership (D7). Defence in depth, so
-- a leaked publishable key alone exposes nothing.
alter table organization           enable row level security;
alter table membership             enable row level security;
alter table job                    enable row level security;
alter table candidate              enable row level security;
alter table application            enable row level security;
alter table interview_invite       enable row level security;
alter table interview              enable row level security;
alter table question_instance      enable row level security;
alter table integrity_event        enable row level security;
alter table recruiter_chat_session enable row level security;
alter table outreach_message       enable row level security;
