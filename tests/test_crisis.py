"""The crisis guard: what stops a conversation, what does not, and that no model is asked."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.chat import PersonaChat
from twin.persona.crisis import CRISIS_REPLY, EXAMPLES, CrisisGuard, CrisisVerdict, in_crisis
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
    # Spaces and marks between the characters, homophones and pinyin.
    "想 死",
    "我 不 想 活 了",
    "想.自.杀",
    "我想紫砂",
    "wo xiang zisha",
    "我想自sha",
    "不想活le",
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
    "累 得 要 死",
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


class Meaning:
    """Vectors by meaning, made up: what speaks of hoarded pills or a last letter lies by the crisis sentences."""

    name = "meaning"
    cluster_threshold = 0.8

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> Any:
        self.calls.append(texts)
        near = ("药", "信", "告别")

        # Very close (1.0), not close at all (0.0), or close enough to ask (0.6) for what is only "睡".
        def vector(t: str) -> list[float]:
            if t in EXAMPLES or any(w in t for w in near):
                return [1.0, 0.0]
            return [0.6, 0.8] if "睡" in t else [0.0, 1.0]

        return np.array([vector(t) for t in texts])


def judged(crisis: bool | None) -> FakeLLM:
    """A model that answers only the crisis question: yes, no, or fails (None)."""

    def handle(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        assert schema is CrisisVerdict, schema
        if crisis is None:
            raise RuntimeError("down")
        return {"crisis": crisis}

    return FakeLLM(handle)


def turns(*said: str) -> list[ChatTurn]:
    return [ChatTurn(role="user", content=s) for s in said]


@pytest.mark.parametrize(("verdict", "caught"), [(True, "model"), (False, None), (None, "close")])
def test_what_the_words_miss_is_asked_of_the_model_once_its_meaning_comes_close(
    verdict: bool | None, caught: str | None
) -> None:
    llm = judged(verdict)
    assert CrisisGuard(Meaning(), llm).check(turns("药我都攒好了")) == caught
    assert len(llm.calls) == 1
    # With no model at all, only very close is enough.
    assert CrisisGuard(Meaning(), None).check(turns("药我都攒好了")) == "close"
    assert CrisisGuard(Meaning(), None).check(turns("想睡一整天")) is None
    assert CrisisGuard(Meaning(), judged(False)).check(turns("想睡一整天")) is None


def test_nothing_close_asks_no_model_and_hashing_vectors_are_left_to_the_words() -> None:
    llm = judged(True)
    assert CrisisGuard(Meaning(), llm).check(turns("周末去爬山")) is None
    assert CrisisGuard(HashingEmbedder(), llm).check(turns("我已经把安眠药攒够了")) is None
    assert CrisisGuard(None, llm).check(turns("我已经把安眠药攒够了")) is None
    assert llm.calls == []
    # The words stop it before any vector or model.
    vectors = Meaning()
    assert CrisisGuard(vectors, llm).check(turns("我不想活了")) == "words" and vectors.calls == []


def test_what_is_said_bit_by_bit_is_read_together_and_the_twins_answers_are_not() -> None:
    llm = judged(True)
    assert CrisisGuard(Meaning(), llm).check(turns("信写好了", "放在抽屉里", "明天他们就知道了")) == "model"
    assert "信写好了" in llm.calls[-1][2]
    # Only the latest three of the person's turns.
    assert CrisisGuard(Meaning(), llm).check(turns("信写好了", "a", "b", "c")) is None
    said = [ChatTurn(role="user", content="周末去哪"), ChatTurn(role="twin", content="药店"),
            ChatTurn(role="user", content="好的")]  # fmt: skip
    assert CrisisGuard(Meaning(), llm).check(said) is None
    assert len(llm.calls) == 1


def test_the_meaning_layer_stops_a_twin_before_anything_is_looked_up(tmp_path: Path) -> None:
    llm = judged(True)
    with PersonaStore(tmp_path / "twin.db") as store:
        chat = PersonaChat(store, llm, Meaning(), Settings(), assistant=True, reflection="mirror")
        reply = chat.reply(turns("药我都攒好了"))
        assert (reply.reply, reply.citations, reply.retrieved_ids) == (CRISIS_REPLY, [], [])
        assert store._db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 0
    assert len(llm.calls) == 1


def test_the_page_is_told_a_reply_is_the_crisis_reply_whichever_layer_gave_it(tmp_path: Path) -> None:
    from twin.persona.crisis import crisis_reply
    from twin.web.persona import chat_payload

    with PersonaStore(tmp_path / "twin.db") as store:
        assert chat_payload(store, crisis_reply())["crisis"] is True
        other = crisis_reply().model_copy(update={"reply": "好的"})
        assert "crisis" not in chat_payload(store, other)
