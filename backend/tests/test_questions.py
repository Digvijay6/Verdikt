"""Per-candidate probes against a fixed rubric.

No Gemini calls. These check the one property the whole design rests on: two
candidates asked different questions are scored against identical anchors. If
that breaks, the leaderboard silently stops meaning anything, and nothing
downstream can detect it.
"""

import pytest

from intake.questions import POISON_DIMENSION, ProbeDraft, ProbeSet, assemble
from shared.models.job import (
    Competency,
    CompetencyKind,
    JobRubric,
    QuestionType,
    RubricDimension,
)


def _dimension(key: str = "correctness", weight: float = 1.0) -> RubricDimension:
    return RubricDimension(
        key=key,
        weight=weight,
        anchors={
            1: "No relevant approach offered.",
            2: "Names one idea without reasoning.",
            3: "Describes a systematic approach.",
            4: "Names a trade-off and says which side they picked.",
            5: "Anticipates a second-order failure mode.",
        },
    )


RUBRIC = JobRubric(
    version="v3",
    competencies=[
        Competency(
            key="delivery_semantics",
            name="Message delivery semantics",
            why="Reasons about duplicate and out-of-order processing.",
            kind=CompetencyKind.TECHNICAL,
            must_have=True,
            weight=0.6,
            dimensions=[_dimension("correctness", 0.6), _dimension("depth", 0.4)],
        ),
        Competency(
            key="incident_response",
            name="Incident response",
            why="Gives a specific example with what they actually did.",
            kind=CompetencyKind.BEHAVIORAL,
            must_have=False,
            weight=0.4,
            dimensions=[_dimension("structure", 1.0)],
        ),
    ],
)


def _probe(key: str, prompt: str) -> ProbeDraft:
    return ProbeDraft(
        competency_key=key,
        type=QuestionType.TECHNICAL,
        prompt=prompt,
        grounded_in="quoted from the resume",
        follow_up_guidance="Ask what they measured.",
    )


POISON = _probe("poison", "How would you tune Kafkaesque 4.2 for backpressure?")


def _set(*probes: ProbeDraft) -> ProbeSet:
    return ProbeSet(probes=list(probes), poison=POISON)


# --- the comparability guarantee ------------------------------------------


def test_dimensions_come_from_the_rubric_not_the_model():
    """The whole design. Two candidates are asked different questions about the
    same competency and must be scored against the same anchors."""
    alice = assemble(
        RUBRIC,
        _set(
            _probe(
                "delivery_semantics",
                "Your notification consumer restarts mid-batch. Then what?",
            )
        ),
    )
    bob = assemble(
        RUBRIC,
        _set(
            _probe(
                "delivery_semantics",
                "Two workers picked up the same payment. What stopped the double charge?",
            )
        ),
    )

    alice_q = next(q for q in alice if q.competency == "delivery_semantics")
    bob_q = next(q for q in bob if q.competency == "delivery_semantics")

    assert alice_q.prompt != bob_q.prompt
    assert alice_q.dimensions == bob_q.dimensions
    assert alice_q.dimensions == RUBRIC.by_key("delivery_semantics").dimensions


def test_must_have_carries_from_the_competency():
    """Not from the model, which has no reason to know and every reason to be
    agreeable about it."""
    questions = assemble(
        RUBRIC,
        _set(_probe("delivery_semantics", "..."), _probe("incident_response", "...")),
    )
    by_key = {q.competency: q for q in questions}
    assert by_key["delivery_semantics"].must_have is True
    assert by_key["incident_response"].must_have is False


def test_probe_for_an_unknown_competency_is_discarded():
    """A probe tagged with a competency the rubric does not contain has no
    anchors, so it cannot be scored. Better dropped than guessed at."""
    questions = assemble(
        RUBRIC,
        _set(_probe("delivery_semantics", "..."), _probe("hallucinated_key", "...")),
    )
    assert [q.competency for q in questions if q.competency != "integrity"] == [
        "delivery_semantics"
    ]


# --- the poison question ---------------------------------------------------


def test_poison_is_scored_on_integrity_not_a_competency():
    questions = assemble(RUBRIC, _set(_probe("delivery_semantics", "...")))
    poison = next(q for q in questions if q.type == QuestionType.POISON)
    assert poison.competency == "integrity"
    assert poison.dimensions == [POISON_DIMENSION]
    assert poison.must_have is False


def test_poison_sits_in_the_middle_never_last():
    """A candidate who has relaxed into the interview reacts more naturally than
    one who is wrapping up."""
    questions = assemble(
        RUBRIC,
        _set(*[_probe("delivery_semantics", f"q{i}") for i in range(4)]),
    )
    positions = [i for i, q in enumerate(questions) if q.type == QuestionType.POISON]
    assert positions == [2]
    assert questions[-1].type != QuestionType.POISON


def test_exactly_one_poison():
    questions = assemble(RUBRIC, _set(_probe("delivery_semantics", "...")))
    assert sum(q.type == QuestionType.POISON for q in questions) == 1


# --- ordering --------------------------------------------------------------


def test_ids_and_order_are_sequential_after_the_poison_insert():
    """Lane 2 walks these in order and stores `question_instance` keyed on id, so
    a gap or a duplicate is not a cosmetic problem."""
    questions = assemble(
        RUBRIC,
        _set(*[_probe("delivery_semantics", f"q{i}") for i in range(3)]),
    )
    assert [q.order for q in questions] == [1, 2, 3, 4]
    assert [q.id for q in questions] == ["q1", "q2", "q3", "q4"]


def test_a_rubric_with_no_usable_probes_still_yields_the_poison():
    """Degenerate, but it must not raise: an interview with one question is
    recoverable, an exception during invite generation is not."""
    questions = assemble(RUBRIC, _set(_probe("hallucinated_key", "...")))
    assert len(questions) == 1
    assert questions[0].type == QuestionType.POISON
    assert questions[0].order == 1


@pytest.mark.parametrize("key", ["delivery_semantics", "incident_response"])
def test_every_competency_key_survives_assembly(key):
    probes = [_probe(c.key, f"probe for {c.key}") for c in RUBRIC.competencies]
    questions = assemble(RUBRIC, _set(*probes))
    assert key in {q.competency for q in questions}


# --- the jsonb round-trip --------------------------------------------------


def test_anchors_survive_a_json_round_trip():
    """`anchors` is dict[int, str] and JSON has no integer keys.

    Postgres stores them as "1".."5" and hands them back that way. If Pydantic
    did not coerce them, every anchor lookup downstream would KeyError — after
    the interview, in lane 2, with the reason four layers away.
    """
    import json

    from shared.models.job import Job, JobStatus

    stored = json.loads(RUBRIC.model_dump_json())
    assert set(stored["competencies"][0]["dimensions"][0]["anchors"]) == {
        "1", "2", "3", "4", "5"
    }

    row = {
        "id": "j1",
        "org_id": "o1",
        "title": "Backend Engineer",
        "seniority": "mid",
        "jd_text": "...",
        "status": JobStatus.OPEN.value,
        "rubric": stored,
        "rubric_version": "v3",
        "created_at": "2026-08-23T00:00:00Z",
    }
    job = Job.model_validate(row)
    assert job.rubric is not None
    assert job.rubric == RUBRIC
    assert job.rubric.by_key("delivery_semantics").dimensions[0].anchors[3]


def test_questions_survive_a_json_round_trip():
    """application.questions is written as jsonb and read back by lane 2."""
    import json

    from shared.models.candidate import Application, ApplicationStatus

    generated = assemble(RUBRIC, _set(_probe("delivery_semantics", "...")))
    stored = [json.loads(q.model_dump_json()) for q in generated]

    application = Application.model_validate(
        {
            "id": "a1",
            "org_id": "o1",
            "job_id": "j1",
            "candidate_id": "c1",
            "status": ApplicationStatus.INVITED.value,
            "resume_url": "resumes/a1.pdf",
            "questions": stored,
            "consent_given_at": "2026-08-23T00:00:00Z",
            "created_at": "2026-08-23T00:00:00Z",
        }
    )
    assert application.questions == generated
    assert application.questions[0].dimensions[0].anchors[5]
