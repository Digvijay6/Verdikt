-- Initial schema, all three lanes.
--
-- Written once rather than three times because every lane is blocked until the
-- tables exist. Derived directly from backend/shared/models/ — keep names 1:1
-- with the Pydantic models, since there is no ORM keeping them in sync.
--
-- Ownership (everyone reads, only the owner writes):
--   lane 1  job, candidate, application, interview_invite
--   lane 2  interview, question_instance, integrity_event
--   lane 3  recruiter_chat_session, outreach_message

create extension if not exists "pgcrypto";
create extension if not exists "citext";

-- updated_at maintenance -----------------------------------------------------

create or replace function set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ============================================================ LANE 1 — intake

create table job (
  id                   uuid primary key default gen_random_uuid(),
  title                text        not null,
  role_family          text,
  seniority            text        not null,
  jd_text              text        not null,

  -- ScreeningProfile: min_years_experience, required_skills, preferred_skills,
  -- locations, remote_ok, work_authorization
  screening_profile    jsonb       not null default '{}'::jsonb,

  -- list[Question] produced by the ADK question_builder workflow. Generated
  -- once per job and identical for every candidate (D16) — tailoring per
  -- candidate would destroy score comparability across the leaderboard.
  question_bank        jsonb,
  question_bank_status text        not null default 'pending'
                         check (question_bank_status in
                                ('pending','building','ready','failed')),
  question_bank_error  text,

  -- Bump whenever the bank or its anchors change. Lane 2 scores against these
  -- anchors, so a change here changes scores.
  rubric_version       text        not null default 'v1',

  created_by           uuid,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create trigger job_updated_at
  before update on job
  for each row execute function set_updated_at();

-- One row per human. citext gives case-insensitive uniqueness, so
-- Ada@x.com and ada@x.com are the same candidate (D20) — without this you get
-- duplicate leaderboard entries for one person.
create table candidate (
  id         uuid primary key default gen_random_uuid(),
  email      citext      not null unique,
  full_name  text,
  phone      text,
  location   text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger candidate_updated_at
  before update on candidate
  for each row execute function set_updated_at();

create table application (
  id           uuid primary key default gen_random_uuid(),
  job_id       uuid        not null references job(id)       on delete cascade,
  candidate_id uuid        not null references candidate(id) on delete cascade,

  status text not null default 'received'
    check (status in ('received','parsed','screened','invited',
                      'interviewing','complete','rejected')),

  resume_url    text  not null,
  parsed_resume jsonb,
  hard_checks   jsonb not null default '[]'::jsonb,
  screening     jsonb,

  -- Provenance (D5). A screening decision without these cannot be compared
  -- against one made under a different model or prompt version.
  screening_model_id      text,
  screening_prompt_version text,

  -- compliance.md: recorded before the resume is processed, not after.
  consent_given_at timestamptz not null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- One application per person per job. Re-applying updates rather than
  -- duplicating.
  unique (job_id, candidate_id)
);

create trigger application_updated_at
  before update on application
  for each row execute function set_updated_at();

create index application_job_status_idx on application (job_id, status);
create index application_candidate_idx  on application (candidate_id);

-- The emailed link. Only the hash is stored, so a database leak does not hand
-- out working interview links (D12).
create table interview_invite (
  id             uuid primary key default gen_random_uuid(),
  application_id uuid        not null references application(id) on delete cascade,
  token_hash     text        not null unique,
  expires_at     timestamptz not null,

  -- Set on first redeem. Revisiting the link while the interview is still
  -- in_progress rejoins it rather than starting over — strict single-use would
  -- strand any candidate whose connection drops.
  redeemed_at    timestamptz,
  interview_id   uuid,

  created_at     timestamptz not null default now()
);

create index interview_invite_application_idx on interview_invite (application_id);

-- ========================================================= LANE 2 — interview

create table interview (
  id             uuid primary key default gen_random_uuid(),
  application_id uuid not null references application(id) on delete cascade,
  job_id         uuid not null references job(id)         on delete cascade,

  status text not null default 'pending'
    check (status in ('pending','in_progress','completed','abandoned','flagged')),

  room_name  text unique,
  started_at timestamptz,
  ended_at   timestamptz,

  transcript jsonb not null default '[]'::jsonb,
  audio_url  text,

  -- Which Gemini Live model actually conducted this interview. Matters because
  -- the 2.5 native-audio and 3.1 live models differ in mid-session capability.
  model_id       text,
  prompt_version text,

  -- InterviewResult composite. Per-question scores live in question_instance;
  -- assembling the model means this row plus its children.
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
  updated_at timestamptz not null default now()
);

create trigger interview_updated_at
  before update on interview
  for each row execute function set_updated_at();

create index interview_application_idx on interview (application_id);
create index interview_job_overall_idx on interview (job_id, overall desc nulls last);

create table question_instance (
  id          uuid primary key default gen_random_uuid(),
  interview_id uuid not null references interview(id) on delete cascade,

  question_id text not null,
  order_index int  not null,

  transcript_segment text,

  -- list[DimensionScore] — each carries a verbatim evidence quote. Lane 3's
  -- chat cannot explain a score it has no quote for, so this is not optional.
  dimension_scores jsonb,
  weighted_score   numeric(3,2),
  followed_up      boolean not null default false,

  model_id       text,
  prompt_version text,

  created_at timestamptz not null default now(),

  unique (interview_id, question_id)
);

create index question_instance_interview_idx on question_instance (interview_id, order_index);

create table integrity_event (
  id           uuid primary key default gen_random_uuid(),
  interview_id uuid        not null references interview(id) on delete cascade,
  type         text        not null,
  severity     numeric(3,2) not null check (severity between 0 and 1),
  at_ms        integer     not null,
  detail       jsonb       not null default '{}'::jsonb,
  created_at   timestamptz not null default now()
);

create index integrity_event_interview_idx on integrity_event (interview_id);

-- ========================================================== LANE 3 — insights

create table recruiter_chat_session (
  id           uuid primary key default gen_random_uuid(),
  interview_id uuid not null references interview(id) on delete cascade,
  recruiter_id uuid not null,
  messages     jsonb not null default '[]'::jsonb,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create trigger recruiter_chat_session_updated_at
  before update on recruiter_chat_session
  for each row execute function set_updated_at();

create index recruiter_chat_session_interview_idx
  on recruiter_chat_session (interview_id);

create table outreach_message (
  id             uuid primary key default gen_random_uuid(),
  application_id uuid not null references application(id) on delete cascade,
  channel        text not null check (channel in ('email','sms')),
  subject        text,
  body           text not null,
  sent_at        timestamptz,
  sent_by        uuid,
  created_at     timestamptz not null default now()
);

create index outreach_message_application_idx on outreach_message (application_id);

-- ================================================================ RLS

-- Enabled with no permissive policy: the browser never queries these tables
-- directly. Every read and write goes through FastAPI, which holds the service
-- key and has already checked who is asking (D7). This is defence in depth, so
-- that a leaked anon key alone does not expose candidate PII.

alter table job                    enable row level security;
alter table candidate              enable row level security;
alter table application            enable row level security;
alter table interview_invite       enable row level security;
alter table interview              enable row level security;
alter table question_instance      enable row level security;
alter table integrity_event        enable row level security;
alter table recruiter_chat_session enable row level security;
alter table outreach_message       enable row level security;
