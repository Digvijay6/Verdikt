"""Lane 2 (interview) models.

InterviewPackage is the lane 1 -> lane 2 handoff: everything the voice worker
needs to conduct an interview, assembled at redeem time and passed into the
LiveKit room as metadata.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .candidate import ParsedResume


class QuestionType(StrEnum):
    BEHAVIORAL = "behavioral"
    TECHNICAL = "technical"
    SITUATIONAL = "situational"
    POISON = "poison"  # references tech that does not exist — see docs/rubric.md


class RubricDimension(BaseModel):
    """One scored axis. Weights are per question template and re-normalised at
    aggregation, so a missing dimension never silently distorts the total."""

    key: str = Field(description="e.g. 'correctness', 'depth', 'communication'")
    weight: float = Field(gt=0.0, le=1.0)
    anchors: dict[int, str] = Field(
        description="BARS anchors, 1-5. What each score level actually looks like."
    )


class Question(BaseModel):
    id: str
    order: int
    type: QuestionType
    prompt: str
    competency: str
    dimensions: list[RubricDimension]
    must_have: bool = Field(
        False, description="Scoring <=2 here caps the overall score. See scoring.py."
    )
    follow_up_guidance: str | None = None


class InterviewPackage(BaseModel):
    """LANE 1 -> LANE 2. Everything the worker needs; nothing it doesn't.

    Deliberately excludes the candidate's name and demographic detail — the
    interviewer agent does not need them, and blind conduct is easier to
    defend than blind conduct retrofitted later.
    """

    interview_id: str
    job_id: str
    job_title: str
    seniority: str
    questions: list[Question]
    resume_summary: str = Field(description="Short prose summary, not the full resume")
    resume_highlights: ParsedResume | None = None
    rubric_version: str
    language: str = "en"


class InterviewStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    FLAGGED = "flagged"


class TranscriptTurn(BaseModel):
    speaker: str = Field(description="'agent' or 'candidate'")
    text: str
    start_ms: int
    end_ms: int
    question_id: str | None = None


class Interview(BaseModel):
    id: str
    application_id: str
    job_id: str
    status: InterviewStatus
    room_name: str
    started_at: datetime | None = None
    ended_at: datetime | None = None
    transcript: list[TranscriptTurn] = []
    audio_url: str | None = None
    model_id: str | None = None
    prompt_version: str | None = None


# --- Proctoring -----------------------------------------------------------


class IntegrityEventType(StrEnum):
    TAB_BLUR = "tab_blur"
    FULLSCREEN_EXIT = "fullscreen_exit"
    PASTE_BURST = "paste_burst"
    VIRTUAL_CAMERA = "virtual_camera"
    MULTIPLE_DISPLAYS = "multiple_displays"
    VM_DETECTED = "vm_detected"
    RAF_JITTER = "raf_jitter"
    DEVICE_CHANGE = "device_change"
    MULTI_SPEAKER = "multi_speaker"  # post-call diarization
    LATENCY_FLATLINE = "latency_flatline"
    POISON_QUESTION_FAILED = "poison_question_failed"
    PROMPT_INJECTION = "prompt_injection"


class IntegrityEvent(BaseModel):
    interview_id: str
    type: IntegrityEventType
    severity: float = Field(ge=0.0, le=1.0)
    at_ms: int
    detail: dict = {}


class IntegrityReport(BaseModel):
    """Aggregated signal. Never an auto-reject on its own — GDPR Art. 22 and
    NY AEDTA both require a human in the loop. Surfaced to the recruiter as
    evidence, not as a verdict."""

    score: int = Field(ge=0, le=100, description="<30 clean, 30-60 review, >60 flag")
    events: list[IntegrityEvent] = []
    summary: str
