"""Presentation preserves source text, provenance and abstention."""

from __future__ import annotations

import datetime as dt

import pytest
from pydantic import ValidationError

from twin.media.adapters import (
    presentable_from_chat_reply,
    presentable_from_payload,
)
from twin.media.schema import (
    EXPLICIT_LABEL,
    OPENING_NOTICE,
    MediaManifest,
    MediaScript,
    PresentableAnswer,
    Segment,
)
from twin.media.script import script_from_presentable, split_sentences
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
    assert script.segments[0].text == OPENING_NOTICE
    assert [c.ref_id for c in script.citations] == reply.citations
    assert all(c.reason == "" for c in script.citations)
    assert (script.as_of, script.confidence) == (reply.as_of, reply.confidence)


@pytest.mark.parametrize("reason", ["  证据不足  ", "", "  \n "])
def test_abstain_no_speech(reply: ChatReply, reason: str) -> None:
    reply.abstain = True
    reply.abstain_reason = reason
    for p in [presentable_from_chat_reply(reply)]:
        script = script_from_presentable(p, "合成人物")
        assert len(script.segments) == 2
        assert script.segments[0].text == OPENING_NOTICE
        assert all(s.kind == "notice" for s in script.segments)
        assert script.segments[1].text == (reason.strip() or "资料不足以判断，请向本人确认。")
        assert script.citations


def test_empty_speech_still_has_notice(reply: ChatReply) -> None:
    reply.reply = "  "
    assert script_from_presentable(presentable_from_chat_reply(reply), "合成人物").segments == [
        Segment(index=0, kind="notice", text=OPENING_NOTICE)
    ]


def test_manifest_roundtrip() -> None:
    manifest = MediaManifest(source_fingerprint="abc", created_at=dt.datetime.now(dt.UTC))
    assert MediaManifest.model_validate_json(manifest.model_dump_json()) == manifest
    assert manifest.label == EXPLICIT_LABEL
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
