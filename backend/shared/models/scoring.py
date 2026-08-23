"""Scoring models — written by lane 2, read and rendered by lane 3.

Scoring uses a 0-100 scale with 5 bands per dimension. The rubric lives in
docs/rubric.md and the anchor descriptions in llm/prompts/score-answer.v1.md.

The hybrid design: a fast correctness-only signal streams during the call,
then a full two-pass re-score replaces it after. `InterviewResult` is the
lane 2 -> lane 3 handoff and is what the leaderboard ranks on.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .interview import IntegrityReport

# --- Enums ----------------------------------------------------------------


class OwnershipLevel(StrEnum):
    """Categorical, not scored 0-100. Feeds into depth interpretation."""

    FULL_OWNER = "full_owner"
    MAJOR_CONTRIBUTOR = "major_contributor"
    MINOR_CONTRIBUTOR = "minor_contributor"
    UNCLEAR = "unclear"


class ConsistencyLabel(StrEnum):
    """Per-answer consistency. Aggregated into a 0-100 consistency_score."""

    CONSISTENT = "consistent"
    VAGUE = "vague"
    UNVERIFIABLE = "unverifiable"
    INFLATED = "inflated"


class Recommendation(StrEnum):
    ADVANCE = "advance"
    HOLD = "hold"
    REJECT = "reject"


# --- Scoring dimensions ---------------------------------------------------


class DimensionScore(BaseModel):
    """One dimension of one answer, scored 0-100.

    `evidence` is not optional. Lane 3's chat exists to answer "why did it
    score a 73 on depth?" — without a verbatim quote it can only paraphrase,
    which is exactly the black-box behaviour we're differentiating against.
    """

    key: str = Field(
        description="One of: 'domain_technical_accuracy', 'project_depth', "
        "'followup_resilience'"
    )
    score: int = Field(ge=0, le=100)
    band: str = Field(
        description="One of: 'expert', 'strong', 'adequate', 'weak', 'poor'"
    )
    evidence: str = Field(description="Verbatim quote from the transcript")
    rationale: str


class AnswerScore(BaseModel):
    """Pass 1 — per question, parallelisable."""

    question_id: str
    dimensions: list[DimensionScore]
    ownership_level: OwnershipLevel | None = Field(
        None, description="Only for project-type questions"
    )
    consistency_label: ConsistencyLabel
    weighted_score: float = Field(ge=0.0, le=100.0)
    followed_up: bool = False
    followup_resilience_score: int = Field(
        0, ge=0, le=100,
        description="Only meaningful if followed_up=True",
    )
    model_id: str
    prompt_version: str


class LiveSignal(BaseModel):
    """The in-call fast pass. Correctness only, cheap model, shown to the
    recruiter clearly marked provisional — it is overwritten by AnswerScore."""

    question_id: str
    correctness: int = Field(ge=0, le=100)
    at_ms: int


class HolisticScore(BaseModel):
    """Pass 2 — run over the assembled per-question dossier, not the raw
    transcript. Keeps the prompt bounded and lets the judge see cross-question
    patterns that per-question scoring structurally cannot."""

    score: float = Field(ge=0.0, le=100.0)
    strengths: list[str] = Field(max_length=3)
    concerns: list[str] = Field(max_length=3)
    representative_quote: str
    model_id: str
    prompt_version: str


class InterviewResult(BaseModel):
    """LANE 2 -> LANE 3. The leaderboard ranks on `overall`.

    overall = w1 * mean(domain_technical_accuracy)
            + w2 * mean(project_depth)
            + w3 * mean(followup_resilience)
            + w4 * consistency_score

    Weights shift by seniority (junior/mid/senior). See docs/rubric.md.
    Human-review triggers fire independently of the composite score.
    """

    interview_id: str
    org_id: str
    application_id: str
    job_id: str
    seniority: str = Field(description="drives composite weights")

    answers: list[AnswerScore]
    holistic: HolisticScore
    consistency_score: int = Field(
        ge=0, le=100,
        description="max(0, 100 - sum(penalties))",
    )

    overall: float = Field(ge=0.0, le=100.0)
    composite_weights: dict[str, float] = Field(
        description="The actual weights used, for audit"
    )
    percentile: float | None = Field(
        None, description="Within the same job only. Never cross-job."
    )
    recommendation: Recommendation
    needs_human_review: bool = False
    human_review_reasons: list[str] = []
    hard_gate_applied: bool = False

    integrity: IntegrityReport

    # For Lane 3's recruiter chat context
    transcript_summary: str = Field(
        description="Short prose gist for the recruiter chat"
    )
    transcript_url: str = ""

    # Provenance. Without these a leaderboard silently compares scores
    # produced by different models under different prompts.
    rubric_version: str
    scored_at: datetime