"""Per-persona speaker confirmation and candidate adoption endpoints."""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..assets import AssetStore
from ..config import Settings
from ..media.claim import Analysis, Candidate, cut, face_crop, sample_windows
from ..persona.store import PersonaStore
from .assets import portrait, voice
from .jobs import Job

if TYPE_CHECKING:
    from .uploads import MediaIngestion


class SpeakerBody(BaseModel):
    speaker: str | None = Field(max_length=80)


class AdoptBody(BaseModel):
    candidate: str = Field(min_length=1, max_length=120)


def register(app: FastAPI, settings: Settings, ingestion: MediaIngestion) -> None:
    def load(source_id: str, ready: bool = False) -> tuple[Path, Analysis]:
        with PersonaStore(settings.db_path) as store:
            source = store.get_source(source_id)
        if source is None or not source.media_sha:
            raise HTTPException(404, "找不到这条音视频记忆")
        if source.media_status in {"queued", "extracting", "transcribing"}:
            raise HTTPException(409, "请等录音转写完成后再确认")
        if ready and source.media_status != "ready":
            raise HTTPException(409, "请先完成转写并确认说话人")
        folder = settings.db_path.parent / "media-sources" / source.media_sha
        if not (folder / "analysis.json").is_file():
            raise HTTPException(409, "请等录音转写完成后再确认")
        return folder, Analysis.load(folder)

    def candidate_file(folder: Path, candidate: Candidate) -> Path:
        path = folder / candidate.file
        if (
            not re.fullmatch(r"[0-9a-f]{32}-(voice|portrait)-\d+\.(wav|png)", candidate.file)
            or path.is_symlink()
            or not path.is_file()
        ):
            raise HTTPException(404, "找不到这个候选，请刷新后重试")
        return path

    def view(source_id: str, analysis: Analysis) -> dict[str, Any]:
        base = f"/api/persona/sources/{source_id}"
        with PersonaStore(settings.db_path) as store:
            source = store.get_source(source_id)
        return {
            "pending": source.candidates_pending if source else False,
            "speaker": analysis.speaker,
            "confirmed": analysis.confirmed,
            "automatic": analysis.automatic,
            "speakers": [
                {
                    **s.model_dump(),
                    "suggested": s.id == analysis.suggested,
                    "samples": [
                        f"{base}/samples/{position}/{i}?revision={analysis.revision}"
                        for i, _ in enumerate(sample_windows(analysis, s.id))
                    ],
                }
                for position, s in enumerate(analysis.speakers)
            ],
            "voices": [{**c.model_dump(), "url": f"{base}/candidates/voice/{c.id}"} for c in analysis.voices],
            "portraits": [{**c.model_dump(), "url": f"{base}/candidates/portrait/{c.id}"} for c in analysis.portraits],
            "candidate_error": analysis.candidate_error,
        }

    @app.get("/api/persona/sources/{source_id}/speakers")
    def speakers(source_id: str) -> dict[str, Any]:
        with ingestion.lock:
            _, analysis = load(source_id)
            return view(source_id, analysis)

    @app.put("/api/persona/sources/{source_id}/speaker")
    def choose(source_id: str, body: SpeakerBody) -> dict[str, Any]:
        with ingestion.lock, PersonaStore(settings.db_path) as store:
            folder, analysis = load(source_id)
            source = store.get_source(source_id)
            assert source is not None
            if body.speaker is not None and body.speaker not in {s.id for s in analysis.speakers}:
                raise HTTPException(400, "请选择录音中的说话人")
            analysis.speaker, analysis.confirmed, analysis.automatic = body.speaker, True, False
            analysis.revision = uuid.uuid4().hex
            analysis.voices, analysis.portraits, analysis.candidate_error = [], [], None

            def prepare(job: Job) -> None:
                source.media_job_id = job.job_id
                analysis.save(folder)
                ingestion.store_analysis(store, source, analysis)

            job = ingestion.jobs.submit(
                "media_ingest",
                source.title,
                lambda log: ingestion.candidates(source_id, analysis.revision, log),
                prepare=prepare,
            )
        ingestion.queue_build()
        return {**view(source_id, analysis), "job_id": job.job_id}

    @app.get("/api/persona/sources/{source_id}/samples/{position}/{index}")
    def sample(source_id: str, position: int, index: int, revision: str | None = None) -> FileResponse:
        with ingestion.lock:
            folder, analysis = load(source_id)
            if (
                position < 0
                or position >= len(analysis.speakers)
                or index < 0
                or (revision and revision != analysis.revision)
            ):
                raise HTTPException(404, "找不到这段试听")
            windows = sample_windows(analysis, analysis.speakers[position].id)
            if index >= len(windows):
                raise HTTPException(404, "找不到这段试听")
            path = folder / f"{analysis.revision}-sample-{position}-{index}.wav"
            if not path.is_file():
                cut(folder / "audio.wav", path, *windows[index])
            return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})

    @app.get("/api/persona/sources/{source_id}/candidates/{kind}/{candidate_id}")
    def media(source_id: str, kind: Literal["voice", "portrait"], candidate_id: str) -> FileResponse:
        with ingestion.lock:
            folder, analysis = load(source_id)
            candidates = analysis.voices if kind == "voice" else analysis.portraits
            candidate = next((c for c in candidates if c.id == candidate_id), None)
            if candidate is None:
                raise HTTPException(404, "找不到这个候选，请刷新后重试")
            return FileResponse(
                candidate_file(folder, candidate),
                media_type="audio/wav" if kind == "voice" else "image/png",
                headers={"Cache-Control": "private, no-store"},
            )

    def adopt(source_id: str, body: AdoptBody, kind: Literal["voice", "portrait"]) -> dict[str, Any]:
        with ingestion.lock:
            folder, analysis = load(source_id, ready=True)
            candidates = analysis.voices if kind == "voice" else analysis.portraits
            candidate = next((c for c in candidates if c.id == body.candidate), None)
            if candidate is None:
                raise HTTPException(404, "找不到这个候选，请刷新后重试")
            path = candidate_file(folder, candidate)
            assets = AssetStore(settings.db_path)
            assets.prepare()
            if kind == "voice":
                content, duration = voice(path, assets.directory)
                profile = assets.save("voice", content, duration)
                assets.publish_voice(settings.tts.voice_dir)
                return profile
            return assets.save("portrait", portrait(path, face_crop(candidate, path)))

    @app.post("/api/persona/sources/{source_id}/adopt-voice")
    def adopt_voice(source_id: str, body: AdoptBody) -> dict[str, Any]:
        return adopt(source_id, body, "voice")

    @app.post("/api/persona/sources/{source_id}/adopt-portrait")
    def adopt_portrait(source_id: str, body: AdoptBody) -> dict[str, Any]:
        return adopt(source_id, body, "portrait")
