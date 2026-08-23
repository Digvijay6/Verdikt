"""Public job postings and their Google for Jobs structured data.

LinkedIn's job APIs are closed to new partners and Apply Connect needs a signed
partner agreement (D15). Google for Jobs is the one distribution channel that is
free, sanctioned, and needs nobody's permission: publish `JobPosting` JSON-LD on
a crawlable page and Google indexes it.

Rendered server-side rather than injected by the SPA. Google can execute
JavaScript, but server-rendered markup is what its own guidance calls the
standard approach, and an unindexed job fails silently — there is no error to
notice.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape

from shared.models.job import Job, JobStatus
from shared.models.organization import Organization

# Google removes a listing once validThrough passes, and issues a manual action
# against a whole domain that lets undated stale jobs accumulate. Every posting
# therefore gets an expiry whether or not the recruiter set one.
DEFAULT_VALIDITY = timedelta(days=60)


def _html_paragraphs(text: str) -> str:
    """Plain text to safe HTML.

    `description` must be HTML for Google, and the JD is recruiter-supplied text
    that ends up in a page other people load — so it is escaped first and only
    then given structure.
    """
    blocks = [b.strip() for b in text.split("\n\n") if b.strip()]
    return "".join(
        "<p>" + escape(b).replace("\n", "<br/>") + "</p>" for b in blocks
    )


def _country_of(location: str | None) -> str | None:
    """Last comma-separated segment, which is the country by convention.

    Google requires a country for remote roles — `applicantLocationRequirements`
    is what makes a TELECOMMUTE listing eligible at all.
    """
    if not location:
        return None
    return location.split(",")[-1].strip() or None


def valid_through(job: Job) -> datetime:
    if job.valid_through:
        return job.valid_through
    if job.status is not JobStatus.OPEN and job.closed_at:
        # A closed role expires when it closed, so Google drops it promptly
        # rather than advertising a vacancy that no longer exists.
        return job.closed_at
    return job.created_at + DEFAULT_VALIDITY


def job_posting_jsonld(job: Job, org: Organization, apply_url: str) -> dict:
    """Google's JobPosting schema.

    Required by Google: title, description, datePosted, hiringOrganization, and
    either jobLocation or (jobLocationType + applicantLocationRequirements).
    Everything else is recommended and improves placement.
    """
    data: dict = {
        "@context": "https://schema.org/",
        "@type": "JobPosting",
        "title": job.title,
        "description": _html_paragraphs(job.jd_text),
        "datePosted": job.created_at.date().isoformat(),
        "validThrough": valid_through(job).date().isoformat(),
        "identifier": {
            "@type": "PropertyValue",
            "name": org.name,
            "value": job.id,
        },
        "hiringOrganization": {
            "@type": "Organization",
            "name": org.name,
        },
        "directApply": True,  # applicants land on our form, not a redirect chain
        "url": apply_url,
    }

    if job.employment_type:
        data["employmentType"] = job.employment_type.value

    country = _country_of(job.location)

    if job.remote:
        # Both properties are required together. Without
        # applicantLocationRequirements a remote listing is not eligible, and
        # the description must also say it is remote — which the JD does.
        data["jobLocationType"] = "TELECOMMUTE"
        if country:
            data["applicantLocationRequirements"] = {
                "@type": "Country",
                "name": country,
            }

    if job.location and not job.remote:
        parts = [p.strip() for p in job.location.split(",")]
        address: dict = {"@type": "PostalAddress"}
        if len(parts) >= 2:
            address["addressLocality"] = parts[0]
            address["addressCountry"] = parts[-1]
        else:
            address["addressCountry"] = parts[0]
        data["jobLocation"] = {"@type": "Place", "address": address}

    return data


def indexing_problems(job: Job) -> list[str]:
    """What would stop Google indexing this posting.

    Surfaced to the recruiter rather than discovered by nobody noticing traffic
    that never arrived.
    """
    problems = []
    if job.status is not JobStatus.OPEN:
        problems.append("Job is not open, so it will not be listed.")
    if not job.jd_text or len(job.jd_text) < 100:
        problems.append("Description is too short to be useful in search.")
    if not job.location and not job.remote:
        problems.append(
            "No location and not marked remote. Google requires one or the other."
        )
    if job.remote and not _country_of(job.location):
        problems.append(
            "Remote roles need a country in `location` "
            "(applicantLocationRequirements), e.g. 'India'."
        )
    if not job.employment_type:
        problems.append(
            "employmentType is missing. Recommended, and it affects placement."
        )
    if valid_through(job) < datetime.now(timezone.utc):
        problems.append("validThrough is in the past — the listing has expired.")
    return problems
