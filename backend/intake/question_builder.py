"""ADK workflow: job description -> validated question bank with BARS rubrics.

This is the one genuinely multi-step piece of lane 1, and the only place in the
repo where an agent framework earns its keep (D9).

    SequentialAgent "question_builder"
      1. competency_extractor                 -> state["competencies"]
      2. ParallelAgent "draft"  (concurrent)
           technical_writer                   -> state["technical_questions"]
           behavioral_writer                  -> state["behavioral_questions"]
           poison_writer                      -> state["poison_question"]
      3. rubric_writer                        -> state["draft_bank"]
      4. LoopAgent "validate_and_fix" (max 3)
           validator  [tool: exit_loop]       -> state["validation"]
           reviser                            -> state["draft_bank"]

Worth being clear about what this is and is not: SequentialAgent, ParallelAgent
and LoopAgent contain no model. They are loops and branches expressed as
objects. The *steps* are ours and fixed; only the *content* of each step is
generated. That is what makes the output predictable enough to build on.

DEPRECATION, known and accepted (D22): as of google-adk 2.7.1 these three
classes are deprecated in favour of `google.adk.workflow.Workflow`, an
edge-based graph API. They still work, every tutorial and doc page still uses
them, and `Workflow` cannot yet be an LlmAgent sub-agent — so it is still
settling. Migration is a contained change because it lives entirely behind
`build_workflow()`. Revisit before launch, not before the hackathon.

The bank is generated once per job and every candidate gets the identical set
(D16). Tailoring per candidate would make scores incomparable across the
leaderboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from google.adk.agents import LlmAgent, LoopAgent, ParallelAgent, SequentialAgent
from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.runners import InMemoryRunner
from google.adk.tools import ToolContext
from google.genai import types

from shared import llm
from shared.models.job import Question, QuestionBankStatus

from . import repo

log = logging.getLogger(__name__)

APP_NAME = "question_builder"
MAX_REVISIONS = 3


# --- the loop's exit hatch ------------------------------------------------


def exit_loop(tool_context: ToolContext) -> dict[str, str]:
    """Called by the validator when the bank passes every check.

    Setting `escalate` is ADK's `break`. Without it the loop runs until
    max_iterations, which would burn three full revisions on a bank that was
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
    draft = ParallelAgent(
        name="draft",
        description="Write each question type concurrently.",
        sub_agents=[
            _agent(
                "technical-writer",
                reads=("job_brief", "competencies"),
                output_key="technical_questions",
            ),
            _agent(
                "behavioral-writer",
                reads=("job_brief", "competencies"),
                output_key="behavioral_questions",
            ),
            _agent(
                "poison-writer",
                reads=("job_brief", "competencies"),
                output_key="poison_question",
            ),
        ],
    )

    validate_and_fix = LoopAgent(
        name="validate_and_fix",
        description="Check the bank and repair it until it passes.",
        max_iterations=MAX_REVISIONS,
        sub_agents=[
            _agent(
                "validator",
                reads=("job_brief", "competencies", "draft_bank"),
                output_key="validation",
                tools=[exit_loop],
            ),
            _agent(
                "reviser",
                reads=("job_brief", "competencies", "draft_bank", "validation"),
                output_key="draft_bank",
            ),
        ],
    )

    return SequentialAgent(
        name=APP_NAME,
        description="Turn a job description into a validated question bank.",
        sub_agents=[
            _agent(
                "competency-extractor",
                reads=("job_brief",),
                output_key="competencies",
            ),
            draft,
            _agent(
                "rubric-writer",
                reads=(
                    "job_brief",
                    "competencies",
                    "technical_questions",
                    "behavioral_questions",
                    "poison_question",
                ),
                output_key="draft_bank",
            ),
            validate_and_fix,
        ],
    )


# --- the typed boundary ---------------------------------------------------

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


def parse_bank(raw: Any) -> list[Question]:
    """Validate the workflow's output into Question models.

    ADK works in loose text and JSON in session state; the rest of the system
    works in Pydantic. This is the seam. Anything malformed fails here rather
    than being stored and surfacing later as a broken interview.
    """
    if isinstance(raw, str):
        raw = json.loads(_FENCE.sub("", raw).strip())
    if isinstance(raw, dict):
        raw = raw.get("questions", raw)
    if not isinstance(raw, list):
        raise ValueError(f"Question bank is not a list (got {type(raw).__name__})")

    questions = [Question.model_validate(q) for q in raw]
    if not questions:
        raise ValueError("Question bank is empty")
    return questions


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


async def build_question_bank_async(job_id: str) -> list[Question]:
    job = repo.get_job(job_id)
    if job is None:
        raise ValueError(f"No job {job_id}")

    repo.set_question_bank_status(job_id, QuestionBankStatus.BUILDING)

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
                parts=[types.Part(text="Build the question bank for this role.")],
            ),
        ):
            pass

        final = await runner.session_service.get_session(
            app_name=APP_NAME, user_id=job_id, session_id=session.id
        )
        questions = parse_bank(final.state.get("draft_bank"))
    finally:
        await runner.close()

    # Bump the rubric version: these anchors are what lane 2 scores against, so
    # a new bank means scores are not comparable to the previous one.
    version = _next_version(job.rubric_version)
    repo.save_question_bank(job_id, questions, version)
    log.info("built %d questions for job %s (%s)", len(questions), job_id, version)
    return questions


def _next_version(current: str) -> str:
    match = re.fullmatch(r"v(\d+)", current or "")
    return f"v{int(match.group(1)) + 1}" if match else "v1"


def build_question_bank(job_id: str) -> None:
    """Sync entry point for FastAPI BackgroundTasks.

    Failures are recorded on the job rather than raised — this runs detached
    from the request, so an exception here would otherwise vanish and leave the
    job stuck on `building` forever.
    """
    try:
        asyncio.run(build_question_bank_async(job_id))
    except Exception as exc:
        log.exception("question bank build failed for job %s", job_id)
        repo.set_question_bank_status(
            job_id, QuestionBankStatus.FAILED, error=str(exc)[:500]
        )
