-- LANE 2 — additive columns for the 0-100 rubric scoring pipeline.
-- Depends on 20260822120000_lane_all_multitenancy.sql (which recreated the
-- interview / question_instance / integrity_event tables with org_id).

-- interview: scoring pipeline columns
alter table interview add column if not exists seniority text default 'mid';
alter table interview add column if not exists transcript_summary text;
alter table interview add column if not exists result jsonb;
  -- full InterviewResult object (the lane 2 -> lane 3 handoff)

alter table interview add column if not exists needs_human_review boolean
  not null default false;
alter table interview add column if not exists human_review_reasons jsonb
  not null default '[]'::jsonb;
alter table interview add column if not exists consistency_score int
  check (consistency_score between 0 and 100);
alter table interview add column if not exists composite_weights jsonb;

-- question_instance: per-question scoring columns
alter table question_instance add column if not exists answer_score jsonb;
  -- AnswerScore object (post-call rubric scores)
alter table question_instance add column if not exists live_signal jsonb;
  -- LiveSignal object (provisional, overwritten by answer_score)
alter table question_instance add column if not exists followup_count int
  not null default 0;
alter table question_instance add column if not exists followup_transcript text;
alter table question_instance add column if not exists scored_at timestamptz;
alter table question_instance add column if not exists followup_resilience_score int
  check (followup_resilience_score between 0 and 100);
alter table question_instance add column if not exists ownership_level text;
  -- full_owner | major_contributor | minor_contributor | unclear
alter table question_instance add column if not exists consistency_label text;
  -- consistent | vague | unverifiable | inflated