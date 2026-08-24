"""Contract tests for the custom Rumik LiveKit TTS adapter."""

from __future__ import annotations

import json

import pytest

from voice import rumik_tts


class _FakeMintResponse:
    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, str]:
        return {
            "ws_url": "wss://rumik.test/tts",
            "token": "session-token",
        }


class _FakeHttpClient:
    async def __aenter__(self) -> _FakeHttpClient:
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def post(self, *_args: object, **_kwargs: object) -> _FakeMintResponse:
        return _FakeMintResponse()


class _FakeWebSocket:
    def __init__(self) -> None:
        # 250 ms of silent 24 kHz, 16-bit mono PCM, then Rumik's done event.
        self._messages = iter((bytes(24_000 // 4 * 2), json.dumps({"type": "done"})))
        self.sent: list[str] = []

    async def __aenter__(self) -> _FakeWebSocket:
        return self

    async def __aexit__(self, *_args: object) -> None:
        pass

    async def send(self, message: str) -> None:
        self.sent.append(message)

    def __aiter__(self) -> _FakeWebSocket:
        return self

    async def __anext__(self) -> bytes | str:
        try:
            return next(self._messages)
        except StopIteration as error:
            raise StopAsyncIteration from error


@pytest.mark.asyncio
async def test_synthesize_emits_pcm_audio_as_one_complete_segment(monkeypatch) -> None:
    websocket = _FakeWebSocket()
    monkeypatch.setattr(rumik_tts.httpx, "AsyncClient", _FakeHttpClient)
    monkeypatch.setattr(
        rumik_tts.websockets,
        "connect",
        lambda *_args, **_kwargs: websocket,
    )

    tts = rumik_tts.RumikTTS(api_key="test-key")
    events = []
    async with tts.synthesize("Hello from Verdikt") as stream:
        async for event in stream:
            events.append(event)

    assert events
    # LiveKit may append a 10 ms final marker after the provider audio.
    assert sum(event.frame.samples_per_channel for event in events) >= 6_000
    assert events[-1].is_final is True
    assert all(event.frame.sample_rate == 24_000 for event in events)
    assert all(event.frame.num_channels == 1 for event in events)
    assert json.loads(websocket.sent[0])["text"] == "Hello from Verdikt"
