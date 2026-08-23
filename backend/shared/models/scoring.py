"""Scoring models — written by lane 2, read and rendered by lane 3.

The hybrid design: a fast correctness-only signal streams during the call, then
a full two-pass re-score replaces it after. `InterviewResult` is the lane 2 ->
lane 3 handoff and is what the leaderboard ranks on.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

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


class OwnershipLevel(StrEnum):
    FULL_OWNER = "full_owner"
    MAJOR_CONTRIBUTOR = "major_contributor"
    MINOR_CONTRIBUTOR = "minor_contributor"
    UNCLEAR = "unclear"


class ConsistencyLabel(StrEnum):
    CONSISTENT = "consistent"
    VAGUE = "vague"
    UNVERIFIABLE = "unverifiable"
    INFLATED = "inflated"


class ScoringQuestionType(StrEnum):
    BACKGROUND = "background"
    TECHNICAL = "technical"
    PROJECT = "project"
    BEHAVIORAL = "behavioral"
    SITUATIONAL = "situational"
    POISON = "poison"


class RubricEvidence(BaseModel):
    quote: str = Field(description="Verbatim quote from the candidate transcript")
    rationale: str


class FixedRubricAssessment(BaseModel):
    """The fixed v2 rubric measurements extracted from one answer.

    Scores are optional because not every question measures every dimension.
    The deterministic aggregator re-normalizes weights over dimensions that are
    actually present rather than treating a non-applicable dimension as zero.
    """

    question_type: ScoringQuestionType
    technical_accuracy_score: int | None = Field(None, ge=0, le=100)
    technical_accuracy_evidence: RubricEvidence | None = None
    project_depth_score: int | None = Field(None, ge=0, le=100)
    project_depth_evidence: RubricEvidence | None = None
    ownership_level: OwnershipLevel | None = None
    ownership_evidence: RubricEvidence | None = None
    followup_resilience_score: int | None = Field(None, ge=0, le=100)
    followup_resilience_evidence: RubricEvidence | None = None
    consistency_label: ConsistencyLabel = ConsistencyLabel.CONSISTENT
    consistency_evidence: RubricEvidence
    central_to_role: bool = False
    resume_headline_claim: bool = False
    flagship_project: bool = False

    @model_validator(mode="after")
    def require_evidence_for_present_measurements(self) -> "FixedRubricAssessment":
        pairs = (
            (
                self.technical_accuracy_score,
                self.technical_accuracy_evidence,
                "technical_accuracy_evidence",
            ),
            (self.project_depth_score, self.project_depth_evidence, "project_depth_evidence"),
            (
                self.followup_resilience_score,
                self.followup_resilience_evidence,
                "followup_resilience_evidence",
            ),
            (self.ownership_level, self.ownership_evidence, "ownership_evidence"),
        )
        missing = [
            name for value, evidence, name in pairs if value is not None and evidence is None
        ]
        if missing:
            raise ValueError(f"Missing evidence for fixed rubric measurement: {', '.join(missing)}")
        return self


class AnswerScore(BaseModel):
    """Pass 1 — per question, parallelisable."""

    question_id: str
    dimensions: list[DimensionScore]
    weighted_score: float = Field(ge=1.0, le=5.0)
    followed_up: bool = False
    fixed_rubric: FixedRubricAssessment | None = None
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


class SeniorityBucket(StrEnum):
    JUNIOR = "junior"
    MID = "mid"
    SENIOR = "senior"


class ReviewReason(StrEnum):
    INFLATED_CENTRAL_CLAIM = "inflated_central_claim"
    WEAK_HEADLINE_FOLLOWUP = "weak_headline_followup"
    UNCLEAR_FLAGSHIP_OWNERSHIP = "unclear_flagship_ownership"
    BACKGROUND_HEAVY_HIGH_SCORE = "background_heavy_high_score"
    MUST_HAVE_HARD_GATE = "must_have_hard_gate"


class RubricComposite(BaseModel):
    """Deterministic v2 aggregate produced from per-answer measurements."""

    seniority: SeniorityBucket
    technical_accuracy_score: float | None = Field(None, ge=0.0, le=100.0)
    project_depth_score: float | None = Field(None, ge=0.0, le=100.0)
    followup_resilience_score: float | None = Field(None, ge=0.0, le=100.0)
    consistency_score: float = Field(ge=0.0, le=100.0)
    composite_score: float = Field(ge=0.0, le=100.0)
    needs_human_review: bool = False
    review_reasons: list[ReviewReason] = Field(default_factory=list)


class InterviewResult(BaseModel):
    """LANE 2 -> LANE 3 scoring and explanation contract.

    Rubric v2 ranks on `composite_score` (0-100). `overall` remains as a
    derived 1-5 compatibility value for consumers produced under v1. Formula,
    caps, and review rules are specified in docs/rubric.md.
    """

    interview_id: str
    org_id: str
    application_id: str
    job_id: str

    answers: list[AnswerScore]
    holistic: HolisticScore
    role_fit: float = Field(ge=1.0, le=5.0)

    # v2's recruiter-facing score. Optional so results produced under the v1
    # contract remain readable and can be re-scored deliberately.
    seniority: SeniorityBucket | None = None
    technical_accuracy_score: float | None = Field(None, ge=0.0, le=100.0)
    project_depth_score: float | None = Field(None, ge=0.0, le=100.0)
    followup_resilience_score: float | None = Field(None, ge=0.0, le=100.0)
    consistency_score: float | None = Field(None, ge=0.0, le=100.0)
    composite_score: float | None = Field(None, ge=0.0, le=100.0)
    needs_human_review: bool = False
    review_reasons: list[ReviewReason] = Field(default_factory=list)

    # Compatibility score for v1 consumers. New v2 results derive this from
    # composite_score using 1 + 4 * (composite / 100).
    overall: float = Field(ge=1.0, le=5.0)
    percentile: float | None = Field(None, description="Within the same job only. Never cross-job.")
    recommendation: Recommendation
    hard_gate_applied: bool = False

    integrity: IntegrityReport

    # Provenance. Without these a leaderboard silently compares scores produced
    # by different models under different prompts, which is worse than no
    # leaderboard. See docs/rubric.md -> Calibration.
    rubric_version: str
    scored_at: datetime
