"""Re-applying must not inherit decisions about a previous resume.

Found by testing with a real resume: a second application under the same email
kept the first application's screening decision, because the pipeline stopped at
the hard checks and never wrote a new one. The result was an "accept" citing
evidence from a document the candidate had not submitted.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from intake import repo

DERIVED_FIELDS = [
    "parsed_resume",
    "hard_checks",
    "screening",
    "screening_model_id",
    "screening_prompt_version",
    "decided_by",
    "decided_at",
    "decision_note",
    "failure_reason",
]


class FakeTable:
    def __init__(self, sink):
        self.sink = sink

    def upsert(self, payload, on_conflict=None):
        self.sink["payload"] = payload
        self.sink["on_conflict"] = on_conflict
        return self

    def execute(self):
        row = {
            "id": "app-1",
            "org_id": "org-1",
            "job_id": "job-1",
            "candidate_id": "cand-1",
            "status": "received",
            "resume_url": "x.pdf",
            "hard_checks": [],
            "consent_given_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return SimpleNamespace(data=[row])


@pytest.fixture
def captured(monkeypatch):
    sink: dict = {}
    monkeypatch.setattr(repo, "db", lambda: SimpleNamespace(table=lambda _n: FakeTable(sink)))
    return sink


def test_reapplying_clears_everything_derived_from_the_old_resume(captured):
    repo.create_application(
        org_id="org-1",
        job_id="job-1",
        candidate_id="cand-1",
        resume_url="new.pdf",
        consent_given_at=datetime.now(timezone.utc),
    )
    payload = captured["payload"]

    for field in DERIVED_FIELDS:
        assert field in payload, f"{field} is not reset on re-application"
        assert payload[field] in (None, []), (
            f"{field} carries over from the previous resume"
        )


def test_status_returns_to_received(captured):
    repo.create_application(
        org_id="org-1",
        job_id="job-1",
        candidate_id="cand-1",
        resume_url="new.pdf",
        consent_given_at=datetime.now(timezone.utc),
    )
    assert captured["payload"]["status"] == "received"


def test_upsert_is_keyed_on_job_and_candidate(captured):
    """One application per person per job (D20) — re-applying updates rather
    than creating a duplicate leaderboard entry."""
    repo.create_application(
        org_id="org-1",
        job_id="job-1",
        candidate_id="cand-1",
        resume_url="new.pdf",
        consent_given_at=datetime.now(timezone.utc),
    )
    assert captured["on_conflict"] == "job_id,candidate_id"
