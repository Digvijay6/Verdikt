"""Supabase access for lane 1's tables.

Only this lane writes to job / candidate / application / interview_invite.
Other lanes read them; if they need a write, they ask rather than reaching in.

Kept separate from the routers so the pipeline can be exercised without HTTP.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from shared.db import db
from shared.models.candidate import (
    Application,
    ApplicationStatus,
    HardCheckResult,
    ParsedResume,
    ScreeningDecision,
)
from shared.models.job import Job, JobCreate, Question, QuestionBankStatus


# --- job ------------------------------------------------------------------


def create_job(payload: JobCreate, created_by: str | None) -> Job:
    row = (
        db()
        .table("job")
        .insert(
            {
                "title": payload.title,
                "seniority": payload.seniority,
                "role_family": payload.role_family,
                "jd_text": payload.jd_text,
                "screening_profile": payload.screening_profile.model_dump(),
                "created_by": created_by,
            }
        )
        .execute()
        .data[0]
    )
    return Job.model_validate(row)


def get_job(job_id: str) -> Job | None:
    res = db().table("job").select("*").eq("id", job_id).execute()
    return Job.model_validate(res.data[0]) if res.data else None


def list_jobs() -> list[Job]:
    res = db().table("job").select("*").order("created_at", desc=True).execute()
    return [Job.model_validate(r) for r in res.data]


def set_question_bank_status(
    job_id: str, status: QuestionBankStatus, error: str | None = None
) -> None:
    db().table("job").update(
        {"question_bank_status": status.value, "question_bank_error": error}
    ).eq("id", job_id).execute()


def save_question_bank(job_id: str, questions: list[Question], rubric_version: str) -> None:
    db().table("job").update(
        {
            "question_bank": [q.model_dump(mode="json") for q in questions],
            "question_bank_status": QuestionBankStatus.READY.value,
            "question_bank_error": None,
            "rubric_version": rubric_version,
        }
    ).eq("id", job_id).execute()


# --- candidate ------------------------------------------------------------


def upsert_candidate(
    email: str,
    full_name: str | None = None,
    phone: str | None = None,
    location: str | None = None,
) -> str:
    """One row per human, keyed on email (D20).

    Email is `citext` in the database, so casing is handled there rather than
    depending on every caller remembering to normalise.
    """
    fields: dict[str, Any] = {"email": email}
    for key, value in (
        ("full_name", full_name),
        ("phone", phone),
        ("location", location),
    ):
        if value:
            fields[key] = value

    row = (
        db()
        .table("candidate")
        .upsert(fields, on_conflict="email")
        .execute()
        .data[0]
    )
    return row["id"]


def enrich_candidate(
    candidate_id: str,
    full_name: str | None = None,
    phone: str | None = None,
    location: str | None = None,
) -> None:
    """Fill in fields the resume revealed that the application form did not ask
    for. Only writes non-empty values, so a sparse resume never blanks out
    details the candidate typed themselves."""
    fields = {
        k: v
        for k, v in (
            ("full_name", full_name),
            ("phone", phone),
            ("location", location),
        )
        if v
    }
    if fields:
        db().table("candidate").update(fields).eq("id", candidate_id).execute()


def get_candidate(candidate_id: str) -> dict | None:
    res = db().table("candidate").select("*").eq("id", candidate_id).execute()
    return res.data[0] if res.data else None


# --- application ----------------------------------------------------------


def create_application(
    job_id: str, candidate_id: str, resume_url: str, consent_given_at: datetime
) -> Application:
    row = (
        db()
        .table("application")
        .upsert(
            {
                "job_id": job_id,
                "candidate_id": candidate_id,
                "resume_url": resume_url,
                "consent_given_at": consent_given_at.isoformat(),
                "status": ApplicationStatus.RECEIVED.value,
            },
            on_conflict="job_id,candidate_id",
        )
        .execute()
        .data[0]
    )
    return Application.model_validate(row)


def get_application(application_id: str) -> Application | None:
    res = (
        db().table("application").select("*").eq("id", application_id).execute()
    )
    return Application.model_validate(res.data[0]) if res.data else None


def list_applications(
    job_id: str, status: ApplicationStatus | None = None
) -> list[Application]:
    q = db().table("application").select("*").eq("job_id", job_id)
    if status:
        q = q.eq("status", status.value)
    return [
        Application.model_validate(r)
        for r in q.order("created_at", desc=True).execute().data
    ]


def set_status(application_id: str, status: ApplicationStatus) -> None:
    db().table("application").update({"status": status.value}).eq(
        "id", application_id
    ).execute()


def save_parsed_resume(application_id: str, resume: ParsedResume) -> None:
    db().table("application").update(
        {
            "parsed_resume": resume.model_dump(mode="json"),
            "status": ApplicationStatus.PARSED.value,
        }
    ).eq("id", application_id).execute()


def save_hard_checks(application_id: str, checks: list[HardCheckResult]) -> None:
    db().table("application").update(
        {"hard_checks": [c.model_dump(mode="json") for c in checks]}
    ).eq("id", application_id).execute()


def save_screening(
    application_id: str,
    decision: ScreeningDecision,
    model_id: str,
    prompt_version: str,
) -> None:
    """Provenance is written in the same statement as the decision, so a
    decision can never exist without the model and prompt that produced it."""
    db().table("application").update(
        {
            "screening": decision.model_dump(mode="json"),
            "screening_model_id": model_id,
            "screening_prompt_version": prompt_version,
            "status": ApplicationStatus.SCREENED.value,
        }
    ).eq("id", application_id).execute()


# --- invites --------------------------------------------------------------


def create_invite(
    application_id: str, token_hash: str, expires_at: datetime
) -> str:
    row = (
        db()
        .table("interview_invite")
        .insert(
            {
                "application_id": application_id,
                "token_hash": token_hash,
                "expires_at": expires_at.isoformat(),
            }
        )
        .execute()
        .data[0]
    )
    return row["id"]


# --- storage --------------------------------------------------------------

RESUME_BUCKET = "resumes"


def upload_resume(path: str, data: bytes) -> str:
    """Private bucket. The returned path is stored; readers get a signed URL."""
    db().storage.from_(RESUME_BUCKET).upload(
        path, data, {"content-type": "application/pdf", "upsert": "true"}
    )
    return path


def download_resume(path: str) -> bytes:
    return db().storage.from_(RESUME_BUCKET).download(path)


def signed_resume_url(path: str, expires_in: int = 3600) -> str:
    res = db().storage.from_(RESUME_BUCKET).create_signed_url(path, expires_in)
    return res["signedURL"]
