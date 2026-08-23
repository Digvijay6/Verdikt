"""Assembling the lane 1 -> lane 2 handoff.

Lane 2's redeem endpoint used to read `job.question_bank`, validate it into
`Question` objects, and format a resume summary itself. All three are lane 1
models, so every change to them broke lane 2's file. Behind this function they
stop being lane 2's problem.

Reads per-candidate questions when they exist and falls back to the job-wide
bank when they do not. That is deliberate: lane 2 can adopt this before the
rubric switch lands, so the shape can move underneath them without their code
changing again.
"""

from __future__ import annotations

import logging

from shared.models.candidate import ParsedResume
from shared.models.interview import InterviewPackage
from shared.models.job import Question

from . import repo

log = logging.getLogger(__name__)

MAX_SKILLS = 12


class PackageUnavailable(Exception):
    """The interview cannot be conducted, and the reason is worth stating."""


def resume_summary(resume: ParsedResume | None) -> str:
    """A few lines of context for the interviewer agent.

    Deliberately omits the candidate's name and anything demographic (D14). The
    agent does not need them, and blind conduct is far easier to defend than
    blind conduct retrofitted after a complaint.
    """
    if resume is None:
        return "No parsed resume available."

    parts: list[str] = []
    if resume.total_years_experience is not None:
        parts.append(f"{resume.total_years_experience:g} years of experience.")
    if resume.skills:
        parts.append("Skills: " + ", ".join(resume.skills[:MAX_SKILLS]) + ".")

    for role in resume.employment[:3]:
        line = f"{role.title} at {role.company}"
        if role.summary:
            line += f" - {role.summary}"
        parts.append(line)

    return " ".join(parts) if parts else "Resume parsed but empty."


def _questions_for(application, job) -> list[Question]:
    """Per-candidate questions if generated, otherwise the job-wide bank."""
    if application.questions:
        return application.questions
    if job.question_bank:
        log.warning(
            "application %s has no generated questions; falling back to the "
            "job-wide bank",
            application.id,
        )
        return job.question_bank
    raise PackageUnavailable(
        f"Job {job.id} has neither a generated question set for this candidate "
        f"nor a question bank. Check job.question_bank_status."
    )


def build_interview_package(
    application_id: str, org_id: str, interview_id: str
) -> InterviewPackage:
    """Everything the voice worker needs, and nothing it does not.

    Raises PackageUnavailable rather than returning a package with no questions:
    an interview that starts and has nothing to ask is worse for the candidate
    than one that never starts.
    """
    application = repo.get_application(application_id, org_id)
    if application is None:
        raise PackageUnavailable(f"No application {application_id}")

    job = repo.get_job(application.job_id, org_id)
    if job is None:
        raise PackageUnavailable(f"No job {application.job_id}")

    return InterviewPackage(
        interview_id=interview_id,
        org_id=org_id,
        job_id=job.id,
        job_title=job.title,
        seniority=job.seniority,
        questions=_questions_for(application, job),
        resume_summary=resume_summary(application.parsed_resume),
        resume_highlights=application.parsed_resume,
        rubric_version=job.rubric_version,
        language="en",
    )
