"""P2.5 生前 / 身后: once the memory is sealed nothing grows in it. Every write to it is refused, whichever way it
comes (the web, the command line, the background); reading it and talking with it go on, and talking leaves no trace
in it. Sealing snapshots the store first, and that snapshot is kept."""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from pydantic import BaseModel
from typer.testing import CliRunner

from twin import cli
from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import lifecycle
from twin.persona.assistant import SEALED_NOTE_REPLY
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.lifecycle import MemorySealed, seal
from twin.persona.profile import build_profile, profile_stale
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.sources import parse_note
from twin.persona.store import SNAPSHOT_KEEP, PersonaStore, list_snapshots
from twin.web import create_app
from twin.web.jobs import PersonaProcessing
from twin.web.persona import sealed_write
from twin.web.system import team_path

CSRF = {"X-Twin": "1"}
WORK = "ALPHA-WORK-1f"

# Every write a sealed twin refuses, written out: a route added later is either listed here or in ``OPEN``, so
# whoever adds it decides whether it changes the memory.
SEALED = {
    # 资料：导入、转写、删、重抽、说话人和别名
    ("POST", "/api/uploads"),
    ("PUT", "/api/uploads/{upload_id}"),
    ("DELETE", "/api/uploads/{upload_id}"),
    ("POST", "/api/uploads/{upload_id}/finish"),
    ("POST", "/api/persona/import"),
    ("POST", "/api/persona/notes"),
    ("PUT", "/api/persona/notes/{source_id}/tier"),
    ("DELETE", "/api/persona/sources/{source_id}"),
    ("POST", "/api/persona/sources/{source_id}/reextract"),
    ("POST", "/api/persona/sources/{source_id}/transcribe"),
    ("PUT", "/api/persona/sources/{source_id}/speaker"),
    ("POST", "/api/persona/sources/{source_id}/adopt-voice"),
    ("POST", "/api/persona/sources/{source_id}/adopt-portrait"),
    ("POST", "/api/persona/transcripts/names"),
    ("PUT", "/api/persona/transcripts/{source_id}/speakers"),
    ("POST", "/api/persona/transcripts/not-mine"),
    ("POST", "/api/persona/aliases"),
    ("DELETE", "/api/persona/aliases/{name}"),
    # 整理 / 重建
    ("POST", "/api/persona/build"),
    ("POST", "/api/kernel/rebuild"),
    # 补一补、人生回顾、问卷
    ("POST", "/api/persona/fill/draft"),
    ("POST", "/api/persona/fill/preview"),
    ("POST", "/api/persona/fill/keep"),
    ("POST", "/api/persona/life-review/skip"),
    ("PUT", "/api/persona/questionnaire/draft"),
    ("POST", "/api/persona/questionnaire/submit"),
    ("POST", "/api/persona/followups/{followup_id}/answer"),
    ("POST", "/api/persona/followups/{followup_id}/status"),
    # 条目和档位
    ("POST", "/api/persona/items/{item_id}/review"),
    ("PUT", "/api/persona/items/{item_id}/tier"),
    # 剖析观察、自评
    ("POST", "/api/persona/observations"),
    ("PUT", "/api/persona/observations/{observation_id}/mark"),
    ("PUT", "/api/persona/self-ratings"),
    # The will is the person's while alive; sealed, it stands as they left it (P2.2).
    ("POST", "/api/persona/will/heirs"),
    ("PUT", "/api/persona/will/heirs/{heir_id}"),
    ("DELETE", "/api/persona/will/heirs/{heir_id}"),
    # 身份、声音和形象
    ("PUT", "/api/identity"),
    ("PUT", "/api/identity/avatar-preset"),
    ("POST", "/api/identity/onboarding-complete"),
    ("PUT", "/api/me/portrait"),
    ("DELETE", "/api/me/portrait"),
    ("PUT", "/api/me/voice"),
    ("DELETE", "/api/me/voice"),
    # 合成同意：冻结后不再由谁替本人同意或撤回
    ("POST", "/api/me/consent"),
    # 承诺账本
    ("POST", "/api/persona/ledger/build"),
    ("POST", "/api/persona/ledger/{entry_id}/review"),
    ("POST", "/api/persona/ledger/{entry_id}/accept"),
    ("POST", "/api/persona/ledger/{entry_id}/decline"),
    # 团队版：本人的转交、答复、团队答案、代问、视角、助手任务
    ("POST", "/api/persona/handoffs/{handoff_id}/reply"),
    ("POST", "/api/persona/handoffs/{handoff_id}/draft"),
    ("POST", "/api/persona/handoffs/{handoff_id}/accept"),
    ("POST", "/api/persona/handoffs/{handoff_id}/decline"),
    ("POST", "/api/persona/handoffs/{handoff_id}/dismiss"),
    ("POST", "/api/persona/handoffs/{handoff_id}/restore"),
    ("POST", "/api/persona/handoffs/{handoff_id}/often/decline"),
    ("POST", "/api/persona/handoffs/reply-many"),
    ("POST", "/api/persona/answers/{conversation_id}/{turn}/confirm"),
    ("POST", "/api/persona/answers/{conversation_id}/{turn}/correct"),
    ("POST", "/api/persona/team-answers"),
    ("PATCH", "/api/persona/team-answers/{answer_id}"),
    ("POST", "/api/persona/team-answers/{answer_id}/keep"),
    ("POST", "/api/persona/team-answers/{answer_id}/withdraw"),
    ("POST", "/api/persona/delegations/{delegation_id}/forward"),
    ("POST", "/api/persona/delegations/{delegation_id}/skip"),
    ("POST", "/api/persona/delegations/{delegation_id}/ask"),
    ("POST", "/api/persona/lenses"),
    ("POST", "/api/persona/lenses/preview"),
    ("PATCH", "/api/persona/lenses/{lens_id}"),
    ("POST", "/api/persona/lenses/{lens_id}/pause"),
    ("POST", "/api/persona/lenses/{lens_id}/resume"),
    ("POST", "/api/persona/lenses/{lens_id}/withdraw"),
    ("POST", "/api/persona/lenses/{lens_id}/uses/{use_id}/correct"),
    ("POST", "/api/persona/lenses/ask-owner"),
    ("POST", "/api/persona/lenses/{lens_id}/ask"),
    ("POST", "/api/persona/work"),
    ("POST", "/api/persona/work/{task_id}/stop"),
    ("DELETE", "/api/persona/work/{task_id}"),
}
# Writes that go on: talking with the twin, the conversations themselves, hearing an answer, a channel to talk in.
OPEN = {
    ("POST", "/api/persona/chat"),
    ("POST", "/api/persona/chat/stream"),
    ("POST", "/api/persona/chat/stream-with-files"),
    ("POST", "/api/conversations"),
    ("PATCH", "/api/conversations/{conversation_id}"),
    ("DELETE", "/api/conversations/{conversation_id}"),
    ("POST", "/api/media/audio"),
    ("POST", "/api/media/audio/stream"),
    ("POST", "/api/media/script"),
    ("POST", "/api/media/clip"),
    ("POST", "/api/media/video"),
    ("POST", "/api/media/export"),
    ("PUT", "/api/channels/wecom"),
    ("DELETE", "/api/channels/wecom"),
    # An heir opens the sealed twin and leaves it (P2.7): sessions and the heirs' log, not the memory.
    ("POST", "/api/heir/open"),
    ("POST", "/api/heir/leave"),
}


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


class Promiser(FakeLLM):
    """Answers every chat, citing what it is shown, and says the person made a promise."""

    def __init__(self) -> None:
        super().__init__(self.handle)
        self.asked = 0

    @staticmethod
    def meta(text: str) -> dict[str, Any]:
        return {
            "citations": sorted(set(re.findall(r"\[(pi_[a-z]+)\]", text))),
            "confidence": 0.9,
            "mode": "grounded",
            "asked": "工作",
            "answered": True,
            "topic_facets": ["2.1"],
            "promise_what": "周五前给王屿发布方案",
            "promise_to": "王屿",
            "promise_due": dt.date.today().isoformat(),
        }

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            return {}
        self.asked += 1
        return {"reply": "我回答了。", **self.meta(system + user)}

    async def stream(self, **kwargs: Any) -> Any:
        self.asked += 1
        yield "我回答了。\n<<<META>>>\n" + json.dumps(self.meta(kwargs["system"] + kwargs["user"]), ensure_ascii=False)


def count(path: Path, table: str) -> int:
    with closing(sqlite3.connect(path)) as db:
        return int(db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def seeded(path: Path) -> None:
    with PersonaStore(path) as store:
        store.set_meta("built_at", "2026-01-01")
        store.replace_facet_items("2.1", [item("pi_work", "2.1", WORK)])


def sealed_now(path: Path) -> Path | None:
    with PersonaStore(path) as store:
        return seal(store)


@pytest.fixture
def queued(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Every build queued (``PersonaProcessing.queue``), which none of these tests runs."""
    calls: list[int] = []
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: calls.append(1))
    return calls


def behind_the_heirs_door(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reach the twin as if through the heirs' way in: in the persona edition a sealed twin answers nobody else at all
    (``web.heir_door.HeirsOnlyMiddleware``, tested in ``tests/test_heir_door.py``); what is tested here is the twin's
    own layer behind it, which keeps nothing whoever reaches it."""
    monkeypatch.setattr("twin.web.heir_door.own_twin_sealed", lambda registry, edition: False)


def persona_app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, llm: FakeLLM, edition: str = "persona") -> Any:
    monkeypatch.setenv("TWIN_EDITION", edition)
    return create_app(Settings(db_path=tmp_path / "twin.db"), llm_factory=lambda: llm, embedder_factory=HashingEmbedder)


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, queued: list[int]) -> Iterator[tuple[TestClient, Promiser]]:
    llm = Promiser()
    with TestClient(persona_app(tmp_path, monkeypatch, llm), base_url="http://localhost") as client:
        yield client, llm


# ------------------------------------------------------------ the state and the seal


def test_a_memory_is_alive_until_sealed_and_sealing_snapshots_it_first_and_keeps_that_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    seeded(path)
    with PersonaStore(path) as store:
        assert (lifecycle.state(store), lifecycle.sealed_at(store)) == ("alive", None)
        assert not lifecycle.sealed_path(path)
        snapshot = seal(store, dt.datetime(2026, 10, 30, 8, 0, tzinfo=dt.UTC))
        assert (lifecycle.state(store), lifecycle.sealed_at(store)) == ("sealed", "2026-10-30T08:00:00+00:00")
        # Sealing again changes nothing and takes no other snapshot.
        assert seal(store) is None and lifecycle.sealed_at(store) == "2026-10-30T08:00:00+00:00"
        with pytest.raises(MemorySealed):
            lifecycle.refuse_if_sealed(store)
    assert lifecycle.sealed_path(path)
    assert not lifecycle.sealed_path(tmp_path / "missing.db")
    # The snapshot is the memory as it was just before: alive, with what it held.
    assert snapshot is not None and snapshot.name.endswith("-sealed.db")
    with closing(sqlite3.connect(snapshot)) as db:
        assert db.execute("SELECT value FROM p_meta WHERE key = 'lifecycle'").fetchone() is None
        assert db.execute("SELECT COUNT(*) FROM p_items").fetchone()[0] == 1
    # Later snapshots (upgrades, restores) never push it out.
    with PersonaStore(path) as store:
        for n in range(SNAPSHOT_KEEP + 2):
            store.snapshot(f"later{n}")
    kept = list_snapshots(path)
    assert snapshot in kept and len(kept) == SNAPSHOT_KEEP + 1


# ------------------------------------------------------------ every write on the web


def test_the_written_list_of_writes_is_every_route_that_is_not_a_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = persona_app(tmp_path, monkeypatch, Promiser(), edition="team")
    context = app.state.personas.application(app.state.personas.data["personas"][0]["id"])
    writes = {
        (method, route.path)
        for route in context.routes
        if isinstance(route, APIRoute)
        for method in (route.methods or set()) - {"GET", "HEAD"}
    }
    assert writes == SEALED | OPEN
    assert {w for w in writes if sealed_write(*w)} == SEALED
    # Reading is never refused.
    assert not any(sealed_write(method, path) for _, path in writes for method in ("GET", "HEAD"))


def concrete(path: str) -> str:
    return re.sub(r"\{[^}]+\}", "x1", path)


@pytest.mark.parametrize("edition", ["persona", "team"])
def test_a_sealed_twin_refuses_every_write_to_its_memory_and_nothing_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, queued: list[int], edition: str
) -> None:
    # The team edition has no heirs' door: its sealed twin goes on being read as ever.
    if edition == "persona":
        behind_the_heirs_door(monkeypatch)
    path = tmp_path / "twin.db"
    seeded(path)
    with TestClient(persona_app(tmp_path, monkeypatch, Promiser(), edition), base_url="http://localhost") as web:
        before = {w: web.request(w[0], concrete(w[1]), json={}, headers=CSRF).status_code for w in sorted(SEALED)}
        assert 423 not in before.values()
        assert web.get("/api/persona/will").json()["sealed"] is False
        sealed_now(path)
        queued.clear()  # by the writes made alive
        with PersonaStore(path) as store:
            revision, signature = store.memory_revision(), store.items_signature()
        for method, route in sorted(SEALED):
            response = web.request(method, concrete(route), json={}, headers=CSRF)
            if edition == "persona" and team_path(route):
                # Not there at all in the persona edition.
                assert response.status_code == 404, route
                continue
            assert response.status_code == 423, (method, route, response.text)
            assert response.json() == {"detail": "记忆已冻结，不能再改动", "code": "memory_sealed"}
        with PersonaStore(path) as store:
            assert (store.memory_revision(), store.items_signature()) == (revision, signature)
        for method, route in sorted(OPEN):
            if edition == "persona" and team_path(route):
                continue
            response = web.request(method, concrete(route), json={}, headers=CSRF)
            assert response.status_code != 423, (method, route)
        # Reading goes on.
        for route in ("/api/persona/items", "/api/persona/sources", "/api/persona/life-story", "/api/persona/coverage"):
            assert web.get(route).status_code == 200, route
        # The will says it is sealed, so the page shows it as it stands before anything is tried.
        assert web.get("/api/persona/will").json()["sealed"] is True
    with PersonaStore(path) as store:
        assert store.items_signature() == signature
    assert queued == []


# ------------------------------------------------------------ talking leaves no trace


def test_a_sealed_twin_answers_but_logs_no_question_keeps_no_promise_and_takes_no_note(
    web: tuple[TestClient, Promiser], tmp_path: Path, queued: list[int], monkeypatch: pytest.MonkeyPatch
) -> None:
    behind_the_heirs_door(monkeypatch)
    client, llm = web
    path = tmp_path / "twin.db"
    seeded(path)
    conversation = client.post("/api/conversations", json={}, headers=CSRF).json()["id"]

    def say(text: str) -> dict[str, Any]:
        sent = {"messages": [{"role": "user", "content": text}], "conversation_id": conversation}
        response = client.post("/api/persona/chat/stream", json=sent, headers=CSRF)
        assert response.status_code == 200 and "event: final" in response.text, response.text
        return json.loads(response.text.split("event: final\ndata: ", 1)[1].split("\n\n", 1)[0])  # type: ignore[no-any-return]

    # Alive, the same words log the question and keep the promise.
    say("我这周答应过谁什么")
    assert (count(path, "p_chat_log"), count(path, "p_ledger")) == (1, 1)
    sealed_now(path)
    sources = count(path, "p_sources")

    final = say("我这周答应过谁什么")
    assert final["reply"] == "我回答了。" and final["citations"] == ["pi_work"]
    assert "commitment" not in final and not final.get("promise_what")
    noted = say("记一下，下周三我请假")
    assert noted["reply"] == SEALED_NOTE_REPLY and "note" not in noted
    assert (count(path, "p_chat_log"), count(path, "p_ledger"), count(path, "p_sources")) == (1, 1, sources)
    assert queued == []
    with PersonaStore(path) as store:
        assert store.chat_demand() == {"2.1": (1, 0)}  # what was counted alive, and nothing since
    # The conversation itself is kept, to be read again.
    turns = client.get(f"/api/conversations/{conversation}").json()["turns"]
    assert [t["role"] for t in turns][-4:] == ["user", "twin", "user", "twin"]
    assert llm.asked == 2


# ------------------------------------------------------------ the background


def test_a_sealed_twin_is_not_built_again_at_start_up_or_by_a_build_already_queued(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, queued: list[int]
) -> None:
    behind_the_heirs_door(monkeypatch)
    path = tmp_path / "twin.db"
    seeded(path)
    with PersonaStore(path) as store:
        # A source added after the last build and a kernel older than the running one: alive, both rebuild.
        store.put_source(parse_note("周五不上班", Settings(db_path=path)))
        store.set_meta("built_at", "2000-01-01T00:00:00+00:00")
        assert profile_stale(store)
        seal(store)
        assert not profile_stale(store)
        with pytest.raises(MemorySealed):
            build_profile(store, Promiser(), Settings(db_path=path))
    with TestClient(persona_app(tmp_path, monkeypatch, Promiser()), base_url="http://localhost") as web:
        assert queued == []
        context = web.app.state.personas.application("default")  # type: ignore[attr-defined]
        # A build that was queued before the seal does nothing when it runs.
        assert context.state.processing.build(lambda _: None) == {"sealed": True}
        status = web.get("/api/status").json()
        assert status["kernel"]["scope"] == "none"
    with PersonaStore(path) as store:
        assert store.get_meta("built_at") == "2000-01-01T00:00:00+00:00"


# ------------------------------------------------------------ the command line


def test_the_command_line_refuses_to_change_a_sealed_memory_and_its_chat_leaves_no_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "make_llm", lambda _: Promiser())
    config = tmp_path / "twin.toml"
    config.write_text('target_name = "张明"\ndb_path = "twin.db"\n', encoding="utf-8")
    (tmp_path / "笔记.md").write_text("钱进了账户才算数。", encoding="utf-8")
    path = tmp_path / "twin.db"
    seeded(path)
    sealed_now(path)

    def run(*args: str) -> Any:
        return CliRunner().invoke(cli.app, ["--config", str(config), *args])

    for args in (
        ("persona", "import", "笔记.md"),
        ("persona", "note", "周五不上班"),
        ("persona", "reextract", "s1"),
        ("persona", "build"),
        ("kernel", "rebuild"),
    ):
        result = run(*args)
        assert result.exit_code == 1 and "记忆已冻结" in result.stderr, (args, result.stdout, result.stderr)
    skipped = run("kernel", "rebuild", "--all")
    assert skipped.exit_code == 0 and "记忆已冻结，跳过" in skipped.stdout
    answered = run("persona", "chat", "你看重什么？")
    assert answered.exit_code == 0 and "我回答了。" in answered.stdout
    assert (count(path, "p_sources"), count(path, "p_chat_log"), count(path, "p_ledger")) == (0, 0, 0)
