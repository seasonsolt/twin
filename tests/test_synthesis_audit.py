"""合成标识评测 (P3.7): for every state of the person's consent, through the web, what is synthesized uses their own
voice or portrait only as far as they agreed to, and audio in their own voice first says it is synthesized.

Each part is tested on its own elsewhere (``test_consent``, ``test_media_video``, ``test_media_clip``); this walks the
whole matrix end to end, so that no state is left where their material is used unsaid or without their word."""

from __future__ import annotations

import io
import wave
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from twin.assets import AssetStore
from twin.config import Settings, TTSSettings, VideoSettings
from twin.media.schema import (
    SYNTHESIS_NOTICE,
    MediaScript,
    SpeechRequest,
    SpeechResult,
    SynthCapabilities,
    VideoResult,
    VoiceSpec,
)
from twin.web.app import create_app

HEADERS = {"X-Twin": "1"}
MEDIA = {
    "kind": "chat_reply",
    "answer": {
        "reply": "第一句。第二句。",
        "citations": [],
        "confidence": 0.8,
        "abstain": False,
        "abstain_reason": "",
        "retrieved_ids": [],
    },
}


def wav(seconds: float) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\1\0" * int(24000 * seconds))
    return output.getvalue()


class Speech:
    """A speech backend that records what it was asked to say."""

    name = "fake"
    identity = "fake-backend"
    capabilities = SynthCapabilities(audio_formats=["wav"], languages=["zh"], max_chars=1000)

    def __init__(self, voice_id: str) -> None:
        self.voice = VoiceSpec(voice_id=voice_id)
        self.said: list[str] = []

    def synthesize(self, request: SpeechRequest) -> SpeechResult:
        self.said.append(request.text)
        return SpeechResult(audio=wav(0.05), audio_format="wav", duration_s=0.05)


class Video:
    name = "fake"

    def synthesize(self, script: MediaScript, out_path: Path) -> VideoResult:
        out_path.write_bytes(b"video")
        return VideoResult(output=out_path, duration_s=1, warnings=[])


@pytest.mark.parametrize("voice", [False, True])
@pytest.mark.parametrize("portrait", [False, True])
def test_their_material_is_used_only_as_far_as_they_agreed_and_their_voice_says_it_is_synthesized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, voice: bool, portrait: bool
) -> None:
    speakers: list[Speech] = []
    videos: list[bool] = []

    def speech(config: TTSSettings) -> Speech:
        speakers.append(Speech(config.voice))
        return speakers[-1]

    def video(settings: Settings, own: bool = True) -> Video:
        videos.append(own)
        return Video()

    monkeypatch.setattr("twin.web.media.make_synthesizer", speech)
    monkeypatch.setattr("twin.web.media.make_video_synthesizer", video)
    settings = Settings(
        db_path=tmp_path / "twin.db",
        tts=TTSSettings(voice="preset", voice_dir=tmp_path / "voices"),
        video=VideoSettings(provider="remote", command="driver", require_assets=False),
    )
    assets = AssetStore(settings.db_path)
    assets.save("voice", wav(6), 6)
    assets.save("portrait", b"portrait")
    with TestClient(create_app(settings), base_url="http://localhost") as web:

        def agree(kind: str, granted: bool) -> None:
            response = web.post("/api/me/consent", json={"kind": kind, "granted": granted}, headers=HEADERS)
            assert response.status_code == 200, response.text

        def check(voice: bool, portrait: bool) -> None:
            capabilities: dict[str, Any] = web.get("/api/media/capabilities").json()
            assert capabilities["own_voice"] is voice and capabilities["video"]["own"] is (voice and portrait)
            audio = web.post("/api/media/audio", json=MEDIA, headers=HEADERS)
            assert audio.status_code == 200, audio.text
            manifest = audio.json()["manifest"]
            assert manifest["ai_generated"] is True and speakers[-1].voice.own is voice
            # Said once, before anything else, only in their own voice (a repeat is served from the cache).
            parts = [part["spoken_text"] for segment in manifest["segments"] for part in segment["parts"]]
            assert (parts[0] == SYNTHESIS_NOTICE) is voice and parts.count(SYNTHESIS_NOTICE) == int(voice)
            submitted = web.post("/api/media/video", json=MEDIA, headers=HEADERS)
            assert submitted.status_code == 200, submitted.text
            assert videos[-1] is (voice and portrait)

        agree("voice", voice)
        agree("portrait", portrait)
        check(voice, portrait)
        # Withdrawn, nothing of theirs is used any more.
        agree("voice", False)
        agree("portrait", False)
        check(False, False)
        agree("voice", voice)
        agree("portrait", portrait)
        check(voice, portrait)
        # Another recording or picture is not what they agreed to.
        assets.save("voice", wav(7), 7)
        assets.save("portrait", b"another portrait")
        check(False, False)
