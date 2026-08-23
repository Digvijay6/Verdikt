-- LANE 2 — additive columns for the interview and question_instance tables.
-- Depends on 20260822120000_lane_all_multitenancy.sql and
-- 20260823090000_lane_all_interview_score.sql (which created interview_score).
--
-- interview_score (Lane 3's table) carries the recruiter-facing summary
-- columns (composite_score, needs_human_review, etc). These columns on
-- interview and question_instance are the raw audit trail and per-question
-- detail that Lane 2 owns.

-- interview: raw audit columns
alter table interview add column if not exists seniority text default 'mid';
  -- drives composite weights, read from job at redeem time
alter table interview add column if not exists transcript_summary text;
  -- short prose gist for Lane 3's recruiter chat context
alter table interview add column if not exists result jsonb;
  -- full InterviewResult object (the lane 2 -> lane 3 handoff audit copy)
alter table interview add column if not exists composite_weights jsonb;
  -- the actual seniority weights used, for audit

-- question_instance: per-question scoring columns
alter table question_instance add column if not exists answer_score jsonb;
  -- AnswerScore object (post-call rubric scores, includes fixed_rubric)
alter table question_instance add column if not exists live_signal jsonb;
  -- LiveSignal object (provisional correctness, overwritten by answer_score)
alter table question_instance add column if not exists followup_count int
  not null default 0;
alter table question_instance add column if not exists followup_transcript text;
  -- concatenated follow-up answers
alter table question_instance add column if not exists scored_at timestamptz;