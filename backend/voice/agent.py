"""LANE 2 — LiveKit voice worker.

Run: python -m voice.agent dev

Uses the cascaded STT -> LLM -> TTS pipeline (not speech-to-speech), so:
  - on_user_turn_completed fires after each candidate answer
  - the state machine decides: follow up, advance, or close
  - generate_reply speaks the next question/follow-up
  - live scoring fires per turn (off-thread)
  - on room disconnect, the post-call scoring pipeline runs
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
    InterviewPackage,
    TranscriptTurn,
)
from shared.models.scoring import LiveSignal
from voice.interview import InterviewStateMachine
from voice.proctor import aggregate_integrity
from voice.scoring import run_postcall_pipeline, score_live

logger = structlog.get_logger(__name__)


class InterviewerAgent(Agent):
    """The voice interviewer. Uses the cascaded pipeline so
    on_user_turn_completed fires after each answer and the state machine
    controls the question flow."""

    def __init__(
        self,
        package: InterviewPackage,
        state_machine: InterviewStateMachine,
    ) -> None:
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[2]
        prompt_path = repo_root / "llm" / "prompts" / "interviewer-system.v1.md"
        system_prompt = prompt_path.read_text()

        # Build a rich system prompt with job context, resume, and the
        # question guide. The LLM uses this to conduct the interview.
        question_guide = self._build_question_guide(package)
        resume_context = self._build_resume_context(package)
        full_prompt = (
            f"{system_prompt}\n\n"
            f"## Job Context\n"
            f"Job title: {package.job_title}\n"
            f"Seniority: {package.seniority}\n\n"
            f"## Candidate Resume Summary\n"
            f"{resume_context}\n\n"
            f"## Interview Questions\n"
            f"Ask these questions in order, one at a time. After each answer, "
            f"ask a follow-up if the answer is shallow (max 2 per question), "
            f"then move to the next question. After all questions, thank the "
            f"candidate and end the interview.\n\n"
            f"{question_guide}"
        )

        super().__init__(instructions=full_prompt)
        self._package = package
        self._sm = state_machine
        self._session: AgentSession | None = None
        self._turn_start_ms = 0
        self._last_agent_end_ms = 0
        self._transcript: list[TranscriptTurn] = []
        self._live_signals: list[LiveSignal] = []

    def set_session(self, session: AgentSession) -> None:
        self._session = session

    @staticmethod
    def _build_question_guide(package: InterviewPackage) -> str:
        lines = []
        for i, q in enumerate(package.questions, 1):
            lines.append(f"Q{i} [{q.type.value}] ({q.competency}):")
            lines.append(f"  {q.prompt}")
            if q.follow_up_guidance:
                lines.append(f"  Follow-up guidance: {q.follow_up_guidance}")
            if q.must_have:
                lines.append("  [MUST HAVE]")
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

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """Candidate finished speaking — capture answer, score, advance."""
        transcript = new_message.text_content or ""
        if not transcript.strip():
            return

        now_ms = int(time.time() * 1000)

        # Record in the state machine
        self._sm.record_answer(
            transcript=transcript,
            live_correctness=0,
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

        # Fire live scoring off-thread
        if q:
            asyncio.create_task(self._fire_live_score(transcript, q))

        # Decide next action and speak it
        if self._sm.should_follow_up():
            follow_up = self._sm.get_follow_up_prompt()
            self._last_agent_end_ms = now_ms
            if self._session and follow_up:
                await self._session.generate_reply(
                    instructions=f"Ask this follow-up: {follow_up}"
                )
        else:
            self._sm.advance()
            next_q = self._sm.current_question()
            self._last_agent_end_ms = now_ms
            if next_q is not None and self._session:
                await self._session.generate_reply(
                    instructions=f"Ask this question: {next_q.prompt}"
                )
            elif next_q is None and self._session:
                await self._session.generate_reply(
                    instructions=(
                        "Thank the candidate for their time, tell them the "
                        "recruiter will follow up, and end the interview."
                    )
                )

    async def _fire_live_score(self, transcript: str, question) -> None:
        """Score the answer for correctness in real time (off-thread)."""
        try:
            signal, _ = await asyncio.to_thread(
                score_live,
                question.prompt,
                question.type.value,
                question.competency,
                transcript,
            )
            signal.question_id = question.id
            self._live_signals.append(signal)

            if self._sm._current_turn is not None:
                self._sm._current_turn.live_correctness = signal.correctness

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


async def _run_postcall(
    package: InterviewPackage,
    sm: InterviewStateMachine,
    agent: InterviewerAgent,
    application_id: str = "",
) -> None:
    """Post-call pipeline — runs on room disconnect."""
    try:
        if sm._current_turn is not None and sm._current_turn.answer_text:
            sm.advance()
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
            application_id="",  # fetched inside _write_interview_result
        )

        await asyncio.to_thread(
            _write_interview_result,
            package.interview_id,
            package.org_id,
            package.job_id,
            result,
            agent.get_transcript(),
            agent.get_live_signals(),
        )

        logger.info(
            "interview_completed",
            interview_id=package.interview_id,
            overall=result.overall,
            composite_score=result.composite_score,
            recommendation=result.recommendation.value,
            needs_human_review=result.needs_human_review,
        )
    except Exception:
        logger.exception("postcall_pipeline_failed")


async def entrypoint(ctx: JobContext) -> None:
    """Join the assigned room and conduct the interview."""
    await ctx.connect()

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

    sm = InterviewStateMachine(questions=package.questions)
    sm.start()

    # Cascaded STT (Deepgram) -> LLM (Gemini) -> TTS (ElevenLabs) pipeline.
    # This means on_user_turn_completed fires after each answer, giving
    # the state machine control over question flow.
    #
    # Turn detection + interruption handling:
    # - VAD (silero) detects speech onset/end
    # - min_silence_duration=1.5s: candidate must pause 1.5s before we
    #   consider their turn done (avoids cutting off mid-thought)
    # - allow_interruptions=True: candidate can barge in while the agent
    #   is speaking — the agent stops immediately and listens
    # - min_endpointing_delay: small delay after VAD fires to avoid
    #   false triggers on breaths/pauses
    import os

    from livekit.plugins import deepgram, elevenlabs
    from livekit.plugins import google as lk_google

    session = AgentSession(
        stt=deepgram.STT(
            model="nova-3",
            interim_results=True,
            smart_format=True,
            api_key=os.environ.get("DEEPGRAM_API_KEY") or None,
        ),
        llm=lk_google.LLM(
            model="gemini-2.5-flash",
            api_key=os.environ.get("GEMINI_API_KEY", ""),
        ),
        tts=elevenlabs.TTS(
            voice_id=os.environ.get("ELEVENLABS_VOICE_ID") or "EXAVITQu4vr4xnSDxMaL",
            api_key=os.environ.get("ELEVENLABS_API_KEY") or None,
        ),
        vad=silero.VAD.load(
            min_speech_duration=0.3,
            min_silence_duration=1.5,
            prefix_padding_duration=0.5,
            max_buffered_speech=60.0,
            activation_threshold=0.5,
        ),
        turn_detection=None,  # use VAD-based turn detection
        allow_interruptions=True,
        min_endpointing_delay=0.5,
    )

    agent = InterviewerAgent(package=package, state_machine=sm)

    await session.start(agent=agent, room=ctx.room)
    agent.set_session(session)

    # Greet and ask the first question
    first_q = sm.current_question()
    if first_q:
        await session.generate_reply(
            instructions=(
                f"Greet the candidate briefly and ask this question: "
                f"{first_q.prompt}"
            )
        )
    agent._last_agent_end_ms = int(time.time() * 1000)

    # On room disconnect — run the post-call pipeline.
    # LiveKit's Python SDK requires SYNC callbacks for room events.
    def on_disconnect() -> None:
        logger.info("room_disconnected", interview_id=package.interview_id)
        asyncio.create_task(
            _run_postcall(package, sm, agent)
        )

    ctx.room.on("disconnected", on_disconnect)


def _push_live_signal(interview_id: str, signal: LiveSignal) -> None:
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
    job_id: str,
    result,
    transcript: list[TranscriptTurn],
    live_signals: list[LiveSignal],
) -> None:
    """Write the final interview result to Supabase.

    Writes to three tables:
    - interview: status, transcript, full result JSON
    - interview_score: Lane 3 reads this for the leaderboard (via build_interview_score_row)
    - question_instance: per-question scores
    - integrity_event: proctoring events
    """
    supabase = db()

    # Fetch application_id from the interview row
    interview_row = supabase.table("interview").select("application_id").eq(
        "id", interview_id
    ).limit(1).execute()
    application_id = interview_row.data[0]["application_id"] if interview_row.data else ""

    # Stamp application_id onto the result so build_interview_score_row can use it
    if not result.application_id:
        result = result.model_copy(update={"application_id": application_id})

    # 1. Update the interview row
    supabase.table("interview").update({
        "status": "completed",
        "ended_at": datetime.now(UTC).isoformat(),
        "transcript": json.dumps([t.model_dump() for t in transcript]),
        "result": result.model_dump(mode="json"),
        "model_id": "gemini-2.5-flash",
    }).eq("id", interview_id).execute()

    # 2. Write to interview_score (Lane 3 reads this for the leaderboard)
    from voice.scoring.pipeline import build_score_row

    score_row = build_score_row(result)
    # Remove fields that come from the DB (id, created_at, updated_at)
    score_row.pop("id", None)
    score_row.pop("created_at", None)
    score_row.pop("updated_at", None)
    supabase.table("interview_score").upsert(score_row).execute()

    # 3. Write per-question scores
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

    # 4. Write integrity events
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
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))