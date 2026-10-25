from __future__ import annotations

import io
import json
import math
import os
import struct
import threading
import time
import wave
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from twin.config import ASRSettings, Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.ingest import CommandTranscriber, HTTPTranscriber, Segment, silence_chunks, timestamp, transcript_text
from twin.media.schema import ASRCapabilities, Transcription, TranscriptionRequest
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import JobManager, describe_error
from twin.web.uploads import MAX_CHUNK_SIZE, MAX_MEDIA_SIZE, MediaIngestion, UploadBody, Uploads

HEADERS = {"X-Twin": "1"}


def wav_bytes(seconds: float = 1) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(b"\0\0" * int(seconds * 16000))
    return buffer.getvalue()


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = Settings(db_path=tmp_path / "twin.db", max_workers=1)
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def create(client: TestClient, data: bytes, name: str = "录音.wav") -> str:
    response = client.post(
        "/api/uploads", headers=HEADERS, json={"filename": name, "size": len(data), "type": "audio/wav"}
    )
    assert response.status_code == 200
    assert response.json()["chunk_size"] == 8 * 1024**2
    return str(response.json()["id"])


def wait_job(client: TestClient, job_id: str) -> dict[str, Any]:
    for _ in range(200):
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in {"done", "failed"}:
            return dict(job)
        time.sleep(0.02)
    raise AssertionError("job did not finish")


def finish(client: TestClient, data: bytes, name: str = "录音.wav") -> dict[str, Any]:
    uid = create(client, data, name)
    assert client.put(f"/api/uploads/{uid}?offset=0", headers=HEADERS, content=data).status_code == 200
    response = client.post(f"/api/uploads/{uid}/finish", headers=HEADERS)
    assert response.status_code == 200
    return dict(response.json())


@pytest.mark.codec
def test_chunk_resume_finish_limits_and_csrf(client: TestClient, tmp_path: Path) -> None:
    data = wav_bytes()
    uid = create(client, data)
    path = f"/api/uploads/{uid}"
    assert client.put(path + "?offset=0", content=data).status_code == 403
    assert client.put(path + "?offset=0", headers=HEADERS, content=data[:20]).json() == {"offset": 20}
    conflict = client.put(path + "?offset=0", headers=HEADERS, content=data)
    assert conflict.status_code == 409 and conflict.json() == {"offset": 20}
    assert client.get(path).json() == {"offset": 20, "size": len(data)}
    assert client.post(path + "/finish", headers=HEADERS).status_code == 400
    assert client.put(path + "?offset=20", headers=HEADERS, content=data[20:] + b"extra").status_code == 413
    assert client.get(path).json()["offset"] == 20
    assert client.put(path + "?offset=20", headers=HEADERS, content=data[20:]).json()["offset"] == len(data)
    result = client.post(path + "/finish", headers=HEADERS).json()
    assert wait_job(client, result["job_id"])["status"] == "done"
    assert client.post(path + "/finish", headers=HEADERS).json()["source_id"] == result["source_id"]
    assert client.get(path).json()["offset"] == len(data)
    row = client.get("/api/persona/sources").json()["items"][0]
    assert row["status"] == "needs_asr" and row["duration_s"] == 1
    folder = tmp_path / "media-sources" / row["media_sha"]
    assert (folder / "original.wav").read_bytes() == data
    assert folder.stat().st_mode & 0o777 == 0o700
    assert (folder / "original.wav").stat().st_mode & 0o777 == 0o600
    # Nothing was transcribed, so no extracted audio is kept; a retry extracts it again.
    assert not (folder / "audio.wav").exists() and not (folder / "audio.flac").exists()
    for size, name, status in [(MAX_MEDIA_SIZE + 1, "a.mp4", 413), (0, "a.wav", 400), (1, "a.exe", 400)]:
        response = client.post("/api/uploads", headers=HEADERS, json={"filename": name, "size": size})
        assert response.status_code == status and not response.json()["detail"].isascii()
    assert client.get("/api/uploads/../../bad").status_code == 404
    assert client.delete(path, headers=HEADERS).json() == {"deleted": True}
    assert client.get(path).status_code == 404


def test_large_stream_bypasses_json_cap_and_rolls_back(client: TestClient, tmp_path: Path) -> None:
    data = b"x" * (2 * 1024**2)
    uid = create(client, data)
    assert client.put(f"/api/uploads/{uid}?offset=0", headers=HEADERS, content=data).status_code == 200
    assert (tmp_path / "uploads" / f"{uid}.part").stat().st_mode & 0o777 == 0o600
    uid = create(client, b"x" * (MAX_CHUNK_SIZE + 1))
    response = client.put(
        f"/api/uploads/{uid}?offset=0", headers={**HEADERS, "Content-Length": "0"}, content=b"x" * (MAX_CHUNK_SIZE + 1)
    )
    assert response.status_code == 413
    assert client.get(f"/api/uploads/{uid}").json()["offset"] == 0


def test_cleanup_and_disk_resume(client: TestClient, tmp_path: Path) -> None:
    uploads = Uploads(tmp_path)
    old = uploads.create(UploadBody(filename="a.mp4", size=5))
    uploads.append(old["id"], b"12")
    assert Uploads(tmp_path).load(old["id"])["offset"] == 2
    metadata, part = uploads.paths(old["id"])
    (uploads.root / "notes.json").write_text("{}")
    os.utime(uploads.root / "notes.json", (time.time() - 86401, time.time() - 86401))
    os.utime(metadata, (time.time() - 86401, time.time() - 86401))
    # Creating an upload removes the ones untouched for a day, and leaves files that are not uploads alone.
    response = client.post("/api/uploads", headers=HEADERS, json={"filename": "fresh.mov", "size": MAX_MEDIA_SIZE})
    assert response.status_code == 200
    assert not metadata.exists() and not part.exists()
    assert (uploads.root / "notes.json").exists()
    assert uploads.load(response.json()["id"])["size"] == MAX_MEDIA_SIZE


@pytest.mark.codec
def test_a_slow_chunk_does_not_hold_up_other_uploads(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    slow, other = create(client, b"x" * 4), create(client, b"y" * 4)
    started, release = threading.Event(), threading.Event()
    append = Uploads.append

    def stalled(self: Uploads, upload_id: str, chunk: bytes, offset: int | None = None) -> None:
        if upload_id == slow:
            started.set()
            assert release.wait(5)
        append(self, upload_id, chunk, offset)

    monkeypatch.setattr(Uploads, "append", stalled)
    result: list[int] = []
    sending = threading.Thread(
        target=lambda: result.append(
            client.put(f"/api/uploads/{slow}?offset=0", headers=HEADERS, content=b"xxxx").status_code
        )
    )
    sending.start()
    try:
        assert started.wait(5)
        assert client.put(f"/api/uploads/{other}?offset=0", headers=HEADERS, content=b"yyyy").json()["offset"] == 4
        assert client.post(f"/api/uploads/{other}/finish", headers=HEADERS).status_code == 200
    finally:
        release.set()
        sending.join(5)
    assert result == [200]
    assert client.get(f"/api/uploads/{slow}", headers=HEADERS).json()["offset"] == 4


@pytest.mark.codec
def test_dedupe_retry_transcript_and_delete(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = finish(client, wav_bytes())
    wait_job(client, result["job_id"])
    duplicate = finish(client, wav_bytes(), "另一名字.wav")
    assert duplicate["source_id"] == result["source_id"] and not duplicate["new"]
    assert len(client.get("/api/persona/sources").json()["items"]) == 1

    class FakeTranscriber:
        diarizes = True

        def transcribe(self, audio: Path, duration: float, progress: Any) -> list[Segment]:
            assert audio.is_absolute() and duration == 1
            progress(0.5, duration)
            return [Segment(start=0, end=1, text="我喜欢核对测试结果。")]

    monkeypatch.setattr("twin.web.uploads.make_transcriber", lambda _: FakeTranscriber())
    retry = client.post(f"/api/persona/sources/{result['source_id']}/transcribe", headers=HEADERS).json()
    job = wait_job(client, retry["job_id"])
    assert job["status"] == "done"
    assert [s for s in job["progress"] if "提取音频" in s]
    assert [s for s in job["progress"] if "整理记忆" in s]
    text = client.get(f"/api/persona/sources/{result['source_id']}/text").text
    assert "本人：[00:00] 我喜欢核对" in text
    assert "未区分说话人" not in text
    with PersonaStore(tmp_path / "twin.db") as store:
        assert all(e.source_id == result["source_id"] for e in store.list_expressions())
        source = store.get_source(result["source_id"])
        assert source and source.media_status == "ready" and source.kind == "audio"
        assert store.delete_source(result["source_id"])
    assert not (tmp_path / "media-sources" / result["media_sha"]).exists()


def test_command_contract_and_sanitized_failure(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav_bytes())
    command = (
        'python3 -c \'import json,sys; r=json.load(sys.stdin); assert r["language"]=="zh"; '
        'print("log"); print(json.dumps({"ok":True,"segments":[{"start":0,"end":1,"text":r["audio"]}]}))\''
    )
    progress: list[float] = []
    segments = CommandTranscriber(command).transcribe(audio, 1, lambda done, _: progress.append(done))
    assert segments[0].text == str(audio.resolve()) and progress == [0, 1]
    for command in [
        'echo \'{"ok":false,"error":"secret-token"}\'',
        "echo bad-json",
        "exit 1",
        'echo \'{"ok":true,"segments":[{"start":2,"end":1,"text":"x"}]}\'',
    ]:
        with pytest.raises(RuntimeError, match="语音识别失败") as error:
            CommandTranscriber(command).transcribe(audio, 1, lambda *_: None)
        assert "secret-token" not in str(error.value)


def test_command_progress_from_stderr(tmp_path: Path) -> None:
    audio = tmp_path / "audio.wav"
    audio.write_bytes(wav_bytes())
    script = tmp_path / "slow.py"
    script.write_text(
        "import json, sys, time\n"
        "json.load(sys.stdin)\n"
        "for value in (0.25, 0.5):\n"
        "    print('noise', file=sys.stderr)\n"
        "    print(f'@@twin-progress {value}', file=sys.stderr, flush=True)\n"
        "    time.sleep(0.8)\n"
        "print(json.dumps({'ok': True, 'segments': [{'start': 0, 'end': 1, 'text': 'x'}]}))\n"
    )
    progress: list[float] = []
    CommandTranscriber(f"python3 {script}").transcribe(audio, 100, lambda done, _: progress.append(done))
    assert progress[0] == 0 and progress[-1] == 100
    assert 25 in progress and 50 in progress and progress == sorted(progress)


@pytest.mark.codec
def test_http_silence_chunks_and_offsets(tmp_path: Path) -> None:
    audio = tmp_path / "tone.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        frames = b"".join(
            struct.pack("<h", int(10000 * math.sin(i * 2 * math.pi * 440 / 16000)))
            if i < 20 * 16000 or i >= 22 * 16000
            else b"\0\0"
            for i in range(30 * 16000)
        )
        wav.writeframes(frames)
    chunks = silence_chunks(audio, 30)
    assert len(chunks) == 2 and 21.9 < chunks[0][1] < 22.1
    assert all(end - start <= 25 for start, end in chunks)

    class Recognizer:
        name, identity, capabilities = "fake", "fake", ASRCapabilities()

        def transcribe(self, request: TranscriptionRequest) -> Transcription:
            with wave.open(io.BytesIO(request.audio), "rb") as wav:
                assert wav.getnframes() / wav.getframerate() <= 25
            return Transcription(text="合成文字")

    segments = HTTPTranscriber(Recognizer()).transcribe(audio, 30, lambda *_: None)
    assert [(s.start, s.end) for s in segments] == chunks
    assert silence_chunks(audio, 60)[-1][1] == 60  # hard cut when no later silence


@pytest.mark.codec
def test_http_ingestion_requires_confirmation(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    class Recognizer:
        name, identity, capabilities = "fake", "fake", ASRCapabilities()

        def transcribe(self, request: TranscriptionRequest) -> Transcription:
            return Transcription(text="会议里不同人的话")

    transcriber = HTTPTranscriber(Recognizer())
    assert not transcriber.diarizes
    monkeypatch.setattr("twin.web.uploads.make_transcriber", lambda _: transcriber)
    result = finish(client, wav_bytes())
    assert wait_job(client, result["job_id"])["status"] == "done"
    row = client.get("/api/persona/sources").json()["items"][0]
    assert row["status"] == "needs_speaker" and row["n_target"] == 0
    base = f"/api/persona/sources/{result['source_id']}"
    claim = client.get(base + "/speakers").json()
    assert not claim["diarized"] and not claim["confirmed"] and claim["claimed"] == []
    assert claim["speakers"][0]["id"] == "S1" and not claim["speakers"][0]["suggested"]
    assert client.get(base + "/text").text == ""
    chosen = client.put(base + "/speaker", json={"speakers": ["S1"]}, headers=HEADERS).json()
    assert wait_job(client, chosen["job_id"])["status"] == "done"
    assert "本人：[00:00] 会议里不同人的话" in client.get(base + "/text").text


def test_transcript_paragraphs_and_timestamps() -> None:
    text = transcript_text(
        "电影.mov",
        3661,
        "2025-01-02",
        [
            Segment(start=2, end=5, text="甲" * 120),
            Segment(start=10, end=20, text="乙" * 120),
            Segment(start=3600, end=3610, text="丙" * 220),
        ],
    )
    assert "来源文件名：电影.mov" in text and "时长：1:01:01" in text
    paragraphs = text.split("\n\n")[1:]
    assert paragraphs[0].startswith("[00:02]")
    assert any("[1:00:00]" in p for p in paragraphs)
    assert all(len(p.split("] ", 1)[1]) <= 200 for p in paragraphs)
    assert timestamp(65) == "01:05"
    with pytest.raises(ValueError, match="没有识别"):
        transcript_text("空.wav", 1, None, [])


@pytest.mark.codec
def test_single_media_worker_and_job_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = JobManager(4, describe_error)
    settings = Settings(db_path=tmp_path / "twin.db", asr=ASRSettings(provider="command", command="unused"))
    ingestion = MediaIngestion(settings, jobs, lambda: None, lambda: FakeLLM(lambda *_: {}))
    uploads = Uploads(tmp_path)
    started, release = threading.Event(), threading.Event()
    concurrent: list[int] = []

    class Fake:
        diarizes = True

        def transcribe(self, audio: Path, duration: float, progress: Any) -> list[Segment]:
            concurrent.append(1)
            assert len(concurrent) == 1
            started.set()
            assert release.wait(5)
            concurrent.pop()
            raise RuntimeError("private-backend-error")

    monkeypatch.setattr("twin.web.uploads.make_transcriber", lambda _: Fake())
    results = []
    for size in (1, 2):
        data = wav_bytes(size)
        info = uploads.create(UploadBody(filename="a.wav", size=len(data)))
        uploads.append(info["id"], data)
        results.append(ingestion.finish(uploads, info["id"]))
    assert started.wait(5)
    assert jobs.snapshot(results[1]["job_id"])["status"] == "queued"  # type: ignore[index]
    release.set()
    for result in results:
        assert jobs.wait(result["job_id"], 5)
        snapshot = jobs.snapshot(result["job_id"])
        assert snapshot and snapshot["status"] == "failed" and "private-backend-error" not in json.dumps(snapshot)


def test_no_asr_still_saved_without_ffmpeg(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(original: Path) -> Any:
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr("twin.web.uploads.extract_audio", missing)
    result = finish(client, wav_bytes())
    assert wait_job(client, result["job_id"])["status"] == "done"
    assert client.get("/api/persona/sources").json()["items"][0]["status"] == "needs_asr"


@pytest.mark.codec
def test_deleted_job_cannot_overwrite_reuploaded_source(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    started, release = threading.Event(), threading.Event()
    calls = 0

    class Fake:
        diarizes = True

        def transcribe(self, audio: Path, duration: float, progress: Any) -> list[Segment]:
            nonlocal calls
            calls += 1
            text = "旧转写" if calls == 1 else "新转写"
            started.set()
            assert release.wait(5)
            return [Segment(start=0, end=1, text=text)]

    monkeypatch.setattr("twin.web.uploads.make_transcriber", lambda _: Fake())
    old = finish(client, wav_bytes())
    assert started.wait(5)
    try:
        assert client.delete(f"/api/persona/sources/{old['source_id']}", headers=HEADERS).status_code == 200
        new = finish(client, wav_bytes())
        assert new["new"] and new["job_id"] != old["job_id"]
    finally:
        release.set()
    assert wait_job(client, old["job_id"])["result"] == {"deleted": True}
    assert wait_job(client, new["job_id"])["status"] == "done"
    text = client.get(f"/api/persona/sources/{new['source_id']}/text").text
    assert "新转写" in text and "旧转写" not in text


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.codec
def test_transcript_is_proofread_before_speakers_are_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, enabled: bool
) -> None:
    from twin.media.clean import Edits

    proofread: list[str] = []

    def handler(system: str, user: str, schema: type) -> dict[str, Any]:
        if schema is not Edits:
            return {"items": []}
        proofread.append(user)
        return {"edits": [{"id": 0, "text": "我们用限界上下文划分模块。"}]}

    class FakeTranscriber:
        diarizes = True

        def transcribe(self, audio: Path, duration: float, progress: Any) -> list[Segment]:
            return [Segment(start=0, end=1, text="我们用涨号上下文划分模块。")]

    settings = Settings(db_path=tmp_path / "twin.db", max_workers=1, asr=ASRSettings(clean=enabled))
    app = create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder)
    monkeypatch.setattr("twin.web.uploads.make_transcriber", lambda _: FakeTranscriber())
    with TestClient(app, base_url="http://localhost") as client:
        result = finish(client, wav_bytes())
        job = wait_job(client, result["job_id"])
        assert job["status"] == "done"
        text = client.get(f"/api/persona/sources/{result['source_id']}/text").text
    assert len(proofread) == int(enabled)
    assert bool([s for s in job["progress"] if "校对完成：修正 1 段" in s]) is enabled
    assert ("限界上下文" if enabled else "涨号上下文") in text


def test_digest_follows_the_bytes_as_they_arrive(client: TestClient, tmp_path: Path) -> None:
    import hashlib

    from twin.web import uploads as uploads_module

    data = os.urandom(3 * 1024**2 + 17)
    sha = hashlib.sha256(data).hexdigest()
    # Several request chunks in order: the running hash is used, and it matches a fresh read of the file.
    uid = create(client, data)
    cut = 1024**2 + 5
    assert client.put(f"/api/uploads/{uid}?offset=0", headers=HEADERS, content=data[:cut]).status_code == 200
    assert client.put(f"/api/uploads/{uid}?offset={cut}", headers=HEADERS, content=data[cut:]).status_code == 200
    part = tmp_path / "uploads" / f"{uid}.part"
    assert uploads_module._running[str(part)][1] == len(data)
    assert Uploads(tmp_path).digest(uid) == sha
    assert str(part) not in uploads_module._running
    # A restart between chunks loses the running hash; the file is then read once and still agrees.
    uid = create(client, data)
    assert client.put(f"/api/uploads/{uid}?offset=0", headers=HEADERS, content=data[:cut]).status_code == 200
    uploads_module._running.clear()
    assert client.put(f"/api/uploads/{uid}?offset={cut}", headers=HEADERS, content=data[cut:]).status_code == 200
    assert Uploads(tmp_path).digest(uid) == sha
    # A rolled-back chunk drops the hash, so a retry cannot mix the two attempts.
    uid = create(client, data)
    uploads = Uploads(tmp_path)
    uploads.append(uid, data[:10], 0)
    uploads.truncate(uid, 0)
    uploads.append(uid, data[:10], 0)
    uploads.append(uid, data[10:], 10)
    assert uploads.digest(uid) == sha


def test_running_hashes_of_vanished_uploads_are_dropped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from twin.web import uploads as uploads_module

    monkeypatch.setattr(uploads_module, "MAX_RUNNING", 2)
    monkeypatch.setattr(uploads_module, "_running", {})
    uploads = Uploads(tmp_path)
    ids = [uploads.create(UploadBody(filename="a.mp4", size=10))["id"] for _ in range(3)]
    for upload_id in ids[:2]:
        uploads.append(upload_id, b"ab", 0)
    for upload_id in ids[:2]:
        uploads.paths(upload_id)[1].unlink()
    uploads.append(ids[2], b"ab", 0)
    assert list(uploads_module._running) == [str(uploads.paths(ids[2])[1])]


def test_sweep_removes_abandoned_uploads_and_orphan_parts(tmp_path: Path) -> None:
    uploads = Uploads(tmp_path)
    old = uploads.create(UploadBody(filename="a.mp4", size=5))["id"]
    fresh = uploads.create(UploadBody(filename="b.mp4", size=5))["id"]
    orphan = uploads.root / ("f" * 32 + ".part")
    orphan.write_bytes(b"x")
    longago = time.time() - 86401
    for path in (*uploads.paths(old), orphan):
        os.utime(path, (longago, longago))
    assert uploads.sweep() == 2
    assert not uploads.paths(old)[0].exists() and not orphan.exists()
    assert uploads.paths(fresh)[0].exists() and uploads.paths(fresh)[1].exists()
    assert Uploads(tmp_path / "none").sweep() == 0


@pytest.mark.codec
def test_audio_decodes_again_from_the_original(tmp_path: Path) -> None:
    from twin.media.ingest import readable_wav

    with pytest.raises(FileNotFoundError), readable_wav(tmp_path):
        pass
    data = wav_bytes(2)
    (tmp_path / "original.wav").write_bytes(data)
    with readable_wav(tmp_path) as wav, wave.open(str(wav)) as decoded:
        assert wav.name.startswith(".audio-") and wav.stat().st_mode & 0o777 == 0o600
        assert (decoded.getnframes(), decoded.getframerate(), decoded.getnchannels()) == (32000, 16000, 1)
        assert decoded.readframes(32000) == data[44:]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["original.wav"]
    # While transcription has it extracted, that file is used as it is.
    (tmp_path / "audio.wav").write_bytes(data)
    with readable_wav(tmp_path) as wav:
        assert wav == tmp_path / "audio.wav"


def test_failed_originals_expire_but_recent_and_ready_ones_stay(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    from twin.config import LibrarySettings
    from twin.media.library import Library

    # Nothing is deleted unless an administrator asks for it: a failure may be the transcription service being down.
    assert LibrarySettings().failed_keep_days == 0

    library = Library(tmp_path)
    ids = []
    for index in range(3):
        upload = tmp_path / f"u{index}.part"
        upload.write_bytes(wav_bytes(index + 1))
        recording, _ = library.add(upload, f"{index}.wav")
        ids.append(recording.id)
    old, recent, ready = ids
    long_ago = "2020-01-01T00:00:00+00:00"
    library.update(old, status="failed", error="x")
    with library._db() as db:
        db.execute("UPDATE recordings SET updated_at = ? WHERE id = ?", (long_ago, old))
        db.execute("UPDATE recordings SET updated_at = ?, status = 'ready' WHERE id = ?", (long_ago, ready))
    library.update(recent, status="failed", error="y")
    assert library.expire_failed(0) == 0
    with caplog.at_level("WARNING", logger="twin.media.library"):
        assert library.expire_failed(30) == 1
    assert [r.getMessage() for r in caplog.records if old in r.getMessage() and "0.wav" in r.getMessage()]
    assert library.original(old) is None and library.original(recent) and library.original(ready)
    assert "30 天" in (library.get(old) or library.list()[0]).error
    assert library.retry(old) is None and library.retry(recent) is not None
    assert library.expire_failed(30) == 0


def test_start_up_drops_kept_audio_and_abandoned_uploads(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    folder = tmp_path / "media-sources" / ("a" * 64)
    folder.mkdir(parents=True)
    legacy_sample = "b" * 32 + "-sample-0-1.wav"
    for name in ("original.wav", "audio.wav", "audio.flac", ".audio-1.wav", "analysis.json", legacy_sample):
        (folder / name).write_bytes(b"x")
    uploads = Uploads(tmp_path)
    abandoned = uploads.create(UploadBody(filename="a.mp4", size=5))["id"]
    os.utime(uploads.paths(abandoned)[0], (time.time() - 86401,) * 2)
    MediaIngestion(settings, None, lambda: None, lambda: None).sweep()  # type: ignore[arg-type]
    assert sorted(p.name for p in folder.iterdir()) == ["analysis.json", "original.wav"]
    assert not uploads.paths(abandoned)[0].exists()
