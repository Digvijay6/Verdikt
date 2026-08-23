"""Consistency aggregation, composite scoring, and human-review triggers.

The composite formula and weight tables live here — the one place. Do not
inline them in the agent worker or the API router.
"""

from __future__ import annotations

from shared.models.scoring import (
    AnswerScore,
    ConsistencyLabel,
    OwnershipLevel,
)

# --- Weight tables (from the rubric) --------------------------------------

SENIORITY_WEIGHTS: dict[str, dict[str, float]] = {
    "junior": {
        "domain_technical_accuracy": 0.45,
        "project_depth": 0.20,
        "followup_resilience": 0.20,
        "consistency_score": 0.15,
    },
    "mid": {
        "domain_technical_accuracy": 0.35,
        "project_depth": 0.30,
        "followup_resilience": 0.20,
        "consistency_score": 0.15,
    },
    "senior": {
        "domain_technical_accuracy": 0.25,
        "project_depth": 0.35,
        "followup_resilience": 0.25,
        "consistency_score": 0.15,
    },
}

CONSISTENCY_PENALTIES: dict[ConsistencyLabel, int] = {
    ConsistencyLabel.CONSISTENT: 0,
    ConsistencyLabel.VAGUE: 5,
    ConsistencyLabel.UNVERIFIABLE: 3,
    ConsistencyLabel.INFLATED: 15,
}


# --- Consistency aggregation ----------------------------------------------


def aggregate_consistency(answers: list[AnswerScore]) -> int:
    """Aggregate per-answer consistency labels into a 0-100 score.

    consistency_score = max(0, 100 - sum(penalties across all answers))
    """
    penalty = 0
    for a in answers:
        penalty += CONSISTENCY_PENALTIES.get(a.consistency_label, 0)
    return max(0, 100 - penalty)


# --- Composite scoring ----------------------------------------------------


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_composite(
    answers: list[AnswerScore],
    consistency_score: int,
    seniority: str,
) -> tuple[float, dict[str, float]]:
    """Compute the overall composite score using seniority-weighted dimensions.

    Returns (overall, weights_used).
    """
    weights = SENIORITY_WEIGHTS.get(seniority, SENIORITY_WEIGHTS["mid"])

    dta_scores = [
        next(
            (d.score for d in a.dimensions if d.key == "domain_technical_accuracy"),
            0,
        )
        for a in answers
    ]
    pd_scores = [
        next(
            (d.score for d in a.dimensions if d.key == "project_depth"),
            0,
        )
        for a in answers
    ]
    # Only use followup_resilience from questions that were followed up
    fr_scores = [
        a.followup_resilience_score for a in answers if a.followed_up
    ]
    if not fr_scores:
        # If no follow-ups happened, use all resilience scores (will be 0)
        fr_scores = [
            next(
                (d.score for d in a.dimensions if d.key == "followup_resilience"),
                0,
            )
            for a in answers
        ]

    overall = (
        weights["domain_technical_accuracy"] * _mean(dta_scores)
        + weights["project_depth"] * _mean(pd_scores)
        + weights["followup_resilience"] * _mean(fr_scores)
        + weights["consistency_score"] * consistency_score
    )

    return round(overall, 1), weights


# --- Human review triggers ------------------------------------------------


def check_human_review(
    answers: list[AnswerScore],
    composite_score: float,
) -> tuple[bool, list[str]]:
    """Check the rubric's human-review triggers.

    Returns (needs_review, reasons).
    """
    reasons: list[str] = []

    # 1. Any inflated consistency label on a core-role claim
    #    (heuristic: any inflated label counts as core for now)
    if any(a.consistency_label == ConsistencyLabel.INFLATED for a in answers):
        reasons.append(
            "inflated consistency label on a claim central to the role"
        )

    # 2. followup_resilience_score < 40 on a resume-headline claim
    #    (heuristic: any followed_up answer with fr < 40)
    for a in answers:
        if a.followed_up and a.followup_resilience_score < 40:
            reasons.append(
                f"followup resilience {a.followup_resilience_score} < 40 "
                f"on question {a.question_id}"
            )
            break

    # 3. ownership_level = unclear on flagship project
    #    (heuristic: any answer with unclear ownership)
    for a in answers:
        if a.ownership_level == OwnershipLevel.UNCLEAR:
            reasons.append(
                f"unclear ownership on question {a.question_id}"
            )
            break

    # 4. Composite > 80 but mostly background questions
    #    (heuristic: skip for now — we don't have question type here)
    #    This trigger is evaluated in pipeline.py where we have the
    #    InterviewPackage available.

    return len(reasons) > 0, reasons


# --- Recommendation -------------------------------------------------------


def recommend(
    overall: float,
    needs_human_review: bool,
    consistency_score: int,
) -> str:
    """Provisional recommendation. Always advisory — human makes the call."""
    if needs_human_review:
        return "hold"
    if overall >= 70:
        return "advance"
    if overall >= 45:
        return "hold"
    return "reject"