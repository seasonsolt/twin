from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import numpy as np
import pytest

from twin.config import Settings
from twin.persona.transcript_schema import Meeting, Utterance
from twin.persona.transcripts import funasr_to_utterances, load_speaker_map, parse_transcript


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="本人", target_aliases=["本人裁", "Alexander Hamilton-Smith"])


def write(directory: Path, name: str, content: str, encoding: str = "utf-8") -> Path:
    path = directory / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content.encode(encoding))
    return path


def turns(meeting: Meeting) -> list[tuple[str, str]]:
    return [(u.speaker, u.text) for u in meeting.utterances]


def assert_idx_sequential(meeting: Meeting) -> None:
    assert [u.idx for u in meeting.utterances] == list(range(len(meeting.utterances)))


# ---------------------------------------------------------------- line transcripts


def test_colon_lines_with_bom_crlf_and_body_colons(tmp_path: Path, settings: Settings) -> None:
    text = (
        "﻿会议主题：Q3 交流\r\n"
        "\r\n"
        "本人：大家好。\r\n"
        "张三: 我汇报三点。\r\n"
        "第一：成本下降 5%。\r\n"
        "（二）：交付提前。\r\n"
        "参考 https://example.com/a\r\n"
        "会议改到 10:30 开始\r\n"
        "我们这个季度最最重要的核心目标是：利润\r\n"
        "\r\n"
        "本人裁：好的：继续。\r\n"
    )
    path = write(tmp_path, "交流_2025-03-17.txt", text)
    meeting = parse_transcript(path, settings)
    assert meeting.meeting_id == "交流_2025-03-17"
    assert meeting.date == dt.date(2025, 3, 17)
    assert meeting.title == "交流_2025-03-17"
    assert meeting.source == str(path)
    assert turns(meeting) == [
        ("本人", "大家好。"),
        (
            "张三",
            "我汇报三点。第一：成本下降 5%。（二）：交付提前。参考 https://example.com/a"
            "会议改到 10:30 开始我们这个季度最最重要的核心目标是：利润",
        ),
        ("本人", "好的：继续。"),
    ]
    assert_idx_sequential(meeting)


def test_long_labels_need_to_recur_or_be_known(tmp_path: Path, settings: Settings) -> None:
    text = (
        "John: Let's start.\n"
        "Maria Gonzalez-Lee: Revenue is up.\n"
        "Thanks, quick note on churn too.\n"
        "Alexander Hamilton-Smith: Why?\n"
        "Maria Gonzalez-Lee: Pricing.\n"
        "The executive summary is: we grew\n"
    )
    meeting = parse_transcript(write(tmp_path, "sync_20250317.txt", text), settings)
    assert turns(meeting) == [
        ("John", "Let's start."),
        ("Maria Gonzalez-Lee", "Revenue is up. Thanks, quick note on churn too."),
        ("本人", "Why?"),
        ("Maria Gonzalez-Lee", "Pricing. The executive summary is: we grew"),
    ]


def test_sentence_fragments_and_field_labels_are_not_speakers(tmp_path: Path, settings: Settings) -> None:
    text = (
        "本人：我说两点。\n"
        "问题是：现金流不够。\n"
        "我觉得：可以再等等。\n"
        "张三：我汇报一下。\n"
        "上周：完成了A。\n"
        "本周计划：做B。\n"
        "负责人：李四\n"
        "对了：还有C。\n"
        "客户说：不行。\n"
        "本人：问题是：为什么？\n"
        "张三：问题是：供应商。\n"
    )
    meeting = parse_transcript(write(tmp_path, "2025-03-17.txt", text), settings)
    assert turns(meeting) == [
        ("本人", "我说两点。问题是：现金流不够。我觉得：可以再等等。"),
        ("张三", "我汇报一下。上周：完成了A。本周计划：做B。负责人：李四对了：还有C。客户说：不行。"),
        ("本人", "问题是：为什么？"),
        ("张三", "问题是：供应商。"),
    ]


def test_english_fragments_rejected_but_letter_and_acronym_labels_kept(tmp_path: Path, settings: Settings) -> None:
    text = "A: hello\nThe point is: margin\nI: why?\nThe point is: cost\nIT: system is live\nA: thanks\n"
    meeting = parse_transcript(write(tmp_path, "2025-03-17.txt", text), settings)
    assert turns(meeting) == [
        ("A", "hello The point is: margin"),
        ("I", "why? The point is: cost"),
        ("IT", "system is live"),
        ("A", "thanks"),
    ]


def test_name_then_timestamp_then_colon(tmp_path: Path, settings: Settings) -> None:
    text = "张三 00:01:23: 内容一\n本人 1:02:03：内容二\n会议改到 10:30 开始\n"
    meeting = parse_transcript(write(tmp_path, "2025-03-17.txt", text), settings)
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("张三", "内容一", 83.0),
        ("本人", "内容二会议改到 10:30 开始", 3723.0),
    ]


def test_timestamped_lines_and_standalone_timestamps(tmp_path: Path, settings: Settings) -> None:
    text = (
        "[00:00:05] 本人: 开始吧\n"
        "(00:00:10) 张三：好的\n"
        "【00:00:20】李四：我补充\n"
        "00:00:30 王五：嗯\n"
        "[00:00:40] 我再补充一句\n"
        "00:01:00\n"
        "本人：结束\n"
        "[01:02:03.5 - 01:02:09] 张三: 区间时间戳\n"
    )
    meeting = parse_transcript(write(tmp_path, "20250318.txt", text), settings)
    assert meeting.meeting_id == "20250318"
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("本人", "开始吧", 5.0),
        ("张三", "好的", 10.0),
        ("李四", "我补充", 20.0),
        ("王五", "嗯我再补充一句", 30.0),
        ("本人", "结束", 60.0),
        ("张三", "区间时间戳", 3723.5),
    ]


def test_name_with_bracketed_timestamp_and_content_below(tmp_path: Path, settings: Settings) -> None:
    text = "张三(00:00:05):\n今天汇报进展。\n风险：供应商延期。\n本人（00:01:10）：\n为什么？\n"
    meeting = parse_transcript(write(tmp_path, "2025-03-18.txt", text), settings)
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("张三", "今天汇报进展。风险：供应商延期。", 5.0),
        ("本人", "为什么？", 70.0),
    ]


def test_markdown_decorations_are_stripped(tmp_path: Path, settings: Settings) -> None:
    text = "# 交流记录\n\n- **本人**：先看数据。\n- **张三**：Q3 完成 80%。\n> 李四：补充一下\n---\n继续说\n"
    meeting = parse_transcript(write(tmp_path, "2025年3月20日交流.md", text), settings)
    assert turns(meeting) == [("本人", "先看数据。"), ("张三", "Q3 完成 80%。"), ("李四", "补充一下继续说")]


def test_markdown_headings_as_speaker_headers(tmp_path: Path, settings: Settings) -> None:
    text = "# 交流 2025-03-20\n\n## 本人 00:00:05\n先看数据。\n\n### **张三** [00:00:30]\n好的。\n## 附录\n"
    meeting = parse_transcript(write(tmp_path, "2025-03-20.md", text), settings)
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("本人", "先看数据。", 5.0),
        ("张三", "好的。", 30.0),
    ]


# ---------------------------------------------------------------- header blocks


def test_header_blocks_with_sidecar_mapping(tmp_path: Path, settings: Settings) -> None:
    text = (
        "飞书妙记 交流\n"
        "说话人 1 00:00:05\n"
        "大家好，今天开会。\n"
        "目标：增长 30%\n"
        "\n"
        "说话人 2 00:01:10\n"
        "好的：我先说。\n"
        "\n"
        "张三  00:02:00\n"
        "我再补充。\n"
        "说话人 3 01:05\n"
        "收到\n"
    )
    path = write(tmp_path, "交流_2025_03_19.txt", text)
    write(tmp_path, "交流_2025_03_19.speakers.json", json.dumps({"说话人1": "本人", "说话人 2": "张三"}))
    meeting = parse_transcript(path, settings)
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("本人", "大家好，今天开会。目标：增长 30%", 5.0),
        ("张三", "好的：我先说。我再补充。", 70.0),
        ("说话人 3", "收到", 65.0),
    ]
    assert_idx_sequential(meeting)


def test_header_blocks_keep_out_of_order_one_off_headers_as_content(tmp_path: Path, settings: Settings) -> None:
    text = (
        "说话人 1 00:00:05\n"
        "大家好。\n"
        "会议改到 10:30\n"
        "请大家注意时间。\n"
        "说话人 2 00:01:10\n"
        "截止到 23:00\n"
        "王五 00:01:40\n"
        "我插一句。\n"
        "说话人 1 00:02:00\n"
        "再说。\n"
    )
    meeting = parse_transcript(write(tmp_path, "2025-03-17.txt", text), settings)
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("说话人 1", "大家好。会议改到 10:30请大家注意时间。", 5.0),
        ("说话人 2", "截止到 23:00", 70.0),
        ("王五", "我插一句。", 100.0),
        ("说话人 1", "再说。", 120.0),
    ]


def test_header_blocks_with_timestamp_first(tmp_path: Path, settings: Settings) -> None:
    text = "[00:00:05] 本人\n先看数据。\n[00:00:30] 张三\n好的，\n马上看。\n"
    meeting = parse_transcript(write(tmp_path, "2025-03-21.txt", text), settings)
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("本人", "先看数据。", 5.0),
        ("张三", "好的，马上看。", 30.0),
    ]


# ---------------------------------------------------------------- subtitles


def test_srt_cues(tmp_path: Path, settings: Settings) -> None:
    text = (
        "1\n00:00:01,000 --> 00:00:04,000\n本人: 开始。\n\n"
        "2\n00:00:04,500 --> 00:00:06,000\n继续说。\n\n"
        "3\n00:00:07,000 --> 00:00:09,250\n张三：第一行\n第二行\n"
        "4\n00:00:10,000 --> 00:00:12,000\n李四: 我来\n王五: 我也来\n"
    )
    meeting = parse_transcript(write(tmp_path, "交流_20250317.srt", text), settings)
    assert [(u.speaker, u.text, u.start, u.end) for u in meeting.utterances] == [
        ("本人", "开始。继续说。", 1.0, 6.0),
        ("张三", "第一行第二行", 7.0, 9.25),
        ("李四", "我来", 10.0, 12.0),
        ("王五", "我也来", 10.0, 12.0),
    ]


def test_vtt_cues_with_voice_tags(tmp_path: Path, settings: Settings) -> None:
    text = (
        "WEBVTT\n\n"
        "NOTE 自动生成\n\n"
        "intro\n00:01.000 --> 00:03.000 align:start\n<v 本人>为什么<i>延期</i>？</v>\n\n"
        "00:03.500 --> 00:05.000\n张三: 供应商问题\n"
    )
    meeting = parse_transcript(write(tmp_path, "2025-03-17.vtt", text), settings)
    assert [(u.speaker, u.text, u.start, u.end) for u in meeting.utterances] == [
        ("本人", "为什么延期？", 1.0, 3.0),
        ("张三", "供应商问题", 3.5, 5.0),
    ]


def test_subtitles_without_speakers_raise(tmp_path: Path, settings: Settings) -> None:
    path = write(tmp_path, "2025-03-17.srt", "1\n00:00:01,000 --> 00:00:02,000\n只有字幕\n")
    with pytest.raises(ValueError, match="no speaker labels"):
        parse_transcript(path, settings)


def test_cue_text_shaped_like_a_timing_line_stays_text(tmp_path: Path, settings: Settings) -> None:
    text = (
        "1\n00:00:01,000 --> 00:00:04,000\n王芳: 培训安排如下\n10:00 --> 11:30 产品培训\n\n"
        "2\n00:00:05,000 --> 00:00:06,000\n本人: 要签到。\n"
    )
    meeting = parse_transcript(write(tmp_path, "2025-03-17.srt", text), settings)
    assert [(u.speaker, u.text, u.start, u.end) for u in meeting.utterances] == [
        ("王芳", "培训安排如下10:00 --> 11:30 产品培训", 1.0, 4.0),
        ("本人", "要签到。", 5.0, 6.0),
    ]


@pytest.mark.parametrize("suffix", [".txt", ".md"])
@pytest.mark.parametrize(
    ("schedule", "wang_text"),
    [
        (
            "10:00 --> 11:30 产品培训\n14:00 --> 15:00 合规培训\n",
            "下周一安排：10:00 --> 11:30 产品培训14:00 --> 15:00 合规培训",
        ),
        (
            "10:00 --> 11:30 产品培训\n14:00 --> 15:00 合规培训\n\n",
            "下周一安排：10:00 --> 11:30 产品培训14:00 --> 15:00 合规培训",
        ),
        ("10:00 --> 11:30\n产品培训\n14:00 --> 15:00\n合规培训\n", "下周一安排：产品培训合规培训"),
    ],
    ids=["inline", "inline-then-blank", "bare-timing-lines"],
)
def test_cue_shaped_lines_in_a_line_transcript_keep_every_utterance(
    tmp_path: Path, settings: Settings, suffix: str, schedule: str, wang_text: str
) -> None:
    text = (
        "[00:12:00] 主持人：请王芳说一下培训。\n"
        "[00:12:10] 王芳：下周一安排：\n"
        f"{schedule}"
        "[00:14:00] 本人：要签到。\n"
        "[00:14:20] 张三：好的。\n"
        "[00:14:30] 本人：散会。\n"
    )
    meeting = parse_transcript(write(tmp_path, f"2026-04-27_交流{suffix}", text), settings)
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("主持人", "请王芳说一下培训。", 720.0),
        ("王芳", wang_text, 730.0),
        ("本人", "要签到。", 840.0),
        ("张三", "好的。", 860.0),
        ("本人", "散会。", 870.0),
    ]


@pytest.mark.parametrize(
    "template",
    ["{s} --> {e} {line}", "{s} - {e} {line}", "[{s} --> {e}] {line}"],
    ids=["arrow", "dash", "bracketed-arrow"],
)
def test_inline_timestamp_ranges_in_text_transcripts(tmp_path: Path, settings: Settings, template: str) -> None:
    rows = [
        ("00:00:01", "00:00:05", "李明: 先看数据。"),
        ("00:00:06", "00:00:09", "本人: 为什么？"),
        ("00:00:10", "00:00:12", "李明: 渠道。"),
    ]
    text = "".join(template.format(s=s, e=e, line=line) + "\n" for s, e, line in rows)
    meeting = parse_transcript(write(tmp_path, "2025-03-17.txt", text), settings)
    assert [(u.speaker, u.text, u.start) for u in meeting.utterances] == [
        ("李明", "先看数据。", 1.0),
        ("本人", "为什么？", 6.0),
        ("李明", "渠道。", 10.0),
    ]


@pytest.mark.parametrize("suffix", [".txt", ".md"])
def test_real_cues_in_text_files_are_still_subtitles(tmp_path: Path, settings: Settings, suffix: str) -> None:
    srt = (
        "交流字幕\n\n"
        "1\n00:00:01,000 --> 00:00:04,000\n本人: 开始。\n\n"
        "2\n00:00:04,500 --> 00:00:06,000\n继续说。\n\n"
        "3\n00:00:07,000 --> 00:00:09,250\n张三：第一行\n第二行\n"
        "4\n00:00:10,000 --> 00:00:12,000\n李四: 我来\n"
    )
    meeting = parse_transcript(write(tmp_path, f"2025-03-17{suffix}", srt), settings)
    assert [(u.speaker, u.text, u.start, u.end) for u in meeting.utterances] == [
        ("本人", "开始。继续说。", 1.0, 6.0),
        ("张三", "第一行第二行", 7.0, 9.25),
        ("李四", "我来", 10.0, 12.0),
    ]
    vtt = (
        "WEBVTT\nKind: captions\n\nNOTE 自动生成\n第二行注释\n\n"
        "intro\n00:01.000 --> 00:03.000 align:start position:10%\n<v 本人>为什么延期？\n\n"
        "00:03.500 --> 00:05.000\n<v 张三>供应商问题\n"
    )
    voiced = parse_transcript(write(tmp_path, f"2025-03-18{suffix}", vtt), settings)
    assert [(u.speaker, u.text, u.start, u.end) for u in voiced.utterances] == [
        ("本人", "为什么延期？", 1.0, 3.0),
        ("张三", "供应商问题", 3.5, 5.0),
    ]


def test_text_outside_cues_in_a_text_file_is_never_dropped_silently(tmp_path: Path, settings: Settings) -> None:
    voiced = (
        "00:00:01.000 --> 00:00:03.000\n<v 本人>为什么延期？\n\n"
        "会后补充\n\n"
        "张三补充：供应商下周到货\n"
        "00:00:03.500 --> 00:00:05.000\n<v 张三>供应商问题\n"
    )
    with pytest.raises(ValueError, match=r"2 line\(s\) outside subtitle cues.*'会后补充'"):
        parse_transcript(write(tmp_path, "2025-03-17.txt", voiced), settings)

    labelled = (
        "00:00:01.000 --> 00:00:03.000\n本人: 为什么延期？\n\n"
        "供应商下周到货\n\n"
        "00:00:03.500 --> 00:00:05.000\n张三: 供应商问题\n"
    )
    meeting = parse_transcript(write(tmp_path, "2025-03-18.txt", labelled), settings)
    assert [u.speaker for u in meeting.utterances] == ["本人", "张三"]
    assert "供应商下周到货" in meeting.utterances[0].text


# ---------------------------------------------------------------- errors and encodings


def test_unrecognised_text_raises(tmp_path: Path, settings: Settings) -> None:
    path = write(tmp_path, "2025-03-17.txt", "这是一段没有说话人的会议纪要。\n大家讨论了很多事情，最后决定下周再议。\n")
    with pytest.raises(ValueError, match="unrecognised transcript format"):
        parse_transcript(path, settings)


def test_unsupported_suffix_and_unrecognised_json_raise(tmp_path: Path, settings: Settings) -> None:
    with pytest.raises(ValueError, match="unsupported file type"):
        parse_transcript(write(tmp_path, "2025-03-17.docx", "本人：好"), settings)
    with pytest.raises(ValueError, match="unrecognised JSON"):
        parse_transcript(write(tmp_path, "2025-03-17.json", json.dumps({"foo": 1})), settings)
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_transcript(write(tmp_path, "2025-03-18.json", "{not json"), settings)


@pytest.mark.parametrize("encoding", ["gb18030", "utf-16"])
def test_non_utf8_encodings(tmp_path: Path, settings: Settings, encoding: str) -> None:
    path = write(tmp_path, "2025-03-17.txt", "本人：预算怎么算的？\n张三：按去年口径。\n", encoding=encoding)
    assert turns(parse_transcript(path, settings)) == [("本人", "预算怎么算的？"), ("张三", "按去年口径。")]


# ---------------------------------------------------------------- dates and ids


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("交流_2025-03-17.txt", dt.date(2025, 3, 17)),
        ("20250317交流.txt", dt.date(2025, 3, 17)),
        ("交流_2025_03_17.txt", dt.date(2025, 3, 17)),
        ("交流 2025.3.7.txt", dt.date(2025, 3, 7)),
        ("2025年3月17日交流.txt", dt.date(2025, 3, 17)),
        ("交流-2025 年 03 月 17 日.txt", dt.date(2025, 3, 17)),
        ("v2_交流_20251399_20250318.txt", dt.date(2025, 3, 18)),
        ("录音20250317143000.txt", dt.date(2025, 3, 17)),
        ("rec_202503171430.txt", dt.date(2025, 3, 17)),
        ("交流_2025-03-17T14-30.txt", dt.date(2025, 3, 17)),
        ("1787-05-30_制宪会议.txt", dt.date(1787, 5, 30)),
        ("1723-04-03_田文鏡.txt", dt.date(1723, 4, 3)),
        ("0627-01-01_贞观元年.txt", dt.date(627, 1, 1)),
        ("1731年11月25日_硃批.txt", dt.date(1731, 11, 25)),
    ],
)
def test_date_from_file_name(tmp_path: Path, settings: Settings, name: str, expected: dt.date) -> None:
    meeting = parse_transcript(write(tmp_path, name, "本人：好。\n"), settings)
    assert meeting.date == expected
    assert meeting.meeting_id == Path(name).stem


@pytest.mark.parametrize("name", ["0000-01-01_会.txt", "1787-13-30_会.txt", "17870530_会.txt"])
def test_invalid_or_compact_pre_1900_dates_are_not_guessed(tmp_path: Path, settings: Settings, name: str) -> None:
    with pytest.raises(ValueError, match="cannot determine the meeting date"):
        parse_transcript(write(tmp_path, name, "本人：好。\n"), settings)


def test_missing_date_raises_and_argument_date_prefixes_id(tmp_path: Path, settings: Settings) -> None:
    path = write(tmp_path, "交流_12345678.txt", "本人：好。\n")
    with pytest.raises(ValueError, match="cannot determine the meeting date"):
        parse_transcript(path, settings)
    meeting = parse_transcript(path, settings, meeting_date=dt.date(2025, 3, 17))
    assert meeting.meeting_id == "2025-03-17_交流_12345678"
    custom = parse_transcript(path, settings, meeting_date=dt.date(2025, 3, 17), meeting_id="m1")
    assert custom.meeting_id == "m1"
    dated = write(tmp_path, "交流_20250317.txt", "本人：好。\n")
    overridden = parse_transcript(dated, settings, meeting_date=dt.date(2025, 4, 1))
    assert (overridden.date, overridden.meeting_id) == (dt.date(2025, 4, 1), "交流_20250317")


# ---------------------------------------------------------------- speakers and merging


def test_speaker_map_argument_overrides_sidecar_then_aliases(tmp_path: Path, settings: Settings) -> None:
    path = write(tmp_path, "2025-03-17.txt", "spk0：开始\nspk1：好\nspk2：嗯\n")
    write(tmp_path, "2025-03-17.speakers.json", json.dumps({"spk0": "张三", "spk1": "李四"}))
    assert load_speaker_map(path, {"spk0": "本人裁"}) == {"spk0": "本人裁", "spk1": "李四"}
    meeting = parse_transcript(path, settings, speaker_map={"spk0": "本人裁"})
    assert turns(meeting) == [("本人", "开始"), ("李四", "好"), ("spk2", "嗯")]


def test_invalid_speaker_maps_raise(tmp_path: Path, settings: Settings) -> None:
    path = write(tmp_path, "2025-03-17.txt", "spk0：开始\n")
    with pytest.raises(ValueError, match="non-empty names"):
        parse_transcript(path, settings, speaker_map={"spk0": " "})
    write(tmp_path, "2025-03-17.speakers.json", json.dumps(["spk0", "本人"]))
    with pytest.raises(ValueError, match="expected a JSON object"):
        parse_transcript(path, settings)
    write(tmp_path, "2025-03-17.speakers.json", "{broken")
    with pytest.raises(ValueError, match="invalid JSON"):
        parse_transcript(path, settings)


def test_merge_consecutive_renumbers_idx(tmp_path: Path, settings: Settings) -> None:
    text = "[00:00:01] spk0: 第一句\n[00:00:03] spk2: 第二句\n[00:00:05] spk1: 插话\n[00:00:07] spk0: 回来\n"
    path = write(tmp_path, "2025-03-17.txt", text)
    write(tmp_path, "2025-03-17.speakers.json", json.dumps({"spk0": "本人", "spk2": "本人裁", "spk1": "张三"}))
    merged = parse_transcript(path, settings)
    assert [(u.idx, u.speaker, u.text, u.start) for u in merged.utterances] == [
        (0, "本人", "第一句第二句", 1.0),
        (1, "张三", "插话", 5.0),
        (2, "本人", "回来", 7.0),
    ]
    unmerged = parse_transcript(path, settings, merge_consecutive=False)
    assert [(u.idx, u.speaker) for u in unmerged.utterances] == [(0, "本人"), (1, "本人"), (2, "张三"), (3, "本人")]


# ---------------------------------------------------------------- JSON inputs


def test_meeting_json_is_renormalised(tmp_path: Path, settings: Settings) -> None:
    data = {
        "meeting_id": "weekly-42",
        "date": "2025-03-17",
        "title": "第 42 次交流",
        "utterances": [
            {"idx": 5, "speaker": "本人裁", "text": "先说结论。", "start": 1.0, "end": 2.0},
            {"idx": 9, "speaker": "本人", "text": "再说原因。", "start": 2.5, "end": 4.0},
            {"idx": 11, "speaker": "张三", "text": "  ", "start": None, "end": None},
            {"idx": 12, "speaker": "张三", "text": "明白。"},
        ],
    }
    path = write(tmp_path, "export.json", json.dumps(data, ensure_ascii=False))
    meeting = parse_transcript(path, settings)
    assert (meeting.meeting_id, meeting.date, meeting.title) == ("weekly-42", dt.date(2025, 3, 17), "第 42 次交流")
    assert [(u.idx, u.speaker, u.text, u.start, u.end) for u in meeting.utterances] == [
        (0, "本人", "先说结论。再说原因。", 1.0, 4.0),
        (1, "张三", "明白。", None, None),
    ]
    overridden = parse_transcript(path, settings, meeting_date=dt.date(2025, 3, 18), meeting_id="x")
    assert (overridden.meeting_id, overridden.date) == ("x", dt.date(2025, 3, 18))

    bad = write(tmp_path, "bad_2025-03-17.json", json.dumps({"utterances": [{"speaker": "本人"}]}))
    with pytest.raises(ValueError, match=r"utterances\[0\] is invalid"):
        parse_transcript(bad, settings)


def test_funasr_json_file_with_sidecar(tmp_path: Path, settings: Settings) -> None:
    result = [
        {
            "key": "meeting",
            "text": "开始吧。好的。",
            "sentence_info": [
                {"text": "开始吧。", "start": 1230, "end": 2500, "spk": 0},
                {"text": "好的。", "start": 2600, "end": 3100, "spk": 1},
            ],
        }
    ]
    path = write(tmp_path, "交流_20250317.json", json.dumps(result, ensure_ascii=False))
    write(tmp_path, "交流_20250317.speakers.json", json.dumps({"spk0": "本人"}))
    meeting = parse_transcript(path, settings)
    assert [(u.speaker, u.text, u.start, u.end) for u in meeting.utterances] == [
        ("本人", "开始吧。", 1.23, 2.5),
        ("spk1", "好的。", 2.6, 3.1),
    ]


def test_funasr_to_utterances_variants() -> None:
    single = {
        "key": "a",
        "sentence_info": [
            {"text": "前言", "start": 0, "end": 100},
            {"text": "第一句", "start": 100, "end": 900, "spk": np.int64(2)},
            {"text": "", "start": 900, "end": 950, "spk": 0},
            {"text": "续", "start": 1000, "end": "bad"},
            {"sentence": "旧版字段", "start": 2000.0, "end": 2500.0, "spk": "1"},
            {"text": "已带前缀", "start": 3000, "end": 3500, "spk": "spk3"},
            "not a sentence",
        ],
    }
    assert funasr_to_utterances(single) == [
        Utterance(idx=0, speaker="spk2", text="前言", start=0.0, end=0.1),
        Utterance(idx=1, speaker="spk2", text="第一句", start=0.1, end=0.9),
        Utterance(idx=2, speaker="spk2", text="续", start=1.0, end=None),
        Utterance(idx=3, speaker="spk1", text="旧版字段", start=2.0, end=2.5),
        Utterance(idx=4, speaker="spk3", text="已带前缀", start=3.0, end=3.5),
    ]
    many = funasr_to_utterances(
        [
            {"sentence_info": [{"text": "甲", "start": 0, "end": 10, "spk": 0}]},
            {"text": "", "sentence_info": []},
            {"sentence_info": [{"text": "乙", "start": 0, "end": 10, "spk": 1}]},
        ]
    )
    assert [(u.idx, u.speaker, u.text) for u in many] == [(0, "spk0", "甲"), (1, "spk1", "乙")]
    assert funasr_to_utterances([]) == []
    assert funasr_to_utterances({"key": "silence", "text": ""}) == []


def test_funasr_to_utterances_errors() -> None:
    with pytest.raises(ValueError, match="no 'sentence_info'"):
        funasr_to_utterances([{"key": "a", "text": "有文字没有分句"}])
    with pytest.raises(ValueError, match="no speaker labels"):
        funasr_to_utterances({"sentence_info": [{"text": "无说话人", "start": 0, "end": 10}]})
    with pytest.raises(ValueError, match="unexpected FunASR result item"):
        funasr_to_utterances(["text"])
    with pytest.raises(ValueError, match="must be a list"):
        funasr_to_utterances({"sentence_info": {"text": "x"}})
