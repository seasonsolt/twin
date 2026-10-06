"""Resumable uploads and media jobs feeding the existing persona source pipeline."""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import json
import os
import re
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..assets import AssetStore
from ..config import Settings
from ..media.claim import Analysis, analyse, vision_candidates, voice_candidates
from ..media.ingest import MEDIA_EXTENSIONS, VIDEO_EXTENSIONS, CommandTranscriber, extract_audio, make_transcriber
from ..persona.schema import ParsedSource, Source, SourceKind
from ..persona.sources import parse_media
from ..persona.store import PersonaStore, stored_identity
from ..util import private_directory
from .jobs import Job, JobError, JobManager, Log

CHUNK_SIZE = 8 * 1024 * 1024
MAX_CHUNK_SIZE = 16 * 1024 * 1024
MAX_MEDIA_SIZE = 4 * 1024**3


class UploadBody(BaseModel):
    filename: str = Field(min_length=1, max_length=255)
    size: int
    type: str = Field(default="", max_length=200)


class Uploads:
    def __init__(self, data: Path) -> None:
        self.root = data / "uploads"

    def paths(self, upload_id: str) -> tuple[Path, Path]:
        if not re.fullmatch(r"[0-9a-f]{32}", upload_id):
            raise HTTPException(404, "找不到上传记录，请重新选择文件")
        return self.root / f"{upload_id}.json", self.root / f"{upload_id}.part"

    def load(self, upload_id: str) -> dict[str, Any]:
        metadata, part = self.paths(upload_id)
        if not metadata.is_file():
            raise HTTPException(404, "找不到上传记录，请重新选择文件")
        info: dict[str, Any] = json.loads(metadata.read_text())
        info["offset"] = info["size"] if info.get("source_id") else part.stat().st_size
        return info

    def save(self, upload_id: str, info: dict[str, Any]) -> None:
        metadata, _ = self.paths(upload_id)
        metadata.write_text(json.dumps(info, ensure_ascii=False))
        metadata.chmod(0o600)

    def create(self, body: UploadBody) -> dict[str, Any]:
        name = Path(body.filename.replace("\\", "/")).name
        if Path(name).suffix.lower().lstrip(".") not in MEDIA_EXTENSIONS:
            raise HTTPException(400, "不支持此音视频格式")
        if body.size > MAX_MEDIA_SIZE:
            raise HTTPException(413, "音视频文件最多 4 GB")
        if body.size <= 0:
            raise HTTPException(400, "文件不能为空")
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        self.root.chmod(0o700)
        for metadata in self.root.glob("*.json"):
            if metadata.stat().st_mtime < time.time() - 86400:
                self.cancel(metadata.stem)
        upload_id = uuid.uuid4().hex
        metadata, part = self.paths(upload_id)
        metadata.touch(mode=0o600)
        part.touch(mode=0o600)
        self.save(upload_id, {"filename": name, "size": body.size, "type": body.type})
        return {"id": upload_id, "offset": 0, "chunk_size": CHUNK_SIZE}

    def cancel(self, upload_id: str) -> None:
        metadata, part = self.paths(upload_id)
        metadata.unlink(missing_ok=True)
        part.unlink(missing_ok=True)

    def append(self, upload_id: str, chunk: bytes) -> None:
        metadata, part = self.paths(upload_id)
        with part.open("ab") as file:
            file.write(chunk)
        os.utime(metadata, None)

    def truncate(self, upload_id: str, offset: int) -> None:
        _, part = self.paths(upload_id)
        with part.open("r+b") as file:
            file.truncate(offset)


class MediaIngestion:
    def __init__(self, settings: Settings, jobs: JobManager, queue_build: Callable[[], None]) -> None:
        self.settings, self.jobs, self.queue_build = settings, jobs, queue_build
        self.lock = threading.RLock()
        self.active: dict[str, Job] = {}

    def queue(self, source_id: str) -> Job:
        with self.lock, PersonaStore(self.settings.db_path) as store:
            source = store.get_source(source_id)
            if source is None or not source.media_sha:
                raise HTTPException(404, "找不到这条音视频记忆")
            self.active = {sid: job for sid, job in self.active.items() if job.active}
            existing = self.active.get(source_id)
            if existing and existing.job_id == source.media_job_id:
                return existing
            job_id = ""

            def prepare(job: Job) -> None:
                nonlocal job_id
                job_id = job.job_id
                source.media_status, source.media_job_id = "queued", job.job_id
                source.transcribed_s = 0
                store.update_source(source)
                self.active[source_id] = job

            try:
                return self.jobs.submit(
                    "media_ingest", source.title, lambda log: self.run(source_id, job_id, log), prepare=prepare
                )
            except Exception:
                source.media_status = "failed"
                store.update_source(source)
                raise

    def update(self, source_id: str, job_id: str, **fields: Any) -> Source | None:
        with self.lock, PersonaStore(self.settings.db_path) as store:
            source = store.get_source(source_id)
            if source is None or source.media_job_id != job_id:
                return None
            source = source.model_copy(update=fields)
            store.update_source(source)
            return source

    def run(self, source_id: str, job_id: str, log: Log) -> dict[str, Any]:
        try:
            source = self.update(source_id, job_id, media_status="extracting")
            if not source or not source.media_sha:
                return {"deleted": True}
            log("[1/6] 提取音频")
            folder = self.settings.db_path.parent / "media-sources" / source.media_sha
            original = next(folder.glob("original.*"))
            transcriber = make_transcriber(self.settings.asr)
            try:
                audio, duration, creation = extract_audio(original)
            except Exception:
                if transcriber is not None:
                    raise
                self.update(source_id, job_id, media_status="needs_asr")
                log("需要配置语音识别")
                return {"source_id": source_id, "status": "needs_asr"}
            source = self.update(source_id, job_id, duration_s=duration, creation_time=creation)
            if source is None:
                return {"deleted": True}
            if transcriber is None:
                self.update(source_id, job_id, media_status="needs_asr")
                log("需要配置语音识别")
                return {"source_id": source_id, "status": "needs_asr"}

            def progress(done: float, total: float) -> None:
                self.update(source_id, job_id, media_status="transcribing", transcribed_s=done)
                log(f"[2/6] 转写（已完成 {done / 60:.1f} / {total / 60:.1f} 分钟）")

            reference = AssetStore(self.settings.db_path).path("voice")
            if isinstance(transcriber, CommandTranscriber):
                transcriber.diarize, transcriber.reference = True, reference
            segments = transcriber.transcribe(audio, duration, progress)
            log("[3/6] 区分说话人")
            analysis = analyse(segments, getattr(transcriber, "speakers", []), reference is not None)
            with self.lock, PersonaStore(self.settings.db_path) as store:
                current = store.get_source(source_id)
                if current is None or current.media_job_id != job_id:
                    return {"deleted": True}
                analysis.save(folder)
                self.store_analysis(store, current, analysis)
            if not analysis.confirmed:
                log("请确认哪位是你")
                return {"source_id": source_id, "status": "needs_speaker"}
            log("[4/6] 整理记忆")
            self.queue_build()
            self.candidates(source_id, analysis.revision, log)
            return {"source_id": source_id}
        except Exception:
            self.update(source_id, job_id, media_status="failed")
            raise JobError("音视频转写失败，请检查 ffmpeg 和语音识别配置后重试") from None

    def store_analysis(self, store: PersonaStore, source: Source, analysis: Analysis) -> None:
        source = source.model_copy(
            update={
                "media_status": "ready" if analysis.confirmed else "needs_speaker",
                "transcribed_s": source.duration_s or 0,
                "voice_candidates": len(analysis.voices),
                "portrait_candidates": len(analysis.portraits),
                "candidates_pending": analysis.confirmed and analysis.speaker is not None,
            }
        )
        name = stored_identity(self.settings.db_path)[0] or self.settings.target_name
        parsed = parse_media(source, analysis.lines(name) if analysis.confirmed else [])
        store.put_source(parsed)
        store.set_meta(f"source_error:{source.source_id}", "")

    def candidates(self, source_id: str, revision: str, log: Log) -> dict[str, Any]:
        with self.lock, PersonaStore(self.settings.db_path) as store:
            source = store.get_source(source_id)
            if source is None or not source.media_sha:
                return {"deleted": True}
            folder = self.settings.db_path.parent / "media-sources" / source.media_sha
            analysis = Analysis.load(folder)
            if analysis.revision != revision:
                return {"superseded": True}
        if analysis.speaker is not None:
            log("[5/6] 提取声音候选")
        try:
            analysis.voices = voice_candidates(analysis, folder)
        except Exception:
            analysis.candidate_error = "声音候选提取失败，可重新确认说话人后重试"
        if source.kind == SourceKind.VIDEO and analysis.speaker and self.settings.vision.command:
            log("[6/6] 提取形象候选")
            try:
                analysis.portraits = vision_candidates(
                    analysis, next(folder.glob("original.*")), folder, self.settings.vision
                )
            except Exception:
                analysis.candidate_error = "形象候选提取失败，请检查形象提取配置后重试"
        with self.lock, PersonaStore(self.settings.db_path) as store:
            source = store.get_source(source_id)
            if source is None or Analysis.load(folder).revision != revision:
                return {"superseded": True}
            analysis.save(folder)
            source.voice_candidates, source.portrait_candidates = len(analysis.voices), len(analysis.portraits)
            source.candidates_pending = False
            store.update_source(source)
        return {"source_id": source_id}

    def finish(self, uploads: Uploads, upload_id: str) -> dict[str, Any]:
        info = uploads.load(upload_id)
        if info["offset"] != info["size"]:
            raise HTTPException(400, "文件尚未上传完成")
        if info.get("source_id"):
            with PersonaStore(self.settings.db_path) as store:
                source = store.get_source(info["source_id"])
                if source:
                    job = self.queue(source.source_id) if not source.media_job_id else None
                    return {
                        **source.model_dump(mode="json"),
                        "new": False,
                        "job_id": job.job_id if job else source.media_job_id,
                    }
            raise HTTPException(404, "这条记忆已删除，请重新上传")
        _, part = uploads.paths(upload_id)
        with part.open("rb") as file:
            sha = hashlib.file_digest(file, "sha256").hexdigest()
        source_id = "src_media_" + sha
        with self.lock, PersonaStore(self.settings.db_path) as store:
            source = store.get_source(source_id)
            new = source is None
            if source is None:
                extension = Path(info["filename"]).suffix.lower().lstrip(".")
                folder = self.settings.db_path.parent / "media-sources" / sha
                private_directory(folder)
                folder.chmod(0o700)
                original = folder / f"original.{extension}"
                part.replace(original)
                original.chmod(0o600)
                source = Source(
                    source_id=source_id,
                    kind=SourceKind.VIDEO if extension in VIDEO_EXTENSIONS else SourceKind.AUDIO,
                    title=Path(info["filename"]).stem,
                    origin=info["filename"],
                    imported_at=dt.datetime.now(dt.UTC).isoformat(),
                    n_expressions=0,
                    n_target=0,
                    text_state="raw",
                    media_sha=sha,
                    media_status="queued",
                )
                store.put_source(ParsedSource(source, []))
            else:
                part.unlink(missing_ok=True)
            info["source_id"] = source_id
            uploads.save(upload_id, info)
            job = self.queue(source_id) if new else None
            return {**source.model_dump(mode="json"), "new": new, "job_id": job.job_id if job else source.media_job_id}


def register(app: FastAPI, settings: Settings, jobs: JobManager, queue_build: Callable[[], None]) -> MediaIngestion:
    uploads = Uploads(settings.db_path.parent)
    ingestion = MediaIngestion(settings, jobs, queue_build)
    # Serialize append/finish/cancel across requests, including stream rollback on disconnect.
    lock = asyncio.Lock()

    @app.post("/api/uploads")
    async def create(body: UploadBody) -> dict[str, Any]:
        async with lock:
            return await run_in_threadpool(uploads.create, body)

    @app.get("/api/uploads/{upload_id}")
    async def get(upload_id: str) -> dict[str, int]:
        async with lock:
            info = await run_in_threadpool(uploads.load, upload_id)
            return {"offset": info["offset"], "size": info["size"]}

    @app.delete("/api/uploads/{upload_id}")
    async def cancel(upload_id: str) -> dict[str, bool]:
        async with lock:
            await run_in_threadpool(uploads.cancel, upload_id)
            return {"deleted": True}

    @app.put("/api/uploads/{upload_id}")
    async def append(upload_id: str, request: Request, offset: int) -> Any:
        async with lock:
            info = await run_in_threadpool(uploads.load, upload_id)
            if offset != info["offset"] or info.get("source_id"):
                return JSONResponse({"offset": info["offset"]}, status_code=409)
            declared = request.headers.get("content-length", "")
            if declared.isdigit() and int(declared) > min(MAX_CHUNK_SIZE, info["size"] - offset):
                raise HTTPException(413, "分片最多 16 MB，且不能超过文件大小")
            received = 0
            try:
                async for chunk in request.stream():
                    received += len(chunk)
                    if received > MAX_CHUNK_SIZE or offset + received > info["size"]:
                        raise HTTPException(413, "分片最多 16 MB，且不能超过文件大小")
                    await run_in_threadpool(uploads.append, upload_id, chunk)
            except BaseException:
                await run_in_threadpool(uploads.truncate, upload_id, offset)
                raise
            return {"offset": offset + received}

    @app.post("/api/uploads/{upload_id}/finish")
    async def finish(upload_id: str) -> dict[str, Any]:
        async with lock:
            return await run_in_threadpool(ingestion.finish, uploads, upload_id)

    @app.post("/api/persona/sources/{source_id}/transcribe", status_code=202)
    def retry(source_id: str) -> dict[str, str]:
        job = ingestion.queue(source_id)
        return {"source_id": source_id, "job_id": job.job_id}

    return ingestion
