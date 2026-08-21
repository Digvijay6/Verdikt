"""Hard checks are the only place in lane 1 that rejects a candidate outright,
so the boundaries matter more than the happy path."""

import pytest

from intake.hard_checks import failures, passed, run_hard_checks
from shared.models.candidate import EmploymentPeriod, ParsedResume
from shared.models.job import ScreeningProfile


def resume(**kw) -> ParsedResume:
    return ParsedResume(**{"full_name": "A. Candidate", **kw})


# --- years of experience --------------------------------------------------


@pytest.mark.parametrize(
    "actual,required,expect_pass",
    [
        (5.0, 3.0, True),
        (3.0, 3.0, True),   # exactly at the boundary passes
        (2.9, 3.0, False),
        (0.0, 0.0, True),
    ],
)
def test_min_years_boundaries(actual, required, expect_pass):
    r = run_hard_checks(
        resume(total_years_experience=actual),
        ScreeningProfile(min_years_experience=required),
    )
    assert passed(r) is expect_pass


def test_unknown_years_passes_rather_than_rejects():
    """An unparseable date range must not cost someone the job."""
    r = run_hard_checks(
        resume(total_years_experience=None),
        ScreeningProfile(min_years_experience=10.0),
    )
    assert passed(r)
    assert "could not compute" in r[0].detail


# --- required skills ------------------------------------------------------


def test_skill_matched_case_and_punctuation_insensitively():
    r = run_hard_checks(
        resume(skills=["Node.js", "PostgreSQL"]),
        ScreeningProfile(required_skills=["nodejs", "postgresql"]),
    )
    assert passed(r)


def test_java_does_not_match_javascript():
    """The classic substring bug. Matching 'java' inside 'javascript' would
    admit candidates who do not have the required skill."""
    r = run_hard_checks(
        resume(skills=["JavaScript"]),
        ScreeningProfile(required_skills=["Java"]),
    )
    assert not passed(r)


def test_skill_found_in_employment_prose_when_parser_missed_it():
    """Parsers routinely miss skills mentioned only in prose."""
    r = run_hard_checks(
        resume(
            skills=[],
            employment=[
                EmploymentPeriod(
                    company="Acme",
                    title="Engineer",
                    summary="Rebuilt the dashboard in React and shipped it.",
                )
            ],
        ),
        ScreeningProfile(required_skills=["React"]),
    )
    assert passed(r)


def test_missing_skill_fails_and_is_reported():
    r = run_hard_checks(
        resume(skills=["Python"]),
        ScreeningProfile(required_skills=["Python", "Kubernetes"]),
    )
    assert not passed(r)
    assert [f.check for f in failures(r)] == ["required_skill:Kubernetes"]


def test_preferred_skills_never_gate():
    r = run_hard_checks(
        resume(skills=[]),
        ScreeningProfile(preferred_skills=["Rust", "Go"]),
    )
    assert passed(r)
    assert r == []


# --- location -------------------------------------------------------------


def test_remote_ok_ignores_location():
    r = run_hard_checks(
        resume(location="Reykjavik"),
        ScreeningProfile(locations=["Berlin"], remote_ok=True),
    )
    assert passed(r)


def test_onsite_requires_matching_location():
    r = run_hard_checks(
        resume(location="Reykjavik, Iceland"),
        ScreeningProfile(locations=["Berlin"], remote_ok=False),
    )
    assert not passed(r)


def test_onsite_matches_city_within_full_location_string():
    r = run_hard_checks(
        resume(location="Berlin, Germany"),
        ScreeningProfile(locations=["Berlin"], remote_ok=False),
    )
    assert passed(r)


def test_unknown_location_passes_rather_than_rejects():
    r = run_hard_checks(
        resume(location=None),
        ScreeningProfile(locations=["Berlin"], remote_ok=False),
    )
    assert passed(r)


# --- work authorization ---------------------------------------------------


def test_work_authorization_is_never_auto_failed():
    """Inferring authorization from a resume is unreliable and legally
    hazardous. It is surfaced for a human, never gated on."""
    r = run_hard_checks(
        resume(location="Toronto"),
        ScreeningProfile(work_authorization="US citizen or GC"),
    )
    assert passed(r)
    assert any(c.check == "work_authorization" for c in r)


# --- empty profile --------------------------------------------------------


def test_empty_profile_admits_everyone():
    assert run_hard_checks(resume(), ScreeningProfile()) == []
