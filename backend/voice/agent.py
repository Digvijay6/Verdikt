"""LANE 2 — LiveKit voice worker.

Run: python -m voice.agent dev

Not a web service. It subscribes to LiveKit job dispatch, joins the room it is
assigned, reads the InterviewPackage from room metadata, conducts the
interview, and writes results to Supabase. Nothing makes requests to it.

Two constraints worth knowing before designing the question flow:

  1. On gemini-3.1-flash-live-preview, LiveKit documents that generate_reply(),
     update_instructions(), and update_chat_ctx() do not work mid-session, and
     async function calling is unavailable. Adaptive probing therefore has to
     be driven by function calling plus a question state machine, not by
     rewriting instructions mid-call. The 2.5 native-audio model does not have
     these limits — pick deliberately, and record which in Interview.model_id.

  2. Speech-to-speech means no live diarization. Multi-speaker detection runs
     post-call over the recorded candidate track. Cheat signals do not need to
     be realtime; they need to land with the score.
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime

import structlog
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.agents.llm import ChatContext, ChatMessage
from livekit.plugins import silero

from shared.db import db
from shared.models.interview import (
    IntegrityEvent,
    InterviewPackage,
    TranscriptTurn,
)
from shared.models.scoring import LiveSignal
from voice.interview import InterviewStateMachine
from voice.proctor import aggregate_integrity
from voice.scoring import run_postcall_pipeline, score_live

logger = structlog.get_logger(__name__)


class InterviewerAgent(Agent):
    """The voice interviewer. Asks questions, follows up, records turns."""

    def __init__(
        self,
        package: InterviewPackage,
        state_machine: InterviewStateMachine,
    ) -> None:
        # Load the interviewer system prompt from the registry
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        prompt_path = repo_root / "llm" / "prompts" / "interviewer-system.v1.md"
        system_prompt = prompt_path.read_text()

        super().__init__(
            instructions=system_prompt,
        )
        self._package = package
        self._sm = state_machine
        self._turn_start_ms = 0
        self._last_agent_end_ms = 0
        self._transcript: list[TranscriptTurn] = []
        self._live_signals: list[LiveSignal] = []
        self._browser_events: list[IntegrityEvent] = []

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """Candidate finished speaking — capture the answer and decide next."""
        transcript = new_message.text_content or ""
        if not transcript.strip():
            return

        now_ms = int(time.time() * 1000)

        # Record the answer in the state machine
        self._sm.record_answer(
            transcript=transcript,
            live_correctness=0,  # updated after live score
            answer_start_ms=self._turn_start_ms,
            answer_end_ms=now_ms,
        )

        # Record transcript turn
        q = self._sm.current_question()
        self._transcript.append(TranscriptTurn(
            speaker="candidate",
            text=transcript,
            start_ms=self._turn_start_ms,
            end_ms=now_ms,
            question_id=q.id if q else None,
        ))

        # Fire live scoring off-thread (non-blocking)
        asyncio.create_task(self._fire_live_score(transcript, q))

        # Decide: follow up or advance
        if self._sm.should_follow_up():
            self._sm.get_follow_up_prompt()
            # Record the follow-up as an agent transcript turn
            self._last_agent_end_ms = now_ms
            # The agent will speak the follow-up via generate_reply below
        else:
            self._sm.advance()
            next_q = self._sm.current_question()
            if next_q is None:
                # Interview done — closing
                pass
            self._last_agent_end_ms = now_ms

    async def _fire_live_score(self, transcript: str, question) -> None:
        """Score the answer for correctness in real time (off-thread)."""
        if question is None:
            return
        try:
            signal, provenance = await asyncio.to_thread(
                score_live,
                question.prompt,
                question.type.value,
                question.competency,
                transcript,
            )
            signal.question_id = question.id
            self._live_signals.append(signal)

            # Update the state machine's live correctness
            if self._sm._current_turn is not None:
                self._sm._current_turn.live_correctness = signal.correctness

            # Push to Supabase realtime for the recruiter HUD
            await asyncio.to_thread(
                _push_live_signal,
                self._package.interview_id,
                signal,
            )
        except Exception:
            logger.exception("live_scoring_failed")

    def get_transcript(self) -> list[TranscriptTurn]:
        return list(self._transcript)

    def get_live_signals(self) -> list[LiveSignal]:
        return list(self._live_signals)

    def get_correctness_scores(self) -> dict[str, int]:
        return {s.question_id: s.correctness for s in self._live_signals}


async def entrypoint(ctx: JobContext) -> None:
    """Join the assigned room and conduct the interview."""
    await ctx.connect()

    # LiveKit passes room metadata, not job metadata. The InterviewPackage
    # is set as room metadata when the room is created (by /redeem or the
    # test script). Job metadata is empty by default.
    raw_metadata = ctx.job.metadata or ""
    if not raw_metadata and ctx.room:
        raw_metadata = ctx.room.metadata or ""

    if not raw_metadata:
        logger.error("no_interview_package", room=ctx.room.name if ctx.room else "?")
        return

    package = InterviewPackage.model_validate_json(raw_metadata)
    logger.info(
        "interview_started",
        interview_id=package.interview_id,
        job_id=package.job_id,
        questions=len(package.questions),
    )

    # Build the state machine
    sm = InterviewStateMachine(questions=package.questions)
    sm.start()

    # Build the session with Gemini Live via LiveKit's google plugin
    from livekit.plugins import google as lk_google

    # Use the 2.5 native-audio model (supports mid-session generate_reply)
    session = AgentSession(
        llm=lk_google.realtime.RealtimeModel(
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            voice="Aoede",
        ),
        vad=silero.VAD.load(
            min_speech_duration=0.5,
            min_silence_duration=1.5,
        ),
    )

    agent = InterviewerAgent(package=package, state_machine=sm)

    # Start the session
    await session.start(agent=agent, room=ctx.room)

    # Greet and ask the first question
    first_q = sm.current_question()
    if first_q:
        await session.generate_reply(
            instructions=(
                f"Greet the candidate briefly and ask this question: "
                f"{first_q.prompt}"
            )
        )

    # Mark the agent's first speech end for latency tracking
    agent._last_agent_end_ms = int(time.time() * 1000)

    # On room disconnect — run the post-call pipeline
    @ctx.room.on("disconnected")
    async def on_disconnect() -> None:
        logger.info("room_disconnected", interview_id=package.interview_id)

        try:
            # Finalize any in-progress turn
            if sm._current_turn is not None and sm._current_turn.answer_text:
                sm.advance()
            sm.close()

            # Aggregate integrity
            integrity = aggregate_integrity(
                org_id=package.org_id,
                browser_events=agent.get_correctness_scores(),
                state_machine=sm,
                answer_correctness_scores=agent.get_correctness_scores(),
            )

            # Run the post-call scoring pipeline
            result = await run_postcall_pipeline(
                package=package,
                state_machine=sm,
                transcript=agent.get_transcript(),
                integrity=integrity,
            )

            # Write results to Supabase
            await asyncio.to_thread(
                _write_interview_result,
                package.interview_id,
                package.org_id,
                result,
                agent.get_transcript(),
                agent.get_live_signals(),
                sm,
            )

            logger.info(
                "interview_completed",
                interview_id=package.interview_id,
                overall=result.overall,
                recommendation=result.recommendation.value,
                needs_human_review=result.needs_human_review,
            )
        except Exception:
            logger.exception("postcall_pipeline_failed")


def _push_live_signal(interview_id: str, signal: LiveSignal) -> None:
    """Push a live signal to Supabase for the recruiter's real-time HUD."""
    try:
        supabase = db()
        supabase.table("question_instance").upsert({
            "interview_id": interview_id,
            "question_id": signal.question_id,
            "live_signal": signal.model_dump(),
        }).execute()
    except Exception:
        logger.exception("push_live_signal_failed")


def _write_interview_result(
    interview_id: str,
    org_id: str,
    result,
    transcript: list[TranscriptTurn],
    live_signals: list[LiveSignal],
    sm: InterviewStateMachine,
) -> None:
    """Write the final interview result, transcript, and per-question scores
    to Supabase."""
    supabase = db()

    # Update the interview row
    supabase.table("interview").update({
        "status": "completed",
        "ended_at": datetime.now(UTC).isoformat(),
        "transcript": json.dumps([t.model_dump() for t in transcript]),
        "result": result.model_dump(mode="json"),
        "model_id": "gemini-2.5-flash-native-audio-preview-12-2025",
    }).eq("id", interview_id).execute()

    # Write per-question scores
    for answer in result.answers:
        supabase.table("question_instance").upsert({
            "org_id": org_id,
            "interview_id": interview_id,
            "question_id": answer.question_id,
            "answer_score": answer.model_dump(mode="json"),
            "scored_at": datetime.now(UTC).isoformat(),
            "model_id": answer.model_id,
            "prompt_version": answer.prompt_version,
        }).execute()

    # Write integrity events
    for event in result.integrity.events:
        supabase.table("integrity_event").insert({
            "org_id": org_id,
            "interview_id": interview_id,
            "type": event.type.value,
            "severity": event.severity,
            "at_ms": event.at_ms,
            "detail": json.dumps(event.detail),
        }).execute()

    logger.info("result_written", interview_id=interview_id)


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv()
    # livekit-plugins-google reads GOOGLE_API_KEY, not GEMINI_API_KEY
    os.environ.setdefault("GOOGLE_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))