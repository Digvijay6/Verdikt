"""The intake pipeline: application -> parsed -> gated -> screened -> invited.

Runs in the background after the application endpoint has already returned, so
the candidate never waits on a model call.

Ordering is deliberate. Hard checks are free and run before the LLM screen, so
the model only ever sees candidates genuinely in contention (D18).
"""

from __future__ import annotations

import logging

from shared.models.candidate import ApplicationStatus, ScreeningOutcome

from . import evidence, hard_checks, invites, parsing, repo, screening

log = logging.getLogger(__name__)


def process_application(application_id: str, org_id: str) -> None:
    """Full pipeline for one application.

    Failures are recorded on the row rather than only logged. This runs detached
    from any request, so an unhandled error would otherwise leave the
    application sitting at `received` — indistinguishable from one that had just
    arrived, and therefore invisible.
    """
    try:
        _process(application_id, org_id)
    except Exception as exc:
        log.exception("intake pipeline failed for application %s", application_id)
        repo.set_status(
            application_id,
            org_id,
            ApplicationStatus.FAILED,
            failure_reason=str(exc)[:500],
        )


def _process(application_id: str, org_id: str) -> None:
    application = repo.get_application(application_id, org_id)
    if application is None:
        log.error("application %s disappeared mid-pipeline", application_id)
        return

    job = repo.get_job(application.job_id, org_id)
    if job is None:
        log.error("job %s missing for application %s", application.job_id, application_id)
        return

    # 1. Parse -------------------------------------------------------------
    repo.set_status(application_id, org_id, ApplicationStatus.PARSING)
    pdf = repo.download_resume(application.resume_url)
    resume, _ = parsing.parse_resume(pdf)
    repo.save_parsed_resume(application_id, org_id, resume)

    # Backfill what the résumé revealed that the form did not ask for. Keyed on
    # the candidate row, not the résumé's email — those can differ, and the
    # address they applied with is the one we can actually reach.
    repo.enrich_candidate(
        application.candidate_id,
        org_id,
        full_name=resume.full_name,
        phone=resume.phone,
        location=resume.location,
    )

    # 2. Hard checks -------------------------------------------------------
    checks = hard_checks.run_hard_checks(resume, job.screening_profile)
    repo.save_hard_checks(application_id, org_id, checks)

    if not hard_checks.passed(checks):
        failed = ", ".join(c.check for c in hard_checks.failures(checks))
        log.info("application %s failed hard checks: %s", application_id, failed)
        # Not deleted, and reversible from the dashboard. If an AI-extracted
        # requirement is quietly culling everyone, the Rejected tile makes that
        # visible instead of silent.
        repo.set_status(application_id, org_id, ApplicationStatus.REJECTED_SCREEN)
        return

    # 3. Evidence ----------------------------------------------------------
    # Only runs when the candidate supplied a GitHub link on their own
    # application. Returns None on anything going wrong, because verification
    # is an enhancement to screening and must never block it.
    found = evidence.gather(resume, job.jd_text)
    if found:
        log.info(
            "evidence for application %s: %d findings",
            application_id,
            len(found.findings),
        )

    # 4. LLM screen --------------------------------------------------------
    decision, provenance = screening.screen_application(resume, job, evidence=found)

    next_status = {
        ScreeningOutcome.ACCEPT: ApplicationStatus.SCREENING,
        ScreeningOutcome.REJECT: ApplicationStatus.REJECTED_SCREEN,
        ScreeningOutcome.REVIEW: ApplicationStatus.REVIEW,
    }[decision.outcome]

    repo.save_screening(
        application_id,
        org_id,
        decision,
        next_status,
        provenance.model_id,
        provenance.prompt_version,
    )

    # 5. Act ---------------------------------------------------------------
    if decision.outcome is ScreeningOutcome.ACCEPT:
        send_invite(application_id, org_id)
    # REJECT: recorded, no email. A human reviews before anything reaches the
    # candidate — compliance.md, GDPR Art. 22, NY AEDTA.
    # REVIEW: left at `review`, which is what the recruiter queue reads.


def send_invite(application_id: str, org_id: str) -> None:
    """Mint an invite and email it.

    Also the path a recruiter takes when accepting from the review queue, or
    un-rejecting someone the hard checks caught.
    """
    application = repo.get_application(application_id, org_id)
    if application is None:
        raise ValueError(f"No application {application_id}")

    job = repo.get_job(application.job_id, org_id)
    if job is None:
        raise ValueError(f"No job {application.job_id}")

    candidate = repo.get_candidate(application.candidate_id, org_id)
    if candidate is None:
        raise ValueError(f"No candidate {application.candidate_id}")

    token, token_hash, expires_at = invites.mint_token()
    repo.create_invite(org_id, application_id, token_hash, expires_at)

    # Status is set *before* the email, and an email failure does not undo it.
    # The decision to invite someone and the delivery of that invitation are
    # separate facts: a Resend outage should not erase an accept, and it should
    # not look identical to a candidate who was never accepted at all.
    repo.set_status(application_id, org_id, ApplicationStatus.INVITED)

    try:
        invites.send_invite_email(
            to_email=str(candidate.email),
            candidate_name=candidate.full_name,
            job=job,
            token=token,  # the only moment the raw token exists
            expires_at=expires_at,
        )
    except Exception as exc:
        # The invite is valid and redeemable — the candidate simply has not been
        # told about it. Recorded so a recruiter can see it and resend, rather
        # than the person sitting in `invited` forever wondering.
        log.exception("invite email failed for application %s", application_id)
        repo.set_status(
            application_id,
            org_id,
            ApplicationStatus.INVITED,
            failure_reason=f"Invite email not delivered: {str(exc)[:400]}",
        )
        return

    log.info("invited application %s, expires %s", application_id, expires_at)
