"""Scoring models — written by lane 2, read and rendered by lane 3.

The hybrid design: a fast correctness-only signal streams during the call, then
a full two-pass re-score replaces it after. `InterviewResult` is the lane 2 ->
lane 3 handoff and is what the leaderboard ranks on.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .interview import IntegrityReport


class DimensionScore(BaseModel):
    """One dimension of one answer.

    `evidence` is not optional. Lane 3's chat exists to answer "why did it score
    a 3 on depth?" — without a verbatim quote it can only paraphrase, which is
    exactly the black-box behaviour we're differentiating against.
    """

    key: str
    score: int = Field(ge=1, le=5)
    evidence: str = Field(description="Verbatim quote from the transcript")
    rationale: str


class AnswerScore(BaseModel):
    """Pass 1 — per question, parallelisable."""

    question_id: str
    dimensions: list[DimensionScore]
    weighted_score: float = Field(ge=1.0, le=5.0)
    followed_up: bool = False
    model_id: str
    prompt_version: str


class LiveSignal(BaseModel):
    """The in-call fast pass. Correctness only, cheap model, shown to the
    recruiter clearly marked provisional — it is overwritten by AnswerScore."""

    question_id: str
    correctness: int = Field(ge=1, le=5)
    at_ms: int


class HolisticScore(BaseModel):
    """Pass 2 — run over the assembled per-question dossier, not the raw
    transcript. Keeps the prompt bounded and lets the judge see cross-question
    patterns that per-question scoring structurally cannot."""

    score: float = Field(ge=1.0, le=5.0)
    strengths: list[str] = Field(max_length=3)
    concerns: list[str] = Field(max_length=3)
    representative_quote: str
    model_id: str
    prompt_version: str


class Recommendation(StrEnum):
    ADVANCE = "advance"
    HOLD = "hold"
    REJECT = "reject"


class InterviewResult(BaseModel):
    """LANE 2 -> LANE 3. The leaderboard ranks on `overall`.

    overall = 0.55 * mean(weighted per-question)
            + 0.30 * holistic
            + 0.15 * role_fit
    then a hard-gate floor (any must_have question scoring <=2 on correctness
    caps overall at 2.5), then multiplicative integrity penalties.

    Formula and weights live in docs/rubric.md. Do not inline them elsewhere —
    two copies will disagree within a week.
    """

    interview_id: str
    application_id: str
    job_id: str

    answers: list[AnswerScore]
    holistic: HolisticScore
    role_fit: float = Field(ge=1.0, le=5.0)

    overall: float = Field(ge=1.0, le=5.0)
    percentile: float | None = Field(
        None, description="Within the same job only. Never cross-job."
    )
    recommendation: Recommendation
    hard_gate_applied: bool = False

    integrity: IntegrityReport

    # Provenance. Without these a leaderboard silently compares scores produced
    # by different models under different prompts, which is worse than no
    # leaderboard. See docs/rubric.md -> Calibration.
    rubric_version: str
    scored_at: datetime
