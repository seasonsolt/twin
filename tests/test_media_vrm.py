from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
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
        ("large", "64 MB"),
        ("magic", "二进制标记"),
    ],
)
def test_vrm_validation(tmp_path: Path, case: str, message: str) -> None:
    path = tmp_path / ("avatar.glb" if case == "suffix" else "avatar.vrm")
    if case == "directory":
        path.mkdir()
    elif case != "missing":
        path.write_bytes(b"glTF" if case != "magic" else b"xxxx")
        if case == "large":
            with path.open("ab") as model:
                model.truncate(64 * 1024 * 1024 + 1)
    with pytest.raises(ValidationError, match=message):
        AvatarSettings(vrm_path=str(path))


def test_vrm_validation_boundary(tmp_path: Path) -> None:
    path = tmp_path / "avatar.vrm"
    path.write_bytes(b"glTF")
    with path.open("ab") as model:
        model.truncate(64 * 1024 * 1024)
    assert AvatarSettings(vrm_path=str(path)).vrm_path == str(path.resolve())
    assert AvatarSettings().vrm_path is None


@pytest.fixture(params=[False, True])
def client(request: pytest.FixtureRequest, tmp_path: Path) -> Iterator[TestClient]:
    model = tmp_path / "avatar.vrm"
    model.write_bytes(b"glTF\x02\x00\x00\x00")
    settings = Settings(
        db_path=tmp_path / "twin.db",
        avatar=AvatarSettings(vrm_path=str(model) if request.param else None),
    )
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        yield client


def test_vrm_endpoint_and_capabilities(client: TestClient) -> None:
    capabilities = client.get("/api/media/capabilities").json()
    response = client.get("/api/media/avatar.vrm")
    if capabilities["avatar_model"] is None:
        assert response.status_code == 404
        assert response.json()["detail"] == "未配置 VRM 形象模型"
    else:
        assert capabilities["avatar_model"] == {"format": "vrm", "url": "/api/media/avatar.vrm"}
        assert response.status_code == 200
        assert response.content == b"glTF\x02\x00\x00\x00"
        assert response.headers["content-type"] == "model/gltf-binary"
        assert response.headers["cache-control"] == "no-cache"
    csp = response.headers["content-security-policy"]
    assert csp == (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
        "font-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'"
    )
    assert [directive.strip() for directive in csp.split(";") if "blob:" in directive] == ["img-src 'self' data: blob:"]


def test_model_available_without_speech(tmp_path: Path) -> None:
    def factory() -> SilentSynthesizer:
        raise ValueError("invalid speech configuration")

    path = tmp_path / "avatar.vrm"
    path.write_bytes(b"glTF")
    settings = Settings(db_path=tmp_path / "twin.db", avatar=AvatarSettings(vrm_path=str(path)))
    with TestClient(create_app(settings, synthesizer_factory=factory), base_url="http://localhost") as client:
        response = client.get("/api/media/capabilities")
        assert response.json()["available"] is False
        assert response.json()["avatar_model"] == {"format": "vrm", "url": "/api/media/avatar.vrm"}
        assert str(path) not in response.text
        assert client.get("/api/media/avatar.vrm").status_code == 200
        path.unlink()
        assert client.get("/api/media/avatar.vrm").status_code == 404
