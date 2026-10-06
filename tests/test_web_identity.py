"""Offline identity API contracts."""

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
            "llm": {"model": "test-model", "base_url": "https://llm.invalid/v1", "egress": "external"},
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
            "about": "",
            "name_source": "config",
            "voice": "invented-preset",
            "avatar": "ink",
            "egress": egress_status(settings, external_only=True),
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
        assert response.status_code == 404
        assert response.json() == {"detail": "找不到请求的资源"}
    assert not settings.db_path.exists()
