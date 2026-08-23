-- Preserve the exact per-question Gemini request and rubric-v2 response.
--
-- The source transcript, job, and resume remain normalized in their owning
-- tables. These snapshots make a score reproducible even if those sources are
-- edited later, and let a reviewer compare the model input with its evidence.

alter table question_instance
  add column if not exists scoring_input jsonb
    check (scoring_input is null or jsonb_typeof(scoring_input) = 'object'),
  add column if not exists fixed_rubric jsonb
    check (fixed_rubric is null or jsonb_typeof(fixed_rubric) = 'object');

comment on column question_instance.scoring_input is
  'Exact structured user_content sent to score-answer for this question.';

comment on column question_instance.fixed_rubric is
  'Validated FixedRubricAssessment returned by score-answer.v2.';
