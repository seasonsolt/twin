"""The persona edition: one person's own twin on their own machine. The team's API is not there; chat, memories and
sources are. The team edition keeps everything."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.config import ProductSettings, Settings, load_settings
from twin.media.tts import SilentSynthesizer
from twin.web import create_app
from twin.web.gpu import GpuMonitor
from twin.web.system import TEAM_PATHS, team_path

CSRF = {"X-Twin": "1"}


def client_for(settings: Settings) -> TestClient:
    app = create_app(settings, synthesizer_factory=SilentSynthesizer)
    monitor: GpuMonitor = app.state.gpu
    monitor.interval = 3600  # no background round during the test
    return TestClient(app, base_url="http://localhost")


def persona_settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "twin.db", product=ProductSettings(edition="persona"))


def test_the_edition_defaults_to_persona_unless_twin_edition_says_team(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TWIN_EDITION")
    assert Settings().product.edition == "persona"
    monkeypatch.setenv("TWIN_EDITION", "something else")
    assert Settings().product.edition == "persona"
    monkeypatch.setenv("TWIN_EDITION", "team")
    assert Settings().product.edition == "team"


def test_twin_toml_wins_over_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_EDITION", "team")
    config = tmp_path / "twin.toml"
    config.write_text('[product]\nedition = "persona"\n', encoding="utf-8")
    assert load_settings(config).product.edition == "persona"
    config.write_text('[product]\nedition = "company"\n', encoding="utf-8")
    with pytest.raises(ValueError):
        load_settings(config)


def test_team_paths_are_whole_segments() -> None:
    assert team_path("/api/library") and team_path("/api/library/recordings/r1")
    assert team_path("/api/persona/handoffs/count")
    assert not team_path("/api/libraryish")
    assert not team_path("/api/persona/answersheet")
    assert not any(team_path(p) for p in ("/api/status", "/api/persona/sources", "/api/persona/items", "/api/whoami"))
    assert len(set(TEAM_PATHS)) == len(TEAM_PATHS)


def test_the_persona_edition_has_no_team_api(tmp_path: Path) -> None:
    client = client_for(persona_settings(tmp_path))
    whoami = client.get("/api/whoami").json()
    assert whoami["edition"] == "persona"
    assert whoami["features"] == {"work": False, "ledger": False}
    for path in (
        "/api/library",
        "/api/library/people",
        "/api/library/minutes/pending",
        "/api/library/voice",
        "/api/personas/commitments",
        "/api/persona/handoffs",
        "/api/persona/handoffs/count",
        "/api/persona/lenses",
        "/api/persona/team-answers",
        "/api/persona/work",
        "/api/persona/ledger/brief",
        "/api/channels",
    ):
        refused = client.get(path)
        assert refused.status_code == 404 and refused.json()["code"] == "edition", path
    refused = client.post("/api/personas/ask", json={"question": "谁懂预算"}, headers=CSRF)
    assert refused.status_code == 404 and refused.json()["code"] == "edition"
    # The work and ledger switches are not there to turn back on.
    assert client.put("/api/admin/system/features/work", json={"enabled": True}, headers=CSRF).status_code == 404
    assert client.get("/api/persona/work").status_code == 404
    # The person's own twin stays: its status, memories, sources and conversations.
    for path in ("/api/status", "/api/persona/sources", "/api/persona/items", "/api/personas", "/api/conversations"):
        assert client.get(path).status_code == 200, path


def test_the_team_edition_keeps_everything(tmp_path: Path) -> None:
    client = client_for(Settings(db_path=tmp_path / "twin.db", product=ProductSettings(edition="team")))
    whoami = client.get("/api/whoami").json()
    assert whoami["edition"] == "team"
    assert whoami["features"] == {"work": True, "ledger": True}
    for path in ("/api/library", "/api/persona/handoffs/count", "/api/persona/work", "/api/channels"):
        assert client.get(path).status_code == 200, path
