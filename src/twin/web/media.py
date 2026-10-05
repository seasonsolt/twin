"""HTTP access to the stable media presentation contracts."""

from __future__ import annotations

import datetime as dt
import re
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, ValidationError
from starlette.background import BackgroundTask
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from ..config import Settings, make_synthesizer
from ..media.adapters import presentable_from_payload
from ..media.clip import render_clip
from ..media.render import EXPORT_CSP, export_html, render_audio
from ..media.schema import AVATAR_PRESETS, EXPLICIT_LABEL, AudioManifest, MediaScript
from ..media.script import script_from_presentable
from ..media.tts import (
    MediaError,
    MediaInputTooLong,
    MediaRejected,
    MediaTimeout,
    MediaUnavailable,
    SpeechSynthesizer,
)
from ..util import private_directory

AUDIO_NAME = re.compile(r"[0-9a-f]{64}\.(wav|mp3)")


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


def register(
    app: FastAPI,
    settings: Settings,
    synthesizer_factory: Callable[[], SpeechSynthesizer] | None = None,
) -> None:
    """Register under the application's existing security middleware with lazy speech."""
    app.add_middleware(PrivateAudioMiddleware)
    cache_dir = settings.db_path.parent / "media-cache"
    factory = synthesizer_factory or (lambda: make_synthesizer(settings.tts))
    synthesizer: SpeechSynthesizer | None = None
    lock = threading.Lock()

    def speech() -> SpeechSynthesizer:
        nonlocal synthesizer
        with lock:
            if synthesizer is None:
                try:
                    synthesizer = factory()
                except (ValueError, OSError):
                    raise MediaUnavailable("语音配置无效") from None
            return synthesizer

    @app.exception_handler(MediaError)
    async def media_error(request: Request, exc: MediaError) -> JSONResponse:
        status, detail = speech_error(exc)
        return JSONResponse({"detail": detail}, status_code=status)

    @app.get("/api/media/capabilities")
    def capabilities() -> dict[str, Any]:
        avatar = AVATAR_PRESETS[settings.avatar.preset].model_dump(mode="json")
        try:
            synth = speech()
            declared = synth.capabilities
        except MediaError as exc:
            return {
                "avatar": avatar,
                "available": False,
                "backend": None,
                "label": EXPLICIT_LABEL,
                "languages": [],
                "audio_formats": [],
                "error": speech_error(exc)[1],
            }
        return {
            "avatar": avatar,
            "available": synth.name != "silent",
            "backend": synth.name,
            "label": EXPLICIT_LABEL,
            "languages": declared.languages,
            "audio_formats": declared.audio_formats,
        }

    def make_script(body: MediaBody) -> MediaScript:
        try:
            presentable = presentable_from_payload(body.kind, body.answer)
        except ValidationError as exc:
            errors = [{**error, "loc": ("body", "answer", *error["loc"])} for error in exc.errors()]
            raise RequestValidationError(errors) from exc
        name = body.persona_name if body.persona_name is not None else settings.target_name
        return script_from_presentable(presentable, name)

    @app.post("/api/media/audio")
    def audio(body: MediaBody) -> dict[str, Any]:
        script = make_script(body)
        try:
            synth = speech()
            private_directory(cache_dir)
            cache_dir.chmod(0o700)
            requests = cache_dir / "requests"
            private_directory(requests)
            requests.chmod(0o700)
            rendered = render_audio(script, synth, cache_dir)
            manifest = AudioManifest.model_validate_json((cache_dir / rendered.manifest_file).read_bytes())
        except OSError:
            raise MediaUnavailable("无法保存语音文件") from None
        return {
            "script": script.model_dump(mode="json"),
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
                headers={"X-AI-Generated": "twin", "Cache-Control": "private, no-store"},
                background=BackgroundTask(path.unlink, missing_ok=True),
            )
        except (MediaError, OSError) as exc:
            if path is not None:
                path.unlink(missing_ok=True)
            if isinstance(exc, OSError):
                raise MediaUnavailable("无法保存视频文件") from None
            raise

    @app.post("/api/media/export", response_class=HTMLResponse)
    def export(body: MediaBody) -> HTMLResponse:
        return HTMLResponse(
            export_html(make_script(body), clock=lambda: dt.datetime.now(dt.UTC)),
            headers={
                "Content-Disposition": 'attachment; filename="twin-media.html"',
                "Content-Security-Policy": EXPORT_CSP,
            },
        )
