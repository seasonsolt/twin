"""Self-serve portrait and voice uploads using FastAPI's spooled files and bounded copies."""

from __future__ import annotations

import io
import math
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import IO, Annotated, Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, ImageOps, UnidentifiedImageError
from pillow_heif import register_heif_opener
from starlette.concurrency import run_in_threadpool

from ..assets import AssetStore
from ..config import Settings
from ..media.clip import ffmpeg_path
from ..media.tts import MediaUnavailable

register_heif_opener()

PORTRAIT_LIMIT = 15 * 1024 * 1024
VOICE_LIMIT = 95_000_000
UPLOAD_PATHS = frozenset({"/api/me/portrait", "/api/me/voice"})
VOICE_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".webm", ".mp4", ".mov", ".caf"}


async def read_upload(
    file: UploadFile, output: IO[bytes], limit: int, size_error: str = "文件太大，请选择较小的文件"
) -> None:
    size = 0
    while chunk := await file.read(65536):
        size += len(chunk)
        if size > limit:
            raise HTTPException(413, size_error)
        await run_in_threadpool(output.write, chunk)
    if not size:
        raise HTTPException(400, "文件为空或上传不完整，请重试")
    await run_in_threadpool(output.flush)


def portrait(path: Path, fields: dict[str, str]) -> bytes:
    try:
        with Image.open(path) as source:
            if source.format not in {"JPEG", "PNG", "WEBP", "HEIF"}:
                raise HTTPException(400, "请选择 JPEG、PNG、WebP 或 HEIC/HEIF 照片")
            image = ImageOps.exif_transpose(source).convert("RGB")
        width, height = image.size
        if fields:
            try:
                x, y, w, h = (float(fields[key]) for key in ("x", "y", "w", "h"))
                if not all(math.isfinite(n) and 0 <= n <= 1 for n in (x, y, w, h)):
                    raise ValueError
                if w <= 0 or h <= 0 or x + w > 1.000001 or y + h > 1.000001:
                    raise ValueError
            except (KeyError, ValueError):
                raise HTTPException(400, "裁剪范围无效，请重新裁剪") from None
            box = (round(x * width), round(y * height), round(min(1, x + w) * width), round(min(1, y + h) * height))
        else:
            w_px, h_px = min(width, height * 3 / 4), min(height, width * 4 / 3)
            box = (
                round((width - w_px) / 2),
                round((height - h_px) / 2),
                round((width + w_px) / 2),
                round((height + h_px) / 2),
            )
        image = image.crop(box)
        if min(image.size) < 320:
            raise HTTPException(400, "照片裁剪后太小，短边至少需要 320 像素")
        image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
        # A fresh image strips EXIF, ICC and text metadata inherited from the upload.
        clean = Image.new("RGB", image.size)
        clean.paste(image)
        output = io.BytesIO()
        clean.save(output, format="PNG")
        return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        raise HTTPException(400, "无法读取照片，请选择有效的 JPEG、PNG、WebP 或 HEIC/HEIF 图片") from None


def voice(path: Path, directory: Path) -> tuple[bytes, float]:
    try:
        ffmpeg = ffmpeg_path()
    except MediaUnavailable:
        raise HTTPException(503, "声音处理需要 ffmpeg，请先安装后重试") from None
    with tempfile.NamedTemporaryFile(dir=directory, suffix=".wav") as output:
        try:
            subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-v",
                    "error",
                    "-y",
                    "-i",
                    str(path),
                    "-map",
                    "0:a:0",
                    "-vn",
                    "-af",
                    "highpass=f=80,loudnorm,silenceremove=start_periods=1:start_duration=0.1:"
                    "start_threshold=-45dB,atrim=duration=20,areverse,silenceremove=start_periods=1:"
                    "start_duration=0.1:start_threshold=-45dB,areverse",
                    "-t",
                    "20",
                    "-ac",
                    "1",
                    "-ar",
                    "24000",
                    "-c:a",
                    "pcm_s16le",
                    "-map_metadata",
                    "-1",
                    output.name,
                ],
                check=True,
                capture_output=True,
                timeout=120,
            )
            with wave.open(output.name) as audio:
                duration = audio.getnframes() / audio.getframerate()
                pcm = audio.readframes(audio.getnframes())
        except (subprocess.SubprocessError, OSError, wave.Error):
            raise HTTPException(400, "无法读取声音，请上传带有清晰说话声的录音或视频") from None
        if duration < 5:
            raise HTTPException(400, "声音太短，至少需要 5 秒清晰的说话")
        clean = io.BytesIO()
        with wave.open(clean, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(24000)
            wav.writeframes(pcm)
        return clean.getvalue(), duration


def register(app: FastAPI, settings: Settings) -> None:
    store = AssetStore(settings.db_path)

    @app.get("/api/me/assets")
    def assets() -> dict[str, Any]:
        return {
            **store.profile(),
            "speech_clone": settings.tts.voice_dir is not None,
            "video": settings.video.provider == "remote",
        }

    @app.put("/api/me/portrait")
    async def put_portrait(
        file: Annotated[UploadFile, File()],
        x: Annotated[str | None, Form()] = None,
        y: Annotated[str | None, Form()] = None,
        w: Annotated[str | None, Form()] = None,
        h: Annotated[str | None, Form()] = None,
    ) -> dict[str, Any]:
        fields = {key: value for key, value in {"x": x, "y": y, "w": w, "h": h}.items() if value is not None}
        if any(len(value) > 128 for value in fields.values()):
            raise HTTPException(400, "裁剪参数无效")
        store.prepare()
        with tempfile.NamedTemporaryFile(dir=store.directory, suffix=".upload") as upload:
            await read_upload(file, upload.file, PORTRAIT_LIMIT, "照片不能超过 15 MB")
            content = await run_in_threadpool(portrait, Path(upload.name), fields)
            return await run_in_threadpool(store.save, "portrait", content)

    @app.delete("/api/me/portrait")
    def delete_portrait() -> dict[str, Any]:
        return store.update("portrait", None)

    @app.put("/api/me/voice")
    async def put_voice(file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        if Path(file.filename or "").suffix.lower() not in VOICE_EXTENSIONS:
            raise HTTPException(400, "请选择 wav、mp3、m4a 等录音或常见视频文件")
        store.prepare()
        with tempfile.NamedTemporaryFile(dir=store.directory, suffix=".upload") as upload:
            await read_upload(file, upload.file, VOICE_LIMIT)
            content, duration = await run_in_threadpool(voice, Path(upload.name), store.directory)
            profile = await run_in_threadpool(store.save, "voice", content, duration)
            await run_in_threadpool(store.publish_voice, settings.tts.voice_dir)
            return profile

    @app.get("/api/me/voice/reference")
    def reference() -> FileResponse:
        path = store.path("voice")
        if path is None:
            raise HTTPException(404, "还没有保存自己的声音")
        return FileResponse(path, media_type="audio/wav", headers={"Cache-Control": "private, no-store"})

    @app.delete("/api/me/voice")
    def delete_voice() -> dict[str, Any]:
        return store.update("voice", None)
