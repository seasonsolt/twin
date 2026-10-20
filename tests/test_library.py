"""The account recording library: upload, queued transcription with voiceprints, restart, capacity, backups."""

from __future__ import annotations

import io
import shutil
import time
import wave
from collections import namedtuple
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from twin.config import ASRSettings, LibrarySettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.ingest import CommandTranscriber, Progress, Segment, Speaker
from twin.media.library import Library, TranscriptionError, TranscriptionInterrupted, owner_key
from twin.ops.backup import backup, restore
from twin.ops.paths import TwinPaths
from twin.web import create_app

HEADERS = {"X-Twin": "1"}
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg required")


def wav_bytes(seconds: float = 1, tone: int = 0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes([tone, 0]) * int(seconds * 16000))
    return buffer.getvalue()


class FakeTranscriber(CommandTranscriber):
    """Two speakers with voiceprints, the way asr-funasr 1.3.0 answers a diarized request."""

    fail = False

    def __init__(self) -> None:
        super().__init__("unused")

    def transcribe(self, audio: Path, duration: float, progress: Progress) -> list[Segment]:
        assert self.diarize and self.reference is None and audio.is_file()
        if FakeTranscriber.fail:
            raise RuntimeError("private-backend-error")
        progress(duration / 2, duration)
        self.speakers = [
            Speaker(id="S1", seconds=0.6, embedding=[1.0, 0.0]),
            Speaker(id="S2", seconds=0.4, embedding=[0.0, 1.0]),
        ]
        return [
            Segment(start=0, end=0.6, text="先看预算。", speaker="S1"),
            Segment(start=0.6, end=0.6, text="", speaker="S2"),
            Segment(start=0.6, end=1, text="同意。", speaker="S2"),
        ]


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    FakeTranscriber.fail = False
    monkeypatch.setattr("twin.web.library.make_transcriber", lambda _: FakeTranscriber())
    settings = Settings(
        db_path=tmp_path / "twin.db",
        asr=ASRSettings(provider="command", command="unused"),
        library=LibrarySettings(headroom_gb=0, max_pending=3),
    )
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def upload(client: TestClient, data: bytes, name: str = "周会.wav") -> Any:
    created = client.post("/api/library/uploads", headers=HEADERS, json={"filename": name, "size": len(data)})
    if created.status_code != 200:
        return created
    uid = created.json()["id"]
    assert client.put(f"/api/library/uploads/{uid}?offset=0", headers=HEADERS, content=data).status_code == 200
    return client.post(f"/api/library/uploads/{uid}/finish", headers=HEADERS)


def test_a_recording_arrives_in_chunks_of_the_size_the_page_sends(client: TestClient) -> None:
    """The page sends 8 MiB per request, past the 1 MiB limit for ordinary requests; upload chunks are exempt."""
    chunk = b"\0" * (8 * 1024 * 1024)
    created = client.post(
        "/api/library/uploads", headers=HEADERS, json={"filename": "周会.m4a", "size": 2 * len(chunk)}
    )
    uid = created.json()["id"]
    for offset in (0, len(chunk)):
        put = client.put(f"/api/library/uploads/{uid}?offset={offset}", headers=HEADERS, content=chunk)
        assert put.status_code == 200, put.text
    assert put.json()["offset"] == 2 * len(chunk)


def settled(client: TestClient) -> dict[str, Any]:
    for _ in range(300):
        library = client.get("/api/library").json()
        if not library["pending"]:
            return dict(library)
        time.sleep(0.02)
    raise AssertionError("library did not settle")


@needs_ffmpeg
def test_upload_transcribes_once_keeps_voiceprints_and_drops_the_upload(client: TestClient, tmp_path: Path) -> None:
    first = upload(client, wav_bytes())
    assert first.status_code == 200 and first.json()["new"] is True
    recording = settled(client)["recordings"][0]
    assert recording["status"] == "ready" and recording["speakers"] == 2 and recording["segments"] == 3
    assert "sha256" not in recording

    library = Library(tmp_path / "library" / "team")
    stored = library.get(recording["id"])
    assert stored is not None
    transcript = library.transcript(stored)
    assert transcript is not None and transcript.id == recording["transcript_id"]
    # Empty segments stay: later stages cite a sentence by its index in this transcript.
    assert [s.text for s in transcript.segments] == ["先看预算。", "", "同意。"]
    assert [s.embedding for s in transcript.speakers] == [[1.0, 0.0], [0.0, 1.0]]
    folder = library.folder(recording["id"])
    assert sorted(p.name for p in folder.iterdir()) == ["playback.flac", f"transcript-{transcript.id}.json"]
    assert not list((tmp_path / "library" / "team" / "members" / "local" / "uploads").glob("*.part"))

    again = upload(client, wav_bytes(), "改了名字.wav")
    assert again.json()["new"] is False and again.json()["id"] == recording["id"]
    assert len(client.get("/api/library").json()["recordings"]) == 1


@needs_ffmpeg
def test_failed_transcription_keeps_the_upload_for_retry(client: TestClient, tmp_path: Path) -> None:
    FakeTranscriber.fail = True
    upload(client, wav_bytes())
    failed = settled(client)["recordings"][0]
    assert failed["status"] == "failed" and "private" not in failed["error"]
    folder = tmp_path / "library" / "team" / "recordings" / failed["id"]
    assert [p.name for p in folder.iterdir()] == ["original.wav"]
    FakeTranscriber.fail = False
    assert client.post(f"/api/library/recordings/{failed['id']}/retry", headers=HEADERS).status_code == 202
    assert settled(client)["recordings"][0]["status"] == "ready"
    assert client.post(f"/api/library/recordings/{failed['id']}/retry", headers=HEADERS).status_code == 409
    assert client.delete(f"/api/library/recordings/{failed['id']}", headers=HEADERS).json() == {"deleted": True}
    assert not folder.exists() and client.get("/api/library").json()["recordings"] == []


def test_interrupted_transcription_is_queued_again(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    part = tmp_path / "upload.part"
    part.write_bytes(wav_bytes())
    recording, new = library.add(part, "会议.wav")
    assert new and not part.exists()
    library.update(recording.id, status="transcribing", transcribed_s=0.5)
    assert library.resume() == 1
    resumed = library.get(recording.id)
    assert resumed and resumed.status == "queued" and resumed.transcribed_s == 0


@needs_ffmpeg
@pytest.mark.parametrize(
    ("command", "status"),
    [
        # Stopping the service signals the whole group: the shell running the command, or the command under it.
        ("kill -TERM $$", "queued"),
        ("bash -c 'kill -TERM $$'", "queued"),
        ("bash -c 'kill -HUP $$'", "queued"),
        # Anything else is the transcription failing.
        ("exit 1", "failed"),
        ("bash -c 'kill -KILL $$'", "failed"),
    ],
)
def test_a_transcription_cut_off_by_a_stop_waits_again_instead_of_failing(
    tmp_path: Path, command: str, status: str
) -> None:
    library = Library(tmp_path / "library" / "team")
    part = tmp_path / "upload.part"
    part.write_bytes(wav_bytes())
    recording, _ = library.add(part, "会议.wav")
    with pytest.raises(TranscriptionError) as raised:
        library.transcribe(recording.id, CommandTranscriber(command), lambda done, total: None)
    assert isinstance(raised.value, TranscriptionInterrupted) == (status == "queued")
    after = library.get(recording.id)
    assert after is not None and after.status == status and after.transcribed_s == 0
    assert after.error == ("" if status == "queued" else "语音识别失败，请检查转写服务后重试")
    # The upload stays, to be transcribed again.
    assert [p.name for p in library.folder(recording.id).iterdir()] == ["original.wav"]


@needs_ffmpeg
def test_a_stop_right_after_publishing_leaves_a_ready_recording(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The recording is published before its upload is deleted: a stop in between never strands a queued recording
    whose upload is gone, and the next start deletes the leftover upload."""
    library = Library(tmp_path / "library" / "team")
    part = tmp_path / "upload.part"
    part.write_bytes(wav_bytes())
    recording, _ = library.add(part, "会议.wav")
    unlink = Path.unlink

    def stopped(self: Path, missing_ok: bool = False) -> None:
        if self.name.startswith("original."):
            raise KeyboardInterrupt
        unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(Path, "unlink", stopped)
    with pytest.raises(KeyboardInterrupt):
        library.transcribe(recording.id, FakeTranscriber(), lambda done, total: None)
    monkeypatch.undo()
    folder = library.folder(recording.id)
    assert (folder / "original.wav").is_file()
    published = library.get(recording.id)
    assert published and published.status == "ready" and published.transcript_id
    assert library.resume() == 0
    assert not (folder / "original.wav").exists() and library.transcript(published) is not None


def test_uploads_are_admitted_by_free_space_and_queue_length(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    usage = namedtuple("usage", "total used free")
    monkeypatch.setattr("twin.web.library.shutil.disk_usage", lambda _: usage(100, 90, 10))
    refused = upload(client, wav_bytes())
    assert refused.status_code == 507 and "磁盘空间不足" in refused.json()["detail"]
    monkeypatch.setattr("twin.web.library.shutil.disk_usage", lambda _: usage(10**12, 0, 10**12))
    # Without a transcription service recordings wait; three may wait at once.
    monkeypatch.setattr("twin.web.library.make_transcriber", lambda _: None)
    for tone in range(3):
        assert upload(client, wav_bytes(tone=tone)).status_code == 200
    library = client.get("/api/library").json()
    assert library["pending"] == 3 and library["asr"] is False
    assert upload(client, wav_bytes(tone=9)).status_code == 409


def test_library_is_not_scoped_to_a_twin(client: TestClient) -> None:
    assert client.get("/api/library?persona=does-not-exist").status_code == 200
    assert owner_key(None) == "local"
    assert owner_key("Boss@Example.com") == owner_key("boss@example.com") != owner_key("other@example.com")
    assert "@" not in owner_key("boss@example.com")


def test_backups_hard_link_library_recordings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_HOME", str(tmp_path / "home"))
    data = tmp_path / "data"
    folder = data / "library" / "team" / "recordings" / "rec_1"
    folder.mkdir(parents=True)
    for name in ("transcript-a.json", "playback.flac", "original.wav", "audio.wav", ".transcript-b.json.tmp"):
        (folder / name).write_bytes(b"x")
    # An old library set aside when it was merged into the team's.
    aside = data / "library" / ".legacy" / "abc" / "recordings" / "rec_2"
    aside.mkdir(parents=True)
    (aside / "playback.flac").write_bytes(b"z")
    (data / "notes").mkdir()
    (data / "notes" / "recordings").mkdir()
    (data / "notes" / "recordings" / "copy.txt").write_text("y")
    target = backup(TwinPaths.from_env(), data, tmp_path / "twin.toml")
    copied = target / "data" / "library" / "team" / "recordings" / "rec_1"
    assert sorted(p.name for p in copied.iterdir()) == ["playback.flac", "transcript-a.json"]
    assert (copied / "playback.flac").stat().st_ino == (folder / "playback.flac").stat().st_ino
    kept = target / "data" / "library" / ".legacy" / "abc" / "recordings" / "rec_2" / "playback.flac"
    assert kept.stat().st_ino == (aside / "playback.flac").stat().st_ino
    other = target / "data" / "notes" / "recordings" / "copy.txt"
    assert other.stat().st_ino != (data / "notes" / "recordings" / "copy.txt").stat().st_ino
    # A restore copies: the restored recordings share no file with the backup.
    restored = tmp_path / "restored"
    restore(target, restored, tmp_path / "restored.toml", services_stopped=True)
    back = restored / "library" / "team" / "recordings" / "rec_1"
    assert sorted(p.name for p in back.iterdir()) == ["playback.flac", "transcript-a.json"]
    assert (back / "playback.flac").stat().st_ino != (copied / "playback.flac").stat().st_ino
