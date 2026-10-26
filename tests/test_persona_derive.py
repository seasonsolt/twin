from __future__ import annotations

import asyncio
import datetime as dt
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM, LLMError
from twin.persona import chat as pc
from twin.persona import derive as dv
from twin.persona.schema import ChatDraft, ChatTurn
from twin.persona.sources import parse_chat
from twin.persona.store import PersonaStore
from twin.usage import BudgetExceeded

TODAY = dt.date(2024, 3, 25)


def fact(ref: str, date: str = "", quantity: float | None = None, unit: str = "", event: str = "事") -> dv.DatedFact:
    return dv.DatedFact(ref=ref, event=event, date=date, quantity=quantity, unit=unit)


@pytest.mark.parametrize(
    "question",
    [
        "How many days ago did I buy a smoker?",
        "How long have I been birdwatching?",
        "What is the order of the three trips I took?",
        "Which event did I attend first, the gala or the fair?",
        "How much have I made from selling eggs this month?",
        "我上次体检是多久以前？",
        "这两次搬家相隔几个月？",
        "我一共去过几次日本？",
        "How many plants do I keep on the balcony?",
        "What is the total I paid for the two concert tickets?",
        "我买过几部相机？",
    ],
)
def test_span_order_and_total_questions_trigger_derivation(question: str) -> None:
    assert dv.needs_derivation(question)


@pytest.mark.parametrize(
    "question", ["What is your favourite film?", "What do you think about remote work?", "你最喜欢哪本书？", "你好"]
)
def test_ordinary_questions_skip_derivation(question: str) -> None:
    assert not dv.needs_derivation(question)


def test_compute_checks_refs_and_dates_then_spans_order_and_totals() -> None:
    lines = dv.compute(
        [
            fact("b", "2024-03-17", 350, "粉丝", "收到球拍"),
            fact("a", "2024-03-10", 250, "粉丝", "买了球拍"),
            fact("ghost", "2024-03-01", event="没有这条资料"),
            fact("a", "2024-04-01", event="晚于今天"),
            fact("c", "not a date", 5, "粉丝", "日期不明"),
            fact("c", event=" "),
        ],
        TODAY,
        {"a", "b", "c"},
    )
    assert lines == [
        "已核对的事件（按日期先后）：",
        "- 2024-03-10 买了球拍，数量 250粉丝 [a]，距今天 15 天，约 2.1 周",
        "- 2024-03-17 收到球拍，数量 350粉丝 [b]，距今天 8 天，约 1.1 周",
        "- 日期不详：日期不明，数量 5粉丝 [c]",
        "- 从 [a] 到 [b]：相隔 7 天，约 1 周",
        "- 数量合计（粉丝，3 条）：605",
    ]


def test_compute_reports_change_and_long_spans_when_every_quantity_is_dated() -> None:
    lines = dv.compute(
        [fact("a", "2024-01-01", 40, "打"), fact("b", "2024-02-15", 10, "打"), fact("c", "2023-12-01")],
        TODAY,
        {"a", "b", "c"},
    )
    assert "- 2023-12-01 事 [c]，距今天 115 天，约 16.4 周，约 3.8 个月" in lines
    assert "- 最早到最晚：相隔 76 天，约 10.9 周，约 2.5 个月" in lines
    assert lines[-2:] == [
        "- 数量合计（打，2 条）：50",
        ("- 从最早一条 [a] 到最晚一条 [b] 的变化（打）：-30；先后按的是资料的日期，后提到的不一定是后发生的"),
    ]
    assert dv.compute([fact("ghost", "2024-01-01")], TODAY, {"a"}) == []
    assert not any(line.startswith("- 以上共") for line in lines)
    assert dv.compute([fact("a")], TODAY, {"a"}) == []


def test_compute_lists_every_thing_found_for_a_count_question() -> None:
    lines = dv.compute(
        [fact("a", event="戴着手环"), fact("b", "2024-03-01", event="买了血压计"), fact("ghost", event="没有这条")],
        TODAY,
        {"a", "b"},
        count=True,
    )
    assert lines == [
        "已核对的事件（按日期先后）：",
        "- 2024-03-01 买了血压计 [b]，距今天 24 天，约 3.4 周",
        "- 日期不详：戴着手环 [a]",
        "- 以上共 2 件（问个数时，这就是资料里找到的符合条件的件数）",
    ]


@pytest.mark.parametrize(
    ("question", "count"),
    [
        ("How many plants do I keep on the balcony?", True),
        ("我一共去过几次日本？", True),
        ("How many weeks passed between the two trips?", False),
        ("What is the total I paid for the two concert tickets?", False),
    ],
)
def test_only_questions_about_how_many_things_count_them(question: str, count: bool) -> None:
    assert bool(dv.COUNT.search(question)) is count


def test_compute_counts_dates_back_from_the_day_the_words_were_said() -> None:
    def back(ref: str, said: str, before: float | None, unit: str, event: str, date: str = "") -> dv.DatedFact:
        return dv.DatedFact(ref=ref, event=event, date=date, said=said, before=before, before_unit=unit)  # type: ignore[arg-type]

    lines = dv.compute(
        [
            back("f", "2024-03-24", None, "", "参加文化节"),  # happened the day it was said
            back("s", "2024-03-24", 3, "月", "开始上西班牙语课"),
            back("m", "2024-03-31", 1, "月", "月末那天说的上个月"),
            back("w", "2024-03-20", 1.5, "周", "一周半前"),
            back("y", "2024-03-20", 1, "年", "一年前"),
            back("x", "2024-03-20", 2, "", "没有单位就不推算"),
            back("z", "", 2, "天", "没有说出日期就不推算", "2024-03-01"),
        ],
        TODAY,
        {"f", "s", "m", "w", "y", "x", "z"},
    )
    assert lines[:7] == [
        "已核对的事件（按日期先后）：",
        "- 2023-03-20（由 2024-03-20 说的话往前推 1 年） 一年前 [y]，距今天 371 天，约 53 周，约 12.2 个月",
        "- 2023-12-24（由 2024-03-24 说的话往前推 3 月） 开始上西班牙语课 [s]，距今天 92 天，约 13.1 周，约 3 个月",
        "- 2024-02-29（由 2024-03-31 说的话往前推 1 月） 月末那天说的上个月 [m]，距今天 25 天，约 3.6 周",
        "- 2024-03-01 没有说出日期就不推算 [z]，距今天 24 天，约 3.4 周",
        "- 2024-03-10（由 2024-03-20 说的话往前推 1.5 周） 一周半前 [w]，距今天 15 天，约 2.1 周",
        "- 2024-03-24 参加文化节 [f]，距今天 1 天",
    ]
    assert not any("没有单位" in line for line in lines)


def test_derive_only_calls_the_model_for_questions_that_need_it() -> None:
    def sheet(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        assert schema is dv.FactSheet and "【今天】2024-03-25" in user and "[a] 2024-03-15 说" in user
        return {"facts": [{"ref": "a", "event": "买了烟熏炉", "date": "2024-03-15"}]}

    llm = FakeLLM(sheet)
    assert dv.derive(llm, "你好", "- [a] 2024-03-15 说「I just got a smoker today」", TODAY, {"a"}, "low") == []
    assert llm.calls == []
    lines = dv.derive(llm, "How many days ago did I buy a smoker?", "- [a] 2024-03-15 说「…」", TODAY, {"a"}, "low")
    assert lines[1] == "- 2024-03-15 买了烟熏炉 [a]，距今天 10 天，约 1.4 周"


@pytest.fixture
def chat() -> pc.PersonaChat:
    settings = Settings(target_name="张三", pseudonymize_others=False)
    store = PersonaStore(":memory:")
    store.put_source(parse_chat("群_2024-03.txt", "2024-03-15 10:00 张三：今天刚买了烟熏炉\n", settings))
    embedder = HashingEmbedder()
    pc.index_persona(store, embedder, settings)
    return pc.PersonaChat(store, FakeLLM(lambda *_: {}), embedder, settings)


def test_reply_shows_computed_lines_and_survives_a_failed_derivation(chat: pc.PersonaChat) -> None:
    expression = chat.store.list_expressions()[0].expression_id
    failing = {"on": False}

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is dv.FactSheet:
            if failing["on"]:
                raise LLMError("timed out")
            return {"facts": [{"ref": expression, "event": "买了烟熏炉", "date": "2024-03-15"}]}
        assert schema is ChatDraft
        return {"reply": "十天前", "citations": [expression], "confidence": 0.8, "mode": "grounded"}

    chat.llm = FakeLLM(answer)
    question = [ChatTurn(role="user", content="烟熏炉是多久以前买的？")]
    assert chat.reply(question, persist=False, today=TODAY).reply == "十天前"
    _, system, user = chat.llm.calls[-1]
    assert "今天是 2024-03-25" in system and "【推算】" in user
    assert f"- 2024-03-15 买了烟熏炉 [{expression}]，距今天 10 天，约 1.4 周" in user
    assert "所问的一项在【推算】里有就算资料给出了" in system

    failing["on"] = True
    chat.llm = FakeLLM(answer)
    assert chat.reply(question, persist=False, today=TODAY).reply == "十天前"
    assert "【推算】" not in chat.llm.calls[-1][2]

    def over_budget(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        raise BudgetExceeded("budget")

    chat.llm = FakeLLM(over_budget)
    with pytest.raises(BudgetExceeded):
        chat.reply(question, persist=False, today=TODAY)


def test_streamed_reply_derives_too(chat: pc.PersonaChat) -> None:
    expression = chat.store.list_expressions()[0].expression_id

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is dv.FactSheet:
            return {"facts": [{"ref": expression, "event": "买了烟熏炉", "date": "2024-03-15"}]}
        return {"reply": "十天前", "citations": [expression], "confidence": 0.8, "mode": "grounded"}

    chat.llm = FakeLLM(answer)

    async def run() -> list[Any]:
        return [
            part
            async for part in chat.stream_reply(
                [ChatTurn(role="user", content="烟熏炉是多久以前买的？")], persist=False, steps=True
            )
        ]

    parts = asyncio.run(run())
    assert parts[-1].reply == "十天前"
    assert [p.name for p in parts if isinstance(p, pc.Step)] == ["search", "think", "write"]
    assert "【推算】" in chat.llm.calls[-1][2]


def test_nothing_found_skips_the_round_that_works_things_out(
    chat: pc.PersonaChat, monkeypatch: pytest.MonkeyPatch
) -> None:
    def nothing(*_: Any, **__: Any) -> pc.PersonaContext:
        return pc.PersonaContext(items=[], expressions=[], core=[], voice=[])

    monkeypatch.setattr(chat, "_ranked", nothing)
    asked: list[type[BaseModel]] = []

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        asked.append(schema)
        return {"reply": "资料里没有", "citations": [], "confidence": 0.2, "mode": "abstain"}

    chat.llm = FakeLLM(answer)

    async def run() -> list[Any]:
        return [
            part
            async for part in chat.stream_reply(
                [ChatTurn(role="user", content="烟熏炉是多久以前买的？")], persist=False, steps=True
            )
        ]

    parts = asyncio.run(run())
    assert [p.name for p in parts if isinstance(p, pc.Step)] == ["search", "write"]
    assert not {dv.FactSheet} & set(asked)
    assert "【推算】" not in chat.llm.calls[-1][2]


def test_count_for_a_named_month_leaves_out_other_months_and_undated_things() -> None:
    lines = dv.compute(
        [fact("a", "2024-03-03", event="看医生"), fact("b", "2024-02-20", event="看牙"), fact("c", event="复诊")],
        TODAY,
        {"a", "b", "c"},
        count=True,
        month=(dt.date(2024, 3, 1), dt.date(2024, 3, 31)),
    )
    assert lines[-3:] == [
        "- 2024-03 这个月内有日期的共 1 件",
        "- 另有 1 件日期不详，没有计入；资料的说法表明它也在这个月（如说的是“这个月”）就加上，否则不加",
        "- 从 [b] 到 [a]：相隔 12 天，约 1.7 周",
    ]


def test_running_totals_are_not_summed_and_later_changes_are_added_to_the_latest() -> None:
    def amount(ref: str, date: str, quantity: float, kind: str) -> dv.DatedFact:
        return dv.DatedFact(ref=ref, event="事", date=date, quantity=quantity, unit="枚", kind=kind)  # type: ignore[arg-type]

    lines = dv.compute(
        [
            amount("a", "2024-03-01", 3, "累计"),
            amount("b", "2024-03-10", 5, "累计"),
            amount("c", "2024-03-05", 4, "增减"),  # before the latest total, so already in it
            amount("d", "2024-03-20", 1, "增减"),
        ],
        TODAY,
        {"a", "b", "c", "d"},
    )
    assert lines[-2:] == [
        "- 现在的数量（枚）：按最新的累计数 5（2024-03-10 [b]），加上 2024-03-20 的 +1 [d]，得 6；累计数之间不要相加",
        "- 累计数的变化（枚）：从 2024-03-01 的 3 [a] 到 2024-03-10 的 5 [b]，+2",
    ]
    assert not any(line.startswith("- 数量合计") for line in lines)


def test_a_count_question_with_a_running_total_answers_from_the_total_not_the_number_of_facts() -> None:
    facts = [
        dv.DatedFact(ref="a", event="一共有 37 枚", date="2024-03-01", quantity=37, unit="枚", kind="累计"),
        dv.DatedFact(ref="b", event="又添了一枚", date="2024-03-03", quantity=1, unit="枚", kind="增减"),
    ]
    lines = dv.compute(facts, TODAY, {"a", "b"}, count=True)
    assert not any(line.startswith("- 以上共") for line in lines)
    assert lines[-1].startswith(
        "- 现在的数量（枚）：按最新的累计数 37（2024-03-01 [a]），加上 2024-03-03 的 +1 [b]，得 38"
    )


def test_amounts_marked_as_running_totals_are_plain_amounts_outside_a_present_question() -> None:
    facts = [
        dv.DatedFact(ref="a", event="改过的报价 2800", date="2024-03-01", quantity=2800, unit="元", kind="累计"),
        dv.DatedFact(ref="b", event="最初的报价 2500", date="2024-03-05", quantity=2500, unit="元", kind="累计"),
    ]
    lines = dv.compute(facts, TODAY, {"a", "b"}, present=False)
    assert not any(line.startswith(("- 现在的数量", "- 累计数的变化")) for line in lines)


def test_a_sum_of_amounts_that_grow_by_date_says_they_may_be_one_running_total() -> None:
    lines = dv.compute([fact("a", "2024-01-01", 3, "次"), fact("b", "2024-02-15", 5, "次")], TODAY, {"a", "b"})
    assert f"- 数量合计（次，2 条）：8；{dv.SUM_CAVEAT}" in lines
