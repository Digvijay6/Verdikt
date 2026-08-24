from datetime import UTC, datetime

import pytest

from shared.interview_scoring import (
    apply_rubric_to_result,
    build_interview_score_row,
    calculate_rubric_composite,
    composite_to_overall,
    normalize_seniority,
)
from shared.models.interview import IntegrityReport
from shared.models.scoring import (
    AnswerScore,
    ConsistencyLabel,
    DimensionScore,
    FixedRubricAssessment,
    HolisticScore,
    InterviewResult,
    OwnershipLevel,
    Recommendation,
    ReviewReason,
    RubricEvidence,
    ScoringQuestionType,
    SeniorityBucket,
)


def _answer(
    question_id: str,
    *,
    question_type: ScoringQuestionType = ScoringQuestionType.TECHNICAL,
    technical: int | None = 80,
    depth: int | None = 80,
    ownership: OwnershipLevel | None = OwnershipLevel.MAJOR_CONTRIBUTOR,
    followup: int | None = 80,
    consistency: ConsistencyLabel = ConsistencyLabel.CONSISTENT,
    followed_up: bool = True,
    central_to_role: bool = False,
    resume_headline_claim: bool = False,
    flagship_project: bool = False,
) -> AnswerScore:
    evidence = RubricEvidence(
        quote="I measured the latency before changing the cache policy.",
        rationale="The answer provides a concrete, internally consistent decision.",
    )
    return AnswerScore(
        question_id=question_id,
        dimensions=[
            DimensionScore(
                key="correctness",
                score=80,
                band="strong",
                evidence="I measured the latency before changing the cache policy.",
                rationale="The answer provides a concrete technical decision.",
            )
        ],
        weighted_score=4.0,
        followed_up=followed_up,
        fixed_rubric=FixedRubricAssessment(
            question_type=question_type,
            technical_accuracy_score=technical,
            technical_accuracy_evidence=evidence if technical is not None else None,
            project_depth_score=depth,
            project_depth_evidence=evidence if depth is not None else None,
            ownership_level=ownership,
            ownership_evidence=evidence if ownership is not None else None,
            followup_resilience_score=followup,
            followup_resilience_evidence=evidence if followup is not None else None,
            consistency_label=consistency,
            consistency_evidence=evidence,
            central_to_role=central_to_role,
            resume_headline_claim=resume_headline_claim,
            flagship_project=flagship_project,
        ),
        model_id="gemini-test",
        prompt_version="v2",
    )


def test_mid_level_composite_uses_fixed_weights_and_consistency_penalties() -> None:
    result = calculate_rubric_composite(
        [
            _answer("q1", technical=90, depth=70, followup=80),
            _answer(
                "q2",
                technical=70,
                depth=90,
                followup=60,
                consistency=ConsistencyLabel.INFLATED,
            ),
        ],
        "mid-level",
    )

    assert result.seniority is SeniorityBucket.MID
    assert result.technical_accuracy_score == 80
    assert result.project_depth_score == 80
    assert result.followup_resilience_score == 70
    assert result.consistency_score == 85
    assert result.composite_score == 78.75


def test_unclear_ownership_after_followup_caps_depth_at_49() -> None:
    result = calculate_rubric_composite(
        [
            _answer(
                "q1",
                depth=95,
                ownership=OwnershipLevel.UNCLEAR,
                flagship_project=True,
            )
        ],
        SeniorityBucket.SENIOR,
    )

    assert result.project_depth_score == 49
    assert result.needs_human_review is True
    assert ReviewReason.UNCLEAR_FLAGSHIP_OWNERSHIP in result.review_reasons


def test_claim_review_triggers_are_exposed_even_when_score_is_high() -> None:
    result = calculate_rubric_composite(
        [
            _answer(
                "q1",
                consistency=ConsistencyLabel.INFLATED,
                central_to_role=True,
                followup=35,
                resume_headline_claim=True,
            )
        ],
        "junior",
    )

    assert result.needs_human_review is True
    assert result.review_reasons == [
        ReviewReason.INFLATED_CENTRAL_CLAIM,
        ReviewReason.WEAK_HEADLINE_FOLLOWUP,
    ]


def test_background_heavy_high_score_is_flagged() -> None:
    answers = [
        _answer(f"background-{index}", question_type=ScoringQuestionType.BACKGROUND, technical=90)
        for index in range(3)
    ]
    answers.append(_answer("technical", technical=90))

    result = calculate_rubric_composite(answers, "mid")

    assert result.composite_score == 86.5
    assert ReviewReason.BACKGROUND_HEAVY_HIGH_SCORE in result.review_reasons


def test_seniority_normalization_and_legacy_score_conversion() -> None:
    assert normalize_seniority("Staff Engineer") is SeniorityBucket.SENIOR
    assert normalize_seniority("Intermediate") is SeniorityBucket.MID
    assert normalize_seniority("Graduate") is SeniorityBucket.JUNIOR
    assert composite_to_overall(0) == 1.0
    assert composite_to_overall(50) == 3.0
    assert composite_to_overall(100) == 5.0


def test_fixed_measurement_without_evidence_is_rejected() -> None:
    with pytest.raises(ValueError, match="technical_accuracy_evidence"):
        FixedRubricAssessment(
            question_type=ScoringQuestionType.TECHNICAL,
            technical_accuracy_score=80,
            consistency_evidence=RubricEvidence(
                quote="I used a cache.",
                rationale="The claim is consistent with the answer.",
            ),
        )


def test_apply_rubric_populates_result_and_preserves_hard_gate() -> None:
    result = InterviewResult(
        interview_id="interview-1",
        org_id="org-1",
        application_id="application-1",
        job_id="job-1",
        # All three became required when InterviewResult moved to the 0-100
        # rubric. `seniority` drives the composite weights, so it is not
        # cosmetic — a fixture without it was never scoreable.
        seniority="mid",
        consistency_score=100,
        transcript_summary="Candidate walked through one latency investigation.",
        answers=[_answer("q1", technical=95, depth=95, followup=95)],
        holistic=HolisticScore(
            score=5,
            strengths=[],
            concerns=[],
            representative_quote="I measured the latency.",
            model_id="gemini-test",
            prompt_version="v1",
        ),
        role_fit=5,
        overall=5,
        recommendation=Recommendation.HOLD,
        hard_gate_applied=True,
        integrity=IntegrityReport(score=0, events=[], summary="Clean"),
        rubric_version="v2",
        scored_at=datetime(2026, 8, 23, tzinfo=UTC),
    )

    scored = apply_rubric_to_result(result, "senior")

    assert scored.composite_score == 37.5
    assert scored.overall == 2.5
    assert scored.needs_human_review is True
    assert ReviewReason.MUST_HAVE_HARD_GATE in scored.review_reasons

    row = build_interview_score_row(scored)
    assert row["composite_score"] == 37.5
    assert row["seniority_bucket"] == "senior"
    assert row["review_reasons"] == ["must_have_hard_gate"]
    assert row["result"]["composite_score"] == 37.5
