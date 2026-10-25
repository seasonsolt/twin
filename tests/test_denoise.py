"""Denoised copies for listening (``media.denoise``): made when the service can, one recording at a time and those
transcribed before it too, kept only when whole; what people hear plays them unless they ask for the original,
and what the library computes keeps the original."""

from __future__ import annotations

import datetime as dt
import io
import math
import shutil
import threading
import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_recollect import OLD, playback
from test_team import recording, until

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media import denoise
from twin.media.ingest import CommandTranscriber, Progress, Speaker
from twin.media.library import Library
from twin.web import create_app

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")

SPEAKERS = [Speaker(id=f"S{n}", seconds=10, embedding=[float(n == k) for k in range(1, 5)]) for n in range(1, 5)]


class Quieter(CommandTranscriber):
    """A service that denoises: a constant tone as long as the input, or ``seconds`` long."""

    def __init__(self, can: bool = True, seconds: float | None = None, fail: bool = False) -> None:
        super().__init__("unused")
        self.can, self.seconds, self.fail = can, seconds, fail
        self.heard: list[Path] = []

    def can_denoise(self) -> bool:
        return self.can

    def denoise(self, audio: Path, output: Path, duration: float, progress: Progress) -> None:
        self.heard.append(audio)
        if self.fail:
            raise RuntimeError("转写服务没能降噪")
        with wave.open(str(output), "wb") as wav:
            wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
            wav.writeframes(b"\x10\x27" * int(16000 * (duration if self.seconds is None else self.seconds)))


def frames(clip: bytes) -> bytes:
    with wave.open(io.BytesIO(clip), "rb") as wav:
        return wav.readframes(wav.getnframes())


def meeting(library: Library, seconds: int = 60) -> str:
    recording_id = recording(library, "2026-03-02 周会.m4a", OLD, SPEAKERS)
    playback(library, recording_id)
    with wave.open(str(library.folder(recording_id) / "playback.flac"), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(2) * 16000 * seconds)
    return recording_id


@pytest.mark.codec
def test_a_whole_denoised_copy_is_what_people_hear(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    first, second = meeting(library), meeting(library)
    assert [r.id for r in denoise.waiting(library)] == [first, second]
    service = Quieter()
    assert denoise.run(library, first, service, lambda done, total: None) is True
    folder = library.folder(first)
    assert service.heard == [folder / "playback.flac"]
    assert denoise.listening(library, first) == folder / denoise.DENOISED
    assert denoise.listening(library, first, original=True) == folder / "playback.flac"
    assert denoise.listening(library, second) == library.folder(second) / "playback.flac"
    assert (folder / denoise.DENOISED).stat().st_mode & 0o777 == 0o600
    assert [r.id for r in denoise.waiting(library)] == [second]
    # Made once: asked again, nothing is sent.
    assert denoise.run(library, first, service, lambda done, total: None) is False and len(service.heard) == 1
    assert library.delete(first)
    with library.read() as db:
        assert db.execute("SELECT count(*) FROM denoised").fetchone()[0] == 0


@pytest.mark.parametrize("service", [Quieter(seconds=30), Quieter(fail=True)])
@pytest.mark.codec
def test_a_copy_that_cannot_be_made_whole_is_noted_and_tried_later(tmp_path: Path, service: Quieter) -> None:
    library = Library(tmp_path / "library" / "team")
    recording_id = meeting(library)
    with pytest.raises(RuntimeError):
        denoise.run(library, recording_id, service, lambda done, total: None)
    folder = library.folder(recording_id)
    assert not denoise.denoised(library, recording_id)
    assert [p.name for p in folder.iterdir() if p.name.startswith(".")] == []
    # The queue moves on, and comes back to it after a while.
    assert denoise.waiting(library) == []
    with library.transaction() as db:
        then = (dt.datetime.now(dt.UTC) - denoise.RETRY - dt.timedelta(minutes=1)).isoformat()
        db.execute("UPDATE denoised SET created_at = ?", (then,))
    assert [r.id for r in denoise.waiting(library)] == [recording_id]


@pytest.mark.codec
def test_the_library_denoises_when_idle_and_plays_the_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library = Library(tmp_path / "library" / "team")
    recording_id = meeting(library)
    service = Quieter()
    monkeypatch.setattr("twin.web.library.make_transcriber", lambda _: service)
    settings = Settings(db_path=tmp_path / "twin.db")
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        assert web.get(f"/api/library/recordings/{recording_id}").json()["denoised"] is False
        until(lambda: web.get("/api/library").status_code == 200 and denoise.denoised(library, recording_id))
        assert web.get(f"/api/library/recordings/{recording_id}").json()["denoised"] is True
        heard = web.get(f"/api/library/recordings/{recording_id}/speakers/S1/samples/0")
        original = web.get(f"/api/library/recordings/{recording_id}/speakers/S1/samples/0?original=true")
        assert heard.status_code == original.status_code == 200
        # The copy is a tone; the recording itself is silence.
        assert set(frames(original.content)) == {0} and set(frames(heard.content)) != {0}


@pytest.mark.codec
def test_a_service_that_cannot_denoise_is_not_asked_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library = Library(tmp_path / "library" / "team")
    recording_id = meeting(library)
    service = Quieter(can=False)
    monkeypatch.setattr("twin.web.library.make_transcriber", lambda _: service)
    settings = Settings(db_path=tmp_path / "twin.db")
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        libraries = app.state.libraries
        until(lambda: web.get("/api/library").status_code == 200 and libraries._denoise_asked > -math.inf)
        until(lambda: not any(t.name == "library-denoise-ask" for t in threading.enumerate()))
        web.get("/api/library")
        sample = web.get(f"/api/library/recordings/{recording_id}/speakers/S1/samples/0")
        assert sample.status_code == 200
    assert service.heard == [] and not denoise.denoised(library, recording_id)
