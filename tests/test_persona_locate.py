from __future__ import annotations

import datetime as dt
import threading
from typing import Any

import pytest
from pydantic import BaseModel

from twin.llm import FakeLLM, LLMError
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
        "What was my office address?",
        "Which was the car I used for commuting?",
        "Where were my keys?",
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
        "- 日期最晚的那条是最新的说法；它和档案条目或更早的话不一致时，以它为准；"
        "较晚的话说的是新增或减少（‘又添了一个’）时，要在之前说的数上加减。"
        "这是资料范围内的最新已知状态，回答时保留原话中的约数和限定；记录距提问有时间间隔本身不表示没有答案",
    ]
    assert lc.order([lc.Mention(ref="c", says="提到过那辆车")], DATES) == ["- 日期不详 [c] 提到过那辆车"]
    assert lc.order([lc.Mention(ref="ghost", says="x")], DATES) == []


@pytest.mark.parametrize("question", ["Where did I live before I moved here?", "我之前的住址是什么？"])
def test_previous_state_keeps_the_change_as_its_reference_point(question: str) -> None:
    lines = lc.order(
        [lc.Mention(ref="b", says="现在住在城南"), lc.Mention(ref="a", says="现在住在城北")],
        DATES,
        question=question,
    )
    assert "[a]" in lines[0] and "[b]" in lines[1]
    assert "变更之前的状态" in lines[-1]
    assert "最新已知状态" not in lines[-1]


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


def test_locate_keeps_every_record_either_listing_names() -> None:
    answers = iter(
        [
            {"mentions": [{"ref": "a", "says": "车停在楼下"}]},
            {"mentions": [{"ref": "b", "says": "车现在停在车库"}, {"ref": "a", "says": "另一种说法"}]},
        ]
    )
    lock = threading.Lock()

    def found(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        with lock:
            return next(answers)

    llm = FakeLLM(found)
    lines = lc.locate(llm, "Where do I keep my bike now?", "- [a] …\n- [b] …", DATES, "low")
    assert len(llm.calls) == lc.SAMPLES
    assert [line.split("]")[0] for line in lines[:2]] == ["- 2024-03-01 [a", "- 2024-03-20 [b"]
    assert len(lines) == 3


def test_locate_uses_the_listing_that_succeeds_and_fails_only_when_all_do() -> None:
    calls = iter([True, False])
    lock = threading.Lock()

    def flaky(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        with lock:
            ok = next(calls)
        if not ok:
            raise LLMError("down")
        return {"mentions": [{"ref": "b", "says": "车现在停在车库"}]}

    assert lc.locate(FakeLLM(flaky), "Where do I keep my bike now?", "- [b] …", DATES, "low")[0].startswith(
        "- 2024-03-20 [b]"
    )

    def down(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        raise LLMError("down")

    with pytest.raises(LLMError):
        lc.locate(FakeLLM(down), "Where do I keep my bike now?", "- [b] …", DATES, "low")
