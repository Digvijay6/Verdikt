import os
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException

os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "service")
os.environ.setdefault("SUPABASE_JWT_SECRET", "secret")
os.environ.setdefault("GEMINI_API_KEY", "gemini")
os.environ.setdefault("LIVEKIT_URL", "wss://example.livekit.cloud")
os.environ.setdefault("LIVEKIT_API_KEY", "key")
os.environ.setdefault("LIVEKIT_API_SECRET", "secret")
os.environ.setdefault("RESEND_API_KEY", "resend")

from api.routers.insights import (
    _interview_result_from_score_row,
    _legacy_dimension_band,
    _normalize_score_payload,
    build_leaderboard_entries,
    score_to_100,
)
from shared.models.interview import IntegrityReport
from shared.models.scoring import HolisticScore, InterviewResult, Recommendation


def _result(
    application_id: str,
    interview_id: str,
    overall: float,
    *,
    integrity_score: int = 10,
    recommendation: Recommendation = Recommendation.HOLD,
    hard_gate_applied: bool = False,
    composite_score: float | None = None,
    needs_human_review: bool = False,
) -> InterviewResult:
    return InterviewResult(
        interview_id=interview_id,
        org_id="org_1",
        application_id=application_id,
        job_id="job_1",
        seniority="mid",
        answers=[],
        holistic=HolisticScore(
            score=overall,
            strengths=[],
            concerns=[],
            representative_quote="I designed the service boundary.",
            model_id="gemini-test",
            prompt_version="score-holistic.v1",
        ),
        consistency_score=100,
        composite_score=composite_score,
        needs_human_review=needs_human_review,
        overall=overall,
        recommendation=recommendation,
        hard_gate_applied=hard_gate_applied,
        integrity=IntegrityReport(
            score=integrity_score,
            events=[],
            summary="No notable integrity events.",
        ),
        transcript_summary="The candidate discussed service boundaries.",
        rubric_version="rubric.v1",
        scored_at=datetime(2026, 8, 22, tzinfo=UTC),
    )


def test_score_to_100_maps_canonical_score_to_display_score() -> None:
    assert score_to_100(1.0) == 0
    assert score_to_100(3.0) == 50
    assert score_to_100(5.0) == 100
    assert score_to_100(6.0) == 100


def test_legacy_score_metadata_is_added_without_changing_scores() -> None:
    payload = {
        "seniority": "senior",
        "consistency_score": 0,
        "holistic": {"representative_quote": "I measured the baseline."},
        "answers": [{"dimensions": [{"score": 5}, {"score": 2}]}],
    }

    normalized = _normalize_score_payload(payload, {})

    assert normalized["consistency_score"] == 0
    assert normalized["transcript_summary"] == "I measured the baseline."
    assert normalized["answers"][0]["dimensions"][0] == {
        "score": 5,
        "band": "expert",
    }
    assert normalized["answers"][0]["dimensions"][1] == {
        "score": 2,
        "band": "weak",
    }
    assert _legacy_dimension_band(92) == "expert"


def test_build_leaderboard_entries_sorts_and_flags_review_cases() -> None:
    entries = build_leaderboard_entries(
        [
            _result("app_low", "int_low", 2.0),
            _result("app_high_flagged", "int_high_flagged", 4.5, integrity_score=70),
            _result("app_high", "int_high", 4.5),
            _result(
                "app_reject",
                "int_reject",
                3.0,
                recommendation=Recommendation.REJECT,
            ),
        ],
        {
            "app_high": "Ada Lovelace",
            "app_high_flagged": "Grace Hopper",
            "app_low": "Alan Turing",
            "app_reject": "Katherine Johnson",
        },
    )

    assert [entry.candidate_name for entry in entries] == [
        "Ada Lovelace",
        "Grace Hopper",
        "Katherine Johnson",
        "Alan Turing",
    ]
    assert entries[0].score == 88
    assert entries[0].percentile == 100.0
    assert entries[1].flagged is True
    assert entries[2].flagged is True
    assert entries[3].percentile == 25.0


def test_leaderboard_prefers_v2_composite_and_exposes_component_scores() -> None:
    first = _result("app_first", "int_first", 3.0, composite_score=91.5)
    first.technical_accuracy_score = 94
    first.project_depth_score = 88
    first.followup_resilience_score = 90
    first.consistency_score = 95
    first.needs_human_review = True

    entries = build_leaderboard_entries(
        [first, _result("app_second", "int_second", 4.5, composite_score=80)],
        {"app_first": "First", "app_second": "Second"},
    )

    assert [entry.candidate_name for entry in entries] == ["First", "Second"]
    assert entries[0].score == 92
    assert entries[0].composite_score == 91.5
    assert entries[0].technical_accuracy_score == 94
    assert entries[0].flagged is True


def test_leaderboard_rejects_incompatible_score_versions() -> None:
    v1 = _result("app_v1", "int_v1", 4)
    v2 = _result("app_v2", "int_v2", 4, composite_score=75)
    v2.rubric_version = "rubric.v2"

    with pytest.raises(HTTPException) as exc_info:
        build_leaderboard_entries([v1, v2], {})

    assert exc_info.value.status_code == 409


def test_interview_result_from_score_row_uses_full_result_payload() -> None:
    result = _result("app_1", "int_1", 4.0)
    parsed = _interview_result_from_score_row(
        {
            "org_id": "org_1",
            "interview_id": "int_1",
            "application_id": "app_1",
            "job_id": "job_1",
            "result": result.model_dump(mode="json"),
        }
    )

    assert parsed.interview_id == "int_1"
    assert parsed.org_id == "org_1"
    assert parsed.overall == 4.0


def test_interview_result_from_score_row_can_fallback_to_score_columns() -> None:
    parsed = _interview_result_from_score_row(
        {
            "org_id": "org_1",
            "interview_id": "int_1",
            "application_id": "app_1",
            "job_id": "job_1",
            "overall": "4.25",
            "percentile": "75.0",
            "recommendation": "advance",
            "hard_gate_applied": False,
            "role_fit": "4.0",
            "seniority_bucket": "mid",
            "consistency_score": 100,
            "answers": "[]",
            "holistic": {
                "score": 4.0,
                "strengths": ["Clear systems thinking"],
                "concerns": [],
                "representative_quote": "I designed the service boundary.",
                "model_id": "gemini-test",
                "prompt_version": "score-holistic.v1",
            },
            "integrity": {
                "score": 12,
                "events": [],
                "summary": "No notable integrity events.",
            },
            "rubric_version": "rubric.v1",
            "scored_at": "2026-08-22T00:00:00Z",
            "result": None,
        }
    )

    assert parsed.overall == 4.25
    assert parsed.percentile == 75.0
    assert parsed.recommendation is Recommendation.ADVANCE
