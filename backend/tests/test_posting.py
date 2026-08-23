"""Google for Jobs structured data.

A malformed posting does not error — Google just silently declines to index it,
and nobody notices the traffic that never arrived. So the required fields are
asserted explicitly rather than assumed.
"""

from datetime import datetime, timedelta, timezone

import pytest

from intake.posting import indexing_problems, job_posting_jsonld, valid_through
from shared.models.job import EmploymentType, Job, JobStatus
from shared.models.organization import Organization

NOW = datetime(2026, 8, 23, tzinfo=timezone.utc)

ORG = Organization(id="o1", name="Acme Corp", slug="acme", created_at=NOW)

JD = (
    "We are hiring a Backend Engineer.\n\n"
    "You will build services in Python and PostgreSQL, and help run them.\n"
    "At least 1 year of experience. Internships count."
)


def job(**kw) -> Job:
    return Job(
        **{
            "id": "j1",
            "org_id": "o1",
            "title": "Backend Engineer",
            "seniority": "mid",
            "jd_text": JD,
            "created_at": NOW,
            **kw,
        }
    )


def ld(**kw) -> dict:
    return job_posting_jsonld(job(**kw), ORG, "https://verdikt.app/apply/j1")


# --- what Google requires -------------------------------------------------


@pytest.mark.parametrize(
    "field", ["title", "description", "datePosted", "hiringOrganization"]
)
def test_required_fields_present(field):
    assert ld(location="Berlin, Germany")[field]


def test_remote_roles_carry_both_properties_google_needs():
    """TELECOMMUTE alone is not enough — without applicantLocationRequirements
    a remote listing is not eligible at all."""
    d = ld(remote=True, location="Bangalore, India")
    assert d["jobLocationType"] == "TELECOMMUTE"
    assert d["applicantLocationRequirements"]["name"] == "India"


def test_onsite_roles_carry_a_postal_address():
    d = ld(location="Berlin, Germany")
    addr = d["jobLocation"]["address"]
    assert addr["addressLocality"] == "Berlin"
    assert addr["addressCountry"] == "Germany"
    assert "jobLocationType" not in d


def test_country_only_location_still_produces_an_address():
    assert ld(location="India")["jobLocation"]["address"]["addressCountry"] == "India"


# --- description ----------------------------------------------------------


def test_description_is_html_as_google_requires():
    assert ld(location="Berlin, Germany")["description"].startswith("<p>")


def test_recruiter_text_is_escaped_before_it_becomes_html():
    """The JD is recruiter-supplied and lands in a page other people load."""
    d = ld(location="Berlin, Germany", jd_text="<script>alert(1)</script>\n\nreal text")
    assert "<script>" not in d["description"]
    assert "&lt;script&gt;" in d["description"]


# --- expiry ---------------------------------------------------------------


def test_undated_jobs_get_an_expiry_rather_than_none():
    """Google issues a manual action against a domain whose stale undated jobs
    accumulate, so a posting is never published without one."""
    assert valid_through(job()) > NOW
    assert ld(location="Berlin, Germany")["validThrough"]


def test_explicit_expiry_wins():
    when = NOW + timedelta(days=5)
    assert valid_through(job(valid_through=when)) == when


def test_closed_jobs_expire_when_they_closed():
    """Not 60 days later — that would keep advertising a filled vacancy."""
    closed = NOW + timedelta(days=3)
    j = job(status=JobStatus.CLOSED, closed_at=closed)
    assert valid_through(j) == closed


# --- pre-flight warnings --------------------------------------------------


def test_a_complete_posting_reports_no_problems():
    j = job(
        location="Berlin, Germany",
        employment_type=EmploymentType.FULL_TIME,
        valid_through=NOW + timedelta(days=30),
    )
    assert indexing_problems(j) == []


def test_remote_without_a_country_is_flagged():
    problems = indexing_problems(
        job(remote=True, location=None, employment_type=EmploymentType.FULL_TIME)
    )
    assert any("country" in p for p in problems)


def test_missing_location_entirely_is_flagged():
    problems = indexing_problems(job(employment_type=EmploymentType.FULL_TIME))
    assert any("location" in p.lower() for p in problems)


def test_closed_job_is_flagged_as_unlistable():
    problems = indexing_problems(job(status=JobStatus.CLOSED, location="Berlin, Germany"))
    assert any("not open" in p for p in problems)
