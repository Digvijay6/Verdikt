"""Lane 1 (intake) models — application through to interview invite.

These are the contracts, not just internal types. FastAPI turns them into
OpenAPI (which generates the frontend's types) and the Gemini SDK takes them
directly as `response_schema`. Change one and both sides follow.
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field


# --- Resume parsing -------------------------------------------------------
# Passed to Gemini as response_schema; response.parsed returns ParsedResume.


class EmploymentPeriod(BaseModel):
    company: str
    title: str
    start: date | None = None
    end: date | None = Field(None, description="None means current role")
    summary: str | None = None


class Education(BaseModel):
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    graduation_year: int | None = None


class ParsedResume(BaseModel):
    full_name: str | None = None
    email: EmailStr | None = None
    phone: str | None = None
    location: str | None = None
    total_years_experience: float | None = Field(
        None, description="Computed from employment history, not self-reported"
    )
    skills: list[str] = []
    employment: list[EmploymentPeriod] = []
    education: list[Education] = []
    links: list[str] = Field([], description="GitHub, portfolio, LinkedIn")


# --- Screening ------------------------------------------------------------


class ScreeningOutcome(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    REVIEW = "review"


class HardCheckResult(BaseModel):
    """Deterministic gate. No LLM — plain Python over ParsedResume."""

    check: str = Field(description="e.g. 'min_years_experience', 'work_authorization'")
    passed: bool
    detail: str


class ScreeningDecision(BaseModel):
    """Gemini's judgement on the soft criteria, after hard checks pass.

    `evidence` is required: every claim must point at something in the resume.
    An unevidenced rejection is not defensible under GDPR Art. 22 or NY AEDTA.
    """

    outcome: ScreeningOutcome
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    evidence: list[str] = Field(description="Quotes or specifics drawn from the resume")
    concerns: list[str] = []


# --- Persisted rows -------------------------------------------------------


class ApplicationStatus(StrEnum):
    RECEIVED = "received"
    PARSED = "parsed"
    SCREENED = "screened"
    INVITED = "invited"
    INTERVIEWING = "interviewing"
    COMPLETE = "complete"
    REJECTED = "rejected"


class Application(BaseModel):
    id: str
    job_id: str
    candidate_id: str
    status: ApplicationStatus
    resume_url: str
    parsed_resume: ParsedResume | None = None
    hard_checks: list[HardCheckResult] = []
    screening: ScreeningDecision | None = None
    # Stamped on every LLM-derived field so scores stay comparable across
    # model and prompt changes. See llm/registry.json.
    screening_model_id: str | None = None
    screening_prompt_version: str | None = None
    created_at: datetime


class InterviewInvite(BaseModel):
    """The emailed link. Only the hash is stored — never the raw token."""

    id: str
    application_id: str
    token_hash: str
    expires_at: datetime
    redeemed_at: datetime | None = None
    interview_id: str | None = Field(
        None, description="Set on redeem. Revisits with this set rejoin, not restart."
    )
    created_at: datetime
