from __future__ import annotations

import datetime as dt
import json
import sqlite3
import stat
from pathlib import Path

import pytest

from twin.config import Settings, load_settings
from twin.persona.dimensions import (
    DIMENSIONS,
    FACET_BY_ID,
    FACETS,
    TAXONOMY_VERSION,
    facet_guide,
    facets_of,
    requires_consent,
)
from twin.persona.items import PersonaCandidate, PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind, evidence_class
from twin.persona.sources import (
    expression_view,
    parse_chat,
    parse_document,
    parse_interview,
    parse_questionnaire,
    parse_source,
    pseudonym,
)
from twin.persona.store import PersonaStore

D = dt.date


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="张三", target_aliases=["老张"], pseudonymize_others=False)


def test_taxonomy_has_nine_dimensions_and_39_unique_facets() -> None:
    assert TAXONOMY_VERSION == "v1" and len(DIMENSIONS) == 9 and len(FACETS) == 39
    assert len(FACET_BY_ID) == 39
    assert all(facets_of(d.dimension_id) for d in DIMENSIONS)
    assert requires_consent("9.3") and not requires_consent("3.1")
    guide = facet_guide(frozenset({"3.1", "6.1"}))
    assert guide.splitlines() == [
        "D3 怎么做决定",
        "  3.1 风险偏好：面对不确定的选择时，愿意尝试到什么程度",
        "D6 说话方式",
        "  6.1 用词与口头禅：高频词、口头禅、行话",
    ]


QUESTIONNAIRE = """# 数字分身建档问卷 v0

## 第一部分

**1. 用三五句话介绍你现在的角色：负责什么。**　*开放 · 1.1 1.4*

回答：我负责运营中心。
向 CEO 汇报。

**13.合作方提出一个大单，你第一句会说什么？**　*情境 · 3.4 3.6*

回答：首付多少？

**33.【可跳过】工作之外你喜欢做什么？**　*开放 · 9.1*

回答：

**34.【可跳过】你的作息？**　*开放 · 9.2 9.4*

回答：六点起，跑步。
"""


def test_questionnaire_answers_become_self_report_expressions_with_facet_hints(settings: Settings) -> None:
    parsed = parse_questionnaire("问卷_2026-10-05.md", QUESTIONNAIRE, settings)
    src, rows = parsed.source, parsed.expressions
    assert src.kind is SourceKind.QUESTIONNAIRE and evidence_class(src.kind) is EvidenceClass.SELF_REPORT
    assert [r.text for r in rows] == ["我负责运营中心。\n向 CEO 汇报。", "首付多少？", "六点起，跑步。"]
    assert rows[0].context == "问卷第 1 题：用三五句话介绍你现在的角色：负责什么。"
    assert rows[0].facets_hint == ["1.1", "1.4"] and rows[0].date == D(2026, 10, 5) and rows[0].is_target
    assert src.declined_facets == ["9.1"]  # skipped optional question = no consent for its facets
    assert src.n_expressions == 3 and src.n_target == 3


def test_questionnaire_without_questions_is_refused(settings: Settings) -> None:
    with pytest.raises(ValueError, match="no questionnaire question"):
        parse_questionnaire("x.md", "随便写点什么", settings)


CHAT = """2026-09-01 10:02 李四：周报我晚点发
2026-09-01 10:03 王五：客户那边催了
2026-09-01 10:05 张三：先把客户的事办了
周报明天上午给我就行
[2026/9/2 09:00:00] 老张: 早
"""


def test_chat_lines_with_continuations_and_context(settings: Settings) -> None:
    parsed = parse_chat("项目群.txt", CHAT, settings)
    rows = parsed.expressions
    assert [(r.speaker, r.is_target) for r in rows] == [
        ("李四", False),
        ("王五", False),
        ("张三", True),
        ("老张", True),
    ]
    assert rows[2].text == "先把客户的事办了\n周报明天上午给我就行"
    assert rows[2].context == "李四：周报我晚点发 王五：客户那边催了"
    assert rows[3].context == "" and rows[3].date == D(2026, 9, 2)
    assert rows[2].channel == "项目群" and evidence_class(parsed.source.kind) is EvidenceClass.BEHAVIOR
    assert parsed.source.first_date == D(2026, 9, 1) and parsed.source.last_date == D(2026, 9, 2)


def test_wechat_style_header_blocks(settings: Settings) -> None:
    text = "李四 2026-09-03 08:00:01\n今天开会吗\n\n张三 2026-09-03 08:01:10\n开，九点半\n带上数据\n"
    rows = parse_chat("wx.txt", text, settings).expressions
    assert [(r.speaker, r.text) for r in rows] == [("李四", "今天开会吗"), ("张三", "开，九点半\n带上数据")]
    assert rows[1].context == "李四：今天开会吗"


def test_chat_csv_and_json(settings: Settings) -> None:
    csv_text = "时间,发送者,内容\n2026-09-04 10:00,李四,方案好了\n2026-09-04 10:01,张三,发我看看\n"
    rows = parse_chat("a.csv", csv_text, settings).expressions
    assert [(r.speaker, r.date) for r in rows] == [("李四", D(2026, 9, 4)), ("张三", D(2026, 9, 4))]
    payload = json.dumps(
        {"messages": [{"time": "2026-09-05", "sender": "张三", "content": "好"}, {"sender": "", "content": "x"}]}
    )
    parsed = parse_chat("b.json", payload, settings)
    assert [r.text for r in parsed.expressions] == ["好"] and len(parsed.skipped_lines) == 1


def test_chat_without_the_target_is_refused_with_the_speakers_seen(settings: Settings) -> None:
    with pytest.raises(ValueError, match="speakers seen: 李四"):
        parse_chat("c.txt", "2026-09-01 10:00 李四：在吗\n", settings)


def test_interview_and_document(settings: Settings) -> None:
    rows = parse_interview("访谈_2026-10-10.txt", "主持人：怎么看授权？\n张三：能放就放\n", settings).expressions
    assert rows[1].is_target and rows[1].context == "主持人：怎么看授权？" and rows[1].date == D(2026, 10, 10)
    doc = parse_document("2026-08-01_年度计划.md", "# 目标\n\n收入翻倍。\n\n## 风险\n\n回款。\n", settings)
    assert [(e.channel, e.text) for e in doc.expressions] == [("目标", "收入翻倍。"), ("风险", "回款。")]
    assert all(e.is_target and e.date == D(2026, 8, 1) for e in doc.expressions)


def test_store_round_trip_replace_filters_and_delete(settings: Settings, tmp_path: Path) -> None:
    path = tmp_path / "twin.db"
    store = PersonaStore(path)
    q = parse_questionnaire("q_2026-10-05.md", QUESTIONNAIRE, settings)
    chat = parse_chat("群.txt", CHAT, settings)
    assert store.put_source(q) is True and store.put_source(chat) is True
    assert store.put_source(q) is False  # the same file again replaces, not duplicates
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert [s.kind for s in store.list_sources()] == [SourceKind.CHAT, SourceKind.QUESTIONNAIRE]
    assert len(store.list_expressions()) == len(q.expressions) + len(chat.expressions)
    assert {e.speaker for e in store.list_expressions(target_only=True)} == {"张三", "老张"}
    assert [e.date for e in store.list_expressions(source_id=chat.source.source_id, until=D(2026, 9, 1))] == [
        D(2026, 9, 1)
    ] * 3
    assert store.get_expression(chat.expressions[2].expression_id) == chat.expressions[2]
    assert store.delete_source(chat.source.source_id) and store.get_source(chat.source.source_id) is None
    assert store.list_expressions(source_id=chat.source.source_id) == []
    store.close()


def test_parse_source_reads_the_file(settings: Settings, tmp_path: Path) -> None:
    f = tmp_path / "2026-08-01_笔记.txt"
    f.write_text("﻿第一段\n\n第二段\n", encoding="utf-8")
    assert [e.text for e in parse_source(SourceKind.DOCUMENT, f, settings).expressions] == ["第一段", "第二段"]


def test_other_speakers_are_pseudonymized_consistently_and_the_person_kept() -> None:
    settings = Settings(target_name="张三", target_aliases=["老张"])
    chat = parse_chat(
        "群.txt", "2026-09-01 10:00 李四：张三，王五说周报晚点\n2026-09-01 10:01 张三：李四你跟王五说明天给\n", settings
    )
    code = pseudonym("李四")
    assert code == pseudonym(" 李四 ") and code.startswith("他人") and code != pseudonym("王五")
    assert [r.speaker for r in chat.expressions] == ["李四", "张三"]
    assert chat.expressions[1].text == "李四你跟王五说明天给"
    assert chat.expressions[1].context == "李四：张三，王五说周报晚点"
    store = PersonaStore(":memory:")
    store.put_source(chat)
    rows = expression_view(store, settings, source_id=chat.source.source_id)
    assert [r.speaker for r in rows] == [code, "张三"]
    assert rows[0].text == "张三，王五说周报晚点"  # 王五 never spoke here, so only speakers are known names
    assert rows[1].text == f"{code}你跟王五说明天给" and rows[1].context == f"{code}：张三，王五说周报晚点"
    interview = parse_interview("访谈_2026-10-10.txt", "李四：怎么看授权？\n老张：能放就放\n", settings)
    assert interview.expressions[0].speaker == "李四" and interview.expressions[1].speaker == "老张"
    store.put_source(interview)
    viewed = expression_view(store, settings, source_id=interview.source.source_id)
    assert viewed[0].speaker == code and viewed[1].speaker == "老张"
    store.close()


@pytest.mark.parametrize("kind", ["meeting", "biography"])
def test_legacy_kinds_load_as_documents_without_losing_text(kind: str, tmp_path: Path, settings: Settings) -> None:
    path = tmp_path / "legacy.db"
    parsed = parse_document("legacy.txt", "旧资料里的文字。", settings)
    evidence = PEvidence(
        expression_id=parsed.expressions[0].expression_id,
        source_id=parsed.source.source_id,
        source_kind=SourceKind.DOCUMENT,
        evidence_class=EvidenceClass.BEHAVIOR,
        quote="旧资料里的文字。",
    )
    with PersonaStore(path) as store:
        store.put_source(parsed)
        store.put_chunk(
            "old-chunk",
            parsed.source.source_id,
            [
                PersonaCandidate(
                    candidate_id="old-candidate",
                    chunk_id="old-chunk",
                    facet_id="1.1",
                    statement="旧结论",
                    evidence=[evidence],
                )
            ],
        )
        store.replace_facet_items(
            "1.1",
            [
                PersonaItem(
                    item_id="old-item",
                    facet_id="1.1",
                    statement="旧结论",
                    evidence=[evidence],
                )
            ],
        )
    with sqlite3.connect(path) as db:
        source = parsed.source.model_dump(mode="json") | {"kind": kind, "meeting_id": "old-id"}
        db.execute("UPDATE p_sources SET kind = ?, json = ?", (kind, json.dumps(source)))
        for table in ("p_candidates", "p_items"):
            raw = json.loads(db.execute(f"SELECT json FROM {table}").fetchone()[0])
            raw["evidence"][0]["source_kind"] = kind
            db.execute(f"UPDATE {table} SET json = ?", (json.dumps(raw),))
    with PersonaStore(path) as store:
        source = store.get_source(parsed.source.source_id)
        assert source is not None and source.kind is SourceKind.DOCUMENT
        assert store.list_sources(SourceKind.DOCUMENT) == [source]
        assert store.list_expressions()[0].text == "旧资料里的文字。"
        assert expression_view(store, settings)[0].text == "旧资料里的文字。"
        assert store.list_candidates()[0].evidence[0].source_kind is SourceKind.DOCUMENT
        assert store.list_items()[0].evidence[0].source_kind is SourceKind.DOCUMENT


def test_old_config_ignores_unused_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "twin.toml"
    path.write_text(
        'target_name = "小林"\nsegment_window_chars = 4000\npersona_principles = 8\n'
        "[twin]\nk_principles = 8\nk_question_patterns = 8\nk_tradeoffs = 8\n"
        "k_stances = 8\nk_cases = 8\nk_directives = 8\nsegment_window_chars = 4000\n"
    )
    settings = load_settings(path)
    assert settings.target_name == "小林"
    assert "segment_window_chars" not in settings.model_dump() and "twin" not in settings.model_dump()
    assert not caplog.records
