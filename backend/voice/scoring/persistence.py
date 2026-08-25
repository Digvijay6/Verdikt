"""Persist the normalized Lane 2 → Lane 3 scoring handoff."""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid5

from shared.db import db
from shared.interview_scoring import build_interview_score_row
from shared.models.interview import TranscriptTurn
from shared.models.scoring import AnswerScore, InterviewResult, RubricEvidence, ScoreInterviewInput

PERSISTENCE_NAMESPACE = UUID("34e2a6f1-00c7-4ced-89c2-a10b12296b4f")


def _stable_id(*parts: str) -> str:
    return str(uuid5(PERSISTENCE_NAMESPACE, ":".join(parts)))


def _assessment_row(org_id: str, question_instance_id: str, answer: AnswerScore) -> dict:
    rubric = answer.fixed_rubric

    def evidence(prefix: str, value: RubricEvidence | None) -> dict:
        return {
            f"{prefix}_quote": value.quote if value else None,
            f"{prefix}_rationale": value.rationale if value else None,
        }

    return {
        "id": _stable_id(question_instance_id, "assessment"),
        "org_id": org_id,
        "question_instance_id": question_instance_id,
        "technical_accuracy_score": rubric.technical_accuracy_score,
        **evidence("technical_accuracy", rubric.technical_accuracy_evidence),
        "project_depth_score": rubric.project_depth_score,
        **evidence("project_depth", rubric.project_depth_evidence),
        "ownership_level": rubric.ownership_level.value if rubric.ownership_level else None,
        **evidence("ownership", rubric.ownership_evidence),
        "followup_resilience_score": rubric.followup_resilience_score,
        **evidence("followup_resilience", rubric.followup_resilience_evidence),
        "consistency_label": rubric.consistency_label.value,
        **evidence("consistency", rubric.consistency_evidence),
        "model_id": answer.model_id,
        "prompt_version": answer.prompt_version,
    }


def persist_result(
    package: ScoreInterviewInput,
    result: InterviewResult,
    transcript: list[TranscriptTurn],
    *,
    client: Any | None = None,
) -> None:
    """Write the full score contract plus normalized question evidence."""
    expected_ids = [question.question_id for question in package.questions]
    answer_ids = [answer.question_id for answer in result.answers]
    if answer_ids != expected_ids:
        raise ValueError("Refusing to publish without the complete question set")

    client = client or db()
    existing = (
        client.table("question_instance")
        .select("id,question_id")
        .eq("org_id", result.org_id)
        .eq("interview_id", result.interview_id)
        .execute()
    )
    existing_ids = {row["question_id"]: row["id"] for row in existing.data}
    questions_by_id = {question.question_id: question for question in package.questions}
    question_rows = []
    claim_rows = []
    turn_rows = []
    assessment_rows = []

    for order, answer in enumerate(result.answers, start=1):
        question = questions_by_id[answer.question_id]
        question_instance_id = existing_ids.get(answer.question_id) or _stable_id(
            result.interview_id,
            answer.question_id,
        )
        candidate_text = "\n".join(
            turn.text for turn in question.conversation if turn.speaker == "candidate"
        )
        question_rows.append(
            {
                "id": question_instance_id,
                "org_id": result.org_id,
                "interview_id": result.interview_id,
                "question_id": answer.question_id,
                "order_index": order,
                "question_text": question.question,
                "question_type": question.question_type.value,
                "competency": question.competency,
                "seniority": question.seniority.value,
                "resume_headline_claim": question.resume_context.is_resume_headline_claim,
                "flagship_project": question.resume_context.is_flagship_project,
                "central_to_role": question.resume_context.central_to_role,
                "transcript_segment": candidate_text,
                "dimension_scores": [item.model_dump(mode="json") for item in answer.dimensions],
                "weighted_score": answer.weighted_score,
                "followed_up": answer.followed_up,
                "model_id": answer.model_id,
                "prompt_version": answer.prompt_version,
            }
        )
        for source, claims in (
            ("resume", question.resume_context.relevant_claims),
            ("prior_answer", question.prior_relevant_claims),
        ):
            for claim_index, claim in enumerate(claims):
                claim_rows.append(
                    {
                        "id": _stable_id(question_instance_id, source, str(claim_index)),
                        "org_id": result.org_id,
                        "question_instance_id": question_instance_id,
                        "source": source,
                        "claim_index": claim_index,
                        "claim_text": claim,
                    }
                )
        for turn_index, turn in enumerate(question.conversation):
            turn_rows.append(
                {
                    "id": _stable_id(question_instance_id, "turn", str(turn_index)),
                    "org_id": result.org_id,
                    "question_instance_id": question_instance_id,
                    "turn_index": turn_index,
                    **turn.model_dump(mode="json"),
                }
            )
        assessment_rows.append(_assessment_row(result.org_id, question_instance_id, answer))

    client.table("question_instance").upsert(
        question_rows,
        on_conflict="interview_id,question_id",
    ).execute()
    if claim_rows:
        client.table("question_scoring_claim").upsert(
            claim_rows,
            on_conflict="question_instance_id,source,claim_index",
        ).execute()
    client.table("question_conversation_turn").upsert(
        turn_rows,
        on_conflict="question_instance_id,turn_index",
    ).execute()
    client.table("question_rubric_assessment").upsert(
        assessment_rows,
        on_conflict="question_instance_id",
    ).execute()
    client.table("interview").update(
        {
            "status": "completed",
            "ended_at": result.scored_at.isoformat(),
            "transcript": [turn.model_dump(mode="json") for turn in transcript],
            "result": result.model_dump(mode="json"),
            "overall": result.overall,
            "recommendation": result.recommendation.value,
            "hard_gate_applied": result.hard_gate_applied,
            "role_fit": result.role_fit,
            "holistic": result.holistic.model_dump(mode="json"),
            "integrity": result.integrity.model_dump(mode="json"),
            "rubric_version": result.rubric_version,
            "scored_at": result.scored_at.isoformat(),
        }
    ).eq("org_id", result.org_id).eq("id", result.interview_id).execute()
    # Publish the recruiter-facing row last. If an earlier normalized write
    # fails, Lane 3 cannot observe a partial result on the leaderboard.
    client.table("interview_score").upsert(
        build_interview_score_row(result),
        on_conflict="org_id,interview_id",
    ).execute()
