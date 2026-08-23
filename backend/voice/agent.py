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
from datetime import UTC, datetime

import structlog
from livekit.agents import (
    Agent,
    AgentSession,
    JobContext,
    WorkerOptions,
    cli,
)
from livekit.plugins import silero

from shared.db import db
from shared.models.interview import (
    InterviewPackage,
    TranscriptTurn,
)
from shared.models.scoring import LiveSignal
from voice.interview import InterviewStateMachine
from voice.proctor import aggregate_integrity
from voice.scoring import run_postcall_pipeline

logger = structlog.get_logger(__name__)


class InterviewerAgent(Agent):
    """The voice interviewer. Questions are embedded in the system prompt so
    Gemini's speech-to-speech model handles the full conversation flow —
    asking questions, following up, and moving to the next question — without
    needing per-turn generate_reply calls (which don't work with realtime
    speech-to-speech models)."""

    def __init__(
        self,
        package: InterviewPackage,
    ) -> None:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        prompt_path = repo_root / "llm" / "prompts" / "interviewer-system.v1.md"
        base_prompt = prompt_path.read_text()

        # Build the question guide as part of the system prompt.
        # Gemini's realtime model reads this once and conducts the interview
        # autonomously — asking one question at a time, following up on shallow
        # answers, and moving to the next question.
        question_guide = self._build_question_guide(package)
        resume_context = self._build_resume_context(package)

        full_prompt = (
            f"{base_prompt}\n\n"
            f"## Job Context\n"
            f"Job title: {package.job_title}\n"
            f"Seniority: {package.seniority}\n\n"
            f"## Candidate Resume Summary\n"
            f"{resume_context}\n\n"
            f"## Interview Questions\n"
            f"Ask these questions in order. Ask ONE at a time. After each "
            f"answer, decide: ask a follow-up if the answer is shallow (max 2 "
            f"follow-ups per question), or move to the next question. After all "
            f"questions, thank the candidate and end the interview.\n\n"
            f"{question_guide}"
        )

        super().__init__(instructions=full_prompt)
        self._package = package
        self._transcript: list[TranscriptTurn] = []
        self._live_signals: list[LiveSignal] = []

    @staticmethod
    def _build_question_guide(package: InterviewPackage) -> str:
        lines = []
        for i, q in enumerate(package.questions, 1):
            lines.append(f"Q{i} [{q.type.value}] ({q.competency}):")
            lines.append(f"  {q.prompt}")
            if q.follow_up_guidance:
                lines.append(f"  Follow-up guidance: {q.follow_up_guidance}")
            if q.must_have:
                lines.append("  [MUST HAVE — weak answer here is a hard gate]")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _build_resume_context(package: InterviewPackage) -> str:
        if not package.resume_highlights:
            return package.resume_summary or "No resume available."
        r = package.resume_highlights
        parts = [package.resume_summary or ""]
        if r.skills:
            parts.append(f"Skills: {', '.join(r.skills[:15])}")
        if r.employment:
            for emp in r.employment[:3]:
                parts.append(
                    f"- {emp.title} at {emp.company} "
                    f"({emp.start or '?'} to {emp.end or 'present'})"
                )
        return "\n".join(parts)

    def get_transcript(self) -> list[TranscriptTurn]:
        return list(self._transcript)

    def get_live_signals(self) -> list[LiveSignal]:
        return list(self._live_signals)

    def get_correctness_scores(self) -> dict[str, int]:
        return {s.question_id: s.correctness for s in self._live_signals}


async def _run_postcall(
    package: InterviewPackage,
    agent: InterviewerAgent,
) -> None:
    """Post-call pipeline — runs on room disconnect."""
    try:
        # Build a state machine from the package for the scoring pipeline
        sm = InterviewStateMachine(questions=package.questions)
        sm.start()
        sm.close()

        integrity = aggregate_integrity(
            org_id=package.org_id,
            browser_events=agent.get_correctness_scores(),
            state_machine=sm,
            answer_correctness_scores=agent.get_correctness_scores(),
        )

        result = await run_postcall_pipeline(
            package=package,
            state_machine=sm,
            transcript=agent.get_transcript(),
            integrity=integrity,
        )

        await asyncio.to_thread(
            _write_interview_result,
            package.interview_id,
            package.org_id,
            result,
            agent.get_transcript(),
            agent.get_live_signals(),
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

    # Build the session with Gemini Live (speech-to-speech).
    # The full interview guide is in the system prompt — Gemini conducts
    # the interview autonomously: asks questions, follows up, moves on.
    from livekit.plugins import google as lk_google

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

    agent = InterviewerAgent(package=package)

    # Start the session — Gemini greets and asks Q1 from the system prompt
    await session.start(agent=agent, room=ctx.room)

    # On room disconnect — run the post-call pipeline.
    # LiveKit's Python SDK requires SYNC callbacks for room events.
    def on_disconnect() -> None:
        logger.info("room_disconnected", interview_id=package.interview_id)
        asyncio.create_task(
            _run_postcall(package, agent)
        )

    ctx.room.on("disconnected", on_disconnect)


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