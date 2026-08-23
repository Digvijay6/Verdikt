"""Post-call scoring pipeline — orchestrates Pass 1, Pass 2, and the
deterministic v2 rubric aggregation into a final InterviewResult.

Called from the agent worker on room disconnect.

Flow:
  1. Pass 1: LLM scores each answer (parallel) → AnswerScore with FixedRubricAssessment
  2. Pass 2: LLM holistic dossier re-score → HolisticScore
  3. Deterministic aggregation via shared.interview_scoring.apply_rubric_to_result()
     (seniority weights, consistency penalties, ownership cap, hard gate,
     human-review triggers, composite score)
  4. Serialize via build_interview_score_row() for the interview_score table

The LLM extracts measurements and evidence. The composite, review flags, and
ranking score are computed in plain Python by shared.interview_scoring —
never by the LLM. That is what makes scores reproducible and defensible.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from shared.interview_scoring import (
    apply_rubric_to_result,
    build_interview_score_row,
)
from shared.models.interview import (
    IntegrityReport,
    InterviewPackage,
    TranscriptTurn,
)
from shared.models.scoring import (
    AnswerScore,
    InterviewResult,
    Recommendation,
)
from voice.interview.state_machine import InterviewStateMachine, TurnRecord
from voice.scoring.postcall import score_answer, score_holistic


async def run_postcall_pipeline(
    package: InterviewPackage,
    state_machine: InterviewStateMachine,
    transcript: list[TranscriptTurn],
    integrity: IntegrityReport,
    application_id: str = "",
) -> InterviewResult:
    """Run the full post-call scoring pipeline and return InterviewResult.

    1. Pass 1: score each answer against the v2 rubric (parallel).
    2. Pass 2: holistic re-score over the assembled dossier.
    3. Deterministic aggregation via interview_scoring.apply_rubric_to_result().
    4. Return the completed InterviewResult.
    """
    turns = state_machine.get_all_turns()

    # Pass 1 — per-answer scoring in parallel
    answer_tasks = [
        _score_one_answer(t, package) for t in turns
    ]
    answers = await asyncio.gather(*answer_tasks)

    # Pass 2 — holistic dossier re-score
    holistic = await score_holistic(
        answers=list(answers),
        job_title=package.job_title,
        seniority=package.seniority,
        resume_summary=package.resume_summary,
    )

    # Build the InterviewResult with raw answers + holistic
    # (composite/review flags are added by apply_rubric_to_result below)
    transcript_summary = _generate_gist(transcript)
    hard_gate = _has_hard_gate(list(answers), package)

    # Determine recommendation based on hard gate
    recommendation = Recommendation.HOLD
    if hard_gate:
        recommendation = Recommendation.REJECT

    result = InterviewResult(
        interview_id=package.interview_id,
        org_id=package.org_id,
        application_id=application_id,
        job_id=package.job_id,
        seniority=package.seniority,
        answers=list(answers),
        holistic=holistic,
        consistency_score=100,  # overwritten by apply_rubric_to_result
        overall=3.0,  # overwritten by apply_rubric_to_result
        composite_weights={},
        percentile=None,
        recommendation=recommendation,
        needs_human_review=False,
        human_review_reasons=[],
        hard_gate_applied=hard_gate,
        integrity=integrity,
        transcript_summary=transcript_summary,
        transcript_url="",
        rubric_version=package.rubric_version,
        scored_at=datetime.now(UTC),
    )

    # Deterministic v2 aggregation — this computes:
    #   seniority-weighted composite, consistency penalties, ownership cap,
    #   hard gate cap, human-review triggers, overall (1-5 derived from composite)
    result = apply_rubric_to_result(result, package.seniority)

    return result


def build_score_row(result: InterviewResult) -> dict:
    """Serialize the InterviewResult for insertion into interview_score table.

    This produces the row format that Lane 3 reads for the leaderboard.
    """
    return build_interview_score_row(result)


async def _score_one_answer(
    turn: TurnRecord,
    package: InterviewPackage,
) -> AnswerScore:
    """Score one turn (question + answer + follow-ups) against the v2 rubric."""
    answer = await score_answer(
        question_text=turn.question.prompt,
        question_type=turn.question.type.value,
        competency=turn.question.competency,
        seniority=package.seniority,
        resume_summary=package.resume_summary,
        answer_text=turn.answer_text,
        followup_answers=turn.followup_answers or None,
        question_id=turn.question_id,
        dimensions=turn.question.dimensions,
    )
    return answer


def _has_hard_gate(
    answers: list[AnswerScore],
    package: InterviewPackage,
) -> bool:
    """Check if any must_have question scored below 25 on technical accuracy.

    The hard gate caps the composite at 37.5 (applied in interview_scoring).
    Here we just detect it; the cap is applied deterministically.
    """
    must_have_ids = {
        q.id for q in package.questions if q.must_have
    }
    for a in answers:
        if a.question_id in must_have_ids and a.fixed_rubric:
            if (
                a.fixed_rubric.technical_accuracy_score is not None
                and a.fixed_rubric.technical_accuracy_score < 25
            ):
                return True
    return False


def _generate_gist(transcript: list[TranscriptTurn]) -> str:
    """Generate a short prose gist of the conversation for Lane 3's chat.

    Simple extraction — the first 150 chars of each candidate answer joined.
    Deterministic; no extra LLM call needed.
    """
    candidate_turns = [t for t in transcript if t.speaker == "candidate"]
    if not candidate_turns:
        return "No candidate answers recorded."
    excerpts = []
    for t in candidate_turns[:5]:
        text = t.text.strip()
        if len(text) > 150:
            text = text[:147] + "..."
        excerpts.append(text)
    return " | ".join(excerpts)