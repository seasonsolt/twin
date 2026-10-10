"""Questionnaire evaluation with invented answers only; no real person's choices belong in the repository."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from typer.testing import CliRunner

from twin.cli import app
from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.evals.survey import (
    Instrument,
    PersonGrade,
    Sheet,
    SheetItem,
    TwinAnswer,
    apply_key,
    ask_baseline,
    ask_survey,
    blank_sheet,
    item_prompt,
    load_instrument,
    parse_choice,
    read_sheet,
    score_markdown,
    score_sheet,
    screen_leakage,
    write_sheet,
)
from twin.llm import FakeLLM
from twin.persona.chat import PersonaChat
from twin.persona.dimensions import FACETS
from twin.persona.sources import parse_interview
from twin.persona.store import PersonaStore

TINY = {
    "version": "test-v1",
    "title": "虚构问卷",
    "items": [
        {"id": "a", "domain": "values", "question": "虚构问题甲", "options": ["甲一", "甲二", "甲三"]},
        {
            "id": "b",
            "domain": "views",
            "question": "虚构问题乙",
            "options": ["很不同意", "不同意", "中立", "同意", "很同意"],
            "ordinal": True,
        },
        {"id": "c", "domain": "views", "question": "虚构问题丙", "options": ["丙一", "丙二"]},
    ],
}


def tiny() -> Instrument:
    return Instrument.model_validate(TINY)


def test_builtin_instrument_is_valid_and_mapped_to_facets() -> None:
    survey = load_instrument()
    assert survey.version == "zh-v2"
    assert len(survey.items) == 62
    facets = {facet.facet_id for facet in FACETS}
    assert all(item.facet is None or item.facet in facets for item in survey.items)
    assert len({item.domain for item in survey.items}) == 8
    # Mini-IPIP: four items per trait, the published keying (11 of 20 reversed, three of them openness).
    scaled = [item for item in survey.items if item.scale is not None]
    assert len(scaled) == 20 and all(item.ordinal and item.origin == "mini-ipip" for item in scaled)
    assert {t: sum(i.scale == t for i in scaled) for t in "EACNO"} == dict.fromkeys("EACNO", 4)
    assert sum(item.reverse for item in scaled) == 11
    assert sum(item.reverse for item in scaled if item.scale == "O") == 3
    # The economic-game items the paper found uninformative are gone.
    assert not {"s3", "s4", "p1"} & {item.id for item in survey.items}


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("B\n因为……", 1),
        ("「C」我一般会这样", 2),
        ("**A**. 先说结论", 0),
        ("  \nA、确定拿", 0),
        ("E", None),  # out of range for three options
        ("Because I think so", None),
        ("我不知道", None),
    ],
)
def test_parse_choice(text: str, expected: int | None) -> None:
    assert parse_choice(text, 3) == expected


def test_prompt_lists_lettered_options_and_allows_abstaining() -> None:
    item = tiny().items[0]
    prompt = item_prompt(item)
    assert "A. 甲一" in prompt and "C. 甲三" in prompt and "不知道" in prompt
    assert "也请选一个" in item_prompt(item, force_choice=True)


def _chat(handler: Any) -> tuple[PersonaStore, PersonaChat]:
    store = PersonaStore(":memory:")
    return store, PersonaChat(store, FakeLLM(handler), HashingEmbedder(), Settings(target_name="虚构林沐"))


def test_ask_takes_the_majority_and_keeps_abstentions() -> None:
    replies = iter(["B\n一", "A\n二", "B\n三"])

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if "虚构问题甲" in user:
            return {"reply": next(replies), "citations": [], "confidence": 0.7, "mode": "grounded"}
        if "虚构问题乙" in user:
            return {"reply": "资料里看不出来。", "citations": [], "confidence": 0.1, "mode": "abstain"}
        return {"reply": "我会选丙二。", "citations": [], "confidence": 0.6, "mode": "grounded"}

    store, chat = _chat(handler)
    with store:
        sheet = ask_survey(chat, tiny(), repeats=3)
        # Repeats are independent single turns and never written to the chat log.
        assert store.list_sources() == []
    a, b, c = sheet.items
    assert a.twin is not None and a.twin.choice == 1 and a.twin.choices == [1, 0, 1]
    assert a.twin.reply.startswith("B")
    assert b.twin is not None and b.twin.choice is None and b.twin.modes == ["abstain"] * 3
    assert c.twin is not None and c.twin.choice == 1  # matched by option text


def _graded() -> Sheet:
    store, chat = _chat(lambda *a: {"reply": "A", "citations": [], "confidence": 0.5, "mode": "grounded"})
    with store:
        sheet = ask_survey(chat, tiny())
    grades = {"a": PersonGrade(choice=0, rating=4), "b": PersonGrade(choice=2), "c": PersonGrade(choice=1)}
    for row in sheet.items:
        row.person = grades[row.item.id]
    return sheet


def test_score_counts_abstentions_as_wrong_only_in_strict_accuracy() -> None:
    sheet = _graded()
    sheet.items[2].twin.choice = None  # type: ignore[union-attr]
    overall = score_sheet(sheet)["overall"]
    assert overall["n_graded"] == 3 and overall["n_answered"] == 2
    assert overall["accuracy"] == pytest.approx(1 / 2)
    assert overall["strict_accuracy"] == pytest.approx(1 / 3)
    assert overall["coverage"] == pytest.approx(2 / 3)
    assert overall["chance"] == pytest.approx((1 / 3 + 1 / 5 + 1 / 2) / 3)
    assert overall["ordinal_error"] == pytest.approx(2 / 4)
    assert overall["ordinal_within_one"] == 0
    assert overall["reason_rating"] == 4


def test_retest_normalizes_by_the_persons_own_consistency() -> None:
    sheet = _graded()
    later = blank_sheet(tiny())
    for row, choice in zip(later.items, [0, 3, 1], strict=True):
        row.person = PersonGrade(choice=choice)
    retest = score_sheet(sheet, later)["retest"]
    assert retest["n_common"] == 3
    assert retest["consistency"] == pytest.approx(2 / 3)
    assert retest["strict_accuracy"] == pytest.approx(1 / 3)
    assert retest["normalized"] == pytest.approx(0.5)
    assert "归一化准确率" in score_markdown(score_sheet(sheet, later))


def test_retest_must_use_the_same_instrument() -> None:
    other = Instrument.model_validate({**TINY, "version": "other"})
    with pytest.raises(ValueError, match="同一版"):
        score_sheet(_graded(), blank_sheet(other))


def test_sheet_round_trip_is_owner_only(tmp_path: Path) -> None:
    path = tmp_path / "private" / "sheet.json"
    write_sheet(path, _graded())
    assert os.stat(path).st_mode & 0o777 == 0o600
    assert read_sheet(path).items[0].person.rating == 4


def test_out_of_range_choices_are_rejected(tmp_path: Path) -> None:
    data = json.loads(_graded().model_dump_json())
    data["items"][0]["person"]["choice"] = 7
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="答卷"):
        read_sheet(path)


def test_cli_grades_blind_then_scores(tmp_path: Path) -> None:
    path = tmp_path / "sheet.json"
    sheet = _graded()
    for row in sheet.items:
        row.person = PersonGrade()
    write_sheet(path, sheet)
    runner = CliRunner()
    # a: pick A then rate 5; b: skip; c: pick B then no rating.
    result = runner.invoke(app, ["survey", "grade", str(path)], input="A\n5\ns\nB\n\n")
    assert result.exit_code == 0, result.output
    # The person's prompt comes before the twin's answer is revealed.
    assert result.output.index("你会选") < result.output.index("分身选了：")
    graded = read_sheet(path)
    assert [r.person.choice for r in graded.items] == [0, None, 1]
    assert graded.items[1].person.skipped and graded.items[0].person.rating == 5
    scored = runner.invoke(app, ["survey", "score", str(path)])
    assert scored.exit_code == 0 and "准确率" in scored.output


def test_cli_grading_can_stop_and_resume(tmp_path: Path) -> None:
    path = tmp_path / "self.json"
    write_sheet(path, blank_sheet(tiny()))
    runner = CliRunner()
    assert runner.invoke(app, ["survey", "grade", str(path)], input="B\nq\n").exit_code == 0
    assert [r.person.choice for r in read_sheet(path).items] == [1, None, None]
    assert runner.invoke(app, ["survey", "grade", str(path)], input="C\nA\n").exit_code == 0
    assert [r.person.choice for r in read_sheet(path).items] == [1, 2, 0]


IPIP_ITEMS = [
    {
        "id": f"{trait}{n}",
        "domain": "personality",
        "question": f"虚构{trait}{n}",
        "options": ["1", "2", "3", "4", "5"],
        "ordinal": True,
        "scale": trait,
        "reverse": n == 2,
    }
    for trait in "EACNO"
    for n in (1, 2)
]


def _scaled_sheet(person: list[int], twin: list[int | None]) -> Sheet:
    survey = Instrument.model_validate({"version": "ipip-test", "title": "虚构", "items": IPIP_ITEMS})
    rows = []
    for item, mine, theirs in zip(survey.items, person, twin, strict=True):
        twin_answer = TwinAnswer(choice=theirs, choices=[theirs], modes=["grounded"], reply="", confidence=0.5)
        rows.append(SheetItem(item=item, person=PersonGrade(choice=mine), twin=twin_answer))
    return Sheet(instrument=survey.version, created=dt.date(2026, 1, 1), items=rows)


def test_scale_items_must_be_ordinal() -> None:
    bad = {**IPIP_ITEMS[0], "ordinal": False}
    with pytest.raises(ValueError, match="有序"):
        Instrument.model_validate({"version": "x", "title": "x", "items": [bad]})


def test_trait_scores_reverse_key_and_correlate() -> None:
    # Per trait: item 1 straight, item 2 reversed. Person answers (choice index 0-4 -> 1-5).
    person = [4, 0, 3, 1, 2, 2, 1, 3, 0, 4]  # E=5, A=4, C=3, N=2, O=1
    twin = [3, 1, 3, 1, 2, 2, 1, 3, None, 4]  # E=4, A=4, C=3, N=2, O=1 (from the one answered item)
    traits = score_sheet(_scaled_sheet(person, twin))["personality"]
    assert {t: v["person"] for t, v in traits["traits"].items()} == {"E": 5, "A": 4, "C": 3, "N": 2, "O": 1}
    assert traits["traits"]["E"]["twin"] == 4 and traits["traits"]["O"]["twin"] == 1
    assert traits["mae"] == pytest.approx(0.2)
    assert traits["r"] == pytest.approx(0.970, abs=1e-3)
    retest = _scaled_sheet([3, 1, 3, 1, 2, 2, 1, 3, 0, 4], [None] * 10)
    with_retest = score_sheet(_scaled_sheet(person, twin), retest)["personality"]
    assert with_retest["retest_mae"] == pytest.approx(0.2)
    assert with_retest["normalized_r"] == pytest.approx(1.0)
    assert "性格" in score_markdown(score_sheet(_scaled_sheet(person, twin)))


def _store_with_interview(question: str, answer: str) -> PersonaStore:
    store = PersonaStore(":memory:")
    settings = Settings(target_name="虚构林沐")
    store.put_source(
        parse_interview(
            "访谈_2026-01-01.txt", f"采访者：{question}\n虚构林沐：{answer}\n", settings, dt.date(2026, 1, 1)
        )
    )
    return store


def test_leakage_screen_flags_asked_questions_and_verbatim_items() -> None:
    survey = Instrument.model_validate(
        {
            "version": "leak-test",
            "title": "虚构",
            "items": [
                {
                    "id": "role",
                    "domain": "social",
                    "question": "和别人一起做事时，你通常是哪种角色？",
                    "options": ["甲", "乙"],
                },
                {"id": "sleep", "domain": "life", "question": "你通常几点睡觉？", "options": ["早", "晚"]},
            ],
        }
    )
    with _store_with_interview("和别人一起做事时，你通常是什么角色？", "我一般负责拿主意。") as store:
        assert set(screen_leakage(store, survey)) == {"role"}
        # A judge has the final word on lexical candidates.
        judge = FakeLLM(lambda *a: {"score": 20, "same": False})
        assert screen_leakage(store, survey, judge) == {}
        assert len(judge.calls) == 1
    with _store_with_interview("随便聊聊", "你通常几点睡觉？我一般十二点。") as store:
        assert screen_leakage(store, survey) == {"sleep": "题目原文出现在记忆里"}


def test_leaked_items_are_left_out_unless_asked() -> None:
    sheet = _graded()
    sheet.items[0].leak = "和记忆里问过的问题几乎一样"
    summary = score_sheet(sheet)
    assert summary["n_leaked"] == 1 and summary["overall"]["n_graded"] == 2
    assert score_sheet(sheet, include_leaked=True)["overall"]["n_graded"] == 3
    assert "未计入" in score_markdown(summary)


def test_baselines_use_only_the_self_description_or_nothing() -> None:
    seen: list[str] = []

    def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        seen.append(user)
        return {"reasoning": "虚构推理", "choice": "B"}

    intro = ask_baseline(FakeLLM(handler), tiny(), about="我是虚构林沐，喜欢安静。")
    assert intro.system == "intro" and intro.force_choice
    assert [row.twin.choice for row in intro.items if row.twin] == [1, 1, 1]
    assert all("虚构林沐" in prompt for prompt in seen)
    seen.clear()
    blank = ask_baseline(FakeLLM(handler), tiny(), about=None)
    assert blank.system == "blank" and not any("虚构林沐" in prompt for prompt in seen)
    with pytest.raises(ValueError, match="自我介绍"):
        ask_baseline(FakeLLM(handler), tiny(), about="  ")


def test_baseline_is_scored_against_the_graded_key() -> None:
    key = _graded()
    key.items[2].leak = "和记忆里问过的问题几乎一样"
    baseline = ask_baseline(FakeLLM(lambda *a: {"reasoning": "", "choice": "A"}), tiny(), about=None)
    scored = apply_key(baseline, key)
    assert [row.person.choice for row in scored.items] == [0, 2, 1]
    assert all(row.person.rating is None for row in scored.items)
    summary = score_sheet(scored)
    assert summary["system"] == "blank" and summary["n_leaked"] == 1
    assert summary["overall"]["strict_accuracy"] == pytest.approx(1 / 2)
    assert "没有任何信息的基线" in score_markdown(summary)
    other = Instrument.model_validate({**TINY, "version": "other"})
    with pytest.raises(ValueError, match="同一版"):
        apply_key(blank_sheet(other), key)
