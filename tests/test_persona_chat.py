from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import chat as pc
from twin.persona import profile as pf
from twin.persona.items import PReview
from twin.persona.schema import ChatTurn, ReviewStatus
from twin.persona.sources import parse_biography, parse_chat, parse_questionnaire
from twin.persona.store import PersonaStore

D = dt.date

QUESTIONNAIRE = """**4. 排序。**　*偏好 · 2.1*

回答：结果第一，钱进了账户才算数。

**13.【测试题】大单第一句？**　*情境 · 3.4*

回答：首付多少？
"""

CHAT = """2026-09-01 10:02 李四：这单签了，首付 10%
2026-09-01 10:05 张三：首付不到 30% 不开工，说白了钱进了账户才叫收入
2026-09-20 09:00 李四：数据看着不错
2026-09-20 09:01 张三：我就问一句，对照组是谁挑的？
"""


def extract_handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    entries = {int(n): t for n, t in re.findall(r"\[(\d+)\][^\n]*\n(?:语境：[^\n]*\n)?本人：([^\n]*)", user)}
    items = []
    for n, text in entries.items():
        if "钱进了账户" in text:
            items.append(
                {"facet_id": "2.1", "statement": "他把回款放第一", "quotes": [{"n": n, "quote": "钱进了账户"}]}
            )
        if "对照组" in text:
            items.append(
                {"facet_id": "4.2", "statement": "他追问对照组", "quotes": [{"n": n, "quote": "对照组是谁挑的"}]}
            )
    if schema is pf.MergeDraft:
        ids = re.findall(r"\[(pc_[0-9a-f]+)\]", user)
        return {"items": [{"statement": "他认为钱进了账户才算收入", "candidate_ids": ids}]}
    return {"items": items}


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="张三", max_workers=2)


@pytest.fixture
def store(settings: Settings) -> PersonaStore:
    s = PersonaStore(":memory:")
    s.put_source(parse_questionnaire("q_2026-08-30.md", QUESTIONNAIRE, settings))
    s.put_source(parse_chat("群.txt", CHAT, settings))
    pf.build_profile(s, FakeLLM(extract_handler), settings)
    return s


def test_index_is_incremental_and_follows_the_embedding_space(store: PersonaStore, settings: Settings) -> None:
    embedder = HashingEmbedder()
    first = pc.index_persona(store, embedder, settings)
    assert first == {
        "items": 2,
        "expressions": 3,
    }  # one questionnaire answer and two chat messages; held-out answers are not indexed
    assert pc.index_persona(store, embedder, settings) == {"items": 0, "expressions": 0}
    other = HashingEmbedder(dim=256)
    assert pc.index_persona(store, other, settings) == {"items": 2, "expressions": 3}
    assert store.get_vectors("items")[1].shape == (2, 256)


def test_retrieve_respects_as_of_and_keeps_held_out_answers_out(store: PersonaStore, settings: Settings) -> None:
    embedder = HashingEmbedder()
    pc.index_persona(store, embedder, settings)
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), embedder, settings)
    ctx = chat.retrieve("对照组和数据", as_of=D(2026, 9, 10))
    texts = [e.text for e, _ in ctx.expressions]
    assert all("对照组" not in t for t in texts)  # said on 09-20, after as_of
    assert all("首付多少" not in t for t in texts)  # held-out test answer
    assert {i.facet_id for i, _ in ctx.items} | {i.facet_id for i in ctx.core} == {"2.1"}
    assert ctx.voice == ["首付不到 30% 不开工，说白了钱进了账户才叫收入"]  # chat words only
    full = chat.retrieve("对照组")
    assert any("对照组" in e.text for e, _ in full.expressions) and len(full.voice) == 2


def test_reply_filters_citations_and_caps_confidence(store: PersonaStore, settings: Settings) -> None:
    embedder = HashingEmbedder()
    pc.index_persona(store, embedder, settings)
    item_id = store.list_items("2.1")[0].item_id
    cite = {"reply": "钱到账才算。", "citations": [f"[{item_id}]", "pi_fake"], "confidence": 0.9, "abstain": False}
    answers = iter(
        [
            {**cite, "topic_facets": ["2.1", "x.9"]},
            {
                "reply": "这个我没想过。",
                "citations": [],
                "confidence": 0.8,
                "abstain": True,
                "abstain_reason": "无依据",
                "topic_facets": ["9.4"],
            },
            cite,
        ]
    )
    llm = FakeLLM(lambda s, u, schema: next(answers))
    chat = pc.PersonaChat(store, llm, embedder, settings)
    history = [ChatTurn(role="user", content="你怎么看签大单？")]
    first = chat.reply(history)
    assert first.citations == [item_id] and first.confidence == 0.6  # rests on an unreviewed item only
    assert first.topic_facets == ["2.1"] and not first.abstain
    _, system, user = llm.calls[0]
    assert "张三的数字分身" in system and "说白了钱进了账户才叫收入" in system  # voice sample
    assert "2.1 核心价值排序；" in system and "；本人已确认" not in system
    assert user.endswith("对方：你怎么看签大单？\n\n请回复对方的最后一句话。")
    history += [ChatTurn(role="twin", content=first.reply), ChatTurn(role="user", content="你喜欢什么运动？")]
    second = chat.reply(history, as_of=D(2026, 9, 30))
    assert second.abstain and second.confidence == 0.3 and second.abstain_reason == "无依据"
    assert "你：钱到账才算。" in llm.calls[1][2] and "2026-09-30（含）以前" in llm.calls[1][1]
    assert store.chat_demand() == {"2.1": (1, 0), "9.4": (1, 1)}

    store.set_review(item_id, PReview(status=ReviewStatus.CONFIRMED, reviewed_at="2026-10-03T10:00:00"))
    third = chat.reply([ChatTurn(role="user", content="签大单看什么？")])
    assert third.confidence == 0.9 and "；本人已确认" in llm.calls[2][1] + llm.calls[2][2]
    with pytest.raises(ValueError, match="last message"):
        chat.reply(history[:2])


def test_reviews_edit_and_reject_what_the_twin_sees(store: PersonaStore, settings: Settings) -> None:
    embedder = HashingEmbedder()
    money, probe = store.list_items("2.1")[0], store.list_items("4.2")[0]
    now = "2026-10-03T10:00:00"
    store.set_review(money.item_id, PReview(status=ReviewStatus.EDITED, statement="他只认到账的钱", reviewed_at=now))
    store.set_review(probe.item_id, PReview(status=ReviewStatus.REJECTED, reviewed_at=now))
    edited = store.get_item(money.item_id)
    assert edited is not None and edited.statement == "他只认到账的钱" and edited.extracted_statement == money.statement
    assert [i.item_id for i in store.list_items()] == [money.item_id]
    assert len(store.list_items(include_rejected=True)) == 2
    pc.index_persona(store, embedder, settings)
    ctx = pc.PersonaChat(store, FakeLLM(lambda *a: {}), embedder, settings).retrieve("对照组")
    assert probe.item_id not in ctx.ids and money.item_id in ctx.trusted
    with pytest.raises(KeyError):
        store.set_review("pi_missing", None)


def test_biography_narration_is_marked_untrusted_and_its_quotes_become_voice(settings: Settings) -> None:
    store = PersonaStore(":memory:")
    store.put_source(
        parse_biography("年谱.md", "# 1854 年\n\n众请速攻。公曰：宁可屯兵不进，不可轻进致败。\n", settings)
    )

    def bio(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is pf.ExtractDraft:
            quote = {"n": 1, "quote": "宁可屯兵不进，不可轻进致败", "own_words": True}
            return {"items": [{"facet_id": "3.1", "statement": "他宁守勿冒进", "quotes": [quote]}]}
        return {"reply": "宁可屯兵不进。", "citations": [], "confidence": 0.9, "abstain": False}

    llm = FakeLLM(bio)
    pf.build_profile(store, llm, settings)
    embedder = HashingEmbedder()
    pc.index_persona(store, embedder, settings)
    chat = pc.PersonaChat(store, llm, embedder, settings)
    ctx = chat.retrieve("要不要速攻")
    narrated = [e for e, _ in ctx.expressions if e.narrated]
    assert narrated and not ctx.trusted & {e.expression_id for e in narrated}
    assert ctx.voice == ["宁可屯兵不进，不可轻进致败"]
    message = pc.chat_user_message([ChatTurn(role="user", content="要不要速攻")], ctx)
    assert "别人写的关于你的记述（第三人称" in message and "（无相关原话）" in message
    assert "宁可屯兵不进，不可轻进致败" in pc.chat_system_prompt("张三", ctx)
