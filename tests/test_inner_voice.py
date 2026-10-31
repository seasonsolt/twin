"""内在声音 (P3.2): the person's own principles said back to them, looked up only in what they value and how they
decide and in their own words, never telling them what to do, and leaving nothing behind."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.chat import PersonaChat, index_persona
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.reflection import VOICE_ASK, VOICE_HEAD, VOICE_NONE, commands
from twin.persona.schema import ChatReply, ChatTurn, EvidenceClass, SourceKind
from twin.persona.sources import parse_chat
from twin.persona.store import PersonaStore
from twin.persona.tiers import SELF

SAID = {
    "money": ("2.1", "朋友借钱，钱的事先说清楚再谈感情"),
    "night": ("3.1", "大事我都睡一晚再定"),
    "fish": ("9.1", "朋友约我周末钓鱼，借着聊聊"),
}
QUESTION = "朋友找我借钱，我很纠结"


@pytest.fixture
def path(tmp_path: Path) -> Path:
    settings = Settings()
    path = tmp_path / "twin.db"
    with PersonaStore(path) as store:
        lines = [f"2026-09-0{n + 1} 10:00 本人：{said}" for n, (_, said) in enumerate(SAID.values())]
        store.put_source(parse_chat("家里.txt", "\n".join(lines) + "\n", settings))
        store.set_meta("built_at", "2026-10-01")
        expressions = store.list_expressions()
        for key, (facet, said) in SAID.items():
            e = next(e for e in expressions if said in e.text)
            evidence = PEvidence(
                expression_id=e.expression_id,
                source_id=e.expression_id.split("#", 1)[0],
                source_kind=SourceKind.CHAT,
                evidence_class=EvidenceClass.SELF_REPORT,
                quote=e.text,
                date=e.date,
            )
            store.replace_facet_items(facet, [PersonaItem(item_id=f"pi_{key}", facet_id=facet, statement=said,
                                                          evidence=[evidence])])  # fmt: skip
        index_persona(store, HashingEmbedder(), settings)
    return path


class Voice(FakeLLM):
    """The model: each answer it is asked for is the next of ``replies``, citing what it was shown of the money item."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        super().__init__(self.handle)

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            return {}
        cited = ["pi_money"] if "pi_money" in user else []
        return {"reply": self.replies.pop(0), "citations": cited, "confidence": 0.8, "mode": "grounded"}


def chat(store: PersonaStore, llm: FakeLLM) -> PersonaChat:
    return PersonaChat(store, llm, HashingEmbedder(), Settings(), audience=SELF, assistant=True, reflection="voice")


def drafts(llm: FakeLLM) -> list[tuple[str, str, str]]:
    return [c for c in llm.calls if c[0] == "ChatDraft"]


def test_it_looks_only_in_what_the_person_values_and_how_they_decide(path: Path) -> None:
    llm = Voice("你说过：“钱的事先说清楚再谈感情”。你会怎么选？")
    with PersonaStore(path) as store:
        reply = chat(store, llm).reply([ChatTurn(role="user", content=QUESTION)])
    [(_, system, user)] = drafts(llm)
    assert "## 这一轮：内在声音" in system
    assert {"pi_money", "pi_night"} <= set(reply.retrieved_ids) and "pi_fish" not in reply.retrieved_ids
    assert "pi_fish" not in user
    # Their own words are still there to be said back, whatever they were about.
    assert "钓鱼" in user
    assert reply.citations == ["pi_money"] and "你说过" in reply.reply


@pytest.mark.parametrize(
    ("text", "found"),
    [
        ("你应该先把钱的事说清楚。", ["你应该"]),
        ("我建议你等一晚。", ["我建议你"]),
        ("你必须拒绝他。", ["你必须"]),
        ("这次千万别借。", ["千万别"]),
        ("你得想清楚。", ["你得"]),
        ("You should wait.", ["You should"]),
        # Their own words in quotation marks are theirs to have said, whatever they say.
        ("你说过：“钱的事一定要先说清楚”。你会怎么选？", []),
        ("你得到过一个教训。", []),
    ],
)
def test_telling_the_person_what_to_do_is_found_outside_their_quoted_words(text: str, found: list[str]) -> None:
    assert commands(text) == found


def test_an_answer_that_tells_them_what_to_do_is_rewritten_once(path: Path) -> None:
    llm = Voice("你应该先说清楚再借。", "你说过：“钱的事先说清楚再谈感情”。你会怎么选？")
    with PersonaStore(path) as store:
        reply = chat(store, llm).reply([ChatTurn(role="user", content=QUESTION)])
    first, again = drafts(llm)
    assert "## 改写" not in first[2] and "## 改写" in again[2] and "你应该" in again[2]
    assert reply.reply == "你说过：“钱的事先说清楚再谈感情”。你会怎么选？"


def test_one_that_keeps_telling_them_gives_their_cited_words_alone(path: Path) -> None:
    llm = Voice("你应该先说清楚再借。", "一定要先说清楚。")
    with PersonaStore(path) as store:
        reply = chat(store, llm).reply([ChatTurn(role="user", content=QUESTION)])
    assert reply.reply.startswith(VOICE_HEAD) and reply.reply.endswith(VOICE_ASK)
    assert "“朋友借钱，钱的事先说清楚再谈感情”（2026-09-01）" in reply.reply
    assert commands(reply.reply) == [] and reply.citations == ["pi_money"] and not reply.abstain


def test_with_nothing_of_theirs_cited_it_says_it_found_no_principle(path: Path) -> None:
    def none(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        return {"reply": "你应该先等等。", "citations": [], "confidence": 0.5, "mode": "general"}

    with PersonaStore(path) as store:
        reply = chat(store, FakeLLM(none)).reply([ChatTurn(role="user", content=QUESTION)])
    assert reply.reply == VOICE_NONE and reply.abstain


def test_its_words_are_shown_only_once_checked_and_it_leaves_nothing_behind(path: Path) -> None:
    llm = Voice("你应该先说清楚再借。", "你说过：“钱的事先说清楚再谈感情”。你会怎么选？")

    async def collect(c: PersonaChat) -> list[object]:
        return [part async for part in c.stream_reply([ChatTurn(role="user", content=QUESTION)])]

    with PersonaStore(path) as store:
        parts = asyncio.run(collect(chat(store, llm)))
        final = parts[-1]
        assert isinstance(final, ChatReply)
        # Nothing of the first answer was shown: the only words are the checked reply's.
        assert [p for p in parts if isinstance(p, str)] == [final.reply]
        assert "你应该" not in final.reply
        assert store._db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 0
        assert (final.promise_what, final.promise_to) == ("", "")
