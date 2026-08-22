"""Lane 1 (intake) — the job and everything configured on it.

The question bank lives here rather than on the interview because the job owns
it: generated once per job, identical for every candidate (D16). Tailoring per
candidate would destroy score comparability across the leaderboard and
reintroduce exactly the bias structured interviewing exists to remove.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ScreeningProfile(BaseModel):
    """The hard gate, configured per job.

    Checked in plain Python before any model runs — deterministic, free, and it
    means the LLM screen only ever sees survivors (D18).
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


class ProfileSource(StrEnum):
    AI = "ai"
    MANUAL = "manual"


class QuestionType(StrEnum):
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    SITUATIONAL = "situational"
    POISON = "poison"  # references technology that does not exist


class RubricDimension(BaseModel):
    """One scored axis of one question.

    Anchors must describe *observable behaviour*. "Names a specific trade-off
    and says which side they would pick" is scorable; "shows good understanding"
    is not, because two people read it differently. Lane 2 scores against these
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


class JobStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"      # stops new applications, keeps everything else
    ARCHIVED = "archived"


class Job(BaseModel):
    id: str
    org_id: str

    title: str
    role_family: str | None = None
    seniority: str
    jd_text: str

    # A filled role is still an asset: its leaderboard, transcripts and scores
    # stay intact, and compliance.md requires decision records for 24 months
    # regardless. Closing stops new applications, nothing more.
    status: JobStatus = JobStatus.OPEN
    closed_at: datetime | None = None

    screening_profile: ScreeningProfile = ScreeningProfile()
    # Recorded, never enforced. The meaningful human decision is at the
    # leaderboard; blocking the pipeline on an approval click would defeat its
    # purpose. The safety valve is that screen-rejected candidates stay visible
    # and reversible.
    screening_profile_source: ProfileSource = ProfileSource.MANUAL
    screening_profile_model_id: str | None = None
    screening_profile_reviewed_at: datetime | None = None
    screening_profile_reviewed_by: str | None = None

    question_bank: list[Question] | None = None
    question_bank_status: QuestionBankStatus = QuestionBankStatus.PENDING
    question_bank_error: str | None = None

    # Bump whenever the bank or its anchors change — lane 2 scores against those
    # anchors, so a change here changes scores.
    rubric_version: str = "v1"

    created_by: str | None = None
    created_at: datetime

    @property
    def accepts_applications(self) -> bool:
        return self.status is JobStatus.OPEN


class JobCreate(BaseModel):
    title: str
    seniority: str
    jd_text: str
    role_family: str | None = None
    # Omit to have Gemini extract the hard requirements from the JD.
    screening_profile: ScreeningProfile | None = None


class JobPipelineStats(BaseModel):
    """One grouped count behind every dashboard tile.

    Backed by the `job_pipeline_stats` view — a single query rather than one
    per tile.
    """

    org_id: str
    job_id: str
    total: int = 0
    processing: int = 0
    needs_review: int = 0
    rejected_screen: int = 0
    rejected_post: int = 0
    interview_remaining: int = 0
    interview_ongoing: int = 0
    scoring: int = 0
    scored: int = 0
    advanced: int = 0
    failed: int = 0
