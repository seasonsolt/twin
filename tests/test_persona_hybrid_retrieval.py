from __future__ import annotations

import math
from collections.abc import Callable
from time import perf_counter

import numpy as np
import pytest

from twin.config import Settings
from twin.embed import Matrix
from twin.llm import FakeLLM
from twin.persona import chat as pc
from twin.persona.items import PersonaItem
from twin.persona.lexical import BM25, tokenize
from twin.persona.sources import parse_chat, pseudonym
from twin.persona.store import PersonaStore


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
        ranked = pc._rank(store, pc.ITEMS_NS, "rare", np.array([1.0, 0.0]), {"a": "rare", "b": "other"}, str, 12)
        assert ranked == [("rare", 1 / 61), ("other", 1 / 61)]


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
    start = perf_counter()
    scores = BM25(docs).scores("数据分析预算")
    elapsed = perf_counter() - start
    record_property("bm25_seconds", elapsed)
    assert len(scores) == 5000
    assert elapsed < 1.0
