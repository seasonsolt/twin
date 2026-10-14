from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.llm import FakeLLM
from twin.persona import followups as fu
from twin.persona.profile import build_profile
from twin.persona.schema import ChatReply, SourceKind, evidence_class
from twin.persona.sources import ANSWER_CHANNEL
from twin.persona.store import PersonaStore


def reply(abstain: bool, reason: str = "") -> ChatReply:
    return ChatReply(
        reply="这得问我本人" if abstain else "我会先看回款",
        citations=[],
        confidence=0.2,
        abstain=abstain,
        abstain_reason=reason,
        retrieved_ids=[],
    )


@pytest.fixture
def store(tmp_path: Path) -> Iterator[PersonaStore]:
    with PersonaStore(tmp_path / "twin.db") as opened:
        yield opened


def test_abstentions_queue_once_per_question_with_reason_and_previous_turn(store: PersonaStore) -> None:
    store.log_chat("你怎么看远岚的报价？", reply(True, "资料里没有"))
    store.log_chat("你怎么看远岚的报价", reply(True, "还是没有"), previous="上周的会你在吗")
    store.log_chat("你喜欢喝什么茶？", reply(True))
    store.log_chat("你怎么看回款？", reply(False))
    pending = fu.list_followups(store)
    assert [f.question for f in pending] == ["你喜欢喝什么茶？", "你怎么看远岚的报价"]
    price = pending[1]
    assert price.asked == 2 and price.reason == "还是没有" and price.previous == "上周的会你在吗"
    assert price.status == "pending" and price.handled_at is None and price.first_at <= price.last_at
    assert fu.followup_id("你怎么看远岚的报价？ ") == fu.followup_id("你怎么看  远岚的报价") == price.followup_id


def test_an_answer_becomes_a_self_report_source_with_the_question_as_context(store: PersonaStore) -> None:
    store.log_chat("那报价呢？", reply(True), previous="你怎么看远岚这个客户")
    (followup,) = fu.list_followups(store)
    answered, source = fu.answer_followup(store, followup.followup_id, "  报价我只认实施费打包。 ", "张总")
    assert answered.status == "answered" and answered.source_id == source.source_id
    assert source.kind is SourceKind.INTERVIEW and evidence_class(source.kind).value == "self_report"
    assert source.title == "回答：那报价呢？" and source.origin == f"followup:{followup.followup_id}"
    (expression,) = store.list_expressions(source.source_id)
    assert expression.text == "报价我只认实施费打包。" and expression.is_target and expression.speaker == "张总"
    assert expression.context == "有人先问：你怎么看远岚这个客户；接着问：那报价呢？"
    assert expression.channel == ANSWER_CHANNEL
    with pytest.raises(ValueError):
        fu.answer_followup(store, followup.followup_id, "   ", "张总")
    with pytest.raises(KeyError):
        fu.answer_followup(store, "nope", "回答", "张总")


def test_answered_question_returns_when_the_answer_is_deleted_or_does_not_help(store: PersonaStore) -> None:
    store.log_chat("你的作息？", reply(True))
    (followup,) = fu.list_followups(store)
    _, source = fu.answer_followup(store, followup.followup_id, "我一般十二点睡。", "张总")
    # Asked again before a build included the answer: still answered.
    store.log_chat("你的作息？", reply(True))
    assert fu.get_followup(store, followup.followup_id).status == "answered"

    # A build after the answer, and the twin still abstains after it: the answer did not cover the question.
    state = fu.FollowupState(status="answered", at="2026-01-01T09:00:00", asked=1, source_id=source.source_id)
    store.set_meta(fu.PREFIX + followup.followup_id, state.model_dump_json())
    store.set_meta("built_at", "2026-01-01T02:00:00+00:00")  # 10:00 in UTC+8, after the answer anywhere west of it
    store.log_chat("你的作息？", reply(True))
    again = fu.get_followup(store, followup.followup_id)
    assert again.status == "pending" and again.unresolved and again.asked_since == 2

    store.delete_source(source.source_id)
    store.set_meta("built_at", "2025-12-31T00:00:00+00:00")
    gone = fu.get_followup(store, followup.followup_id)
    assert gone.status == "pending" and not gone.unresolved


def test_set_aside_and_back(store: PersonaStore) -> None:
    store.log_chat("你的家庭住址？", reply(True))
    (followup,) = fu.list_followups(store)
    assert fu.set_followup(store, followup.followup_id, "dismissed").status == "dismissed"
    store.log_chat("你的家庭住址？", reply(True))
    dismissed = fu.get_followup(store, followup.followup_id)
    assert dismissed.status == "dismissed" and dismissed.asked_since == 1 and dismissed.handled_at
    back = fu.set_followup(store, followup.followup_id, "pending")
    assert back.status == "pending" and back.handled_at is None and back.asked_since == 0
    with pytest.raises(KeyError):
        fu.set_followup(store, "nope", "dismissed")


def test_a_build_reads_the_answer_with_its_question_and_quotes_it(store: PersonaStore, tmp_path: Path) -> None:
    store.log_chat("你怎么看远岚的报价？", reply(True))
    (followup,) = fu.list_followups(store)
    fu.answer_followup(store, followup.followup_id, "报价我只认实施费打包。", "张总")
    seen: list[str] = []

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        seen.append(user)
        if schema.__name__ == "ExtractDraft":
            n = int(re.findall(r"\[(\d+)\]", user)[0])
            return {
                "items": [{"facet_id": "2.1", "statement": "报价坚持打包", "quotes": [{"n": n, "quote": "实施费打包"}]}]
            }
        return {"items": [{"statement": "报价坚持打包", "candidate_ids": re.findall(r"\[(pc_[0-9a-f]+)\]", user)}]}

    settings = Settings(target_name="张总", db_path=tmp_path / "twin.db")
    build_profile(store, FakeLLM(handler), settings)
    (extract,) = [u for u in seen if "报价我只认实施费打包" in u]
    assert "语境：有人问：你怎么看远岚的报价？" in extract and "本人：报价我只认实施费打包。" in extract
    (item,) = store.list_items()
    assert item.statement == "报价坚持打包" and item.evidence[0].quote == "实施费打包"
