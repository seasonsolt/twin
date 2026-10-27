from __future__ import annotations

import datetime as dt

import pytest

from twin.llm import FakeLLM
from twin.persona.when import meeting_window, named_month, time_window

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


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("How many doctor's appointments did I go to in March?", (dt.date(2024, 3, 1), dt.date(2024, 3, 31))),
        ("What did I buy during June?", (dt.date(2023, 6, 1), dt.date(2023, 6, 30))),
        ("How many trips in December 2022?", (dt.date(2022, 12, 1), dt.date(2022, 12, 31))),
        ("我3月份去了几次健身房？", (dt.date(2024, 3, 1), dt.date(2024, 3, 31))),
        ("十二月买了几本书？", (dt.date(2023, 12, 1), dt.date(2023, 12, 31))),
        ("2023年2月去了几次", (dt.date(2023, 2, 1), dt.date(2023, 2, 28))),
        ("三个月前买的", None),
        ("5月前交稿了吗", None),
        ("How many books did I read?", None),
    ],
)
def test_named_month_is_the_latest_such_month_unless_a_year_is_given(
    text: str, expected: tuple[dt.date, dt.date] | None
) -> None:
    assert named_month(text, dt.date(2024, 3, 25)) == expected


MEETINGS = [d("2019-07-02"), d("2019-07-08"), d("2023-07-08"), d("2026-03-02"), d("2026-05-25")]
NOW = dt.date(2026, 10, 27)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2019年7月8号那次会上定了哪些事？", ("2019-07-08", "2019-07-08")),
        # Without a year, the latest meeting on that day.
        ("7月8号的会上说了什么", ("2023-07-08", "2023-07-08")),
        ("2019年7月的会", ("2019-07-01", "2019-07-31")),
        ("最近一次周会定了哪些事？", ("2026-05-25", "2026-05-25")),
        ("上次开会说的那个方案", ("2026-05-25", "2026-05-25")),
        ("上上次开会定了哪些事？", ("2026-03-02", "2026-03-02")),
        ("最近几次会都谈了什么", ("2023-07-08", "2026-05-25")),
        # A month with no meeting, or a day with none, names none.
        ("2024年3月的会", None),
        ("8月9号的会", None),
        ("客户案例怎么用", None),
    ],
)
def test_a_meeting_named_by_its_day_month_or_order(text: str, expected: tuple[str, str] | None) -> None:
    window = meeting_window(text, MEETINGS, NOW)
    assert window == (expected and (d(expected[0]), d(expected[1])))


def test_without_meetings_nothing_is_named_as_one() -> None:
    assert meeting_window("最近一次会定了什么", [], NOW) is None
    assert meeting_window("2019年7月8号的会", [], NOW) is None
    # Meetings later than the day asked from are not yet held.
    assert meeting_window("最近一次会", MEETINGS, d("2026-04-01")) == (d("2026-03-02"), d("2026-03-02"))
