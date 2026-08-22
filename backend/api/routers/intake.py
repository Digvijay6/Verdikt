"""LANE 1 — Aditya. Application intake through interview invite.

Two audiences on one router:
  - recruiters, behind a Supabase JWT, scoped to their organization
  - candidates, on the public application form, with no account at all

Recruiter routes take the organization from the caller's membership, never from
a path or query parameter. A client cannot ask for another tenant's data by
changing a URL, because the URL never carries the tenant.

The public endpoint is the one exception, and derives the org from the job it
was given.
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

from intake import pipeline, repo, requirements
from intake.question_builder import build_question_bank
from shared.models.candidate import Application, ApplicationStatus
from shared.models.job import (
    Job,
    JobCreate,
    JobPipelineStats,
    JobStatus,
    ProfileSource,
    ScreeningProfile,
)

from ..deps import Recruiter, current_recruiter

router = APIRouter(prefix="/intake", tags=["intake"])

MAX_RESUME_BYTES = 10 * 1024 * 1024


# --- jobs -----------------------------------------------------------------


def _create_job_assets(job_id: str, org_id: str, extract_profile: bool) -> None:
    """Background work after a job is created.

    Requirement extraction runs first when asked for, because the hard checks
    it produces gate every application that follows.
    """
    if extract_profile:
        job = repo.get_job(job_id, org_id)
        if job is not None:
            profile, prov = requirements.extract_screening_profile(
                job.jd_text, job.title, job.seniority
            )
            repo.save_screening_profile(
                job_id, org_id, profile, ProfileSource.AI, prov.model_id
            )
    build_question_bank(job_id, org_id)


@router.post("/jobs", response_model=Job, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: JobCreate,
    background: BackgroundTasks,
    recruiter: Recruiter = Depends(current_recruiter),
) -> Job:
    """Create a job and start building its assets.

    Omit `screening_profile` and Gemini extracts the hard requirements from the
    JD. The question bank is a multi-step workflow with a validation loop, so
    the job returns immediately with `question_bank_status: building` and the
    client polls.
    """
    job = repo.create_job(payload, org_id=recruiter.org_id, created_by=recruiter.id)
    background.add_task(
        _create_job_assets,
        job.id,
        recruiter.org_id,
        extract_profile=payload.screening_profile is None,
    )
    return job


@router.get("/jobs", response_model=list[Job])
def list_jobs(
    status_filter: JobStatus | None = None,
    recruiter: Recruiter = Depends(current_recruiter),
) -> list[Job]:
    return repo.list_jobs(recruiter.org_id, status_filter)


@router.get("/jobs/{job_id}", response_model=Job)
def get_job(job_id: str, recruiter: Recruiter = Depends(current_recruiter)) -> Job:
    job = repo.get_job(job_id, recruiter.org_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    return job


@router.get("/jobs/{job_id}/stats", response_model=JobPipelineStats)
def job_stats(
    job_id: str, recruiter: Recruiter = Depends(current_recruiter)
) -> JobPipelineStats:
    """Every dashboard tile in one query.

    `needs_review` and `failed` are the two that want a human's attention:
    the first is the compliance queue, the second is stuck work.
    """
    if repo.get_job(job_id, recruiter.org_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    return repo.pipeline_stats(recruiter.org_id, job_id)


@router.put("/jobs/{job_id}/screening-profile", response_model=Job)
def update_screening_profile(
    job_id: str,
    profile: ScreeningProfile,
    recruiter: Recruiter = Depends(current_recruiter),
) -> Job:
    """Correct the hard requirements.

    The counterpart to AI extraction (D28). Requirements auto-reject people, so
    a recruiter who spots a wrong one — "5+ years preferred" read as a hard
    minimum, a skill that is not really mandatory — needs to be able to fix it
    without recreating the job.

    Marks the profile reviewed and attributes it, which also converts an
    AI-drafted profile into a human-owned one.

    Only affects applications screened *after* this. Anyone already in
    `rejected_screen` stays there until invited from that list.
    """
    if repo.get_job(job_id, recruiter.org_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")

    repo.save_screening_profile(
        job_id,
        recruiter.org_id,
        profile,
        source=ProfileSource.MANUAL,
        reviewed_by=recruiter.id,
    )
    refreshed = repo.get_job(job_id, recruiter.org_id)
    assert refreshed is not None
    return refreshed


@router.post("/jobs/{job_id}/close", response_model=Job)
def close_job(job_id: str, recruiter: Recruiter = Depends(current_recruiter)) -> Job:
    """Stop accepting applications. Everything already collected stays.

    A filled role is still an asset — its leaderboard, transcripts and scores
    remain, and compliance.md requires decision records for 24 months anyway.
    """
    if repo.get_job(job_id, recruiter.org_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    repo.close_job(job_id, recruiter.org_id)
    refreshed = repo.get_job(job_id, recruiter.org_id)
    assert refreshed is not None
    return refreshed


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
    if repo.get_job(job_id, recruiter.org_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    background.add_task(build_question_bank, job_id, recruiter.org_id)
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

    Consent is checked before the file is read, not after. Processing a résumé
    without recorded consent is the violation; doing it and then discarding the
    result is still the violation.
    """
    if not consent:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Consent is required before an application can be processed.",
        )

    # Local checks first — free, and no round trip. A malformed upload should
    # not cost a database query, which on a public endpoint is also the cheapest
    # defence against junk traffic.
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

    # The only unscoped lookup in the codebase: the candidate has no account, so
    # the job id is what establishes the tenant. Every write below uses
    # job.org_id rather than anything the client supplied.
    job = repo.get_job_unscoped(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such job")
    if not job.accepts_applications:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "This role is no longer accepting applications.",
        )

    org_id = job.org_id
    candidate_id = repo.upsert_candidate(
        org_id, email=str(email), full_name=full_name, phone=phone
    )

    path = repo.resume_path(org_id, job_id, candidate_id, f"{uuid.uuid4()}.pdf")
    repo.upload_resume(path, data)

    application = repo.create_application(
        org_id=org_id,
        job_id=job_id,
        candidate_id=candidate_id,
        resume_url=path,
        consent_given_at=datetime.now(timezone.utc),
    )

    background.add_task(pipeline.process_application, application.id, org_id)
    return ApplicationAccepted(application_id=application.id, status=application.status)


@router.get("/applications", response_model=list[Application])
def list_applications(
    job_id: str,
    status_filter: ApplicationStatus | None = None,
    recruiter: Recruiter = Depends(current_recruiter),
) -> list[Application]:
    """The review queue. Filter to `review` for applications the model flagged
    for a human — that is where the human-in-the-loop requirement lives.

    `rejected_screen` is worth looking at too: if an AI-extracted requirement is
    quietly culling everyone, this is where it shows.
    """
    return repo.list_applications(recruiter.org_id, job_id, status_filter)


@router.get("/applications/{application_id}", response_model=Application)
def get_application(
    application_id: str, recruiter: Recruiter = Depends(current_recruiter)
) -> Application:
    application = repo.get_application(application_id, recruiter.org_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")
    return application


class Decision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"


class DecideRequest(BaseModel):
    decision: Decision
    note: str | None = None


@router.post("/applications/{application_id}/decide", response_model=Application)
def decide(
    application_id: str,
    body: DecideRequest,
    recruiter: Recruiter = Depends(current_recruiter),
) -> Application:
    """A human resolving a `review`, or overriding the model either way.

    Accepting works from any state, including `rejected_screen` — that is what
    makes a bad hard-check reversible rather than final.

    This endpoint is the compliance story made concrete: every rejection that
    reaches a candidate passed through a person here, and that person is
    recorded.
    """
    application = repo.get_application(application_id, recruiter.org_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")

    if body.decision is Decision.ACCEPT:
        pipeline.send_invite(application_id, recruiter.org_id)
        repo.record_decision(
            application_id,
            recruiter.org_id,
            ApplicationStatus.INVITED,
            decided_by=recruiter.id,
            note=body.note,
        )
    else:
        # Which rejection it is depends on how far they got: someone who has
        # been interviewed was not rejected by the screen.
        interviewed = application.status in {
            ApplicationStatus.INTERVIEWED,
            ApplicationStatus.SCORED,
            ApplicationStatus.ADVANCED,
        }
        repo.record_decision(
            application_id,
            recruiter.org_id,
            ApplicationStatus.REJECTED_POST
            if interviewed
            else ApplicationStatus.REJECTED_SCREEN,
            decided_by=recruiter.id,
            note=body.note,
        )

    refreshed = repo.get_application(application_id, recruiter.org_id)
    assert refreshed is not None
    return refreshed


@router.get("/applications/{application_id}/resume-url")
def resume_url(
    application_id: str, recruiter: Recruiter = Depends(current_recruiter)
) -> dict[str, str]:
    """Short-lived signed URL. Résumés live in a private bucket, so there is no
    permanent link to leak."""
    application = repo.get_application(application_id, recruiter.org_id)
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such application")
    return {"url": repo.signed_resume_url(application.resume_url)}
