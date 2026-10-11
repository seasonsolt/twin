from __future__ import annotations

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona import chat as pc
from twin.persona.sources import parse_chat, parse_questionnaire
from twin.persona.store import PersonaStore
from twin.persona.style import MIN_GRADED, extreme_rate


def test_extreme_rate_counts_each_graded_part_in_either_language() -> None:
    answers = ["I like order: Agree strongly; I plan ahead: Agree a little", "非常同意", "有点同意", "Paris"] * 5
    assert extreme_rate(answers) == 0.5
    assert extreme_rate(["Agree strongly"] * (MIN_GRADED - 1)) is None
    assert extreme_rate(["Neither agree nor disagree"] * MIN_GRADED) == 0


def questionnaire(answers: list[str]) -> str:
    return "\n\n".join(f"**{n}. 你同意吗？**　*偏好 · 2.1*\n\n回答：{a}" for n, a in enumerate(answers, 1))


def system_prompt(store: PersonaStore, settings: Settings) -> str:
    pc.index_persona(store, HashingEmbedder(), settings)
    chat = pc.PersonaChat(store, FakeLLM(lambda *_: {}), HashingEmbedder(), settings)
    return pc.chat_system_prompt("张三", chat.retrieve("你支持吗？"))


def test_prompt_states_the_persons_answer_style_only_from_enough_questionnaire_answers() -> None:
    settings = Settings(target_name="张三", pseudonymize_others=False)
    store = PersonaStore(":memory:")
    store.put_source(parse_questionnaire("q.md", questionnaire(["非常同意"] * 15 + ["有点同意"] * 10), settings))
    prompt = system_prompt(store, settings)
    assert "## 答题风格" in prompt and "约 60% 选了最强烈的一端" in prompt

    chats = PersonaStore(":memory:")
    chats.put_source(parse_chat("群.txt", "\n".join(["2024-03-15 10:00 张三：非常同意"] * 30), settings))
    assert "## 答题风格" not in system_prompt(chats, settings)
