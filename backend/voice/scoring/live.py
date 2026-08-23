"""In-call provisional scorer.

Fires a fast correctness-only LLM call after each candidate answer. The result
is pushed to Supabase realtime for the recruiter's live HUD and drives the
follow-up decision in the state machine. It is overwritten by the post-call
full rubric re-score.
"""

from __future__ import annotations

import time

from pydantic import BaseModel, Field

from shared.llm import Provenance, run
from shared.models.scoring import LiveSignal


class LiveCorrectnessResult(BaseModel):
    """Schema passed to Gemini as response_schema for the live scorer."""

    correctness: int = Field(ge=0, le=100)
    rationale: str = ""


def score_live(
    question_text: str,
    question_type: str,
    competency: str,
    answer_text: str,
) -> tuple[LiveSignal, Provenance]:
    """Score one answer for correctness only, in real time.

    Returns a LiveSignal to stream to the recruiter and Provenance to persist.
    """
    user_content = (
        f"Question: {question_text}\n"
        f"Question type: {question_type}\n"
        f"Competency: {competency}\n\n"
        f"Candidate answer: {answer_text}"
    )

    result, provenance = run(
        "score-answer-live",
        LiveCorrectnessResult,
        user_content=user_content,
    )

    signal = LiveSignal(
        question_id="",  # set by caller
        correctness=result.correctness,
        at_ms=int(time.time() * 1000),
    )

    return signal, provenance