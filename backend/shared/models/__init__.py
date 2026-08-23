"""Shared Pydantic models — the contracts between all three lanes.

One source of truth, three consumers:
  FastAPI  -> OpenAPI -> frontend/src/types/api.ts
  Gemini   -> response_schema (google-genai takes these directly)
  Python   -> imported by both api/ and voice/

Every tenant-scoped model carries `org_id`. The database enforces that it
matches the parent row through composite foreign keys, so a cross-org row
cannot be inserted even if a query forgets to filter.

Changing anything here is a cross-lane change. Say so in the group chat first.
"""

from .candidate import (
    Application,
    ApplicationStatus,
    Candidate,
    Education,
    EmploymentPeriod,
    HardCheckResult,
    InterviewInvite,
    ParsedResume,
    ScreeningDecision,
    ScreeningOutcome,
)
from .interview import (
    IntegrityEvent,
    IntegrityEventType,
    IntegrityReport,
    Interview,
    InterviewPackage,
    InterviewStatus,
    TranscriptTurn,
)
from .job import (
    Job,
    JobCreate,
    JobPipelineStats,
    JobStatus,
    ProfileSource,
    Question,
    QuestionBankStatus,
    QuestionType,
    RubricDimension,
    ScreeningProfile,
)
from .organization import (
    Membership,
    Organization,
    OrganizationCreate,
    Plan,
    Role,
)
from .scoring import (
    AnswerScore,
    ConsistencyLabel,
    DimensionScore,
    FixedRubricAssessment,
    HolisticScore,
    InterviewResult,
    LiveSignal,
    OwnershipLevel,
    Recommendation,
    ReviewReason,
    RubricComposite,
    RubricEvidence,
    ScoringQuestionType,
    SeniorityBucket,
)

__all__ = [
    "AnswerScore",
    "Application",
    "ApplicationStatus",
    "Candidate",
    "ConsistencyLabel",
    "DimensionScore",
    "Education",
    "EmploymentPeriod",
    "HardCheckResult",
    "FixedRubricAssessment",
    "HolisticScore",
    "IntegrityEvent",
    "IntegrityEventType",
    "IntegrityReport",
    "Interview",
    "InterviewInvite",
    "InterviewPackage",
    "InterviewResult",
    "InterviewStatus",
    "Job",
    "JobCreate",
    "JobPipelineStats",
    "JobStatus",
    "LiveSignal",
    "Membership",
    "Organization",
    "OrganizationCreate",
    "OwnershipLevel",
    "ParsedResume",
    "Plan",
    "ProfileSource",
    "Question",
    "QuestionBankStatus",
    "QuestionType",
    "Recommendation",
    "ReviewReason",
    "Role",
    "RubricDimension",
    "RubricComposite",
    "RubricEvidence",
    "ScoringQuestionType",
    "ScreeningDecision",
    "ScreeningOutcome",
    "ScreeningProfile",
    "SeniorityBucket",
    "TranscriptTurn",
]