"""Offline factory smoke test for every remaining page, static import and browsing API."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi.testclient import TestClient

from twin.config import Settings
from twin.web import create_app
from twin.web.app import MAX_JSON_BYTES

HEADERS = {"X-Twin": "1"}


def test_remaining_pages_and_apis(tmp_path: Path) -> None:
    app = create_app(Settings(target_name="合成人物", db_path=tmp_path / "persona.db"))
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for route in ("chat", "questionnaire", "persona", "sources"):
            page = client.get(f"/#/{route}")
            assert page.status_code == 200
            assert f'data-route="{route}"' in page.text
        pending = ["app.js"]
        visited: set[str] = set()
        while pending:
            name = pending.pop()
            if name in visited:
                continue
            visited.add(name)
            response = client.get(f"/static/{name}")
            assert response.status_code == 200, name
            assert response.headers["content-type"].startswith("text/javascript")
            for symbols, module in re.findall(r'import\s*\{([^}]+)\}\s*from\s*"\./([^\"]+)"', response.text):
                dependency = client.get(f"/static/{module}")
                assert dependency.status_code == 200, module
                for symbol in symbols.split(","):
                    original = symbol.strip().split(" as ")[0]
                    assert re.search(rf"export (?:async )?(?:function|const|class) {original}\b", dependency.text)
                pending.append(module)
        assert visited == {
            "app.js",
            "api.js",
            "dom.js",
            "state.js",
            "persona.js",
            "jobs.js",
            "labels.js",
            "playback.js",
        }
        assert client.get("/static/styles.css").status_code == 200
        persona_js = client.get("/static/persona.js").text
        assert "playbackAction(reply, targetName())" in persona_js
        assert 'kind: "chat_reply"' in client.get("/static/playback.js").text
        for api in (
            "/api/status",
            "/api/jobs",
            "/api/persona/sources",
            "/api/persona/items",
            "/api/persona/coverage",
            "/api/persona/questionnaire",
            "/api/persona/questionnaire?round=retest",
            "/api/media/capabilities",
        ):
            assert client.get(api).status_code == 200, api
        assert client.get("/api/media/capabilities").json()["available"] is False
        assert client.post("/api/persona/build").status_code == 403
        assert client.post("/api/persona/chat", json={}, headers=HEADERS).status_code == 400
        assert client.post("/api/persona/chat", content=b"x" * (MAX_JSON_BYTES + 1), headers=HEADERS).status_code == 413
        assert client.get("/api/status", headers={"Host": "untrusted.invalid"}).status_code == 403

        imported = client.post(
            "/api/persona/import?kind=meeting",
            files={"files": ("2026-01-01_访谈.txt", "合成人物：我喜欢先核对来源。".encode())},
            headers=HEADERS,
        )
        assert imported.status_code == 200, imported.text
        source = imported.json()["imported"][0]
        assert source["kind"] == "meeting" and source["n_target"] == 1
        assert client.get("/api/status").json()["counts"]["sources"] == 1
        assert client.delete(f"/api/persona/sources/{source['source_id']}", headers=HEADERS).status_code == 200

        body = {
            "kind": "chat_reply",
            "answer": {
                "reply": "先核对来源。",
                "confidence": 0.7,
                "abstain": False,
                "abstain_reason": "",
                "citations": [],
                "retrieved_ids": [],
            },
        }
        for api in ("script", "export", "audio"):
            response = client.post(f"/api/media/{api}", json=body, headers=HEADERS)
            assert response.status_code == 200, response.text
        audio = client.post("/api/media/audio", json=body, headers=HEADERS).json()
        for part in audio["segments"]:
            assert client.get(part["url"]).status_code == 200
