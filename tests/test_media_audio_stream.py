"""Offline streaming protocol, caching, and cancellation contracts."""

from __future__ import annotations

import asyncio
import io
import json
import stat
import struct
import wave
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest
from fastapi.testclient import TestClient

from twin.config import AuthSettings, Settings, SMTPSettings, TTSSettings, make_synthesizer
from twin.media.schema import VoiceSpec
from twin.media.stream import SAMPLE_RATE, PCMResampler, frame
from twin.media.tts import CloudflareMeloTTS, OpenAICompatSpeech, SilentSynthesizer, wav_pcm
from twin.web import create_app

HEADERS = {"X-Twin": "1"}
BODY: dict[str, Any] = {
    "answer": {
        "reply": "首先核对 **API** 和 12 个参数。随后记录结果。",
        "citations": [],
        "confidence": 0.8,
        "abstain": False,
        "abstain_reason": "",
        "retrieved_ids": [],
    }
}


def decode(data: bytes) -> list[tuple[int, Any]]:
    frames = []
    offset = 0
    while offset < len(data):
        kind, size = struct.unpack_from(">BI", data, offset)
        payload = data[offset + 5 : offset + 5 + size]
        assert len(payload) == size
        frames.append((kind, payload if kind == 2 else json.loads(payload)))
        offset += 5 + size
    return frames


class PCMBody(httpx.AsyncByteStream):
    def __init__(self, *, block: bool = False) -> None:
        self.closed = False
        self.block = block

    async def __aiter__(self) -> AsyncIterator[bytes]:
        # Deliberately split a signed little-endian sample across HTTP chunks.
        yield b"\x00"
        yield b"\x10" * 9599
        if self.block:
            await asyncio.Event().wait()
        yield b"\x00\x10" * 4800

    async def aclose(self) -> None:
        self.closed = True


def synthesizer(
    handler: Any, *, model: str = "mock", voice: str = "default", streaming: bool = True
) -> OpenAICompatSpeech:
    return OpenAICompatSpeech(
        model,
        "http://speech.invalid/v1",
        voice=VoiceSpec(voice_id=voice),
        streaming=streaming,
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404))),
        async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


def test_encoding_and_resampling_are_chunk_independent() -> None:
    assert frame(2, b"\x01\x80") == b"\x02\x00\x00\x00\x02\x01\x80"
    assert decode(frame(1, {"caption": "中文"})) == [(1, {"caption": "中文"})]
    pcm = np.arange(-1000, 1000, dtype="<i2").tobytes()
    for rate in (16000, 24000, 44100, 48000):
        whole = PCMResampler(rate)
        expected = whole.convert(pcm) + whole.convert(b"", final=True)
        split = PCMResampler(rate)
        actual = b"".join(split.convert(pcm[i : i + 14]) for i in range(0, len(pcm), 14))
        actual += split.convert(b"", final=True)
        assert actual == expected
        assert len(actual) // 2 == (2000 * SAMPLE_RATE + rate - 1) // rate


def test_stream_order_cache_replay_voice_and_model(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []
    bodies: list[PCMBody] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        body = PCMBody()
        bodies.append(body)
        return httpx.Response(200, headers={"Content-Type": "audio/pcm", "X-Sample-Rate": "16000"}, stream=body)

    for model, voice in (("mock", "default"), ("new-model", "default"), ("mock", "new-voice")):
        synth = synthesizer(handler, model=model, voice=voice)
        with TestClient(
            create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=lambda synth=synth: synth),
            base_url="http://localhost",
        ) as client:
            before = len(calls)
            response = client.post("/api/media/audio/stream", json=BODY, headers=HEADERS)
            assert response.status_code == 200
            assert response.headers["content-type"] == "application/octet-stream"
            assert response.headers["cache-control"] == "no-store"
            assert response.headers["x-accel-buffering"] == "no"
            assert response.headers["x-content-type-options"] == "nosniff"
            frames = decode(response.content)
            assert frames[0] == (1, {"sample_rate": SAMPLE_RATE, "segments": 2})
            assert frames[1] == (1, {"segment": 0, "caption": "首先核对 API 和 12"})
            assert frames[2][0] == 2
            assert [payload["segment"] for kind, payload in frames[1:] if kind == 1] == [0, 1]
            size = sum(len(payload) for kind, payload in frames if kind == 2)
            assert frames[-1] == (3, {"duration_s": size / (SAMPLE_RATE * 2)})
            assert len(calls) == before + 2
            assert all(request.url.path == "/v1/audio/speech/stream" for request in calls)
            spoken = json.loads(calls[before].content)["input"]
            assert "**" not in spoken and "12" not in spoken
            replay = client.post("/api/media/audio/stream", json=BODY, headers=HEADERS)
            assert replay.content == response.content
            assert len(calls) == before + 2
    assert all(body.closed for body in bodies)
    entries = list((tmp_path / "media-cache" / "requests").glob("*.pcm-stream"))
    assert len(entries) == 3
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in entries)


@pytest.mark.parametrize("status", [404, 405, None])
def test_whole_wav_fallback(tmp_path: Path, status: int | None) -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x10" * 4800)
    paths = []

    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/stream"):
            return httpx.Response(status or 500, json={"detail": "unsupported"})
        assert json.loads(request.content)["response_format"] == "wav"
        return httpx.Response(200, content=output.getvalue(), headers={"Content-Type": "audio/wav"})

    synth = synthesizer(handler, streaming=status is not None)
    with TestClient(
        create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=lambda: synth),
        base_url="http://localhost",
    ) as client:
        frames = decode(client.post("/api/media/audio/stream", json=BODY, headers=HEADERS).content)
        assert frames[-1] == (3, {"duration_s": 0.4})
        assert b"".join(payload for kind, payload in frames if kind == 2) == b"\x00\x10" * 9600
        assert paths == (["/v1/audio/speech/stream", "/v1/audio/speech"] * 2 if status else ["/v1/audio/speech"] * 2)


@pytest.mark.parametrize("mode", ["status", "rate", "odd", "transport"])
def test_errors_are_framed_sanitized_and_not_cached(tmp_path: Path, mode: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        if mode == "transport":
            raise httpx.ConnectError("secret-token")
        return httpx.Response(
            500 if mode == "status" else 200,
            headers={"Content-Type": "audio/pcm", "X-Sample-Rate": "bad" if mode == "rate" else "24000"},
            content=b"x" if mode == "odd" else b"secret-token",
        )

    synth = synthesizer(handler)
    with TestClient(
        create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=lambda: synth),
        base_url="http://localhost",
    ) as client:
        frames = decode(client.post("/api/media/audio/stream", json=BODY, headers=HEADERS).content)
        assert frames[0][0] == 1
        assert frames[-1][0] == 4 and "语音" in frames[-1][1]["detail"]
        assert "secret-token" not in frames[-1][1]["detail"]
        assert not list((tmp_path / "media-cache").rglob("*.pcm-stream"))


def test_security_auth_and_persona_cache_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    settings = Settings(db_path=tmp_path / "twin.db")
    with TestClient(create_app(settings, synthesizer_factory=SilentSynthesizer), base_url="http://localhost") as client:
        assert client.post("/api/media/audio/stream", json=BODY).status_code == 403
        assert (
            client.post("/api/media/audio/stream", json=BODY, headers={**HEADERS, "Host": "evil.invalid"}).status_code
            == 403
        )
        assert client.post("/api/media/audio/stream", json={"answer": {}}, headers=HEADERS).status_code == 400
        assert (
            client.post(
                "/api/media/audio/stream", json=BODY, headers={**HEADERS, "X-Twin-Persona": "missing"}
            ).status_code
            == 404
        )
        persona = client.post("/api/personas", json={"name": "另一个人"}, headers=HEADERS).json()["id"]
        for selected in ("default", persona):
            result = client.post("/api/media/audio/stream", json=BODY, headers={**HEADERS, "X-Twin-Persona": selected})
            assert decode(result.content)[-1][0] == 3
        assert len(list(tmp_path.rglob("*.pcm-stream"))) == 2
    with TestClient(
        create_app(
            settings.model_copy(
                update={
                    "auth": AuthSettings(
                        enabled=True,
                        smtp=SMTPSettings(host="smtp.invalid", username="test", from_address="test@example.com"),
                    )
                }
            )
        ),
        base_url="http://localhost",
    ) as client:
        assert client.post("/api/media/audio/stream", json=BODY, headers=HEADERS).status_code == 401


@pytest.mark.parametrize("provider", ["openai_compat", "cloudflare"])
def test_immediate_meta_and_disconnect_close_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("TWIN_MOCK_TTS_KEY", "test-only")

    async def run() -> None:
        body = PCMBody(block=True)
        calls = 0
        disconnected = asyncio.Event()

        def handler(_: httpx.Request) -> httpx.Response:
            nonlocal calls
            calls += 1
            if provider == "cloudflare":
                disconnected.set()
            return httpx.Response(200, headers={"Content-Type": "audio/pcm", "X-Sample-Rate": "24000"}, stream=body)

        synth = (
            synthesizer(handler)
            if provider == "openai_compat"
            else CloudflareMeloTTS(
                "http://speech.invalid",
                api_key_env="TWIN_MOCK_TTS_KEY",
                async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
            )
        )
        web = create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=lambda: synth)
        sent: list[bytes] = []
        delivered = False

        async def receive() -> dict[str, Any]:
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": json.dumps(BODY).encode(), "more_body": False}
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.body" and message.get("body"):
                data = message["body"]
                sent.append(data)
                if len(sent) == 1:
                    assert calls == 0
                    assert decode(data)[0][1]["sample_rate"] == SAMPLE_RATE
                if data[0] == 2:
                    disconnected.set()

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/api/media/audio/stream",
            "raw_path": b"/api/media/audio/stream",
            "query_string": b"",
            "root_path": "",
            "headers": [(b"host", b"localhost"), (b"x-twin", b"1"), (b"content-type", b"application/json")],
            "server": ("localhost", 80),
            "client": ("127.0.0.1", 1234),
        }
        await asyncio.wait_for(web(scope, receive, send), timeout=5)
        assert body.closed
        assert calls == 1
        assert not list(tmp_path.rglob("*.pcm-stream"))
        await synth._async_client.aclose()  # type: ignore[union-attr]

    asyncio.run(run())


def test_cloudflare_whole_audio_uses_async_fallback_and_replays_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWIN_MOCK_TTS_KEY", "test-only")
    calls = []
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        wav.writeframes(b"\x00\x10" * 4800)

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, headers={"Content-Type": "audio/wav"}, content=output.getvalue())

    synth = CloudflareMeloTTS(
        "http://speech.invalid",
        api_key_env="TWIN_MOCK_TTS_KEY",
        async_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with TestClient(
        create_app(Settings(db_path=tmp_path / "twin.db"), synthesizer_factory=lambda: synth),
        base_url="http://localhost",
    ) as client:
        first = client.post("/api/media/audio/stream", json=BODY, headers=HEADERS)
        assert decode(first.content)[-1] == (3, {"duration_s": 0.4})
        assert calls == ["/run/@cf/myshell-ai/melotts"] * 2
        assert client.post("/api/media/audio/stream", json=BODY, headers=HEADERS).content == first.content
        assert len(calls) == 2


@pytest.mark.parametrize("width", [1, 2, 3, 4])
def test_wav_decode_converts_stereo_pcm_to_mono_s16le(width: int) -> None:
    output = io.BytesIO()
    sample = bytes([192]) if width == 1 else (16384 << (8 * (width - 2))).to_bytes(width, "little", signed=True)
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(width)
        wav.setframerate(44100)
        wav.writeframes(sample * 4)
    assert wav_pcm(output.getvalue()) == (44100, struct.pack("<hh", 16384, 16384))


def test_streaming_setting() -> None:
    assert TTSSettings().streaming
    synth = make_synthesizer(
        TTSSettings(provider="openai_compat", model="mock", base_url="http://localhost", streaming=False)
    )
    assert isinstance(synth, OpenAICompatSpeech) and not synth.streaming
