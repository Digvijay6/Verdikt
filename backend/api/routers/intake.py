"""LANE 1 — Aditya. Application intake through interview invite.

Two audiences on one router:
  - recruiters, behind a Supabase JWT
  - candidates, on the public application form, with no account at all

The public endpoint returns immediately and runs the pipeline in the
background, so nobody sits on a loading spinner waiting for a model call.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from pydantic import BaseModel, EmailStr

from intake import pipeline, repo
from intake.question_builder import build_question_bank
from shared.models.candidate import Application, ApplicationStatus
from shared.models.job import Job, JobCreate

from ..deps import Recruiter, current_recruiter

router = APIRouter(prefix="/intake", tags=["intake"])

MAX_RESUME_BYTES = 10 * 1024 * 1024


# --- jobs -----------------------------------------------------------------


@router.post("/jobs", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    background: BackgroundTasks,
    recruiter: Recruiter = Depends(current_recruiter),
) -> Job:
    """Create a job and start building its question bank.

    The bank takes a while — it is a multi-step workflow with a validation loop
    — so the job comes back immediately with `question_bank_status: building`
    and the client polls.
    """
    job = repo.create_job(payload, created_by=recruiter.id)
    background.add_task(build_question_bank, job.id)
    return job


@router.get("/jobs", response_model=list[Job])
def list_jobs(recruiter: Recruiter = Depends(current_recruiter)) -> list[Job]:
    return repo.list_jobs()


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(
    job_id: str, recruiter: Recruiter = Depends(current_recruiter)
) -> Job:
    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    return job


@router.post("/jobs/{job_id}/rebuild-questions", status_code=status.HTTP_202_ACCEPTED)
def rebuild_questions(
    job_id: str,
    background: BackgroundTasks,
    recruiter: Recruiter = Depends(current_recruiter),
) -> dict[str, str]:
    """Regenerate the bank — after editing the JD, or if a build failed.

    This changes the questions and their anchors, so it bumps `rubric_version`.
    Interviews already scored under the old version stay interpretable; new ones
    are not comparable to them.
    """
    if repo.get_job(job_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    background.add_task(build_question_bank, job_id)
    return {"status": "building"}


# --- applications ---------------------------------------------------------


class ApplicationAccepted(BaseModel):
    application_id: str
    status: ApplicationStatus


@router.post(
    "/applications",
    response_model=ApplicationAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def apply(
    background: BackgroundTasks,
    job_id: str = Form(...),
    email: EmailStr = Form(...),
    full_name: str | None = Form(None),
    phone: str | None = Form(None),
    consent: bool = Form(
        ..., description="Must be true. Recorded before the resume is processed."
    ),
    resume: UploadFile = File(...),
) -> ApplicationAccepted:
    """Public. No account — this is a candidate applying.

    Consent is checked before the file is read, not after. Processing a resume
    without recorded consent is the violation; doing it and then discarding the
    result is still the violation.
    """
    if not consent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Consent is required before an application can be processed.",
        )

    # Local checks first — they are free and need no round trip. A malformed
    # upload should not cost a database query, and on a public endpoint that
    # ordering is also the cheapest defence against junk traffic.
    if resume.content_type != "application/pdf":
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Resume must be a PDF"
        )

    data = await resume.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Resume file is empty")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Resume exceeds 10MB"
        )

    job = repo.get_job(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")

    candidate_id = repo.upsert_candidate(email=str(email), full_name=full_name, phone=phone)

    path = f"{job_id}/{candidate_id}/{uuid.uuid4()}.pdf"
    repo.upload_resume(path, data)

    application = repo.create_application(
        job_id=job_id,
        candidate_id=candidate_id,
        resume_url=path,
        consent_given_at=datetime.now(timezone.utc),
    )

    background.add_task(pipeline.process_application, application.id)
    return ApplicationAccepted(
        application_id=application.id, status=application.status
    )


@router.get("/applications", response_model=list[Application])
def list_applications(
    job_id: str,
    status_filter: ApplicationStatus | None = None,
    recruiter: Recruiter = Depends(current_recruiter),
) -> list[Application]:
    """The review queue. Filter to `screened` for applications the model flagged
    for a human — that is where the human-in-the-loop requirement lives."""
    return repo.list_applications(job_id, status_filter)


@router.get("/applications/{application_id}", response_model=Application)
def get_application(
    application_id: str, recruiter: Recruiter = Depends(current_recruiter)
) -> Application:
    application = repo.get_application(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")
    return application


class Decision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


class DecideRequest(BaseModel):
    decision: Decision


@router.post("/applications/{application_id}/decide", response_model=Application)
def decide(
    application_id: str,
    body: DecideRequest,
    recruiter: Recruiter = Depends(current_recruiter),
) -> Application:
    """A human resolving a `review`, or overriding the model either way.

    This endpoint is the compliance story made concrete: every rejection that
    reaches a candidate passed through a person here.
    """
    application = repo.get_application(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")

    if body.decision is Decision.ACCEPT:
        pipeline.send_invite(application_id)
    else:
        pipeline.reject(application_id)

    refreshed = repo.get_application(application_id)
    assert refreshed is not None
    return refreshed


@router.get("/applications/{application_id}/resume-url")
def resume_url(
    application_id: str, recruiter: Recruiter = Depends(current_recruiter)
) -> dict[str, str]:
    """Short-lived signed URL. Resumes live in a private bucket, so there is no
    permanent link to leak."""
    application = repo.get_application(application_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")
    return {"url": repo.signed_resume_url(application.resume_url)}
