"""Build and score the Lane 2 → Lane 3 post-call handoff."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from shared.interview_scoring import (
    apply_rubric_to_result,
    build_interview_score_row,
    normalize_seniority,
)
from shared.models.interview import IntegrityReport, InterviewPackage, TranscriptTurn
from shared.models.scoring import (
    InterviewResult,
    Recommendation,
    ScoreAnswerInput,
    ScoreInterviewInput,
    ScoringConversationTurn,
    ScoringQuestionType,
    ScoringResumeContext,
)
from shared.post_call_scoring import score_interview
from voice.interview.state_machine import InterviewStateMachine


def build_scoring_input(
    package: InterviewPackage,
    state_machine: InterviewStateMachine,
    transcript: list[TranscriptTurn],
) -> ScoreInterviewInput:
    """Build the canonical one-call scoring request from recorded answers."""
    completed_turns = {
        turn.question_id: turn for turn in state_machine.get_all_turns()
    }
    transcript_by_question: dict[str, list[TranscriptTurn]] = {}
    for turn in transcript:
        if turn.question_id:
            transcript_by_question.setdefault(turn.question_id, []).append(turn)

    prior_answers: list[str] = []
    questions: list[ScoreAnswerInput] = []
    for question in sorted(package.questions, key=lambda item: item.order):
        recorded = completed_turns.get(question.id)
        if recorded is None or not recorded.answer_text.strip():
            continue

        raw_turns = transcript_by_question.get(question.id) or [
            TranscriptTurn(
                speaker="agent",
                text=question.prompt,
                start_ms=recorded.answer_start_ms,
                end_ms=recorded.answer_start_ms,
                question_id=question.id,
            ),
            TranscriptTurn(
                speaker="candidate",
                text=recorded.answer_text,
                start_ms=recorded.answer_start_ms,
                end_ms=recorded.answer_end_ms,
                question_id=question.id,
            ),
        ]

        candidate_has_answered = False
        conversation: list[ScoringConversationTurn] = []
        for turn in raw_turns:
            speaker = "interviewer" if turn.speaker == "agent" else turn.speaker
            if speaker not in ("candidate", "interviewer"):
                continue
            is_follow_up = speaker == "interviewer" and candidate_has_answered
            start_ms = max(0, turn.start_ms)
            conversation.append(
                ScoringConversationTurn(
                    speaker=speaker,
                    text=turn.text,
                    start_ms=start_ms,
                    end_ms=max(start_ms, turn.end_ms),
                    is_follow_up=is_follow_up,
                )
            )
            if speaker == "candidate":
                candidate_has_answered = True

        questions.append(
            ScoreAnswerInput(
                question_id=question.id,
                question=question.prompt,
                question_type=ScoringQuestionType(question.type.value),
                competency=question.competency,
                seniority=normalize_seniority(package.seniority),
                dimensions=question.dimensions,
                resume_context=ScoringResumeContext(
                    relevant_claims=[package.resume_summary]
                    if package.resume_summary.strip()
                    else [],
                    central_to_role=question.must_have,
                ),
                conversation=conversation,
                prior_relevant_claims=prior_answers[-3:],
            )
        )
        prior_answers.append(recorded.answer_text)
        prior_answers.extend(recorded.followup_answers)

    return ScoreInterviewInput(
        interview_id=package.interview_id,
        questions=questions,
    )


async def run_postcall_pipeline(
    package: InterviewPackage,
    state_machine: InterviewStateMachine,
    transcript: list[TranscriptTurn],
    integrity: IntegrityReport,
    application_id: str,
) -> tuple[InterviewResult, ScoreInterviewInput]:
    """Score all recorded questions once and apply deterministic aggregation."""
    scoring_input = build_scoring_input(package, state_machine, transcript)
    answers, holistic = await asyncio.to_thread(score_interview, scoring_input)
    must_have_ids = {question.id for question in package.questions if question.must_have}
    hard_gate = any(
        answer.question_id in must_have_ids and answer.weighted_score <= 2
        for answer in answers
    )
    result = InterviewResult(
        interview_id=package.interview_id,
        org_id=package.org_id,
        application_id=application_id,
        job_id=package.job_id,
        seniority=package.seniority,
        answers=answers,
        holistic=holistic,
        role_fit=holistic.score,
        overall=holistic.score,
        recommendation=Recommendation.HOLD,
        hard_gate_applied=hard_gate,
        integrity=integrity,
        transcript_summary=_generate_gist(transcript),
        rubric_version=package.rubric_version,
        scored_at=datetime.now(UTC),
    )
    result = apply_rubric_to_result(result, package.seniority)
    recommendation = (
        Recommendation.ADVANCE
        if result.composite_score is not None
        and result.composite_score >= 70
        and not result.needs_human_review
        else Recommendation.HOLD
    )
    return result.model_copy(update={"recommendation": recommendation}), scoring_input


def build_score_row(result: InterviewResult) -> dict[str, object]:
    return build_interview_score_row(result)


def _generate_gist(transcript: list[TranscriptTurn]) -> str:
    excerpts = []
    for turn in transcript:
        if turn.speaker != "candidate" or turn.question_id is None:
            continue
        text = turn.text.strip()
        excerpts.append(text if len(text) <= 150 else text[:147] + "...")
        if len(excerpts) == 5:
            break
    return " | ".join(excerpts) or "No candidate answers recorded."
