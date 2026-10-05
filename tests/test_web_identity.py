"""Offline identity API, consent privacy and page contracts."""

from __future__ import annotations

import datetime as dt
import sqlite3
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from twin.config import Settings
from twin.egress import egress_status
from twin.identity import BIOMETRIC_SCOPES, Decision, Scope
from twin.media.schema import CHAT_NOTICE, EXPLICIT_LABEL, OPENING_NOTICE
from twin.persona.dimensions import FACETS, requires_consent
from twin.persona.sources import parse_questionnaire
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.app import STATIC_DIR

HEADERS = {"X-Twin": "1"}
PRIVATE_NOTE = "虚构的私密备注，不应回显"


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.chdir(tmp_path)
    for name in ("TWIN_CONFIG", "DTWIN_CONFIG", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("TWIN_LLM_KEY", "invented-offline-key")
    return Settings.model_validate(
        {
            "target_name": "合成人物",
            "target_aliases": ["合成别名"],
            "db_path": tmp_path / "identity.db",
            "llm": {"base_url": "https://llm.example.invalid/v1", "model": "invented", "egress": "external"},
            "embed": {"provider": "hashing"},
            "tts": {"provider": "silent", "voice": "invented-preset"},
            "asr": {"base_url": "http://127.0.0.1:1234/v1"},
            "judges": [{"base_url": "https://judge.example.invalid/v1", "model": "invented"}],
        }
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as client:
        yield client


def consent_row(client: TestClient, scope: str) -> dict[str, Any]:
    return next(row for row in client.get("/api/identity").json()["consents"] if row["scope"] == scope)


def assert_no_note(response: Any) -> None:
    assert PRIVATE_NOTE not in response.text
    assert '"note"' not in response.text


def test_get_shape_and_latest_decision(client: TestClient, settings: Settings) -> None:
    with PersonaStore(settings.db_path) as store:
        store.append_consent("facet:9.1", Decision.GRANT, "questionnaire", PRIVATE_NOTE)
        latest = store.append_consent("facet:9.1", Decision.REVOKE, "cli", PRIVATE_NOTE)
        store.append_consent("facet:9.2", Decision.DECLINE, "questionnaire")
        expected_egress = egress_status(settings, store)
    response = client.get("/api/identity")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert_no_note(response)
    data = response.json()
    assert set(data) == {"name", "aliases", "voice", "avatar", "consents", "egress", "biometric"}
    assert (data["name"], data["aliases"], data["voice"]) == ("合成人物", ["合成别名"], "invented-preset")
    assert data["avatar"] == settings.avatar.preset
    assert {row["scope"] for row in data["consents"]} == {
        f"facet:{facet.facet_id}" for facet in FACETS if requires_consent(facet.facet_id)
    }
    row = consent_row(client, "facet:9.1")
    assert row == {
        "scope": "facet:9.1",
        "name": "兴趣爱好",
        "decision": "revoke",
        "label": "已撤回",
        "at": latest.at.isoformat(),
        "origin": "cli",
        "granted": False,
        "derived_decision": None,
    }
    assert dt.datetime.fromisoformat(row["at"]).utcoffset() == dt.timedelta(0)
    assert consent_row(client, "facet:9.2")["decision"] == "decline"
    missing = consent_row(client, "facet:9.3")
    assert missing["label"] == "未记录" and missing["derived_decision"] == "decline"
    assert missing["decision"] is None and missing["at"] is None and missing["origin"] is None
    assert data["egress"] == expected_egress
    assert data["biometric"]["voice_clone"] is False and data["biometric"]["face"] is False
    assert "M4 门槛" in data["biometric"]["reason"]


def test_legacy_derived_state_is_not_backfilled(client: TestClient, settings: Settings) -> None:
    parsed = parse_questionnaire("invented.md", "**33.【可跳过】爱好？**　*开放 · 9.1*\n\n回答：虚构爱好。\n", settings)
    with PersonaStore(settings.db_path) as store:
        store.put_source(parsed)
    # Simulate questionnaire rows imported before the ledger existed.
    with sqlite3.connect(settings.db_path) as db:
        db.execute("DELETE FROM p_consent")
    row = consent_row(client, "facet:9.1")
    assert row["label"] == "未记录" and row["decision"] is None
    assert row["derived_decision"] == "grant" and row["granted"] is True
    with PersonaStore(settings.db_path) as store:
        assert store.consent_events() == []
    client.post("/api/identity/consent", headers=HEADERS, json={"scope": "facet:9.1", "decision": "revoke"})
    assert consent_row(client, "facet:9.1")["granted"] is False


@pytest.mark.parametrize("scope", ["facet:9.1", "egress:llm", "egress:embed", "egress:tts", "egress:asr"])
def test_grant_revoke_append_with_web_origin(client: TestClient, settings: Settings, scope: str) -> None:
    for decision in ("grant", "revoke"):
        response = client.post(
            "/api/identity/consent",
            headers=HEADERS,
            json={"scope": scope, "decision": decision, "note": PRIVATE_NOTE},
        )
        assert response.status_code == 200, response.text
        assert_no_note(response)
        result = response.json()
        assert result["scope"] == scope and result["decision"] == decision and result["origin"] == "web"
        assert result["rebuild_needed"] is scope.startswith("facet:")
        assert result["restart_needed"] is False
        if scope.startswith("facet:"):
            assert "twin persona build" in result["message"]
        else:
            assert "下一次懒构造" in result["message"] and "已构造的网页后端需重启，不热更新" in result["message"]
            rows = [row for row in client.get("/api/identity").json()["egress"] if f"egress:{row['kind']}" == scope]
            assert rows and all(row["granted"] is (decision == "grant") for row in rows)
        row = consent_row(client, scope)
        assert row["decision"] == decision and row["at"] == result["at"] and row["origin"] == "web"
        assert_no_note(client.get("/api/identity"))
    with PersonaStore(settings.db_path) as store:
        events = store.consent_events()
    assert [event.decision for event in events] == [Decision.GRANT, Decision.REVOKE]
    assert [event.seq for event in events] == [1, 2]
    assert all(event.origin == "web" and event.note == PRIVATE_NOTE for event in events)


@pytest.mark.parametrize("scope", sorted(BIOMETRIC_SCOPES))
def test_biometric_grant_refused_and_revoke_allowed(client: TestClient, settings: Settings, scope: str) -> None:
    response = client.post(
        "/api/identity/consent", headers=HEADERS, json={"scope": scope, "decision": "grant", "note": PRIVATE_NOTE}
    )
    assert response.status_code == 400
    assert client.get("/api/identity").json()["biometric"]["reason"] in response.json()["detail"]
    assert_no_note(response)
    with PersonaStore(settings.db_path) as store:
        assert store.consent_events() == []
    response = client.post("/api/identity/consent", headers=HEADERS, json={"scope": scope, "decision": "revoke"})
    assert response.status_code == 200 and response.json()["rebuild_needed"] is False
    assert client.get("/api/identity").json()["biometric"]["voice_clone"] is False


@pytest.mark.parametrize("scope", ["", "facet:1.1", "facet:99.1", "egress:other", "biometric:other"])
def test_invalid_scope_uses_contract_message(client: TestClient, settings: Settings, scope: str) -> None:
    with pytest.raises(ValidationError) as error:
        TypeAdapter(Scope).validate_python(scope)
    response = client.post(
        "/api/identity/consent", headers=HEADERS, json={"scope": scope, "decision": "grant", "note": PRIVATE_NOTE}
    )
    assert response.status_code == 400
    assert response.json()["detail"] == error.value.errors(include_input=False)[0]["msg"]
    assert_no_note(response)
    with PersonaStore(settings.db_path) as store:
        assert store.consent_events() == []


def test_csrf_required(client: TestClient, settings: Settings) -> None:
    body = {"scope": "facet:9.1", "decision": "grant", "note": PRIVATE_NOTE}
    for headers in ({}, {"X-Twin": "0"}, {**HEADERS, "Host": "evil.invalid"}):
        response = client.post("/api/identity/consent", json=body, headers=headers)
        assert response.status_code == 403
        assert_no_note(response)
    with PersonaStore(settings.db_path) as store:
        assert store.consent_events() == []


@pytest.mark.parametrize(
    "update", [{"decision": "decline"}, {"note": PRIVATE_NOTE * 201}, {"note": {"secret": PRIVATE_NOTE}}]
)
def test_bad_body_does_not_echo_notes(client: TestClient, settings: Settings, update: dict[str, Any]) -> None:
    response = client.post(
        "/api/identity/consent", headers=HEADERS, json={"scope": "facet:9.1", "decision": "grant", **update}
    )
    assert response.status_code == 400
    assert_no_note(response)
    with PersonaStore(settings.db_path) as store:
        assert store.consent_events() == []


def test_identity_page_static_contract(client: TestClient) -> None:
    page = client.get("/")
    assert 'href="#/identity" data-route="identity"' in page.text
    router = client.get("/static/app.js").text
    assert 'import("./identity.js")' in router
    response = client.get("/static/identity.js")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/javascript")
    script = response.text
    assert script == (STATIC_DIR / "identity.js").read_text(encoding="utf-8")
    for text in (EXPLICIT_LABEL, CHAT_NOTICE, OPENING_NOTICE, "不代表", "数据只保存在本机"):
        assert text not in script
    assert "labels?.explicit" in script
    assert "export async function identityPage" in script
    assert 'method: "POST"' in script and "window.confirm" in script and "数据将发送到外部主机" in script
    assert 'href: "#/sources"' in script and "disabled: true" in script
    assert "innerHTML" not in script
