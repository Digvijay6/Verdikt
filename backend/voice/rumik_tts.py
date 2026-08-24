"""Rumik TTS plugin for LiveKit.

Uses Rumik's WebSocket streaming API for low-latency TTS with barge-in support.

Protocol:
1. Mint a session: POST /v1/tts/ws-connect → { ws_url, token }
2. Connect to ws_url?token=<token>
3. Send {"text": "...", "speaker": "noah", "description": "..."}
4. Receive binary PCM chunks (int16, 24kHz, mono)
5. Receive {"type": "done"} when generation finishes

Barge-in: sending a new {"text": "..."} frame cancels the current generation.
"""

from __future__ import annotations

import json
import os
import uuid

import httpx
import structlog
import websockets
from livekit.agents import tts as tts_mod
from livekit.agents.tts import (
    TTS,
    TTSCapabilities,
)
from livekit.agents.types import APIConnectOptions

logger = structlog.get_logger(__name__)

BASE_URL = "https://silk-api.rumik.ai"
SAMPLE_RATE = 24000
NUM_CHANNELS = 1


class RumikTTS(TTS):
    """Rumik TTS using WebSocket streaming.

    Sessions are minted per synthesis call (one-shot).
    For live calls with barge-in, use the streaming API directly.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str = "mulberry",
        speaker: str = "noah",
        description: str = (
            "a professional male voice, calm, conversational, "
            "like an interviewer"
        ),
    ) -> None:
        super().__init__(
            capabilities=TTSCapabilities(
                streaming=False,
            ),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._api_key = api_key or os.environ.get("RUMIK_API_KEY", "")
        self._model = model
        self._speaker = speaker
        self._description = description

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions | None = None,
    ) -> tts_mod.ChunkedStream:
        if conn_options is None:
            conn_options = APIConnectOptions()
        return _RumikChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )


class _RumikChunkedStream(tts_mod.ChunkedStream):
    """Streams audio from Rumik's WebSocket TTS API."""

    def __init__(
        self,
        *,
        tts: RumikTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts
        self._text = input_text

    async def _run(self, output_emitter) -> None:
        """Mint a session, connect, send text, collect PCM chunks."""
        try:
            # 1. Mint a session
            async with httpx.AsyncClient() as client:
                r = await client.post(
                    f"{BASE_URL}/v1/tts/ws-connect",
                    headers={"Authorization": f"Bearer {self._tts._api_key}"},
                    json={
                        "model": self._tts._model,
                        "text": self._text,
                    },
                    timeout=15,
                )
                r.raise_for_status()
                data = r.json()

            ws_url = f'{data["ws_url"]}?token={data["token"]}'

            logger.info(
                "rumik_tts_session",
                ws_url=data["ws_url"],
                text_len=len(self._text),
            )

            # 2. Connect and send synthesis frame
            async with websockets.connect(ws_url, open_timeout=10) as ws:
                await ws.send(json.dumps({
                    "text": self._text,
                    "speaker": self._tts._speaker,
                    "description": self._tts._description,
                }))

                # 3. Initialize the output emitter
                output_emitter.initialize(
                    request_id=f"rumik-{uuid.uuid4().hex[:8]}",
                    sample_rate=SAMPLE_RATE,
                    num_channels=NUM_CHANNELS,
                    mime_type="audio/pcm",
                    # ChunkedStream is one synthesis segment. LiveKit starts
                    # that segment automatically only in non-streaming mode.
                    stream=False,
                )

                # 4. Collect PCM chunks and push them
                total_bytes = 0

                async for msg in ws:
                    if isinstance(msg, bytes):
                        total_bytes += len(msg)
                        output_emitter.push(bytes(msg))
                    else:
                        parsed = json.loads(msg)
                        if parsed.get("type") == "done":
                            break
                        elif parsed.get("error"):
                            logger.error(
                                "rumik_tts_error",
                                error=parsed,
                            )
                            break

            output_emitter.flush()

            logger.info(
                "rumik_tts_done",
                total_bytes=total_bytes,
            )

        except Exception as e:
            logger.exception("rumik_tts_failed", error=str(e))
            raise
