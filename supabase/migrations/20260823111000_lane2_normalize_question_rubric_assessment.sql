-- Store the validated post-call Gemini assessment in relational columns.
-- One assessment belongs to exactly one question instance.

create table if not exists question_rubric_assessment (
  id                   uuid primary key default gen_random_uuid(),
  org_id               uuid not null,
  question_instance_id uuid not null,

  technical_accuracy_score     smallint check (technical_accuracy_score between 0 and 100),
  technical_accuracy_quote     text,
  technical_accuracy_rationale text,

  project_depth_score     smallint check (project_depth_score between 0 and 100),
  project_depth_quote     text,
  project_depth_rationale text,

  ownership_level     text check (ownership_level in (
    'full_owner', 'major_contributor', 'minor_contributor', 'unclear'
  )),
  ownership_quote     text,
  ownership_rationale text,

  followup_resilience_score     smallint check (followup_resilience_score between 0 and 100),
  followup_resilience_quote     text,
  followup_resilience_rationale text,

  consistency_label     text not null check (consistency_label in (
    'consistent', 'vague', 'unverifiable', 'inflated'
  )),
  consistency_quote     text not null check (btrim(consistency_quote) <> ''),
  consistency_rationale text not null check (btrim(consistency_rationale) <> ''),

  model_id       text not null,
  prompt_version text not null,
  created_at     timestamptz not null default now(),

  foreign key (org_id, question_instance_id)
    references question_instance(org_id, id) on delete cascade,
  unique (question_instance_id),
  unique (org_id, id),

  check (
    (technical_accuracy_score is null
      and technical_accuracy_quote is null
      and technical_accuracy_rationale is null)
    or
    (technical_accuracy_score is not null
      and technical_accuracy_quote is not null
      and technical_accuracy_rationale is not null
      and btrim(technical_accuracy_quote) <> ''
      and btrim(technical_accuracy_rationale) <> '')
  ),
  check (
    (project_depth_score is null
      and project_depth_quote is null
      and project_depth_rationale is null)
    or
    (project_depth_score is not null
      and project_depth_quote is not null
      and project_depth_rationale is not null
      and btrim(project_depth_quote) <> ''
      and btrim(project_depth_rationale) <> '')
  ),
  check (
    (ownership_level is null
      and ownership_quote is null
      and ownership_rationale is null)
    or
    (ownership_level is not null
      and ownership_quote is not null
      and ownership_rationale is not null
      and btrim(ownership_quote) <> ''
      and btrim(ownership_rationale) <> '')
  ),
  check (
    (followup_resilience_score is null
      and followup_resilience_quote is null
      and followup_resilience_rationale is null)
    or
    (followup_resilience_score is not null
      and followup_resilience_quote is not null
      and followup_resilience_rationale is not null
      and btrim(followup_resilience_quote) <> ''
      and btrim(followup_resilience_rationale) <> '')
  )
);

-- Some development databases still have the legacy JSONB column while others
-- have already removed it. Preserve valid existing assessments when available
-- without making this migration depend on that column.
do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'question_instance'
      and column_name = 'fixed_rubric'
  ) then
    execute $backfill$
      insert into question_rubric_assessment (
        org_id,
        question_instance_id,
        technical_accuracy_score,
        technical_accuracy_quote,
        technical_accuracy_rationale,
        project_depth_score,
        project_depth_quote,
        project_depth_rationale,
        ownership_level,
        ownership_quote,
        ownership_rationale,
        followup_resilience_score,
        followup_resilience_quote,
        followup_resilience_rationale,
        consistency_label,
        consistency_quote,
        consistency_rationale,
        model_id,
        prompt_version
      )
      select
        qi.org_id,
        qi.id,
        nullif(qi.fixed_rubric ->> 'technical_accuracy_score', '')::smallint,
        qi.fixed_rubric #>> '{technical_accuracy_evidence,quote}',
        qi.fixed_rubric #>> '{technical_accuracy_evidence,rationale}',
        nullif(qi.fixed_rubric ->> 'project_depth_score', '')::smallint,
        qi.fixed_rubric #>> '{project_depth_evidence,quote}',
        qi.fixed_rubric #>> '{project_depth_evidence,rationale}',
        qi.fixed_rubric ->> 'ownership_level',
        qi.fixed_rubric #>> '{ownership_evidence,quote}',
        qi.fixed_rubric #>> '{ownership_evidence,rationale}',
        nullif(qi.fixed_rubric ->> 'followup_resilience_score', '')::smallint,
        qi.fixed_rubric #>> '{followup_resilience_evidence,quote}',
        qi.fixed_rubric #>> '{followup_resilience_evidence,rationale}',
        qi.fixed_rubric ->> 'consistency_label',
        qi.fixed_rubric #>> '{consistency_evidence,quote}',
        qi.fixed_rubric #>> '{consistency_evidence,rationale}',
        qi.model_id,
        qi.prompt_version
      from question_instance qi
      where jsonb_typeof(qi.fixed_rubric) = 'object'
        and qi.model_id is not null
        and qi.prompt_version is not null
        and qi.fixed_rubric ->> 'consistency_label' is not null
        and qi.fixed_rubric #>> '{consistency_evidence,quote}' is not null
        and qi.fixed_rubric #>> '{consistency_evidence,rationale}' is not null
      on conflict (question_instance_id) do nothing
    $backfill$;
  end if;
end
$$;

create index if not exists question_rubric_assessment_question_idx
  on question_rubric_assessment (question_instance_id);

comment on table question_rubric_assessment is
  'Validated score-answer.v2 measurements and evidence for one completed answer.';
comment on column question_rubric_assessment.model_id is
  'Gemini model that produced this assessment.';
comment on column question_rubric_assessment.prompt_version is
  'Registry prompt version used to produce this assessment.';

alter table question_rubric_assessment enable row level security;
