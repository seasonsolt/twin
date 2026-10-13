from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from twin.llm import FakeLLM
from twin.persona import chat as pc
from twin.persona import connect as cn


@pytest.mark.parametrize(
    "question",
    [
        "At which venue did I give my talk?",
        "How old is my sister?",
        "When did I move?",
        "我的猫是从哪来的？",
        "我姐姐多大？",
        "How many years older is my brother than me?",
        "How many years will I be when I retire?",
        "How much did I save on the lamp?",
    ],
)
def test_questions_about_the_person_connect(question: str) -> None:
    assert cn.needs_connecting(question)


@pytest.mark.parametrize(
    "question",
    [
        "What is the capital of France?",
        "Should I take the job?",
        "我选择什么？",
        "如何理解这句话？",
        "你好",
        "How many plants did I buy last month?",
        "How many years in total did I spend at school?",
        "What is the total amount I spent on shoes?",
        "我一共去过几次北京？",
    ],
)
def test_other_questions_skip_the_call(question: str) -> None:
    llm = FakeLLM(lambda *a: pytest.fail("no call expected"))
    assert not cn.needs_connecting(question)
    assert cn.connect(llm, question, "", {"a"}, "low") == []


def test_joins_keep_only_retrieved_records_and_at_least_two_of_them() -> None:
    seen: list[str] = []

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        seen.append(system)
        assert schema is cn.Links and "【问题】\nHow old is my sister?" in user and "【资料】\nM" in user
        return {
            "links": [
                {"refs": ["a", "b", "a"], "via": "我的年龄", "conclusion": "姐姐 31 岁"},
                {"refs": ["a", "z"], "via": "x", "conclusion": "编号不在资料里"},
                {"refs": ["b"], "via": "x", "conclusion": "只有一条"},
                {"refs": ["a", "b"], "via": "", "conclusion": "  "},
            ]
        }

    lines = cn.connect(FakeLLM(handler), "How old is my sister?", "M", {"a", "b"}, "low")
    assert lines == ["- 姐姐 31 岁（共同点：我的年龄） [a] [b]"]
    assert "相似但不同的事不要连" in seen[0]


def test_the_reply_sees_joins_in_their_own_block() -> None:
    ctx = pc.PersonaContext([], [], [], [], connected=["- 姐姐 31 岁（共同点：我的年龄） [a] [b]"])
    message = pc.chat_user_message([pc.ChatTurn(role="user", content="How old is my sister?")], ctx)
    block = message.split("【连起来】", 1)[1]
    assert "连接合理时据此回答" in block and "- 姐姐 31 岁（共同点：我的年龄） [a] [b]" in block
    assert "【连起来】" not in pc.chat_user_message(
        [pc.ChatTurn(role="user", content="How old is my sister?")], pc.PersonaContext([], [], [], [])
    )
