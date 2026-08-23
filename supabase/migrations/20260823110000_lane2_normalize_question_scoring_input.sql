-- Normalize the stable score-answer request fields for querying and review.
--
-- This migration does not depend on the deprecated scoring_input JSONB column.
-- The post-call scoring pipeline writes these columns and child tables directly.

alter table question_instance
  add column if not exists question_text text,
  add column if not exists question_type text
    check (question_type is null or question_type in (
      'background', 'technical', 'project', 'behavioral', 'situational', 'poison'
    )),
  add column if not exists competency text,
  add column if not exists seniority text
    check (seniority is null or seniority in ('junior', 'mid', 'senior')),
  add column if not exists resume_headline_claim boolean,
  add column if not exists flagship_project boolean,
  add column if not exists central_to_role boolean;

comment on column question_instance.question_text is
  'Exact question text sent to score-answer for this question instance.';
comment on column question_instance.question_type is
  'Fixed-rubric question category sent to score-answer.';
comment on column question_instance.competency is
  'Job competency measured by this question.';
comment on column question_instance.seniority is
  'Seniority weighting context sent to score-answer.';
comment on column question_instance.resume_headline_claim is
  'Whether this question tests a headline resume claim.';
comment on column question_instance.flagship_project is
  'Whether this question tests the candidate flagship project.';
comment on column question_instance.central_to_role is
  'Whether the tested claim is central to the role.';

create table if not exists question_scoring_claim (
  id                   uuid primary key default gen_random_uuid(),
  org_id               uuid not null,
  question_instance_id uuid not null,
  source               text not null check (source in ('resume', 'prior_answer')),
  claim_index          integer not null check (claim_index >= 0),
  claim_text           text not null check (btrim(claim_text) <> ''),
  created_at           timestamptz not null default now(),

  foreign key (org_id, question_instance_id)
    references question_instance(org_id, id) on delete cascade,
  unique (question_instance_id, source, claim_index),
  unique (org_id, id)
);

create index if not exists question_scoring_claim_question_idx
  on question_scoring_claim (question_instance_id, source, claim_index);

comment on table question_scoring_claim is
  'Ordered resume and prior-answer claims supplied to Gemini for one answer score.';

create table if not exists question_conversation_turn (
  id                   uuid primary key default gen_random_uuid(),
  org_id               uuid not null,
  question_instance_id uuid not null,
  turn_index           integer not null check (turn_index >= 0),
  speaker              text not null check (speaker in ('candidate', 'interviewer', 'agent')),
  text                 text not null check (btrim(text) <> ''),
  start_ms             integer not null check (start_ms >= 0),
  end_ms               integer not null check (end_ms >= start_ms),
  is_follow_up         boolean not null default false,
  created_at           timestamptz not null default now(),

  foreign key (org_id, question_instance_id)
    references question_instance(org_id, id) on delete cascade,
  unique (question_instance_id, turn_index),
  unique (org_id, id)
);

create index if not exists question_conversation_turn_question_idx
  on question_conversation_turn (question_instance_id, turn_index);

comment on table question_conversation_turn is
  'Ordered transcript turns supplied to Gemini for one answer score.';

alter table question_scoring_claim enable row level security;
alter table question_conversation_turn enable row level security;
