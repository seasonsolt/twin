from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError

from twin.config import AvatarSettings, Settings
from twin.media.tts import SilentSynthesizer
from twin.web import create_app


@pytest.mark.parametrize(
    ("case", "message"),
    [
        ("missing", "不存在"),
        ("directory", "必须是文件"),
        ("suffix", "后缀"),
        ("large", "10 MB"),
        ("magic", "真实图片魔数"),
        ("mismatch", "真实图片魔数"),
        ("fake_webp", "真实图片魔数"),
    ],
)
def test_image_validation(tmp_path: Path, case: str, message: str) -> None:
    suffix = ".gif" if case == "suffix" else ".webp" if case == "fake_webp" else ".png"
    path = tmp_path / f"avatar{suffix}"
    if case == "directory":
        path.mkdir()
    elif case != "missing":
        path.write_bytes(
            b"not an image"
            if case == "magic"
            else b"\xff\xd8\xff"
            if case == "mismatch"
            else b"RIFFxxxxFAKE"
            if case == "fake_webp"
            else b"\x89PNG\r\n\x1a\n"
        )
        if case == "large":
            with path.open("ab") as image:
                image.truncate(10 * 1024 * 1024 + 1)
    with pytest.raises(ValidationError, match=message):
        AvatarSettings(image_path=str(path))


def test_image_validation_boundary_and_relative_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "avatar.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")
    with path.open("ab") as image:
        image.truncate(10 * 1024 * 1024)
    monkeypatch.chdir(tmp_path)
    assert AvatarSettings(image_path="avatar.png").image_path == str(path.resolve())
    monkeypatch.setenv("HOME", str(tmp_path))
    assert AvatarSettings(image_path="~/avatar.png").image_path == str(path.resolve())
    assert AvatarSettings().image_path is None


def test_unreadable_image_has_chinese_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "avatar.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n")

    def unreadable(*args: object, **kwargs: object) -> None:
        raise PermissionError("private path")

    monkeypatch.setattr(Path, "open", unreadable)
    with pytest.raises(ValidationError, match="无法读取肖像图片文件"):
        AvatarSettings(image_path=str(path))


@pytest.mark.parametrize(
    ("suffix", "format_name", "content_type"),
    [
        (".PNG", "PNG", "image/png"),
        (".jpg", "JPEG", "image/jpeg"),
        (".jpeg", "JPEG", "image/jpeg"),
        (".webp", "WEBP", "image/webp"),
    ],
)
@pytest.mark.parametrize("speech_error", [False, True])
def test_image_endpoint_and_capabilities(
    tmp_path: Path, suffix: str, format_name: str, content_type: str, speech_error: bool
) -> None:
    path = tmp_path / f"avatar{suffix}"
    Image.new("RGB", (8, 8)).save(path, format=format_name)
    model = tmp_path / "avatar.vrm"
    model.write_bytes(b"glTF")
    settings = Settings(
        db_path=tmp_path / "twin.db",
        avatar=AvatarSettings(image_path=str(path), vrm_path=str(model)),
    )

    def factory() -> SilentSynthesizer:
        if speech_error:
            raise ValueError("invalid speech configuration")
        return SilentSynthesizer()

    with TestClient(create_app(settings, synthesizer_factory=factory), base_url="http://localhost") as client:
        capabilities = client.get("/api/media/capabilities")
        assert capabilities.json()["avatar_image"] == {"url": "/api/media/avatar-image"}
        assert capabilities.json()["avatar_model"] == {"format": "vrm", "url": "/api/media/avatar.vrm"}
        assert str(tmp_path) not in capabilities.text
        response = client.get("/api/media/avatar-image")
        assert response.status_code == 200
        assert response.content == path.read_bytes()
        assert response.headers["content-type"] == content_type
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-content-type-options"] == "nosniff"
        path.unlink()
        assert client.get("/api/media/avatar-image").status_code == 404


def test_unset_image_endpoint_and_capabilities(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://localhost") as client:
        assert client.get("/api/media/capabilities").json()["avatar_image"] is None
        response = client.get("/api/media/avatar-image")
        assert response.status_code == 404
        assert response.json()["detail"] == "未配置肖像图片"
