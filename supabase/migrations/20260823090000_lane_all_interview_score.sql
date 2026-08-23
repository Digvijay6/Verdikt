-- Stored post-call scores.
--
-- Lane 2 writes one row after the deterministic post-call scoring pass. Lane 3
-- reads this table for the leaderboard, detail page, and recruiter chat. The
-- summary columns make ranking cheap; `result` preserves the full
-- InterviewResult contract with evidence quotes and provenance.

create table if not exists interview_score (
  id             uuid primary key default gen_random_uuid(),
  org_id         uuid not null,
  interview_id   uuid not null,
  application_id uuid not null,
  job_id         uuid not null,

  overall        numeric(3,2) not null check (overall between 1 and 5),
  display_score  integer generated always as
    (round(((overall - 1) / 4) * 100)::integer) stored
    check (display_score between 0 and 100),
  percentile     numeric(5,2) check (percentile between 0 and 100),
  recommendation text not null check (recommendation in ('advance','hold','reject')),
  hard_gate_applied boolean not null default false,

  role_fit numeric(3,2) not null check (role_fit between 1 and 5),
  holistic  jsonb not null,
  integrity jsonb not null,
  answers   jsonb not null default '[]'::jsonb,

  rubric_version text not null,
  scored_at timestamptz not null default now(),

  -- Full shared.models.scoring.InterviewResult payload. Keeping this whole
  -- object avoids splitting the evidence/rationale contract across columns.
  result jsonb not null,

  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  foreign key (org_id, interview_id)   references interview(org_id, id)   on delete cascade,
  foreign key (org_id, application_id) references application(org_id, id) on delete cascade,
  foreign key (org_id, job_id)         references job(org_id, id)         on delete cascade,

  unique (org_id, interview_id),
  unique (org_id, id)
);

create trigger interview_score_updated_at before update on interview_score
  for each row execute function set_updated_at();

create index if not exists interview_score_leaderboard_idx
  on interview_score (org_id, job_id, overall desc, scored_at desc);

create index if not exists interview_score_application_idx
  on interview_score (org_id, application_id);

alter table interview_score enable row level security;
