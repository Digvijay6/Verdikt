"""The LLM screening judgement.

Runs only on candidates who cleared the deterministic hard checks (D18), so
every call here is on someone genuinely in contention.

Its output is a recommendation for a human, never a decision. `reject` still
gets reviewed before anything is sent — compliance.md, GDPR Art. 22, NY AEDTA.
"""

from __future__ import annotations

from datetime import date

from shared.llm import Provenance, run
from shared.models.candidate import ParsedResume, ScreeningDecision
from shared.models.job import Job


def _requirements_brief(job: Job, today: date) -> str:
    """Job-side context for the system prompt.

    Written by the recruiter, so it is trusted and may go in system
    instructions. The resume never does.

    The date is here for the same reason it is in parsing: the screen reasons
    about recency — how long ago someone last did the thing, whether a gap is
    recent — and a model with no anchor assumes the present is near its
    training cutoff.
    """
    p = job.screening_profile
    lines = [
        f"Today's date is {today.isoformat()}.",
        "",
        f"Role: {job.title}",
        f"Seniority: {job.seniority}",
    ]
    if p.min_years_experience is not None:
        lines.append(f"Minimum experience: {p.min_years_experience} years")
    if p.required_skills:
        lines.append(f"Required skills: {', '.join(p.required_skills)}")
    if p.preferred_skills:
        lines.append(f"Preferred skills: {', '.join(p.preferred_skills)}")
    if p.locations:
        lines.append(
            f"Locations: {', '.join(p.locations)}"
            f"{' (remote acceptable)' if p.remote_ok else ' (on-site)'}"
        )
    lines.append("\nJob description:\n" + job.jd_text)
    return "## Role requirements\n\n" + "\n".join(lines)


def screen_application(
    resume: ParsedResume,
    job: Job,
    today: date | None = None,
    evidence: object | None = None,
) -> tuple[ScreeningDecision, Provenance]:
    """`evidence` is the GitHub verification, when there was a link to check.

    Passed as context for the model to weigh, never as a score adjustment. The
    recruiter sees the same findings in the review queue, so a decision that
    leaned on evidence can be traced to the repository it came from.
    """
    content = (
        "Candidate resume, as structured data:\n\n"
        + resume.model_dump_json(indent=2)
    )
    if evidence is not None and not getattr(evidence, "checked", True):
        # Say nothing to the model rather than hand it an empty findings list,
        # which reads as "we looked and there was nothing there".
        evidence = None
    if evidence is not None:
        content += (
            "\n\n## Verified evidence from the GitHub profile they supplied\n\n"
            + evidence.model_dump_json(indent=2)
            + "\n\nA `not_found` verdict means nothing was located either way. It is "
            "NOT evidence against the claim - most professional work is in private "
            "repositories. Treat it as neutral. Only `supported` and `contradicted` "
            "should move your assessment."
        )
    return run(
        "screen-application",
        ScreeningDecision,
        # Untrusted. The candidate wrote the resume, and README content in the
        # evidence is theirs too.
        user_content=content,
        # Trusted. The recruiter wrote this, plus a date the model cannot know.
        extra_instructions=_requirements_brief(job, today or date.today()),
    )
