"""合成同意 (P3.3): the person's own voice or portrait is used to synthesize only once they agreed to it, for that very
material; every agreement and withdrawal is kept for good; and a voice of theirs first says it is synthesized."""

from __future__ import annotations

import asyncio
import datetime as dt
import io
import sqlite3
import wave
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.assets import AssetStore
from twin.config import Settings, TTSSettings, VideoSettings
from twin.media.render import render_audio
from twin.media.schema import (
    SYNTHESIS_NOTICE,
    MediaScript,
    Segment,
    SpeechRequest,
    SpeechResult,
    SynthCapabilities,
    VoiceSpec,
)
from twin.media.stream import stream_audio
from twin.persona import consent
from twin.persona import store as storage
from twin.persona.store import PersonaStore, list_snapshots
from twin.web.app import create_app

NOW = dt.datetime(2026, 10, 31, 9, 0, tzinfo=dt.UTC)
HEADERS = {"X-Twin": "1"}


def wav(seconds: float) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\1\0" * int(24000 * seconds))
    return output.getvalue()


def test_the_latest_word_on_the_very_material_decides_and_every_word_is_kept(tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        assert not consent.consented(store, "voice", "a" * 64) and not consent.consented(store, "voice", None)
        consent.give(store, "voice", "a" * 64, NOW)
        assert consent.consented(store, "voice", "a" * 64)
        # Another recording, or the same one as a portrait, is not agreed to.
        assert not consent.consented(store, "voice", "b" * 64) and not consent.consented(store, "portrait", "a" * 64)
        consent.withdraw(store, "voice", "a" * 64, NOW)
        assert not consent.consented(store, "voice", "a" * 64)
        consent.give(store, "voice", "a" * 64, NOW)
        assert consent.consented(store, "voice", "a" * 64)
        said = store.consents()
    assert [(kind, granted) for _, kind, _, granted, _ in said] == [("voice", True), ("voice", False), ("voice", True)]
    assert said[0][0] == NOW.isoformat(timespec="seconds") and said[0][4] == consent.TEXTS["voice"]
    with closing(sqlite3.connect(tmp_path / "twin.db")) as db:
        for statement in ("UPDATE p_media_consent SET granted = 1", "DELETE FROM p_media_consent"):
            with pytest.raises(sqlite3.IntegrityError, match="append-only"):
                db.execute(statement)


def test_an_older_store_upgrades_to_the_consents_after_a_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    with closing(sqlite3.connect(path)) as db, db:
        for migration in storage._MIGRATIONS[:10]:  # the database as it was before consents
            db.executescript(migration)
        db.execute("PRAGMA user_version = 10")
    with PersonaStore(path) as store:
        assert store.schema_version() == len(storage._MIGRATIONS) and store.consents() == []
    assert [p.name for p in list_snapshots(path)][-1].endswith("-schema10.db")


class Own:
    """A speech backend that records what it was asked to say, in which voice."""

    name = "fake"
    identity = "fake-backend"
    capabilities = SynthCapabilities(audio_formats=["wav"], languages=["zh"], max_chars=1000)

    def __init__(self, voice_id: str) -> None:
        self.voice = VoiceSpec(voice_id=voice_id)
        self.said: list[str] = []

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        self.said.append(request.text)
        return SpeechResult(audio=wav(0.05), audio_format="wav", duration_s=0.05)


SCRIPT = MediaScript(
    source_kind="chat_reply",
    source_fingerprint="consent-test",
    persona_name="测试人",
    as_of=None,
    confidence=0.8,
    abstain=False,
    citations=[],
    segments=[Segment(index=0, kind="speech", text="第一句。"), Segment(index=1, kind="speech", text="第二句。")],
)


@pytest.mark.parametrize(("voice_id", "notice"), [("self-0123456789abcdef", True), ("preset", False)])
def test_audio_in_the_persons_own_voice_first_says_it_is_synthesized(
    tmp_path: Path, voice_id: str, notice: bool
) -> None:
    synth = Own(voice_id)
    rendered = render_audio(SCRIPT, synth, tmp_path / "cache")
    assert (synth.said[0] == SYNTHESIS_NOTICE) is notice and synth.said.count(SYNTHESIS_NOTICE) == int(notice)
    # Before the first part of whatever is rendered, as the first part of that segment.
    assert (rendered.segments[0].parts[0].spoken_text == SYNTHESIS_NOTICE) is notice
    one = Own(voice_id)
    render_audio(SCRIPT, one, tmp_path / "cache-one", segments=[1])
    assert (one.said[0] == SYNTHESIS_NOTICE) is notice

    async def streamed() -> None:
        async for _ in stream_audio(SCRIPT, streaming, tmp_path / "cache-stream"):
            pass

    streaming = Own(voice_id)
    asyncio.run(streamed())
    assert (streaming.said[0] == SYNTHESIS_NOTICE) is notice and streaming.said.count(SYNTHESIS_NOTICE) == int(notice)


def test_the_person_agrees_and_withdraws_on_the_web_and_video_waits_for_both(tmp_path: Path) -> None:
    settings = Settings(
        db_path=tmp_path / "twin.db",
        tts=TTSSettings(voice_dir=tmp_path / "voices"),
        video=VideoSettings(provider="remote", command="driver", require_assets=True),
    )
    assets = AssetStore(settings.db_path)
    with TestClient(create_app(settings), base_url="http://localhost") as web:

        def agree(kind: str, granted: bool = True) -> dict[str, bool]:
            response = web.post("/api/me/consent", json={"kind": kind, "granted": granted}, headers=HEADERS)
            assert response.status_code == 200, response.text
            return dict(response.json())

        def video() -> dict[str, object]:
            return dict(web.get("/api/media/capabilities").json()["video"])

        missing = web.post("/api/me/consent", json={"kind": "voice", "granted": True}, headers=HEADERS)
        assert missing.status_code == 404
        assets.save("voice", wav(6), 6)
        assets.save("portrait", b"portrait")
        shown = web.get("/api/me/assets").json()
        assert shown["consent"] == {"voice": False, "portrait": False} and shown["consent_texts"] == consent.TEXTS
        assert video()["reason"] == "先在「关于你」同意用你的形象和声音"
        assert agree("voice") == {"voice": True, "portrait": False}
        assert video()["reason"] == "先在「关于你」同意用你的形象和声音"
        assert agree("portrait") == {"voice": True, "portrait": True}
        assert "reason" not in video()
        assert agree("voice", False) == {"voice": False, "portrait": True}
        assert web.post("/api/media/video", json={"kind": "chat_reply", "answer": ANSWER}, headers=HEADERS).json() == {
            "detail": "先在「关于你」同意用你的形象和声音"
        }
    with PersonaStore(settings.db_path) as store:
        assert [(k, g) for _, k, _, g, _ in store.consents()] == [("voice", True), ("portrait", True), ("voice", False)]


ANSWER = {
    "reply": "有依据的回答。",
    "citations": [],
    "confidence": 0.8,
    "abstain": False,
    "abstain_reason": "",
    "retrieved_ids": [],
}
