"""Question state machine — walks through the interview question by question.

The agent asks one question at a time. After each candidate answer, the state
machine decides: follow up, advance, or close. Follow-up decisions are driven
by the live provisional score (correctness < 70 → probe deeper).

This module holds no LiveKit or Gemini dependencies — it is pure state logic
that the agent worker calls. That keeps it testable without a voice session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from shared.models.job import Question, QuestionType


class Phase(StrEnum):
    GREETING = "greeting"
    ASKING = "asking"
    LISTENING = "listening"
    FOLLOWUP_DECISION = "followup_decision"
    CLOSING = "closing"
    DONE = "done"


MAX_FOLLOWUPS_PER_QUESTION = 2
FOLLOW_UP_SCORE_THRESHOLD = 70  # below this → follow up

# Dimensions that the live scorer returns (correctness only)
LIVE_CORRECTNESS_KEY = "domain_technical_accuracy"


@dataclass
class TurnRecord:
    """One candidate answer, accumulated for post-call scoring."""

    question_id: str
    question: Question
    answer_text: str = ""
    answer_start_ms: int = 0
    answer_end_ms: int = 0
    followup_count: int = 0
    followup_texts: list[str] = field(default_factory=list)
    followup_answers: list[str] = field(default_factory=list)
    live_correctness: int = 0


@dataclass
class InterviewStateMachine:
    """Drives the interview question flow.

    Usage:
        sm = InterviewStateMachine(questions)
        sm.start()
        # agent asks sm.current_question().prompt
        # candidate answers
        sm.record_answer(transcript, live_correctness)
        if sm.should_follow_up():
            follow_up = sm.get_follow_up_prompt()
            # agent asks follow_up
            # candidate answers
            sm.record_followup(transcript)
        sm.advance()
        # repeat until sm.is_done()
    """

    questions: list[Question]
    phase: Phase = Phase.GREETING
    _index: int = 0
    _followup_count: int = 0
    _current_turn: TurnRecord | None = None
    turns: list[TurnRecord] = field(default_factory=list)

    def start(self) -> None:
        self.phase = Phase.ASKING

    def current_question(self) -> Question | None:
        if self._index >= len(self.questions):
            return None
        return self.questions[self._index]

    def begin_turn(self) -> TurnRecord:
        """Called when the candidate starts answering the current question."""
        q = self.current_question()
        if q is None:
            raise RuntimeError("No current question")
        self._current_turn = TurnRecord(
            question_id=q.id,
            question=q,
        )
        self.phase = Phase.LISTENING
        return self._current_turn

    def record_answer(
        self,
        transcript: str,
        live_correctness: int = 0,
        answer_start_ms: int = 0,
        answer_end_ms: int = 0,
    ) -> None:
        """Record the candidate's answer to the current question."""
        if self._current_turn is None:
            self.begin_turn()
        self._current_turn.answer_text = transcript
        self._current_turn.live_correctness = live_correctness
        self._current_turn.answer_start_ms = answer_start_ms
        self._current_turn.answer_end_ms = answer_end_ms
        self.phase = Phase.FOLLOWUP_DECISION

    def record_followup(self, transcript: str) -> None:
        """Record the candidate's answer to a follow-up."""
        if self._current_turn is None:
            return
        self._current_turn.followup_answers.append(transcript)
        self.phase = Phase.FOLLOWUP_DECISION

    def should_follow_up(self) -> bool:
        """Decide whether to follow up on the current answer."""
        if self._current_turn is None:
            return False
        if self._followup_count >= MAX_FOLLOWUPS_PER_QUESTION:
            return False
        q = self._current_turn.question
        if q.follow_up_guidance is None:
            return False
        # Follow up if the live score is below threshold OR the answer is
        # suspiciously short (likely shallow)
        if self._current_turn.live_correctness < FOLLOW_UP_SCORE_THRESHOLD:
            return True
        if len(self._current_turn.answer_text.split()) < 15:
            return True
        return False

    def get_follow_up_prompt(self) -> str:
        """Return the follow-up prompt for the agent to ask."""
        if self._current_turn is None:
            return ""
        q = self._current_turn.question
        self._followup_count += 1
        self._current_turn.followup_count = self._followup_count
        self._current_turn.followup_texts.append(q.follow_up_guidance or "")
        return q.follow_up_guidance or ""

    def advance(self) -> Question | None:
        """Move to the next question. Finalize the current turn."""
        if self._current_turn is not None:
            self.turns.append(self._current_turn)
            self._current_turn = None
        self._followup_count = 0
        self._index += 1
        if self._index >= len(self.questions):
            self.phase = Phase.CLOSING
            return None
        self.phase = Phase.ASKING
        return self.current_question()

    def is_done(self) -> bool:
        return self.phase in (Phase.CLOSING, Phase.DONE)

    def close(self) -> None:
        self.phase = Phase.DONE

    def closing_prompt(self) -> str:
        return (
            "Thank the candidate for their time, tell them the recruiter will "
            "follow up, and end the interview. Do not give feedback on their "
            "performance."
        )

    def get_all_turns(self) -> list[TurnRecord]:
        """Return all completed turns for post-call scoring."""
        turns = list(self.turns)
        if self._current_turn is not None and self._current_turn.answer_text:
            turns.append(self._current_turn)
        return turns

    def has_poison_question(self) -> bool:
        return any(q.type == QuestionType.POISON for q in self.questions)