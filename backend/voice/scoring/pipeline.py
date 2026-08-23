"""Post-call scoring pipeline — orchestrates Pass 1, Pass 2, consistency,
composite, and human-review checks into a final InterviewResult.

Called from the agent worker on room disconnect.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from shared.models.interview import (
    IntegrityReport,
    InterviewPackage,
    QuestionType,
    TranscriptTurn,
)
from shared.models.scoring import (
    AnswerScore,
    InterviewResult,
    Recommendation,
)
from voice.interview.state_machine import InterviewStateMachine, TurnRecord
from voice.scoring.consistency import (
    aggregate_consistency,
    check_human_review,
    compute_composite,
    recommend,
)
from voice.scoring.postcall import score_answer, score_holistic


async def run_postcall_pipeline(
    package: InterviewPackage,
    state_machine: InterviewStateMachine,
    transcript: list[TranscriptTurn],
    integrity: IntegrityReport,
) -> InterviewResult:
    """Run the full post-call scoring pipeline and return InterviewResult.

    1. Split transcript into per-answer segments by question_id.
    2. Pass 1: score each answer against the full rubric (parallel).
    3. Pass 2: holistic re-score over the assembled dossier.
    4. Aggregate consistency, compute composite, check human-review triggers.
    5. Assemble InterviewResult.
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

    # Consistency aggregation
    consistency_score = aggregate_consistency(list(answers))

    # Composite
    overall, weights = compute_composite(
        list(answers), consistency_score, package.seniority
    )

    # Human review triggers
    needs_review, reasons = check_human_review(list(answers), overall)

    # Check if composite is high but mostly background questions
    # (trigger 4 from the rubric)
    if overall > 80 and _mostly_background_questions(turns, package):
        needs_review = True
        reasons.append(
            "composite > 80 but built mostly from background questions, "
            "not technical/project"
        )

    # Recommendation
    recommendation = recommend(overall, needs_review, consistency_score)

    # Transcript summary (short gist for Lane 3)
    transcript_summary = _generate_gist(transcript)

    return InterviewResult(
        interview_id=package.interview_id,
        org_id=package.org_id,
        application_id="",  # filled by caller from the Interview row
        job_id=package.job_id,
        seniority=package.seniority,
        answers=list(answers),
        holistic=holistic,
        consistency_score=consistency_score,
        overall=overall,
        composite_weights=weights,
        percentile=None,  # computed by Lane 3 across the job's candidates
        recommendation=Recommendation(recommendation),
        needs_human_review=needs_review,
        human_review_reasons=reasons,
        hard_gate_applied=_has_hard_gate(answers, package),
        integrity=integrity,
        transcript_summary=transcript_summary,
        transcript_url="",  # filled by caller from egress
        rubric_version=package.rubric_version,
        scored_at=datetime.now(UTC),
    )


async def _score_one_answer(
    turn: TurnRecord,
    package: InterviewPackage,
) -> AnswerScore:
    """Score one turn (question + answer + follow-ups)."""
    answer = await score_answer(
        question_text=turn.question.prompt,
        question_type=turn.question.type.value,
        competency=turn.question.competency,
        seniority=package.seniority,
        resume_summary=package.resume_summary,
        answer_text=turn.answer_text,
        followup_answers=turn.followup_answers or None,
        question_id=turn.question_id,
    )
    return answer


def _mostly_background_questions(
    turns: list[TurnRecord],
    package: InterviewPackage,
) -> bool:
    """Heuristic: are most questions behavioral/situational rather than
    technical?"""
    technical_count = sum(
        1 for t in turns if t.question.type == QuestionType.TECHNICAL
    )
    return technical_count < len(turns) / 2


def _has_hard_gate(
    answers: list[AnswerScore],
    package: InterviewPackage,
) -> bool:
    """Check if any must_have question scored poorly on correctness.

    With the new 0-100 rubric, the hard gate is: any must_have question
    scoring below 25 on domain_technical_accuracy.
    """
    must_have_ids = {
        q.id for q in package.questions if q.must_have
    }
    for a in answers:
        if a.question_id in must_have_ids:
            dta = next(
                (d for d in a.dimensions if d.key == "domain_technical_accuracy"),
                None,
            )
            if dta and dta.score < 25:
                return True
    return False


def _generate_gist(transcript: list[TranscriptTurn]) -> str:
    """Generate a short prose gist of the conversation for Lane 3's chat.

    For now this is a simple extraction — the first 200 chars of each
    candidate answer joined. In production this could be an LLM call, but
    keeping it deterministic avoids an extra model dependency in the
    post-call pipeline.
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