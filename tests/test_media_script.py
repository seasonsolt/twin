"""Presentation preserves source text, provenance and abstention."""

from __future__ import annotations

import datetime as dt
from itertools import pairwise
from pathlib import Path

import pytest
from pydantic import ValidationError

from twin.media.adapters import (
    presentable_from_chat_reply,
    presentable_from_payload,
)
from twin.media.render import export_html, render_audio
from twin.media.schema import (
    MediaManifest,
    MediaScript,
    PresentableAnswer,
)
from twin.media.script import script_from_presentable, speech_script, split_sentences
from twin.media.speech_text import split_speech
from twin.media.tts import SilentSynthesizer
from twin.persona.schema import ChatReply
from twin.util import fingerprint


@pytest.fixture
def reply() -> ChatReply:
    return ChatReply(
        reply="先验证。再推进！",
        citations=["pi_synthetic", "ex_synthetic"],
        confidence=0.6,
        abstain=False,
        abstain_reason="",
        retrieved_ids=["pi_synthetic"],
        as_of=dt.date(2026, 1, 2),
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", []),
        (" \n\r\n ", []),
        ("  甲。乙！？第三!?…尾巴  ", ["甲。", "乙！？", "第三!?…", "尾巴"]),
        ("First. Second! Last? Tail", ["First.", "Second!", "Last?", "Tail"]),
        ("增长3.5%", ["增长3.5%"]),
        ("v1.2 版本", ["v1.2 版本"]),
        ("结尾.", ["结尾."]),
        ("Done. Next.", ["Done.", "Next."]),
        ("3.5%增长。v1.2 版本！Done. Next.", ["3.5%增长。", "v1.2 版本！", "Done.", "Next."]),
        ("甲.乙", ["甲.乙"]),
        ('He said "Done." Next.', ['He said "Done."', "Next."]),
        ("Done.\nNext.", ["Done.", "Next."]),
        ("“Done. Next.”结束。", ["“Done. Next.”结束。"]),
        ("甲\r\n乙\n丙", ["甲", "乙", "丙"]),
        ("他说「可以！但先验证？」再决定。后续", ["他说「可以！但先验证？」再决定。", "后续"]),
        ("“甲。\n「乙！？…」丙”丁！尾", ["“甲。\n「乙！？…」丙”丁！", "尾"]),
        ("“未闭合。还有！", ["“未闭合。还有！"]),
        ("甲  乙。\t丙  丁", ["甲  乙。", "丙  丁"]),
    ],
)
def test_split_sentences(text: str, expected: list[str]) -> None:
    assert split_sentences(text) == expected


def test_chat_provenance(reply: ChatReply) -> None:
    p = presentable_from_chat_reply(reply)
    assert p.text == reply.reply
    script = script_from_presentable(p, "合成人物")
    assert MediaScript.model_validate_json(script.model_dump_json()) == script
    assert script.source_kind == "chat_reply"
    assert script.source_fingerprint == fingerprint(reply.model_dump(mode="json"))
    assert [s.text for s in script.segments] == split_sentences(reply.reply)
    assert [c.ref_id for c in script.citations] == reply.citations
    assert all(c.reason == "" for c in script.citations)
    assert (script.as_of, script.confidence) == (reply.as_of, reply.confidence)


@pytest.mark.parametrize("reason", ["  证据不足  ", "", "  \n "])
def test_abstain_speaks_reply_not_reason(reply: ChatReply, reason: str) -> None:
    reply.abstain = True
    reply.abstain_reason = reason
    for p in [presentable_from_chat_reply(reply)]:
        script = script_from_presentable(p, "合成人物")
        assert script.abstain
        assert all(s.kind == "speech" for s in script.segments)
        assert [s.text for s in script.segments] == split_sentences(reply.reply)
        assert script.citations


@pytest.mark.parametrize("abstain", [False, True])
def test_empty_speech_has_no_segments(reply: ChatReply, abstain: bool) -> None:
    reply.abstain = abstain
    reply.reply = "  "
    assert script_from_presentable(presentable_from_chat_reply(reply), "合成人物").segments == []


def test_general_content_is_shown_and_spoken_unchanged(reply: ChatReply, tmp_path: Path) -> None:
    general = ChatReply.model_validate({**reply.model_dump(), "mode": "general", "reply": "这是通用知识。先验证。"})
    presentable = presentable_from_chat_reply(general)
    assert presentable.mode == "general"
    script = script_from_presentable(presentable, "合成人物")
    assert not script.abstain
    assert [s.index for s in script.segments] == list(range(len(script.segments)))
    assert [s.kind for s in script.segments] == ["speech", "speech"]
    assert [s.text for s in script.segments] == split_sentences(general.reply)
    assert "这是通用知识。" in export_html(script, clock=lambda: dt.datetime(2026, 1, 2, tzinfo=dt.UTC))
    audio = render_audio(script, SilentSynthesizer(), tmp_path)
    assert "".join(p.text for s in audio.segments for p in s.parts) == general.reply


def test_markdown_script_strips_before_splitting_and_keeps_citations(reply: ChatReply) -> None:
    reply.reply = (
        "**先核对**。\n\n1. 再决定。\n\n```sh\necho secret.\n```\n\n| 方案 | 成本 |\n| --- | --- |\n| 甲 | 低 |"
    )
    presentable = presentable_from_chat_reply(reply)
    script = script_from_presentable(presentable, "合成人物")
    assert [segment.text for segment in script.segments] == [
        "先核对。",
        "再决定。",
        "（代码略）",
        "方案，成本",
        "甲，低",
    ]
    assert script.citations == presentable.citations
    assert script.source_fingerprint == fingerprint(reply.model_dump(mode="json"))
    assert presentable.text == reply.reply


@pytest.mark.parametrize(
    "text",
    [
        "首先我们需要确认当前目标，接下来逐步检查已有资料和关键假设，随后根据验证结果调整实施方案，最后记录风险并安排下一轮复核。",
        "First review the facts, then check the assumptions carefully. "
        "Keep each step small, and record the outcome for the next review.",
        "首先核对所有的关键资料，然后再检查 API 和所有参数，随后运行 pytest 验证最终输出，最后记录验证结果。",
        "**首先核对当前目标**，并确认相关资料是否完整。\n1. 再按优先级逐项验证，最后认真记录验证结果。",
    ],
)
def test_speech_chunks_have_a_short_lead_and_bounded_growth(text: str) -> None:
    from twin.media.speech_text import strip_markdown

    pieces = split_speech(text)
    assert 8 <= len(pieces[0]) <= 16
    assert all(8 <= len(piece) <= 28 for piece in pieces)
    assert all(len(right) <= round(len(left) * 1.3) for left, right in pairwise(pieces))
    assert "".join("".join(pieces).split()) == "".join(strip_markdown(text).split())
    assert all(piece[-1] in "，。,.!?" or piece[-1].isascii() for piece in pieces)


def test_speech_keeps_words_numbers_and_indivisible_clauses_intact() -> None:
    text = "Check API v1.2 and 1,200 records, then keep hyperparameterization intact."
    pieces = split_speech(text)
    assert all(token in " ".join(pieces) for token in ["API", "v1.2", "1,200", "hyperparameterization"])
    assert " ".join(pieces) == text
    assert split_speech("这是没有标点也没有空格的一整段中文内容不能为了长度把词切开") == [
        "这是没有标点也没有空格的一整段中文内容不能为了长度把词切开"
    ]
    assert split_speech("  \n ") == []
    assert split_speech("先验证。再推进。") == ["先验证。再推进。"]
    assert split_speech("首先核对所有的关键资料，完成。") == ["首先核对所有的关键资料，完成。"]


def test_audio_rechunking_does_not_change_video_or_presentation(reply: ChatReply) -> None:
    reply.reply = "首先核对所有的关键资料，然后再检查 API 和所有参数，随后运行 pytest 验证最终输出，最后记录验证结果。"
    original = script_from_presentable(presentable_from_chat_reply(reply), "合成人物")
    before = original.model_dump_json()
    spoken = speech_script(original)
    assert original.model_dump_json() == before
    assert len(original.segments) == 1
    assert [segment.text for segment in spoken.segments] == split_speech(reply.reply)
    assert [segment.index for segment in spoken.segments] == list(range(len(spoken.segments)))
    assert spoken.citations == original.citations
    assert spoken.source_fingerprint == original.source_fingerprint
    abstention = original.model_copy(update={"abstain": True})
    assert speech_script(abstention).abstain
    assert speech_script(abstention).segments == spoken.segments


def test_manifest_roundtrip() -> None:
    manifest = MediaManifest(source_fingerprint="abc", created_at=dt.datetime.now(dt.UTC))
    assert MediaManifest.model_validate_json(manifest.model_dump_json()) == manifest
    assert manifest.schema_version == 1
    with pytest.raises(ValidationError):
        manifest.ai_generated = False  # type: ignore[assignment]


def test_presentable_contract(reply: ChatReply) -> None:
    for p in [presentable_from_chat_reply(reply)]:
        assert PresentableAnswer.model_validate_json(p.model_dump_json()) == p
        assert p.schema_version == 1
        with pytest.raises(ValidationError):
            p.text = "改写"
        with pytest.raises(ValidationError):
            PresentableAnswer.model_validate({**p.model_dump(), "upstream_only": "字段"})
        with pytest.raises(ValidationError):
            PresentableAnswer.model_validate({**p.model_dump(), "schema_version": 2})
        script = script_from_presentable(p, "合成人物")
        assert script.source_fingerprint == p.source_fingerprint
        assert script.citations == p.citations
        assert script.citations is not p.citations
        assert (script.abstain, script.confidence, script.as_of) == (p.abstain, p.confidence, p.as_of)


def test_payload_adapters(reply: ChatReply) -> None:
    for kind, upstream, expected in [
        ("chat_reply", reply, presentable_from_chat_reply(reply)),
    ]:
        data = upstream.model_dump(mode="json")
        assert presentable_from_payload(kind, data) == expected
        assert presentable_from_payload(kind, {**data, "web_only": "ignored"}) == expected
        assert presentable_from_payload(kind, dict(reversed(list(data.items())))) == expected
        assert expected.source_fingerprint == fingerprint(data)
        with pytest.raises(ValidationError):
            presentable_from_payload(kind, {})
        with pytest.raises(ValidationError):
            presentable_from_payload(kind, {**data, "confidence": "invalid"})
        with pytest.raises(ValidationError):
            presentable_from_payload(kind, [])
    with pytest.raises(ValueError, match="来源应为"):
        presentable_from_payload("unknown", {})


def test_fingerprint_includes_upstream_fields_not_in_contract(reply: ChatReply) -> None:
    chat_before = presentable_from_chat_reply(reply)
    reply.topic_facets = ["synthetic"]
    chat_after = presentable_from_chat_reply(reply)
    assert chat_before.text == chat_after.text
    assert chat_before.source_fingerprint != chat_after.source_fingerprint
