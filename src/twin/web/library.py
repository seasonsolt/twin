"""``/api/library``: the signed-in account's recording library, outside any one twin.

Only the account that uploaded a recording can see it. Recordings are transcribed one after another in the shared
media slot (so a library batch and a twin's own recordings take turns on the transcription service); the queue
lives in ``library.db``, so a restart picks up where it stopped.
"""

from __future__ import annotations

import contextlib
import shutil
import threading
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..media.ingest import CommandTranscriber, make_transcriber
from ..media.library import Library, Recording, TranscriptionError, owner_key
from .jobs import Job, JobError, JobManager, Log, TooManyJobs
from .uploads import UploadBody, Uploads, upload_routes

GIB = 1024**3


class Libraries:
    def __init__(self, settings: Settings, jobs: JobManager) -> None:
        self.settings, self.jobs = settings, jobs
        self.root = settings.db_path.parent / "library"
        self.lock = threading.RLock()
        self.opened: dict[str, Library] = {}
        # The transcription job of each owner; the next recording is queued when it ends.
        self.running: dict[str, Job] = {}

    def owner(self, request: Request) -> str:
        return owner_key(request.scope["twin_identity"]["email"])

    def library(self, owner: str) -> Library:
        with self.lock:
            if owner not in self.opened:
                self.opened[owner] = Library(self.root / owner)
            return self.opened[owner]

    def uploads(self, owner: str) -> Uploads:
        return Uploads(self.library(owner).root)

    def resume(self) -> None:
        """At start-up: recordings cut off by the last shutdown are queued again, and every queue starts."""
        if not self.root.is_dir():
            return
        for folder in sorted(self.root.iterdir()):
            if (folder / "library.db").is_file() and self.library(folder.name).resume():
                self.kick(folder.name)

    def kick(self, owner: str) -> None:
        """Start transcribing the owner's next queued recording unless one is already running. Without a diarizing
        transcription service, or with the job queue full, recordings stay queued; the next status poll tries
        again."""
        with self.lock:
            job = self.running.get(owner)
            if job is not None and job.active:
                return
            recording = self.library(owner).next_queued()
            if recording is None or not isinstance(make_transcriber(self.settings.asr), CommandTranscriber):
                return
            with contextlib.suppress(TooManyJobs):
                self.running[owner] = self.jobs.scoped(f"library:{owner}").submit(
                    "media_ingest", recording.filename, lambda log: self.run(owner, recording.id, log)
                )

    def run(self, owner: str, recording_id: str, log: Log) -> dict[str, Any]:
        library = self.library(owner)
        transcriber = make_transcriber(self.settings.asr)

        def progress(done: float, total: float) -> None:
            library.update(recording_id, transcribed_s=done)
            log(f"[1/2] 转写（已完成 {done / 60:.1f} / {total / 60:.1f} 分钟）")

        try:
            if not isinstance(transcriber, CommandTranscriber):
                raise TranscriptionError("录音库需要能区分说话人的转写服务（asr-funasr）")
            log("[1/2] 提取音频")
            recording = library.transcribe(recording_id, transcriber, progress)
            log(f"[2/2] 完成：{recording.segments} 段，{recording.speakers} 位说话人")
            return {"recording_id": recording_id, "status": recording.status}
        except TranscriptionError as exc:
            raise JobError(str(exc)) from None
        finally:
            with self.lock:
                self.running.pop(owner, None)
            self.kick(owner)

    def capacity(self) -> dict[str, int]:
        self.root.mkdir(parents=True, mode=0o700, exist_ok=True)
        arriving = count = 0
        for folder in self.root.iterdir():
            if (folder / "library.db").is_file():
                n, remaining = Uploads(folder).arriving()
                count, arriving = count + n, arriving + remaining
        return {
            "free_bytes": shutil.disk_usage(self.root).free,
            "arriving_bytes": arriving,
            "arriving": count,
            "headroom_bytes": int(self.settings.library.headroom_gb * GIB),
        }

    def admit(self, owner: str, body: UploadBody) -> None:
        """Refuse an upload that would leave less than the headroom free once every upload still arriving is in,
        or that would queue more than ``max_pending`` recordings. Transcription works on one recording at a time,
        so its temporary audio fits in the headroom."""
        library = self.library(owner)
        waiting = library.pending() + self.uploads(owner).arriving()[0]
        limit = self.settings.library.max_pending
        if waiting >= limit:
            raise HTTPException(409, f"最多同时排队 {limit} 个文件，请等前面的转写完成后再添加")
        capacity = self.capacity()
        left = capacity["free_bytes"] - capacity["arriving_bytes"] - body.size
        if left < capacity["headroom_bytes"]:
            raise HTTPException(
                507,
                f"磁盘空间不足：添加后可用空间会低于 {self.settings.library.headroom_gb:g} GB 的安全余量，"
                "请联系管理员扩容",
            )

    def finish(self, owner: str, upload_id: str) -> dict[str, Any]:
        uploads = self.uploads(owner)
        info = uploads.load(upload_id)
        if info["offset"] != info["size"]:
            raise HTTPException(400, "文件尚未上传完成")
        library = self.library(owner)
        if info.get("recording_id"):
            existing = library.get(info["recording_id"])
            if existing is None:
                raise HTTPException(404, "这段录音已删除，请重新上传")
            return {**view(existing), "new": False}
        _, part = uploads.paths(upload_id)
        recording, new = library.add(part, info["filename"])
        info["recording_id"] = recording.id
        uploads.save(upload_id, info)
        self.kick(owner)
        return {**view(library.get(recording.id) or recording), "new": new}

    def status(self, owner: str) -> dict[str, Any]:
        self.kick(owner)
        library = self.library(owner)
        recordings = library.list()
        return {
            "recordings": [view(r) for r in recordings],
            "pending": sum(r.status in {"queued", "transcribing"} for r in recordings),
            "max_pending": self.settings.library.max_pending,
            "asr": isinstance(make_transcriber(self.settings.asr), CommandTranscriber),
            "capacity": self.capacity(),
        }


def view(recording: Recording) -> dict[str, Any]:
    return recording.model_dump(mode="json", exclude={"sha256"})


def register(app: FastAPI, settings: Settings, jobs: JobManager) -> Libraries:
    libraries = Libraries(settings, jobs)

    @app.get("/api/library")
    def get_library(request: Request) -> dict[str, Any]:
        return libraries.status(libraries.owner(request))

    upload_routes(
        app,
        "/api/library/uploads",
        lambda request: libraries.uploads(libraries.owner(request)),
        lambda request, upload_id: libraries.finish(libraries.owner(request), upload_id),
        admit=lambda request, uploads, body: libraries.admit(libraries.owner(request), body),
    )

    @app.post("/api/library/recordings/{recording_id}/retry", status_code=202)
    def retry(recording_id: str, request: Request) -> dict[str, Any]:
        owner = libraries.owner(request)
        recording = libraries.library(owner).retry(recording_id)
        if recording is None:
            raise HTTPException(409, "只有转写失败、原始文件还在的录音可以重试")
        libraries.kick(owner)
        return view(recording)

    @app.delete("/api/library/recordings/{recording_id}")
    async def delete(recording_id: str, request: Request) -> dict[str, bool]:
        owner = libraries.owner(request)
        if not await run_in_threadpool(libraries.library(owner).delete, recording_id):
            raise HTTPException(409, "这段录音正在转写，请稍后再删除")
        return {"deleted": True}

    return libraries
