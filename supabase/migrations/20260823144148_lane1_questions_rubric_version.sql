-- Record which rubric version a candidate's questions were written against.
--
-- application.questions is a point-in-time snapshot: each question carries a
-- copy of its competency's anchors, frozen at invite time. job.rubric_version
-- is live and moves when a recruiter rebuilds.
--
-- Sending the live version alongside frozen questions meant an interview could
-- be stamped v2 while being scored against v1 anchors:
--
--   day 0  invite sent            -> questions written against rubric v1
--   day 2  recruiter edits the JD -> rubric rebuilt, job.rubric_version = v2
--   day 4  candidate redeems      -> InterviewPackage says v2, anchors are v1
--
-- Invites live 7 days and PUT /jobs/{id} rebuilds by default when jd_text
-- changes, so the window is wide open. Lane 3 would then rank that interview
-- against genuine v2 ones as if calibrated, which is the exact thing
-- rubric_version exists to prevent.

alter table application
  add column if not exists questions_rubric_version text;

comment on column application.questions_rubric_version is
  'The job.rubric_version in force when application.questions was generated.
   Travels on the InterviewPackage instead of the job''s current value, because
   the questions carry anchors from this version, not the current one.';

-- Existing rows stay null. build_interview_package() falls back to
-- job.rubric_version for them, which is correct: they were generated before
-- rebuilds could diverge, and a wrong guess is worse than the old behaviour.
