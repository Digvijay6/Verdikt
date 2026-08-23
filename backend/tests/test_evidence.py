"""Candidate evidence gathering.

The asymmetry is the point (D32): a supported claim raises confidence, a
contradicted one lowers it, and finding nothing does neither. Most of these
tests exist to make sure "nothing found" never becomes a negative signal,
because that failure would be invisible — it looks like a reasonable score.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from intake import evidence, github
from intake.evidence import TOOL_BUDGET, Verdict, _spend
from shared.models.candidate import ParsedResume


# --- pulling a username out of whatever they pasted -----------------------


@pytest.mark.parametrize(
    "given,expected",
    [
        ("https://github.com/adityaarya03", "adityaarya03"),
        ("https://github.com/adityaarya03/", "adityaarya03"),
        ("github.com/adityaarya03", "adityaarya03"),
        ("  github.com/adityaarya03  ", "adityaarya03"),
        ("https://www.github.com/torvalds", "torvalds"),
        ("https://github.com/octo-cat/some-repo", "octo-cat"),
        ("@adityaarya03", "adityaarya03"),
        ("adityaarya03", "adityaarya03"),
    ],
)
def test_username_parsed_from_every_shape_people_write(given, expected):
    """Losing evidence over a trailing slash would be a silly way to fail."""
    assert github.username_from_url(given) == expected


@pytest.mark.parametrize("given", ["", "   ", "https://gitlab.com/someone", "not a url at all"])
def test_non_github_links_yield_nothing(given):
    assert github.username_from_url(given) is None


def test_github_link_found_among_several():
    resume = ParsedResume(
        links=["https://mysite.dev", "linkedin.com/in/x", "github.com/adityaarya03"]
    )
    assert evidence.github_username(resume) == "adityaarya03"


def test_no_github_link_means_nothing_to_check():
    resume = ParsedResume(links=["https://mysite.dev", "linkedin.com/in/x"])
    assert evidence.github_username(resume) is None


def test_gather_returns_none_without_a_link(monkeypatch):
    """No link is not a failure — it is simply nothing to verify, and the
    pipeline must carry on screening normally."""
    assert evidence.gather(ParsedResume(links=[]), "some jd") is None


# --- the budget -----------------------------------------------------------


def test_budget_stops_at_the_cap():
    """Unbounded exploration is slow and expensive, and the marginal repository
    is rarely the informative one."""
    ctx = SimpleNamespace(state={})
    assert sum(1 for _ in range(TOOL_BUDGET + 5) if _spend(ctx)) == TOOL_BUDGET
    assert ctx.state["tool_calls_used"] == TOOL_BUDGET


def test_exhausted_budget_returns_guidance_not_an_error():
    ctx = SimpleNamespace(state={"tool_calls_used": TOOL_BUDGET})
    out = evidence.get_profile("someone", ctx)
    assert out["error"] == "budget_exhausted"
    assert "Summarise" in out["note"]


# --- failures must never become negative signal ---------------------------


def test_unavailable_profile_says_so_explicitly(monkeypatch):
    """A rate limit, a rename, a private account — none are the candidate's
    fault, and the tool output has to say so or the model may infer otherwise."""
    monkeypatch.setattr(github, "profile", lambda _u: None)
    out = evidence.get_profile("someone", SimpleNamespace(state={}))
    assert out["found"] is False
    assert "not evidence against" in out["note"].lower()


def test_unavailable_repository_says_so_explicitly(monkeypatch):
    monkeypatch.setattr(github, "repository_detail", lambda _u, _r: None)
    out = evidence.inspect_repository("someone", "repo", SimpleNamespace(state={}))
    assert out["found"] is False
    assert "not evidence against" in out["note"].lower()


def test_gather_swallows_failures(monkeypatch):
    """Verification is an enhancement to screening, never a precondition. An
    outage here must not stop someone's application being read."""
    def boom(*_a, **_k):
        raise RuntimeError("github is down")

    monkeypatch.setattr(evidence, "gather_async", boom)
    resume = ParsedResume(links=["github.com/someone"])
    assert evidence.gather(resume, "jd") is None


# --- the client -----------------------------------------------------------


def test_http_failure_returns_none_rather_than_raising(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(github.httpx, "get", boom)
    assert github.profile("someone") is None
    assert github.repositories("someone") == []


def test_non_200_is_treated_as_absent(monkeypatch):
    monkeypatch.setattr(
        github.httpx, "get", lambda *a, **k: MagicMock(status_code=404)
    )
    assert github.profile("someone") is None


def test_forks_are_excluded(monkeypatch):
    """A forked repository says nothing about what someone built, and forks are
    the most common way a skill looks evidenced when it is not."""
    payload = [
        {"name": "mine", "fork": False, "language": "Python"},
        {"name": "someone-elses", "fork": True, "language": "Go"},
    ]
    monkeypatch.setattr(
        github.httpx,
        "get",
        lambda *a, **k: MagicMock(status_code=200, json=lambda: payload),
    )
    names = [r["name"] for r in github.repositories("someone")]
    assert names == ["mine"]


# --- verdict vocabulary ---------------------------------------------------


def test_not_found_is_a_distinct_verdict_from_contradicted():
    """Collapsing these would turn silence into a negative signal, which is the
    exact failure this design exists to prevent."""
    assert Verdict.NOT_FOUND != Verdict.CONTRADICTED
    assert {v.value for v in Verdict} == {"supported", "contradicted", "not_found"}
