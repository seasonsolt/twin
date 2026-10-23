"""A small team for the tests of the organisation's layer (team answers, finding who knows, delegation): a web app with
accounts, twins made for several people who have taken them, and colleagues who ask. Everything offline: a model that
answers as a plan says and an embedder that tells topics apart by keywords."""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import numpy as np
import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import Matrix
from twin.llm import FakeLLM
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.store import PersonaStore
from twin.teamdb import TeamDB
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
ADMIN = "admin@example.com"

# Words that make two texts the same matter for the test embedder, one direction each.
TOPICS: tuple[tuple[str, ...], ...] = (
    ("模板", "Word", "导出"),
    ("折扣", "续约", "批"),
    ("周报", "汇报"),
    ("排期", "脚本"),
    ("发布", "上线"),
)


class TopicEmbedder:
    """Texts about the same topic are alike (cosine 1), others are not (0): a direction per topic in ``TOPICS``, a
    hashed direction for the rest. Counts the texts it was asked to embed."""

    name = "topics:test"
    cluster_threshold = 0.8
    dim = len(TOPICS) + 16

    def __init__(self) -> None:
        self.calls = 0

    def embed(self, texts: list[str]) -> Matrix:
        self.calls += len(texts)
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            hit = False
            for column, words in enumerate(TOPICS):
                if any(word in text for word in words):
                    out[row, column] = 1.0
                    hit = True
            if not hit:
                out[row, len(TOPICS) + sum(map(ord, text)) % 16] = 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return (out / norms).astype(np.float32)


class Scripted(FakeLLM):
    """Answers each question as ``plan`` says (the first key found in the question): the reply text and the metadata of
    what it leaves; keeps everything a chat call was shown."""

    def __init__(self, plan: dict[str, dict[str, Any]] | None = None) -> None:
        super().__init__(self.handle)
        self.plan = plan or {}
        self.seen: list[str] = []
        self.systems: list[str] = []
        self.structured_calls: list[tuple[str, str, str]] = []
        self.verdicts: dict[str, Any] = {}

    def planned(self, user: str, system: str = "") -> dict[str, Any]:
        """The plan for the last thing said: a key ``名字|问题片段`` is for the twin that name is in the prompt of."""
        question = user.rsplit("对方：", 1)[-1]
        for key, plan in self.plan.items():
            who, _, fragment = key.rpartition("|")
            if fragment in question and (not who or who in system):
                return plan
        return {"reply": "好的。", "meta": {}}

    @staticmethod
    def meta(plan: dict[str, Any]) -> dict[str, Any]:
        return {"citations": [], "confidence": 0.9, "mode": "grounded", "asked": "事", "answered": True, **plan["meta"]}

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            self.structured_calls.append((schema.__name__, system, user))
            return dict(self.verdicts.get(schema.__name__, {}))
        plan = self.planned(user, system)
        self.seen.append(user)
        self.systems.append(system)
        return {"reply": plan["reply"], **self.meta(plan)}

    async def stream(self, **kwargs: Any) -> Any:
        plan = self.planned(kwargs["user"], kwargs["system"])
        self.seen.append(kwargs["user"])
        self.systems.append(kwargs["system"])
        text = plan["reply"]
        for start in range(0, len(text), 6):
            yield text[start : start + 6]
        yield "\n<<<META>>>\n" + json.dumps(self.meta(plan), ensure_ascii=False)


def item(
    item_id: str,
    facet: str,
    statement: str,
    *,
    day: str = "2026-09-01",
    sources: int = 2,
    own_words: bool = True,
    behavior: bool = False,
) -> PersonaItem:
    """An item standing on ``sources`` occasions, one a day from ``day``; on the person's own words, or only on what
    others said (``own_words`` False); ``behavior`` adds a piece of evidence of what they did."""
    import datetime as dt

    start = dt.date.fromisoformat(day)
    evidence = [
        PEvidence(
            expression_id=f"e_{item_id}_{n}#00000",
            source_id=f"s_{item_id}_{n}",
            source_kind=SourceKind.CHAT,
            evidence_class=EvidenceClass.BEHAVIOR if behavior and n == 0 else EvidenceClass.SELF_REPORT,
            date=start + dt.timedelta(days=n),
            quote=f"原话{statement}",
            own_words=own_words,
        )
        for n in range(sources)
    ]
    return PersonaItem(item_id=item_id, facet_id=facet, statement=statement, evidence=evidence)


@dataclass
class Twin:
    """A twin made for ``email`` (who may have taken it)."""

    persona: str
    email: str
    name: str
    path: Path
    headers: dict[str, str] = field(default_factory=dict)


@dataclass
class Team:
    web: TestClient
    llm: Scripted
    embedder: TopicEmbedder
    root: Path
    cookies: dict[str, str] = field(default_factory=dict)
    twins: dict[str, Twin] = field(default_factory=dict)

    def login(self, email: str) -> str:
        if email in self.cookies:
            return self.cookies[email]
        self.web.cookies.clear()
        self.web.post("/api/auth/request", json={"email": email}, headers=CSRF)
        code = str(self.web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
        assert self.web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200
        self.cookies[email] = str(self.web.cookies["twin_session"])
        return self.cookies[email]

    def as_(self, email: str) -> None:
        self.web.cookies.set("twin_session", self.login(email))

    @property
    def team(self) -> TeamDB:
        return self.web.app.state.team  # type: ignore[no-any-return,attr-defined]

    def add_twin(
        self,
        key: str,
        email: str,
        name: str,
        *,
        items: list[PersonaItem] | None = None,
        public: bool = True,
        take: bool = True,
    ) -> Twin:
        """A twin for ``email``, called ``name``, holding ``items``; taken by them and opened to colleagues unless
        said not to be."""
        self.as_(ADMIN)
        made = self.web.post("/api/personas", json={"name": name}, headers=CSRF)
        assert made.status_code == 201, made.text
        persona = made.json()["id"]
        path = self.root / "personas" / persona / "twin.db"
        # A twin that holds nothing does not answer; every twin here has at least one memory.
        held = items if items is not None else [item(f"pi_{key}", "2.1", f"{name}看重按时交付")]
        with PersonaStore(path) as store:
            store.set_meta("built_at", "2026-01-01")
            for facet in sorted({i.facet_id for i in held}):
                store.replace_facet_items(facet, [i for i in held if i.facet_id == facet])
        twin = Twin(persona, email, name, path, {**CSRF, "X-Twin-Persona": persona})
        self.twins[key] = twin
        self.login(email)
        if take:
            self.as_(ADMIN)
            claim = self.web.put(f"/api/personas/{persona}/claim", json={"claim": email}, headers=CSRF)
            assert claim.status_code == 200, claim.text
            self.as_(email)
            self.web.get("/api/personas")  # they take it
            approved = self.web.post(f"/api/personas/{persona}/approve", json={"public": public}, headers=CSRF)
            assert approved.status_code == 200, approved.text
        elif public:
            self.as_(ADMIN)
            assert self.web.patch(f"/api/personas/{persona}", json={"public": True}, headers=CSRF).status_code == 200
        return twin

    def index_items(self, twin: Twin) -> None:
        """Embed a twin's items the way a build does, so that retrieval and the finder can see them."""
        from twin.persona.chat import index_persona

        settings = Settings(db_path=twin.path)
        with PersonaStore(twin.path) as store:
            index_persona(store, self.embedder, settings)

    def conversation(self, who: str, twin: Twin) -> str:
        self.as_(who)
        created = self.web.post("/api/conversations", json={}, headers=twin.headers)
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    def stream(
        self, who: str, twin: Twin, conversation: str, messages: list[dict[str, str]], *, preview: bool = False
    ) -> dict[str, Any]:
        self.as_(who)
        body: dict[str, Any] = {"messages": messages, "conversation_id": conversation}
        if preview:
            body["preview"] = True
        response = self.web.post("/api/persona/chat/stream", json=body, headers=twin.headers)
        assert response.status_code == 200 and "event: final" in response.text, response.text
        final = response.text.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0]
        return json.loads(final)  # type: ignore[no-any-return]

    def ask(self, who: str, twin: Twin, *questions: str, conversation: str | None = None) -> tuple[str, dict[str, Any]]:
        """``who`` asks ``twin`` (in a conversation of their own, opened if not given); its id and the final reply."""
        cid = conversation or self.conversation(who, twin)
        sent: list[dict[str, str]] = []
        final: dict[str, Any] = {}
        for question in questions:
            sent.append({"role": "user", "content": question})
            final = self.stream(who, twin, cid, sent)
            sent.append({"role": "twin", "content": final["reply"]})
        return cid, final

    def turns(self, who: str, twin: Twin, conversation: str) -> list[dict[str, Any]]:
        self.as_(who)
        opened = self.web.get(f"/api/conversations/{conversation}", headers=twin.headers)
        assert opened.status_code == 200, opened.text
        return opened.json()["turns"]  # type: ignore[no-any-return]

    def page(self, twin: Twin) -> dict[str, Any]:
        self.as_(twin.email)
        response = self.web.get("/api/persona/handoffs", headers=twin.headers)
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]

    def sources(self, twin: Twin) -> list[str]:
        with PersonaStore(twin.path) as store:
            return [s.title for s in store.list_sources()]


def make_web(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan: dict[str, dict[str, Any]] | None = None,
    configure: Callable[[Settings], Settings] | None = None,
) -> Iterator[Team]:
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
    if configure:
        settings = configure(settings)
    llm, embedder = Scripted(plan), TopicEmbedder()
    app = create_app(settings, llm_factory=lambda: llm, embedder_factory=lambda: embedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        yield Team(client, llm, embedder, tmp_path)


def final_of(text: str) -> dict[str, Any]:
    """The ``final`` event of a streamed reply."""
    match = re.search(r"event: final\ndata: (.*)\n\n", text)
    assert match is not None, text
    return json.loads(match.group(1))  # type: ignore[no-any-return]
