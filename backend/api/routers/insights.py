"""LANE 3 — leaderboard, candidate detail, recruiter chat, outreach.

The chat does not need RAG. A full interview — transcript, per-question scores
with evidence quotes, resume, integrity report — is roughly 10-15k tokens, and
Gemini's context window is 1M. Put the whole thing in the prompt. No embeddings,
no vector store, no chunking, and citations get more accurate rather than less.
"""

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from agents.recruiter_chat import (
    ChatMessage,
    RecruiterChatSession,
    answer_question,
)
from shared.db import db
from shared.models.scoring import InterviewResult

from ..deps import Recruiter, current_recruiter

router = APIRouter(prefix="/insights", tags=["insights"])
log = logging.getLogger(__name__)

CurrentRecruiter = Annotated[Recruiter, Depends(current_recruiter)]
DbClient = Annotated[Any, Depends(db)]

INTERVIEW_SCORE_SELECT = (
    "id,org_id,interview_id,application_id,job_id,overall,display_score,"
    "percentile,recommendation,hard_gate_applied,role_fit,holistic,integrity,"
    "answers,rubric_version,scored_at,seniority_bucket,technical_accuracy_score,"
    "project_depth_score,followup_resilience_score,consistency_score,composite_score,"
    "needs_human_review,review_reasons,result"
)
INTERVIEW_SELECT = "id,org_id,application_id,job_id,status"
APPLICATION_SELECT = "id,org_id,candidate_id"
CANDIDATE_SELECT = "id,org_id,full_name,email"
CHAT_SESSION_SELECT = "id,org_id,interview_id,recruiter_id,messages,created_at,updated_at"


class RecruiterChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2_000)


class LeaderboardEntry(BaseModel):
    application_id: str
    interview_id: str
    candidate_name: str
    score: int = Field(
        ge=0,
        le=100,
        description="Rubric v2 composite, with a converted v1 fallback.",
    )
    overall: float
    composite_score: float | None = None
    technical_accuracy_score: float | None = None
    project_depth_score: float | None = None
    followup_resilience_score: float | None = None
    consistency_score: float | None = None
    percentile: float | None
    recommendation: str
    integrity_score: int
    flagged: bool
    review_reasons: list[str] = Field(default_factory=list)


def score_to_100(overall: float) -> int:
    """Convert the canonical 1-5 interview score into a recruiter-facing 0-100."""
    bounded = min(5.0, max(1.0, overall))
    return round(((bounded - 1.0) / 4.0) * 100)


def build_leaderboard_entries(
    results: list[InterviewResult],
    candidate_names: dict[str, str],
) -> list[LeaderboardEntry]:
    """Build a within-job leaderboard from completed interview results."""
    _ensure_comparable_results(results)
    sorted_results = sorted(
        results,
        key=lambda result: (
            -_ranking_score(result),
            result.integrity.score,
            result.scored_at,
            result.application_id,
        ),
    )
    percentiles = _percentiles_by_interview_id(sorted_results)

    return [
        LeaderboardEntry(
            application_id=result.application_id,
            interview_id=result.interview_id,
            candidate_name=candidate_names.get(
                result.application_id,
                _fallback_candidate_name(result.application_id),
            ),
            score=round(_ranking_score(result)),
            overall=round(result.overall, 2),
            composite_score=result.composite_score,
            technical_accuracy_score=result.technical_accuracy_score,
            project_depth_score=result.project_depth_score,
            followup_resilience_score=result.followup_resilience_score,
            consistency_score=result.consistency_score,
            percentile=result.percentile
            if result.percentile is not None
            else percentiles.get(result.interview_id),
            recommendation=result.recommendation,
            integrity_score=result.integrity.score,
            flagged=_needs_human_review(result),
            review_reasons=_review_reasons(result),
        )
        for result in sorted_results
    ]


@router.get("/leaderboard", response_model=list[LeaderboardEntry])
def leaderboard(
    job_id: str,
    recruiter: CurrentRecruiter,
    client: DbClient,
) -> list[LeaderboardEntry]:
    """Ranked within one job only. Scores are not comparable across jobs —
    different rubrics, different weights, sometimes different models."""
    rows = _query_rows(
        client.table("interview_score")
        .select(INTERVIEW_SCORE_SELECT)
        .eq("org_id", recruiter.org_id)
        .eq("job_id", job_id)
    )
    results = [_interview_result_from_score_row(row) for row in rows]
    candidate_names = _candidate_names_by_application_id(
        client,
        recruiter.org_id,
        [result.application_id for result in results],
    )
    return build_leaderboard_entries(results, candidate_names)


@router.get("/interviews/{interview_id}", response_model=InterviewResult)
def interview_detail(
    interview_id: str,
    recruiter: CurrentRecruiter,
    client: DbClient,
) -> InterviewResult:
    return _interview_result_for_org(client, recruiter.org_id, interview_id)


@router.get(
    "/interviews/{interview_id}/chat",
    response_model=RecruiterChatSession,
)
def recruiter_chat_history(
    interview_id: str,
    recruiter: CurrentRecruiter,
    client: DbClient,
) -> RecruiterChatSession:
    """Return this recruiter's persisted conversation for one interview."""
    _interview_result_for_org(client, recruiter.org_id, interview_id)
    row = _chat_session_row(client, recruiter.org_id, recruiter.id, interview_id)
    return RecruiterChatSession(
        session_id=row.get("id") if row else None,
        interview_id=interview_id,
        messages=_chat_messages(row),
    )


@router.post(
    "/interviews/{interview_id}/chat",
    response_model=RecruiterChatSession,
)
async def recruiter_chat(
    interview_id: str,
    request: RecruiterChatRequest,
    recruiter: CurrentRecruiter,
    client: DbClient,
) -> RecruiterChatSession:
    """Ask Gemini to explain a score from the complete stored dossier."""
    result = _interview_result_for_org(client, recruiter.org_id, interview_id)
    row = _chat_session_row(client, recruiter.org_id, recruiter.id, interview_id)
    history = _chat_messages(row)
    dossier = _build_chat_dossier(client, recruiter.org_id, result)

    try:
        answer, provenance = await answer_question(
            recruiter_id=recruiter.id,
            dossier=dossier,
            history=history,
            question=request.message,
        )
    except Exception as exc:
        log.exception("Recruiter chat failed for interview %s", interview_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The score assistant could not answer right now",
        ) from exc

    now = datetime.now(UTC)
    messages = [
        *history,
        ChatMessage(role="user", content=request.message, created_at=now),
        ChatMessage(
            role="assistant",
            content=answer,
            created_at=now,
            model_id=provenance.model_id,
            prompt_version=provenance.prompt_version,
        ),
    ]
    payload = [message.model_dump(mode="json") for message in messages]

    try:
        if row:
            response = (
                client.table("recruiter_chat_session")
                .update({"messages": payload})
                .eq("org_id", recruiter.org_id)
                .eq("id", row["id"])
                .execute()
            )
        else:
            response = (
                client.table("recruiter_chat_session")
                .insert(
                    {
                        "org_id": recruiter.org_id,
                        "interview_id": interview_id,
                        "recruiter_id": recruiter.id,
                        "messages": payload,
                    }
                )
                .execute()
            )
    except Exception as exc:
        log.exception("Could not persist recruiter chat for interview %s", interview_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not save recruiter chat",
        ) from exc

    saved = (response.data or [None])[0]
    return RecruiterChatSession(
        session_id=(saved or row or {}).get("id"),
        interview_id=interview_id,
        messages=messages,
    )


def _interview_result_for_org(
    client: Any,
    org_id: str,
    interview_id: str,
) -> InterviewResult:
    rows = _query_rows(
        client.table("interview_score")
        .select(INTERVIEW_SCORE_SELECT)
        .eq("org_id", org_id)
        .eq("interview_id", interview_id)
        .limit(1)
    )
    if rows:
        return _interview_result_from_score_row(rows[0])

    interview_rows = _query_rows(
        client.table("interview")
        .select(INTERVIEW_SELECT)
        .eq("org_id", org_id)
        .eq("id", interview_id)
        .limit(1)
    )
    if not interview_rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Interview not found",
        )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Interview result not available yet",
    )


def _chat_session_row(
    client: Any,
    org_id: str,
    recruiter_id: str,
    interview_id: str,
) -> dict[str, Any] | None:
    rows = _query_rows(
        client.table("recruiter_chat_session")
        .select(CHAT_SESSION_SELECT)
        .eq("org_id", org_id)
        .eq("interview_id", interview_id)
        .eq("recruiter_id", recruiter_id)
        .order("created_at", desc=True)
        .limit(1)
    )
    return rows[0] if rows else None


def _chat_messages(row: dict[str, Any] | None) -> list[ChatMessage]:
    if not row:
        return []
    raw_messages = _json_value(row.get("messages"), [])
    try:
        return [ChatMessage.model_validate(message) for message in raw_messages]
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored recruiter chat has an invalid shape",
        ) from exc


def _build_chat_dossier(
    client: Any,
    org_id: str,
    result: InterviewResult,
) -> dict[str, Any]:
    interview = _first_row(
        _query_rows(
            client.table("interview")
            .select("id,org_id,application_id,job_id,status,transcript,started_at,ended_at")
            .eq("org_id", org_id)
            .eq("id", result.interview_id)
            .limit(1)
        )
    )
    application = _first_row(
        _query_rows(
            client.table("application")
            .select("id,org_id,job_id,candidate_id,parsed_resume,screening,hard_checks")
            .eq("org_id", org_id)
            .eq("id", result.application_id)
            .limit(1)
        )
    )
    job = _first_row(
        _query_rows(
            client.table("job")
            .select("id,org_id,title,seniority,jd_text,rubric,rubric_version")
            .eq("org_id", org_id)
            .eq("id", result.job_id)
            .limit(1)
        )
    )
    question_rows = _query_rows(
        client.table("question_instance")
        .select(
            "id,question_id,order_index,question_text,question_type,competency,"
            "seniority,resume_headline_claim,flagship_project,central_to_role,"
            "transcript_segment,followed_up"
        )
        .eq("org_id", org_id)
        .eq("interview_id", result.interview_id)
        .order("order_index")
    )
    question_ids = [row["id"] for row in question_rows]
    turns = (
        _query_rows(
            client.table("question_conversation_turn")
            .select(
                "question_instance_id,turn_index,speaker,text,start_ms,end_ms,is_follow_up"
            )
            .eq("org_id", org_id)
            .in_("question_instance_id", question_ids)
            .order("turn_index")
        )
        if question_ids
        else []
    )
    claims = (
        _query_rows(
            client.table("question_scoring_claim")
            .select("question_instance_id,source,claim_index,claim_text")
            .eq("org_id", org_id)
            .in_("question_instance_id", question_ids)
            .order("claim_index")
        )
        if question_ids
        else []
    )

    turns_by_question: dict[str, list[dict[str, Any]]] = {}
    for turn in turns:
        turns_by_question.setdefault(turn["question_instance_id"], []).append(turn)
    claims_by_question: dict[str, list[dict[str, Any]]] = {}
    for claim in claims:
        claims_by_question.setdefault(claim["question_instance_id"], []).append(claim)
    scores_by_question = {
        answer.question_id: answer.model_dump(mode="json") for answer in result.answers
    }

    questions = []
    for row in question_rows:
        questions.append(
            {
                **{key: value for key, value in row.items() if key != "id"},
                "conversation": turns_by_question.get(row["id"], []),
                "claims": claims_by_question.get(row["id"], []),
                "assessment": scores_by_question.get(row.get("question_id")),
            }
        )

    parsed_resume = _json_value(application.get("parsed_resume"), {})
    resume = _resume_without_direct_identifiers(parsed_resume)
    score_payload = result.model_dump(mode="json")
    return {
        "interview": interview,
        "job": job,
        "resume": resume,
        "screening": {
            "hard_checks": _json_value(application.get("hard_checks"), []),
            "assessment": _json_value(application.get("screening"), None),
        },
        "score_summary": score_payload,
        "review_signals": {
            "needs_human_review": result.needs_human_review,
            "review_reasons": [str(reason) for reason in result.review_reasons],
            "hard_gate_applied": result.hard_gate_applied,
            "integrity": result.integrity.model_dump(mode="json"),
        },
        "questions": questions,
    }


def _resume_without_direct_identifiers(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    excluded = {"full_name", "email", "phone", "location"}
    return {key: item for key, item in value.items() if key not in excluded}


def _first_row(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return rows[0] if rows else {}


def _percentiles_by_interview_id(
    results: list[InterviewResult],
) -> dict[str, float]:
    if not results:
        return {}

    scores = [_ranking_score(result) for result in results]
    return {
        result.interview_id: round(
            100 * sum(score <= _ranking_score(result) for score in scores) / len(scores),
            1,
        )
        for result in results
    }


def _needs_human_review(result: InterviewResult) -> bool:
    return (
        result.needs_human_review
        or result.integrity.score >= 60
        or result.hard_gate_applied
        or result.recommendation == "reject"
    )


def _review_reasons(result: InterviewResult) -> list[str]:
    reasons = [str(reason) for reason in result.review_reasons]
    if result.integrity.score >= 60:
        reasons.append("integrity_flag")
    if result.hard_gate_applied:
        reasons.append("must_have_hard_gate")
    if result.recommendation == "reject":
        reasons.append("rejection_requires_human_review")
    return list(dict.fromkeys(reasons))


def _ranking_score(result: InterviewResult) -> float:
    if result.composite_score is not None:
        return result.composite_score
    return float(score_to_100(result.overall))


def _ensure_comparable_results(results: list[InterviewResult]) -> None:
    signatures = {_comparison_signature(result) for result in results}
    if len(signatures) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Leaderboard contains scores from incompatible rubric or model versions",
        )


def _comparison_signature(result: InterviewResult) -> tuple[object, ...]:
    provenance = tuple(
        sorted({(answer.model_id, answer.prompt_version) for answer in result.answers})
    )
    scoring_contract = "v2" if result.composite_score is not None else "v1"
    return (scoring_contract, result.rubric_version, provenance)


def _interview_result_from_score_row(row: dict[str, Any]) -> InterviewResult:
    payload = row.get("result") or _result_payload_from_score_columns(row)
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Stored interview result is not valid JSON",
            ) from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored interview result has an invalid shape",
        )

    payload = {
        **payload,
        "interview_id": payload.get("interview_id") or row.get("interview_id"),
        "org_id": payload.get("org_id") or row.get("org_id"),
        "application_id": payload.get("application_id") or row.get("application_id"),
        "job_id": payload.get("job_id") or row.get("job_id"),
    }
    try:
        return InterviewResult.model_validate(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stored interview result does not match the scoring contract",
        ) from exc


def _result_payload_from_score_columns(row: dict[str, Any]) -> dict[str, Any]:
    """Build an InterviewResult payload from normalized score columns.

    New rows store the full `result` JSON. This fallback keeps the reader useful
    for hand-seeded rows and SQL debugging where only the summary columns were
    inserted.
    """
    return {
        "interview_id": row.get("interview_id"),
        "org_id": row.get("org_id"),
        "application_id": row.get("application_id"),
        "job_id": row.get("job_id"),
        "answers": _json_value(row.get("answers"), []),
        "holistic": _json_value(row.get("holistic"), None),
        "role_fit": row.get("role_fit"),
        "seniority": row.get("seniority_bucket"),
        "technical_accuracy_score": row.get("technical_accuracy_score"),
        "project_depth_score": row.get("project_depth_score"),
        "followup_resilience_score": row.get("followup_resilience_score"),
        "consistency_score": row.get("consistency_score"),
        "composite_score": row.get("composite_score"),
        "needs_human_review": row.get("needs_human_review") or False,
        "review_reasons": _json_value(row.get("review_reasons"), []),
        "overall": row.get("overall"),
        "percentile": row.get("percentile"),
        "recommendation": row.get("recommendation"),
        "hard_gate_applied": row.get("hard_gate_applied") or False,
        "integrity": _json_value(row.get("integrity"), None),
        "rubric_version": row.get("rubric_version"),
        "scored_at": row.get("scored_at"),
    }


def _candidate_names_by_application_id(
    client: Any,
    org_id: str,
    application_ids: list[str],
) -> dict[str, str]:
    unique_application_ids = sorted(set(application_ids))
    if not unique_application_ids:
        return {}

    applications = _query_rows(
        client.table("application")
        .select(APPLICATION_SELECT)
        .eq("org_id", org_id)
        .in_("id", unique_application_ids)
    )
    candidate_ids = sorted(
        {
            application["candidate_id"]
            for application in applications
            if application.get("candidate_id")
        }
    )
    if not candidate_ids:
        return {}

    candidates = _query_rows(
        client.table("candidate")
        .select(CANDIDATE_SELECT)
        .eq("org_id", org_id)
        .in_("id", candidate_ids)
    )
    candidates_by_id = {candidate["id"]: candidate for candidate in candidates}

    names_by_application_id: dict[str, str] = {}
    for application in applications:
        candidate = candidates_by_id.get(application.get("candidate_id"))
        if candidate:
            names_by_application_id[application["id"]] = _candidate_display_name(candidate)
    return names_by_application_id


def _candidate_display_name(candidate: dict[str, Any]) -> str:
    return (
        candidate.get("full_name")
        or candidate.get("email")
        or _fallback_candidate_name(candidate.get("id", ""))
    )


def _fallback_candidate_name(identifier: str) -> str:
    short_id = identifier[:8] if identifier else "unknown"
    return f"Candidate {short_id}"


def _query_rows(query: Any) -> list[dict[str, Any]]:
    try:
        response = query.execute()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not read insights data",
        ) from exc
    return response.data or []


def _json_value(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value
