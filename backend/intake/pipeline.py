"""The intake pipeline: application -> parsed -> gated -> screened -> invited.

Runs in the background after the application endpoint has already returned, so
the candidate never waits on a model call.

Ordering is deliberate. Hard checks are free and run before the LLM screen, so
the model only ever sees candidates genuinely in contention (D18).
"""

from __future__ import annotations

import logging
from shared.models.candidate import ApplicationStatus, ScreeningOutcome

from . import hard_checks, invites, parsing, repo, screening

log = logging.getLogger(__name__)


def process_application(application_id: str) -> None:
    """Full pipeline for one application.

    Exceptions are caught and logged rather than raised: this runs detached from
    any request, so an unhandled error would vanish silently and strand the
    application mid-status. A stuck application is recoverable by re-running;
    an invisible crash is not.
    """
    try:
        _process(application_id)
    except Exception:
        log.exception("intake pipeline failed for application %s", application_id)


def _process(application_id: str) -> None:
    application = repo.get_application(application_id)
    if application is None:
        log.error("application %s disappeared mid-pipeline", application_id)
        return

    job = repo.get_job(application.job_id)
    if job is None:
        log.error("job %s missing for application %s", application.job_id, application_id)
        return

    # 1. Parse -------------------------------------------------------------
    pdf = repo.download_resume(application.resume_url)
    resume, _ = parsing.parse_resume(pdf)
    repo.save_parsed_resume(application_id, resume)

    # Backfill what the candidate did not type but the resume does contain.
    # Keyed on the address they applied with, not the one in the resume — those
    # can differ, and the application address is the one we can actually reach.
    repo.enrich_candidate(
        application.candidate_id,
        full_name=resume.full_name,
        phone=resume.phone,
        location=resume.location,
    )

    # 2. Hard checks -------------------------------------------------------
    checks = hard_checks.run_hard_checks(resume, job.screening_profile)
    repo.save_hard_checks(application_id, checks)

    if not hard_checks.passed(checks):
        failed = ", ".join(c.check for c in hard_checks.failures(checks))
        log.info("application %s failed hard checks: %s", application_id, failed)
        repo.set_status(application_id, ApplicationStatus.REJECTED)
        return

    # 3. LLM screen --------------------------------------------------------
    decision, provenance = screening.screen_application(resume, job)
    repo.save_screening(
        application_id, decision, provenance.model_id, provenance.prompt_version
    )

    # 4. Act ---------------------------------------------------------------
    if decision.outcome is ScreeningOutcome.ACCEPT:
        send_invite(application_id)
    elif decision.outcome is ScreeningOutcome.REJECT:
        # No email. A human reviews every rejection before anything is sent —
        # compliance.md, GDPR Art. 22, NY AEDTA.
        repo.set_status(application_id, ApplicationStatus.REJECTED)
    # REVIEW: left at SCREENED, which is what the recruiter queue reads.


def send_invite(application_id: str) -> None:
    """Mint an invite and email it. Also the path a recruiter takes when
    accepting a `review` application by hand."""
    application = repo.get_application(application_id)
    if application is None:
        raise ValueError(f"No application {application_id}")

    job = repo.get_job(application.job_id)
    if job is None:
        raise ValueError(f"No job {application.job_id}")

    candidate = repo.get_candidate(application.candidate_id)
    if candidate is None:
        raise ValueError(f"No candidate {application.candidate_id}")

    token, token_hash, expires_at = invites.mint_token()
    repo.create_invite(application_id, token_hash, expires_at)

    invites.send_invite_email(
        to_email=candidate["email"],
        candidate_name=candidate.get("full_name"),
        job=job,
        token=token,          # the only moment the raw token exists
        expires_at=expires_at,
    )
    repo.set_status(application_id, ApplicationStatus.INVITED)
    log.info("invited application %s, expires %s", application_id, expires_at)


def reject(application_id: str) -> None:
    """Recruiter-initiated rejection from the review queue."""
    repo.set_status(application_id, ApplicationStatus.REJECTED)
