from __future__ import annotations

import asyncio
import hashlib
import io
import math
import shutil
import struct
import wave
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import HTTPException, UploadFile
from fastapi.testclient import TestClient
from PIL import Image, PngImagePlugin
from pillow_heif import from_pillow

from twin.assets import AssetStore
from twin.config import AvatarSettings, Settings, TTSSettings, load_settings
from twin.media.schema import SpeechRequest, SpeechResult, SynthCapabilities, VoiceSpec
from twin.web.app import create_app
from twin.web.assets import read_upload

HEADERS = {"X-Twin": "1"}
BODY = {
    "kind": "chat_reply",
    "answer": {
        "reply": "你好，这是我的声音。",
        "citations": [],
        "confidence": 1,
        "abstain": False,
        "abstain_reason": "",
        "retrieved_ids": [],
    },
}


def image(size: tuple[int, int] = (1200, 1600), format: str = "PNG") -> bytes:
    output = io.BytesIO()
    picture = Image.new("RGB", size, "red")
    metadata = PngImagePlugin.PngInfo()
    metadata.add_text("private", "secret metadata")
    picture.save(output, format=format, pnginfo=metadata)
    return output.getvalue()


def audio(seconds: float, silence: float = 0) -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(24000)
        pcm = b"".join(
            struct.pack("<h", round(10000 * math.sin(i * math.tau * 300 / 24000)))
            for i in range(round(seconds * 24000))
        )
        padding = b"\0\0" * round(silence * 24000)
        wav.writeframes(padding + pcm + padding)
    return output.getvalue()


def client(tmp_path: Path, **kwargs: Any) -> TestClient:
    return TestClient(create_app(Settings(db_path=tmp_path / "twin.db", **kwargs)), base_url="http://localhost")


def test_portrait_profile_crop_metadata_permissions_and_fallbacks(tmp_path: Path) -> None:
    fallback = tmp_path / "fallback.png"
    fallback.write_bytes(image())
    with client(tmp_path, avatar=AvatarSettings(image_path=str(fallback))) as web:
        assert web.get("/api/me/assets").json() == {
            "portrait": None,
            "voice": None,
            "speech_clone": False,
            "video": False,
        }
        assert web.get("/api/media/avatar-image").content == fallback.read_bytes()
        response = web.put("/api/me/portrait", files={"file": ("self.png", image(), "image/png")}, headers=HEADERS)
        assert response.status_code == 200, response.text
        profile = response.json()
        portrait = profile["portrait"]
        assert portrait["file"] == portrait["sha"] + ".png"
        content = web.get("/api/media/avatar-image").content
        assert hashlib.sha256(content).hexdigest() == portrait["sha"]
        saved = Image.open(io.BytesIO(content))
        assert saved.size == (768, 1024) and saved.mode == "RGB"
        assert not saved.info
        assert web.get("/api/media/capabilities").json()["avatar_image"]["url"].endswith("?v=" + portrait["sha"])
        directory = tmp_path / "assets"
        assert directory.stat().st_mode & 0o777 == 0o700
        assert all(path.stat().st_mode & 0o777 == 0o600 for path in directory.iterdir())
        assert not list(directory.glob("*.upload"))
        # Crop fractions are applied to the transposed image.
        source = Image.new("RGB", (800, 1200), "blue")
        exif = source.getexif()
        exif[274] = 6
        upload = io.BytesIO()
        source.save(upload, format="JPEG", exif=exif)
        response = web.put(
            "/api/me/portrait",
            files={"file": ("self.jpg", upload.getvalue())},
            data={"x": "0.5", "y": "0", "w": "0.5", "h": "1"},
            headers=HEADERS,
        )
        assert response.status_code == 200
        assert Image.open(io.BytesIO(web.get("/api/media/avatar-image").content)).size == (600, 800)
        assert web.delete("/api/me/portrait", headers=HEADERS).json()["portrait"] is None
        assert web.get("/api/media/avatar-image").content == fallback.read_bytes()
    with client(tmp_path) as web:
        assert web.get("/api/media/avatar-image").status_code == 404
        assert web.get("/api/media/capabilities").json()["avatar_image"] is None


@pytest.mark.parametrize("extension", ["heic", "heif"])
def test_heic_portrait_default_crop_and_metadata(tmp_path: Path, extension: str) -> None:
    source = Image.new("RGB", (640, 640), "blue")
    exif = source.getexif()
    exif[315] = "private artist"
    source.info["exif"] = exif.tobytes()
    output = io.BytesIO()
    from_pillow(source).save(output)
    with client(tmp_path) as web:
        response = web.put(
            "/api/me/portrait",
            files={"file": (f"self.{extension}", output.getvalue(), f"image/{extension}")},
            headers=HEADERS,
        )
        assert response.status_code == 200, response.text
        profile = response.json()
        with Image.open(io.BytesIO(web.get("/api/media/avatar-image").content)) as saved:
            assert saved.format == "PNG" and saved.mode == "RGB"
            assert saved.size == (480, 640)
            assert not saved.info and not saved.getexif()
        invalid = web.put(
            "/api/me/portrait", files={"file": (f"bad.{extension}", b"garbage", f"image/{extension}")}, headers=HEADERS
        )
        assert invalid.status_code == 400
        assert "无法读取照片" in invalid.json()["detail"]
        assert web.get("/api/me/assets").json()["portrait"] == profile["portrait"]
        assert not list((tmp_path / "assets").glob("*.upload"))


@pytest.mark.parametrize(
    "content,fields",
    [
        (b"not an image", {}),
        (image((300, 500)), {}),
        (image(format="GIF"), {}),
        (image(), {"x": "nan", "y": "0", "w": "1", "h": "1"}),
        (image(), {"x": "0.8", "y": "0", "w": "0.5", "h": "1"}),
        (image(), {"x": "0", "y": "0", "w": "0.1", "h": "0.1"}),
        (image(), {"x": "0"}),
    ],
)
def test_portrait_validation_preserves_profile(tmp_path: Path, content: bytes, fields: dict[str, str]) -> None:
    with client(tmp_path) as web:
        response = web.put("/api/me/portrait", files={"file": ("self.png", content)}, data=fields, headers=HEADERS)
        assert response.status_code == 400
        assert web.get("/api/me/assets").json()["portrait"] is None
        assert not list((tmp_path / "assets").glob("*.upload"))


def test_spooled_portrait_upload_keeps_json_size_exemption(tmp_path: Path) -> None:
    content = image() + b"\0" * (2 * 1024 * 1024)
    with client(tmp_path) as web:
        response = web.put("/api/me/portrait", files={"file": ("large.png", content)}, headers=HEADERS)
        assert response.status_code == 200, response.text
        assert response.json()["portrait"] is not None
        assert not list((tmp_path / "assets").glob("*.upload"))


def test_chunked_upload_size_limit_and_clean_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.web.assets.PORTRAIT_LIMIT", 100)
    consumed = 0

    async def chunks() -> Any:
        nonlocal consumed
        yield b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="self.png"\r\n\r\n'
        for _ in range(100):
            consumed += 1
            yield b"x" * 80
        yield b"\r\n--boundary--\r\n"

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(Settings(db_path=tmp_path / "twin.db"))),
            base_url="http://localhost",
        ) as web:
            return await web.put(
                "/api/me/portrait",
                content=chunks(),
                headers={**HEADERS, "Content-Type": "multipart/form-data; boundary=boundary"},
            )

    response = asyncio.run(request())
    assert response.status_code == 413 and consumed == 100
    assert response.json()["detail"] == "照片不能超过 15 MB"
    assert not list((tmp_path / "assets").glob("*.upload"))
    with client(tmp_path) as web:
        malformed = web.put(
            "/api/me/portrait", content=b"x", headers={**HEADERS, "Content-Type": "multipart/form-data"}
        )
        assert malformed.status_code == 400
        assert malformed.json()["detail"] == "上传格式无效，请重新选择文件"
        assert web.put("/api/me/portrait", files={"file": ("x.png", image())}).status_code == 403
        missing = web.put("/api/me/portrait", files={"other": ("x.png", b"x")}, headers=HEADERS)
        assert missing.status_code == 400
        assert missing.json()["detail"] == "请上传文件，字段名为 file"
        empty = web.put("/api/me/portrait", files={"file": ("x.png", b"")}, headers=HEADERS)
        assert empty.status_code == 400
        assert empty.json()["detail"] == "文件为空或上传不完整，请重试"


@pytest.mark.parametrize("path,setting", [("portrait", "PORTRAIT_LIMIT"), ("voice", "VOICE_LIMIT")])
def test_content_length_rejected_before_multipart_parsing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str, setting: str
) -> None:
    monkeypatch.setattr(f"twin.web.assets.{setting}", 100)
    consumed = False

    async def chunks() -> Any:
        nonlocal consumed
        consumed = True
        yield b"not multipart"

    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(Settings(db_path=tmp_path / "twin.db"))),
            base_url="http://localhost",
        ) as web:
            return await web.put(
                f"/api/me/{path}",
                content=chunks(),
                headers={**HEADERS, "Content-Length": str(100 + 16385), "Content-Type": "multipart/form-data"},
            )

    response = asyncio.run(request())
    assert response.status_code == 413
    assert response.json()["detail"] == ("照片不能超过 15 MB" if path == "portrait" else "文件太大，请选择较小的文件")
    assert not consumed and not (tmp_path / "assets").exists()
    assert response.headers["x-content-type-options"] == "nosniff"


def test_upload_copy_uses_bounded_chunks_and_stops_at_limit() -> None:
    class Source(io.BytesIO):
        def read(self, size: int = -1) -> bytes:
            assert size == 65536
            return super().read(size)

    source = Source(b"x" * (3 * 65536))
    upload = UploadFile(file=source, filename="large.png")
    output = io.BytesIO()
    with pytest.raises(HTTPException) as exc:
        asyncio.run(read_upload(upload, output, 100_000))
    assert exc.value.status_code == 413 and exc.value.detail == "文件太大，请选择较小的文件"
    assert source.tell() == 2 * 65536 and len(output.getvalue()) == 65536
    source.seek(0)
    output = io.BytesIO()
    asyncio.run(read_upload(upload, output, 3 * 65536))
    assert output.getvalue() == source.getvalue()
    asyncio.run(upload.close())


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_voice_processing_short_rejection_trim_reference_and_reset(tmp_path: Path) -> None:
    voice_dir = tmp_path / "voices"
    with client(tmp_path, tts=TTSSettings(voice_dir=voice_dir)) as web:
        assert web.get("/api/me/assets").json()["speech_clone"]
        assert web.get("/api/me/voice/reference").status_code == 404
        short = web.put("/api/me/voice", files={"file": ("record.wav", audio(3))}, headers=HEADERS)
        assert short.status_code == 400
        assert short.json()["detail"] == "声音太短，至少需要 5 秒清晰的说话"
        silent = web.put("/api/me/voice", files={"file": ("record.wav", audio(0, 10))}, headers=HEADERS)
        assert silent.status_code == 400 and "至少需要 5 秒" in silent.json()["detail"]
        for seconds in (6, 25):
            response = web.put("/api/me/voice", files={"file": ("record.wav", audio(seconds, 1))}, headers=HEADERS)
            assert response.status_code == 200, response.text
            voice = response.json()["voice"]
            reference = web.get("/api/me/voice/reference")
            sha = hashlib.sha256(reference.content).hexdigest()
            assert voice["id"] == "self-" + sha[:16]
            assert voice["file"] == sha + ".wav"
            assert 5 <= voice["duration_s"] <= 20
            if seconds == 6:
                assert voice["duration_s"] < 7
            with wave.open(io.BytesIO(reference.content)) as wav:
                assert (wav.getnchannels(), wav.getframerate(), wav.getsampwidth()) == (1, 24000, 2)
            exported = voice_dir / f"{voice['id']}.wav"
            assert exported.read_bytes() == reference.content
            assert exported.stat().st_mode & 0o777 == 0o644
            assert reference.headers["cache-control"] == "no-store"
        assert web.delete("/api/me/voice", headers=HEADERS).json()["voice"] is None
        assert web.get("/api/me/voice/reference").status_code == 404
        assert not list((tmp_path / "assets").glob("*.upload"))


def test_voice_validation_and_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("twin.web.assets.VOICE_LIMIT", 100)
    with client(tmp_path) as web:
        assert web.put("/api/me/voice", files={"file": ("x.wav", b"x" * 101)}, headers=HEADERS).status_code == 413
        assert web.put("/api/me/voice", files={"file": ("x.exe", b"x")}, headers=HEADERS).status_code == 400
        assert web.put("/api/me/voice", files={"file": ("x.mp4", b"invalid")}, headers=HEADERS).status_code == 400


def test_effective_voice_cache_changes_and_preset_fallback(tmp_path: Path) -> None:
    calls: list[str] = []

    class Synth:
        name = "fake"
        identity = "same-backend"
        voice = VoiceSpec(voice_id="preset")
        capabilities = SynthCapabilities(audio_formats=["wav"], languages=["zh"], max_chars=1000)

        def synthesize(self, request: SpeechRequest) -> SpeechResult:
            calls.append(request.voice.voice_id)
            return SpeechResult(audio=audio(0.01), audio_format="wav", duration_s=0.01)

    settings = Settings(db_path=tmp_path / "twin.db", tts=TTSSettings(voice="preset", voice_dir=tmp_path / "voices"))
    store = AssetStore(settings.db_path)
    with TestClient(create_app(settings, synthesizer_factory=Synth), base_url="http://localhost") as web:
        initial = web.post("/api/media/audio", json=BODY, headers=HEADERS).json()
        first_voice = store.save("voice", audio(6), 6)["voice"]["id"]
        first = web.post("/api/media/audio", json=BODY, headers=HEADERS).json()
        second_voice = store.save("voice", audio(7), 7)["voice"]["id"]
        second = web.post("/api/media/audio", json=BODY, headers=HEADERS).json()
        web.post("/api/media/audio", json=BODY, headers=HEADERS)
        assert calls == ["preset", first_voice, second_voice]
        assert len({reply["segments"][0]["url"] for reply in (initial, first, second)}) == 3
        assert second["manifest"]["voice"]["voice_id"] == second_voice
        store.update("voice", None)
        assert web.post("/api/media/audio", json=BODY, headers=HEADERS).json()["segments"] == initial["segments"]
        assert len(calls) == 3
        # Stored references remain available for video even without speech cloning configured.
        store.save("voice", audio(6), 6)
        settings.tts.voice_dir = None
        assert (
            web.post("/api/media/audio", json=BODY, headers=HEADERS).json()["manifest"]["voice"]["voice_id"] == "preset"
        )


def test_voice_dir_resolves_relative_to_config(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('[tts]\nvoice_dir = "voices"\n')
    assert load_settings(config).tts.voice_dir == tmp_path / "voices"
