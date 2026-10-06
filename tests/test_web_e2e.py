from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.web import create_app
from twin.web.app import MAX_JSON_BYTES

TARGET = "本人"
ACCEPT = {"Accept": "application/json"}


class Browser:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        response = self.client.get(path, params=query or {})
        assert response.status_code == 200, response.text
        return response.json()

    def post(self, path: str, expected_status: int = 200, **request: Any) -> Any:
        response = self.client.post(path, headers={"X-Twin": "1"}, **request)
        assert response.status_code == expected_status, response.text
        return response.json()

    def wait(self, job_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            job = self.get(f"/api/jobs/{job_id}")
            if job["status"] in ("done", "failed"):
                return job
            time.sleep(0.01)
        raise AssertionError(job_id)

    def run(self, path: str, **request: Any) -> dict[str, Any]:
        job = self.wait(self.post(path, 202, **request)["job_id"])
        assert job["status"] == "done", job
        return job


def make_settings(path: Path) -> Settings:
    return Settings(target_name="本人", db_path=path / "data/twin.db", max_workers=2)


def make_browser(settings: Settings, handler: Any) -> Browser:
    return Browser(
        TestClient(
            create_app(settings, llm_factory=lambda: FakeLLM(handler), embedder_factory=HashingEmbedder),
            base_url="http://127.0.0.1",
        )
    )


PERSONA_QUESTIONNAIRE = """**4. 排序。**　*偏好 · 2.1*

回答：结果第一，钱进了账户才算数。

**33.【可跳过】爱好？**　*开放 · 9.1*

回答：
"""

PERSONA_CHAT = f"2026-09-01 10:02 李四：首付 10%\n2026-09-01 10:05 {TARGET}：说白了钱进了账户才叫收入\n"


def uploads(contents: dict[str, str | bytes]) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [
        ("files", (name, data.encode("utf-8") if isinstance(data, str) else data, "application/octet-stream"))
        for name, data in contents.items()
    ]


def persona_handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    from twin.persona import profile as pf
    from twin.persona.schema import ChatDraft

    if schema is pf.ExtractDraft:
        n = int(re.findall(r"\[(\d+)\]", user)[0])
        return {"items": [{"facet_id": "2.1", "statement": "他看重回款", "quotes": [{"n": n, "quote": "钱进了账户"}]}]}
    if schema is pf.MergeDraft:
        return {"items": [{"statement": "他认为回款第一", "candidate_ids": re.findall(r"\[(pc_[0-9a-f]+)\]", user)}]}
    if schema is ChatDraft:
        refs = re.findall(r"\[((?:pi_|src_)[^\]]+)\]", user)
        return {"reply": "钱到账才算。", "citations": refs, "confidence": 0.8, "abstain": False}
    raise AssertionError(schema)


def test_persona_pages(tmp_path: Path) -> None:
    browser = make_browser(make_settings(tmp_path), persona_handler)
    headers = {**ACCEPT, "X-Twin": "1"}
    assert browser.get("/api/persona/sources") == []
    error = browser.client.post("/api/persona/build", headers=headers)
    assert error.status_code == 400 and "还没有导入资料" in error.json()["detail"]

    imported = browser.post(
        "/api/persona/import",
        params={"kind": "questionnaire"},
        files=uploads({"问卷_2026-08-30.md": PERSONA_QUESTIONNAIRE, "bad.pptx": b"PK"}),
    )
    assert imported["imported"][0]["declined_facets"] == ["9.1"] and imported["skipped"][0]["file"] == "bad.pptx"
    browser.post("/api/persona/import", params={"kind": "chat"}, files=uploads({"群.txt": PERSONA_CHAT}))
    sources = browser.get("/api/persona/sources")
    assert [s["evidence_class"] for s in sources] == ["self_report", "behavior"]

    build = browser.run("/api/persona/build")["result"]
    assert build["items"] == 1 and build["failures"] == []
    coverage = browser.get("/api/persona/coverage", {"as_of": "2026-10-03"})
    money = next(f for f in coverage["facets"] if f["facet_id"] == "2.1")
    assert money["level"] == 2 and money["by_kind"] == {"questionnaire": 1, "chat": 1}

    messages = [{"role": "user", "content": "你看重什么？"}]
    chat = browser.run("/api/persona/chat", json={"messages": messages})["result"]
    assert chat["reply"] == "钱到账才算。" and {c["kind"] for c in chat["cited"]} == {"item", "expression"}
    bad = browser.client.post(
        "/api/persona/chat", headers=headers, json={"messages": [{"role": "twin", "content": "x"}]}
    )
    assert bad.status_code == 400

    item_id = browser.get("/api/persona/items")[0]["item_id"]

    def review(body: dict[str, Any], expected: int = 200) -> Any:
        response = browser.client.post(f"/api/persona/items/{item_id}/review", headers=headers, json=body)
        assert response.status_code == expected, response.text
        return response.json()

    confirmed = review({"status": "confirmed"})
    assert confirmed["review"] == "confirmed"
    edited = review({"status": "edited", "statement": "他只认到账的钱"})
    assert edited["statement"] == "他只认到账的钱" and edited["extracted_statement"] == "他认为回款第一"
    assert "必须给出新的表述" in review({"status": "edited", "statement": " "}, 400)["detail"]
    review({"status": "rejected"})
    assert browser.get("/api/persona/items") == []
    assert len(browser.get("/api/persona/items", {"include_rejected": "true"})) == 1
    assert review({"status": "unreviewed"})["review"] == "unreviewed"
    missing = browser.client.post("/api/persona/items/pi_x/review", headers=headers, json={"status": "confirmed"})
    assert missing.status_code == 404
    asked = next(f for f in browser.get("/api/persona/coverage")["facets"] if f["facet_id"] == "2.1")
    assert asked["confirmed"] == 0 and asked["asked"] == 0  # the fake chat tagged no topic

    deleted = browser.client.delete(f"/api/persona/sources/{sources[1]['source_id']}", headers=headers)
    assert deleted.status_code == 200 and len(browser.get("/api/persona/sources")) == 1


def test_questionnaire_page(tmp_path: Path) -> None:
    browser = make_browser(make_settings(tmp_path), persona_handler)
    headers = {**ACCEPT, "X-Twin": "1"}
    empty = browser.get("/api/persona/questionnaire", {"round": "initial"})
    assert empty["status"] == "empty" and len(empty["questions"]) == 20

    draft = browser.client.put(
        "/api/persona/questionnaire/draft",
        headers=headers,
        json={"round": "initial", "answers": {"q04": "结果第一，钱进了账户才算数。"}},
    )
    assert draft.status_code == 200 and draft.json()["answered"] == 1
    bad = browser.client.put("/api/persona/questionnaire/draft", headers=headers, json={"answers": {"q99": "x"}})
    assert bad.status_code == 400 and "q99" in bad.json()["detail"]

    answers = {"q04": "结果第一，钱进了账户才算数。", "q13": "首付多少？"}
    submitted = browser.post("/api/persona/questionnaire/submit", json={"round": "initial", "answers": answers})
    assert submitted["job_id"] and "正在构建" in submitted["notice"]
    assert browser.wait(submitted["job_id"])["status"] == "done"
    assert [s["kind"] for s in browser.get("/api/persona/sources")] == ["questionnaire"]
    assert browser.get("/api/persona/items")[0]["facet_id"] == "2.1"

    after = browser.get("/api/persona/questionnaire")
    assert after["status"] == "submitted" and "retest_from" not in after
    for endpoint in ("/api/persona/questionnaire/draft", "/api/persona/questionnaire/submit"):
        response = browser.client.request(
            "PUT" if endpoint.endswith("draft") else "POST",
            endpoint,
            headers=headers,
            json={"round": "retest", "answers": {}},
        )
        assert response.status_code == 400
    assert browser.client.get("/api/persona/questionnaire?round=retest").status_code == 400


def test_offline_browsing_import_and_media_api_contracts(tmp_path: Path) -> None:
    app = create_app(Settings(target_name="合成人物", db_path=tmp_path / "persona.db"))
    headers = {"X-Twin": "1"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for api in (
            "/api/status",
            "/api/jobs",
            "/api/persona/sources",
            "/api/persona/items",
            "/api/persona/coverage",
            "/api/persona/questionnaire",
            "/api/media/capabilities",
        ):
            assert client.get(api).status_code == 200, api
        assert client.get("/api/media/capabilities").json()["available"] is False
        assert client.post("/api/persona/build").status_code == 403
        assert client.post("/api/persona/chat", json={}, headers=headers).status_code == 400
        assert client.post("/api/persona/chat", content=b"x" * (MAX_JSON_BYTES + 1), headers=headers).status_code == 413
        assert client.get("/api/status", headers={"Host": "untrusted.invalid"}).status_code == 403

        imported = client.post(
            "/api/persona/import?kind=interview",
            files={"files": ("2026-01-01_访谈.txt", "合成人物：我喜欢先核对来源。".encode())},
            headers=headers,
        )
        assert imported.status_code == 200, imported.text
        source = imported.json()["imported"][0]
        assert source["kind"] == "interview" and source["n_target"] == 1
        assert client.get("/api/status").json()["counts"]["sources"] == 1
        assert client.delete(f"/api/persona/sources/{source['source_id']}", headers=headers).status_code == 200

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
            response = client.post(f"/api/media/{api}", json=body, headers=headers)
            assert response.status_code == 200, response.text
        audio = client.post("/api/media/audio", json=body, headers=headers).json()
        for part in audio["segments"]:
            assert client.get(part["url"]).status_code == 200
