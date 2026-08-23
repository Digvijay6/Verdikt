"""The lane 1 -> lane 2 handoff.

No network. These pin the two things lane 2 cannot check for itself: that the
package never carries the candidate's name, and that its `rubric_version`
describes the anchors actually attached to its questions.
"""

import pytest

from intake.packaging import (
    PackageUnavailable,
    _questions_for,
    _rubric_version_for,
    resume_summary,
)
from shared.models.candidate import EmploymentPeriod, ParsedResume
from shared.models.job import Question, QuestionType, RubricDimension


class _App:
    """Only the fields packaging reads. A full Application needs a row's worth
    of unrelated required fields, which would obscure what is being tested."""

    def __init__(self, questions=None, questions_rubric_version=None):
        self.id = "a1"
        self.questions = questions
        self.questions_rubric_version = questions_rubric_version


class _Job:
    def __init__(self, rubric_version="v1", question_bank=None):
        self.id = "j1"
        self.rubric_version = rubric_version
        self.question_bank = question_bank


def _question(qid: str = "q1") -> Question:
    return Question(
        id=qid,
        order=1,
        type=QuestionType.TECHNICAL,
        prompt="What stopped the double charge?",
        competency="delivery_semantics",
        must_have=True,
        dimensions=[
            RubricDimension(
                key="correctness",
                weight=1.0,
                anchors={i: f"level {i}" for i in range(1, 6)},
            )
        ],
    )


# --- rubric_version must describe the anchors on the questions -------------


def test_uses_the_version_the_questions_were_written_against():
    """The bug this exists to prevent: a recruiter rebuilds the rubric between
    invite and redeem, and the interview gets stamped with a version whose
    anchors it was never scored against."""
    application = _App(questions=[_question()], questions_rubric_version="v1")
    job = _Job(rubric_version="v2")  # rebuilt after the invite went out
    assert _rubric_version_for(application, job) == "v1"


def test_falls_back_to_the_job_for_applications_invited_before_this_existed():
    application = _App(questions=[_question()], questions_rubric_version=None)
    assert _rubric_version_for(application, _Job(rubric_version="v2")) == "v2"


def test_falls_back_to_the_job_when_using_the_job_wide_bank():
    """No generated questions means the job's bank is in play, and the job's
    version is the right one to report."""
    application = _App(questions=None, questions_rubric_version="v1")
    assert _rubric_version_for(application, _Job(rubric_version="v3")) == "v3"


# --- which questions ------------------------------------------------------


def test_prefers_per_candidate_questions():
    application = _App(questions=[_question("q1")])
    job = _Job(question_bank=[_question("bank1")])
    assert [q.id for q in _questions_for(application, job)] == ["q1"]


def test_falls_back_to_the_job_bank():
    """Lets lane 2 adopt build_interview_package() before the rubric switch
    reaches jobs they already created."""
    application = _App(questions=None)
    job = _Job(question_bank=[_question("bank1")])
    assert [q.id for q in _questions_for(application, job)] == ["bank1"]


def test_raises_when_there_are_no_questions_at_all():
    """An interview that starts with nothing to ask is worse for the candidate
    than one that never starts."""
    with pytest.raises(PackageUnavailable):
        _questions_for(_App(questions=None), _Job(question_bank=None))


# --- D14: the agent never learns who it is talking to ---------------------


def test_resume_summary_omits_name_and_contact():
    resume = ParsedResume(
        full_name="Priya Raman",
        email="priya@example.com",
        phone="+1 555 0100",
        location="Bengaluru",
        total_years_experience=4.0,
        skills=["Go", "Kafka"],
        employment=[
            EmploymentPeriod(
                company="Ledgerly", title="Backend Engineer", summary="Payments."
            )
        ],
    )
    summary = resume_summary(resume)
    for leaked in ("Priya", "Raman", "priya@example.com", "555", "Bengaluru"):
        assert leaked not in summary, f"{leaked!r} reached the interviewer agent"
    assert "Backend Engineer" in summary
    assert "Go" in summary


def test_resume_summary_handles_no_resume():
    assert resume_summary(None)
