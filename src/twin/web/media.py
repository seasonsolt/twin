"""HTTP access to the stable media presentation contracts."""

from __future__ import annotations

import copy
import datetime as dt
import re
import secrets
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..assets import AssetStore
from ..config import Settings, make_synthesizer, make_video_synthesizer
from ..media.adapters import presentable_from_payload
from ..media.clip import render_clip
from ..media.render import EXPORT_CSP, export_html, render_audio
from ..media.schema import AVATAR_PRESETS, AudioManifest, MediaScript, VoiceSpec
from ..media.script import script_from_presentable
from ..media.tts import (
    MediaError,
    MediaInputTooLong,
    MediaRejected,
    MediaTimeout,
    MediaUnavailable,
    SpeechSynthesizer,
)
from ..media.video import VideoSynthesizer
from ..util import private_directory
from .jobs import JobError, JobManager

AUDIO_NAME = re.compile(r"[0-9a-f]{64}\.(wav|mp3)")
VIDEO_NAME = re.compile(r"[0-9a-f]{64}\.mp4")


class PrivateAudioMiddleware:
    """Keep served audio private without relaxing the application's security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def send_private(message: Message) -> None:
            if (
                message["type"] == "http.response.start"
                and 200 <= message["status"] < 300
                and scope.get("method") in {"GET", "HEAD"}
                and str(scope.get("path", "")).startswith("/api/media/audio/")
            ):
                MutableHeaders(scope=message)["Cache-Control"] = "private, no-store"
            if (
                message["type"] == "http.response.start"
                and 200 <= message["status"] < 300
                and scope.get("path") in {"/api/media/avatar.vrm", "/api/media/avatar-image"}
            ):
                MutableHeaders(scope=message)["Cache-Control"] = "no-cache"
            await send(message)

        await self.app(scope, receive, send_private)


def speech_error(exc: MediaError) -> tuple[int, str]:
    """Map backend-neutral errors without reflecting backend messages or credentials."""
    if isinstance(exc, MediaInputTooLong):
        return 413, "朗读内容过长，请缩短回答后重试"
    if isinstance(exc, MediaTimeout):
        return 504, "语音合成超时，请稍后重试"
    if isinstance(exc, MediaRejected):
        return 502, "语音服务拒绝了请求，请检查预置音色和语言配置"
    return 503, "语音服务不可用，请检查语音配置和密钥环境变量"


class MediaBody(BaseModel):
    kind: Literal["chat_reply"]
    answer: dict[str, Any]
    persona_name: str | None = None


class AudioBody(MediaBody):
    segments: list[Annotated[int, Field(strict=True, ge=0)]] | None = None


def register(
    app: FastAPI,
    settings: Settings,
    synthesizer_factory: Callable[[], SpeechSynthesizer] | None = None,
    video_factory: Callable[[], VideoSynthesizer | None] | None = None,
    *,
    jobs: JobManager | None = None,
    name_factory: Callable[[], str] | None = None,
) -> None:
    """Register under the application's existing security middleware with lazy speech."""
    app.add_middleware(PrivateAudioMiddleware)
    cache_dir = settings.db_path.parent / "media-cache"
    assets = AssetStore(settings.db_path)
    synthesizer: SpeechSynthesizer | None = None
    selected_voice: str | None = None
    lock = threading.Lock()
    video_jobs = jobs or JobManager(1, lambda _: "视频生成失败，请检查 [video] 和 ffmpeg 配置")
    video = video_factory or (lambda: make_video_synthesizer(settings))
    video_available = video_factory is not None or settings.video.provider == "remote"
    allow_video_fallback = not settings.video.require_assets

    def own_video_assets() -> bool:
        return assets.path("portrait") is not None and assets.path("voice") is not None

    def speech() -> SpeechSynthesizer:
        nonlocal synthesizer, selected_voice
        with lock:
            try:
                voice_id = assets.publish_voice(settings.tts.voice_dir) or settings.tts.voice
                if synthesizer is None or voice_id != selected_voice:
                    if synthesizer_factory is None:
                        synthesizer = make_synthesizer(settings.tts.model_copy(update={"voice": voice_id}))
                    else:
                        synthesizer = copy.copy(synthesizer_factory())
                        if voice_id.startswith("self-"):
                            synthesizer.voice = VoiceSpec(
                                voice_id=voice_id, language=settings.tts.language, label="我的声音"
                            )
                    selected_voice = voice_id
            except (ValueError, OSError):
                raise MediaUnavailable("语音配置无效") from None
            return synthesizer

    @app.exception_handler(MediaError)
    async def media_error(request: Request, exc: MediaError) -> JSONResponse:
        status, detail = speech_error(exc)
        return JSONResponse({"detail": detail}, status_code=status)

    @app.get("/api/media/avatar.vrm")
    def avatar_file() -> FileResponse:
        if settings.avatar.vrm_path is None:
            raise HTTPException(404, "未配置 VRM 形象模型")
        path = Path(settings.avatar.vrm_path)
        if not path.is_file():
            raise HTTPException(404, "找不到 VRM 形象模型")
        return FileResponse(path, media_type="model/gltf-binary", headers={"Cache-Control": "no-cache"})

    @app.get("/api/media/avatar-image")
    def avatar_image_file() -> FileResponse:
        uploaded = assets.path("portrait")
        if uploaded is None and settings.avatar.image_path is None:
            raise HTTPException(404, "未配置肖像图片")
        path = uploaded or Path(settings.avatar.image_path or "")
        if not path.is_file():
            raise HTTPException(404, "找不到肖像图片")
        content_type = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }[path.suffix.lower()]
        return FileResponse(path, media_type=content_type, headers={"Cache-Control": "no-cache"})

    @app.get("/api/media/capabilities")
    def capabilities() -> dict[str, Any]:
        avatar = AVATAR_PRESETS[settings.avatar.preset].model_dump(mode="json")
        avatar_model = (
            {"format": "vrm", "url": "/api/media/avatar.vrm"} if settings.avatar.vrm_path is not None else None
        )
        portrait = assets.profile()["portrait"] if assets.path("portrait") else None
        avatar_image = (
            {"url": f"/api/media/avatar-image?v={portrait['sha']}"}
            if portrait
            else {"url": "/api/media/avatar-image"}
            if settings.avatar.image_path is not None
            else None
        )
        profile = assets.profile()
        asset_key = f"{portrait['sha'] if portrait else ''}:{profile['voice']['id'] if profile['voice'] else ''}"
        missing_assets = not allow_video_fallback and not own_video_assets()
        video_capability = {
            "available": video_available and not missing_assets,
            **({"reason": "先在「关于你」上传形象和声音"} if missing_assets else {}),
            **({"asset_key": asset_key} if portrait or profile["voice"] else {}),
        }
        try:
            synth = speech()
            declared = synth.capabilities
        except MediaError as exc:
            return {
                "avatar": avatar,
                "avatar_model": avatar_model,
                "avatar_image": avatar_image,
                "video": video_capability,
                "available": False,
                "backend": None,
                "languages": [],
                "audio_formats": [],
                "error": speech_error(exc)[1],
            }
        return {
            "avatar": avatar,
            "avatar_model": avatar_model,
            "avatar_image": avatar_image,
            "video": video_capability,
            "available": synth.name != "silent",
            "backend": synth.name,
            "languages": declared.languages,
            "audio_formats": declared.audio_formats,
        }

    def make_script(body: MediaBody) -> MediaScript:
        try:
            presentable = presentable_from_payload(body.kind, body.answer)
        except ValidationError as exc:
            errors = [{**error, "loc": ("body", "answer", *error["loc"])} for error in exc.errors()]
            raise RequestValidationError(errors) from exc
        name = (
            body.persona_name
            if body.persona_name is not None
            else name_factory()
            if name_factory
            else settings.target_name
        )
        return script_from_presentable(presentable, name)

    @app.post("/api/media/audio")
    def audio(body: AudioBody) -> dict[str, Any]:
        script = make_script(body)
        if body.segments is not None and any(index >= len(script.segments) for index in body.segments):
            raise HTTPException(400, "语音分段索引超出范围")
        try:
            synth = speech()
            private_directory(cache_dir)
            cache_dir.chmod(0o700)
            requests = cache_dir / "requests"
            private_directory(requests)
            requests.chmod(0o700)
            rendered = render_audio(script, synth, cache_dir, segments=body.segments)
            manifest = AudioManifest.model_validate_json((cache_dir / rendered.manifest_file).read_bytes())
        except OSError:
            raise MediaUnavailable("无法保存语音文件") from None
        return {
            "script": script.model_dump(mode="json"),
            "segment_count": len(script.segments),
            "segments": [
                {
                    "index": segment.index,
                    "url": f"/api/media/audio/{part.file_name}",
                    "audio_format": part.audio_format,
                    "duration_s": part.duration_s,
                    "lipsync": part.lipsync.model_dump(mode="json") if part.lipsync is not None else None,
                }
                for segment in rendered.segments
                for part in segment.parts
            ],
            "manifest": manifest.model_dump(mode="json"),
        }

    @app.get("/api/media/audio/{name}")
    def audio_file(name: str) -> FileResponse:
        if AUDIO_NAME.fullmatch(name) is None:
            raise HTTPException(404, "找不到语音文件")
        try:
            directory = cache_dir.resolve()
            candidate = directory / name
            path: Path = candidate.resolve()
            if candidate.is_symlink() or not path.is_relative_to(directory) or not path.is_file():
                raise HTTPException(404, "找不到语音文件")
        except (OSError, RuntimeError):
            raise HTTPException(404, "找不到语音文件") from None
        return FileResponse(path, media_type="audio/wav" if path.suffix == ".wav" else "audio/mpeg")

    @app.post("/api/media/script")
    def script(body: MediaBody) -> MediaScript:
        return make_script(body)

    @app.post("/api/media/clip")
    def clip(body: MediaBody) -> FileResponse:
        script = make_script(body)
        path: Path | None = None
        try:
            private_directory(cache_dir)
            with tempfile.NamedTemporaryFile(dir=cache_dir.parent, suffix=".mp4", delete=False) as output:
                path = Path(output.name)
            render_clip(
                script, speech(), AVATAR_PRESETS[settings.avatar.preset], path, font_path=settings.media.font_path
            )
            return FileResponse(
                path,
                media_type="video/mp4",
                filename="twin-media.mp4",
                headers={"Cache-Control": "private, no-store"},
                background=BackgroundTask(path.unlink, missing_ok=True),
            )
        except (MediaError, OSError) as exc:
            if path is not None:
                path.unlink(missing_ok=True)
            if isinstance(exc, OSError):
                raise MediaUnavailable("无法保存视频文件") from None
            raise

    @app.post("/api/media/video")
    def submit_video(body: MediaBody) -> dict[str, str]:
        script = make_script(body)
        if script.abstain:
            raise HTTPException(400, "分身已弃权，不能生成讲述视频")
        if not allow_video_fallback and not own_video_assets():
            raise HTTPException(503, "先在「关于你」上传形象和声音")
        if not video_available:
            raise HTTPException(503, "视频未配置，请设置 [video]")
        # Capture references before the job starts; later asset edits cannot select driver fallbacks.
        try:
            synth = video()
        except MediaUnavailable:
            if not allow_video_fallback:
                raise HTTPException(503, "先在「关于你」上传形象和声音") from None
            raise

        def generate(log: Callable[[str], None]) -> dict[str, Any]:
            name = f"{secrets.token_hex(32)}.mp4"
            path = cache_dir / name
            try:
                if synth is None:
                    raise MediaUnavailable("视频未配置")
                private_directory(cache_dir)
                cache_dir.chmod(0o700)
                log("正在生成视频，通常需要几分钟")
                result = synth.synthesize(script, path)
                path.chmod(0o600)
                return {"file": name, "duration_s": result.duration_s, "warnings": result.warnings}
            except Exception:
                path.unlink(missing_ok=True)
                # JobManager logs exceptions; never let transport responses or personal text escape.
                raise JobError("视频生成失败，请检查视频和媒体配置") from None

        job = video_jobs.submit("video", "生成真人视频", generate)
        return {"job_id": job.job_id}

    @app.get("/api/media/video/jobs/{job_id}")
    def video_job(job_id: str) -> dict[str, Any]:
        snapshot = video_jobs.snapshot(job_id)
        if snapshot is None:
            raise HTTPException(404, "找不到视频任务，服务重启后记录会清空")
        return {**snapshot, "kind": "video", "kind_label": "生成真人视频"}

    @app.get("/api/media/video/{name}")
    def video_file(name: str) -> FileResponse:
        if VIDEO_NAME.fullmatch(name) is None:
            raise HTTPException(404, "找不到视频文件")
        try:
            directory = cache_dir.resolve()
            candidate = directory / name
            path = candidate.resolve()
            if candidate.is_symlink() or not path.is_relative_to(directory) or not path.is_file():
                raise HTTPException(404, "找不到视频文件")
        except (OSError, RuntimeError):
            raise HTTPException(404, "找不到视频文件") from None
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, no-store"})

    @app.post("/api/media/export", response_class=HTMLResponse)
    def export(body: MediaBody) -> HTMLResponse:
        return HTMLResponse(
            export_html(make_script(body), clock=lambda: dt.datetime.now(dt.UTC)),
            headers={
                "Content-Disposition": 'attachment; filename="twin-media.html"',
                "Content-Security-Policy": EXPORT_CSP,
            },
        )
