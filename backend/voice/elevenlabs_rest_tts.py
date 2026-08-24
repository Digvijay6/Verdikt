"""ElevenLabs REST TTS adapter for LiveKit's PCM audio emitter."""

from __future__ import annotations

import os
import uuid

import httpx
import structlog
from livekit.agents import tts as tts_mod
from livekit.agents.tts import (
    TTS,
    TTSCapabilities,
)
from livekit.agents.types import APIConnectOptions

logger = structlog.get_logger(__name__)

SAMPLE_RATE = 24_000
NUM_CHANNELS = 1


class ElevenLabsRESTTTS(TTS):
    """ElevenLabs TTS using the REST API instead of WebSocket."""

    def __init__(
        self,
        *,
        voice_id: str = "EXAVITQu4vr4xnSDxMaL",
        api_key: str | None = None,
        model_id: str = "eleven_flash_v2_5",
    ) -> None:
        super().__init__(
            capabilities=TTSCapabilities(
                streaming=False,
            ),
            sample_rate=SAMPLE_RATE,
            num_channels=NUM_CHANNELS,
        )
        self._voice_id = voice_id
        self._api_key = api_key or os.environ.get("ELEVENLABS_API_KEY", "")
        self._model_id = model_id

    def synthesize(
        self,
        text: str,
        *,
        conn_options: APIConnectOptions | None = None,
    ) -> tts_mod.ChunkedStream:
        """Synthesize text to audio via REST API."""
        if conn_options is None:
            conn_options = APIConnectOptions()
        return _RESTChunkedStream(
            tts=self,
            input_text=text,
            conn_options=conn_options,
        )


class _RESTChunkedStream(tts_mod.ChunkedStream):
    """A ChunkedStream that fetches audio from the ElevenLabs REST API."""

    def __init__(
        self,
        *,
        tts: ElevenLabsRESTTTS,
        input_text: str,
        conn_options: APIConnectOptions,
    ) -> None:
        super().__init__(tts=tts, input_text=input_text, conn_options=conn_options)
        self._tts = tts
        self._text = input_text

    async def _run(self, output_emitter) -> None:
        """Fetch audio from REST API and emit it as chunks."""
        try:
            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self._tts._voice_id}"
            headers = {
                "xi-api-key": self._tts._api_key,
                "Content-Type": "application/json",
                "Accept": "audio/pcm",
            }
            payload = {
                "text": self._text,
                "model_id": self._tts._model_id,
                "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
            }

            logger.info(
                "elevenlabs_rest_tts",
                voice=self._tts._voice_id,
                text_len=len(self._text),
            )

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    params={"output_format": "pcm_24000"},
                    headers=headers,
                    json=payload,
                    timeout=30,
                )
                response.raise_for_status()

                audio_data = response.content
                logger.info(
                    "elevenlabs_rest_tts_ok",
                    audio_bytes=len(audio_data),
                )

                output_emitter.initialize(
                    request_id=f"elevenlabs-{uuid.uuid4().hex[:8]}",
                    sample_rate=SAMPLE_RATE,
                    num_channels=NUM_CHANNELS,
                    mime_type="audio/pcm",
                    stream=False,
                )
                output_emitter.push(audio_data)
                output_emitter.flush()

        except Exception as e:
            logger.exception("elevenlabs_rest_tts_failed", error=str(e))
            raise
