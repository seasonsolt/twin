from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM, LLMError
from twin.persona import chat as pc
from twin.persona import rewrite as rw
from twin.persona.schema import ChatDraft, ChatTurn
from twin.persona.sources import parse_chat
from twin.persona.store import PersonaStore
from twin.usage import BudgetExceeded

pytestmark = pytest.mark.rewrite


def test_rewrite_joins_at_most_five_named_aspects() -> None:
    names = [" 政治立场（political views） ", "", *(f"方面{i}" for i in range(6))]
    llm = FakeLLM(lambda system, user, schema: {"aspects": names})
    assert rw.rewrite(llm, "Would you support a carbon tax?", "low") == rw.Rewrite(
        "政治立场（political views）；方面0；方面1；方面2"
    )
    assert llm.calls[0][0] == "Aspects" and llm.calls[0][2] == "Would you support a carbon tax?"
    assert rw.rewrite(FakeLLM(lambda *_: {}), "你好", "low") == rw.Rewrite()


def test_rewrite_keeps_at_most_six_offered_alternatives_in_order() -> None:
    offered = [" 川菜（Sichuan） ", "", *(f"备选{i}" for i in range(7))]
    llm = FakeLLM(lambda system, user, schema: {"aspects": [], "alternatives": offered})
    drafted = rw.rewrite(llm, "Sichuan or one of these?", "low")
    assert drafted == rw.Rewrite("", ("川菜（Sichuan）", "备选0", "备选1", "备选2", "备选3", "备选4"))


@pytest.fixture
def chat() -> pc.PersonaChat:
    settings = Settings(target_name="张三", pseudonymize_others=False)
    store = PersonaStore(":memory:")
    store.put_source(parse_chat("群_2024-03.txt", "2024-03-15 10:00 张三：我一直投民主党\n", settings))
    embedder = HashingEmbedder()
    pc.index_persona(store, embedder, settings)
    return pc.PersonaChat(store, FakeLLM(lambda *_: {}), embedder, settings)


def test_reply_ranks_for_the_question_and_the_named_aspects(
    chat: pc.PersonaChat, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedded: list[list[str]] = []
    embed = chat.embedder.embed
    monkeypatch.setattr(chat.embedder, "embed", lambda texts: embedded.append(list(texts)) or embed(texts))

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is rw.Aspects:
            return {"aspects": ["政治立场（political views, party）"]}
        assert schema is ChatDraft
        return {"reply": "Somewhat support", "citations": [], "confidence": 0.4, "mode": "inferred"}

    chat.llm = FakeLLM(answer)
    chat.reply([ChatTurn(role="user", content="Carbon tax?")], persist=False)
    assert embedded == [["Carbon tax?", "政治立场（political views, party）"]]
    assert [call[0] for call in chat.llm.calls] == ["Aspects", "ChatDraft"]


def test_a_failed_rewrite_falls_back_but_a_budget_stop_does_not(chat: pc.PersonaChat) -> None:
    def failing(error: Exception) -> FakeLLM:
        def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
            if schema is rw.Aspects:
                raise error
            return {"reply": "嗯", "citations": [], "confidence": 0.4, "mode": "general"}

        return FakeLLM(answer)

    chat.llm = failing(LLMError("timed out"))
    assert chat.reply([ChatTurn(role="user", content="你好")], persist=False).reply.endswith("嗯")
    chat.llm = failing(BudgetExceeded("budget"))
    with pytest.raises(BudgetExceeded):
        chat.reply([ChatTurn(role="user", content="你好")], persist=False)
