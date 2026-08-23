"""Post-call two-pass scorer.

Pass 1: per-answer rubric scoring producing FixedRubricAssessment + DimensionScore.
Pass 2: holistic dossier re-score (cross-question patterns).

Both calls go through shared.llm.run() so provenance is captured. Candidate
transcript text is passed as user_content, never in the system prompt.

The LLM extracts measurements and evidence only. The deterministic composite,
consistency aggregation, ownership cap, and review flags are calculated by
shared.interview_scoring — never by the LLM.
"""

from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from shared.llm import run
from shared.models.scoring import (
    AnswerScore,
    ConsistencyLabel,
    DimensionScore,
    FixedRubricAssessment,
    HolisticScore,
    OwnershipLevel,
    RubricEvidence,
    ScoringQuestionType,
)

# --- Gemini response schemas ----------------------------------------------


class DimensionScoreResponse(BaseModel):
    """Question-specific BARS layer (1-5 scale stored as 0-100)."""

    key: str
    score: int = Field(ge=0, le=100)
    band: str
    evidence: str
    rationale: str


class RubricEvidenceResponse(BaseModel):
    quote: str
    rationale: str


class FixedRubricResponse(BaseModel):
    """The v2 fixed rubric measurements extracted by the LLM."""

    question_type: ScoringQuestionType
    technical_accuracy_score: int | None = Field(None, ge=0, le=100)
    technical_accuracy_evidence: RubricEvidenceResponse | None = None
    project_depth_score: int | None = Field(None, ge=0, le=100)
    project_depth_evidence: RubricEvidenceResponse | None = None
    ownership_level: OwnershipLevel | None = None
    ownership_evidence: RubricEvidenceResponse | None = None
    followup_resilience_score: int | None = Field(None, ge=0, le=100)
    followup_resilience_evidence: RubricEvidenceResponse | None = None
    consistency_label: ConsistencyLabel = ConsistencyLabel.CONSISTENT
    consistency_evidence: RubricEvidenceResponse
    central_to_role: bool = False
    resume_headline_claim: bool = False
    flagship_project: bool = False


class AnswerScoreResponse(BaseModel):
    """Full per-answer response: BARS dimensions + fixed rubric."""

    dimensions: list[DimensionScoreResponse]
    weighted_score: float = Field(ge=0.0, le=100.0)
    fixed_rubric: FixedRubricResponse


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
    dimensions_info: str,
) -> str:
    """Format the user content for the scoring LLM.

    Includes the question's BARS dimensions and anchors so the LLM can score
    against them, plus the fixed rubric instructions from the system prompt.
    """
    parts = [
        f"Question: {question_text}",
        f"Question type: {question_type}",
        f"Competency: {competency}",
        f"Seniority: {seniority}",
        f"Resume summary: {resume_summary}",
        f"\nQuestion dimensions and anchors:\n{dimensions_info}",
        f"\nCandidate answer: {answer_text}",
    ]
    if followup_texts:
        for i, fu_answer in enumerate(followup_texts, 1):
            parts.append(f"\nFollow-up answer {i}: {fu_answer}")
    else:
        parts.append("\nNo follow-up was asked.")
    return "\n".join(parts)


def _format_dimensions(dimensions) -> str:
    """Format question dimensions with their BARS anchors for the LLM."""
    lines = []
    for d in dimensions:
        lines.append(f"  {d.key} (weight {d.weight}):")
        for anchor_score, anchor_desc in sorted(d.anchors.items()):
            lines.append(f"    {anchor_score}: {anchor_desc}")
    return "\n".join(lines)


async def score_answer(
    question_text: str,
    question_type: str,
    competency: str,
    seniority: str,
    resume_summary: str,
    answer_text: str,
    followup_answers: list[str] | None = None,
    question_id: str = "",
    dimensions=None,
) -> AnswerScore:
    """Pass 1 — score one answer against the full v2 rubric.

    The LLM produces both the question-specific BARS dimensions and the
    fixed rubric measurements (FixedRubricAssessment). Deterministic
    aggregation happens in shared.interview_scoring, not here.

    Runs in a thread (asyncio.to_thread) so it doesn't block the event loop.
    """
    dimensions_info = _format_dimensions(dimensions) if dimensions else "No dimensions provided."

    user_content = _format_answer_for_judge(
        question_text, question_type, competency, seniority,
        resume_summary, answer_text, followup_answers, dimensions_info,
    )

    result, provenance = await asyncio.to_thread(
        run,
        "score-answer",
        AnswerScoreResponse,
        user_content=user_content,
    )

    # Build DimensionScore list from BARS layer
    dimension_scores = [
        DimensionScore(
            key=d.key,
            score=d.score,
            band=d.band,
            evidence=d.evidence,
            rationale=d.rationale,
        )
        for d in result.dimensions
    ]

    # Build FixedRubricAssessment from v2 layer
    def _evidence(e) -> RubricEvidence | None:
        if e is None:
            return None
        return RubricEvidence(quote=e.quote, rationale=e.rationale)

    fixed_rubric = FixedRubricAssessment(
        question_type=result.fixed_rubric.question_type,
        technical_accuracy_score=result.fixed_rubric.technical_accuracy_score,
        technical_accuracy_evidence=_evidence(
            result.fixed_rubric.technical_accuracy_evidence
        ),
        project_depth_score=result.fixed_rubric.project_depth_score,
        project_depth_evidence=_evidence(
            result.fixed_rubric.project_depth_evidence
        ),
        ownership_level=result.fixed_rubric.ownership_level,
        ownership_evidence=_evidence(
            result.fixed_rubric.ownership_evidence
        ),
        followup_resilience_score=result.fixed_rubric.followup_resilience_score,
        followup_resilience_evidence=_evidence(
            result.fixed_rubric.followup_resilience_evidence
        ),
        consistency_label=result.fixed_rubric.consistency_label,
        consistency_evidence=RubricEvidence(
            quote=result.fixed_rubric.consistency_evidence.quote,
            rationale=result.fixed_rubric.consistency_evidence.rationale,
        ),
        central_to_role=result.fixed_rubric.central_to_role,
        resume_headline_claim=result.fixed_rubric.resume_headline_claim,
        flagship_project=result.fixed_rubric.flagship_project,
    )

    return AnswerScore(
        question_id=question_id,
        dimensions=dimension_scores,
        weighted_score=result.weighted_score,
        followed_up=bool(followup_answers),
        followup_resilience_score=(
            result.fixed_rubric.followup_resilience_score or 0
        ),
        fixed_rubric=fixed_rubric,
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
        if a.fixed_rubric:
            fr = a.fixed_rubric
            lines.append(f"  Technical accuracy: {fr.technical_accuracy_score}")
            lines.append(f"  Project depth: {fr.project_depth_score}")
            lines.append(f"  Ownership: {fr.ownership_level}")
            lines.append(f"  Follow-up resilience: {fr.followup_resilience_score}")
            lines.append(f"  Consistency: {fr.consistency_label}")
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