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
    Question,
    QuestionType,
    RubricDimension,
    TranscriptTurn,
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
    "LiveSignal",
    "ParsedResume",
    "Question",
    "QuestionType",
    "Recommendation",
    "RubricDimension",
    "ScreeningDecision",
    "ScreeningOutcome",
    "TranscriptTurn",
]
