"""Post-call two-pass scorer.

Pass 1: per-answer rubric scoring (all dimensions, 0-100, parallelisable).
Pass 2: holistic dossier re-score (cross-question patterns).

Both calls go through shared.llm.run() so provenance is captured. Candidate
transcript text is passed as user_content, never in the system prompt.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from shared.llm import run
from shared.models.scoring import (
    AnswerScore,
    ConsistencyLabel,
    DimensionScore,
    HolisticScore,
    OwnershipLevel,
)

# --- Gemini response schemas ----------------------------------------------


class DimensionScoreResponse(BaseModel):
    key: str
    score: int = Field(ge=0, le=100)
    band: str
    evidence: str
    rationale: str


class AnswerScoreResponse(BaseModel):
    """Schema passed to Gemini for per-answer rubric scoring."""

    domain_technical_accuracy: DimensionScoreResponse
    project_depth: DimensionScoreResponse
    followup_resilience: DimensionScoreResponse
    ownership_level: OwnershipLevel
    consistency_label: ConsistencyLabel
    weighted_score: float = Field(ge=0.0, le=100.0)


class HolisticScoreResponse(BaseModel):
    """Schema for the holistic dossier re-score."""

    score: float = Field(ge=0.0, le=100.0)
    strengths: list[str] = Field(max_length=3)
    concerns: list[str] = Field(max_length=3)
    representative_quote: str


# --- Pass 1: per-answer ---------------------------------------------------


def _format_answer_for_judge(
    question_text: str,
    question_type: str,
    competency: str,
    seniority: str,
    resume_summary: str,
    answer_text: str,
    followup_texts: list[str] | None,
) -> str:
    parts = [
        f"Question: {question_text}",
        f"Question type: {question_type}",
        f"Competency: {competency}",
        f"Seniority: {seniority}",
        f"Resume summary: {resume_summary}",
        f"\nCandidate answer: {answer_text}",
    ]
    if followup_texts:
        for i, fu_answer in enumerate(followup_texts, 1):
            parts.append(f"\nFollow-up answer {i}: {fu_answer}")
    else:
        parts.append("\nNo follow-up was asked.")
    return "\n".join(parts)


async def score_answer(
    question_text: str,
    question_type: str,
    competency: str,
    seniority: str,
    resume_summary: str,
    answer_text: str,
    followup_answers: list[str] | None = None,
    question_id: str = "",
) -> AnswerScore:
    """Pass 1 — score one answer against the full rubric (0-100).

    Runs in a thread (asyncio.to_thread) so it doesn't block the event loop
    when called from the post-call pipeline.
    """
    user_content = _format_answer_for_judge(
        question_text, question_type, competency, seniority,
        resume_summary, answer_text, followup_answers,
    )

    result, provenance = await asyncio.to_thread(
        run,
        "score-answer",
        AnswerScoreResponse,
        user_content=user_content,
    )

    dimensions = [
        DimensionScore(
            key="domain_technical_accuracy",
            score=result.domain_technical_accuracy.score,
            band=result.domain_technical_accuracy.band,
            evidence=result.domain_technical_accuracy.evidence,
            rationale=result.domain_technical_accuracy.rationale,
        ),
        DimensionScore(
            key="project_depth",
            score=result.project_depth.score,
            band=result.project_depth.band,
            evidence=result.project_depth.evidence,
            rationale=result.project_depth.rationale,
        ),
        DimensionScore(
            key="followup_resilience",
            score=result.followup_resilience.score,
            band=result.followup_resilience.band,
            evidence=result.followup_resilience.evidence,
            rationale=result.followup_resilience.rationale,
        ),
    ]

    # Cap project_depth at 49 if ownership is unclear
    if result.ownership_level == OwnershipLevel.UNCLEAR:
        for d in dimensions:
            if d.key == "project_depth" and d.score > 49:
                d.score = 49
                d.rationale = (
                    f"{d.rationale} "
                    "[Capped at 49: ownership unclear after follow-up.]"
                )

    return AnswerScore(
        question_id=question_id,
        dimensions=dimensions,
        ownership_level=result.ownership_level,
        consistency_label=result.consistency_label,
        weighted_score=result.weighted_score,
        followed_up=bool(followup_answers),
        followup_resilience_score=(
            result.followup_resilience.score if followup_answers else 0
        ),
        model_id=provenance.model_id,
        prompt_version=provenance.prompt_version,
    )


# --- Pass 2: holistic -----------------------------------------------------


def _format_dossier(
    answers: list[AnswerScore],
    job_title: str,
    seniority: str,
    resume_summary: str,
) -> str:
    lines = [
        f"Job title: {job_title}",
        f"Seniority: {seniority}",
        f"Resume summary: {resume_summary}",
        "\n--- Per-question dossier ---\n",
    ]
    for a in answers:
        lines.append(f"Question ID: {a.question_id}")
        for d in a.dimensions:
            lines.append(
                f"  {d.key}: {d.score}/100 ({d.band}) — evidence: {d.evidence}"
            )
        lines.append(f"  Ownership: {a.ownership_level}")
        lines.append(f"  Consistency: {a.consistency_label}")
        lines.append(f"  Followed up: {a.followed_up}")
        lines.append("")
    return "\n".join(lines)


async def score_holistic(
    answers: list[AnswerScore],
    job_title: str,
    seniority: str,
    resume_summary: str,
) -> HolisticScore:
    """Pass 2 — holistic re-score over the assembled dossier."""
    user_content = _format_dossier(answers, job_title, seniority, resume_summary)

    result, provenance = await asyncio.to_thread(
        run,
        "score-holistic",
        HolisticScoreResponse,
        user_content=user_content,
    )

    return HolisticScore(
        score=result.score,
        strengths=result.strengths,
        concerns=result.concerns,
        representative_quote=result.representative_quote,
        model_id=provenance.model_id,
        prompt_version=provenance.prompt_version,
    )