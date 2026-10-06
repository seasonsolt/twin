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
    row = client.get("/api/persona/sources").json()[0]
    assert row["status"] == "needs_asr" and row["duration_s"] == 1
    folder = tmp_path / "media-sources" / row["media_sha"]
    assert (folder / "original.wav").read_bytes() == data
    assert folder.stat().st_mode & 0o777 == 0o700
    assert (folder / "original.wav").stat().st_mode & 0o777 == 0o600
    assert (folder / "audio.wav").stat().st_mode & 0o777 == 0o600
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


def test_cleanup_and_disk_resume(tmp_path: Path) -> None:
    uploads = Uploads(tmp_path)
    old = uploads.create(UploadBody(filename="a.mp4", size=5))
    uploads.append(old["id"], b"12")
    assert Uploads(tmp_path).load(old["id"])["offset"] == 2
    metadata, part = uploads.paths(old["id"])
    os.utime(metadata, (time.time() - 86401, time.time() - 86401))
    fresh = uploads.create(UploadBody(filename="fresh.mov", size=MAX_MEDIA_SIZE))
    assert not metadata.exists() and not part.exists()
    assert uploads.load(fresh["id"])["size"] == MAX_MEDIA_SIZE


def test_dedupe_retry_transcript_and_delete(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = finish(client, wav_bytes())
    wait_job(client, result["job_id"])
    duplicate = finish(client, wav_bytes(), "另一名字.wav")
    assert duplicate["source_id"] == result["source_id"] and not duplicate["new"]
    assert len(client.get("/api/persona/sources").json()) == 1

    class FakeTranscriber:
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


def test_single_media_worker_and_job_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    jobs = JobManager(4, describe_error)
    settings = Settings(db_path=tmp_path / "twin.db", asr=ASRSettings(provider="command", command="unused"))
    ingestion = MediaIngestion(settings, jobs, lambda: None)
    uploads = Uploads(tmp_path)
    started, release = threading.Event(), threading.Event()
    concurrent: list[int] = []

    class Fake:
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
    assert client.get("/api/persona/sources").json()[0]["status"] == "needs_asr"


def test_deleted_job_cannot_overwrite_reuploaded_source(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    started, release = threading.Event(), threading.Event()
    calls = 0

    class Fake:
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
