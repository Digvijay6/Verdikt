-- Fixed 0-100 rubric aggregates used by Insights.
--
-- Per-answer measurements remain in `answers` and the complete audit contract
-- remains in `result`. These columns are the indexed recruiter-facing summary.

alter table interview_score
  add column if not exists seniority_bucket text
    check (seniority_bucket in ('junior', 'mid', 'senior')),
  add column if not exists technical_accuracy_score numeric(5,2)
    check (technical_accuracy_score between 0 and 100),
  add column if not exists project_depth_score numeric(5,2)
    check (project_depth_score between 0 and 100),
  add column if not exists followup_resilience_score numeric(5,2)
    check (followup_resilience_score between 0 and 100),
  add column if not exists consistency_score numeric(5,2)
    check (consistency_score between 0 and 100),
  add column if not exists composite_score numeric(5,2)
    check (composite_score between 0 and 100),
  add column if not exists needs_human_review boolean not null default false,
  add column if not exists review_reasons jsonb not null default '[]'::jsonb
    check (jsonb_typeof(review_reasons) = 'array');

create index if not exists interview_score_rubric_v2_leaderboard_idx
  on interview_score (org_id, job_id, composite_score desc nulls last, scored_at desc);
