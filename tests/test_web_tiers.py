"""Two tiers of memory through the web: who a conversation answers for is fixed when it is created, and what the
person keeps to themself never reaches a colleague's or a manager's model input, answer or evidence."""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.store import PersonaStore
from twin.teamdb import TeamDB
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
ADMIN = "admin@example.com"
PERSON = "person@xjjk.com"  # the person the twin is made for
VISITOR = "visitor@xjjk.com"
WORK = "ALPHA-WORK-1f"
FAMILY = "SECRET-FAMILY-9a"
QUESTION = "家里和回款是怎么看的？"


def item(item_id: str, facet: str, marker: str) -> PersonaItem:
    return PersonaItem(
        item_id=item_id,
        facet_id=facet,
        statement=f"他说起过{marker}",
        evidence=[
            PEvidence(
                expression_id=f"e_{item_id}",
                source_id="s1",
                source_kind=SourceKind.CHAT,
                evidence_class=EvidenceClass.SELF_REPORT,
                quote=f"原话{marker}",
            )
        ],
    )


def seed(path: Path) -> None:
    with PersonaStore(path) as store:
        store.set_meta("built_at", "2026-01-01")
        store.replace_facet_items("2.1", [item("pi_work", "2.1", WORK)])
        store.replace_facet_items("9.3", [item("pi_family", "9.3", FAMILY)])


class Recorder(FakeLLM):
    """Cites every record id in what it is shown, and keeps everything a chat call was shown."""

    def __init__(self) -> None:
        super().__init__(self.handle)
        self.seen: list[str] = []

    @staticmethod
    def meta(text: str) -> dict[str, Any]:
        cited = sorted(set(re.findall(r"\[(pi_[a-z]+)\]", text)))
        return {"citations": cited, "confidence": 0.9, "mode": "grounded", "asked": "家人", "answered": True}

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            return {}
        self.seen += [system, user]
        return {"reply": "我回答了。", **self.meta(system + user)}

    async def stream(self, **kwargs: Any) -> Any:
        self.seen += [kwargs["system"], kwargs["user"]]
        yield "我回答了。\n<<<META>>>\n" + json.dumps(self.meta(kwargs["system"] + kwargs["user"]), ensure_ascii=False)


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Recorder]]:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    sender = MagicMock()
    monkeypatch.setattr("twin.web.auth.send_code", sender)
    settings = Settings(
        db_path=tmp_path / "twin.db",
        auth=AuthSettings(
            enabled=True,
            allowed_emails=[ADMIN],
            admin_emails=[ADMIN],
            smtp=SMTPSettings(host="smtp.example.com", username="test", from_address="t@example.com"),
        ),
    )
    recorder = Recorder()
    app = create_app(settings, llm_factory=lambda: recorder, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        yield client, recorder


def login(web: TestClient, email: str) -> str:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200
    return str(web.cookies["twin_session"])


def team(web: TestClient) -> TeamDB:
    return web.app.state.team  # type: ignore[no-any-return,attr-defined]


class Scene:
    """A public twin made by ``PERSON`` for themself; they have not taken it until ``take``."""

    def __init__(self, web: TestClient, recorder: Recorder, root: Path) -> None:
        self.web, self.recorder = web, recorder
        self.cookies = {"person": login(web, PERSON)}
        self.persona = web.post("/api/personas", json={"name": "测试分身"}, headers=CSRF).json()["id"]
        seed(root / "personas" / self.persona / "twin.db")
        self.headers = {**CSRF, "X-Twin-Persona": self.persona}
        self.cookies["visitor"] = login(web, VISITOR)
        self.cookies["admin"] = login(web, ADMIN)
        self.as_("person")
        assert web.patch(f"/api/personas/{self.persona}", json={"public": True}, headers=CSRF).status_code == 200

    def as_(self, who: str) -> None:
        self.web.cookies.set("twin_session", self.cookies[who])

    def take(self) -> None:
        """The person takes the twin and says it is all right."""
        self.as_("person")
        claim = self.web.put(f"/api/personas/{self.persona}/claim", json={"claim": PERSON}, headers=CSRF)
        assert claim.status_code == 200, claim.text
        assert [p["mine"] for p in self.web.get("/api/personas").json()] == [True]
        approved = self.web.post(f"/api/personas/{self.persona}/approve", json={"public": True}, headers=CSRF)
        assert approved.status_code == 200, approved.text

    def conversation(self) -> str:
        created = self.web.post("/api/conversations", json={}, headers=self.headers)
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    def ask(self, conversation_id: str | None) -> dict[str, Any]:
        body = {"messages": [{"role": "user", "content": QUESTION}], "conversation_id": conversation_id}
        response = self.web.post("/api/persona/chat/stream", json=body, headers=self.headers)
        assert response.status_code == 200 and "event: final" in response.text, response.text
        final = response.text.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0]
        return json.loads(final)  # type: ignore[no-any-return]

    def shown(self) -> str:
        return "\n".join(self.recorder.seen)


@pytest.fixture
def scene(web: tuple[TestClient, Recorder], tmp_path: Path) -> Scene:
    return Scene(*web, tmp_path)


def test_a_conversation_is_indexed_with_the_tier_it_was_created_for(scene: Scene) -> None:
    web = scene.web
    scene.as_("person")
    before_taking = scene.conversation()  # not theirs yet: they made it, and manage it
    scene.take()
    mine = scene.conversation()
    scene.as_("visitor")
    visited = scene.conversation()
    scene.as_("admin")
    managed = scene.conversation()
    index = team(web)
    assert [index.audience_of(c) for c in (before_taking, mine, visited, managed)] == [
        "colleague",
        "self",
        "colleague",
        "colleague",
    ]
    rows = {c.id: c for c in index.conversations()}
    assert rows[mine].persona_id == scene.persona and rows[mine].asker == PERSON and rows[mine].via == "direct"
    assert rows[visited].asker == VISITOR and rows[managed].asker == ADMIN
    # Asking, renaming and deleting are followed by the index.
    scene.as_("visitor")
    answer = scene.ask(visited)
    assert answer["reply"] == "我回答了。"
    assert index.conversations(asker=VISITOR)[0].title == QUESTION[:24]
    assert (
        web.patch(f"/api/conversations/{visited}", json={"title": "改过的"}, headers=scene.headers).status_code == 200
    )
    assert index.conversations(asker=VISITOR)[0].title == "改过的"
    assert web.delete(f"/api/conversations/{visited}", headers=scene.headers).status_code == 200
    assert index.conversations(asker=VISITOR) == []
    assert index.audience_of(visited) == "colleague"  # a deleted conversation is marked, not forgotten


def test_a_colleague_a_manager_and_the_untaken_twin_never_see_what_the_person_keeps_to_themself(scene: Scene) -> None:
    scene.take()
    for who in ("visitor", "admin"):
        scene.as_(who)
        scene.recorder.seen.clear()
        conversation = scene.conversation()
        final = scene.ask(conversation)
        assert FAMILY not in scene.shown() and "pi_family" not in scene.shown(), who
        assert WORK in scene.shown() and "pi_work" in final["citations"], who
        assert "pi_family" not in final["retrieved_ids"] + final["citations"], who
        assert [c["id"] for c in final["cited"]] == ["pi_work"], who
        saved = scene.web.get(f"/api/conversations/{conversation}", headers=scene.headers).json()
        assert FAMILY not in json.dumps(saved, ensure_ascii=False), who
    scene.as_("person")
    scene.recorder.seen.clear()
    final = scene.ask(scene.conversation())
    assert FAMILY in scene.shown() and sorted(final["citations"]) == ["pi_family", "pi_work"]
    assert {c["id"] for c in final["cited"]} == {"pi_family", "pi_work"}


def test_before_the_person_takes_their_twin_nobody_gets_the_private_tier(scene: Scene) -> None:
    scene.as_("person")  # made it, has not taken it: a manager like any other
    final = scene.ask(scene.conversation())
    assert FAMILY not in scene.shown() and "pi_family" not in final["retrieved_ids"]


def test_the_persons_tier_cannot_be_lifted_by_a_conversation_from_before_or_after_giving_the_twin_back(
    scene: Scene, tmp_path: Path
) -> None:
    scene.take()
    scene.as_("person")
    mine = scene.conversation()
    assert team(scene.web).audience_of(mine) == "self"
    assert FAMILY in json.dumps(scene.ask(mine), ensure_ascii=False)
    # The twin no longer says it is theirs (back to whoever made it): the conversation keeps its tier on record, but
    # answers from no more than the asker may have now.
    registry = scene.web.app.state.personas  # type: ignore[attr-defined]
    entry = registry.entry(scene.persona)
    for key in ("member", "approved_at"):
        entry.pop(key)
    scene.recorder.seen.clear()
    final = scene.ask(mine)
    assert FAMILY not in scene.shown() and "pi_family" not in final["retrieved_ids"]
    # A conversation the index does not know (the write failed, or it came before the index) is a colleague's.
    entry["member"], entry["approved_at"] = PERSON, "2026-01-01T00:00:00+00:00"
    with PersonaStore(tmp_path / "personas" / scene.persona / "twin.db") as store:
        orphan = store.create_conversation(PERSON)
    assert team(scene.web).audience_of(orphan) is None
    scene.recorder.seen.clear()
    final = scene.ask(orphan)
    assert FAMILY not in scene.shown() and "pi_family" not in final["retrieved_ids"]


def test_old_conversations_are_indexed_at_startup_as_colleague_tier_and_open_as_before(
    scene: Scene, tmp_path: Path
) -> None:
    scene.take()
    with PersonaStore(tmp_path / "personas" / scene.persona / "twin.db") as store:
        old = store.create_conversation(PERSON, [{"role": "user", "content": "以前问过", "timestamp": "2026-01-01"}])
    settings = scene.web.app.state.personas.settings  # type: ignore[attr-defined]
    with TeamDB(tmp_path / "team" / "team.db") as index:
        assert index.audience_of(old) is None
    app = create_app(settings, llm_factory=lambda: scene.recorder, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as again:
        assert again.app.state.team.audience_of(old) == "colleague"  # type: ignore[attr-defined]
        again.cookies.set("twin_session", scene.cookies["person"])
        opened = again.get(f"/api/conversations/{old}", headers=scene.headers)
        assert opened.status_code == 200 and opened.json()["turns"][0]["content"] == "以前问过"
        assert [c["id"] for c in again.get("/api/conversations", headers=scene.headers).json()] == [old]


def test_the_person_alone_can_change_a_tier_and_sees_it_in_their_memory(scene: Scene) -> None:
    web = scene.web
    scene.take()
    scene.as_("person")
    listed = web.get("/api/persona/items", headers=scene.headers).json()
    tiers = {i["item_id"]: (i["tier"], i["tier_changed"]) for i in listed["items"]}
    assert tiers == {"pi_work": ("colleague", False), "pi_family": ("self", False)}
    changed = web.put("/api/persona/items/pi_family/tier", json={"tier": "colleague"}, headers=scene.headers)
    assert changed.status_code == 200 and changed.json()["tier"] == "colleague" and changed.json()["tier_changed"]
    scene.as_("visitor")
    scene.recorder.seen.clear()
    scene.ask(None)
    assert FAMILY in scene.shown()  # opened by the person
    scene.as_("person")
    assert (
        web.put("/api/persona/items/pi_family/tier", json={"tier": None}, headers=scene.headers).json()["tier"]
        == "self"
    )
    assert web.put("/api/persona/items/pi_family/tier", json={"tier": "all"}, headers=scene.headers).status_code == 400
    assert web.put("/api/persona/items/pi_nope/tier", json={"tier": "self"}, headers=scene.headers).status_code == 404
    # The memory the person sees is all of it; a manager sees the colleague tier only, and cannot change anything.
    assert web.get("/api/persona/items/summary", headers=scene.headers).json()["total"] == 2
    coverage = web.get("/api/persona/coverage", headers=scene.headers).json()
    assert {f["facet_id"]: f["items"] for f in coverage["facets"] if f["items"]} == {"2.1": 1, "9.3": 1}
    scene.as_("admin")
    summary = web.get("/api/persona/items/summary", headers=scene.headers).json()
    assert summary["total"] == 1 and [d["dimension_id"] for d in summary["dimensions"]] == ["D2"]
    assert [i["item_id"] for i in web.get("/api/persona/items", headers=scene.headers).json()["items"]] == ["pi_work"]
    assert web.get("/api/persona/items/search?q=SECRET-FAMILY-9a", headers=scene.headers).json()["items"] == []
    coverage = web.get("/api/persona/coverage", headers=scene.headers).json()
    assert {f["facet_id"]: f["items"] for f in coverage["facets"] if f["items"]} == {"2.1": 1}
    for path, payload in (
        ("/api/persona/items/pi_family/tier", {"tier": "colleague"}),
        ("/api/persona/items/pi_work/tier", {"tier": "self"}),
    ):
        assert web.put(path, json=payload, headers=scene.headers).status_code == 403
    review = {"status": "rejected", "statement": None, "note": ""}
    assert web.post("/api/persona/items/pi_family/review", json=review, headers=scene.headers).status_code == 404
    assert FAMILY not in web.get("/api/persona/items?q=原话", headers=scene.headers).text


def test_the_job_path_answers_a_manager_from_the_colleague_tier_too(scene: Scene) -> None:
    scene.take()
    scene.as_("admin")
    conversation = scene.conversation()
    body = {"messages": [{"role": "user", "content": QUESTION}], "conversation_id": conversation}
    started = scene.web.post("/api/persona/chat", json=body, headers=scene.headers)
    assert started.status_code == 202, started.text
    for _ in range(200):
        snapshot = scene.web.get(f"/api/jobs/{started.json()['job_id']}", headers=scene.headers).json()
        if snapshot["status"] == "done":
            break
        time.sleep(0.01)
    result = snapshot["result"]
    assert FAMILY not in scene.shown() and "pi_family" not in result["retrieved_ids"] + result["citations"]
    assert [c["id"] for c in result["cited"]] == ["pi_work"]
