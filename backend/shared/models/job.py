"""Lane 1 (intake) — the job and everything configured on it.

The question bank lives here rather than on the interview because the job owns
it: it is generated once per job and every candidate for that role gets the
identical set (D16). Tailoring per candidate would destroy score comparability
across the leaderboard and reintroduce exactly the bias structured interviewing
exists to remove.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ScreeningProfile(BaseModel):
    """The hard gate, configured per job.

    Everything here is checked in plain Python before any model is called —
    deterministic, free, and it means the LLM screen only ever sees survivors.
    """

    min_years_experience: float | None = None
    required_skills: list[str] = Field(
        [], description="All must be present. This is the hard gate."
    )
    preferred_skills: list[str] = Field(
        [], description="Informs the LLM screen. Never gates on its own."
    )
    locations: list[str] = []
    remote_ok: bool = True
    work_authorization: str | None = None


class QuestionType(StrEnum):
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    SITUATIONAL = "situational"
    POISON = "poison"  # references technology that does not exist — see docs/rubric.md


class RubricDimension(BaseModel):
    """One scored axis of one question.

    Anchors must describe *observable behaviour*. "Names a specific trade-off and
    says which side they would pick" is scorable; "shows good understanding" is
    not, because two judges read it differently. Lane 2 scores against these
    exact anchors, so vagueness here produces inconsistent scores that nothing
    downstream can repair.
    """

    key: str = Field(description="e.g. 'correctness', 'depth', 'communication'")
    weight: float = Field(gt=0.0, le=1.0)
    anchors: dict[int, str] = Field(description="BARS anchors, 1-5")


class Question(BaseModel):
    id: str
    order: int
    type: QuestionType
    prompt: str
    competency: str
    dimensions: list[RubricDimension]
    must_have: bool = Field(
        False, description="Scoring <=2 here caps the overall score. See docs/rubric.md."
    )
    follow_up_guidance: str | None = None


class QuestionBankStatus(StrEnum):
    PENDING = "pending"
    BUILDING = "building"
    READY = "ready"
    FAILED = "failed"


class Job(BaseModel):
    id: str
    title: str
    role_family: str | None = None
    seniority: str
    jd_text: str

    screening_profile: ScreeningProfile = ScreeningProfile()

    question_bank: list[Question] | None = None
    question_bank_status: QuestionBankStatus = QuestionBankStatus.PENDING
    question_bank_error: str | None = None

    # Bump whenever the bank or its anchors change — lane 2 scores against those
    # anchors, so a change here changes scores.
    rubric_version: str = "v1"

    created_by: str | None = None
    created_at: datetime


class JobCreate(BaseModel):
    title: str
    seniority: str
    jd_text: str
    role_family: str | None = None
    screening_profile: ScreeningProfile = ScreeningProfile()
