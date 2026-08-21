"""LANE 2 — LiveKit voice worker.

Run: python -m voice.agent dev

Not a web service. It subscribes to LiveKit job dispatch, joins the room it is
assigned, reads the InterviewPackage from room metadata, conducts the interview,
and writes results to Supabase. Nothing makes requests to it.

Two constraints worth knowing before designing the question flow:

  1. On gemini-3.1-flash-live-preview, LiveKit documents that generate_reply(),
     update_instructions(), and update_chat_ctx() do not work mid-session, and
     async function calling is unavailable. Adaptive probing therefore has to be
     driven by function calling plus a question state machine, not by rewriting
     instructions mid-call. The 2.5 native-audio model does not have these
     limits — pick deliberately, and record which in Interview.model_id.

  2. Speech-to-speech means no live diarization. Multi-speaker detection runs
     post-call over the recorded candidate track. Cheat signals do not need to
     be realtime; they need to land with the score.
"""

from livekit.agents import JobContext, WorkerOptions, cli

from shared.models.interview import InterviewPackage


async def entrypoint(ctx: JobContext) -> None:
    """Join the assigned room and conduct the interview."""
    await ctx.connect()

    package = InterviewPackage.model_validate_json(ctx.job.metadata)  # noqa: F841

    # 1. build the session (Gemini Live via LiveKit's google plugin)
    # 2. walk package.questions through the state machine in voice/interview/
    # 3. stream LiveSignal per answer -> Supabase realtime -> recruiter view
    # 4. on close: voice/scoring/ two-pass re-score, voice/proctor/ diarization
    raise NotImplementedError


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint))
