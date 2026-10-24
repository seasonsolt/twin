"""The commitment ledger as chat material: the person's own chat sees the entries a question is about, a visitor's
chat, a channel's or an agent's never does."""

from __future__ import annotations

import datetime as dt
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
from twin.persona import ledger as lg
from twin.persona.chat import PersonaChat
from twin.persona.items import PersonaItem
from twin.persona.schema import ChatTurn, ReviewStatus
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.jobs import PersonaProcessing
from twin.web.persona import chat_payload

QUESTION = "老王答应我的报价方案到哪一步了？"
TODAY = dt.date(2026, 10, 20)


def entry(entry_id: str, kind: str, owner: str, day: str, what: str, **extra: Any) -> lg.LedgerEntry:
    return lg.LedgerEntry(
        entry_id=entry_id,
        source_id=f"s{day}",
        expression_id=f"s{day}:0001",
        meeting_date=dt.date.fromisoformat(day),
        meeting_title="周一经营会",
        kind=kind,  # type: ignore[arg-type]
        speaker="其他人1",
        quote=f"{what}，没问题",
        owner=owner,
        counterpart=lg.SELF,
        what=what,
        confidence=0.9,
        extractor=lg.LEDGER_VERSION,
        created_at="now",
        updated_at="now",
        **extra,
    )


LEDGER = [
    entry("0123456789abcdef", "commitment", "老王", "2026-10-12", "给华澜新报价方案", due=dt.date(2026, 10, 16)),
    entry(
        "fedcba9876543210",
        "progress",
        "老王",
        "2026-10-19",
        "报价方案已发出",
        relates_to="0123456789abcdef",
        status="claimed_done",
    ),
    entry("00000000000000aa", "commitment", "陈工", "2026-10-12", "修好报表导出", due=dt.date(2026, 10, 15)),
]
CITED = "le_0123456789abcdef"


def seed(path: Path, ledger: list[lg.LedgerEntry] = LEDGER) -> None:
    with PersonaStore(path) as store:
        store.set_meta("built_at", "2026-10-19")
        store.replace_facet_items(
            "2.1", [PersonaItem(item_id="pi_test", facet_id="2.1", statement="回款优先", evidence=[])]
        )
        for e in ledger:
            store.put_ledger_entry(e)


class Recorder:
    """A model that answers from the first ledger entry it is shown, and keeps every chat prompt."""

    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.llm = FakeLLM(self.handle)

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            return {}
        self.prompts.append(user)
        cited = [CITED] if CITED in user else []
        return {"reply": "老王说已经发了。", "citations": cited, "confidence": 0.9, "mode": "grounded"}


def test_the_persons_chat_answers_from_the_ledger_entries_the_question_is_about(tmp_path: Path) -> None:
    seed(tmp_path / "twin.db")
    recorder = Recorder()
    settings = Settings(db_path=tmp_path / "twin.db")
    with PersonaStore(tmp_path / "twin.db") as store:
        chat = PersonaChat(store, recorder.llm, HashingEmbedder(), settings, ledger=True, audience="self")
        reply = chat.reply([ChatTurn(role="user", content=QUESTION)], today=TODAY)
        [prompt] = recorder.prompts
        assert "承诺账本" in prompt
        assert (
            "- [le_0123456789abcdef] 2026-10-12 周一经营会 · 承诺：老王（对我）给华澜新报价方案；截止 2026-10-16，"
            "已过期；当前状态：负责人说已完成；本人未确认。原话（其他人1 说）：「给华澜新报价方案，没问题」"
        ) in prompt
        assert "[le_fedcba9876543210]" in prompt and "报告的状态：负责人说已完成" in prompt
        # A ledger entry is citable; unreviewed, it is machine-read, so it is not trusted like the person's words.
        assert reply.citations == [CITED] and not reply.abstain and reply.confidence == 0.6
        cited = chat_payload(store, reply)["cited"]
        assert cited == [
            {
                "id": CITED,
                "kind": "ledger",
                "ledger_kind": "承诺",
                "date": "2026-10-12",
                "channel": "周一经营会",
                "text": "给华澜新报价方案，没问题",
            }
        ]
        store.put_ledger_entry(LEDGER[0].model_copy(update={"review": ReviewStatus.CONFIRMED}))
        again = chat.reply([ChatTurn(role="user", content=QUESTION)], today=TODAY)
        assert again.confidence == 0.9 and "本人已确认" in recorder.prompts[-1]


def test_the_command_line_chat_is_the_persons_own_with_the_ledger(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`twin persona chat` is the person at their own terminal: their tier and their promises, unlike a colleague."""
    from typer.testing import CliRunner

    from twin import cli

    config = tmp_path / "twin.toml"
    config.write_text('target_name = "合成人物"\n', encoding="utf-8")
    settings = Settings(db_path=tmp_path / "twin.db", target_name="合成人物")
    seed(settings.db_path)
    with PersonaStore(settings.db_path) as store:
        private = PersonaItem(
            item_id="pi_family", facet_id="9.3", statement="他家里的事 PRIVATE-FAMILY-5d", evidence=[]
        )
        store.replace_facet_items("9.3", [private])
    recorder = Recorder()
    monkeypatch.setattr(cli, "_settings", lambda ctx: settings)
    monkeypatch.setattr(cli, "_llm", lambda settings, **kwargs: recorder.llm)
    monkeypatch.setattr(cli, "_embedder", lambda settings: HashingEmbedder())
    result = CliRunner().invoke(cli.app, ["--config", str(config), "persona", "chat", QUESTION + "家里的事"])
    assert result.exit_code == 0, result.output
    [prompt] = recorder.prompts
    assert "承诺账本" in prompt and "PRIVATE-FAMILY-5d" in prompt


def test_without_the_ledger_flag_the_chat_never_sees_it(tmp_path: Path) -> None:
    seed(tmp_path / "twin.db")
    recorder = Recorder()
    with PersonaStore(tmp_path / "twin.db") as store:
        reply = PersonaChat(store, recorder.llm, HashingEmbedder(), Settings(db_path=tmp_path / "twin.db")).reply(
            [ChatTurn(role="user", content=QUESTION)], today=TODAY
        )
    assert "承诺账本" not in recorder.prompts[0] and "le_" not in recorder.prompts[0]
    assert reply.citations == []


def test_a_colleagues_conversation_never_has_the_ledger_even_when_asked_for(tmp_path: Path) -> None:
    seed(tmp_path / "twin.db")
    recorder = Recorder()
    with PersonaStore(tmp_path / "twin.db") as store:
        chat = PersonaChat(store, recorder.llm, HashingEmbedder(), Settings(db_path=tmp_path / "twin.db"), ledger=True)
        assert chat.audience == "colleague" and not chat.ledger
        chat.reply([ChatTurn(role="user", content=QUESTION)], today=TODAY)
    assert "承诺账本" not in recorder.prompts[0] and "le_" not in recorder.prompts[0]


def test_a_past_date_sees_only_what_was_said_by_then(tmp_path: Path) -> None:
    seed(tmp_path / "twin.db")
    recorder = Recorder()
    with PersonaStore(tmp_path / "twin.db") as store:
        PersonaChat(
            store, recorder.llm, HashingEmbedder(), Settings(db_path=tmp_path / "twin.db"), ledger=True, audience="self"
        ).reply([ChatTurn(role="user", content=QUESTION)], as_of=dt.date(2026, 10, 13))
    assert "[le_0123456789abcdef]" in recorder.prompts[0] and "le_fedcba9876543210" not in recorder.prompts[0]
    assert "当前状态：进行中" in recorder.prompts[0]


CSRF = {"X-Twin": "1"}
MEMBER = "member@xjjk.com"
OTHER = "other@xjjk.com"


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[TestClient, Recorder]]:
    monkeypatch.setenv("TWIN_SMTP_PASSWORD", "test-only")
    monkeypatch.setattr(PersonaProcessing, "queue", lambda _: None)
    sender = MagicMock()
    monkeypatch.setattr("twin.web.auth.send_code", sender)
    settings = Settings(
        db_path=tmp_path / "twin.db",
        auth=AuthSettings(
            enabled=True, smtp=SMTPSettings(host="smtp.example.com", username="test", from_address="t@example.com")
        ),
    )
    recorder = Recorder()
    app = create_app(settings, llm_factory=lambda: recorder.llm, embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        client.app.state.sender = sender  # type: ignore[attr-defined]
        yield client, recorder


def login(web: TestClient, email: str) -> str:
    web.post("/api/auth/request", json={"email": email}, headers=CSRF)
    code = str(web.app.state.sender.call_args.args[2])  # type: ignore[attr-defined]
    assert web.post("/api/auth/verify", json={"email": email, "code": code}, headers=CSRF).status_code == 200
    return web.cookies["twin_session"]


def test_a_visitor_of_a_public_twin_never_reaches_the_ledger(web: tuple[TestClient, Recorder], tmp_path: Path) -> None:
    client, recorder = web
    login(client, MEMBER)
    persona = client.post("/api/personas", json={"name": "测试分身"}, headers=CSRF).json()["id"]
    seed(tmp_path / "personas" / persona / "twin.db")
    # 张总 is the person this twin is made for, who has taken it and said it is all right.
    assert client.put(f"/api/personas/{persona}/claim", json={"claim": MEMBER}, headers=CSRF).status_code == 200
    assert [p["mine"] for p in client.get("/api/personas").json()] == [True]
    assert client.post(f"/api/personas/{persona}/approve", json={"public": True}, headers=CSRF).status_code == 200
    headers = {**CSRF, "X-Twin-Persona": persona}
    body = {"messages": [{"role": "user", "content": QUESTION}]}
    owned = client.post("/api/persona/chat/stream", json=body, headers=headers)
    assert owned.status_code == 200 and CITED in owned.text
    assert "承诺账本" in recorder.prompts[-1]
    login(client, OTHER)
    visited = client.post("/api/persona/chat/stream", json=body, headers=headers)
    assert visited.status_code == 200 and "event: final" in visited.text and CITED not in visited.text
    assert len(recorder.prompts) == 2 and "承诺账本" not in recorder.prompts[-1]
