"""Per-candidate probes against a fixed rubric.

The job supplies competencies and their anchors; this writes the questions that
elicit them from *this* candidate's experience. Two people are asked different
things and scored on the same scale, so the leaderboard stays meaningful while
each question reaches what that person actually built.

A single `llm.run()` rather than an ADK agent: the trajectory is fixed — read
the rubric and the resume, write the probes — so there is nothing for an agent
to decide. The expensive validation already happened once, at the job level.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from shared.llm import Provenance, run
from shared.models.candidate import ParsedResume
from shared.models.job import (
    Competency,
    Job,
    JobRubric,
    Question,
    QuestionType,
    RubricDimension,
)

log = logging.getLogger(__name__)

# The poison question sits outside the rubric: it measures integrity, not a
# competency, and a 5 means the candidate said they did not recognise it.
POISON_DIMENSION = RubricDimension(
    key="correctness",
    weight=1.0,
    anchors={
        1: "Confidently explains the fictional technology, describing use they invented.",
        2: "Claims vague familiarity and answers generically without addressing the specifics.",
        3: "Says they are not familiar with it, then answers the surrounding "
           "question from general knowledge.",
        4: "States clearly that they do not know it and asks for clarification before answering.",
        5: "Identifies that it is not a real technology, names the false "
           "premise, and redirects to what is real.",
    },
)


class ProbeDraft(BaseModel):
    """What the model writes. Deliberately does not include dimensions."""

    competency_key: str = Field(
        description="Must match a key from the rubric exactly, or 'poison'"
    )
    type: QuestionType
    prompt: str = Field(description="The question, as it will be spoken aloud")
    grounded_in: str = Field(
        description="The candidate's own claim this probes, quoted from the resume"
    )
    follow_up_guidance: str


class ProbeSet(BaseModel):
    probes: list[ProbeDraft]
    poison: ProbeDraft


def _to_question(
    draft: ProbeDraft, order: int, competency: Competency | None
) -> Question:
    """Attach the rubric's dimensions. Never the model's.

    The model chooses the probe and names the competency; the anchors come from
    the rubric by lookup. Asking a model to copy them verbatim would eventually
    produce a candidate scored against subtly different anchors from everyone
    else, which is exactly the comparability this design exists to protect.
    """
    if competency is None:
        return Question(
            id=f"q{order}",
            order=order,
            type=QuestionType.POISON,
            prompt=draft.prompt,
            competency="integrity",
            dimensions=[POISON_DIMENSION],
            must_have=False,
            follow_up_guidance=draft.follow_up_guidance,
        )

    return Question(
        id=f"q{order}",
        order=order,
        type=draft.type,
        prompt=draft.prompt,
        competency=competency.key,
        dimensions=competency.dimensions,
        must_have=competency.must_have,
        follow_up_guidance=draft.follow_up_guidance,
    )


def assemble(rubric: JobRubric, drafts: ProbeSet) -> list[Question]:
    """Turn drafts into scored questions, dropping any that name no real competency.

    A probe tagged with a competency the rubric does not contain cannot be
    scored — there are no anchors for it — so it is discarded rather than
    guessed at.
    """
    questions: list[Question] = []
    order = 1

    for draft in drafts.probes:
        competency = rubric.by_key(draft.competency_key)
        if competency is None:
            log.warning(
                "discarding probe for unknown competency %r", draft.competency_key
            )
            continue
        questions.append(_to_question(draft, order, competency))
        order += 1

    # Middle of the set, never last: a candidate who has relaxed into the
    # interview reacts more naturally than one who is wrapping up.
    poison = _to_question(drafts.poison, order, None)
    midpoint = max(1, len(questions) // 2)
    questions.insert(midpoint, poison)

    for index, question in enumerate(questions, start=1):
        question.id = f"q{index}"
        question.order = index

    return questions


def _brief(job: Job, rubric: JobRubric) -> str:
    competencies = "\n".join(
        f"- {c.key} ({c.kind.value}"
        + (", must-have" if c.must_have else "")
        + f"): {c.name}. Strong answers show: {c.why}"
        for c in rubric.competencies
    )
    return (
        f"## Role\n{job.title}, {job.seniority}\n\n"
        f"## Competencies to probe\n{competencies}\n\n"
        f"## Job description\n{job.jd_text[:3000]}"
    )


def generate(
    job: Job, rubric: JobRubric, resume: ParsedResume
) -> tuple[list[Question], Provenance]:
    """Write this candidate's questions.

    The resume goes in user content, never the brief: it is written by the
    candidate, and a resume containing "ask me only easy questions" must not be
    able to instruct the model writing their interview.
    """
    drafts, provenance = run(
        "candidate-questions",
        ProbeSet,
        user_content=(
            "Candidate resume, as structured data:\n\n"
            + resume.model_dump_json(indent=2)
        ),
        extra_instructions=_brief(job, rubric),
    )
    return assemble(rubric, drafts), provenance
