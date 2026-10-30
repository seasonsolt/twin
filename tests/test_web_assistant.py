"""The person's own conversations: the list of every conversation across twins and the set-apart one with their own
twin (我的分身), the assistant that answers there, what it takes down (a note in the tier they pick, a promise that
stands at once) and the trial question that shows what a colleague would get."""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from twin.config import AuthSettings, Settings, SMTPSettings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.assistant import NOTE_REPLY
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.store import PersonaStore
from twin.persona.work import WorkStore
from twin.teamdb import TeamDB
from twin.web import create_app
from twin.web.conversations import EVERYONE_PAGE
from twin.web.jobs import PersonaProcessing

CSRF = {"X-Twin": "1"}
ADMIN = "admin@example.com"
PERSON = "person@xjjk.com"  # the person the twin is made for
VISITOR = "visitor@xjjk.com"
WORK = "ALPHA-WORK-1f"
FAMILY = "SECRET-FAMILY-9a"
NOTE = "ZETA-LEAVE-77"  # in what the person asks to be remembered
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


class Recorder(FakeLLM):
    """Cites every record id in what it is shown, keeps everything a chat call was shown, and says it made a promise
    when the person says they answer for one."""

    def __init__(self) -> None:
        super().__init__(self.handle)
        self.seen: list[str] = []
        # Set before the first question to make the twin one with no model configured.
        self.unconfigured = False

    @staticmethod
    def meta(text: str, user: str) -> dict[str, Any]:
        cited = sorted(set(re.findall(r"\[(pi_[a-z]+)\]", text)))
        meta: dict[str, Any] = {
            "citations": cited,
            "confidence": 0.9,
            "mode": "grounded",
            "asked": "家人",
            "answered": True,
        }
        if "我答应" in user:
            meta.update(promise_what="周五前给王屿发布方案", promise_to="王屿", promise_due="2026-10-30")
        return meta

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            return {}
        self.seen += [system, user]
        return {"reply": "我回答了。", **self.meta(system + user, user)}

    async def stream(self, **kwargs: Any) -> Any:
        self.seen += [kwargs["system"], kwargs["user"]]
        meta = self.meta(kwargs["system"] + kwargs["user"], kwargs["user"])
        yield "我回答了。\n<<<META>>>\n" + json.dumps(meta, ensure_ascii=False)


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

    def model() -> Recorder:
        if recorder.unconfigured:
            raise RuntimeError("没有配置模型")
        return recorder

    app = create_app(settings, llm_factory=model, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        yield client, recorder


def login(web: TestClient, email: str) -> str:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200
    return str(web.cookies["twin_session"])


def logged(path: Path) -> int:
    """How many questions the twin has logged as asked of it."""
    with PersonaStore(path):
        pass
    with closing(sqlite3.connect(path)) as db:
        return int(db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0])


def team(web: TestClient) -> TeamDB:
    return web.app.state.team  # type: ignore[no-any-return,attr-defined]


class Scene:
    """A public twin made by ``PERSON`` for themself; they have not taken it until ``take``."""

    def __init__(self, web: TestClient, recorder: Recorder, root: Path) -> None:
        self.web, self.recorder, self.root = web, recorder, root
        self.cookies = {"person": login(web, PERSON)}
        self.persona = web.post("/api/personas", json={"name": "测试分身"}, headers=CSRF).json()["id"]
        self.path = root / "personas" / self.persona / "twin.db"
        with PersonaStore(self.path) as store:
            store.set_meta("built_at", "2026-01-01")
            store.replace_facet_items("2.1", [item("pi_work", "2.1", WORK)])
            store.replace_facet_items("9.3", [item("pi_family", "9.3", FAMILY)])
        self.headers = {**CSRF, "X-Twin-Persona": self.persona}
        self.cookies["visitor"] = login(web, VISITOR)
        self.cookies["admin"] = login(web, ADMIN)
        self.as_("person")
        assert web.patch(f"/api/personas/{self.persona}", json={"public": True}, headers=CSRF).status_code == 200

    def as_(self, who: str) -> None:
        self.web.cookies.set("twin_session", self.cookies[who])

    def take(self) -> None:
        self.as_("person")
        claim = self.web.put(f"/api/personas/{self.persona}/claim", json={"claim": PERSON}, headers=CSRF)
        assert claim.status_code == 200, claim.text
        assert [p["mine"] for p in self.web.get("/api/personas").json()] == [True]
        approved = self.web.post(f"/api/personas/{self.persona}/approve", json={"public": True}, headers=CSRF)
        assert approved.status_code == 200, approved.text

    def conversation(self, persona: str | None = None) -> str:
        headers = {**CSRF, "X-Twin-Persona": persona or self.persona}
        created = self.web.post("/api/conversations", json={}, headers=headers)
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    def say(self, conversation_id: str | None, text: str = QUESTION, **extra: Any) -> dict[str, Any]:
        body = {"messages": [{"role": "user", "content": text}], "conversation_id": conversation_id, **extra}
        response = self.web.post("/api/persona/chat/stream", json=body, headers=self.headers)
        assert response.status_code == 200 and "event: final" in response.text, response.text
        final = response.text.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0]
        return json.loads(final)  # type: ignore[no-any-return]

    def listing(self, **query: Any) -> dict[str, Any]:
        response = self.web.get("/api/personas/conversations", params=query)
        assert response.status_code == 200, response.text
        return response.json()  # type: ignore[no-any-return]

    def other_twin(self) -> str:
        """A public twin of someone else, which every signed-in person can talk to."""
        self.as_("admin")
        made = self.web.post("/api/personas", json={"name": "别人的分身"}, headers=CSRF).json()["id"]
        with PersonaStore(self.root / "personas" / made / "twin.db") as store:
            store.set_meta("built_at", "2026-01-01")
            store.replace_facet_items("2.1", [item("pi_other", "2.1", "OTHER-WORK-3c")])
        assert self.web.patch(f"/api/personas/{made}", json={"public": True}, headers=CSRF).status_code == 200
        return str(made)

    def shown(self) -> str:
        return "\n".join(self.recorder.seen)


@pytest.fixture
def scene(web: tuple[TestClient, Recorder], tmp_path: Path) -> Scene:
    return Scene(*web, tmp_path)


# ------------------------------------------------------------ the list across twins


def test_the_person_sees_only_their_own_conversations_and_the_ones_with_their_own_twin_are_set_apart(
    scene: Scene,
) -> None:
    scene.take()
    other = scene.other_twin()
    scene.as_("visitor")
    asked_by_visitor = scene.conversation()  # a colleague asks the person's twin
    scene.as_("person")
    mine = scene.conversation()  # the person with their own twin
    with_other = scene.conversation(other)  # the person with someone else's twin
    scene.say(mine, "我上周答应过谁什么")

    everything = scene.listing()
    assert [c["id"] for c in everything["conversations"]] == [with_other]
    assert everything["conversations"][0]["persona_id"] == other
    apart = scene.listing(mine="true")
    assert [c["id"] for c in apart["conversations"]] == [mine]
    assert apart["conversations"][0]["preview"] == "我回答了。"  # what was last said, for finding it
    # Nobody else's conversation with the person's own twin is in either list, whoever looks.
    assert asked_by_visitor not in json.dumps([everything, apart])
    assert everything["mine"] == apart["mine"] == {"persona_id": scene.persona, "pending": 0}
    # Filtered to one twin.
    assert scene.listing(**{"with": scene.persona})["conversations"] == []
    assert [c["id"] for c in scene.listing(**{"with": other})["conversations"]] == [with_other]

    scene.as_("visitor")
    theirs = scene.listing()
    assert [c["id"] for c in theirs["conversations"]] == [asked_by_visitor] and theirs["mine"] is None
    assert scene.listing(mine="true")["conversations"] == []  # the person's twin is not theirs

    scene.as_("admin")  # a manager's own conversations only, and no twin of their own
    assert scene.listing()["conversations"] == [] and scene.listing()["mine"] is None


def test_a_conversation_from_before_the_person_took_the_twin_is_an_ordinary_one(scene: Scene) -> None:
    scene.as_("person")  # made it, has not taken it: a manager like any other
    before = scene.conversation()
    scene.take()
    scene.as_("person")
    mine = scene.conversation()
    listed = scene.listing()
    assert [c["id"] for c in listed["conversations"]] == [before]
    assert [c["id"] for c in scene.listing(mine="true")["conversations"]] == [mine]


def test_deleted_conversations_and_twins_in_the_trash_are_not_listed_and_the_list_pages(scene: Scene) -> None:
    scene.take()
    other = scene.other_twin()
    scene.as_("person")
    gone = scene.conversation(other)
    kept = scene.conversation(other)
    headers = {**CSRF, "X-Twin-Persona": other}
    assert scene.web.delete(f"/api/conversations/{gone}", headers=headers).status_code == 200
    assert [c["id"] for c in scene.listing()["conversations"]] == [kept]
    first = scene.listing(offset=0)
    assert first["more"] is False
    assert scene.listing(offset=1)["conversations"] == []
    scene.as_("admin")
    assert scene.web.delete(f"/api/personas/{other}", headers=CSRF).status_code == 200
    scene.as_("person")
    assert scene.listing()["conversations"] == []


def test_tasks_come_with_the_list_and_the_ones_with_the_persons_own_twin_stay_with_it(scene: Scene) -> None:
    scene.take()
    other = scene.other_twin()
    scene.as_("person")
    with_own = WorkStore(scene.path).create("起草发布方案", PERSON, False, "self")
    with_other = WorkStore(scene.root / "personas" / other / "twin.db").create("整理周报", PERSON, True, "colleague")
    WorkStore(scene.path).create("别人交代的", VISITOR, True, "colleague")  # not theirs
    everything = scene.listing()
    assert [(t["task_id"], t["persona_id"]) for t in everything["tasks"]] == [(with_other.task_id, other)]
    apart = scene.listing(mine="true")
    assert [(t["task_id"], t["persona_id"]) for t in apart["tasks"]] == [(with_own.task_id, scene.persona)]
    assert scene.listing(offset=1)["tasks"] == []  # they come with the first page


def test_more_tasks_than_a_page_are_asked_for_by_their_own_offset_without_the_conversations(scene: Scene) -> None:
    scene.take()
    other = scene.other_twin()
    scene.as_("person")
    kept = scene.conversation(other)
    store = WorkStore(scene.root / "personas" / other / "twin.db")
    titles = [store.create(f"任务 {n}", PERSON, True, "colleague").task_id for n in range(EVERYONE_PAGE + 3)]
    first = scene.listing()
    assert len(first["tasks"]) == EVERYONE_PAGE and first["more_tasks"] is True
    assert [c["id"] for c in first["conversations"]] == [kept] and first["next"] == 1
    rest = scene.listing(task_offset=EVERYONE_PAGE)
    assert rest["more_tasks"] is False and rest["conversations"] == [] and rest["more"] is False
    seen = [t["task_id"] for t in first["tasks"]] + [t["task_id"] for t in rest["tasks"]]
    assert sorted(seen) == sorted(titles) and len(set(seen)) == len(titles)


def test_what_a_conversation_handed_to_the_person_shows_beside_it_and_the_person_sees_how_many_wait(
    scene: Scene,
) -> None:
    scene.take()
    scene.as_("visitor")
    asked = scene.conversation()
    scene.say(asked)
    made = team(scene.web).create_handoff(
        persona_id=scene.persona,
        owner=PERSON,
        conversation_id=asked,
        turn=2,
        asker=VISITOR,
        asker_name="访客",
        kind="decide",
        question=QUESTION,
    )
    assert made is not None
    assert scene.listing()["conversations"][0]["handoff"] == "等本人回复"
    scene.as_("person")
    assert scene.listing()["mine"] == {"persona_id": scene.persona, "pending": 1}
    assert (
        scene.web.post(
            f"/api/persona/handoffs/{made.id}/reply", json={"text": "好的"}, headers=scene.headers
        ).status_code
        == 200
    )
    assert scene.listing()["mine"]["pending"] == 0
    scene.as_("visitor")
    assert scene.listing()["conversations"][0]["handoff"] == "本人已回"


# ------------------------------------------------------------ the assistant


def test_the_person_is_answered_by_their_assistant_and_a_colleague_by_the_twin(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    mine = scene.conversation()
    final = scene.say(mine)
    assert "本人的助手" in scene.recorder.seen[0] and "数字分身" not in scene.recorder.seen[0]
    assert FAMILY in scene.shown() and sorted(final["citations"]) == ["pi_family", "pi_work"]
    scene.recorder.seen.clear()
    scene.as_("visitor")
    scene.say(scene.conversation())
    assert "数字分身" in scene.recorder.seen[0] and "本人的助手" not in scene.recorder.seen[0]
    # The conversation says whose tier it answers from.
    scene.as_("person")
    assert scene.web.get(f"/api/conversations/{mine}", headers=scene.headers).json()["audience"] == "self"


def test_a_conversation_of_the_colleague_tier_is_never_the_assistants_even_with_ones_own_twin(scene: Scene) -> None:
    scene.as_("person")  # has not taken the twin: a manager of it
    scene.say(scene.conversation())
    assert "数字分身" in scene.recorder.seen[0] and "本人的助手" not in scene.recorder.seen[0]


def test_a_promise_the_person_says_they_make_stands_in_their_ledger_at_once(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    mine = scene.conversation()
    final = scene.say(mine, "我答应王屿周五前给方案")
    assert final["commitment"]["what"] == "周五前给王屿发布方案" and final["commitment"]["to"] == "王屿"
    with PersonaStore(scene.path) as store:
        [entry] = store.list_ledger()
    assert entry.origin == "conversation" and entry.status is None and entry.review.value == "confirmed"
    assert entry.owner == "本人" and entry.counterpart == "王屿" and str(entry.due) == "2026-10-30"
    # Saved with the reply, so it reads the same after reloading; saying the same turn again is the same commitment.
    reread = scene.web.get(f"/api/conversations/{mine}", headers=scene.headers).json()
    assert reread["turns"][-1]["reply"]["commitment"]["entry_id"] == entry.entry_id
    # A colleague's conversation never makes one, whatever the model says.
    scene.as_("visitor")
    scene.say(scene.conversation(), "我答应王屿周五前给方案")
    with PersonaStore(scene.path) as store:
        assert len(store.list_ledger()) == 1
    # What the person changes in the commitments reads the same under the reply, and once they take it back (撤销) the
    # reply no longer says it was kept.
    scene.as_("person")
    edited = {"action": "edit", "changes": {"what": "下周一前给王屿发布方案"}}
    assert scene.web.post(f"/api/persona/ledger/{entry.entry_id}/review", json=edited, headers=scene.headers).is_success
    reread = scene.web.get(f"/api/conversations/{mine}", headers=scene.headers).json()
    assert reread["turns"][-1]["reply"]["commitment"]["what"] == "下周一前给王屿发布方案"
    undone = scene.web.post(
        f"/api/persona/ledger/{entry.entry_id}/review", json={"action": "reject"}, headers=scene.headers
    )
    assert undone.is_success
    reread = scene.web.get(f"/api/conversations/{mine}", headers=scene.headers).json()
    assert "commitment" not in reread["turns"][-1]["reply"]


# ------------------------------------------------------------ 记一下


def test_a_note_is_kept_without_asking_the_model_and_its_tier_is_the_persons_to_choose(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    mine = scene.conversation()
    final = scene.say(mine, f"记一下，下周三我请假陪家人复查 {NOTE}")
    assert scene.recorder.seen == []  # nothing was asked of the model
    assert final["reply"] == NOTE_REPLY and final["note"]["tier"] == "self"
    note_id = final["note"]["id"]
    with PersonaStore(scene.path) as store:
        source = store.get_source(note_id)
        assert source is not None and source.origin.startswith("note:")
        assert store.note_tiers() == {note_id: "self"}
    saved = scene.web.get(f"/api/conversations/{mine}", headers=scene.headers).json()
    assert [t["role"] for t in saved["turns"]] == ["user", "twin"]
    assert saved["turns"][-1]["reply"]["note"]["tier"] == "self"

    def set_tier(tier: str) -> Any:
        return scene.web.put(f"/api/persona/notes/{note_id}/tier", json={"tier": tier}, headers=scene.headers)

    assert set_tier("colleague").json()["tier"] == "colleague"
    with PersonaStore(scene.path) as store:
        assert store.note_tiers() == {note_id: "colleague"}
    reread = scene.web.get(f"/api/conversations/{mine}", headers=scene.headers).json()
    assert reread["turns"][-1]["reply"]["note"]["tier"] == "colleague"
    assert set_tier("self").json()["tier"] == "self"
    # 不存: the note is not kept after all.
    assert set_tier("none").json()["tier"] == "none"
    with PersonaStore(scene.path) as store:
        assert store.get_source(note_id) is None and store.note_tiers() == {}
    reread = scene.web.get(f"/api/conversations/{mine}", headers=scene.headers).json()
    assert reread["turns"][-1]["reply"]["note"]["tier"] == "none"
    assert set_tier("all").status_code == 400
    assert set_tier("self").status_code == 404  # gone


def test_a_note_kept_to_themself_does_not_reach_a_colleague_until_the_person_opens_it(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    final = scene.say(scene.conversation(), f"记一下，下周三请假复查 {NOTE}")
    note_id = final["note"]["id"]

    def colleague_asks() -> str:
        scene.as_("visitor")
        scene.recorder.seen.clear()
        scene.say(scene.conversation(), "下周三请假复查的事")
        shown = scene.shown()
        scene.as_("person")
        return shown

    # Before any memory stands on it, its own words are not found either.
    assert NOTE not in colleague_asks()
    opened = scene.web.put(f"/api/persona/notes/{note_id}/tier", json={"tier": "colleague"}, headers=scene.headers)
    assert opened.status_code == 200
    assert NOTE in colleague_asks()
    scene.web.put(f"/api/persona/notes/{note_id}/tier", json={"tier": "self"}, headers=scene.headers)
    assert NOTE not in colleague_asks()


def test_a_note_is_for_the_person_alone_and_only_in_their_own_conversation(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    note_id = scene.say(scene.conversation(), "记一下，周五不上班")["note"]["id"]
    for who in ("visitor", "admin"):
        scene.as_(who)
        denied = scene.web.put(f"/api/persona/notes/{note_id}/tier", json={"tier": "colleague"}, headers=scene.headers)
        assert denied.status_code == 403, who
        # In a conversation that is not the person's own, "记一下" is just a message.
        scene.recorder.seen.clear()
        said = scene.say(scene.conversation(), "记一下，周五不上班")
        assert "note" not in said and scene.recorder.seen, who
    with PersonaStore(scene.path) as store:
        assert list(store.note_tiers()) == [note_id]
    scene.as_("person")
    other = scene.web.put("/api/persona/notes/nope/tier", json={"tier": "self"}, headers=scene.headers)
    assert other.status_code == 404
    # What is not a note made by 记一下 (an ordinary memory) cannot be changed here.
    added = scene.web.post("/api/persona/notes", json={"text": "写下的一段话"}, headers=scene.headers).json()
    plain = scene.web.put(f"/api/persona/notes/{added['source_id']}/tier", json={"tier": "self"}, headers=scene.headers)
    assert plain.status_code == 404


def test_a_question_that_only_looks_like_a_note_is_answered(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    mine = scene.conversation()
    for text in ("记得我上周说过什么吗", "记一下", "记一下，我周五是不是不上班？"):
        scene.recorder.seen.clear()
        said = scene.say(mine, text)
        assert "note" not in said and scene.recorder.seen, text


# ------------------------------------------------------------ 看同事会得到什么


def test_the_trial_question_gets_what_a_colleague_really_gets_and_keeps_nothing(scene: Scene) -> None:
    scene.take()
    scene.as_("visitor")
    scene.recorder.seen.clear()
    real = scene.say(scene.conversation())
    real_input = scene.shown()
    scene.as_("person")
    mine = scene.conversation()
    logged_before = logged(scene.path)
    assert logged_before == 1  # what the colleague really asked
    scene.recorder.seen.clear()
    trial = scene.say(mine, QUESTION, preview=True)
    # The same items, as the model was shown them and as the answer cites them.
    assert trial["retrieved_ids"] == real["retrieved_ids"] and trial["citations"] == real["citations"]
    assert [c["id"] for c in trial["cited"]] == [c["id"] for c in real["cited"]] == ["pi_work"]
    assert trial["reply"] == real["reply"] and trial["mode"] == real["mode"]
    assert FAMILY not in scene.shown() and WORK in scene.shown() and WORK in real_input
    assert re.findall(r"\[(pi_[a-z]+)\]", scene.shown()) == re.findall(r"\[(pi_[a-z]+)\]", real_input)
    # What it left out is named, to the person.
    assert [w["id"] for w in trial["preview"]["withheld"]] == ["pi_family"]
    # Nothing was saved: not the question, not the answer, not what was asked.
    assert scene.web.get(f"/api/conversations/{mine}", headers=scene.headers).json()["turns"] == []
    assert logged(scene.path) == logged_before
    assert team(scene.web).handoffs(persona_id=scene.persona) == []


def test_the_trial_question_is_the_persons_alone(scene: Scene) -> None:
    scene.take()
    for who in ("visitor", "admin"):
        scene.as_(who)
        conversation = scene.conversation()
        body = {"messages": [{"role": "user", "content": QUESTION}], "conversation_id": conversation, "preview": True}
        assert scene.web.post("/api/persona/chat/stream", json=body, headers=scene.headers).status_code == 403, who
    scene.as_("person")
    plain = {"messages": [{"role": "user", "content": QUESTION}], "preview": True}
    assert scene.web.post("/api/persona/chat", json=plain, headers=scene.headers).status_code == 400
    # A twin that has not been taken has no person to try it out for.
    registry = scene.web.app.state.personas  # type: ignore[attr-defined]
    entry = registry.entry(scene.persona)
    for key in ("member", "approved_at"):
        entry.pop(key)
    assert scene.web.post("/api/persona/chat/stream", json=plain, headers=scene.headers).status_code == 403


def test_the_trial_question_sees_through_the_notes_kept_from_colleagues_too(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    mine = scene.conversation()
    scene.say(mine, f"记一下，周五要请假复查 {NOTE}")
    scene.recorder.seen.clear()
    trial = scene.say(mine, "周五请假复查的事", preview=True)
    assert NOTE not in scene.shown()
    assert trial["preview"]["withheld"] is not None


def test_a_note_kept_to_themself_is_not_in_a_managers_list_of_memories_nor_readable_by_them(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    note_id = scene.say(scene.conversation(), f"记一下，周五要请假复查 {NOTE}")["note"]["id"]
    listed = scene.web.get("/api/persona/sources", headers=scene.headers).json()
    assert [s["source_id"] for s in listed["items"]] == [note_id] and listed["summary"]["total"] == 1
    assert NOTE in scene.web.get(f"/api/persona/sources/{note_id}/text", headers=scene.headers).text
    scene.as_("admin")
    hidden = scene.web.get("/api/persona/sources", headers=scene.headers).json()
    assert hidden["items"] == [] and hidden["summary"]["total"] == 0
    assert scene.web.get(f"/api/persona/sources/{note_id}/text", headers=scene.headers).status_code == 404
    # Opened to colleagues, it is a memory like any other.
    scene.as_("person")
    scene.web.put(f"/api/persona/notes/{note_id}/tier", json={"tier": "colleague"}, headers=scene.headers)
    scene.as_("admin")
    assert [s["source_id"] for s in scene.web.get("/api/persona/sources", headers=scene.headers).json()["items"]] == [
        note_id
    ]
    assert NOTE in scene.web.get(f"/api/persona/sources/{note_id}/text", headers=scene.headers).text


def test_what_a_person_kept_in_a_twin_that_is_not_theirs_goes_with_them_when_they_say_so(scene: Scene) -> None:
    """The person said "这不是我": their notes kept to themself, the memory made from them, their conversations and
    the promises made there do not stay for whoever takes the twin next; what the meetings say stays."""
    scene.as_("admin")  # the administrator makes the twin for PERSON
    made = scene.web.post("/api/personas", json={"name": "认领的分身"}, headers=CSRF).json()["id"]
    path = scene.root / "personas" / made / "twin.db"
    with PersonaStore(path) as store:
        store.set_meta("built_at", "2026-01-01")
        store.replace_facet_items("2.1", [item("pi_work", "2.1", WORK)])
    headers = {**CSRF, "X-Twin-Persona": made}
    assert scene.web.put(f"/api/personas/{made}/claim", json={"claim": PERSON}, headers=CSRF).status_code == 200
    scene.as_("person")
    assert any(p["id"] == made and p["mine"] for p in scene.web.get("/api/personas").json())  # taken on signing in
    assert scene.web.post(f"/api/personas/{made}/approve", json={"public": False}, headers=CSRF).status_code == 200
    mine = scene.web.post("/api/conversations", json={}, headers=headers).json()["id"]
    sent = {"messages": [{"role": "user", "content": f"记一下，下周三请假复查 {NOTE}"}], "conversation_id": mine}
    final = scene.web.post("/api/persona/chat/stream", json=sent, headers=headers).text
    note_id = json.loads(final.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0])["note"]["id"]
    promised = {"messages": [{"role": "user", "content": "我答应王屿周五前给方案"}], "conversation_id": mine}
    assert scene.web.post("/api/persona/chat/stream", json=promised, headers=headers).status_code == 200
    with PersonaStore(path) as store:
        assert store.note_tiers() == {note_id: "self"} and len(store.list_ledger()) == 1
        noted = item("pi_note", "9.3", NOTE).model_copy(
            update={"evidence": [item("pi_note", "9.3", NOTE).evidence[0].model_copy(update={"source_id": note_id})]}
        )
        store.replace_facet_items("9.3", [noted])
    assert NOTE in scene.web.get(f"/api/persona/sources/{note_id}/text", headers=headers).text

    indexed = team(scene.web)
    assert [c.id for c in indexed.conversations(persona_id=made)] == [mine]
    assert scene.web.post(f"/api/personas/{made}/disown", headers=CSRF).json() == {"disowned": True}
    assert indexed.conversations(persona_id=made) == []  # the index forgets them now, not at the next start
    with PersonaStore(path) as store:
        assert store.get_source(note_id) is None and store.note_tiers() == {}
        assert store.list_ledger() == []
        assert store.list_conversations(PERSON) == []
        assert [i.item_id for i in store.list_items()] == ["pi_work"]  # what the meetings say stays
    assert list((path.parent / "kernel-snapshots").iterdir())  # kept before anything was removed

    # The administrator gives it to someone else, who takes it: none of it is theirs to read.
    scene.as_("admin")
    assert scene.web.put(f"/api/personas/{made}/claim", json={"claim": VISITOR}, headers=CSRF).status_code == 200
    scene.as_("visitor")
    assert any(p["id"] == made and p["mine"] for p in scene.web.get("/api/personas").json())
    assert scene.web.post(f"/api/personas/{made}/approve", json={"public": False}, headers=CSRF).status_code == 200
    assert scene.web.get(f"/api/persona/sources/{note_id}/text", headers=headers).status_code == 404
    assert scene.web.get(f"/api/conversations/{mine}", headers=headers).status_code == 404
    ledger = scene.web.get("/api/persona/ledger", headers=headers)
    assert ledger.status_code == 200 and "王屿" not in ledger.text


def test_without_sign_in_the_one_person_lists_their_conversations_and_no_twin_is_known_to_be_theirs(
    tmp_path: Path,
) -> None:
    app = create_app(Settings(db_path=tmp_path / "twin.db"), llm_factory=Recorder, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        made = web.post("/api/conversations", json={}, headers=CSRF).json()["id"]
        listed = web.get("/api/personas/conversations").json()
        assert [c["id"] for c in listed["conversations"]] == [made] and listed["mine"] is None
        assert web.get("/api/personas/conversations", params={"mine": "true"}).json()["conversations"] == []
        # Nobody is known to be the person, so no assistant: a note is a message, a trial question is refused.
        sent = {"messages": [{"role": "user", "content": "记一下，周五不上班"}], "conversation_id": made}
        final = web.post("/api/persona/chat/stream", json=sent, headers=CSRF)
        assert "note" not in final.text
        trial = web.post("/api/persona/chat/stream", json={**sent, "preview": True}, headers=CSRF)
        assert trial.status_code == 403


# ------------------------------------------------------------ 照镜子 · 随便说 · 记梦, and the crisis guard


@pytest.mark.parametrize(("reflection", "heading"), [("mirror", "照镜子"), ("free", "随便说"), ("dream", "记梦")])
def test_a_way_of_looking_at_oneself_is_the_assistants_and_keeps_no_question_or_promise(
    scene: Scene, reflection: str, heading: str
) -> None:
    scene.take()
    scene.as_("person")
    before = logged(scene.path)
    final = scene.say(scene.conversation(), "我答应王屿周五前给方案", reflection=reflection)
    [system] = [s for s in scene.recorder.seen if "本人的助手" in s]
    assert f"## 这一轮：{heading}" in system and "不下诊断" in system
    # Looking at oneself is neither a question the twin is asked to know more about nor a promise made.
    assert logged(scene.path) == before and "commitment" not in final
    with PersonaStore(scene.path) as store:
        assert store.list_ledger() == []
    # Asking as usual still keeps both.
    scene.recorder.seen.clear()
    scene.say(scene.conversation(), "我答应王屿周五前给方案")
    assert "## 这一轮" not in scene.recorder.seen[0] and logged(scene.path) == before + 1


def test_a_colleague_cannot_ask_the_twin_to_look_at_them(scene: Scene) -> None:
    scene.take()
    scene.as_("visitor")
    scene.say(scene.conversation(), reflection="mirror")
    assert "数字分身" in scene.recorder.seen[0] and "## 这一轮" not in scene.shown()


def test_a_message_of_ending_ones_life_stops_the_conversation_before_any_model(scene: Scene) -> None:
    from twin.persona.crisis import CRISIS_REPLY

    scene.take()
    for who in ("person", "visitor"):
        scene.as_(who)
        conversation = scene.conversation()
        before = logged(scene.path)
        final = scene.say(conversation, "最近总觉得活不下去了", reflection="mirror")
        assert scene.recorder.seen == []  # nothing was asked of the model, nothing looked up
        assert final["reply"] == CRISIS_REPLY and final["crisis"] is True and final["citations"] == []
        assert "12356" in final["reply"] and logged(scene.path) == before
        saved = scene.web.get(f"/api/conversations/{conversation}", headers=scene.headers).json()
        assert [t["role"] for t in saved["turns"]] == ["user", "twin"]
    # A note that says it is not kept as one: the guard comes first.
    scene.as_("person")
    final = scene.say(scene.conversation(), "记一下，我不想活了")
    assert final["crisis"] is True and "note" not in final


def test_in_the_persona_edition_whoever_uses_the_twin_without_sign_in_is_the_person(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One person's own twin on their own computer: the one person there is is answered by their assistant, can keep
    a note and look at themself."""
    monkeypatch.setenv("TWIN_EDITION", "persona")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    recorder = Recorder()
    app = create_app(
        Settings(db_path=tmp_path / "twin.db"), llm_factory=lambda: recorder, embedder_factory=HashingEmbedder
    )
    with TestClient(app, base_url="http://localhost") as web:
        made = web.post("/api/conversations", json={}, headers=CSRF).json()["id"]
        [twin] = web.get("/api/personas").json()
        assert (twin["mine"], twin["approved"]) == (True, True)
        assert web.get("/api/personas/conversations").json()["mine"]["persona_id"] == twin["id"]
        sent = {"messages": [{"role": "user", "content": "记一下，周五不上班"}], "conversation_id": made}
        assert '"note"' in web.post("/api/persona/chat/stream", json=sent, headers=CSRF).text
        with PersonaStore(tmp_path / "twin.db") as store:
            store.set_meta("built_at", "2026-01-01")
            store.replace_facet_items("2.1", [item("pi_work", "2.1", WORK)])
        asked = {**sent, "messages": [{"role": "user", "content": QUESTION}], "reflection": "mirror"}
        assert web.post("/api/persona/chat/stream", json=asked, headers=CSRF).status_code == 200
    [system] = [s for s in recorder.seen if "本人的助手" in s]
    assert "## 这一轮：照镜子" in system


# ------------------------------------------------------------ 自评记录


def test_the_person_says_of_an_answer_whether_it_is_like_them_and_it_is_kept_for_evaluation(scene: Scene) -> None:
    scene.take()
    scene.as_("person")
    conversation = scene.conversation()
    final = scene.say(conversation, "我最近在忙什么", reflection="mirror")
    rate = {"conversation_id": conversation, "reply": final["reply"], "rating": "unlike"}
    marked = scene.web.put("/api/persona/self-ratings", json=rate, headers=scene.headers)
    assert marked.status_code == 200 and marked.json() == {"rating": "unlike"}
    # Changed, it is the latest mark that counts; read back with the conversation.
    scene.web.put("/api/persona/self-ratings", json={**rate, "rating": "like"}, headers=scene.headers)
    saved = scene.web.get(f"/api/conversations/{conversation}", headers=scene.headers).json()
    assert [t.get("self_rating") for t in saved["turns"]] == [None, "like"]
    [kept] = scene.web.get("/api/persona/self-ratings", headers=scene.headers).json()["ratings"]
    assert (kept["question"], kept["reply"], kept["rating"], kept["reflection"]) == (
        "我最近在忙什么",
        final["reply"],
        "like",
        "mirror",
    )
    assert kept["turn_id"] == saved["turns"][1]["id"]
    # Only an answer the twin gave there: words it never said, or help given when the person spoke of harming
    # themself, are not marked.
    assert (
        scene.web.put(
            "/api/persona/self-ratings", json={**rate, "reply": "我说过的话"}, headers=scene.headers
        ).status_code
        == 404
    )
    crisis = scene.say(conversation, "最近总觉得活不下去了")
    refused = {**rate, "reply": crisis["reply"]}
    assert scene.web.put("/api/persona/self-ratings", json=refused, headers=scene.headers).status_code == 400
    with PersonaStore(scene.path) as store:
        store.append_conversation_turn(
            conversation, PERSON, "twin", "资料里没有。", {"reply": "资料里没有。", "abstain": True, "mode": "abstain"}
        )
    unknown = {**rate, "reply": "资料里没有。"}
    assert scene.web.put("/api/persona/self-ratings", json=unknown, headers=scene.headers).status_code == 400
    # Taken back, it is gone.
    scene.web.put("/api/persona/self-ratings", json={**rate, "rating": None}, headers=scene.headers)
    assert scene.web.get("/api/persona/self-ratings", headers=scene.headers).json()["ratings"] == []
    # Someone else talking with the twin is not asked whether it is like the person.
    scene.as_("visitor")
    theirs = scene.conversation()
    answer = scene.say(theirs, "他最近在忙什么")
    asked = {"conversation_id": theirs, "reply": answer["reply"], "rating": "like"}
    assert scene.web.put("/api/persona/self-ratings", json=asked, headers=scene.headers).status_code == 403
    assert scene.web.get("/api/persona/self-ratings", headers=scene.headers).status_code == 403


# ------------------------------------------------------------ 时间切片


def dated(item_id: str, facet: str, marker: str, day: dt.date) -> PersonaItem:
    made = item(item_id, facet, marker)
    return made.model_copy(update={"evidence": [e.model_copy(update={"date": day}) for e in made.evidence]})


@pytest.fixture
def years(scene: Scene) -> Scene:
    """What the person said of work in 2019 and of their family in 2024."""
    with PersonaStore(scene.path) as store:
        store.replace_facet_items("2.1", [dated("pi_work", "2.1", WORK, dt.date(2019, 5, 1))])
        store.replace_facet_items("9.3", [dated("pi_family", "9.3", FAMILY, dt.date(2024, 3, 1))])
    scene.take()
    return scene


def test_the_person_talks_with_themself_as_of_a_year_and_the_conversation_goes_on_so(years: Scene) -> None:
    scene = years
    scene.as_("person")
    conversation = scene.conversation()
    final = scene.say(conversation, as_of="2020-12-31")
    assert final["as_of"] == "2020-12-31"
    # What was known by then answers; what was said later is not used.
    assert WORK in scene.shown() and FAMILY not in scene.shown()
    opened = scene.web.get(f"/api/conversations/{conversation}", headers=scene.headers).json()
    assert opened["as_of"] == "2020-12-31"
    # Back to now: the conversation is the person as they are.
    scene.recorder.seen.clear()
    assert scene.say(conversation)["as_of"] is None
    assert FAMILY in scene.shown()
    assert "as_of" not in scene.web.get(f"/api/conversations/{conversation}", headers=scene.headers).json()
    # Deleted, nothing of it is kept.
    scene.say(conversation, as_of="2020-12-31")
    assert scene.web.delete(f"/api/conversations/{conversation}", headers=scene.headers).status_code == 200
    with PersonaStore(scene.path) as store:
        assert store.meta_with_prefix("conversation_as_of:") == {}


def test_before_anything_is_known_the_twin_says_so_and_asks_no_model(years: Scene) -> None:
    scene = years
    scene.as_("person")
    conversation = scene.conversation()
    final = scene.say(conversation, "那年你在想什么", as_of="2015-12-31")
    assert scene.recorder.seen == []
    assert final["abstain"] is True and final["as_of"] == "2015-12-31" and "2015 年" in final["reply"]
    saved = scene.web.get(f"/api/conversations/{conversation}", headers=scene.headers).json()
    assert [t["role"] for t in saved["turns"]] == ["user", "twin"] and saved["as_of"] == "2015-12-31"


def test_before_anything_is_known_the_twin_says_so_with_no_model_configured(years: Scene) -> None:
    scene = years
    scene.recorder.unconfigured = True
    scene.as_("person")
    conversation = scene.conversation()
    final = scene.say(conversation, "那年你在想什么", as_of="2015-12-31")
    assert final["abstain"] is True and "2015 年" in final["reply"]
    again = {"messages": [{"role": "user", "content": "那年呢"}], "conversation_id": conversation}
    again["as_of"] = "2015-12-31"
    answered = scene.web.post("/api/persona/chat", json=again, headers=scene.headers)
    assert answered.status_code == 200 and answered.json()["abstain"] is True
    # A year something is known by still needs the model.
    body = {"messages": [{"role": "user", "content": QUESTION}], "conversation_id": conversation, "as_of": "2020-12-31"}
    assert scene.web.post("/api/persona/chat/stream", json=body, headers=scene.headers).status_code == 503


def test_only_the_persons_own_conversation_looks_back_and_anyone_elses_answers_as_of_now(years: Scene) -> None:
    scene = years
    # A colleague asking as of a year is answered as of now, and nothing is kept of the year.
    scene.as_("visitor")
    theirs = scene.conversation()
    final = scene.say(theirs, "他最近在忙什么", as_of="2015-12-31")
    assert final["as_of"] is None and final["abstain"] is False and WORK in scene.shown()
    assert "as_of" not in scene.web.get(f"/api/conversations/{theirs}", headers=scene.headers).json()
    # A trial question is a colleague's too.
    scene.as_("person")
    scene.recorder.seen.clear()
    trial = scene.say(scene.conversation(), "最近在忙什么", preview=True, as_of="2015-12-31")
    assert trial["as_of"] is None and WORK in scene.shown()
    with PersonaStore(scene.path) as store:
        assert store.meta_with_prefix("conversation_as_of:") == {}
