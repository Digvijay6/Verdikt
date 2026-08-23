"""Lane 1 (intake) models — application through to interview invite.

These are contracts, not just internal types. FastAPI turns them into OpenAPI
(which generates the frontend's types) and the Gemini SDK takes them directly
as `response_schema`. Change one and both sides follow.
"""

from datetime import date, datetime
from enum import StrEnum

from pydantic import BaseModel, EmailStr, Field

from .job import Question


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


# --- Candidate ------------------------------------------------------------


class Candidate(BaseModel):
    """Scoped to one organization, deliberately.

    A global candidate keyed on email would let company A infer that someone
    also applied to company B. The same person applying to two customers gets
    two rows; the lost deduplication is a feature nobody wants.
    """

    id: str
    org_id: str
    email: EmailStr
    full_name: str | None = None
    phone: str | None = None
    location: str | None = None
    created_at: datetime


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
    """Every stage the dashboard needs to count separately.

    The two rejection states are distinct on purpose: a candidate filtered by
    the hard checks never reached a leaderboard, and that difference matters
    when someone asks why they were rejected.
    """

    RECEIVED = "received"
    PARSING = "parsing"
    SCREENING = "screening"

    REJECTED_SCREEN = "rejected_screen"   # hard checks or the LLM screen
    REVIEW = "review"                     # awaiting a human
    INVITED = "invited"                   # link sent, interview not started

    INTERVIEWING = "interviewing"         # live right now
    INTERVIEWED = "interviewed"           # done, scoring running
    SCORED = "scored"                     # on the leaderboard

    ADVANCED = "advanced"                 # recruiter moved them forward
    REJECTED_POST = "rejected_post"       # rejected after interview

    # Set when the pipeline throws. Without it a failure leaves the row at
    # `received`, indistinguishable from one that just arrived — and invisible
    # stuck work is the worst kind.
    FAILED = "failed"


class Application(BaseModel):
    id: str
    org_id: str
    job_id: str
    candidate_id: str
    status: ApplicationStatus

    resume_url: str
    parsed_resume: ParsedResume | None = None
    hard_checks: list[HardCheckResult] = []
    screening: ScreeningDecision | None = None

    # Stamped on every LLM-derived field so decisions stay comparable across
    # model and prompt changes (D5).
    screening_model_id: str | None = None
    screening_prompt_version: str | None = None

    # Probes generated for this candidate from job.rubric plus their parsed
    # resume. Each carries a copy of its competency's dimensions, so lane 2 and
    # lane 3 see an unchanged Question shape.
    questions: list[Question] | None = None
    questions_model_id: str | None = None
    questions_prompt_version: str | None = None
    questions_error: str | None = None

    consent_given_at: datetime

    # compliance.md promises a human reviews every rejection. Without recording
    # which human, that promise cannot be evidenced when a candidate disputes it.
    decided_by: str | None = None
    decided_at: datetime | None = None
    decision_note: str | None = None

    failure_reason: str | None = None

    created_at: datetime


class InterviewInvite(BaseModel):
    """The emailed link. Only the hash is stored — never the raw token."""

    id: str
    org_id: str
    application_id: str
    token_hash: str
    expires_at: datetime
    redeemed_at: datetime | None = None
    interview_id: str | None = Field(
        None, description="Set on redeem. Revisits with this set rejoin, not restart."
    )
    created_at: datetime
