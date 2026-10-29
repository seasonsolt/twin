"""The crisis guard: what stops a conversation, what does not, and that no model is asked."""

from __future__ import annotations

from pathlib import Path

import pytest

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.chat import PersonaChat
from twin.persona.crisis import CRISIS_REPLY, in_crisis
from twin.persona.schema import ChatTurn
from twin.persona.store import PersonaStore

STOPS = [
    "我想死",
    "好想死啊",
    "真想死了算了",
    "我不想活了",
    "活不下去了",
    "有时候觉得活着没意思",
    "我想自杀",
    "最近有自杀的念头",
    "我想伤害自己",
    "想结束自己的生命",
    "I want to kill myself",
    "thinking about suicide",
]
# Everyday ways of saying "very", and death or loss spoken of: the mirror is for these.
GOES_ON = [
    "想死你了",
    "累得要死",
    "忙得要死",
    "笑死我了",
    "热死了",
    "我爸是自杀走的，我一直没想通",
    "我不想活动",
    "她去世了，我很难过",
    "梦见自己死了",
    "怎么看待死亡",
]


@pytest.mark.parametrize("text", STOPS)
def test_words_of_ending_ones_life_or_harming_oneself_stop_it(text: str) -> None:
    assert in_crisis(text)


@pytest.mark.parametrize("text", GOES_ON)
def test_everyday_words_and_talk_of_death_do_not(text: str) -> None:
    assert not in_crisis(text)


@pytest.mark.parametrize("assistant", [True, False])
def test_every_way_of_asking_a_twin_is_guarded(tmp_path: Path, assistant: bool) -> None:
    """``PersonaChat`` guards the channels, the service and the command line too, before it looks anything up."""
    llm = FakeLLM(lambda *_: pytest.fail("the model was asked"))
    with PersonaStore(tmp_path / "twin.db") as store:
        chat = PersonaChat(store, llm, HashingEmbedder(), Settings(), assistant=assistant, reflection="mirror")
        reply = chat.reply([ChatTurn(role="user", content="我不想活了")])
        assert (reply.reply, reply.citations, reply.retrieved_ids) == (CRISIS_REPLY, [], [])
        assert store._db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 0
    assert llm.calls == []


def test_a_streamed_reply_is_guarded_too(tmp_path: Path) -> None:
    import asyncio

    async def collect(chat: PersonaChat) -> list[object]:
        return [part async for part in chat.stream_reply([ChatTurn(role="user", content="我想结束自己的生命")])]

    llm = FakeLLM(lambda *_: pytest.fail("the model was asked"))
    with PersonaStore(tmp_path / "twin.db") as store:
        text, reply = asyncio.run(collect(PersonaChat(store, llm, HashingEmbedder(), Settings())))
    assert text == CRISIS_REPLY and getattr(reply, "reply", None) == CRISIS_REPLY
