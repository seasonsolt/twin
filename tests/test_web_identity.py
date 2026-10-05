"""Offline read-only identity API and page contracts."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from twin.config import Settings
from twin.egress import egress_status
from twin.web import create_app


def test_get_identity_shape_without_constructing_backends(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "target_name": "合成人物",
            "target_aliases": ["合成别名"],
            "db_path": tmp_path / "identity.db",
            "llm": {"base_url": "https://llm.invalid/v1", "egress": "external"},
            "tts": {"voice": "invented-preset"},
            "avatar": {"preset": "ink"},
            "judges": [{"base_url": "https://judge.invalid/v1"}],
        }
    )
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        response = client.get("/api/identity")
        assert response.status_code == 200
        assert response.json() == {
            "name": "合成人物",
            "aliases": ["合成别名"],
            "voice": "invented-preset",
            "avatar": "ink",
            "egress": egress_status(settings),
        }
    assert not settings.db_path.exists()
    assert all(set(row) == {"kind", "provider", "host", "external", "declared"} for row in egress_status(settings))


def test_identity_consent_endpoint_is_removed(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "identity.db")
    app = create_app(settings)
    assert all(getattr(route, "path", None) != "/api/identity/consent" for route in app.routes)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/identity/consent", json={"scope": "egress:llm", "decision": "grant"}, headers={"X-Twin": "1"}
        )
        assert response.status_code == 405  # static GET mount, not a consent endpoint
    assert not settings.db_path.exists()


def test_identity_page_static_contract(tmp_path: Path) -> None:
    with TestClient(create_app(Settings(db_path=tmp_path / "identity.db")), base_url="http://localhost") as client:
        page = client.get("/static/identity.js")
        assert page.status_code == 200
        assert '/api/identity"' in page.text
        assert "名字与音色/形象" in page.text and "声明/推断" in page.text
        assert "不支持真人声音复刻或照片驱动形象" in page.text
        for removed in ("/api/identity/consent", "data.consents", "data.biometric", "granted", "window.confirm"):
            assert removed not in page.text
        assert 'identity: { title: "身份"' in client.get("/static/app.js").text
        assert "#/identity" in client.get("/").text
