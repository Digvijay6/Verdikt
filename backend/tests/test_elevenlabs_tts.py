"""Contract tests for the ElevenLabs LiveKit TTS adapter."""

from __future__ import annotations

import pytest

from voice import elevenlabs_rest_tts


class _FakeResponse:
    content = bytes(24_000 // 4 * 2)

    def raise_for_status(self) -> None:
        pass


class _FakeHttpClient:
    request: dict[str, object] = {}

    async def __aenter__(self) -> _FakeHttpClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def post(self, url: str, **kwargs: object) -> _FakeResponse:
        self.request = {"url": url, **kwargs}
        type(self).request = self.request
        return _FakeResponse()


@pytest.mark.asyncio
async def test_synthesize_emits_elevenlabs_pcm_as_one_complete_segment(monkeypatch) -> None:
    monkeypatch.setattr(elevenlabs_rest_tts.httpx, "AsyncClient", _FakeHttpClient)

    tts = elevenlabs_rest_tts.ElevenLabsRESTTTS(
        api_key="test-key",
        voice_id="test-voice",
    )
    events = []
    async with tts.synthesize("Hello from Verdikt") as stream:
        async for event in stream:
            events.append(event)

    assert events
    assert sum(event.frame.samples_per_channel for event in events) >= 6_000
    assert events[-1].is_final is True
    assert all(event.frame.sample_rate == 24_000 for event in events)
    assert all(event.frame.num_channels == 1 for event in events)
    assert _FakeHttpClient.request["params"] == {"output_format": "pcm_24000"}
    assert _FakeHttpClient.request["json"]["model_id"] == "eleven_flash_v2_5"
