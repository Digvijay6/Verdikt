from __future__ import annotations

from datetime import UTC, datetime

from shared.models.interview import IntegrityReport, InterviewPackage, TranscriptTurn
from shared.models.job import Question
from shared.models.scoring import (
    AnswerScore,
    ConsistencyLabel,
    DimensionScore,
    FixedRubricAssessment,
    HolisticScore,
    InterviewResult,
    OwnershipLevel,
    Recommendation,
    RubricEvidence,
    ScoringQuestionType,
)
from voice.interview import InterviewStateMachine
from voice.scoring.persistence import persist_result
from voice.scoring.pipeline import build_scoring_input


def _question(question_id: str, order: int) -> Question:
    return Question.model_validate(
        {
            "id": question_id,
            "order": order,
            "type": "technical",
            "prompt": f"Question {order}?",
            "competency": "backend",
            "dimensions": [
                {
                    "key": "depth",
                    "weight": 1.0,
                    "anchors": {score: f"Anchor {score}" for score in range(1, 6)},
                }
            ],
            "must_have": order == 1,
        }
    )


def _package() -> InterviewPackage:
    return InterviewPackage(
        interview_id="interview-1",
        org_id="org-1",
        job_id="job-1",
        job_title="Backend Engineer",
        seniority="mid-level",
        questions=[_question("q-1", 1), _question("q-2", 2)],
        resume_summary="Python and PostgreSQL engineer",
        rubric_version="rubric-v1",
    )


def _completed_state(package: InterviewPackage) -> InterviewStateMachine:
    state = InterviewStateMachine(package.questions)
    state.start()
    state.record_answer("Answer 1", answer_start_ms=110, answer_end_ms=190)
    state.advance()
    state.record_answer("Answer 2", answer_start_ms=310, answer_end_ms=390)
    state.advance()
    return state


def _transcript() -> list[TranscriptTurn]:
    return [
        TranscriptTurn(
            speaker="agent",
            text="Question 1?",
            start_ms=100,
            end_ms=109,
            question_id="q-1",
        ),
        TranscriptTurn(
            speaker="candidate",
            text="Answer 1",
            start_ms=110,
            end_ms=190,
            question_id="q-1",
        ),
        TranscriptTurn(
            speaker="agent",
            text="Question 2?",
            start_ms=300,
            end_ms=309,
            question_id="q-2",
        ),
        TranscriptTurn(
            speaker="candidate",
            text="Answer 2",
            start_ms=310,
            end_ms=390,
            question_id="q-2",
        ),
    ]


def test_build_scoring_input_contains_every_recorded_question_in_order() -> None:
    package = _package()
    scoring_input = build_scoring_input(package, _completed_state(package), _transcript())

    assert [question.question_id for question in scoring_input.questions] == ["q-1", "q-2"]
    assert [turn.text for turn in scoring_input.questions[0].conversation] == [
        "Question 1?",
        "Answer 1",
    ]
    assert scoring_input.questions[0].resume_context.central_to_role is True
    assert scoring_input.questions[1].prior_relevant_claims == ["Answer 1"]


class _FakeQuery:
    def __init__(self, client: _FakeClient, table: str) -> None:
        self.client = client
        self.table = table
        self.action = ""
        self.payload = None
        self.on_conflict = None
        self.filters: list[tuple[str, object]] = []

    def select(self, *_: object) -> _FakeQuery:
        self.action = "select"
        return self

    def upsert(self, payload: object, *, on_conflict: str) -> _FakeQuery:
        self.action = "upsert"
        self.payload = payload
        self.on_conflict = on_conflict
        return self

    def update(self, payload: object) -> _FakeQuery:
        self.action = "update"
        self.payload = payload
        return self

    def eq(self, key: str, value: object) -> _FakeQuery:
        self.filters.append((key, value))
        return self

    def execute(self):
        self.client.calls.append(self)
        return type("Response", (), {"data": []})()


class _FakeClient:
    def __init__(self) -> None:
        self.calls: list[_FakeQuery] = []

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self, name)


def _result() -> InterviewResult:
    evidence = RubricEvidence(quote="Answer 1", rationale="Concrete evidence")
    answer = AnswerScore(
        question_id="q-1",
        dimensions=[
            DimensionScore(
                key="depth",
                score=80,
                band="strong",
                evidence="Answer 1",
                rationale="Concrete evidence",
            )
        ],
        weighted_score=4,
        fixed_rubric=FixedRubricAssessment(
            question_type=ScoringQuestionType.TECHNICAL,
            technical_accuracy_score=80,
            technical_accuracy_evidence=evidence,
            project_depth_score=80,
            project_depth_evidence=evidence,
            ownership_level=OwnershipLevel.MAJOR_CONTRIBUTOR,
            ownership_evidence=evidence,
            consistency_label=ConsistencyLabel.CONSISTENT,
            consistency_evidence=evidence,
            central_to_role=True,
        ),
        model_id="gemini-test",
        prompt_version="score-interview.v1",
    )
    return InterviewResult(
        interview_id="interview-1",
        org_id="org-1",
        application_id="application-1",
        job_id="job-1",
        seniority="mid-level",
        answers=[answer],
        holistic=HolisticScore(
            score=4,
            strengths=["Specific"],
            concerns=[],
            representative_quote="Answer 1",
            model_id="gemini-test",
            prompt_version="score-interview.v1",
        ),
        role_fit=4,
        overall=4.2,
        recommendation=Recommendation.ADVANCE,
        integrity=IntegrityReport(score=0, events=[], summary="Clean"),
        transcript_summary="Answer 1",
        rubric_version="rubric-v1",
        scored_at=datetime(2026, 8, 24, tzinfo=UTC),
    )


def test_persist_result_writes_lane_3_handoff_and_normalized_evidence() -> None:
    package = _package().model_copy(update={"questions": [_question("q-1", 1)]})
    state = InterviewStateMachine(package.questions)
    state.start()
    state.record_answer("Answer 1", answer_start_ms=110, answer_end_ms=190)
    state.advance()
    scoring_input = build_scoring_input(package, state, _transcript()[:2])
    client = _FakeClient()

    persist_result(scoring_input, _result(), _transcript()[:2], client=client)

    writes = {call.table: call for call in client.calls if call.action in {"upsert", "update"}}
    assert {
        "question_instance",
        "question_scoring_claim",
        "question_conversation_turn",
        "question_rubric_assessment",
        "interview_score",
        "interview",
    } <= set(writes)
    assert writes["interview_score"].on_conflict == "org_id,interview_id"
    assert ("org_id", "org-1") in writes["interview"].filters
    assert ("id", "interview-1") in writes["interview"].filters
    assert [call for call in client.calls if call.action in {"upsert", "update"}][-1].table == (
        "interview_score"
    )
