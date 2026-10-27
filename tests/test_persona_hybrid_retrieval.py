from __future__ import annotations

import datetime as dt
import math
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from time import process_time

import numpy as np
import pytest
from coverage import Coverage

from twin.config import Settings
from twin.embed import EmbedError, Matrix
from twin.llm import FakeLLM
from twin.persona import chat as pc
from twin.persona import lexical
from twin.persona.items import PersonaItem
from twin.persona.lexical import BM25, cached, tokenize
from twin.persona.schema import ChatTurn, Expression, ParsedSource, Source, SourceKind
from twin.persona.sources import parse_chat, parse_media, pseudonym
from twin.persona.store import PersonaStore
from twin.persona.tiers import COLLEAGUE, SELF, Audience


class ConstantEmbedder:
    name = "constant"
    cluster_threshold = 0.6

    def embed(self, texts: list[str]) -> Matrix:
        return np.tile(np.array([1.0, 0.0], dtype=np.float32), (len(texts), 1))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("项目QX-7预算4200万，使用Python3", ["项目", "qx", "7", "预算", "4200", "万", "使用", "python3"]),
        ("中文测试", ["中文", "文测", "测试"]),
        ("中、文！ Hello... WORLD_42\n", ["中", "文", "hello", "world", "42"]),
        ("ＡＢＣ１２３，４２００万；ＱＸ－７", ["abc123", "4200", "万", "qx", "7"]),
        ("かなカナ 한글 한국어", ["かな", "なカ", "カナ", "한글", "한국", "국어"]),
        ("𠀀𠀁 café Straße тест123", ["𠀀𠀁", "café", "strasse", "тест123"]),
        ("", []),
        ("，。！？ -- \t", []),
        # Regular English plurals fold onto the singular; short words and -ss/-us/-is endings stay.
        ("Trips stories boxes classes this bus is gas", ["trip", "story", "box", "class", "this", "bus", "is", "gas"]),
        ("dishes matches cafés", ["dish", "match", "cafés"]),
    ],
)
def test_tokenize(text: str, expected: list[str]) -> None:
    assert tokenize(text) == expected


def test_bm25_rare_term_outranks_common_term() -> None:
    docs = {"rare": "rare filler", **{f"common{i}": "common filler" for i in range(10)}}
    scores = BM25(docs).scores("RARE common")
    assert scores["rare"] > scores["common0"] > 0
    assert scores["common0"] == scores["common9"]
    assert BM25(docs).scores("") == {}
    assert BM25(docs).scores("missing") == {}
    assert BM25({}).scores("rare") == {}
    assert BM25({"empty": "！？"}).scores("rare") == {}


def test_bm25_lucene_score() -> None:
    scores = BM25({"a": "term term", "b": "other word"}).scores("term")
    assert scores == {"a": pytest.approx(math.log(2) * 2 * 2.2 / (2 + 1.2))}


def test_kept_bm25_is_reused_for_the_same_documents_and_updated_for_changed_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    family = ("test-kept", "items")
    docs = {f"d{i}": f"日常工作安排{i}" for i in range(20)} | {"a": "回款计划", "b": "数据核对"}
    index = cached(docs, family)
    # Another read of the same memory, as the next question's store connection makes, finds the index already built.
    assert cached(dict(docs), family) is index
    assert index.scores("回款") == BM25(docs).scores("回款")
    # A changed document updates the kept index, sharing its postings, and scores as an index built afresh would.
    changed_docs = {**docs, "b": "回款核对"}
    changed = cached(changed_docs, family)
    assert changed is not index and changed._base is index._base
    assert changed.scores("回款核对") == BM25(changed_docs).scores("回款核对")
    # Past the budget the least recently used family is dropped, never the one just built.
    monkeypatch.setattr(lexical, "KEPT_BYTES", 1)
    latest = cached({"c": "预算"}, ("test-kept", "others"))
    assert cached({"c": "预算"}, ("test-kept", "others")) is latest
    assert cached(changed_docs, family) is not changed


def test_an_updated_bm25_scores_exactly_as_one_built_afresh() -> None:
    rng = np.random.default_rng(7)
    words = ["回款", "预算", "数据", "核对", "客户", "项目", "plan", "trips", "风险", "交付"]

    def text() -> str:
        return " ".join(rng.choice(words, size=int(rng.integers(0, 12))).tolist())

    docs = {f"d{i}": text() for i in range(400)}
    index = BM25(docs)
    queries = ["回款 预算", "数据核对 plan", "trip 风险", "交付", "missing"]
    bases = {id(index._base)}
    for step in range(30):
        removed = rng.choice(sorted(docs), size=int(rng.integers(0, 4)), replace=False).tolist()
        added = {ref: text() for ref in rng.choice(sorted(docs), size=int(rng.integers(0, 3))).tolist()}
        added |= {f"n{step}-{k}": text() for k in range(int(rng.integers(0, 3)))}
        docs = {ref: t for ref, t in docs.items() if ref not in removed} | added
        index = index.changed(docs, [*removed, *(ref for ref in added if ref not in removed)], added)
        bases.add(id(index._base))
        fresh = BM25(docs)
        for query in queries:
            assert index.scores(query) == fresh.scores(query)
    # The changes grew past ``COMPACT_SHARE`` of the documents along the way, so it was built again at least once.
    assert len(bases) > 1


def test_rrf_order_and_tie_break() -> None:
    fused = pc._rrf(["a", "b", "c"], ["c", "b", "d"])
    assert [ref for ref, _ in fused] == ["c", "b", "a", "d"]
    assert dict(fused)["c"] == pytest.approx(1 / 63 + 1 / 61)
    assert dict(fused)["b"] == pytest.approx(2 / 62)
    assert pc._rrf(["b", "a"], ["a", "b"]) == [
        ("a", 1 / 61 + 1 / 62),
        ("b", 1 / 61 + 1 / 62),
    ]
    assert pc._rrf([], []) == []


@pytest.mark.parametrize("term", ["QX-7", "4200万"])
@pytest.mark.parametrize("indexed", [True, False])
def test_retrieve_promotes_exact_term(term: str, indexed: bool) -> None:
    settings = Settings(target_name="张三")
    embedder = ConstantEmbedder()
    rare = PersonaItem(item_id="pi_000", facet_id="2.1", statement=f"负责{term}项目", evidence=[])
    items = [
        rare,
        *[
            PersonaItem(item_id=f"pi_{i:03}", facet_id="2.1", statement="日常工作安排", evidence=[])
            for i in range(1, 21)
        ],
    ]
    with PersonaStore(":memory:") as store:
        store.replace_facet_items("2.1", items)
        chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), embedder, settings)
        if indexed:
            pc.index_persona(store, embedder, settings)
            ids, matrix = store.get_vectors(pc.ITEMS_NS)
            sims = matrix @ embedder.embed([term])[0]
            vector_order = [ref for _, ref in sorted(zip(sims, ids, strict=True), reverse=True)]
            assert rare.item_id not in vector_order[: pc.K_ITEMS]
            baseline = chat.retrieve("unmatched")
            assert [item.item_id for item, _ in baseline.items] == vector_order[: pc.K_ITEMS]
        else:
            assert chat.retrieve("unmatched").items == []
        ctx = chat.retrieve(term)
        assert ctx.items[0][0].item_id == rare.item_id
        assert len(ctx.items) == (pc.K_ITEMS if indexed else 1)
        assert ctx.items[0][1] > 0


def test_keyword_ranking_includes_candidates_without_vectors_and_excludes_stale_vectors() -> None:
    with PersonaStore(":memory:") as store:
        store.update_vectors(
            pc.ITEMS_NS,
            "test",
            [("stale", "sha", np.array([1.0, 0.0])), ("b", "sha", np.array([0.0, 1.0]))],
        )
        candidates = {"a": "rare", "b": "other"}
        ranked = pc._rank(store, pc.ITEMS_NS, [("rare", np.array([1.0, 0.0]))], candidates, str, 12, "test")
        assert ranked == [("rare", 1 / 61), ("other", 1 / 61)]
        # A rewrite hint is one more pair of rankings fused with equal weight.
        hinted = pc._rank(
            store,
            pc.ITEMS_NS,
            [("rare", np.array([1.0, 0.0])), ("other", np.array([0.0, 1.0]))],
            candidates,
            str,
            12,
            "test",
        )
        assert hinted == [("other", 3 / 61), ("rare", 1 / 61)]


class WiderEmbedder:
    """Another model: a different vector space and dimension than ``ConstantEmbedder``."""

    name = "wider"
    cluster_threshold = 0.6

    def embed(self, texts: list[str]) -> Matrix:
        return np.tile(np.array([0.0, 0.0, 1.0], dtype=np.float32), (len(texts), 1))


class UnreachableEmbedder:
    name = "unreachable"
    cluster_threshold = 0.6

    def embed(self, texts: list[str]) -> Matrix:
        raise EmbedError("connection refused")


def test_retrieval_ranks_by_keywords_after_a_model_change_or_while_the_service_is_down() -> None:
    settings = Settings(target_name="张三")
    items = [
        PersonaItem(item_id="pi_000", facet_id="2.1", statement="负责QX-7项目", evidence=[]),
        PersonaItem(item_id="pi_001", facet_id="2.1", statement="日常工作安排", evidence=[]),
    ]
    with PersonaStore(":memory:") as store:
        store.replace_facet_items("2.1", items)
        pc.index_persona(store, ConstantEmbedder(), settings)
        assert not pc.index_stale(store, ConstantEmbedder())
        # Vectors of the old model are never compared with the new model's queries (2 vs 3 dimensions).
        assert pc.index_stale(store, WiderEmbedder())
        for embedder in (WiderEmbedder(), UnreachableEmbedder()):
            chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), embedder, settings)
            assert [item.item_id for item, _ in chat.retrieve("QX-7").items] == ["pi_000"]
        assert [i.item_id for i in pc.search_items(store, WiderEmbedder(), "QX-7", 5)] == ["pi_000"]
        pc.index_persona(store, WiderEmbedder(), settings)
        assert not pc.index_stale(store, WiderEmbedder())
        chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), WiderEmbedder(), settings)
        assert len(chat.retrieve("QX-7").items) == 2


def test_expression_keywords_use_privacy_view_and_context_without_vectors() -> None:
    settings = Settings(target_name="张三", pseudonymize_others=True)
    parsed = parse_chat(
        "context.txt",
        "2026-09-01 10:00 李四：QX-7 的安排呢？\n2026-09-01 10:01 张三：先核对数据再决定。",
        settings,
    )
    with PersonaStore(":memory:") as store:
        store.put_source(parsed)
        chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), ConstantEmbedder(), settings)
        assert chat.retrieve("李四").expressions == []
        for query in ("QX-7", pseudonym("李四")):
            ctx = chat.retrieve(query)
            assert len(ctx.expressions) == 1
            expression = ctx.expressions[0][0]
            assert expression.is_target and expression.expression_id == parsed.expressions[-1].expression_id
            assert "李四" not in pc.expression_text(expression)
            assert pseudonym("李四") in expression.context
        assert "李四" in store.list_expressions()[-1].context


def test_bm25_5000_docs_under_one_second(record_property: Callable[[str, object], None]) -> None:
    text = "项目团队讨论数据分析预算安排客户需求产品研发风险管理工作计划交付质量业务发展合作方案"
    docs = {str(i): (text + chr(0x4E00 + i) + "检索测试补充材料" * 2)[:60] for i in range(5000)}
    # CPU time of this process, not wall time: other processes competing for the cores (a parallel suite, a busy
    # release machine) do not count against the budget, only the work BM25 itself does.
    start = process_time()
    scores = BM25(docs).scores("数据分析预算")
    elapsed = process_time() - start
    record_property("bm25_seconds", elapsed)
    assert len(scores) == 5000
    # Coverage tracing (pytest-testmon recording the code each test runs) slows it severalfold; time it untraced.
    if Coverage.current() is None:
        assert elapsed < 1.0


@pytest.mark.rewrite
def test_the_material_is_read_and_the_question_embedded_while_the_question_is_rewritten() -> None:
    settings = Settings(target_name="张三")
    with PersonaStore(":memory:") as store:
        store.replace_facet_items(
            "2.1", [PersonaItem(item_id="pi_000", facet_id="2.1", statement="负责QX-7项目", evidence=[])]
        )
        read = threading.Event()
        read_corpus = store.read_corpus

        def reading() -> tuple[list[object], list[object]]:
            read.set()
            return read_corpus()  # type: ignore[return-value]

        store.read_corpus = reading  # type: ignore[method-assign]
        embedded: list[list[str]] = []
        asked = threading.Event()

        class Recording(ConstantEmbedder):
            def embed(self, texts: list[str]) -> Matrix:
                embedded.append(texts)
                asked.set()
                return super().embed(texts)

        overlapped: list[bool] = []

        def rewrite(system: str, user: str, schema: type) -> dict[str, object]:
            # The rewrite waits on the network; the store is read and the question embedded meanwhile, not after it
            # answers.
            overlapped.append(read.wait(timeout=10) and asked.wait(timeout=10))
            return {"aspects": ["项目（project）"], "alternatives": ["甲", "乙"]}

        chat = pc.PersonaChat(store, FakeLLM(rewrite), Recording(), settings)
        ctx = chat._search([ChatTurn(role="user", content="QX-7 怎么样？")], None)
        assert overlapped == [True]
        # What the rewrite named is embedded once it answers, in the order retrieval ranks it; the question's call may
        # still be running then.
        assert sorted(embedded) == [["QX-7 怎么样？"], ["项目（project）", "甲", "乙"]]
        assert [item.item_id for item, _ in ctx.items] == ["pi_000"]


def test_the_material_is_kept_between_questions_until_the_memory_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(target_name="张三")
    embedder = ConstantEmbedder()
    path = tmp_path / "twin.db"
    reads: list[int] = []
    read_corpus = PersonaStore.read_corpus

    def counted(store: PersonaStore) -> tuple[list[Source], list[Expression]]:
        reads.append(1)
        return read_corpus(store)

    monkeypatch.setattr(PersonaStore, "read_corpus", counted)

    def ask(question: str, audience: Audience = SELF) -> list[str]:
        # Each question opens its own store connection, as the web does.
        with PersonaStore(path) as store:
            chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), embedder, settings, audience=audience)
            return [item.item_id for item, _ in chat.retrieve(question).items]

    item = PersonaItem(item_id="pi_000", facet_id="2.1", statement="负责QX-7项目", evidence=[])
    with PersonaStore(path) as store:
        store.replace_facet_items("2.1", [item])
        pc.index_persona(store, embedder, settings)
    reads.clear()
    assert ask("QX-7") == ["pi_000"]
    assert ask("QX-7") == ["pi_000"] and len(reads) == 1
    # Another tier's view is read for itself.
    ask("QX-7", COLLEAGUE)
    assert len(reads) == 2
    # Writing what chat retrieves from, from any connection, has the next question read the memory again.
    with sqlite3.connect(path) as db:
        db.execute("UPDATE p_items SET json = replace(json, 'QX-7', 'QX-8')")
    assert ask("QX-8") == ["pi_000"] and len(reads) == 3
    # A conversation, or a build's cache of merged batches, is not what chat retrieves from.
    with PersonaStore(path) as store:
        store.create_conversation(None)
        store.set_meta("merge_batch:2.1:x", "{}")
    ask("QX-8")
    assert len(reads) == 3
    monkeypatch.setattr(pc, "KEPT_MATERIAL_BYTES", 0)
    ask("QX-8")
    ask("QX-8")
    assert len(reads) == 5


def test_kept_materials_beyond_the_budget_are_dropped_least_recently_used_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(target_name="张三")
    monkeypatch.setattr(pc, "_kept_material", pc.OrderedDict())
    paths = [tmp_path / f"{name}.db" for name in ("a", "b")]
    for path in paths:
        with PersonaStore(path) as store:
            store.replace_facet_items(
                "2.1", [PersonaItem(item_id="pi_000", facet_id="2.1", statement="负责QX-7项目", evidence=[])]
            )
            pc.index_persona(store, ConstantEmbedder(), settings)

    def read(path: Path) -> pc._Material:
        with PersonaStore(path) as store:
            return pc.PersonaChat(store, FakeLLM(lambda *a: {}), ConstantEmbedder(), settings)._material(None)

    material = read(paths[0])
    assert len(pc._kept_material) == 1
    # Room for one: the twin read last stays, whatever its size, and the one asked longest ago goes.
    monkeypatch.setattr(pc, "KEPT_MATERIAL_BYTES", material.nbytes())
    read(paths[1])
    assert [key[0] for key in pc._kept_material] == [str(paths[1].resolve())]


def test_a_line_found_in_a_meeting_is_shown_with_the_lines_said_around_it() -> None:
    settings = Settings(target_name="张三")
    source = Source(
        source_id="src_meeting",
        kind=SourceKind.AUDIO,
        title="190910_1832",
        origin="录音库：190910_1832.mp3",
        imported_at="2026-10-27T00:00:00+00:00",
        n_expressions=0,
        n_target=0,
        text_state="raw",
        creation_time="2019-09-10",
        media_status="ready",
    )
    lines = [("张三" if i % 2 else "李四", f"第{i}句闲聊", i % 2 == 1) for i in range(30)]
    lines[11] = ("张三", "客户案例为什么员工不转发", True)
    lines[13] = ("李四", "老王下次开会前把转发率分析清楚", False)
    lines[25] = ("张三", "客户案例要真实", True)
    with PersonaStore(":memory:") as store:
        store.put_source(parse_media(source, lines))
        store.put_source(parse_chat("chat.txt", "张三：客户案例我写过一篇\n", settings))
        chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), ConstantEmbedder(), settings)
        ctx = chat.retrieve("客户案例")
    # The two lines found in the meeting are far apart: a passage each, around them, both speakers', in order.
    [first, second] = sorted(ctx.passages, key=lambda p: p.lines[0].idx)
    assert [e.idx for e in first.lines] == list(range(11 - pc.PASSAGE_BEFORE, 11 + pc.PASSAGE_AFTER + 1))
    assert first.ref == "src_meeting#00011" and first.title == "190910_1832"
    assert [e.idx for e in second.lines] == list(range(25 - pc.PASSAGE_BEFORE, 30))
    text = pc.material_text(ctx)
    assert "会议片段" in text and f"  {pseudonym('李四')}：老王下次开会前把转发率分析清楚" in text
    assert f"- [{first.ref}] 会议 2019-09-10 190910_1832：" in text
    # A line of a meeting is shown once, in its passage; a chat line stays one of the person's own words.
    assert text.count("客户案例为什么员工不转发") == 1
    assert "本人原话：" in text and "客户案例我写过一篇" in text
    # What the passage shows may be cited and quoted.
    assert "src_meeting#00013" in ctx.ids
    quoted, removed = pc.remove_unverified_quotes("他说「老王下次开会前把转发率分析清楚」", pc._quote_materials(ctx))
    assert removed == 0 and "老王下次开会前" in quoted


def test_windows_that_overlap_in_a_meeting_are_one_passage() -> None:
    meeting = {
        ("m", i): Expression(
            expression_id=f"m#{i:05d}", source_id="m", idx=i, speaker="甲", is_target=False, text=f"第{i}句"
        )
        for i in range(40)
    }
    material = pc._Material(*(pc._Corpus(pc.NO_VECTORS, {}, str) for _ in range(3)), [], [], None, meeting, {"m": "会"})
    found = [meeting[("m", 20)], meeting[("m", 15)], meeting[("m", 35)]]
    passages = pc._passages(material, found)
    # 15 and 20 overlap: one passage, cited by the better-ranked 20; 35 stands apart.
    assert [(p.ref, p.lines[0].idx, p.lines[-1].idx) for p in passages] == [
        ("m#00020", 15 - pc.PASSAGE_BEFORE, 20 + pc.PASSAGE_AFTER),
        ("m#00035", 35 - pc.PASSAGE_BEFORE, 39),
    ]


def test_a_meeting_recorded_without_its_day_is_dated_by_its_file_and_found_by_that_day() -> None:
    settings = Settings(target_name="张三")

    def recording(title: str, words: str) -> ParsedSource:
        source = Source(
            source_id=f"src_{title}",
            kind=SourceKind.AUDIO,
            title=title,
            origin=f"录音库：{title}.mp3",
            imported_at="2026-10-27T00:00:00+00:00",
            n_expressions=0,
            n_target=0,
            text_state="raw",
            media_status="ready",
        )
        return parse_media(source, [("张三", f"{words}{i}", True) for i in range(30)])

    with PersonaStore(":memory:") as store:
        store.put_source(recording("190708_1834", "游轮项目先查撤单数据"))
        # The other meeting shares every word of the question: only the day tells them apart.
        store.put_source(recording("190801_1830", "那次会上定了哪些事情要查"))
        chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), ConstantEmbedder(), settings)
        assert pc.meeting_day(store.get_source("src_190708_1834")) == dt.date(2019, 7, 8)
        ctx = chat.retrieve("2019年7月8号那次会上定了哪些事？", today=dt.date(2026, 10, 27))
        assert ctx.window == (dt.date(2019, 7, 8), dt.date(2019, 7, 8))
        assert ctx.passages[0].title == "190708_1834"
        assert "- [src_190708_1834#" in pc.material_text(ctx) and " 会议 2019-07-08 190708_1834：" in pc.material_text(
            ctx
        )
        # The latest meeting is the one asked about as the last.
        assert chat.retrieve("最近一次会说了什么", today=dt.date(2026, 10, 27)).passages[0].title == "190801_1830"
