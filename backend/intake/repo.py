"""Supabase access for lane 1's tables.

**Every function takes `org_id` and every query filters on it.** The composite
foreign keys stop a cross-org row being *written*; this stops one being *read*.
Both are needed — a missing filter on a read is just as much a leak, and the
database cannot catch that one for us.

Only this lane writes to job / candidate / application / interview_invite.
Other lanes read them; if they need a write, they ask.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from shared.db import db
from shared.models.candidate import (
    Application,
    ApplicationStatus,
    Candidate,
    HardCheckResult,
    ParsedResume,
    ScreeningDecision,
)
from shared.models.job import (
    Job,
    JobCreate,
    JobPipelineStats,
    JobStatus,
    ProfileSource,
    Question,
    QuestionBankStatus,
    ScreeningProfile,
)


# Mirrors posting.DEFAULT_VALIDITY. A job with no expiry is one Google will
# eventually issue a manual action over.
POSTING_VALIDITY = timedelta(days=60)


# --- job ------------------------------------------------------------------


def create_job(
    payload: JobCreate,
    org_id: str,
    created_by: str,
    profile: ScreeningProfile | None = None,
    profile_source: ProfileSource = ProfileSource.MANUAL,
    profile_model_id: str | None = None,
) -> Job:
    resolved = profile or payload.screening_profile or ScreeningProfile()
    row = (
        db()
        .table("job")
        .insert(
            {
                "org_id": org_id,
                "title": payload.title,
                "seniority": payload.seniority,
                "role_family": payload.role_family,
                "jd_text": payload.jd_text,
                "location": payload.location,
                "remote": payload.remote,
                "employment_type": (
                    payload.employment_type.value if payload.employment_type else None
                ),
                # Never publish a posting without an expiry: Google penalises a
                # domain whose undated stale jobs accumulate.
                "valid_through": (
                    datetime.now(timezone.utc) + POSTING_VALIDITY
                ).isoformat(),
                "screening_profile": resolved.model_dump(mode="json"),
                "screening_profile_source": profile_source.value,
                "screening_profile_model_id": profile_model_id,
                "created_by": created_by,
            }
        )
        .execute()
        .data[0]
    )
    return Job.model_validate(row)


def get_job(job_id: str, org_id: str) -> Job | None:
    res = (
        db()
        .table("job")
        .select("*")
        .eq("id", job_id)
        .eq("org_id", org_id)
        .execute()
    )
    return Job.model_validate(res.data[0]) if res.data else None


def get_job_unscoped(job_id: str) -> Job | None:
    """Look up a job without knowing the organization.

    Used by exactly one caller: the public application form. A candidate has no
    account and no notion of an org — the job id in their URL is what
    establishes which tenant they are applying to, and every write downstream
    then uses `job.org_id`.

    Nothing behind authentication may use this. Recruiter routes take the org
    from the caller's membership, never from a path parameter.
    """
    res = db().table("job").select("*").eq("id", job_id).execute()
    return Job.model_validate(res.data[0]) if res.data else None


def list_jobs(org_id: str, status: JobStatus | None = None) -> list[Job]:
    """Defaults to every status. The UI filters to `open`; closed roles keep
    their leaderboards and stay one click away."""
    q = db().table("job").select("*").eq("org_id", org_id)
    if status:
        q = q.eq("status", status.value)
    return [
        Job.model_validate(r)
        for r in q.order("created_at", desc=True).execute().data
    ]


def update_job(job_id: str, org_id: str, fields: dict[str, Any]) -> None:
    """Patch the job's descriptive fields.

    Only writes what was supplied, so a caller sending one field does not blank
    the rest.
    """
    if fields:
        db().table("job").update(fields).eq("id", job_id).eq(
            "org_id", org_id
        ).execute()


def open_jobs_for_sitemap() -> list[dict]:
    """Every open job across every organization.

    Unscoped on purpose, like get_job_unscoped: a sitemap is a public document
    and a crawler belongs to no tenant. Returns ids and timestamps only —
    nothing here reveals one customer's hiring to another beyond the postings
    they have already chosen to publish.
    """
    res = (
        db()
        .table("job")
        .select("id,updated_at")
        .eq("status", JobStatus.OPEN.value)
        .order("updated_at", desc=True)
        .limit(5000)
        .execute()
    )
    return res.data


def close_job(job_id: str, org_id: str) -> None:
    """Stops new applications. Everything already collected stays."""
    db().table("job").update(
        {
            "status": JobStatus.CLOSED.value,
            "closed_at": datetime.now(timezone.utc).isoformat(),
        }
    ).eq("id", job_id).eq("org_id", org_id).execute()


def set_question_bank_status(
    job_id: str, org_id: str, status: QuestionBankStatus, error: str | None = None
) -> None:
    db().table("job").update(
        {"question_bank_status": status.value, "question_bank_error": error}
    ).eq("id", job_id).eq("org_id", org_id).execute()


def save_question_bank(
    job_id: str, org_id: str, questions: list[Question], rubric_version: str
) -> None:
    db().table("job").update(
        {
            "question_bank": [q.model_dump(mode="json") for q in questions],
            "question_bank_status": QuestionBankStatus.READY.value,
            "question_bank_error": None,
            "rubric_version": rubric_version,
        }
    ).eq("id", job_id).eq("org_id", org_id).execute()


def save_screening_profile(
    job_id: str,
    org_id: str,
    profile: ScreeningProfile,
    source: ProfileSource,
    model_id: str | None = None,
    reviewed_by: str | None = None,
) -> None:
    fields: dict[str, Any] = {
        "screening_profile": profile.model_dump(mode="json"),
        "screening_profile_source": source.value,
        "screening_profile_model_id": model_id,
    }
    if reviewed_by:
        fields["screening_profile_reviewed_by"] = reviewed_by
        fields["screening_profile_reviewed_at"] = datetime.now(timezone.utc).isoformat()
    db().table("job").update(fields).eq("id", job_id).eq("org_id", org_id).execute()


# --- candidate ------------------------------------------------------------


def upsert_candidate(
    org_id: str,
    email: str,
    full_name: str | None = None,
    phone: str | None = None,
    location: str | None = None,
) -> str:
    """One row per person **per organization** (D20 as amended).

    Scoped rather than global so company A cannot infer that someone also
    applied to company B. Email is `citext` in the database, so casing is
    handled there rather than by every caller remembering to normalise.
    """
    fields: dict[str, Any] = {"org_id": org_id, "email": email}
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
        .upsert(fields, on_conflict="org_id,email")
        .execute()
        .data[0]
    )
    return row["id"]


def get_candidate(candidate_id: str, org_id: str) -> Candidate | None:
    res = (
        db()
        .table("candidate")
        .select("*")
        .eq("id", candidate_id)
        .eq("org_id", org_id)
        .execute()
    )
    return Candidate.model_validate(res.data[0]) if res.data else None


def enrich_candidate(
    candidate_id: str,
    org_id: str,
    full_name: str | None = None,
    phone: str | None = None,
    location: str | None = None,
) -> None:
    """Fill in what the résumé revealed that the form did not ask for.

    Only writes non-empty values, so a sparse résumé never blanks out details
    the candidate typed themselves.
    """
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
        db().table("candidate").update(fields).eq("id", candidate_id).eq(
            "org_id", org_id
        ).execute()


# --- application ----------------------------------------------------------


def create_application(
    org_id: str,
    job_id: str,
    candidate_id: str,
    resume_url: str,
    consent_given_at: datetime,
) -> Application:
    row = (
        db()
        .table("application")
        .upsert(
            {
                "org_id": org_id,
                "job_id": job_id,
                "candidate_id": candidate_id,
                "resume_url": resume_url,
                "consent_given_at": consent_given_at.isoformat(),
                "status": ApplicationStatus.RECEIVED.value,
                # Everything below is derived from the *previous* resume, so a
                # new upload invalidates all of it. Without this reset, someone
                # re-applying with an updated CV inherits the decision made
                # about their old one — and if the new resume is stopped by the
                # hard checks, that stale decision is never overwritten and sits
                # there attached to a document it was never about.
                "parsed_resume": None,
                "hard_checks": [],
                "screening": None,
                "screening_model_id": None,
                "screening_prompt_version": None,
                "decided_by": None,
                "decided_at": None,
                "decision_note": None,
                "failure_reason": None,
            },
            on_conflict="job_id,candidate_id",
        )
        .execute()
        .data[0]
    )
    return Application.model_validate(row)


def get_application(application_id: str, org_id: str) -> Application | None:
    res = (
        db()
        .table("application")
        .select("*")
        .eq("id", application_id)
        .eq("org_id", org_id)
        .execute()
    )
    return Application.model_validate(res.data[0]) if res.data else None


def list_applications(
    org_id: str, job_id: str, status: ApplicationStatus | None = None
) -> list[Application]:
    q = (
        db()
        .table("application")
        .select("*")
        .eq("org_id", org_id)
        .eq("job_id", job_id)
    )
    if status:
        q = q.eq("status", status.value)
    return [
        Application.model_validate(r)
        for r in q.order("created_at", desc=True).execute().data
    ]


def pipeline_stats(org_id: str, job_id: str) -> JobPipelineStats:
    """Every dashboard tile from one grouped count."""
    res = (
        db()
        .table("job_pipeline_stats")
        .select("*")
        .eq("org_id", org_id)
        .eq("job_id", job_id)
        .execute()
    )
    if res.data:
        return JobPipelineStats.model_validate(res.data[0])
    return JobPipelineStats(org_id=org_id, job_id=job_id)


def set_status(
    application_id: str,
    org_id: str,
    status: ApplicationStatus,
    failure_reason: str | None = None,
) -> None:
    db().table("application").update(
        {"status": status.value, "failure_reason": failure_reason}
    ).eq("id", application_id).eq("org_id", org_id).execute()


def record_decision(
    application_id: str,
    org_id: str,
    status: ApplicationStatus,
    decided_by: str,
    note: str | None = None,
) -> None:
    """A human decision, with the human recorded.

    compliance.md promises a person reviews every rejection. Without storing
    which person, that promise cannot be evidenced when a candidate disputes it.
    """
    db().table("application").update(
        {
            "status": status.value,
            "decided_by": decided_by,
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "decision_note": note,
        }
    ).eq("id", application_id).eq("org_id", org_id).execute()


def save_parsed_resume(
    application_id: str, org_id: str, resume: ParsedResume
) -> None:
    db().table("application").update(
        {
            "parsed_resume": resume.model_dump(mode="json"),
            "status": ApplicationStatus.SCREENING.value,
        }
    ).eq("id", application_id).eq("org_id", org_id).execute()


def save_hard_checks(
    application_id: str, org_id: str, checks: list[HardCheckResult]
) -> None:
    db().table("application").update(
        {"hard_checks": [c.model_dump(mode="json") for c in checks]}
    ).eq("id", application_id).eq("org_id", org_id).execute()


def save_screening(
    application_id: str,
    org_id: str,
    decision: ScreeningDecision,
    status: ApplicationStatus,
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
            "status": status.value,
        }
    ).eq("id", application_id).eq("org_id", org_id).execute()


# --- invites --------------------------------------------------------------


def create_invite(
    org_id: str, application_id: str, token_hash: str, expires_at: datetime
) -> str:
    row = (
        db()
        .table("interview_invite")
        .insert(
            {
                "org_id": org_id,
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


def resume_path(org_id: str, job_id: str, candidate_id: str, filename: str) -> str:
    """Org first, so bucket policies can scope by tenant the same way tables do."""
    return f"{org_id}/{job_id}/{candidate_id}/{filename}"


def upload_resume(path: str, data: bytes) -> str:
    """Private bucket. The path is stored; readers get a short-lived signed URL."""
    db().storage.from_(RESUME_BUCKET).upload(
        path, data, {"content-type": "application/pdf", "upsert": "true"}
    )
    return path


def download_resume(path: str) -> bytes:
    return db().storage.from_(RESUME_BUCKET).download(path)


def signed_resume_url(path: str, expires_in: int = 3600) -> str:
    res = db().storage.from_(RESUME_BUCKET).create_signed_url(path, expires_in)
    return res["signedURL"]
