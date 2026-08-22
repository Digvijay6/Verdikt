"""Lane 2 (interview) models.

InterviewPackage is the lane 1 -> lane 2 handoff: everything the voice worker
needs to conduct an interview, assembled at redeem time and passed into the
LiveKit room as metadata.

Question and its rubric live in job.py, not here — the job owns them (D16) and
this lane consumes them.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .candidate import ParsedResume
from .job import Question


class InterviewPackage(BaseModel):
    """LANE 1 -> LANE 2. Everything the worker needs; nothing it doesn't.

    Deliberately excludes the candidate's name and demographic detail (D14). The
    interviewer agent does not need them, and blind conduct is far easier to
    defend than blind conduct retrofitted after a complaint.
    """

    interview_id: str
    org_id: str
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
    org_id: str
    application_id: str
    job_id: str
    status: InterviewStatus
    room_name: str | None = None
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
    org_id: str
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
