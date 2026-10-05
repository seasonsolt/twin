from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from twin.config import Settings
from twin.persona.schema import (
    SOURCE_KIND_LABELS,
    EvidenceClass,
    Expression,
    ParsedSource,
    Source,
    SourceKind,
    evidence_class,
)
from twin.persona.sources import (
    CONTEXT_CHARS,
    CONTEXT_MESSAGES,
    meeting_to_source,
    parse_chat,
    parse_document,
    parse_text,
    source_id_for,
    source_to_meeting,
)
from twin.persona.transcript_schema import Meeting, Utterance
from twin.persona.transcripts import parse_transcript

DATE = dt.date(2026, 4, 6)


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="张明", target_aliases=["老周"])


def serialized(parsed: ParsedSource) -> ParsedSource:
    return ParsedSource(
        Source.model_validate_json(parsed.source.model_dump_json()),
        [Expression.model_validate_json(e.model_dump_json()) for e in parsed.expressions],
    )


@pytest.mark.parametrize("suffix", [".txt", ".md", ".srt", ".vtt", ".json"])
def test_synthetic_meeting_round_trip(tmp_path: Path, settings: Settings, suffix: str) -> None:
    path = tmp_path / f"2026-04-06_访谈{suffix}"
    raw = "李四：你重视什么？\n张明：先验证，再推进。"
    if suffix in {".srt", ".vtt"}:
        raw = (
            "1\n00:00:00.000 --> 00:00:01.000\n李四：你重视什么？\n\n"
            "2\n00:00:01.000 --> 00:00:02.000\n张明：先验证，再推进。\n"
        )
        if suffix == ".vtt":
            raw = "WEBVTT\n\n" + raw
    if suffix == ".json":
        raw = Meeting(
            meeting_id="访谈", date=DATE, utterances=[Utterance(idx=0, speaker="张明", text="先验证。")]
        ).model_dump_json()
    path.write_text(raw, encoding="utf-8")
    meeting = parse_transcript(path, settings)
    before = meeting.model_dump_json()
    parsed = meeting_to_source(meeting, settings)
    assert source_to_meeting(parsed) == meeting
    assert source_to_meeting(serialized(parsed)) == meeting
    assert meeting.model_dump_json() == before
    assert parsed.source.kind is SourceKind.MEETING
    assert parsed.source.meeting_id == meeting.meeting_id
    assert parsed.source.title == meeting.title
    assert parsed.source.origin == meeting.source
    assert parsed.source.first_date == parsed.source.last_date == meeting.date
    assert parsed.source.n_expressions == len(meeting.utterances)
    assert parsed.source.n_target == sum(settings.is_target(u.speaker) for u in meeting.utterances)
    assert parsed.skipped_lines == []
    for i, (expression, utterance) in enumerate(zip(parsed.expressions, meeting.utterances, strict=True)):
        assert expression.idx == i
        assert expression.utterance_idx == utterance.idx
        assert expression.speaker == utterance.speaker
        assert expression.text == utterance.text
        assert expression.date == meeting.date
        assert expression.channel == (meeting.title or meeting.meeting_id)
        assert expression.is_target == settings.is_target(utterance.speaker)
        assert not expression.narrated and not expression.held_out


def test_meeting_kind_is_actual_behavior() -> None:
    assert SourceKind.MEETING.value == "meeting"
    assert SOURCE_KIND_LABELS[SourceKind.MEETING] == "会议转写"
    assert evidence_class(SourceKind.MEETING) is EvidenceClass.BEHAVIOR


@pytest.mark.parametrize("title", ["", "评审会"])
def test_every_field_is_preserved_without_normalization(settings: Settings, title: str) -> None:
    meeting = Meeting(
        meeting_id="custom-id",
        date=DATE,
        title=title,
        source="/原始路径/转写.srt",
        utterances=[
            Utterance(idx=9, speaker="李四", text="  张明，预算\n需要调整。  ", start=0.0, end=1.125),
            Utterance(idx=3, speaker="老周", text="李四，给数据。", start=1.5),
            Utterance(idx=9, speaker="张明", text="继续。", end=9.75),
            Utterance(idx=-1, speaker="李四", text=""),
            Utterance(idx=20, speaker="李四", text=" \n "),
        ],
    )
    parsed = meeting_to_source(meeting, settings)
    assert source_to_meeting(serialized(parsed)) == meeting
    assert len(parsed.expressions) == len(meeting.utterances)
    assert [e.idx for e in parsed.expressions] == list(range(5))
    assert [e.is_target for e in parsed.expressions] == [False, True, True, False, False]
    assert all(e.channel == (title or meeting.meeting_id) for e in parsed.expressions)
    assert parsed.expressions[1].speaker == "老周"
    assert parsed.expressions[1].text == "李四，给数据。"


@pytest.mark.parametrize("utterances", [[], [Utterance(idx=7, speaker="李四", text="稍后开会。")]])
def test_empty_and_non_target_only_meetings(settings: Settings, utterances: list[Utterance]) -> None:
    meeting = Meeting(meeting_id="", date=DATE, utterances=utterances)
    parsed = meeting_to_source(meeting, settings)
    assert source_to_meeting(serialized(parsed)) == meeting
    assert parsed.source.n_target == 0
    assert all(e.context == "" and e.start is None and e.end is None for e in parsed.expressions)


def test_already_merged_utterances_stay_merged(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "2026-04-06_评审.txt"
    path.write_text("李四：成本增加。\n李四：需要调整预算。\n老周：先给明细。\n张明：下周再议。\n", encoding="utf-8")
    meeting = parse_transcript(path, settings)
    assert [u.speaker for u in meeting.utterances] == ["李四", "张明"]
    assert [u.text for u in meeting.utterances] == ["成本增加。需要调整预算。", "先给明细。下周再议。"]
    parsed = meeting_to_source(meeting, settings)
    assert len(parsed.expressions) == 2
    assert source_to_meeting(parsed) == meeting


def test_context_uses_chat_rule_and_limits(settings: Settings) -> None:
    messages = [
        ("张明", "开始。"),
        *[("李四", f"报告{i}") for i in range(CONTEXT_MESSAGES + 1)],
        ("张明", "给数据。"),
        ("张明", "继续。"),
        ("李四", "预算 " + "很长" * CONTEXT_CHARS),
        ("老周", "明细呢？"),
    ]
    meeting = Meeting(
        meeting_id="context",
        date=DATE,
        utterances=[Utterance(idx=i, speaker=speaker, text=text) for i, (speaker, text) in enumerate(messages)],
    )
    parsed = meeting_to_source(meeting, settings)
    chat_settings = settings.model_copy(update={"pseudonymize_others": False})
    chat = parse_chat("chat.txt", "\n".join(f"{DATE} 10:00 {s}：{t}" for s, t in messages), chat_settings)
    assert [e.context for e in parsed.expressions] == [e.context for e in chat.expressions]
    assert parsed.expressions[CONTEXT_MESSAGES + 2].context == "李四：报告1 李四：报告2 李四：报告3"
    assert parsed.expressions[CONTEXT_MESSAGES + 3].context == ""
    assert len(parsed.expressions[-1].context) == CONTEXT_CHARS
    assert parsed.expressions[-1].context.startswith("…")


def test_ids_are_stable_content_derived_and_positionally_unique(settings: Settings) -> None:
    meeting = Meeting(
        meeting_id="stable",
        date=DATE,
        utterances=[Utterance(idx=4, speaker="张明", text="好。") for _ in range(2)],
    )
    first = meeting_to_source(meeting, settings)
    second = meeting_to_source(Meeting.model_validate_json(meeting.model_dump_json()), settings)
    expected = source_id_for(SourceKind.MEETING, meeting.source, meeting.model_dump_json())
    assert first.source.source_id == second.source.source_id == expected
    assert [e.expression_id for e in first.expressions] == [f"{expected}#{i:05d}" for i in range(2)]
    assert first.expressions == second.expressions
    changed_settings = settings.model_copy(update={"target_name": "其他人", "target_aliases": []})
    assert meeting_to_source(meeting, changed_settings).source.source_id == expected
    for field, value in [("meeting_id", "different"), ("title", "different"), ("source", "different")]:
        changed = meeting.model_copy(update={field: value})
        assert meeting_to_source(changed, settings).source.source_id != expected
    changed_utterance = meeting.utterances[0].model_copy(update={"start": 0.25})
    changed = meeting.model_copy(update={"utterances": [changed_utterance, meeting.utterances[1]]})
    assert meeting_to_source(changed, settings).source.source_id != expected


def test_legacy_serialized_models_load_with_optional_fields_absent(settings: Settings) -> None:
    document = parse_document("旧文档.md", "给数据。", settings, DATE)
    source_data = document.source.model_dump(mode="json", exclude={"meeting_id"})
    expression_data = document.expressions[0].model_dump(mode="json", exclude={"utterance_idx", "start", "end"})
    source = Source.model_validate(source_data)
    expression = Expression.model_validate(expression_data)
    assert source == document.source and source.meeting_id is None
    assert expression == document.expressions[0]
    assert expression.utterance_idx is None and expression.start is None and expression.end is None


def test_inverse_rejects_non_meetings_and_missing_round_trip_metadata(settings: Settings) -> None:
    with pytest.raises(ValueError, match="requires a meeting source"):
        source_to_meeting(parse_document("d.md", "给数据。", settings))
    meeting = Meeting(meeting_id="m", date=DATE, utterances=[Utterance(idx=0, speaker="张明", text="好。")])
    parsed = meeting_to_source(meeting, settings)
    for field in ("meeting_id", "first_date"):
        incomplete = ParsedSource(parsed.source.model_copy(update={field: None}), parsed.expressions)
        with pytest.raises(ValueError, match="missing meeting_id or date"):
            source_to_meeting(incomplete)
    incomplete = ParsedSource(parsed.source, [parsed.expressions[0].model_copy(update={"utterance_idx": None})])
    with pytest.raises(ValueError, match="missing utterance_idx"):
        source_to_meeting(incomplete)
    with pytest.raises(ValueError, match="cannot determine the meeting date"):
        parse_text(SourceKind.MEETING, "m.txt", "张明：好。", settings)
    parsed_text = parse_text(SourceKind.MEETING, "m.txt", "张明：好。", settings, DATE)
    assert parsed_text.expressions[0].text == "好。"
