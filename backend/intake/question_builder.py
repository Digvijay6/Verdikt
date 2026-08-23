"""ADK workflow: job description -> validated scoring rubric with BARS anchors.

This is the one genuinely multi-step piece of lane 1, and the only place in the
repo where an agent framework earns its keep (D9).

    SequentialAgent "question_builder"
      1. competency_extractor                 -> state["competencies"]
      2. rubric_writer                        -> state["draft_rubric"]
      3. LoopAgent "validate_and_fix" (max 3)
           validator  [tool: exit_loop]       -> state["validation"]
           reviser                            -> state["draft_rubric"]

    It builds the *scoring frame*, not the questions. Probes are written per
    candidate from this rubric plus their resume (intake/questions.py), so two
    people are asked different things and scored on the same scale.

Worth being clear about what this is and is not: SequentialAgent and LoopAgent
contain no model. They are loops and branches expressed as objects. The *steps*
are ours and fixed; only the *content* of each step is generated. That is what
makes the output predictable enough to build on.

DEPRECATION, known and accepted (D22): as of google-adk 2.7.1 these classes are
deprecated in favour of `google.adk.workflow.Workflow`, an
edge-based graph API. They still work, every tutorial and doc page still uses
them, and `Workflow` cannot yet be an LlmAgent sub-agent — so it is still
settling. Migration is a contained change because it lives entirely behind
`build_workflow()`. Revisit before launch, not before the hackathon.

The rubric is built once per job and never varies between candidates (D40). The
questions do vary — the invariant a leaderboard needs is the scoring frame, not
the wording of what was asked.

The anchors this produces must be *portable*: scorable without knowing which
probe produced the answer. "Explains a specific failure mode and how they
handled it" works for a notification consumer and a payment consumer alike;
"mentions idempotency keys" only works for one, and would mark the other down
for a correct answer about their own system. That constraint is the whole risk
of the design and it lands here, in the writer and validator prompts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from google.adk.agents import LlmAgent, LoopAgent, SequentialAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.genai import types

from shared import llm
from shared.models.job import JobRubric, QuestionBankStatus

from . import repo

log = logging.getLogger(__name__)

APP_NAME = "question_builder"
MAX_REVISIONS = 3


# --- the loop's exit hatch ------------------------------------------------


def exit_loop(tool_context: ToolContext) -> dict[str, str]:
    """Called by the validator when the rubric passes every check.

    Setting `escalate` is ADK's `break`. Without it the loop runs until
    max_iterations, which would burn three full revisions on a rubric that was
    already correct after the first.
    """
    tool_context.actions.escalate = True
    return {"status": "validated"}


# --- agent construction ---------------------------------------------------


def _instruction(task: str, *state_keys: str):
    """Build an agent's instruction from its prompt file plus named state.

    Deliberately a callable rather than a plain string. ADK substitutes `{key}`
    in string instructions from session state, which would mangle any prompt
    that shows a JSON example — and most of these do. Assembling the text here
    sidesteps brace-escaping entirely.
    """

    def provider(ctx: ReadonlyContext) -> str:
        parts = [llm.prompt_text(f"question-builder.{task}")]
        for key in state_keys:
            value = ctx.state.get(key)
            if value:
                rendered = (
                    json.dumps(value, indent=2)
                    if not isinstance(value, str)
                    else value
                )
                parts.append(f"\n## {key}\n\n{rendered}")
        return "\n".join(parts)

    return provider


def _agent(
    task: str,
    *,
    reads: tuple[str, ...],
    output_key: str,
    tools: list | None = None,
) -> LlmAgent:
    """One sub-agent. Model comes from llm/registry.json like everything else,
    so changing it stays a config edit (D5, D21)."""
    return LlmAgent(
        name=task.replace("-", "_"),
        model=llm.task_config(f"question-builder.{task}").model,
        instruction=_instruction(task, *reads),
        output_key=output_key,
        tools=tools or [],
    )


def build_workflow() -> SequentialAgent:
    validate_and_fix = LoopAgent(
        name="validate_and_fix",
        description="Check the rubric and repair it until it passes.",
        max_iterations=MAX_REVISIONS,
        sub_agents=[
            _agent(
                "validator",
                reads=("job_brief", "competencies", "draft_rubric"),
                output_key="validation",
                tools=[exit_loop],
            ),
            _agent(
                "reviser",
                reads=("job_brief", "competencies", "draft_rubric", "validation"),
                output_key="draft_rubric",
            ),
        ],
    )

    return SequentialAgent(
        name=APP_NAME,
        description="Turn a job description into a validated scoring rubric.",
        sub_agents=[
            _agent(
                "competency-extractor",
                reads=("job_brief",),
                output_key="competencies",
            ),
            _agent(
                "rubric-writer",
                reads=("job_brief", "competencies"),
                output_key="draft_rubric",
            ),
            validate_and_fix,
        ],
    )


# --- the typed boundary ---------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_rubric(raw: Any) -> JobRubric:
    """Validate the workflow's output into a JobRubric.

    ADK works in loose text and JSON in session state; the rest of the system
    works in Pydantic. This is the seam. Anything malformed fails here rather
    than being stored and surfacing later as an unscoreable interview.
    """
    if isinstance(raw, str):
        raw = json.loads(_FENCE.sub("", raw).strip())
    if isinstance(raw, list):
        raw = {"competencies": raw}
    if not isinstance(raw, dict):
        raise ValueError(f"Rubric is not an object (got {type(raw).__name__})")

    rubric = JobRubric.model_validate(raw)
    if not rubric.competencies:
        raise ValueError("Rubric has no competencies")

    keys = [c.key for c in rubric.competencies]
    if len(set(keys)) != len(keys):
        raise ValueError(f"Rubric has duplicate competency keys: {keys}")

    # `poison` is reserved: intake/questions.py uses it to mark the probe that
    # is scored on integrity rather than on a competency, and a real competency
    # by that name would silently lose its anchors.
    if "poison" in keys:
        raise ValueError("'poison' is a reserved competency key")

    for competency in rubric.competencies:
        if not competency.dimensions:
            raise ValueError(f"Competency {competency.key!r} has no dimensions")

    return rubric


def _job_brief(job) -> str:
    p = job.screening_profile
    lines = [
        f"Title: {job.title}",
        f"Seniority: {job.seniority}",
    ]
    if job.role_family:
        lines.append(f"Role family: {job.role_family}")
    if p.required_skills:
        lines.append(f"Required skills: {', '.join(p.required_skills)}")
    if p.preferred_skills:
        lines.append(f"Preferred skills: {', '.join(p.preferred_skills)}")
    lines.append("\nJob description:\n" + job.jd_text)
    return "\n".join(lines)


async def build_rubric_async(job_id: str, org_id: str) -> JobRubric:
    job = repo.get_job(job_id, org_id)
    if job is None:
        raise ValueError(f"No job {job_id}")

    repo.set_question_bank_status(job_id, org_id, QuestionBankStatus.BUILDING)

    runner = InMemoryRunner(agent=build_workflow(), app_name=APP_NAME)
    try:
        session = await runner.session_service.create_session(
            app_name=APP_NAME,
            user_id=job_id,
            state={"job_brief": _job_brief(job)},
        )

        # Drain the event stream. The workflow's product lives in session state,
        # not in the events, so there is nothing to collect here — but the
        # generator has to be consumed for the run to proceed.
        async for _ in runner.run_async(
            user_id=job_id,
            session_id=session.id,
            new_message=types.Content(
                role="user",
                parts=[types.Part(text="Build the scoring rubric for this role.")],
            ),
        ):
            pass

        final = await runner.session_service.get_session(
            app_name=APP_NAME, user_id=job_id, session_id=session.id
        )
        rubric = parse_rubric(final.state.get("draft_rubric"))
    finally:
        await runner.close()

    # Bump the rubric version: these anchors are what lane 2 scores against, so
    # a rebuilt rubric means scores are not comparable to the previous one.
    rubric.version = _next_version(job.rubric_version)
    repo.save_rubric(job_id, org_id, rubric)
    log.info(
        "built rubric for job %s: %d competencies (%s)",
        job_id,
        len(rubric.competencies),
        rubric.version,
    )
    return rubric


def _next_version(current: str) -> str:
    match = re.fullmatch(r"v(\d+)", current or "")
    return f"v{int(match.group(1)) + 1}" if match else "v1"


def build_rubric(job_id: str, org_id: str) -> None:
    """Sync entry point for FastAPI BackgroundTasks.

    Failures are recorded on the job rather than raised — this runs detached
    from the request, so an exception here would otherwise vanish and leave the
    job stuck on `building` forever.
    """
    try:
        asyncio.run(build_rubric_async(job_id, org_id))
    except Exception as exc:
        log.exception("rubric build failed for job %s", job_id)
        repo.set_question_bank_status(
            job_id, org_id, QuestionBankStatus.FAILED, error=str(exc)[:500]
        )
