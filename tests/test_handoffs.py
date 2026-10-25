"""Handoffs: what a twin's answer leaves to the person, and the person's reply written back to the asker.

A colleague asks a twin for a promise; the twin answers what it can and says in its metadata what it left to the
person. One handoff is made per asker and conversation, the person settles it from their page, and their reply lands in
the asker's own conversation, once, as the person's turn."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import HashingEmbedder
from twin.handoffs import HandoffDesk, HandoffRefused, ledger_id_for, run_all
from twin.llm import FakeLLM, LLMError
from twin.persona.chat import PersonaChat
from twin.persona.followups import followup_id
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import ChatReply, ChatTurn, EvidenceClass, SourceKind
from twin.persona.store import PersonaStore
from twin.teamdb import HandoffUnavailable, TeamDB
from twin.web import create_app
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
ADMIN = "admin@example.com"
PERSON = "person@xjjk.com"  # the person the twin is made for
ASKERS = {"shen": "shen@xjjk.com", "xu": "xu@xjjk.com", "wang": "wang@xjjk.com"}
PROMISE = "周五前给我一版发布方案"
DECISION = "大文件导入这次上不上？"
GUESS = "要是发布延期一周，你能接受吗？"
FACT = "发布定在哪天？"
QUOTED = "你答应的话：「他说过周五一定交」对吗？"
HOLD = "这周值班表的事你看着办吧"  # no word that is a cue by itself: only the rewrite sees what it asks for
COMMON = "你答应过团队的那个功能进展到哪了"  # has a cue word, but asks how a thing stands, not for a promise


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


class Scripted(FakeLLM):
    """Answers each question as the script says: the reply text and the metadata about what it leaves the person.
    Keeps everything a chat call was shown."""

    PLAN: ClassVar[dict[str, dict[str, Any]]] = {
        PROMISE: {
            "reply": "这个我先看看安排，回头给你准话。",
            "cue": True,
            "meta": {
                "owner_part": "commit",
                "owner_ask": "周五前给一版发布方案",
                "commit_what": "周五前给沈从一版发布方案",
                "commit_due": (dt.date.today() + dt.timedelta(days=3)).isoformat(),
            },
        },
        DECISION: {
            "reply": "发布定在周二。大文件导入再说。",
            "meta": {"owner_part": "decide", "owner_ask": "大文件导入这次上不上", "mode": "grounded"},
        },
        GUESS: {"reply": "能接受。", "meta": {"mode": "inferred", "citations": ["pi_work"]}},
        FACT: {"reply": "发布定在周二。", "meta": {"mode": "grounded", "citations": ["pi_work"]}},
        QUOTED: {
            "reply": "他说「周五一定交的事我没说过」，所以我先不答应。",
            "cue": True,
            "meta": {"owner_part": "commit"},
        },
        HOLD: {
            "reply": "值班表在群公告里，这周三之前会更新。",
            "cue": True,
            "meta": {"owner_part": "decide", "owner_ask": "这周谁值班"},
        },
        COMMON: {"reply": "那个功能已经做完七成，下周开始联调。", "meta": {}},
    }

    def __init__(self) -> None:
        super().__init__(self.handle)
        self.seen: list[str] = []
        self.systems: list[str] = []
        self.drafts: list[tuple[str, str]] = []
        # The retrieval rewrite fails (the model is down); the cue words decide what it would have.
        self.rewrite_fails = False

    def plan(self, user: str) -> dict[str, Any]:
        question = user.rsplit("对方：", 1)[-1]
        for key, plan in self.PLAN.items():
            if key in question:
                return plan
        return {"reply": "好的。", "meta": {}}

    def meta(self, plan: dict[str, Any]) -> dict[str, Any]:
        return {"citations": [], "confidence": 0.9, "mode": "grounded", "asked": "事", "answered": True, **plan["meta"]}

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ == "Drafted":
            self.drafts.append((system, user))
            return {"reply": "方案周五前给你。【请你定：大文件导入这次上不上】"}
        if schema.__name__ == "DraftedForMany":
            self.drafts.append((system, user))
            return {"question": "  大文件导入这次上不上？ ", "reply": "这次先不上，下个版本再说。"}
        if schema.__name__ == "Aspects":
            if self.rewrite_fails:
                raise LLMError("rewrite is down")
            return {"owner_cue": bool(self.plan(user).get("cue"))}
        if schema.__name__ != "ChatDraft":
            return {}
        plan = self.plan(user)
        self.seen.append(user)
        self.systems.append(system)
        return {"reply": plan["reply"], **self.meta(plan)}

    async def stream(self, **kwargs: Any) -> Any:
        plan = self.plan(kwargs["user"])
        self.seen.append(kwargs["user"])
        self.systems.append(kwargs["system"])
        text = plan["reply"]
        for start in range(0, len(text), 4):
            yield text[start : start + 4]
        yield "\n<<<META>>>\n" + json.dumps(self.meta(plan), ensure_ascii=False)


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Scripted]]:
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
    llm = Scripted()
    app = create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        yield client, llm


def login(web: TestClient, email: str) -> str:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200
    return str(web.cookies["twin_session"])


class Scene:
    """A public twin made for ``PERSON``, who has taken it; colleagues ask it and the person answers."""

    def __init__(self, web: TestClient, llm: Scripted, root: Path, *, take: bool = True) -> None:
        self.web, self.llm, self.root = web, llm, root
        self.cookies = {"person": login(web, PERSON)}
        self.persona = web.post("/api/personas", json={"name": "测试分身"}, headers=CSRF).json()["id"]
        self.path = root / "personas" / self.persona / "twin.db"
        with PersonaStore(self.path) as store:
            store.set_meta("built_at", "2026-01-01")
            store.replace_facet_items("2.1", [item("pi_work", "2.1", "发布")])
        self.headers = {**CSRF, "X-Twin-Persona": self.persona}
        for who, email in ASKERS.items():
            self.cookies[who] = login(web, email)
        self.cookies["admin"] = login(web, ADMIN)
        self.as_("person")
        assert web.patch(f"/api/personas/{self.persona}", json={"public": True}, headers=CSRF).status_code == 200
        if take:
            self.take()

    def as_(self, who: str) -> None:
        self.web.cookies.set("twin_session", self.cookies[who])

    def take(self) -> None:
        self.as_("person")
        claim = self.web.put(f"/api/personas/{self.persona}/claim", json={"claim": PERSON}, headers=CSRF)
        assert claim.status_code == 200, claim.text
        self.web.get("/api/personas")
        approved = self.web.post(f"/api/personas/{self.persona}/approve", json={"public": True}, headers=CSRF)
        assert approved.status_code == 200, approved.text

    @property
    def team(self) -> TeamDB:
        return self.web.app.state.team  # type: ignore[no-any-return,attr-defined]

    def conversation(self) -> str:
        created = self.web.post("/api/conversations", json={}, headers=self.headers)
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    def ask(self, conversation_id: str, *questions: str, history: list[dict[str, str]] | None = None) -> dict[str, Any]:
        """Ask in a conversation (several questions put the earlier ones in the history); the twin's final reply."""
        final: dict[str, Any] = {}
        sent = list(history or [])
        for question in questions:
            sent.append({"role": "user", "content": question})
            final = self.stream(conversation_id, sent)
            sent.append({"role": "twin", "content": final["reply"]})
        return final

    def stream(self, conversation_id: str, messages: list[dict[str, str]]) -> dict[str, Any]:
        body = {"messages": messages, "conversation_id": conversation_id}
        response = self.web.post("/api/persona/chat/stream", json=body, headers=self.headers)
        assert response.status_code == 200 and "event: final" in response.text, response.text
        final = response.text.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0]
        return json.loads(final)  # type: ignore[no-any-return]

    def deltas(self, conversation_id: str, question: str) -> tuple[list[str], dict[str, Any]]:
        body = {"messages": [{"role": "user", "content": question}], "conversation_id": conversation_id}
        text = self.web.post("/api/persona/chat/stream", json=body, headers=self.headers).text
        events = [e for e in text.split("\n\n") if e.startswith("event: ")]
        deltas = [json.loads(e.split("data: ", 1)[1])["text"] for e in events if e.startswith("event: delta")]
        final = next(json.loads(e.split("data: ", 1)[1]) for e in events if e.startswith("event: final"))
        return deltas, final

    def asked(self, who: str, *questions: str) -> tuple[str, dict[str, Any]]:
        """``who`` opens a conversation and asks; its id and the twin's final reply."""
        self.as_(who)
        conversation = self.conversation()
        return conversation, self.ask(conversation, *questions)

    def page(self) -> dict[str, Any]:
        self.as_("person")
        response = self.web.get("/api/persona/handoffs", headers=self.headers)
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]

    def reply(self, handoff_id: str, text: str, **body: Any) -> Any:
        self.as_("person")
        return self.web.post(
            f"/api/persona/handoffs/{handoff_id}/reply", json={"text": text, **body}, headers=self.headers
        )

    def post(self, handoff_id: str, action: str, **body: Any) -> Any:
        self.as_("person")
        return self.web.post(f"/api/persona/handoffs/{handoff_id}/{action}", json=body, headers=self.headers)

    def turns(self, who: str, conversation_id: str) -> list[dict[str, Any]]:
        self.as_(who)
        opened = self.web.get(f"/api/conversations/{conversation_id}", headers=self.headers)
        assert opened.status_code == 200, opened.text
        return opened.json()["turns"]  # type: ignore[no-any-return]

    def own(self, conversation_id: str) -> list[str]:
        """What the person said in a conversation, read straight from the twin's database."""
        with PersonaStore(self.path) as store:
            return store.owner_replies(conversation_id, store.conversation_head(conversation_id)[0])  # type: ignore[index]

    def desk(self, owner: str | None = PERSON) -> HandoffDesk:
        return HandoffDesk(
            self.team, self.persona, store_path=lambda: self.path, owner=lambda: owner, name=lambda: "测试分身"
        )

    def sources(self) -> list[str]:
        with PersonaStore(self.path) as store:
            return [s.title for s in store.list_sources()]


@pytest.fixture
def scene(web: tuple[TestClient, Scripted], tmp_path: Path) -> Scene:
    return Scene(*web, tmp_path)


# ------------------------------------------------------------------ making a handoff


def test_a_promise_asked_of_the_twin_is_handed_to_the_person_and_waits_as_a_commitment_to_take(scene: Scene) -> None:
    conversation, final = scene.asked("shen", PROMISE)
    assert final["owner_part"] == "commit" and final["commit_what"] == "周五前给沈从一版发布方案"
    assert final["handoff"]["status"] == "delivered" and final["handoff"]["owner_name"] == "测试分身"
    [made] = scene.team.handoffs(persona_id=scene.persona)
    assert (made.kind, made.status, made.owner, made.asker, made.conversation_id) == (
        "commit",
        "delivered",
        PERSON,
        ASKERS["shen"],
        conversation,
    )
    assert made.question == PROMISE and made.group_key == followup_id(PROMISE)
    # The asker reads where it stands under the twin's answer.
    twin_turn = next(t for t in scene.turns("shen", conversation) if t["role"] == "twin")
    assert twin_turn["handoff"]["id"] == made.id and twin_turn["handoff"]["status_label"] == "已送达"
    # The person sees it with what the twin said, and the promise waits as one they have not taken.
    page = scene.page()
    [row] = page["waiting"]
    assert row["id"] == made.id and row["asker_name"] == "shen" and row["answer"] == final["reply"]
    assert row["commit"]["what"] == "周五前给沈从一版发布方案" and row["commit"]["pending"]
    with PersonaStore(scene.path) as store:
        entry = store.get_ledger_entry(ledger_id_for(made.id))
    assert entry is not None and entry.status == "pending_accept" and entry.origin == "conversation"
    assert entry.handoff_id == made.id and entry.counterpart == "shen" and entry.owner == "本人"
    scene.as_("person")
    assert scene.web.get("/api/persona/handoffs/count", headers=scene.headers).json() == {"pending": 1}
    ledger = scene.web.get("/api/persona/ledger", headers=scene.headers).json()
    assert [(e["current_status"], e["current_status_label"]) for e in ledger["entries"]] == [
        ("pending_accept", "待你接受")
    ]


def test_the_job_path_of_a_manager_hands_over_too(scene: Scene) -> None:
    scene.as_("admin")
    conversation = scene.conversation()
    body = {"messages": [{"role": "user", "content": PROMISE}], "conversation_id": conversation}
    started = scene.web.post("/api/persona/chat", json=body, headers=scene.headers)
    assert started.status_code == 202, started.text
    for _ in range(300):
        snapshot = scene.web.get(f"/api/jobs/{started.json()['job_id']}", headers=scene.headers).json()
        if snapshot["status"] == "done":
            break
        time.sleep(0.01)
    result = snapshot["result"]
    assert result["owner_part"] == "commit" and result["handoff"]["status"] == "delivered"
    [made] = scene.team.handoffs(persona_id=scene.persona)
    assert made.conversation_id == conversation and made.kind == "commit"


def test_a_mixed_answer_counts_and_so_does_an_answer_that_did_not_abstain(scene: Scene) -> None:
    # It answered (grounded, not an abstention) and left the decision: judged on the answer, not derived from abstain.
    _, final = scene.asked("xu", DECISION)
    assert final["abstain"] is False and final["owner_part"] == "decide"
    [made] = scene.team.handoffs(persona_id=scene.persona)
    assert made.kind == "decide" and made.ask == "大文件导入这次上不上"
    # An answer that leaves nothing makes none.
    _, plain = scene.asked("xu", FACT)
    assert plain["owner_part"] == "none" and "handoff" not in plain
    # The twin knows whom it is talking with, by the name they signed in with.
    assert "## 和我聊的人\n对方是xu。" in scene.llm.systems[-1]
    assert len(scene.team.handoffs(persona_id=scene.persona)) == 1


def test_a_twin_nobody_has_taken_hands_nothing_over_and_says_to_ask_the_person(
    web: tuple[TestClient, Scripted], tmp_path: Path
) -> None:
    scene = Scene(*web, tmp_path, take=False)
    _, final = scene.asked("shen", PROMISE)
    assert "请直接联系本人" in final["reply"] and final["owner_part"] == "none" and "handoff" not in final
    assert scene.team.handoffs(persona_id=scene.persona) == []
    assert "还没认领这个分身" in scene.llm.systems[-1] and "## 转交" not in scene.llm.systems[-1]
    # Once the person takes it, the same question is handed over.
    scene.take()
    scene.llm.systems.clear()
    _, taken = scene.asked("shen", PROMISE)
    assert taken["handoff"]["status"] == "delivered" and "## 转交" in scene.llm.systems[-1]


def test_the_person_trying_their_twin_before_saying_it_is_all_right_is_handed_nothing(
    web: tuple[TestClient, Scripted], tmp_path: Path
) -> None:
    scene = Scene(*web, tmp_path, take=False)
    scene.as_("person")
    assert (
        scene.web.put(f"/api/personas/{scene.persona}/claim", json={"claim": PERSON}, headers=CSRF).status_code == 200
    )
    scene.web.get("/api/personas")  # they take it
    conversation = scene.conversation()
    final = scene.ask(conversation, PROMISE)
    assert final["owner_part"] == "none" and "handoff" not in final
    assert scene.team.handoffs(persona_id=scene.persona) == []
    assert "## 转交" not in scene.llm.systems[-1] and "还没认领" not in scene.llm.systems[-1]
    # The twin knows it is the person themself it is talking with.
    assert "## 和我聊的人\n对方就是" in scene.llm.systems[-1]


def test_the_person_asking_their_own_twin_is_handed_nothing(scene: Scene) -> None:
    conversation, final = scene.asked("person", PROMISE)
    assert final["owner_part"] == "none" and scene.team.handoffs(persona_id=scene.persona) == []
    assert "## 转交" not in scene.llm.systems[-1]
    del conversation


# ------------------------------------------------------------------ the person's reply


def test_the_reply_lands_in_each_askers_own_conversation_once_whoever_else_asked_the_same(scene: Scene) -> None:
    shen, _ = scene.asked("shen", DECISION)
    # The same question from another person, after different things were said: its own handoff and its own context.
    xu, _ = scene.asked("xu", "上周的评审怎么样？", DECISION)
    wang, _ = scene.asked("wang", DECISION)
    handoffs = {h.asker: h for h in scene.team.handoffs(persona_id=scene.persona)}
    assert set(handoffs) == set(ASKERS.values()) and len({h.id for h in handoffs.values()}) == 3
    assert handoffs[ASKERS["xu"]].context == "上周的评审怎么样？" and handoffs[ASKERS["shen"]].context == ""
    assert len(scene.page()["waiting"]) == 3

    sent = scene.reply(handoffs[ASKERS["xu"]].id, "这次不上，下个版本再说。")
    assert sent.status_code == 200, sent.text
    assert sent.json()["handoff"]["status"] == "replied" and sent.json()["pending"] == 2
    # Only xu's conversation has it, as the person's own turn, marked with the handoff.
    assert scene.own(xu) == ["这次不上，下个版本再说。"]
    assert scene.own(shen) == [] and scene.own(wang) == []
    turns = scene.turns("xu", xu)
    mine = [t for t in turns if t["role"] == "self"]
    assert [t["content"] for t in mine] == ["这次不上，下个版本再说。"]
    assert mine[0]["handoff_id"] == handoffs[ASKERS["xu"]].id
    assert [t["role"] for t in turns] == ["user", "twin", "user", "twin", "self"]
    assert [t.get("handoff", {}).get("status") for t in turns if t["role"] == "twin"] == [None, "replied"]
    # The asker's list marks the conversation whose last word is the person's; the others are not marked.
    scene.as_("xu")
    marked = {c["id"]: c["owner_replied"] for c in scene.web.get("/api/conversations", headers=scene.headers).json()}
    assert marked == {xu: True}
    scene.as_("wang")
    assert [c["owner_replied"] for c in scene.web.get("/api/conversations", headers=scene.headers).json()] == [False]
    # The answer is kept as a memory in the person's words, with the question as its context.
    assert scene.sources() == ["回答：大文件导入这次上不上？"]
    # The others still wait.
    assert {h["id"] for h in scene.page()["waiting"]} == {handoffs[ASKERS["shen"]].id, handoffs[ASKERS["wang"]].id}


def test_the_person_chooses_who_may_use_a_reply_as_a_memory_when_they_send_it(scene: Scene) -> None:
    def private() -> set[str]:
        with PersonaStore(scene.path) as store:
            return store.private_note_sources()

    def answers() -> list[str]:
        with PersonaStore(scene.path) as store:
            return [s.source_id for s in store.list_sources() if s.origin.startswith("handoff:")]

    scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    # Kept to themself: the memory exists, and nothing made from it reaches a colleague's conversation.
    sent = scene.reply(made.id, "这次不上，大文件导入放下个版本。", tier="self")
    assert sent.status_code == 200, sent.text
    [source_id] = answers()
    assert private() == {source_id}
    settled = scene.team.get_handoff(made.id)
    assert settled is not None and settled.reply_tier == "self"
    # Sending it again keeps one memory, in the same tier.
    assert scene.reply(made.id, "这次不上，大文件导入放下个版本。", tier="self").status_code == 409
    assert answers() == [source_id] and private() == {source_id}


def test_a_reply_for_colleagues_leaves_its_tier_to_the_facets_and_one_the_person_does_not_keep_is_no_memory(
    scene: Scene,
) -> None:
    scene.asked("shen", DECISION)
    scene.asked("xu", DECISION)
    first, second = scene.team.handoffs(persona_id=scene.persona)
    assert scene.reply(first.id, "上。", tier="colleague").status_code == 200
    assert scene.reply(second.id, "不上。", tier="none").status_code == 200
    with PersonaStore(scene.path) as store:
        assert [s.origin for s in store.list_sources() if s.origin.startswith("handoff:")] == [f"handoff:{first.id}"]
        assert store.private_note_sources() == set()
    # What was sent is written in each conversation whatever the tier; an unknown tier is refused.
    assert scene.team.get_handoff(second.id).reply_tier == "none"  # type: ignore[union-attr]
    scene.asked("wang", DECISION)
    [_, _, last] = scene.team.handoffs(persona_id=scene.persona)
    assert scene.reply(last.id, "上。", tier="everyone").status_code == 400


def test_a_reply_to_several_askers_is_kept_once_in_the_tier_chosen(scene: Scene) -> None:
    scene.asked("shen", DECISION)
    scene.asked("xu", DECISION)
    group = [h.id for h in scene.team.handoffs(persona_id=scene.persona)]
    scene.as_("person")
    response = scene.web.post(
        "/api/persona/handoffs/reply-many",
        json={"ids": group, "text": "这次不上。", "tier": "self"},
        headers=scene.headers,
    )
    assert response.status_code == 200, response.text
    with PersonaStore(scene.path) as store:
        kept = [s.source_id for s in store.list_sources() if s.origin.startswith("handoff:")]
        assert len(kept) == 1 and store.private_note_sources() == set(kept)


def test_a_reply_made_a_team_answer_cannot_be_kept_from_colleagues(scene: Scene) -> None:
    scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    scene.as_("person")
    body = {"ids": [made.id], "text": "这次不上。", "tier": "self", "team_answer": {"title": "大文件导入上不上"}}
    refused = scene.web.post("/api/persona/handoffs/reply-many", json=body, headers=scene.headers)
    assert refused.status_code == 400
    assert scene.team.get_handoff(made.id).status == "delivered"  # type: ignore[union-attr]


def test_a_reply_sent_twice_is_written_once(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    assert scene.reply(made.id, "不上。").status_code == 200
    again = scene.reply(made.id, "不上。")
    assert again.status_code == 409 and "已经回复" in again.json()["detail"]
    other = scene.reply(made.id, "改成上。")
    assert other.status_code == 409
    assert scene.own(conversation) == ["不上。"]
    assert scene.sources() == ["回答：大文件导入这次上不上？"]


def test_two_replies_at_once_write_one(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    desk = scene.desk()
    outcomes: list[str] = []

    def answer(text: str) -> None:
        try:
            desk.reply(made.id, PERSON, text)
            outcomes.append("sent")
        except HandoffRefused:
            outcomes.append("refused")

    threads = [threading.Thread(target=answer, args=(f"回复 {n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes) == ["refused"] * 3 + ["sent"]
    [said] = scene.own(conversation)
    assert said.startswith("回复 ")
    settled = scene.team.get_handoff(made.id)
    assert settled is not None and settled.status == "replied" and settled.reply == said and settled.reply_turn == 3


def test_a_reply_that_stopped_halfway_is_finished_at_startup_without_a_second_turn(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    # Step one done (the reply is kept, the handoff marked), then nothing.
    kept = scene.team.begin_reply(made.id, "这次不上。", "colleague")
    assert kept.status == "writing" and scene.page()["waiting"] == [] and scene.own(conversation) == []
    # Step two done as well, then nothing.
    with PersonaStore(scene.path) as store:
        assert store.append_conversation_turn(
            conversation, ASKERS["shen"], "self", "这次不上。", None, handoff_id=made.id
        )
    desk = scene.desk()
    assert desk.redo_writing() == 1 and desk.redo_writing() == 0
    assert scene.own(conversation) == ["这次不上。"]
    settled = scene.team.get_handoff(made.id)
    assert settled is not None and settled.status == "replied" and settled.reply_turn == 3
    assert scene.sources() == ["回答：大文件导入这次上不上？"]
    # Starting the service again does the same: nothing is written twice.
    run_all([desk])
    assert scene.own(conversation) == ["这次不上。"]


def test_a_reply_kept_but_not_written_at_all_is_written_at_startup(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    scene.team.begin_reply(made.id, "这次不上。", "none")
    run_all([scene.desk()])
    assert scene.own(conversation) == ["这次不上。"] and scene.sources() == []  # "none": not kept as a memory
    assert scene.turns("shen", conversation)[-1]["role"] == "self"


def test_a_reply_left_halfway_by_a_failed_request_is_finished_when_the_person_next_looks(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    scene.team.begin_reply(made.id, "这次不上。", "colleague")
    # Just kept: the request that kept it may still be writing, so it is left alone.
    assert scene.page()["waiting"] == [] and scene.own(conversation) == []
    with scene.team._tx() as db:  # kept a minute ago
        db.execute("UPDATE handoffs SET replied_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", made.id))
    page = scene.page()
    assert [h["id"] for h in page["settled"]] == [made.id] and scene.own(conversation) == ["这次不上。"]


def test_the_asker_reads_a_handoff_nobody_answered_in_time_as_expired_before_the_person_looks(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    with scene.team._tx() as db:
        db.execute("UPDATE handoffs SET expires_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", made.id))
    turn = next(t for t in scene.turns("shen", conversation) if t["role"] == "twin")
    assert turn["handoff"]["status"] == "expired" and turn["handoff"]["status_label"] == "已过期"
    assert scene.team.get_handoff(made.id).status == "delivered"  # type: ignore[union-attr]


def test_the_asker_deleting_the_conversation_withdraws_the_handoff_and_nothing_is_written(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    other, _ = scene.asked("xu", DECISION)
    [made] = [h for h in scene.team.handoffs(persona_id=scene.persona) if h.conversation_id == conversation]
    scene.as_("shen")
    assert scene.web.delete(f"/api/conversations/{conversation}", headers=scene.headers).status_code == 200
    assert scene.team.get_handoff(made.id).status == "withdrawn"  # type: ignore[union-attr]
    assert [h["asker_name"] for h in scene.page()["waiting"]] == ["xu"]
    late = scene.reply(made.id, "不上。")
    assert late.status_code == 409 and "删掉" in late.json()["detail"]
    with PersonaStore(scene.path) as store:
        assert store.conversation_head(conversation) is None
    assert scene.sources() == [] and scene.own(other) == []
    # A reply that was already being written when the conversation went is not written into nothing either.
    kept = scene.team.begin_reply(scene.team.handoffs(conversation_id=other)[0].id, "不上。", "colleague")
    scene.as_("xu")
    assert scene.web.delete(f"/api/conversations/{other}", headers=scene.headers).status_code == 200
    with pytest.raises(HandoffRefused):
        scene.desk().finish(kept)
    assert scene.team.get_handoff(kept.id).status == "withdrawn"  # type: ignore[union-attr]
    assert scene.sources() == []


def test_a_promise_whose_conversation_the_asker_deleted_can_still_be_taken_or_turned_down_from_the_ledger(
    scene: Scene,
) -> None:
    shen, _ = scene.asked("shen", PROMISE)
    xu, _ = scene.asked("xu", PROMISE)
    for who, conversation in (("shen", shen), ("xu", xu)):
        scene.as_(who)
        assert scene.web.delete(f"/api/conversations/{conversation}", headers=scene.headers).status_code == 200
    first, second = (scene.team.handoffs(conversation_id=c)[0] for c in (shen, xu))
    assert first.status == second.status == "withdrawn" and scene.page()["waiting"] == []
    scene.as_("person")
    taken = scene.web.post(f"/api/persona/ledger/{ledger_id_for(first.id)}/accept", json={}, headers=scene.headers)
    assert taken.status_code == 200, taken.text
    turned_down = scene.web.post(f"/api/persona/ledger/{ledger_id_for(second.id)}/decline", headers=scene.headers)
    assert turned_down.status_code == 200, turned_down.text
    with PersonaStore(scene.path) as store:
        accepted, declined = (store.get_ledger_entry(ledger_id_for(h.id)) for h in (first, second))
    assert accepted is not None and accepted.status is None and accepted.review.value == "confirmed"
    assert declined is not None and declined.review.value == "rejected"
    # Nothing was written to the deleted conversations, and the handoffs stay withdrawn.
    with PersonaStore(scene.path) as store:
        assert store.conversation_head(shen) is None and store.conversation_head(xu) is None
    assert {scene.team.get_handoff(h.id).status for h in (first, second)} == {"withdrawn"}  # type: ignore[union-attr]
    # And it is done: the same entry cannot be taken again.
    again = scene.web.post(f"/api/persona/ledger/{ledger_id_for(first.id)}/accept", json={}, headers=scene.headers)
    assert again.status_code == 409


def test_a_handoff_nobody_answered_expires_and_a_late_reply_still_reaches_the_right_conversation_once(
    scene: Scene,
) -> None:
    shen, _ = scene.asked("shen", DECISION)
    xu, _ = scene.asked("xu", DECISION)
    old = scene.team.handoffs(conversation_id=shen)[0]
    with scene.team._tx() as db:  # the week is up
        db.execute("UPDATE handoffs SET expires_at = ? WHERE id = ?", ("2000-01-01T00:00:00+00:00", old.id))
    page = scene.page()
    assert [h["asker_name"] for h in page["waiting"]] == ["xu"] and page["pending"] == 1
    assert [(h["id"], h["status"]) for h in page["shelved"]] == [(old.id, "expired")]
    assert scene.turns("shen", shen)[1]["handoff"]["status"] == "expired"
    answered = scene.reply(old.id, "上。")
    assert answered.status_code == 200 and answered.json()["handoff"]["status"] == "replied"
    assert scene.own(shen) == ["上。"] and scene.own(xu) == []
    assert scene.reply(old.id, "上。").status_code == 409 and scene.own(shen) == ["上。"]


def test_putting_aside_and_back_and_an_expired_one_put_back_waits_another_week(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    assert scene.post(made.id, "dismiss").json()["handoff"]["status"] == "dismissed"
    assert scene.page()["waiting"] == [] and scene.turns("shen", conversation)[1]["handoff"]["status"] == "dismissed"
    assert scene.post(made.id, "dismiss").status_code == 409
    restored = scene.post(made.id, "restore").json()
    assert restored["handoff"]["status"] == "delivered" and restored["pending"] == 1
    assert scene.post(made.id, "restore").status_code == 409


def test_the_person_alone_reads_and_settles_handoffs(scene: Scene) -> None:
    _, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    for who in ("admin", "xu"):
        scene.as_(who)
        for method, path in (
            ("get", "/api/persona/handoffs"),
            ("get", "/api/persona/handoffs/count"),
            ("post", f"/api/persona/handoffs/{made.id}/reply"),
            ("post", f"/api/persona/handoffs/{made.id}/dismiss"),
        ):
            call = getattr(scene.web, method)
            response = call(path, headers=scene.headers, **({"json": {"text": "x"}} if method == "post" else {}))
            assert response.status_code == 403, (who, path)
    assert scene.team.get_handoff(made.id).status == "delivered"  # type: ignore[union-attr]
    # A handoff of another twin is not found through this one.
    scene.as_("person")
    assert (
        scene.web.post("/api/persona/handoffs/nope/reply", json={"text": "x"}, headers=scene.headers).status_code == 404
    )


def test_the_old_questions_of_the_twin_are_the_persons_alone_too(scene: Scene) -> None:
    scene.as_("person")
    queue = scene.web.get("/api/persona/followups", headers=scene.headers)
    assert queue.status_code == 200
    for who in ("admin", "xu"):
        scene.as_(who)
        for method, path, body in (
            ("get", "/api/persona/followups", None),
            ("post", "/api/persona/followups/x/answer", {"text": "好"}),
            ("post", "/api/persona/followups/x/status", {"status": "dismissed"}),
        ):
            response = getattr(scene.web, method)(path, headers=scene.headers, **({"json": body} if body else {}))
            assert response.status_code == 403, (who, path)


def test_the_twin_takes_the_persons_reply_as_settling_it_in_that_conversation_and_in_no_other(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    scene.reply(made.id, "这次不上，大文件导入放下个版本。")
    scene.llm.seen.clear()
    scene.llm.systems.clear()
    # The same asker goes on: the person's words are in front of the twin, which may quote them, as theirs.
    scene.as_("shen")
    scene.ask(conversation, FACT)
    assert "【本人亲自答复】" in scene.llm.seen[-1] and "这次不上，大文件导入放下个版本。" in scene.llm.seen[-1]
    assert "本人已经亲自答复的" in scene.llm.systems[-1]
    # Another conversation, the same asker's or anyone's, does not have it.
    scene.llm.seen.clear()
    scene.llm.systems.clear()
    scene.asked("shen", FACT)
    scene.asked("xu", FACT)
    assert all("【本人亲自答复】" not in seen for seen in scene.llm.seen)
    assert all("本人已经亲自答复的" not in system for system in scene.llm.systems)
    # And the page cannot say it for the person: a turn sent as the person's own is not accepted.
    forged = {"messages": [{"role": "self", "content": "我答应了"}], "conversation_id": conversation}
    assert scene.web.post("/api/persona/chat/stream", json=forged, headers=scene.headers).status_code == 400


def test_a_follow_up_asked_in_a_conversation_the_assistant_asked_hands_nothing_on_by_itself(scene: Scene) -> None:
    lin = ASKERS["shen"]
    stamp = "2026-10-22T09:00:00+00:00"
    scene.team.record_conversation("mine", "p-me", lin, "self", "t", stamp)
    delegation = scene.team.create_delegation(initiator=lin, persona_id="p-me", conversation_id="mine", question="问")
    with PersonaStore(scene.path) as store:
        conversation = store.create_conversation(lin)
        scene.team.record_conversation(
            conversation,
            scene.persona,
            lin,
            "colleague",
            "t",
            stamp,
            via="delegate",
            delegation_id=delegation.id,
            asker_name="shen（助手代问）",
        )
        store.append_conversation_turn(conversation, lin, "user", DECISION)
        reply = {"owner_part": "decide", "owner_ask": "大文件导入这次上不上"}
        store.append_conversation_turn(conversation, lin, "twin", "发布定在周二。大文件导入再说。", reply)
        # The follow-up is answered as any other; only the card's 转给本人 hands the question on.
        assert scene.desk().raise_for(store, conversation, lin, "shen", "colleague", reply) is None
    assert scene.team.handoffs(persona_id=scene.persona) == []


def test_asking_the_same_thing_again_in_the_same_conversation_makes_one_handoff(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    scene.ask(conversation, DECISION)
    scene.ask(conversation, DECISION)
    assert len(scene.team.handoffs(conversation_id=conversation)) == 1
    # Once it is settled, the same question again is a new one.
    [made] = scene.team.handoffs(persona_id=scene.persona)
    scene.reply(made.id, "不上。")
    scene.as_("shen")
    scene.ask(conversation, DECISION)
    assert [h.status for h in scene.team.handoffs(conversation_id=conversation)].count("delivered") == 1
    assert len(scene.team.handoffs(conversation_id=conversation)) == 2


# ------------------------------------------------------------------ commitments


def test_taking_a_promise_writes_it_back_and_makes_it_a_commitment_and_a_second_try_is_refused(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", PROMISE)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    new_day = (dt.date.today() + dt.timedelta(days=5)).isoformat()
    taken = scene.post(made.id, "accept", due=new_day)
    assert taken.status_code == 200, taken.text
    assert taken.json()["handoff"]["status"] == "accepted"
    [said] = scene.own(conversation)
    assert said.startswith("接下了：周五前给沈从一版发布方案") and f"{int(new_day[5:7])}月" in said
    turns = scene.turns("shen", conversation)
    assert turns[-1]["role"] == "self" and turns[1]["handoff"]["status"] == "accepted"
    with PersonaStore(scene.path) as store:
        entry = store.get_ledger_entry(ledger_id_for(made.id))
    assert entry is not None and entry.status is None and entry.due is not None and entry.due.isoformat() == new_day
    scene.as_("person")
    ledger = scene.web.get("/api/persona/ledger", headers=scene.headers).json()
    assert [e["current_status"] for e in ledger["entries"]] == ["open"]
    assert scene.post(made.id, "accept").status_code == 409 and scene.post(made.id, "decline").status_code == 409
    assert scene.own(conversation) == [said]
    # The asker's twin is not made to remember it as a memory: the commitment is the record.
    assert scene.sources() == []


def test_turning_a_promise_down_and_taking_one_from_the_ledger(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", PROMISE)
    other, _ = scene.asked("xu", PROMISE)
    first = scene.team.handoffs(conversation_id=conversation)[0]
    second = scene.team.handoffs(conversation_id=other)[0]
    declined = scene.post(first.id, "decline")
    assert declined.status_code == 200 and declined.json()["handoff"]["status"] == "declined"
    assert scene.own(conversation) == ["这件事我先不接。"]
    with PersonaStore(scene.path) as store:
        assert store.get_ledger_entry(ledger_id_for(first.id)).review.value == "rejected"  # type: ignore[union-attr]
    # In the ledger the other waits as 待你接受, and 接下 there is the same as on the page.
    entry_id = ledger_id_for(second.id)
    taken = scene.web.post(f"/api/persona/ledger/{entry_id}/accept", json={}, headers=scene.headers)
    assert taken.status_code == 200, taken.text
    assert taken.json()["current_status"] == "open"
    assert scene.team.get_handoff(second.id).status == "accepted"  # type: ignore[union-attr]
    assert scene.own(other)[0].startswith("接下了")
    # A meeting's entry is not one to take.
    assert scene.web.post("/api/persona/ledger/nope/accept", json={}, headers=scene.headers).status_code == 404
    scene.as_("xu")
    assert scene.web.post(f"/api/persona/ledger/{entry_id}/decline", headers=scene.headers).status_code == 403


def test_a_promise_asked_for_is_answered_by_taking_or_turning_it_down_not_by_editing_its_state(scene: Scene) -> None:
    scene.asked("shen", PROMISE)
    scene.asked("xu", PROMISE)
    first, second = scene.team.handoffs(persona_id=scene.persona)
    declined_id, waiting_id = ledger_id_for(first.id), ledger_id_for(second.id)
    assert scene.post(first.id, "decline").status_code == 200
    review = lambda entry_id, body: scene.web.post(  # noqa: E731
        f"/api/persona/ledger/{entry_id}/review", json=body, headers=scene.headers
    )
    # Taking back the "不接" would put 接下 / 不接 on a promise whose asker was already told no; both fail there.
    undone = review(declined_id, {"action": "reset"})
    assert undone.status_code == 409 and "接下" in undone.json()["detail"]
    # Nor can the state "待你接受" be set by hand on any entry, or the one waiting be confirmed away from its asker.
    assert review(waiting_id, {"action": "edit", "changes": {"status": "pending_accept"}}).status_code == 400
    assert review(waiting_id, {"action": "reject"}).status_code == 409
    with PersonaStore(scene.path) as store:
        assert store.get_ledger_entry(declined_id).review.value == "rejected"  # type: ignore[union-attr]
        waiting = store.get_ledger_entry(waiting_id)
        assert waiting is not None and waiting.review.value == "unreviewed" and waiting.status == "pending_accept"
    assert scene.web.post(f"/api/persona/ledger/{waiting_id}/accept", json={}, headers=scene.headers).status_code == 200


def test_a_promise_answered_in_words_can_still_be_taken_in_the_ledger_without_a_second_turn(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", PROMISE)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    assert scene.reply(made.id, "周五前给你。").status_code == 200
    taken = scene.web.post(f"/api/persona/ledger/{ledger_id_for(made.id)}/accept", json={}, headers=scene.headers)
    assert taken.status_code == 200
    assert scene.team.get_handoff(made.id).status == "accepted"  # type: ignore[union-attr]
    assert scene.own(conversation) == ["周五前给你。"]


def test_a_decision_handoff_has_no_promise_to_take(scene: Scene) -> None:
    scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    refused = scene.post(made.id, "accept")
    assert refused.status_code == 409 and "答应" in refused.json()["detail"]


def test_the_twin_drafts_a_reply_for_the_person_to_change_and_nothing_is_sent_or_kept(
    scene: Scene, web: tuple[TestClient, Scripted]
) -> None:
    llm = web[1]
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    drafted = scene.post(made.id, "draft")
    assert drafted.status_code == 200, drafted.text
    assert "方案周五前给你" in drafted.json()["text"]
    # It is made from the person's own memory and the question, and tells the model not to decide for them.
    [(system, user)] = llm.drafts
    assert "不要替他拍板" in system and DECISION in user and "要他定的事" in user
    # Nothing was written, sent or kept.
    assert scene.team.get_handoff(made.id).status == "delivered"  # type: ignore[union-attr]
    assert scene.own(conversation) == [] and scene.sources() == []
    # What it left open is not sent as it is: the person fills it in first.
    refused = scene.reply(made.id, drafted.json()["text"])
    assert refused.status_code == 409 and "请你定" in refused.json()["detail"]
    assert scene.own(conversation) == []
    assert scene.reply(made.id, "方案周五前给你。大文件导入这次不上。").status_code == 200
    assert scene.own(conversation) == ["方案周五前给你。大文件导入这次不上。"]
    # A settled one is not drafted again, and only the person can ask.
    assert scene.post(made.id, "draft").status_code == 409
    scene.as_("xu")
    assert scene.web.post(f"/api/persona/handoffs/{made.id}/draft", json={}, headers=scene.headers).status_code == 403


def test_one_draft_answers_several_askers_of_one_matter_and_sums_their_question_up(
    scene: Scene, web: tuple[TestClient, Scripted]
) -> None:
    llm = web[1]
    scene.asked("shen", DECISION)
    scene.asked("xu", DECISION)
    first, second = scene.team.handoffs(persona_id=scene.persona)
    drafted = scene.post(first.id, "draft", also=[second.id])
    assert drafted.status_code == 200, drafted.text
    # The card's title is the matter asked once, in no one's words; the reply is one for all of them.
    assert drafted.json() == {"text": "这次先不上，下个版本再说。", "question": "大文件导入这次上不上？"}
    [(_, user)] = llm.drafts
    assert "同事们问的同一件事" in user and user.count(DECISION) == 2
    # One asker alone is drafted as before, with no title.
    alone = scene.post(first.id, "draft")
    assert alone.status_code == 200 and "question" not in alone.json()
    # Only the person's own handoffs, and only those still waiting, are drafted for.
    assert scene.post(first.id, "draft", also=["nope"]).status_code == 404
    assert scene.reply(second.id, "不上。").status_code == 200
    assert scene.post(first.id, "draft", also=[second.id]).status_code == 409


def test_a_draft_draws_only_on_what_the_twin_may_tell_the_colleague(
    scene: Scene, web: tuple[TestClient, Scripted]
) -> None:
    llm = web[1]
    with PersonaStore(scene.path) as store:
        store.replace_facet_items(
            "2.1", [item("pi_work", "2.1", "发布"), item("pi_secret", "2.1", "大文件导入私下打算砍掉")]
        )
        store.set_item_tier("pi_secret", "self")
    scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    assert scene.post(made.id, "draft").status_code == 200
    [(system, user)] = llm.drafts
    # What the person keeps to themself is not in what the draft is made from: it is sent to the colleague.
    assert "私下打算砍掉" not in system + user
    assert "他说起过发布" in system + user


def test_a_promise_answered_in_words_is_taken_or_turned_down_once_when_both_are_pressed_at_once(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene.asked("shen", PROMISE)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    assert scene.reply(made.id, "周五前给你。").status_code == 200
    desk = scene.desk()
    both_read = threading.Barrier(2, timeout=5)
    ensure = desk._ensure_commitment

    def read_then_wait(store: PersonaStore, h: Any) -> Any:
        entry = ensure(store, h)
        both_read.wait()  # both requests have seen the commitment waiting
        return entry

    monkeypatch.setattr(desk, "_ensure_commitment", read_then_wait)
    outcomes: dict[str, str] = {}

    def press(action: str) -> None:
        try:
            getattr(desk, action)(made.id, PERSON)
            outcomes[action] = "done"
        except HandoffRefused:
            outcomes[action] = "refused"

    threads = [threading.Thread(target=press, args=(action,)) for action in ("accept", "decline")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(outcomes.values()) == ["done", "refused"]
    winner = next(action for action, outcome in outcomes.items() if outcome == "done")
    settled = scene.team.get_handoff(made.id)
    assert settled is not None and settled.status == {"accept": "accepted", "decline": "declined"}[winner]
    # The ledger says what the handoff says.
    with PersonaStore(scene.path) as store:
        entry = store.get_ledger_entry(ledger_id_for(made.id))
    assert entry is not None and entry.version == 2
    if winner == "accept":
        assert entry.status is None and entry.review.value == "confirmed"
    else:
        assert entry.review.value == "rejected"


# ------------------------------------------------------------------ checking before showing


@pytest.mark.rewrite
def test_an_answer_to_a_request_for_a_promise_is_shown_only_after_its_quotes_are_checked(scene: Scene) -> None:
    scene.as_("shen")
    shown, final = scene.deltas(scene.conversation(), QUOTED)
    # The invented quote lost its marks before anything was shown, in one piece.
    assert final["quotes_removed"] == 1 and "「" not in final["reply"]
    assert shown == [final["reply"]]
    assert all("「周五一定交的事我没说过」" not in piece for piece in shown)
    # Everything else is shown as it is written: in pieces.
    pieces, plain = scene.deltas(scene.conversation(), FACT)
    assert len(pieces) > 1 and "".join(pieces).rstrip() == plain["reply"]


@pytest.mark.rewrite
def test_the_rewrite_decides_what_is_held_back_and_a_cue_word_only_when_it_fails(scene: Scene) -> None:
    scene.as_("shen")
    # The rewrite saw a request for the person's say in a question that has no cue word: held back all the same.
    shown, final = scene.deltas(scene.conversation(), HOLD)
    assert shown == [final["reply"]] and final["owner_part"] == "decide"
    # The rewrite saw none in a question that has a cue word: the rewrite decides, and it is shown as written.
    pieces, plain = scene.deltas(scene.conversation(), COMMON)
    assert len(pieces) > 1 and "".join(pieces).rstrip() == plain["reply"]
    # Without the rewrite the cue words stand in for it.
    scene.llm.rewrite_fails = True
    held, promised = scene.deltas(scene.conversation(), PROMISE)
    assert held == [promised["reply"]]
    held, status = scene.deltas(scene.conversation(), COMMON)
    assert held == [status["reply"]]
    pieces, plain = scene.deltas(scene.conversation(), FACT)
    assert len(pieces) > 1 and "".join(pieces).rstrip() == plain["reply"]


@pytest.mark.rewrite
def test_what_is_held_back_for_a_twin_nobody_has_taken_says_to_ask_the_person_in_the_one_piece(
    web: tuple[TestClient, Scripted], tmp_path: Path
) -> None:
    scene = Scene(*web, tmp_path, take=False)
    scene.as_("shen")
    shown, final = scene.deltas(scene.conversation(), HOLD)
    assert shown == [final["reply"]] and "请直接联系本人" in shown[0]


def chat_of(scene: Scene, llm: Any, store: PersonaStore) -> PersonaChat:
    return PersonaChat(store, llm, HashingEmbedder(), Settings(db_path=scene.path), reach="owner")


def streamed(chat: PersonaChat, question: str) -> list[Any]:
    async def run() -> list[Any]:
        return [x async for x in chat.stream_reply([ChatTurn(role="user", content=question)], persist=False)]

    return asyncio.run(run())


@pytest.mark.rewrite
def test_an_answer_held_back_is_shown_once_by_a_model_that_cannot_stream(scene: Scene) -> None:
    class Whole(Scripted):
        stream = None  # type: ignore[assignment]

    with PersonaStore(scene.path) as store:
        events = streamed(chat_of(scene, Whole(), store), HOLD)
    assert [type(e).__name__ for e in events] == ["str", "ChatReply"] and events[0] == events[1].reply


@pytest.mark.rewrite
def test_an_answer_held_back_when_the_twins_memory_changed_under_it_is_not_shown_at_all(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    with PersonaStore(scene.path) as store:
        chat = chat_of(scene, Scripted(), store)
        monkeypatch.setattr("twin.persona.chat.gate.current", lambda *_: False)
        events = streamed(chat, HOLD)
    assert [type(e).__name__ for e in events] == ["ChatReply"] and chat.stale


# ------------------------------------------------------------------ guessed answers and what has a source


def test_what_the_twin_guessed_and_what_it_answered_from_the_profile_are_on_the_page_and_can_be_checked(
    scene: Scene,
) -> None:
    shen, _ = scene.asked("shen", GUESS)
    xu, _ = scene.asked("xu", GUESS)
    scene.asked("xu", FACT)
    scene.asked("shen", DECISION)
    own, _ = scene.asked("person", GUESS)  # the person's own conversations are not what colleagues were told
    del own
    page = scene.page()
    assert [(g["asker_name"], g["question"], g["answer"]) for g in page["guessed"]] == [
        ("xu", GUESS, "能接受。"),
        ("shen", GUESS, "能接受。"),
    ]
    assert page["sourced_count"] == 1 and [s["question"] for s in page["sourced"]] == [FACT]
    assert page["answered"] == 4 and [h["asker_name"] for h in page["waiting"]] == ["shen"]
    first = page["guessed"][1]
    assert scene.web.post(
        f"/api/persona/answers/{first['conversation_id']}/{first['turn']}/confirm", headers=scene.headers
    ).json() == {"confirmed": True}
    assert [g["asker_name"] for g in scene.page()["guessed"]] == ["xu"]
    # 更正: the asker is told in their conversation and the twin keeps the person's words.
    second = scene.page()["guessed"][0]
    corrected = scene.web.post(
        f"/api/persona/answers/{second['conversation_id']}/{second['turn']}/correct",
        json={"text": "延期一周不行，最多三天。"},
        headers=scene.headers,
    )
    assert corrected.status_code == 200, corrected.text
    assert corrected.json()["handoff"]["kind"] == "inferred" and corrected.json()["handoff"]["status"] == "replied"
    assert scene.own(xu) == ["延期一周不行，最多三天。"]
    assert scene.sources() == [f"回答：{GUESS}"]
    assert scene.page()["guessed"] == []
    again = scene.web.post(
        f"/api/persona/answers/{second['conversation_id']}/{second['turn']}/correct",
        json={"text": "再改一次"},
        headers=scene.headers,
    )
    assert again.status_code in (404, 409)
    assert scene.own(shen) == []
    # An answer that was not a guess cannot be checked, and nobody else can.
    assert scene.web.post("/api/persona/answers/nope/2/confirm", headers=scene.headers).status_code == 404
    scene.as_("shen")
    assert scene.web.post(f"/api/persona/answers/{xu}/2/confirm", headers=scene.headers).status_code == 403


# ------------------------------------------------------------------ the team database


def test_handoffs_missed_by_the_team_database_are_made_again_from_the_twins_replies(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", PROMISE)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    with scene.team._tx() as db:  # the write after the twin's turn did not make it
        db.execute("DELETE FROM handoffs")
    desk = scene.desk()
    assert desk.reconcile() == 1 and desk.reconcile() == 0
    [again] = scene.team.handoffs(persona_id=scene.persona)
    assert again.conversation_id == conversation and again.kind == "commit" and again.id != made.id
    # The commitment it asks for is made for the new handoff, once.
    with PersonaStore(scene.path) as store:
        pending = [e for e in store.list_ledger() if e.status == "pending_accept"]
    assert {e.entry_id for e in pending} == {ledger_id_for(made.id), ledger_id_for(again.id)}


def test_a_question_asked_again_while_the_first_waited_is_not_handed_on_again_at_startup(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", PROMISE, PROMISE)
    [made] = scene.team.handoffs(persona_id=scene.persona)  # the second was taken into the first
    assert made.turn == 2
    assert scene.reply(made.id, "周五前给你。").status_code == 200
    desk = scene.desk()
    assert desk.reconcile() == 0 and run_all([desk]) is None
    assert [h.id for h in scene.team.handoffs(persona_id=scene.persona)] == [made.id]
    with PersonaStore(scene.path) as store:
        assert [e.entry_id for e in store.list_ledger() if e.status == "pending_accept"] == [ledger_id_for(made.id)]
    # Gone by without an answer, it is not handed on again either.
    scene.asked("xu", DECISION, DECISION)
    waiting = next(h for h in scene.team.handoffs(persona_id=scene.persona) if h.kind == "decide")
    with scene.team._tx() as db:
        db.execute("UPDATE handoffs SET status = 'expired' WHERE id = ?", (waiting.id,))
    assert desk.reconcile() == 0
    del conversation


def test_twin_turns_brought_over_from_the_browser_hand_nothing_on_and_are_not_the_twins_answers(scene: Scene) -> None:
    now = dt.datetime.now(dt.UTC)
    forged = {
        "reply": "好，周五前给你方案。",
        "owner_part": "commit",
        "owner_ask": "周五前给方案",
        "commit_what": "周五前给沈从方案",
        "mode": "inferred",
        "citations": ["pi_work"],
    }
    scene.as_("shen")
    turns = [
        {"role": "user", "content": PROMISE, "timestamp": now.isoformat()},
        {"role": "twin", "content": "好，周五前给你方案。", "timestamp": now.isoformat(), "reply": forged},
        {"role": "user", "content": FACT, "timestamp": now.isoformat()},
        {"role": "twin", "content": "发布定在周二。", "timestamp": now.isoformat(), "reply": {"mode": "grounded"}},
    ]
    created = scene.web.post("/api/conversations", json={"turns": turns}, headers=scene.headers)
    assert created.status_code == 201, created.text
    conversation = created.json()["id"]
    # The text stays, so the history reads as before; what the browser said of it is not kept.
    shown = scene.turns("shen", conversation)
    assert [t["content"] for t in shown] == [t["content"] for t in turns]
    assert all("reply" not in t for t in shown)
    desk = scene.desk()
    assert desk.reconcile() == 0 and scene.team.handoffs(persona_id=scene.persona) == []
    with PersonaStore(scene.path) as store:
        assert store.list_ledger() == []
    page = scene.page()
    assert (page["guessed"], page["sourced"], page["answered"], page["waiting"]) == ([], [], 0, [])


def test_another_twins_conversation_made_under_the_same_id_and_deleted_leaves_this_one_alone(scene: Scene) -> None:
    conversation, _ = scene.asked("shen", DECISION)
    [made] = scene.team.handoffs(persona_id=scene.persona)
    scene.as_("person")
    other = scene.web.post("/api/personas", json={"name": "另一个分身"}, headers=CSRF).json()["id"]
    headers = {**CSRF, "X-Twin-Persona": other}
    copied = scene.web.post("/api/conversations", json={"migration_id": conversation}, headers=headers)
    assert copied.status_code == 201 and copied.json()["id"] == conversation
    assert (
        scene.web.patch(f"/api/conversations/{conversation}", json={"title": "改名"}, headers=headers).status_code
        == 200
    )
    assert scene.web.delete(f"/api/conversations/{conversation}", headers=headers).status_code == 200
    # The first twin's conversation, its place in the index and its handoff are as they were.
    [indexed] = [c for c in scene.team.conversations(persona_id=scene.persona) if c.id == conversation]
    assert indexed.deleted_at is None and indexed.title != "改名"
    assert scene.team.get_handoff(made.id).status == "delivered"  # type: ignore[union-attr]
    assert [t["role"] for t in scene.turns("shen", conversation)] == ["user", "twin"]
    assert [h["id"] for h in scene.page()["waiting"]] == [made.id]


def test_the_old_questions_to_answer_become_handoffs_without_a_source_and_are_kept_as_memories_only(
    web: tuple[TestClient, Scripted], tmp_path: Path
) -> None:
    client, llm = web
    scene = Scene(client, llm, tmp_path)
    with PersonaStore(scene.path) as store:
        for question in ("新来的实习生能不能独立负责导入模块？", "你几点睡？"):
            store.log_chat(
                question,
                ChatReply(
                    reply="先不答",
                    citations=[],
                    confidence=0.1,
                    abstain=True,
                    abstain_reason="没有依据",
                    retrieved_ids=[],
                    mode="abstain",
                ),
            )
    # Starting the service again (a new process on the same data) makes them handoffs, once.
    settings = client.app.state.personas.settings  # type: ignore[attr-defined]
    app = create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as again:
        again.cookies.set("twin_session", scene.cookies["person"])
        page = again.get("/api/persona/handoffs", headers=scene.headers).json()
        assert {(h["question"], h["source_known"], h["kind"], h["asker_name"]) for h in page["waiting"]} == {
            ("新来的实习生能不能独立负责导入模块？", False, "missing", ""),
            ("你几点睡？", False, "missing", ""),
        }
        assert page["pending"] == 2
        legacy = next(h for h in page["waiting"] if h["question"] == "你几点睡？")
        answered = again.post(
            f"/api/persona/handoffs/{legacy['id']}/reply",
            json={"text": "凌晨一点。"},
            headers={**CSRF, **scene.headers},
        )
        assert answered.status_code == 200 and answered.json()["handoff"]["status"] == "replied"
        # No conversation to write into; the words are kept as a memory, and the old page follows.
        assert len(scene.sources()) == 1
        old = again.get("/api/persona/followups", headers=scene.headers).json()
        assert sorted(f["status"] for f in old["items"]) == ["answered", "pending"]
        # The old routes still work and the handoff follows them.
        pending = next(f for f in old["items"] if f["status"] == "pending")
        dismissed = again.post(
            f"/api/persona/followups/{pending['followup_id']}/status",
            json={"status": "dismissed"},
            headers={**CSRF, **scene.headers},
        )
        assert dismissed.status_code == 200
        assert again.get("/api/persona/handoffs/count", headers=scene.headers).json() == {"pending": 0}
    # Not made a second time at the next start.
    app = create_app(settings, llm_factory=lambda: llm, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as third:
        assert len(third.app.state.team.handoffs(persona_id=scene.persona)) == 2  # type: ignore[attr-defined]


def test_the_database_keeps_handoffs_by_state_and_forgets_a_twin_for_good(tmp_path: Path) -> None:
    with TeamDB(tmp_path / "team" / "team.db") as team:

        def make(turn: int, **fields: Any) -> Any:
            return team.create_handoff(
                persona_id="p1",
                owner="a@x.com",
                conversation_id="c1",
                turn=turn,
                asker="b@x.com",
                asker_name="b",
                kind="decide",
                question=f"问题{turn}",
                group_key=f"g{turn}",
                **fields,
            )

        first, second = make(2), make(4)
        assert make(2) is None  # the same turn again
        assert first is not None and second is not None and first.status == "delivered"
        with pytest.raises(HandoffUnavailable):
            team.begin_reply("missing", "x", "none")
        kept = team.begin_reply(first.id, "好", "colleague")
        assert kept.status == "writing" and kept.reply == "好" and kept.reply_tier == "colleague"
        with pytest.raises(HandoffUnavailable) as taken:
            team.begin_reply(first.id, "又一个", "colleague")
        assert taken.value.status == "writing"
        assert team.finish_reply(first.id, 3) and not team.finish_reply(first.id, 9)
        assert team.get_handoff(first.id).status == "replied"  # type: ignore[union-attr]
        # Withdrawn with the conversation: what is settled stays, what is not goes.
        assert team.withdraw_conversation("c1") == 1
        assert {h.status for h in team.handoffs(persona_id="p1")} == {"replied", "withdrawn"}
        team.check_answer("c1", 2, "right")
        assert team.checked_answers(["c1", "c2"]) == {("c1", 2)}
        team.record_conversation("c1", "p1", "b@x.com", "colleague", "t", "2026-01-01", asker_name="b")
        team.forget_persona("p1")
        assert team.handoffs() == [] and team.checked_answers(["c1"]) == set() and team.conversations() == []


def test_a_ledger_entry_from_before_conversations_were_a_source_reads_as_a_meeting_entry() -> None:
    from twin.persona.schema import LedgerEntry

    old = {
        "entry_id": "e1",
        "source_id": "s1",
        "expression_id": "s1#00001",
        "kind": "commitment",
        "speaker": "其他人1",
        "quote": "周五前给您",
        "owner": "老王",
        "what": "周五前给一版方案",
        "confidence": 0.9,
        "extractor": "ledger-v1",
        "created_at": "2026-10-12T10:00:00",
        "updated_at": "2026-10-12T10:00:00",
    }
    entry = LedgerEntry.model_validate(old)
    assert (entry.origin, entry.handoff_id, entry.status) == ("meeting", None, None)


def test_every_state_and_kind_has_its_label() -> None:
    from twin.handoffs import KIND_LABELS, STATUS_LABELS

    assert STATUS_LABELS == {
        "delivered": "已送达",
        "writing": "正在写回",
        "replied": "已回复",
        "accepted": "已接受",
        "declined": "已拒绝",
        "dismissed": "不答",
        "expired": "已过期",
        "withdrawn": "已撤回",
    }
    assert set(KIND_LABELS) == {"decide", "commit", "evaluate", "missing", "inferred"}
