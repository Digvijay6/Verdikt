"""Score every completed interview for one job with one Gemini call each.

Run from backend/:

    python -m scripts.score_job_interviews --job-id UUID --dry-run
    python -m scripts.score_job_interviews --job-id UUID
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from uuid import UUID, uuid5

from shared.db import db
from shared.interview_scoring import apply_rubric_to_result, build_interview_score_row
from shared.models.interview import IntegrityReport
from shared.models.job import Question
from shared.models.scoring import (
    AnswerScore,
    InterviewResult,
    Recommendation,
    RubricEvidence,
    ScoreAnswerInput,
    ScoreInterviewInput,
    ScoringConversationTurn,
    ScoringQuestionType,
    ScoringResumeContext,
)
from shared.post_call_scoring import score_interview

PIPELINE_NAMESPACE = UUID("9e7fa40d-cf98-40cd-b8b5-64296a055099")


def _stable_id(*parts: str) -> str:
    return str(uuid5(PIPELINE_NAMESPACE, ":".join(parts)))


def _resume_claims(parsed_resume: dict | None) -> list[str]:
    if not parsed_resume:
        return []
    claims = []
    for role in parsed_resume.get("employment") or []:
        heading = " at ".join(filter(None, [role.get("title"), role.get("company")]))
        summary = role.get("summary")
        claims.append(": ".join(filter(None, [heading, summary])))
    skills = parsed_resume.get("skills") or []
    if skills:
        claims.append(f"Skills: {', '.join(skills)}")
    return [claim for claim in claims if claim]


def build_interview_package(
    interview: dict,
    questions: list[Question],
    *,
    seniority: str,
    parsed_resume: dict | None,
) -> ScoreInterviewInput:
    """Assemble one post-call request from persisted transcript and job data."""

    transcript = interview.get("transcript") or []
    turns_by_question: dict[str, list[dict]] = {question.id: [] for question in questions}
    for turn in transcript:
        question_id = turn.get("question_id")
        if question_id in turns_by_question:
            turns_by_question[question_id].append(turn)

    resume_claims = _resume_claims(parsed_resume)
    prior_candidate_answers: list[str] = []
    packages = []
    for question in sorted(questions, key=lambda item: item.order):
        raw_turns = turns_by_question[question.id]
        if not raw_turns:
            raise ValueError(
                f"Interview {interview['id']} has no transcript turns for question {question.id}"
            )

        conversation = []
        candidate_has_answered = False
        for turn in raw_turns:
            speaker = turn.get("speaker")
            normalized_speaker = "interviewer" if speaker == "agent" else speaker
            is_follow_up = bool(turn.get("is_follow_up")) or (
                normalized_speaker == "interviewer" and candidate_has_answered
            )
            conversation.append(
                ScoringConversationTurn(
                    speaker=normalized_speaker,
                    text=turn["text"],
                    start_ms=turn["start_ms"],
                    end_ms=turn["end_ms"],
                    is_follow_up=is_follow_up,
                )
            )
            if normalized_speaker == "candidate":
                candidate_has_answered = True

        packages.append(
            ScoreAnswerInput(
                question_id=question.id,
                question=question.prompt,
                question_type=ScoringQuestionType(question.type.value),
                competency=question.competency,
                seniority=seniority,
                dimensions=question.dimensions,
                resume_context=ScoringResumeContext(
                    relevant_claims=resume_claims,
                    central_to_role=question.must_have,
                ),
                conversation=conversation,
                prior_relevant_claims=prior_candidate_answers[-3:],
            )
        )
        prior_candidate_answers.extend(
            turn.text for turn in conversation if turn.speaker == "candidate"
        )

    return ScoreInterviewInput(interview_id=interview["id"], questions=packages)


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


def _persist_result(package: ScoreInterviewInput, result: InterviewResult) -> None:
    client = db()
    questions_by_id = {question.question_id: question for question in package.questions}
    question_rows = []
    claim_rows = []
    turn_rows = []
    assessment_rows = []

    for order, answer in enumerate(result.answers, start=1):
        question = questions_by_id[answer.question_id]
        question_instance_id = _stable_id(result.interview_id, answer.question_id)
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

    client.table("question_instance").upsert(question_rows, on_conflict="id").execute()
    if claim_rows:
        client.table("question_scoring_claim").upsert(
            claim_rows, on_conflict="question_instance_id,source,claim_index"
        ).execute()
    client.table("question_conversation_turn").upsert(
        turn_rows, on_conflict="question_instance_id,turn_index"
    ).execute()
    client.table("question_rubric_assessment").upsert(
        assessment_rows, on_conflict="question_instance_id"
    ).execute()
    client.table("interview_score").upsert(
        build_interview_score_row(result), on_conflict="org_id,interview_id"
    ).execute()
    client.table("interview").update(
        {
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
    client.table("application").update({"status": "scored"}).eq("org_id", result.org_id).eq(
        "id", result.application_id
    ).execute()


def _require_scoring_schema() -> None:
    try:
        db().table("question_instance").select(
            "question_text,question_type,competency,seniority"
        ).limit(1).execute()
        db().table("question_scoring_claim").select("id").limit(1).execute()
        db().table("question_conversation_turn").select("id").limit(1).execute()
        db().table("question_rubric_assessment").select("id").limit(1).execute()
    except Exception as exc:
        raise SystemExit(
            "Normalized scoring tables are missing. Apply migrations through "
            "20260823111000 before running real scoring."
        ) from exc


def score_job(job_id: str, *, force: bool = False, dry_run: bool = False) -> list[InterviewResult]:
    client = db()
    if not dry_run:
        _require_scoring_schema()
    jobs = (
        client.table("job")
        .select("id,org_id,seniority,question_bank,rubric_version")
        .eq("id", job_id)
        .limit(1)
        .execute()
        .data
    )
    if not jobs:
        raise SystemExit(f"Job {job_id} not found")
    job = jobs[0]
    questions = [Question.model_validate(item) for item in job.get("question_bank") or []]
    if not questions:
        raise SystemExit(f"Job {job_id} has no question bank")

    interviews = (
        client.table("interview")
        .select("id,org_id,application_id,job_id,status,transcript,integrity,hard_gate_applied")
        .eq("org_id", job["org_id"])
        .eq("job_id", job_id)
        .eq("status", "completed")
        .execute()
        .data
    )
    existing = (
        client.table("interview_score")
        .select("interview_id")
        .eq("org_id", job["org_id"])
        .eq("job_id", job_id)
        .execute()
        .data
    )
    scored_ids = {row["interview_id"] for row in existing}

    results = []
    for interview in interviews:
        if interview["id"] in scored_ids and not force:
            continue
        applications = (
            client.table("application")
            .select("id,parsed_resume")
            .eq("org_id", job["org_id"])
            .eq("id", interview["application_id"])
            .limit(1)
            .execute()
            .data
        )
        if not applications:
            raise ValueError(f"Application {interview['application_id']} not found")
        package = build_interview_package(
            interview,
            questions,
            seniority=job["seniority"],
            parsed_resume=applications[0].get("parsed_resume"),
        )
        if dry_run:
            print(f"{interview['id']}: ready with {len(package.questions)} questions")
            continue

        answers, holistic = score_interview(package)
        must_have_ids = {question.id for question in questions if question.must_have}
        hard_gate = bool(interview.get("hard_gate_applied")) or any(
            answer.question_id in must_have_ids and answer.weighted_score <= 2 for answer in answers
        )
        integrity = IntegrityReport.model_validate(
            interview.get("integrity")
            or {"score": 0, "events": [], "summary": "No integrity flags recorded."}
        )
        base = InterviewResult(
            interview_id=interview["id"],
            org_id=job["org_id"],
            application_id=interview["application_id"],
            job_id=job_id,
            answers=answers,
            holistic=holistic,
            role_fit=holistic.score,
            overall=holistic.score,
            recommendation=Recommendation.HOLD,
            hard_gate_applied=hard_gate,
            integrity=integrity,
            rubric_version=job["rubric_version"],
            scored_at=datetime.now(UTC),
        )
        result = apply_rubric_to_result(base, job["seniority"])
        recommendation = (
            Recommendation.ADVANCE
            if result.composite_score >= 70 and not result.needs_human_review
            else Recommendation.HOLD
        )
        result = result.model_copy(update={"recommendation": recommendation})
        _persist_result(package, result)
        results.append(result)
        print(f"{interview['id']}: scored {result.composite_score:.2f}")
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    results = score_job(args.job_id, force=args.force, dry_run=args.dry_run)
    if args.dry_run:
        print(f"Dry run complete for job_id={args.job_id}; database was not changed")
    else:
        print(f"Scored {len(results)} interview(s) for job_id={args.job_id}")


if __name__ == "__main__":
    main()
