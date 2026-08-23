-- Per-candidate questions against a fixed rubric (supersedes D16).
--
-- The invariant a leaderboard needs is the scoring frame, not the question
-- wording. So the job now carries competencies and their BARS anchors, and the
-- probes that elicit them are generated per candidate from their resume.
--
-- Two candidates get different questions and the same measuring stick, which
-- keeps their scores comparable while letting each question reach what that
-- person actually built.

alter table job
  -- JobRubric: competencies, each with portable anchors and a weight. Replaces
  -- question_bank as the thing generated once per job.
  add column if not exists rubric jsonb;

alter table application
  -- list[Question], generated at invite time from job.rubric plus this
  -- candidate's parsed resume. On the application rather than the interview
  -- because it is produced before an interview row exists, and because a
  -- dropped connection rejoining must get the identical set (D12).
  add column if not exists questions jsonb,
  add column if not exists questions_model_id text,
  add column if not exists questions_prompt_version text,
  add column if not exists questions_error text;

comment on column job.rubric is
  'JobRubric. Competencies and anchors, fixed for every candidate. The probes
   are per-candidate and live on application.questions.';
comment on column application.questions is
  'list[Question] generated for this candidate. Each carries a copy of its
   competency dimensions, so lane 2 and lane 3 see an unchanged Question shape.';

-- job.question_bank is deliberately left in place and unused. Lane 2 currently
-- reads it and validates it into Question objects; leaving it null makes that
-- fail loudly rather than silently parsing a rubric into nonsense. Drop it in a
-- cleanup migration once ai-call has merged and moved to
-- intake.build_interview_package().
