from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat_streaming import StreamingLLM, parse_events, seed

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.auth import digest

HEADERS = {"X-Twin": "1"}


def test_additive_migration_cascade_and_paging(tmp_path: Path) -> None:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE p_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        db.execute("INSERT INTO p_meta VALUES ('old', 'preserved')")
    with PersonaStore(path) as store:
        assert store.get_meta("old") == "preserved"
        first = store.create_conversation(None)
        store.append_conversation_turn(first, None, "user", "  第一条消息很长" * 8)
        assert len(store.get_conversation(first, None)["title"]) == 24
        store.append_conversation_turn(first, None, "twin", "答复", {"reply": "答复", "cited": []})
        for _ in range(51):
            store.create_conversation(None)
        assert len(store.list_conversations(None)) == 50
        assert len(store.list_conversations(None, 50)) == 2
        assert store.list_conversations(None, 50)[-1]["id"] == first
        assert store.delete_conversation(first, None)
        assert (
            store._db.execute("SELECT count(*) FROM conversation_turns WHERE conversation_id = ?", (first,)).fetchone()[
                0
            ]
            == 0
        )
    with PersonaStore(path) as reopened:
        assert reopened.get_meta("old") == "preserved"
        assert len(reopened.list_conversations(None, 50)) == 1


def test_crud_persona_isolation_and_import(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    app = create_app(settings)
    with TestClient(app, base_url="http://localhost") as web:
        cid = web.post("/api/conversations", headers=HEADERS).json()["id"]
        assert web.get(f"/api/conversations/{cid}").json() == {"id": cid, "title": "新对话", "turns": []}
        assert web.patch(f"/api/conversations/{cid}", json={"title": "  新标题  "}, headers=HEADERS).status_code == 200
        assert web.get("/api/conversations").json()[0]["title"] == "新标题"
        assert web.patch(f"/api/conversations/{cid}", json={"title": "  "}, headers=HEADERS).status_code == 400
        assert web.get("/api/conversations?offset=-1").status_code == 400
        other = web.post("/api/personas", json={"name": "另一个"}, headers=HEADERS).json()["id"]
        scoped = {**HEADERS, "X-Twin-Persona": other}
        assert web.get("/api/conversations", headers=scoped).json() == []
        assert web.get(f"/api/conversations/{cid}", headers=scoped).status_code == 404
        payload = {
            "reply": "回答",
            "citations": ["x"],
            "cited": [{"id": "x", "text": "依据"}],
            "mode": "grounded",
            "confidence": 0.6,
        }
        body = {
            "migration_id": "12345678-1234-1234-1234-123456789abc",
            "turns": [
                {"role": "user", "content": "老问题", "timestamp": "2025-01-01T12:00:00Z"},
                {"role": "twin", "content": "回答", "timestamp": "2025-01-01T12:01:00Z", "reply": payload},
            ],
        }
        migrated = web.post("/api/conversations", json=body, headers=scoped).json()["id"]
        assert web.post("/api/conversations", json=body, headers=scoped).json()["id"] == migrated
        saved = web.get(f"/api/conversations/{migrated}", headers=scoped).json()
        assert saved["title"] == "老问题" and len(saved["turns"]) == 2
        assert saved["turns"][1]["reply"] == payload
        assert saved["turns"][0]["timestamp"].startswith("2025-01-01")
        assert web.get("/api/conversations", headers=scoped).json()[0]["updated_at"].startswith("2025-01-01")
        assert web.delete(f"/api/conversations/{cid}", headers=HEADERS).status_code == 200
        assert web.get(f"/api/conversations/{cid}").status_code == 404
        assert web.delete(f"/api/conversations/{cid}", headers=HEADERS).status_code == 404
        assert web.delete(f"/api/personas/{other}", headers=HEADERS).status_code == 200
        assert web.get(f"/api/conversations/{migrated}", headers=scoped).status_code == 404
        assert not (tmp_path / "personas" / other / "twin.db").exists()


def test_owner_isolation_including_admin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    settings = Settings(
        db_path=tmp_path / "twin.db",
        auth=AuthSettings(
            enabled=True,
            allowed_emails=["a@example.com", "b@example.com", "admin@example.com"],
            admin_emails=["admin@example.com"],
            smtp=SMTPSettings(host="smtp.example.com", username="test", from_address="twin@example.com"),
        ),
    )
    app = create_app(settings)
    for email in settings.auth.allowed_emails:
        with app.state.auth.database() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (digest(email), email, time.time() + 3600))
    # Two members share access to one persona to exercise conversation ownership independently.
    with TestClient(app, base_url="http://localhost") as web:
        web.cookies.set("twin_session", "a@example.com")
        pid = web.post("/api/personas", json={"name": "成员分身"}, headers=HEADERS).json()["id"]
        headers = {**HEADERS, "X-Twin-Persona": pid}
        cid = web.post("/api/conversations", headers=headers).json()["id"]
        original_accessible = app.state.personas.accessible
        monkeypatch.setattr(
            app.state.personas,
            "accessible",
            lambda entry, identity: entry["id"] == pid or original_accessible(entry, identity),
        )
        for email in ["b@example.com", "admin@example.com"]:
            web.cookies.clear()
            web.cookies.set("twin_session", email)
            assert web.get("/api/conversations", headers=headers).json() == []
            assert web.get(f"/api/conversations/{cid}", headers=headers).status_code == 404
            assert web.patch(f"/api/conversations/{cid}", json={"title": "no"}, headers=headers).status_code == 404
            assert web.delete(f"/api/conversations/{cid}", headers=headers).status_code == 404
            for endpoint in ["/api/persona/chat/stream", "/api/persona/chat"]:
                assert (
                    web.post(
                        endpoint,
                        headers=headers,
                        json={"conversation_id": cid, "messages": [{"role": "user", "content": "no"}]},
                    ).status_code
                    == 404
                )
            own = web.post("/api/conversations", headers=headers).json()["id"]
            assert own != cid
        web.cookies.clear()
        web.cookies.set("twin_session", "a@example.com")
        assert web.get("/api/conversations", headers=headers).json()[0]["id"] == cid
        assert web.get(f"/api/conversations/{cid}", headers=headers).status_code == 200


@pytest.mark.parametrize("with_profile", [True, False])
def test_stream_persists_final_reply_and_no_id_is_unchanged(tmp_path: Path, with_profile: bool) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    if with_profile:
        seed(settings.db_path)
    app = create_app(settings, llm_factory=lambda: StreamingLLM(lambda *_: {}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        cid = web.post("/api/conversations", headers=HEADERS).json()["id"]
        body: dict[str, Any] = {"conversation_id": cid, "messages": [{"role": "user", "content": "怎么看？"}]}
        final = parse_events(web.post("/api/persona/chat/stream", json=body, headers=HEADERS))[-1][1]
        saved = web.get(f"/api/conversations/{cid}").json()
        assert [turn["role"] for turn in saved["turns"]] == ["user", "twin"]
        assert saved["title"] == "怎么看？"
        assert saved["turns"][1]["reply"] == final
        assert saved["turns"][1]["content"] == final["reply"]
        assert web.get("/api/conversations").json()[0]["preview"] == final["reply"][:120]
        del body["conversation_id"]
        assert parse_events(web.post("/api/persona/chat/stream", json=body, headers=HEADERS))[-1][0] == "final"
        assert len(web.get("/api/conversations").json()) == 1
        assert len(web.get(f"/api/conversations/{cid}").json()["turns"]) == 2
        with PersonaStore(settings.db_path) as store:
            assert store._db.execute("SELECT count(*) FROM p_chat_log").fetchone()[0] == (2 if with_profile else 0)


@pytest.mark.parametrize("with_profile", [True, False])
def test_job_endpoint_persists(tmp_path: Path, with_profile: bool) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    if with_profile:
        seed(settings.db_path)
    llm = FakeLLM(lambda *_: {"reply": "回答", "citations": [], "confidence": 0.5, "abstain": False, "mode": "general"})
    with TestClient(
        create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder), base_url="http://localhost"
    ) as web:
        cid = web.post("/api/conversations", headers=HEADERS).json()["id"]
        response = web.post(
            "/api/persona/chat",
            headers=HEADERS,
            json={"conversation_id": cid, "messages": [{"role": "user", "content": "问题"}]},
        )
        if response.status_code == 202:
            for _ in range(100):
                snapshot = web.get(f"/api/jobs/{response.json()['job_id']}").json()
                if snapshot["status"] == "done":
                    break
                time.sleep(0.01)
            final = snapshot["result"]
        else:
            assert response.status_code == 200
            final = response.json()
        assert web.get(f"/api/conversations/{cid}").json()["turns"][1]["reply"] == final


def test_deleted_conversation_cannot_be_resurrected(tmp_path: Path) -> None:
    from twin.web.conversations import append_reply

    with PersonaStore(tmp_path / "twin.db") as store:
        cid = store.create_conversation(None)
        store.append_conversation_turn(cid, None, "user", "问题")
        store.delete_conversation(cid, None)
        append_reply(store, cid, None, {"reply": "迟来的回复"})
        assert store.list_conversations(None) == []
        assert store._db.execute("SELECT count(*) FROM conversation_turns").fetchone()[0] == 0


def test_stream_failure_keeps_started_user_turn(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    seed(settings.db_path)
    llm = FakeLLM(lambda *_: (_ for _ in ()).throw(RuntimeError("secret prompt")))
    with TestClient(
        create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder), base_url="http://localhost"
    ) as web:
        cid = web.post("/api/conversations", headers=HEADERS).json()["id"]
        response = web.post(
            "/api/persona/chat/stream",
            headers=HEADERS,
            json={"conversation_id": cid, "messages": [{"role": "user", "content": "问题"}]},
        )
        assert parse_events(response) == [("error", {"detail": "分身暂时无法回复，请重试"})]
        turns = web.get(f"/api/conversations/{cid}").json()["turns"]
        assert len(turns) == 1 and turns[0]["role"] == "user" and turns[0]["content"] == "问题"
