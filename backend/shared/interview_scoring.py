"""Deterministic aggregation for the fixed interview scoring rubric.

Gemini extracts anchored measurements and evidence for each answer. This module
does every consequential calculation in plain Python so the same inputs always
produce the same leaderboard score and review flags.
"""

from collections.abc import Iterable
from statistics import fmean

from shared.models.scoring import (
    AnswerScore,
    ConsistencyLabel,
    InterviewResult,
    OwnershipLevel,
    ReviewReason,
    RubricComposite,
    ScoringQuestionType,
    SeniorityBucket,
)

SENIORITY_WEIGHTS: dict[SeniorityBucket, dict[str, float]] = {
    SeniorityBucket.JUNIOR: {
        "technical_accuracy_score": 0.45,
        "project_depth_score": 0.20,
        "followup_resilience_score": 0.20,
        "consistency_score": 0.15,
    },
    SeniorityBucket.MID: {
        "technical_accuracy_score": 0.35,
        "project_depth_score": 0.30,
        "followup_resilience_score": 0.20,
        "consistency_score": 0.15,
    },
    SeniorityBucket.SENIOR: {
        "technical_accuracy_score": 0.25,
        "project_depth_score": 0.35,
        "followup_resilience_score": 0.25,
        "consistency_score": 0.15,
    },
}

CONSISTENCY_PENALTIES: dict[ConsistencyLabel, int] = {
    ConsistencyLabel.CONSISTENT: 0,
    ConsistencyLabel.VAGUE: 5,
    ConsistencyLabel.UNVERIFIABLE: 3,
    ConsistencyLabel.INFLATED: 15,
}


def normalize_seniority(value: str | SeniorityBucket) -> SeniorityBucket:
    """Map common job labels to one of the rubric's three weight profiles."""
    if isinstance(value, SeniorityBucket):
        return value

    normalized = value.strip().lower().replace("-", " ").replace("_", " ")
    if any(token in normalized for token in ("senior", "lead", "staff", "principal")):
        return SeniorityBucket.SENIOR
    if any(token in normalized for token in ("mid", "intermediate")):
        return SeniorityBucket.MID
    return SeniorityBucket.JUNIOR


def calculate_rubric_composite(
    answers: Iterable[AnswerScore],
    seniority: str | SeniorityBucket,
    *,
    hard_gate_applied: bool = False,
) -> RubricComposite:
    """Calculate v2 component scores, composite, and mandatory review flags."""
    scored_answers = [answer for answer in answers if answer.fixed_rubric is not None]
    if not scored_answers:
        raise ValueError("At least one answer with fixed_rubric measurements is required")

    bucket = normalize_seniority(seniority)
    technical = _mean_present(
        answer.fixed_rubric.technical_accuracy_score for answer in scored_answers
    )
    depth = _mean_present(_adjusted_depth(answer) for answer in scored_answers)
    followup = _mean_present(
        answer.fixed_rubric.followup_resilience_score for answer in scored_answers
    )
    consistency = calculate_consistency_score(scored_answers)

    components = {
        "technical_accuracy_score": technical,
        "project_depth_score": depth,
        "followup_resilience_score": followup,
        "consistency_score": consistency,
    }
    weighted_components = [
        (score, SENIORITY_WEIGHTS[bucket][key])
        for key, score in components.items()
        if score is not None
    ]
    measured_skill_components = (technical, depth, followup)
    if not any(score is not None for score in measured_skill_components):
        raise ValueError("At least one skill dimension must be scored")

    weight_total = sum(weight for _, weight in weighted_components)
    composite = round(
        sum(score * weight for score, weight in weighted_components) / weight_total,
        2,
    )
    reasons = _review_reasons(scored_answers, composite)
    if hard_gate_applied:
        composite = min(composite, 37.5)
        reasons.append(ReviewReason.MUST_HAVE_HARD_GATE)

    return RubricComposite(
        seniority=bucket,
        technical_accuracy_score=technical,
        project_depth_score=depth,
        followup_resilience_score=followup,
        consistency_score=consistency,
        composite_score=composite,
        needs_human_review=bool(reasons),
        review_reasons=reasons,
    )


def apply_rubric_to_result(
    result: InterviewResult,
    seniority: str | SeniorityBucket,
) -> InterviewResult:
    """Return an InterviewResult populated with deterministic v2 aggregates."""
    summary = calculate_rubric_composite(
        result.answers,
        seniority,
        hard_gate_applied=result.hard_gate_applied,
    )
    return result.model_copy(
        update={
            **summary.model_dump(),
            "overall": composite_to_overall(summary.composite_score),
        }
    )


def build_interview_score_row(result: InterviewResult) -> dict[str, object]:
    """Serialize one complete result for insertion into `interview_score`."""
    payload = result.model_dump(mode="json")
    return {
        "org_id": result.org_id,
        "interview_id": result.interview_id,
        "application_id": result.application_id,
        "job_id": result.job_id,
        "overall": result.overall,
        "percentile": result.percentile,
        "recommendation": result.recommendation.value,
        "hard_gate_applied": result.hard_gate_applied,
        "role_fit": result.role_fit,
        "holistic": result.holistic.model_dump(mode="json"),
        "integrity": result.integrity.model_dump(mode="json"),
        "answers": [answer.model_dump(mode="json") for answer in result.answers],
        "rubric_version": result.rubric_version,
        "scored_at": result.scored_at.isoformat(),
        "seniority_bucket": result.seniority.value if result.seniority else None,
        "technical_accuracy_score": result.technical_accuracy_score,
        "project_depth_score": result.project_depth_score,
        "followup_resilience_score": result.followup_resilience_score,
        "consistency_score": result.consistency_score,
        "composite_score": result.composite_score,
        "needs_human_review": result.needs_human_review,
        "review_reasons": [reason.value for reason in result.review_reasons],
        "result": payload,
    }


def calculate_consistency_score(answers: Iterable[AnswerScore]) -> float:
    penalties = sum(
        CONSISTENCY_PENALTIES[answer.fixed_rubric.consistency_label]
        for answer in answers
        if answer.fixed_rubric is not None
    )
    return float(max(0, 100 - penalties))


def composite_to_overall(composite_score: float) -> float:
    """Convert canonical v2 score to the legacy 1-5 contract value."""
    bounded = min(100.0, max(0.0, composite_score))
    return round(1.0 + 4.0 * bounded / 100.0, 2)


def _adjusted_depth(answer: AnswerScore) -> int | None:
    rubric = answer.fixed_rubric
    if rubric is None or rubric.project_depth_score is None:
        return None
    if answer.followed_up and rubric.ownership_level is OwnershipLevel.UNCLEAR:
        return min(49, rubric.project_depth_score)
    return rubric.project_depth_score


def _mean_present(values: Iterable[int | None]) -> float | None:
    present = [value for value in values if value is not None]
    return round(fmean(present), 2) if present else None


def _review_reasons(
    answers: list[AnswerScore],
    composite_score: float,
) -> list[ReviewReason]:
    reasons: list[ReviewReason] = []

    if any(
        answer.fixed_rubric.consistency_label is ConsistencyLabel.INFLATED
        and answer.fixed_rubric.central_to_role
        for answer in answers
    ):
        reasons.append(ReviewReason.INFLATED_CENTRAL_CLAIM)

    if any(
        answer.fixed_rubric.followup_resilience_score is not None
        and answer.fixed_rubric.followup_resilience_score < 40
        and answer.fixed_rubric.resume_headline_claim
        for answer in answers
    ):
        reasons.append(ReviewReason.WEAK_HEADLINE_FOLLOWUP)

    if any(
        answer.fixed_rubric.ownership_level is OwnershipLevel.UNCLEAR
        and answer.fixed_rubric.flagship_project
        for answer in answers
    ):
        reasons.append(ReviewReason.UNCLEAR_FLAGSHIP_OWNERSHIP)

    background_count = sum(
        answer.fixed_rubric.question_type is ScoringQuestionType.BACKGROUND for answer in answers
    )
    if composite_score > 80 and background_count / len(answers) >= 0.75:
        reasons.append(ReviewReason.BACKGROUND_HEAVY_HIGH_SCORE)

    return reasons
