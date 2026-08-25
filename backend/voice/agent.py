"""LANE 2 — LiveKit voice worker.

Uses LiveKit's AgentSession with cascaded STT→LLM→TTS pipeline.
The AgentSession handles turn detection, interruptions, and the
conversation loop. The system prompt contains the full interview
guide so the LLM conducts the interview autonomously.

Transcript data is sent to the frontend via the LiveKit data channel.
Post-call scoring runs on room disconnect.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

# Load .env BEFORE any LiveKit/Deepgram/Rumik imports.
# The worker uses forkserver multiprocessing, which spawns fresh Python
# processes that do NOT inherit shell-exported env vars. Loading .env
# here ensures all child processes have the keys.
from dotenv import load_dotenv

_env_path = Path(__file__).resolve().parents[1] / ".env"
load_dotenv(_env_path)

# LiveKit dev mode enables root DEBUG logging. HTTP/2 protocol loggers include
# raw authorization headers at that level, so keep them above DEBUG always.
for _logger_name in ("hpack", "h2", "httpcore", "httpx"):
    logging.getLogger(_logger_name).setLevel(logging.WARNING)

import structlog  # noqa: E402
from livekit.agents import (  # noqa: E402
    Agent,
    AgentSession,
    JobContext,
    StopResponse,
    WorkerOptions,
    cli,
)
from livekit.agents.llm import ChatContext, ChatMessage  # noqa: E402
from livekit.plugins import silero  # noqa: E402

from shared.db import db  # noqa: E402
from shared.llm import prompt_text, task_config  # noqa: E402
from shared.models.interview import (  # noqa: E402
    IntegrityEvent,
    IntegrityEventType,
    InterviewPackage,
    TranscriptTurn,
)
from shared.models.scoring import LiveSignal  # noqa: E402
from voice.interview import InterviewStateMachine, Phase, TurnRecord  # noqa: E402
from voice.proctor import aggregate_integrity  # noqa: E402
from voice.proctor.aggregate import detect_prompt_injection  # noqa: E402
from voice.scoring import run_postcall_pipeline, score_live  # noqa: E402
from voice.scoring.persistence import persist_result  # noqa: E402

logger = structlog.get_logger(__name__)

CLARIFICATION_PHRASES = (
    "could you clarify",
    "can you clarify",
    "what do you mean",
    "could you repeat",
    "can you repeat",
    "please repeat",
    "which part",
)
OFF_TOPIC_PHRASES = (
    "i would rather discuss",
    "i'd rather discuss",
    "instead of answering",
    "change the subject",
    "let's talk about something else",
    "not going to answer",
)
DONT_KNOW_PHRASES = (
    "i don't know",
    "i do not know",
    "i'm not sure",
    "i am not sure",
    "i don't recognize",
    "i don't recognise",
    "i have never used",
    "i'm unfamiliar",
    "i am unfamiliar",
)
LIVE_SCORE_TIMEOUT_SECONDS = 2.0


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    lowered = " ".join(text.lower().split())
    return any(phrase in lowered for phrase in phrases)


def _is_short_clarification(text: str) -> bool:
    normalized = " ".join(text.lower().split())
    return _contains_any(normalized, CLARIFICATION_PHRASES) or (
        normalized.endswith("?") and len(normalized.split()) <= 12
    )


def _is_dont_know(text: str) -> bool:
    normalized = " ".join(text.lower().split()).strip(" .!?")
    return len(normalized.split()) <= 12 and any(
        normalized == phrase or normalized.startswith(f"{phrase} ")
        for phrase in DONT_KNOW_PHRASES
    )


def _relative_ms(*, started_at_ms: int, now_ms: int) -> int:
    """Return the database contract's milliseconds since interview start."""
    return max(0, now_ms - started_at_ms)


class InterviewerAgent(Agent):
    """The voice interviewer.

    The Python state machine owns question order and records every answer.
    The LLM handles the greeting and candidate question period, while exact
    interview questions and follow-ups are spoken with ``session.say``.
    """

    def __init__(
        self,
        package: InterviewPackage,
        state_machine: InterviewStateMachine,
        room: object | None = None,
    ) -> None:
        system_prompt = prompt_text("interviewer-system")

        full_prompt = (
            f"{system_prompt}\n\n"
            f"## Job Context\n"
            f"Job title: {package.job_title}\n"
            f"Seniority: {package.seniority}\n"
        )

        super().__init__(instructions=full_prompt, id="verdikt")
        self._package = package
        self._sm = state_machine
        self._room = room
        self._session: AgentSession | None = None
        self._turn_start_ms = 0
        self._last_agent_end_ms = 0
        self._started_at_ms = int(time.time() * 1000)
        self._transcript: list[TranscriptTurn] = []
        self._transcript_lock = asyncio.Lock()
        self._transcript_tasks: set[asyncio.Task[None]] = set()
        self._pending_agent_turns: list[tuple[str, str | None]] = []
        self._agent_message_question_ids: dict[str, str | None] = {}
        self._live_signals: list[LiveSignal] = []
        self._active_speech: object | None = None
        self._active_prompt = ""
        self._active_marks_question_delivered = False

    def set_session(self, session: AgentSession) -> None:
        self._session = session
        session.on("conversation_item_added", self._on_conversation_item_added)

    def _on_conversation_item_added(self, event: object) -> None:
        item = getattr(event, "item", None)
        if not isinstance(item, ChatMessage) or item.role != "assistant":
            return
        task = asyncio.create_task(self._record_agent_message(item))
        self._transcript_tasks.add(task)
        task.add_done_callback(self._transcript_tasks.discard)

    async def on_user_turn_completed(
        self, turn_ctx: ChatContext, new_message: ChatMessage
    ) -> None:
        """Record the turn and deterministically select the next spoken prompt."""
        transcript = new_message.text_content or ""
        if not transcript.strip():
            return

        now_ms = self._elapsed_ms()

        if self._sm.phase is Phase.DONE:
            raise StopResponse

        injection_pattern = detect_prompt_injection(transcript)

        if self._sm.phase is Phase.CLOSING:
            await self._record_candidate_transcript(transcript, now_ms, question_id=None)
            if injection_pattern:
                await self._persist_prompt_injection(
                    transcript,
                    injection_pattern,
                    now_ms,
                    question_id=None,
                )
                self._sm.close()
                await self._say_scripted(
                    "I can't follow instructions that change the interview. "
                    "Thank you for your time. That is all for today, and you can end the call.",
                    question_id=None,
                )
                raise StopResponse
            self._sm.close()
            return

        if injection_pattern:
            q = self._sm.current_question() if self._sm.phase is not Phase.GREETING else None
            await self._record_candidate_transcript(
                transcript,
                now_ms,
                question_id=None,
            )
            await self._persist_prompt_injection(
                transcript,
                injection_pattern,
                now_ms,
                question_id=q.id if q else None,
            )
            if q:
                await self._say_scripted(
                    "I can't follow instructions that change the interview. "
                    f"{self._active_prompt or q.prompt}",
                    question_id=q.id,
                    marks_question_delivered=self._active_marks_question_delivered,
                )
            else:
                await self._say_scripted(
                    "I can't follow instructions that change the interview. "
                    "Please briefly introduce your professional background.",
                    question_id=None,
                )
            raise StopResponse

        if self._sm.phase is Phase.GREETING:
            await self._record_candidate_transcript(transcript, now_ms, question_id=None)
            self._sm.start()
            await self._say_question(self._sm.current_question())
            raise StopResponse

        q = self._sm.current_question()
        if q is None:
            self._sm.phase = Phase.CLOSING
            await self._record_candidate_transcript(transcript, now_ms, question_id=None)
            await self._say_closing_question()
            raise StopResponse

        if self._speech_was_interrupted():
            await self._record_candidate_transcript(
                transcript,
                now_ms,
                question_id=None,
            )
            await self._say_scripted(
                self._active_prompt or q.prompt,
                question_id=q.id,
                marks_question_delivered=self._active_marks_question_delivered,
            )
            raise StopResponse

        if self._active_marks_question_delivered:
            self._sm.mark_question_delivered()

        if _is_short_clarification(transcript):
            await self._record_candidate_transcript(transcript, now_ms, question_id=None)
            await self._say_scripted(
                f"Sure—I'm asking about this: {self._active_prompt or q.prompt}",
                question_id=q.id,
                marks_question_delivered=self._active_marks_question_delivered,
            )
            raise StopResponse

        if _contains_any(transcript, OFF_TOPIC_PHRASES):
            await self._record_candidate_transcript(transcript, now_ms, question_id=None)
            await self._say_scripted(
                f"Let's stay with the interview question: {self._active_prompt or q.prompt}",
                question_id=q.id,
                marks_question_delivered=self._active_marks_question_delivered,
            )
            raise StopResponse

        answering_follow_up = (
            self._sm._current_turn is not None
            and self._sm._current_turn.followup_count
            > len(self._sm._current_turn.followup_answers)
        )
        if answering_follow_up:
            self._sm.record_followup(transcript)
            await self._record_candidate_transcript(
                transcript,
                now_ms,
                question_id=q.id,
            )
            self._sm.advance()
            await self._say_next_question_or_close()
            raise StopResponse

        # The live score arrives asynchronously, so use the local shallow-answer
        # check for the immediate follow-up decision and update the stored turn
        # with the model score when it arrives.
        self._sm.record_answer(
            transcript=transcript,
            live_correctness=100,
            answer_start_ms=self._turn_start_ms,
            answer_end_ms=now_ms,
        )
        recorded_turn = self._sm._current_turn
        await self._record_candidate_transcript(
            transcript,
            now_ms,
            question_id=q.id,
        )

        if recorded_turn is not None:
            try:
                await asyncio.wait_for(
                    self._fire_live_score(transcript, q, recorded_turn),
                    timeout=LIVE_SCORE_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning(
                    "live_scoring_timed_out",
                    interview_id=self._package.interview_id,
                    question_id=q.id,
                    timeout_seconds=LIVE_SCORE_TIMEOUT_SECONDS,
                )

        if _is_dont_know(transcript):
            self._sm.advance()
            await self._say_next_question_or_close()
        elif self._sm.should_follow_up():
            follow_up = self._sm.get_follow_up_prompt(
                prompt_text("interviewer-follow-up").strip()
            )
            await self._say_scripted(follow_up, question_id=q.id)
        else:
            self._sm.advance()
            await self._say_next_question_or_close()

        raise StopResponse

    async def _record_candidate_transcript(
        self,
        text: str,
        end_ms: int,
        *,
        question_id: str | None,
    ) -> None:
        turn = TranscriptTurn(
            speaker="candidate",
            text=text,
            start_ms=self._turn_start_ms,
            end_ms=end_ms,
            question_id=question_id,
        )
        await self._record_transcript_turn(turn)

    async def _persist_prompt_injection(
        self,
        transcript: str,
        pattern: str,
        at_ms: int,
        *,
        question_id: str | None,
    ) -> None:
        try:
            await asyncio.to_thread(
                _persist_integrity_event,
                IntegrityEvent(
                    org_id=self._package.org_id,
                    interview_id=self._package.interview_id,
                    type=IntegrityEventType.PROMPT_INJECTION,
                    severity=0.8,
                    at_ms=at_ms,
                    detail={
                        "question_id": question_id,
                        "pattern": pattern,
                        "answer_snippet": transcript[:200],
                    },
                ),
            )
        except Exception:
            logger.exception(
                "prompt_injection_persist_failed",
                interview_id=self._package.interview_id,
            )

    async def _record_agent_message(self, message: ChatMessage) -> None:
        """Persist the text LiveKit reports as actually delivered to the candidate."""
        text = (message.text_content or "").strip()
        if not text:
            return
        has_stable_mapping = message.id in self._agent_message_question_ids
        question_id = self._agent_message_question_ids.pop(message.id, None)
        if not has_stable_mapping:
            for index, (intended, pending_question_id) in enumerate(self._pending_agent_turns):
                if intended.startswith(text) or text.startswith(intended):
                    del self._pending_agent_turns[: index + 1]
                    question_id = pending_question_id
                    break
        now_ms = self._elapsed_ms()
        await self._record_transcript_turn(
            TranscriptTurn(
                speaker="agent",
                text=text,
                start_ms=self._last_agent_end_ms,
                end_ms=now_ms,
                question_id=question_id,
            )
        )
        self._last_agent_end_ms = now_ms
        self._turn_start_ms = now_ms

    async def _record_transcript_turn(self, turn: TranscriptTurn) -> None:
        async with self._transcript_lock:
            self._transcript.append(turn)
            transcript = list(self._transcript)
            try:
                await asyncio.to_thread(
                    _persist_interview_transcript,
                    self._package.interview_id,
                    self._package.org_id,
                    transcript,
                )
            except Exception:
                logger.exception(
                    "incremental_transcript_persist_failed",
                    interview_id=self._package.interview_id,
                )

    async def flush_transcript_tasks(self) -> None:
        if self._transcript_tasks:
            await asyncio.gather(*list(self._transcript_tasks), return_exceptions=True)

    async def _say_question(self, question) -> None:
        if question is None:
            await self._say_closing_question()
            return
        await self._say_scripted(
            question.prompt,
            question_id=question.id,
            marks_question_delivered=True,
        )

    async def _say_next_question_or_close(self) -> None:
        next_question = self._sm.current_question()
        if next_question is None:
            await self._say_closing_question()
        else:
            await self._say_question(next_question)

    async def _say_closing_question(self) -> None:
        await self._publish_event({"type": "questions_complete"})
        await self._say_scripted(
            "That's all the interview questions for this round. "
            "Do you have any questions for me?",
            question_id=None,
        )

    async def _publish_event(self, payload: dict[str, str]) -> None:
        participant = getattr(self._room, "local_participant", None)
        if participant is None:
            return
        try:
            await participant.publish_data(json.dumps(payload).encode(), reliable=True)
        except Exception:
            logger.exception("publish_interview_event_failed", payload_type=payload["type"])

    async def _say_scripted(
        self,
        text: str,
        *,
        question_id: str | None,
        marks_question_delivered: bool = False,
    ) -> None:
        if not self._session or not text:
            return
        self._pending_agent_turns.append((text, question_id))
        self._active_prompt = text
        self._active_marks_question_delivered = marks_question_delivered
        self._active_speech = self._session.say(text, allow_interruptions=True)
        add_done_callback = getattr(self._active_speech, "add_done_callback", None)
        if callable(add_done_callback):

            def remember_message_ids(handle: object) -> None:
                for item in getattr(handle, "chat_items", []):
                    self._agent_message_question_ids[item.id] = question_id

            add_done_callback(remember_message_ids)

    def _speech_was_interrupted(self) -> bool:
        handle = self._active_speech
        if handle is None:
            return False
        done = getattr(handle, "done", None)
        return bool(getattr(handle, "interrupted", False)) or (
            callable(done) and not done()
        )

    def _elapsed_ms(self) -> int:
        return _relative_ms(
            started_at_ms=self._started_at_ms,
            now_ms=int(time.time() * 1000),
        )

    async def _fire_live_score(
        self,
        transcript: str,
        question,
        recorded_turn: TurnRecord,
    ) -> None:
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

            recorded_turn.live_correctness = signal.correctness

            await asyncio.to_thread(
                _push_live_signal,
                self._package.org_id,
                self._package.interview_id,
                signal,
                question.order,
            )
        except Exception:
            logger.exception("live_scoring_failed")

    def get_transcript(self) -> list[TranscriptTurn]:
        return list(self._transcript)

    def get_live_signals(self) -> list[LiveSignal]:
        return list(self._live_signals)


async def entrypoint(ctx: JobContext) -> None:
    """Join the assigned room and conduct the interview."""
    await ctx.connect()

    # Read InterviewPackage from room metadata
    raw_metadata = ""
    if hasattr(ctx.room, "metadata") and ctx.room.metadata:
        raw_metadata = ctx.room.metadata
    if not raw_metadata and hasattr(ctx.job, "metadata") and ctx.job.metadata:
        raw_metadata = ctx.job.metadata

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

    # Set the agent's display name
    try:
        await ctx.room.local_participant.set_name("Verdikt")
    except Exception:
        logger.warning("failed to set agent name to Verdikt")

    # Cascaded STT (Deepgram) -> LLM (Gemini) -> TTS (ElevenLabs) pipeline.
    # The AgentSession handles turn detection, interruptions, and the
    # conversation loop. The system prompt contains the full interview
    # guide so the LLM conducts the interview autonomously.
    from livekit.plugins import deepgram
    from livekit.plugins import google as lk_google

    from voice.elevenlabs_rest_tts import ElevenLabsRESTTTS

    deepgram_api_key = os.environ.get("DEEPGRAM_API_KEY", "")
    gemini_api_key = os.environ.get("GEMINI_API_KEY", "")
    elevenlabs_api_key = os.environ.get("ELEVENLABS_API_KEY", "")
    elevenlabs_voice_id = os.environ.get(
        "ELEVENLABS_VOICE_ID",
        "EXAVITQu4vr4xnSDxMaL",
    )

    logger.info(
        "plugin_config",
        deepgram_key_set=bool(deepgram_api_key),
        gemini_key_set=bool(gemini_api_key),
        elevenlabs_key_set=bool(elevenlabs_api_key),
    )

    interviewer_config = task_config("interviewer-system")
    session = AgentSession(
        stt=deepgram.STT(
            model="nova-3",
            interim_results=True,
            smart_format=True,
            api_key=deepgram_api_key or None,
        ),
        llm=lk_google.LLM(
            model=interviewer_config.model,
            api_key=gemini_api_key,
        ),
        tts=ElevenLabsRESTTTS(
            api_key=elevenlabs_api_key,
            voice_id=elevenlabs_voice_id,
            model_id="eleven_flash_v2_5",
        ),
        vad=silero.VAD.load(
            min_speech_duration=0.3,
            min_silence_duration=1.5,
            prefix_padding_duration=0.5,
            max_buffered_speech=60.0,
            activation_threshold=0.5,
        ),
        allow_interruptions=True,
        min_endpointing_delay=1.5,
    )

    agent = InterviewerAgent(package=package, state_machine=sm, room=ctx.room)

    logger.info("starting_session", room=ctx.room.name)
    await session.start(agent=agent, room=ctx.room)
    agent.set_session(session)
    logger.info("session_started", room=ctx.room.name)

    # Greet and start the interview — the system prompt handles the rest
    logger.info("generating_greeting", room=ctx.room.name)
    await session.generate_reply(
        instructions=(
            "Greet the candidate, introduce yourself as Verdikt, and ask "
            "them to introduce themselves. Do not ask any interview "
            "questions yet — just the intro and small talk."
        )
    )
    logger.info("greeting_generated", room=ctx.room.name)

    # LiveKit awaits shutdown callbacks before terminating the job process.
    # A detached task here can be cancelled before it persists the final state.
    async def on_shutdown(reason: str) -> None:
        logger.info(
            "interview_session_ending",
            interview_id=package.interview_id,
            reason=reason,
        )
        if ctx.room.isconnected():
            await ctx.room.disconnect()
        await _run_postcall(package, sm, agent)

    ctx.add_shutdown_callback(on_shutdown)


async def _run_postcall(
    package: InterviewPackage,
    sm: InterviewStateMachine,
    agent: InterviewerAgent,
) -> None:
    """Post-call pipeline — runs on room disconnect."""
    try:
        await agent.flush_transcript_tasks()
        if sm._current_turn is not None and sm._current_turn.answer_text:
            sm.advance()
        completed = sm.is_complete()
        sm.close()

        if not completed:
            await asyncio.to_thread(
                _mark_interview_abandoned,
                package.interview_id,
                package.org_id,
                agent.get_transcript(),
            )
            logger.info(
                "interview_abandoned",
                interview_id=package.interview_id,
            )
            return

        browser_events = await asyncio.to_thread(
            _load_integrity_events,
            package.interview_id,
            package.org_id,
        )
        live_correctness = {
            signal.question_id: signal.correctness
            for signal in agent.get_live_signals()
        }

        integrity = aggregate_integrity(
            org_id=package.org_id,
            browser_events=browser_events,
            state_machine=sm,
            answer_correctness_scores=live_correctness,
        )

        application_id = await asyncio.to_thread(
            _load_application_id,
            package.interview_id,
            package.org_id,
        )
        result, scoring_input = await run_postcall_pipeline(
            package=package,
            state_machine=sm,
            transcript=agent.get_transcript(),
            integrity=integrity,
            application_id=application_id,
        )

        await asyncio.to_thread(
            persist_result,
            scoring_input,
            result,
            agent.get_transcript(),
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
        await asyncio.to_thread(
            _mark_interview_scoring_failed,
            package.interview_id,
            package.org_id,
            agent.get_transcript(),
        )


def _load_integrity_events(interview_id: str, org_id: str) -> list[IntegrityEvent]:
    """Load the browser telemetry persisted during this interview."""
    result = (
        db().table("integrity_event")
        .select("org_id,interview_id,type,severity,at_ms,detail")
        .eq("org_id", org_id)
        .eq("interview_id", interview_id)
        .execute()
    )
    events: list[IntegrityEvent] = []
    for row in result.data:
        detail = row.get("detail", {})
        if isinstance(detail, str):
            try:
                detail = json.loads(detail)
            except json.JSONDecodeError:
                detail = {}
        events.append(IntegrityEvent.model_validate({**row, "detail": detail}))
    return events


def _persist_integrity_event(event: IntegrityEvent) -> None:
    db().table("integrity_event").insert(
        {
            "id": str(uuid.uuid4()),
            "org_id": event.org_id,
            "interview_id": event.interview_id,
            "type": event.type.value,
            "severity": event.severity,
            "at_ms": event.at_ms,
            "detail": event.detail,
        }
    ).execute()


def _load_application_id(interview_id: str, org_id: str) -> str:
    result = (
        db().table("interview")
        .select("application_id")
        .eq("org_id", org_id)
        .eq("id", interview_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise ValueError(f"Interview {interview_id} not found for post-call scoring")
    return result.data[0]["application_id"]


def _mark_interview_abandoned(
    interview_id: str,
    org_id: str,
    transcript: list[TranscriptTurn],
) -> None:
    """Finish an interview that ended before the completion gate passed."""
    (
        db().table("interview")
        .update({
            "status": "abandoned",
            "ended_at": datetime.now(UTC).isoformat(),
            "transcript": [turn.model_dump(mode="json") for turn in transcript],
        })
        .eq("org_id", org_id)
        .eq("id", interview_id)
        .execute()
    )


def _persist_interview_transcript(
    interview_id: str,
    org_id: str,
    transcript: list[TranscriptTurn],
) -> None:
    """Best-effort checkpoint; the next full snapshot retries any missed turn."""
    (
        db().table("interview")
        .update({"transcript": [turn.model_dump(mode="json") for turn in transcript]})
        .eq("org_id", org_id)
        .eq("id", interview_id)
        .execute()
    )


def _mark_interview_scoring_failed(
    interview_id: str,
    org_id: str,
    transcript: list[TranscriptTurn],
) -> None:
    """End the session visibly when post-call scoring cannot finish."""
    (
        db().table("interview")
        .update({
            "status": "flagged",
            "ended_at": datetime.now(UTC).isoformat(),
            "transcript": [turn.model_dump(mode="json") for turn in transcript],
        })
        .eq("org_id", org_id)
        .eq("id", interview_id)
        .execute()
    )


def _push_live_signal(
    org_id: str,
    interview_id: str,
    signal: LiveSignal,
    order_index: int,
) -> None:
    try:
        supabase = db()
        supabase.table("question_instance").upsert(
            {
                "org_id": org_id,
                "interview_id": interview_id,
                "question_id": signal.question_id,
                "order_index": order_index,
                "live_signal": signal.model_dump(),
            },
            on_conflict="interview_id,question_id",
        ).execute()
    except Exception:
        logger.exception("push_live_signal_failed")


def _worker_options() -> WorkerOptions:
    """Keep the job alive while deterministic post-call scoring is persisted."""
    return WorkerOptions(
        entrypoint_fnc=entrypoint,
        shutdown_process_timeout=180.0,
    )


if __name__ == "__main__":
    cli.run_app(_worker_options())
