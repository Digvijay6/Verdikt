"""Shared Pydantic models — the contracts between all three lanes.

One source of truth, three consumers:
  FastAPI  -> OpenAPI -> frontend/src/types/api.ts
  Gemini   -> response_schema (google-genai takes these directly)
  Python   -> imported by both api/ and voice/

Changing anything here is a cross-lane change. Say so in the group chat first.
"""

from .candidate import (
    Application,
    ApplicationStatus,
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
    Question,
    QuestionBankStatus,
    QuestionType,
    RubricDimension,
    ScreeningProfile,
)
from .scoring import (
    AnswerScore,
    DimensionScore,
    HolisticScore,
    InterviewResult,
    LiveSignal,
    Recommendation,
)

__all__ = [
    "Application",
    "ApplicationStatus",
    "AnswerScore",
    "DimensionScore",
    "Education",
    "EmploymentPeriod",
    "HardCheckResult",
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
    "LiveSignal",
    "ParsedResume",
    "Question",
    "QuestionBankStatus",
    "QuestionType",
    "Recommendation",
    "RubricDimension",
    "ScreeningDecision",
    "ScreeningOutcome",
    "ScreeningProfile",
    "TranscriptTurn",
]
