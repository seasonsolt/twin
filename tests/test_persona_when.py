from __future__ import annotations

import datetime as dt

import pytest

from twin.llm import FakeLLM
from twin.persona.when import time_window

TODAY = dt.date(2023, 4, 22)  # a Saturday


def d(day: str) -> dt.date:
    return dt.date.fromisoformat(day)


@pytest.mark.parametrize(
    ("text", "window"),
    [
        ("Who did I go with to the music event last Saturday?", ("2023-04-14", "2023-04-18")),
        ("What did I buy last Monday?", ("2023-04-16", "2023-04-20")),
        ("What was the milestone I mentioned four weeks ago?", ("2023-03-22", "2023-03-30")),
        ("Which relative's event did I attend a week ago?", ("2023-04-12", "2023-04-20")),
        ("Where did I go 10 days ago?", ("2023-04-10", "2023-04-16")),
        ("What did I book two months ago?", ("2023-02-10", "2023-03-04")),
        ("What did I cook yesterday?", ("2023-04-20", "2023-04-22")),
        ("What happened the day before yesterday?", ("2023-04-19", "2023-04-22")),
        ("What did I read last week?", ("2023-04-11", "2023-04-21")),
        ("我上周六和谁去听的音乐会？", ("2023-04-14", "2023-04-18")),
        ("三天前我买了什么？", ("2023-04-17", "2023-04-22")),
        ("一个月前我提到的项目是什么？", ("2023-03-13", "2023-04-04")),
        ("上周我读了什么书？", ("2023-04-11", "2023-04-21")),
        ("上个月我去了哪里？", ("2023-03-08", "2023-04-09")),
    ],
)
def test_relative_times_become_date_windows(text: str, window: tuple[str, str]) -> None:
    assert time_window(text, TODAY) == (d(window[0]), d(window[1]))


def test_the_first_relative_time_wins_and_windows_never_pass_today() -> None:
    assert time_window("What did I do yesterday, and a week ago?", TODAY) == (d("2023-04-20"), d("2023-04-22"))
    # "Last Saturday" asked on a Saturday is a week back, not today.
    assert time_window("last saturday", TODAY)[0] == d("2023-04-14")  # type: ignore[index]


@pytest.mark.parametrize(
    "text",
    [
        "What is the order of the three trips I took in the past three months?",
        "How long have I been birdwatching?",
        "Agonizing about it?",  # "ago" inside a word
        "你最喜欢哪本书？",
        "",
    ],
)
def test_questions_without_a_relative_time_have_no_window(text: str) -> None:
    assert time_window(text, TODAY) is None


def test_retrieval_adds_what_the_person_said_in_the_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from twin.config import Settings
    from twin.embed import HashingEmbedder
    from twin.persona import chat as pc
    from twin.persona.sources import parse_chat
    from twin.persona.store import PersonaStore

    settings = Settings(target_name="张三", pseudonymize_others=False)
    lines = [f"2023-04-{day:02d} 10:00 张三：音乐会的门票真贵，第{day}天还在想要不要去音乐会" for day in range(1, 13)]
    lines.append("2023-04-15 10:00 张三：和爸妈一起去的，很开心")
    with PersonaStore(":memory:") as store:
        store.put_source(parse_chat("群.txt", "\n".join(lines) + "\n", settings))
        embedder = HashingEmbedder()
        pc.index_persona(store, embedder, settings)
        chat = pc.PersonaChat(store, FakeLLM(lambda *_: {}), embedder, settings)
        monkeypatch.setattr(pc, "K_EXPRESSIONS", 3)
        question = "上周六的音乐会我和谁去的？"
        plain = [e.text for e, _ in chat.retrieve(question).expressions]
        assert "和爸妈一起去的，很开心" not in plain and len(plain) == 3
        dated = [e.text for e, _ in chat.retrieve(question, today=TODAY).expressions]
        assert dated[:3] == plain and "和爸妈一起去的，很开心" in dated


def test_the_reply_prompt_names_the_window() -> None:
    from twin.persona import chat as pc
    from twin.persona.schema import ChatTurn

    ctx = pc.PersonaContext([], [], [], [], window=(d("2023-04-14"), d("2023-04-18")))
    user = pc.chat_user_message([ChatTurn(role="user", content="Who did I go with last Saturday?")], ctx)
    assert "【时间】对方话里的相对时间（如“上周六”“四周前”）大约指 2023-04-14 至 2023-04-18" in user
    assert user.index("【时间】") < user.index("【对话】")
    plain = pc.chat_user_message([ChatTurn(role="user", content="你好")], pc.PersonaContext([], [], [], []))
    assert "【时间】" not in plain
