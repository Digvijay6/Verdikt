from __future__ import annotations

import json
from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from livekit.agents import StopResponse
from livekit.agents.llm import ChatContext, ChatMessage

from shared.models.interview import InterviewPackage, TranscriptTurn
from shared.models.job import Question
from voice.agent import InterviewerAgent, _run_postcall
from voice.interview import InterviewStateMachine, Phase


@pytest.fixture(autouse=True)
def _disable_real_transcript_writes(monkeypatch) -> None:
    monkeypatch.setattr("voice.agent._persist_interview_transcript", lambda *_args: None)


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
        resume_summary="Python engineer",
        rubric_version="rubric-v1",
    )


@dataclass
class _FakeSession:
    spoken: list[str] = field(default_factory=list)
    handlers: dict[str, object] = field(default_factory=dict)

    def say(self, text: str, **_: object) -> None:
        self.spoken.append(text)

    def on(self, event: str, callback: object) -> object:
        self.handlers[event] = callback
        return callback


@dataclass
class _FakeLocalParticipant:
    messages: list[dict] = field(default_factory=list)

    async def publish_data(self, payload: bytes, **_: object) -> None:
        self.messages.append(json.loads(payload))


@dataclass
class _FakeRoom:
    local_participant: _FakeLocalParticipant = field(default_factory=_FakeLocalParticipant)


@pytest.mark.asyncio
async def test_candidate_intro_is_not_scored_and_each_answer_is_recorded() -> None:
    package = _package()
    state_machine = InterviewStateMachine(package.questions)
    agent = InterviewerAgent(package, state_machine)
    session = _FakeSession()
    agent.set_session(session)  # type: ignore[arg-type]
    agent._fire_live_score = AsyncMock()  # type: ignore[method-assign]

    assert "conversation_item_added" in session.handlers

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(),
            ChatMessage(role="user", content=["I am a backend engineer."]),
        )

    assert state_machine.phase is Phase.ASKING
    assert state_machine.get_all_turns() == []
    assert agent.get_transcript()[0].question_id is None
    assert session.spoken == ["Question 1?"]

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            ChatContext.empty(),
            ChatMessage(role="user", content=["My first complete answer."]),
        )

    turns = state_machine.get_all_turns()
    assert [(turn.question_id, turn.answer_text) for turn in turns] == [
        ("q-1", "My first complete answer."),
    ]
    candidate_turns = [turn for turn in agent.get_transcript() if turn.speaker == "candidate"]
    assert candidate_turns[-1].question_id == "q-1"
    assert session.spoken[-1] == "Question 2?"


@pytest.mark.asyncio
async def test_final_answer_is_recorded_before_candidate_question_period() -> None:
    package = _package().model_copy(update={"questions": [_question("q-1", 1)]})
    state_machine = InterviewStateMachine(package.questions)
    agent = InterviewerAgent(package, state_machine)
    session = _FakeSession()
    agent.set_session(session)  # type: ignore[arg-type]
    agent._fire_live_score = AsyncMock()  # type: ignore[method-assign]

    for text in ("My introduction.", "My complete technical answer."):
        with pytest.raises(StopResponse):
            await agent.on_user_turn_completed(
                ChatContext.empty(),
                ChatMessage(role="user", content=[text]),
            )

    assert state_machine.phase is Phase.CLOSING
    assert state_machine.get_all_turns()[0].answer_text == "My complete technical answer."
    assert session.spoken[-1] == (
        "That's all the interview questions for this round. "
        "Do you have any questions for me?"
    )


def test_completion_requires_every_primary_answer_and_candidate_question_period() -> None:
    package = _package()
    state_machine = InterviewStateMachine(package.questions)
    state_machine.start()
    state_machine.record_answer("I don't know.")
    state_machine.advance()

    assert state_machine.is_complete() is False

    state_machine.record_answer("Skip.")
    state_machine.advance()

    assert state_machine.phase is Phase.CLOSING
    assert state_machine.is_complete() is True


@pytest.mark.asyncio
async def test_disconnect_after_one_answer_is_abandoned_without_scoring(monkeypatch) -> None:
    package = _package()
    state_machine = InterviewStateMachine(package.questions)
    state_machine.start()
    state_machine.record_answer("Only the first answer.")
    state_machine.advance()
    agent = InterviewerAgent(package, state_machine)
    abandoned: list[str] = []

    monkeypatch.setattr(
        "voice.agent._mark_interview_abandoned",
        lambda interview_id, _org_id, _transcript: abandoned.append(interview_id),
    )
    score = AsyncMock()
    monkeypatch.setattr("voice.agent.run_postcall_pipeline", score)

    await _run_postcall(package, state_machine, agent)

    assert abandoned == [package.interview_id]
    score.assert_not_awaited()


@pytest.mark.asyncio
async def test_delivered_agent_text_is_recorded_instead_of_interrupted_script(
    monkeypatch,
) -> None:
    package = _package()
    agent = InterviewerAgent(package, InterviewStateMachine(package.questions))
    session = _FakeSession()
    agent.set_session(session)  # type: ignore[arg-type]
    persisted: list[list[TranscriptTurn]] = []
    monkeypatch.setattr(
        "voice.agent._persist_interview_transcript",
        lambda _interview_id, _org_id, transcript: persisted.append(transcript),
    )

    await agent._say_scripted("A long question the candidate interrupts.", question_id="q-1")
    await agent._record_agent_message(
        ChatMessage(
            role="assistant",
            content=["A long question"],
            interrupted=True,
        )
    )

    assert [(turn.text, turn.question_id) for turn in agent.get_transcript()] == [
        ("A long question", "q-1")
    ]
    assert persisted[-1][-1].text == "A long question"


@pytest.mark.asyncio
async def test_incremental_transcript_write_failure_does_not_interrupt_call(
    monkeypatch,
) -> None:
    package = _package()
    agent = InterviewerAgent(package, InterviewStateMachine(package.questions))
    attempts = 0

    def fail_write(*_args) -> None:
        nonlocal attempts
        attempts += 1
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("voice.agent._persist_interview_transcript", fail_write)

    await agent._record_candidate_transcript("I don't know.", 100, question_id="q-1")

    assert attempts == 1
    assert agent.get_transcript()[-1].text == "I don't know."


@pytest.mark.asyncio
async def test_candidate_question_period_notifies_frontend_that_questions_are_complete() -> None:
    package = _package()
    room = _FakeRoom()
    agent = InterviewerAgent(
        package,
        InterviewStateMachine(package.questions),
        room=room,
    )
    agent.set_session(_FakeSession())  # type: ignore[arg-type]

    await agent._say_closing_question()

    assert room.local_participant.messages == [{"type": "questions_complete"}]
