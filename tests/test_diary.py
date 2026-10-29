"""A diary: entries written day by day, each dated by its heading. Dreams in it are kept for the mirror only: never
read into memories, indexed or answered from, but there in the source's own text."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.persona.chat import EXPRESSIONS_NS, index_persona
from twin.persona.profile import chunks_for
from twin.persona.schema import EvidenceClass, SourceKind, evidence_class
from twin.persona.sources import detect_kind, expression_view, is_diary, parse_diary, parse_upload
from twin.persona.store import NewerStoreError, PersonaStore
from twin.web.app import create_app
from twin.web.persona import DREAM_MARK

D = dt.date

DIARY = """我的日记

# 2024-03-01 周五 晴
早上去跑步。

### 晚上
和妈妈打电话，说到外婆。

2024年3月2日 梦
我在一座没有门的房子里找人。

2024/3/3 今天开会，被老板批评了，心里很不服气。
梦：又梦见考试迟到。
"""


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="张三", pseudonymize_others=False)


def test_each_paragraph_is_dated_by_the_day_above_it(settings: Settings) -> None:
    parsed = parse_diary("日记.md", DIARY, settings, D(2026, 10, 29))
    rows = [(e.date, e.channel, e.mirror, e.text) for e in parsed.expressions]
    assert rows == [
        (D(2024, 3, 1), "2024-03-01 周五 晴", "", "早上去跑步。"),
        (D(2024, 3, 1), "2024-03-01 周五 晴 · 晚上", "", "和妈妈打电话，说到外婆。"),
        (D(2024, 3, 2), "2024年3月2日 梦", "dream", "我在一座没有门的房子里找人。"),
        # Words after the date that read as a sentence are the day's first words.
        (D(2024, 3, 3), "2024/3/3", "", "今天开会，被老板批评了，心里很不服气。"),
        (D(2024, 3, 3), "2024/3/3", "dream", "又梦见考试迟到。"),
    ]
    assert all(e.is_target and e.speaker == "张三" for e in parsed.expressions)
    # The title line alone before the first day is not an entry, so it dates nothing either.
    source = parsed.source
    assert (source.kind, source.title, source.first_date, source.last_date) == (
        SourceKind.DIARY,
        "日记",
        D(2024, 3, 1),
        D(2024, 3, 3),
    )
    assert evidence_class(SourceKind.DIARY) is EvidenceClass.BEHAVIOR


def test_words_before_the_first_day_take_the_given_date(settings: Settings) -> None:
    parsed = parse_diary(
        "d.txt", "这本日记从搬家那年开始写，断断续续。\n\n2024-03-01\n搬家。\n", settings, D(2020, 1, 1)
    )
    assert [(e.date, e.text) for e in parsed.expressions] == [
        (D(2020, 1, 1), "这本日记从搬家那年开始写，断断续续。"),
        (D(2024, 3, 1), "搬家。"),
    ]


def test_a_dream_needs_the_word_on_its_own(settings: Settings) -> None:
    parsed = parse_diary("d.md", "## 2024-03-01 梦想\n想开一家书店。\n\n## 2024-03-02 （梦）\n飞起来了。\n", settings)
    assert [e.mirror for e in parsed.expressions] == ["", "dream"]


def test_text_written_day_by_day_is_read_as_a_diary(settings: Settings) -> None:
    assert detect_kind("notes.md", DIARY, settings) is SourceKind.DIARY
    # One dated heading is a document with a date, not a diary.
    assert not is_diary("# 2024-03-01 周会\n讨论预算。\n")
    assert detect_kind("周会.md", "# 2024-03-01 周会\n讨论预算。\n", settings) is SourceKind.DOCUMENT
    # A chat log stays a chat even though its lines are dated.
    chat = "2026-09-03 08:00:01 李四：今天开会吗\n2026-09-04 08:01:10 张三：开\n"
    assert detect_kind("wx.txt", chat, settings) is SourceKind.CHAT
    parsed = parse_upload("日记.md", DIARY.encode(), settings)
    assert parsed.source.kind is SourceKind.DIARY and parsed.expressions[0].date == D(2024, 3, 1)


def test_dreams_are_not_extracted_indexed_or_answered_from(settings: Settings, tmp_path: Path) -> None:
    with PersonaStore(tmp_path / "twin.db") as store:
        parsed = parse_diary("日记.md", DIARY, settings)
        store.put_source(parsed)
        dreams = {e.expression_id for e in parsed.expressions if e.mirror}
        assert len(dreams) == 2
        # What memories are extracted from and what chat answers from: the person's words without the dreams.
        said = {e.expression_id for e in expression_view(store, settings, target_only=True)}
        assert said == {e.expression_id for e in parsed.expressions} - dreams
        text = "\n".join(
            e.text for chunk in chunks_for(store, parsed.source, frozenset(), settings) for e in chunk.entries
        )
        assert "早上去跑步" in text and "没有门的房子" not in text and "考试迟到" not in text
        index_persona(store, HashingEmbedder(), settings)
        assert not dreams & set(store.vector_shas(EXPRESSIONS_NS))
        # The diary as written keeps them.
        whole = expression_view(store, settings, source_id=parsed.source.source_id, mirror=True)
        assert dreams <= {e.expression_id for e in whole}


def test_an_older_release_refuses_a_database_with_diaries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "twin.db"
    with PersonaStore(path):
        pass
    with sqlite3.connect(path) as db:
        version = db.execute("PRAGMA user_version").fetchone()[0]
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name = 'p_sources_kind'").fetchone()
    from twin.persona import store as store_module

    monkeypatch.setattr(store_module, "_MIGRATIONS", store_module._MIGRATIONS[: version - 1])
    with pytest.raises(NewerStoreError):
        PersonaStore(path)


def test_the_diary_as_written_marks_its_dreams(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="张三", max_workers=1)
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post(
            "/api/persona/import", files={"files": ("日记.md", DIARY.encode())}, headers={"X-Twin": "1"}
        )
        source_id = response.json()["imported"][0]["source_id"]
        text = client.get(f"/api/persona/sources/{source_id}/text").text
    assert text.split("\n\n") == [
        "早上去跑步。",
        "和妈妈打电话，说到外婆。",
        f"{DREAM_MARK}我在一座没有门的房子里找人。",
        "今天开会，被老板批评了，心里很不服气。",
        f"{DREAM_MARK}又梦见考试迟到。",
    ]
