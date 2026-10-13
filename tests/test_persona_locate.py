from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from pydantic import BaseModel

from twin.llm import FakeLLM
from twin.persona import locate as lc

DATES: dict[str, dt.date | None] = {"a": dt.date(2024, 3, 1), "b": dt.date(2024, 3, 20), "c": None}


@pytest.mark.parametrize(
    "question",
    [
        "Where do I keep my bike now?",
        "What is my current job title?",
        "Where did I go on my most recent trip?",
        "What was my previous phone before this one?",
        "What time do I usually get up?",
        "How often do I go swimming?",
        "Where am I planning to stay on the trip?",
        "What is my sister's job?",
        "我现在住在哪？",
        "我之前的车是什么牌子？",
        "我平时几点睡？",
    ],
)
def test_questions_about_the_present_or_latest_state_locate(question: str) -> None:
    assert lc.needs_locating(question)


@pytest.mark.parametrize(
    "question", ["How many days ago did I buy the lamp?", "烟熏炉是多久以前买的？", "你最喜欢哪本书？", "你好"]
)
def test_other_questions_skip_locating(question: str) -> None:
    assert not lc.needs_locating(question)


def test_order_checks_refs_and_puts_the_latest_last() -> None:
    mentions = [
        lc.Mention(ref="b", says="车现在停在车库"),
        lc.Mention(ref="ghost", says="不存在的资料"),
        lc.Mention(ref="c", says="提到过那辆车"),
        lc.Mention(ref="a", says="车停在楼下"),
        lc.Mention(ref="a", says="同一条又列了一次"),
        lc.Mention(ref="b", says=" "),
    ]
    assert lc.order(mentions, DATES) == [
        "- 2024-03-01 [a] 车停在楼下",
        "- 2024-03-20 [b] 车现在停在车库",
        "- 日期不详 [c] 提到过那辆车",
        "- 日期最晚的那条是最新的说法；它和档案条目或更早的话不一致时，以它为准",
    ]
    assert lc.order([lc.Mention(ref="c", says="提到过那辆车")], DATES) == ["- 日期不详 [c] 提到过那辆车"]
    assert lc.order([lc.Mention(ref="ghost", says="x")], DATES) == []


def test_locate_only_calls_the_model_for_questions_that_need_it() -> None:
    def found(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        assert schema is lc.Mentions and "【问题】\nWhere do I keep my bike now?" in user
        return {"mentions": [{"ref": "b", "says": "bike is in the garage now"}]}

    llm = FakeLLM(found)
    assert lc.locate(llm, "你好", "- [b] …", DATES, "low") == []
    assert llm.calls == []
    assert lc.locate(llm, "Where do I keep my bike now?", "- [b] …", DATES, "low")[0] == (
        "- 2024-03-20 [b] bike is in the garage now"
    )
