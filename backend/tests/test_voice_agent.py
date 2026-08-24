from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest
from livekit.agents import StopResponse
from livekit.agents.llm import ChatContext, ChatMessage

from shared.models.interview import InterviewPackage
from shared.models.job import Question
from voice.agent import InterviewerAgent
from voice.interview import InterviewStateMachine, Phase


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

    def say(self, text: str, **_: object) -> None:
        self.spoken.append(text)


@pytest.mark.asyncio
async def test_candidate_intro_is_not_scored_and_each_answer_is_recorded() -> None:
    package = _package()
    state_machine = InterviewStateMachine(package.questions)
    agent = InterviewerAgent(package, state_machine)
    session = _FakeSession()
    agent.set_session(session)  # type: ignore[arg-type]
    agent._fire_live_score = AsyncMock()  # type: ignore[method-assign]

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
