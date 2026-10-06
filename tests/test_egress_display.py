"""The web lists only configured external services, without constructing them."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.egress import egress_status
from twin.web import create_app


def test_default_and_disabled_backends_do_not_claim_external_services(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    settings = Settings.model_validate(
        {
            "db_path": tmp_path / "twin.db",
            "tts": {"provider": "silent", "base_url": "https://unused.test", "egress": "external"},
            "embed": {"provider": "hashing", "egress": "external"},
            "asr": {"provider": "openai_compat", "model": "unused", "egress": "external"},
            "video": {"provider": "none", "egress": "external"},
            "judges": [{"provider": "openai_compat", "model": "unused"}],
        }
    )
    assert egress_status(settings, external_only=True) == []
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.get("/api/identity").json()["egress"] == []
        status = client.get("/api/status").json()
        assert status["egress"] == []


def test_configured_external_services_include_judges_and_sanitized_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    settings = Settings.model_validate(
        {
            "db_path": tmp_path / "twin.db",
            "llm": {"model": "chat", "base_url": "https://user:secret@api.example.com/v1?token=hidden"},
            "embed": {"provider": "openai_compat", "base_url": "https://api.cloudflare.com/v1"},
            "tts": {"provider": "cloudflare", "base_url": "https://speech.test"},
            "asr": {"model": "whisper", "base_url": "https://recognition.test"},
            "video": {"provider": "remote", "host": "gpu-box", "command": "generate"},
            "judges": [
                {"model": "check", "base_url": "https://judge.test"},
                {"model": "local", "base_url": "http://localhost/v1"},
                {"model": "unconfigured"},
            ],
        }
    )
    rows = egress_status(settings, external_only=True)
    assert [(row["kind"], row["host"]) for row in rows] == [
        ("llm", "api.example.com"),
        ("embed", "api.cloudflare.com"),
        ("tts", "speech.test"),
        ("asr", "recognition.test"),
        ("video", "gpu-box"),
        ("judge", "judge.test"),
    ]
    assert all(row["external"] for row in rows)
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        status = client.get("/api/status").json()
        assert status["egress"] == rows
        assert client.get("/api/identity").json()["egress"] == rows
        assert "secret" not in str(status) and "hidden" not in str(status)


@pytest.mark.parametrize("endpoint,external", [("http://localhost/v1", False), ("https://api.example.com/v1", True)])
def test_env_resolution_matches_actual_factories(
    endpoint: str, external: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", endpoint)
    settings = Settings.model_validate(
        {
            "llm": {"model": "chat"},
            "embed": {"provider": "openai_compat"},
            "tts": {"provider": "openai_compat", "model": "speech"},
            "asr": {"model": "whisper"},
            "judges": [{"model": "check"}],
        }
    )
    # Speech factories require their own endpoint; only LLM/embedding use OPENAI_BASE_URL.
    assert [row["kind"] for row in egress_status(settings, external_only=True)] == (
        ["llm", "embed", "judge"] if external else []
    )


@pytest.mark.parametrize("kind", ["llm", "tts", "asr", "judge"])
def test_openai_compat_without_a_model_is_not_configured(kind: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    section = {"provider": "openai_compat", "base_url": "https://unused.test"}
    settings = Settings.model_validate({"judges": [section]} if kind == "judge" else {kind: section})
    assert not egress_status(settings, external_only=True)
