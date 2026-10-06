from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder, Matrix, embedder_fingerprint
from twin.llm import FakeLLM
from twin.persona import chat as pc
from twin.persona import profile as pf
from twin.persona.schema import ChatTurn, ParsedSource, SourceKind
from twin.persona.sources import expression_view, parse_text, pseudonym
from twin.persona.store import PersonaStore

DAY = dt.date(2026, 9, 1)
WORDS = "李四，我张三和老张先看数据再决定"
QUESTION = "李四来问张三，怎么决定？"
HISTORY = [ChatTurn(role="user", content="怎么决定")]


class RecordingEmbedder(HashingEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> Matrix:
        self.calls.append(list(texts))
        return super().embed(texts)


def source_for(kind: SourceKind, settings: Settings) -> ParsedSource:
    raw = {
        SourceKind.CHAT: f"2026-09-01 10:00 李四：张三，我李四先看数据\n2026-09-01 10:01 老张：{WORDS}\n",
        SourceKind.INTERVIEW: f"李四：张三，我李四先看数据\n老张：{WORDS}\n",
        SourceKind.DOCUMENT: f"# 李四的计划\n\n{WORDS}\n",
        SourceKind.QUESTIONNAIRE: f"**1. {QUESTION}**　*开放 · 3.3*\n\n回答：{WORDS}\n",
    }[kind]
    return parse_text(kind, f"{kind}.md", raw, settings, DAY)


def add_known_speaker(store: PersonaStore, settings: Settings) -> None:
    parsed = parse_text(SourceKind.DOCUMENT, "names.txt", "收到", settings, DAY)
    parsed.expressions[0].speaker = "李四"
    parsed.expressions[0].is_target = False
    parsed.source.n_target = 0
    store.put_source(parsed)


@pytest.mark.parametrize("kind", list(SourceKind))
@pytest.mark.parametrize("enabled", [True, False])
def test_all_kinds_store_raw_and_use_the_same_profile_and_chat_view(
    kind: SourceKind, enabled: bool, tmp_path: Path
) -> None:
    settings = Settings(target_name="张三", target_aliases=["老张"], pseudonymize_others=enabled, max_workers=1)
    parsed = source_for(kind, settings)
    path = tmp_path / "persona.db"
    with PersonaStore(path) as store:
        add_known_speaker(store, settings)
        store.put_source(parsed)
    with PersonaStore(path) as store:
        saved = store.get_source(parsed.source.source_id)
        assert saved == parsed.source and saved.text_state == "raw"
        assert store.list_expressions(parsed.source.source_id) == parsed.expressions
        assert all("李四" in e.text for e in parsed.expressions)
        assert parsed.expressions[-1].text == WORDS
        viewed = expression_view(store, settings, source_id=parsed.source.source_id)
        expected = WORDS.replace("李四", pseudonym("李四")) if enabled else WORDS
        assert viewed[-1].text == expected
        assert viewed[-1].speaker in {"张三", "老张"}
        assert "张三" in viewed[-1].text and "老张" in viewed[-1].text
        assert [e.expression_id for e in viewed] == [e.expression_id for e in parsed.expressions]
        if enabled:
            assert all("李四" not in e.text + e.speaker + e.context + e.channel for e in viewed)
            assert pseudonym("李四") in viewed[-1].context + viewed[-1].channel + viewed[-1].text
        else:
            assert viewed == parsed.expressions

        def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
            if schema is pf.ExtractDraft:
                assert expected in user
                assert ("李四" not in user) if enabled else ("李四" in user)
                return {
                    "items": [
                        {
                            "facet_id": "3.3",
                            "statement": "他先看数据再决定",
                            "quotes": [{"n": 1, "quote": expected, "own_words": True}],
                        }
                    ]
                }
            return {"reply": expected, "citations": [], "confidence": 0.2, "abstain": False}

        llm = FakeLLM(handler)
        report = pf.build_profile(store, llm, settings)
        assert report.failures == [] and report.items == 1
        # The full quote includes the replaced name: verification must use the extractor's view, not raw L1.
        assert store.list_items()[0].evidence[0].quote == expected
        embedder = HashingEmbedder()
        pc.index_persona(store, embedder, settings)
        chat = pc.PersonaChat(store, llm, embedder, settings)
        ctx = chat.retrieve("怎么决定")
        assert [e.text for e, _ in ctx.expressions] == [expected]
        if kind is SourceKind.CHAT:
            assert ctx.voice == [expected]
        system = pc.chat_system_prompt(settings.target_name, ctx)
        user = pc.chat_user_message(HISTORY, ctx)
        assert expected in user and "张三" in user and "老张" in user
        if enabled:
            assert "李四" not in system + user
        else:
            assert "李四" in user
        assert chat.reply(HISTORY).reply == expected
        assert llm.calls[-1][1:] == (system, user)
        assert store.list_expressions(parsed.source.source_id) == parsed.expressions


@pytest.mark.parametrize("kind", list(SourceKind))
@pytest.mark.parametrize("enabled", [True, False])
def test_index_embeds_the_privacy_view_for_every_source_kind(kind: SourceKind, enabled: bool) -> None:
    settings = Settings(target_name="张三", target_aliases=["老张"], pseudonymize_others=enabled)
    with PersonaStore(":memory:") as store:
        add_known_speaker(store, settings)
        parsed = source_for(kind, settings)
        store.put_source(parsed)
        embedder = RecordingEmbedder()
        assert pc.index_persona(store, embedder, settings) == {"items": 0, "expressions": 1}
        viewed = expression_view(store, settings, target_only=True)
        assert embedder.calls == [[pc.expression_text(viewed[0])]]
        text = embedder.calls[0][0]
        assert "张三" in text and "老张" in text
        if enabled:
            assert "李四" not in text and pseudonym("李四") in text
        else:
            assert "李四" in text
        assert store.list_expressions(parsed.source.source_id) == parsed.expressions


def test_index_privacy_change_reembeds_only_affected_raw_rows_and_cleans_context() -> None:
    settings = Settings(target_name="张三", pseudonymize_others=False)
    raw = (
        "2026-09-01 10:00 李四：王五，先看数据\n"
        "2026-09-01 10:01 王五：李四，好的\n"
        "2026-09-01 10:02 张三：我是张三，先看数据\n"
        "2026-09-01 10:03 张三：我是张三，再决定\n"
    )
    with PersonaStore(":memory:") as store:
        parsed = parse_text(SourceKind.CHAT, "context.txt", raw, settings)
        store.put_source(parsed)
        embedder = RecordingEmbedder()
        assert pc.index_persona(store, embedder, settings) == {"items": 0, "expressions": 2}
        before = store.vector_shas(pc.EXPRESSIONS_NS)
        assert "李四" in embedder.calls[0][0] and "王五" in embedder.calls[0][0]
        embedder.calls.clear()
        settings.pseudonymize_others = True
        assert pc.index_persona(store, embedder, settings) == {"items": 0, "expressions": 1}
        # Neither target message mentions others: the private data here is exclusively in Expression.context.
        assert embedder.calls == [
            [
                f"{pseudonym('李四')}：{pseudonym('王五')}，先看数据 "
                f"{pseudonym('王五')}：{pseudonym('李四')}，好的 我是张三，先看数据"
            ]
        ]
        assert all("李四" not in text and "王五" not in text for batch in embedder.calls for text in batch)
        after = store.vector_shas(pc.EXPRESSIONS_NS)
        assert before[parsed.expressions[2].expression_id] != after[parsed.expressions[2].expression_id]
        assert before[parsed.expressions[3].expression_id] == after[parsed.expressions[3].expression_id]
        embedder.calls.clear()
        assert pc.index_persona(store, embedder, settings) == {"items": 0, "expressions": 0}
        assert embedder.calls == [] and store.list_expressions() == parsed.expressions


def test_target_names_and_existing_codes_are_protected_even_inside_names() -> None:
    settings = Settings(target_name="张三丰", target_aliases=["李四海"])
    raw = (
        "2026-09-01 10:00 张三：张三丰，李四海和张三\n"
        "2026-09-01 10:01 李四：李四海\n"
        "2026-09-01 10:02 他人：他人1234\n"
        "2026-09-01 10:03 他人ABCD：收到\n"
        "2026-09-01 10:04 张三丰：张三丰，李四海，张三，李四，他人ABCD\n"
    )
    with PersonaStore(":memory:") as store:
        parsed = parse_text(SourceKind.CHAT, "names.txt", raw, settings)
        store.put_source(parsed)
        viewed = expression_view(store, settings)
        assert viewed[-1].text == f"张三丰，李四海，{pseudonym('张三')}，{pseudonym('李四')}，他人ABCD"
        assert viewed[2].text == "他人1234" and viewed[3].speaker == "他人ABCD"
        assert store.list_expressions() == parsed.expressions


def test_changing_privacy_setting_rebuilds_raw_sources_and_preserves_l1() -> None:
    settings = Settings(target_name="张三", target_aliases=["老张"], max_workers=1)
    with PersonaStore(":memory:") as store:
        parsed = source_for(SourceKind.CHAT, settings)
        store.put_source(parsed)
        llm = FakeLLM(lambda *a: {"items": []})
        assert pf.build_profile(store, llm, settings).chunks_extracted == 1
        assert pf.build_profile(store, llm, settings).chunks_extracted == 0
        settings.pseudonymize_others = False
        report = pf.build_profile(store, llm, settings)
        assert report.chunks_dropped == 1 and report.chunks_extracted == 1
        assert WORDS in llm.calls[-1][2]
        settings.pseudonymize_others = True
        assert pf.build_profile(store, llm, settings).chunks_extracted == 1
        assert pseudonym("李四") in llm.calls[-1][2] and "李四" not in llm.calls[-1][2]
        assert store.list_expressions() == parsed.expressions


def test_chat_evidence_and_voice_use_the_view_even_for_raw_profile_quotes() -> None:
    raw_settings = Settings(target_name="张三", target_aliases=["老张"], pseudonymize_others=False, max_workers=1)
    with PersonaStore(":memory:") as store:
        add_known_speaker(store, raw_settings)
        store.put_source(source_for(SourceKind.CHAT, raw_settings))
        llm = FakeLLM(
            lambda *a: {
                "items": [
                    {
                        "facet_id": "3.3",
                        "statement": "他先看数据再决定",
                        "quotes": [{"n": 1, "quote": WORDS, "own_words": True}],
                    }
                ]
            }
        )
        pf.build_profile(store, llm, raw_settings)
        embedder = HashingEmbedder()
        pc.index_persona(store, embedder, raw_settings)
        private = raw_settings.model_copy(update={"pseudonymize_others": True})
        ctx = pc.PersonaChat(store, llm, embedder, private).retrieve("怎么决定")
        expected = WORDS.replace("李四", pseudonym("李四"))
        assert ctx.voice == [expected]
        assert ctx.items[0][0].evidence[0].quote == expected
        assert "李四" not in pc.chat_system_prompt(private.target_name, ctx) + pc.chat_user_message(HISTORY, ctx)
        assert store.list_items()[0].evidence[0].quote == WORDS
        draft = f"「{expected}」；『{WORDS}』"
        chat_llm = FakeLLM(lambda *a: {"reply": draft, "citations": [], "confidence": 0.5})
        reply = pc.PersonaChat(store, chat_llm, embedder, private).reply(HISTORY)
        assert reply.reply == f"「{expected}」；{WORDS}"
        assert reply.quotes_removed == 1
        assert "李四" not in chat_llm.calls[0][1] + chat_llm.calls[0][2]


# Rows and output hashes captured by running the unmodified code at commit
# 3721bc204165a85635b7f4184e88878d9cf4e92e, before adding text_state. The old database's
# empty-facet merge marks and built_at timestamp are omitted; only JSON whitespace is added for readability.
_LEGACY_SQL = """
CREATE TABLE p_sources (
    source_id TEXT PRIMARY KEY, kind TEXT NOT NULL, first_date TEXT, json TEXT NOT NULL);
CREATE TABLE p_expressions (
    expression_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, idx INTEGER NOT NULL, date TEXT,
    is_target INTEGER NOT NULL, held_out INTEGER NOT NULL, json TEXT NOT NULL);
CREATE TABLE p_chunks (chunk_id TEXT PRIMARY KEY, source_id TEXT NOT NULL);
CREATE TABLE p_candidates (
    candidate_id TEXT PRIMARY KEY, chunk_id TEXT NOT NULL, facet_id TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE p_items (item_id TEXT PRIMARY KEY, facet_id TEXT NOT NULL, json TEXT NOT NULL);
CREATE TABLE p_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO p_sources VALUES('src_039ddb0db28e','chat','2026-09-01','{
    "source_id":"src_039ddb0db28e","kind":"chat","title":"legacy","origin":"legacy.txt",
    "first_date":"2026-09-01","last_date":"2026-09-01","imported_at":"2026-10-04T21:58:57",
    "n_expressions":2,"n_target":1,"declined_facets":[],"meeting_id":null}');
INSERT INTO p_expressions VALUES('src_039ddb0db28e#00000','src_039ddb0db28e',0,'2026-09-01',0,0,'{
    "expression_id":"src_039ddb0db28e#00000","source_id":"src_039ddb0db28e","idx":0,"date":"2026-09-01",
    "speaker":"他人808B","is_target":false,"text":"张三，先看数据","context":"","channel":"legacy",
    "facets_hint":[],"held_out":false,"narrated":false,"utterance_idx":null,"start":null,"end":null}');
INSERT INTO p_expressions VALUES('src_039ddb0db28e#00001','src_039ddb0db28e',1,'2026-09-01',1,0,'{
    "expression_id":"src_039ddb0db28e#00001","source_id":"src_039ddb0db28e","idx":1,"date":"2026-09-01",
    "speaker":"老张","is_target":true,"text":"他人808B，我张三先看数据再决定",
    "context":"他人808B：张三，先看数据","channel":"legacy","facets_hint":[],"held_out":false,
    "narrated":false,"utterance_idx":null,"start":null,"end":null}');
INSERT INTO p_chunks VALUES('ch_a640073438162ea1','src_039ddb0db28e');
INSERT INTO p_candidates VALUES('pc_daf6a29d3bd78188','ch_a640073438162ea1','3.3','{
    "candidate_id":"pc_daf6a29d3bd78188","chunk_id":"ch_a640073438162ea1","facet_id":"3.3",
    "statement":"他先看数据再决定","applies_when":"","evidence":[{
        "expression_id":"src_039ddb0db28e#00001","source_id":"src_039ddb0db28e","source_kind":"chat",
        "evidence_class":"behavior","date":"2026-09-01","quote":"他人808B，我张三先看数据再决定",
        "own_words":true}]}');
INSERT INTO p_items VALUES('pi_a1c3619cc684','3.3','{
    "item_id":"pi_a1c3619cc684","facet_id":"3.3","statement":"他先看数据再决定","applies_when":"",
    "evidence":[{"expression_id":"src_039ddb0db28e#00001","source_id":"src_039ddb0db28e","source_kind":"chat",
        "evidence_class":"behavior","date":"2026-09-01","quote":"他人808B，我张三先看数据再决定","own_words":true}],
    "member_candidate_ids":["pc_daf6a29d3bd78188"],"conflict":"","review":"unreviewed",
    "review_note":"","extracted_statement":""}');
INSERT INTO p_meta VALUES('merge:3.3','aac101ba33f39269fdd8d1daade2ae86b3c54657ea31d6532e7aa0a0b1e82f31');
"""


@pytest.fixture
def legacy_database(tmp_path: Path) -> Path:
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as db:
        db.executescript(_LEGACY_SQL)
    return path


@pytest.mark.parametrize("enabled", [True, False])
def test_legacy_index_keeps_existing_vector_shas_without_reembedding(legacy_database: Path, enabled: bool) -> None:
    # Frozen pre-change rendered inputs and their old SHA keys, not generated through the new indexing path.
    old_docs = {
        pc.ITEMS_NS: ("pi_a1c3619cc684", "7ae152cf7cd4114c", "依据偏好：他先看数据再决定"),
        pc.EXPRESSIONS_NS: (
            "src_039ddb0db28e#00001",
            "883bc866f3904436",
            "他人808B：张三，先看数据 他人808B，我张三先看数据再决定",
        ),
    }
    embedder = RecordingEmbedder()
    with PersonaStore(legacy_database) as store:
        for namespace, (ref, sha, text) in old_docs.items():
            vector = HashingEmbedder().embed([text])[0]
            store.update_vectors(namespace, embedder_fingerprint(embedder), [(ref, sha, vector)])
    settings = Settings(target_name="张三", target_aliases=["老张"], pseudonymize_others=enabled)
    with PersonaStore(legacy_database) as store:
        add_known_speaker(store, settings)
        shas = {namespace: store.vector_shas(namespace) for namespace in old_docs}
        vectors = {namespace: store.get_vectors(namespace)[1].tobytes() for namespace in old_docs}
        source = store.get_source("src_039ddb0db28e")
        assert source is not None and source.text_state == "pseudonymized"
        assert pc.index_persona(store, embedder, settings) == {"items": 0, "expressions": 0}
        assert embedder.calls == []
        for namespace, (ref, sha, _) in old_docs.items():
            assert store.vector_shas(namespace) == shas[namespace] == {ref: sha}
            assert store.get_vectors(namespace)[1].tobytes() == vectors[namespace]


@pytest.mark.parametrize("enabled", [True, False])
def test_old_code_database_loads_and_keeps_profile_and_chat_output_unchanged(
    legacy_database: Path, enabled: bool
) -> None:
    settings = Settings(target_name="张三", target_aliases=["老张"], pseudonymize_others=enabled, max_workers=1)
    with PersonaStore(legacy_database) as store:
        source = store.list_sources()[0]
        assert source.text_state == "pseudonymized"
        with sqlite3.connect(legacy_database) as db:
            assert "text_state" not in json.loads(db.execute("SELECT json FROM p_sources").fetchone()[0])
        raw = store.list_expressions()
        assert raw[0].speaker == "他人808B" and raw[1].text == "他人808B，我张三先看数据再决定"
        # A raw speaker name that overlaps legacy prose must not affect the legacy source's view.
        parsed = parse_text(SourceKind.DOCUMENT, "mixed.txt", "收到", settings, DAY)
        parsed.expressions[0].speaker = "先看数据"
        parsed.expressions[0].is_target = False
        parsed.source.n_target = 0
        store.put_source(parsed)
        assert expression_view(store, settings, source_id=source.source_id) == raw
        chunks = pf.chunks_for(store, source, pf.consented_facets(store), settings)
        assert len(chunks) == 1 and chunks[0].chunk_id != "ch_a640073438162ea1"
        assert chunks[0].text == (
            "[1] 2026-09-01 · legacy\n语境：他人808B：张三，先看数据\n本人：他人808B，我张三先看数据再决定"
        )
        llm = FakeLLM(lambda *a: {"reply": "先看数据再决定", "citations": [], "confidence": 0.2, "abstain": False})
        profile = json.dumps(
            [i.model_dump(mode="json") for i in store.list_items()], ensure_ascii=False, sort_keys=True
        )
        assert (
            hashlib.sha256(profile.encode()).hexdigest()
            == "0972ebdccc478e0f766ae9bd80d9a2c410d31d04adb7499ab7dc87600f135aad"
        )
        embedder = HashingEmbedder()
        pc.index_persona(store, embedder, settings)
        chat = pc.PersonaChat(store, llm, embedder, settings)
        ctx = chat.retrieve("怎么决定")
        assert ctx.voice == [raw[1].text] and ctx.expressions[0][0] == raw[1]
        assert chat.reply(HISTORY).reply == "先看数据再决定"
        _, system, user = llm.calls[-1]
        assert "不替本人答应事情或做承诺" in system
        assert (
            hashlib.sha256(user.encode()).hexdigest()
            == "5d95a8fa94134a4da264fd4e58bd759f5a1fc45734c3f9e8ecdb6c1ac490048c"
        )
        assert store.list_expressions(source.source_id) == raw
