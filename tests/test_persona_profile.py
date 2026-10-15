from __future__ import annotations

import datetime as dt
import json
import re
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.llm import FakeLLM, LLMError, LLMTruncated
from twin.persona import profile as pf
from twin.persona.dimensions import FACETS
from twin.persona.items import ExtractStats, item_as_of
from twin.persona.schema import EvidenceClass
from twin.persona.sources import parse_chat, parse_questionnaire
from twin.persona.store import PersonaStore
from twin.usage import BudgetExceeded

D = dt.date

QUESTIONNAIRE = """**4. 把下面几项排序。**　*偏好 · 2.1*

回答：结果第一，钱进了账户才算数。

**13.合作方提出一个大单，你第一句会说什么？**　*情境 · 3.4 3.6*

回答：首付多少？

**33.【可跳过】工作之外你喜欢做什么？**　*开放 · 9.1*

回答：跑步，周末跑半马。

**36.【可跳过】家庭方面？**　*开放 · 9.3*

回答：
"""

CHAT = """2026-09-01 10:02 李四：这单签了，首付 10%
2026-09-01 10:05 张三：首付不到 30% 不开工，说白了钱进了账户才叫收入
2026-09-02 09:00 李四：数据看着不错
2026-09-02 09:01 张三：我就问一句，对照组是谁挑的？
"""


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="张三", max_workers=2, pseudonymize_others=False)


@pytest.fixture
def store(settings: Settings) -> PersonaStore:
    s = PersonaStore(":memory:")
    s.put_source(parse_questionnaire("q_2026-08-30.md", QUESTIONNAIRE, settings))
    s.put_source(parse_chat("群_2026-09.txt", CHAT, settings))
    return s


def entries(user: str) -> dict[int, str]:
    return {int(n): t for n, t in re.findall(r"\[(\d+)\][^\n]*\n(?:语境：[^\n]*\n)?本人：([^\n]*)", user)}


def handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    if schema is pf.ExtractDraft:
        found = entries(user)
        items: list[dict[str, Any]] = []
        for n, text in found.items():
            if "钱进了账户" in text:
                items.append(
                    {"facet_id": "2.1", "statement": "他把回款放在第一位", "quotes": [{"n": n, "quote": "钱进了账户"}]}
                )
            if "对照组" in text:
                items.append(
                    {"facet_id": "4.2", "statement": "他追问对照组", "quotes": [{"n": n, "quote": "对照组是谁挑的"}]}
                )
                items.append({"facet_id": "4.2", "statement": "编造", "quotes": [{"n": n, "quote": "从来不看数据"}]})
            if "半马" in text:
                items.append({"facet_id": "9.1", "statement": "他爱跑步", "quotes": [{"n": n, "quote": "周末跑半马"}]})
            items.append({"facet_id": "9.3", "statement": "未授权", "quotes": [{"n": n, "quote": text[:4]}]})
            items.append({"facet_id": "3.1", "statement": "越界编号", "quotes": [{"n": 99, "quote": text[:4]}]})
        return {"items": items}
    if schema is pf.MergeDraft:
        ids = re.findall(r"\[(pc_[0-9a-f]+)\]", user)
        return {
            "items": [{"statement": "他认为钱进了账户才算收入", "candidate_ids": ids, "conflict": "自述与行为一致"}]
        }
    raise AssertionError(schema)


@pytest.mark.usefixtures("gated_life_facets")
def test_consent_gated_facets_need_an_answered_questionnaire_question(store: PersonaStore) -> None:
    allowed = pf.consented_facets(store)
    assert "9.1" in allowed and "9.3" not in allowed and "3.1" in allowed
    empty = PersonaStore(":memory:")
    assert not any(f.startswith("9.") for f in pf.consented_facets(empty))


def test_life_facets_are_built_from_any_source_without_a_questionnaire(settings: Settings) -> None:
    chats = PersonaStore(":memory:")
    chats.put_source(parse_chat("群_2026-09.txt", CHAT, settings))
    assert pf.consented_facets(chats) == frozenset(f.facet_id for f in FACETS)
    llm = FakeLLM(handler)
    pf.build_profile(chats, llm, settings)
    assert "9.3" in {c.facet_id for c in chats.list_candidates()}
    assert all("9.4" in system for name, system, _ in llm.calls if name == "ExtractDraft")


@pytest.mark.usefixtures("gated_life_facets")
def test_an_evaluation_can_build_gated_facets_as_if_consented(settings: Settings) -> None:
    chats = PersonaStore(":memory:")
    chats.put_source(parse_chat("群_2026-09.txt", CHAT, settings))
    pf.build_profile(chats, FakeLLM(handler), settings)
    assert not any(c.facet_id.startswith("9.") for c in chats.list_candidates())

    granted = PersonaStore(":memory:")
    granted.put_source(parse_chat("群_2026-09.txt", CHAT, settings))
    llm = FakeLLM(handler)
    pf.build_profile(granted, llm, settings, grant_gated=True)
    assert "9.3" in {c.facet_id for c in granted.list_candidates()}
    assert all("9.4" in system for name, system, _ in llm.calls if name == "ExtractDraft")


@pytest.mark.usefixtures("gated_life_facets")
def test_build_extracts_verified_candidates_merges_per_facet_and_is_incremental(
    store: PersonaStore, settings: Settings
) -> None:
    llm = FakeLLM(handler)
    report = pf.build_profile(store, llm, settings)
    assert report.failures == [] and report.sources == 2 and report.chunks_extracted == 2
    users = [u for name, _, u in llm.calls if name == "ExtractDraft"]
    assert any("首付多少" in u for u in users)
    candidates = store.list_candidates()
    assert sorted(c.facet_id for c in candidates) == [
        "2.1",
        "2.1",
        "4.2",
        "9.1",
    ]  # fabricated, unconsented, n=99 dropped
    by_facet = {i.facet_id: i for i in store.list_items()}
    money = by_facet["2.1"]
    assert money.statement == "他认为钱进了账户才算收入" and money.conflict == "自述与行为一致"
    assert money.classes() == {EvidenceClass.SELF_REPORT, EvidenceClass.BEHAVIOR} and money.occasions() == 2
    assert by_facet["4.2"].statement == "他追问对照组"  # a single candidate is kept as is, without a merge call
    assert [name for name, _, _ in llm.calls].count("MergeDraft") == 1

    calls = len(llm.calls)
    again = pf.build_profile(store, llm, settings)
    assert len(llm.calls) == calls and again.chunks_extracted == 0 and again.facets_merged == 0

    chat = store.list_sources()[1]
    assert store.delete_source(chat.source_id)
    pf.build_profile(store, llm, settings)
    assert {i.facet_id for i in store.list_items()} == {"2.1", "9.1"}  # 4.2 lost its only source
    assert store.list_items("2.1")[0].classes() == {EvidenceClass.SELF_REPORT}


@pytest.mark.parametrize(
    "default, override, expected",
    [
        (None, None, None),
        ("none", None, "low"),
        ("high", None, "high"),
        ("none", "medium", "medium"),
        ("high", "none", "none"),
    ],
)
def test_extract_and_merge_use_effective_reasoning_effort(
    store: PersonaStore,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    default: Any,
    override: Any,
    expected: str | None,
) -> None:
    settings.llm.reasoning_effort = default
    settings.llm.reasoning_effort_extract = override
    llm = FakeLLM(handler)
    original = llm.structured
    options: list[dict[str, Any]] = []

    def structured(**kwargs: Any) -> BaseModel:
        options.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(llm, "structured", structured)
    report = pf.build_profile(store, llm, settings)
    assert report.failures == []
    assert {call["schema"] for call in options} == {pf.ExtractDraft, pf.MergeDraft}
    assert all(call["reasoning_effort"] == expected for call in options)
    assert all(call["effort"] == settings.llm.effort_extract for call in options)


def test_a_build_records_the_model_calls_it_made(store: PersonaStore, settings: Settings) -> None:
    llm = FakeLLM(handler)
    report = pf.build_profile(store, llm, settings)
    assert report.calls["calls"] == len(llm.calls) > 0 and report.calls["failures"] == 0
    assert report.calls["transient"] == {} and report.calls["models"] == [llm.name]
    assert json.loads(store.get_meta("build:last_calls") or "") == report.calls
    assert pf.build_profile(store, llm, settings).calls["calls"] == 0
    assert json.loads(store.get_meta("build:last_calls") or "") == report.calls


def test_failed_chunk_is_reported_and_retried_next_build(store: PersonaStore, settings: Settings) -> None:
    def flaky(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is pf.ExtractDraft and "对照组" in user:
            raise RuntimeError("boom")
        return handler(system, user, schema)

    first = pf.build_profile(store, FakeLLM(flaky), settings)
    assert len(first.failures) == 1 and "RuntimeError" in first.failures[0] and first.chunks_extracted == 1
    second = pf.build_profile(store, FakeLLM(handler), settings)
    assert second.chunks_extracted == 1 and second.failures == []


def test_a_truncated_call_is_made_once_more(store: PersonaStore, settings: Settings) -> None:
    truncated: list[str] = []

    def runaway_once(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        key = f"{schema.__name__}:{user}"
        if key not in truncated:
            truncated.append(key)
            raise LLMTruncated("hit max_tokens")
        return handler(system, user, schema)

    report = pf.build_profile(store, FakeLLM(runaway_once), settings)
    assert report.failures == [] and report.chunks_extracted == 2 and report.items > 0


@pytest.mark.usefixtures("gated_life_facets")
def test_a_chunk_cut_off_twice_is_extracted_in_halves(settings: Settings) -> None:
    plain = PersonaStore(":memory:")
    plain.put_source(parse_chat("群_2026-09.txt", CHAT, settings))
    seen: list[int] = []

    def long_replies(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is pf.ExtractDraft:
            seen.append(len(entries(user)))
            if len(entries(user)) > 1:
                raise LLMTruncated("hit max_tokens")
        return handler(system, user, schema)

    report = pf.build_profile(plain, FakeLLM(long_replies), settings)
    assert report.failures == [] and report.chunks_extracted == 1
    assert seen == [2, 2, 1, 1]  # the whole chunk twice, then each half
    assert report.extraction.splits == 1 and report.extraction.kept == 2
    [chunk] = pf.chunks_for(plain, plain.list_sources()[0], pf.consented_facets(plain), settings)
    candidates = plain.list_candidates()
    assert {c.chunk_id for c in candidates} == {chunk.chunk_id}
    assert len({c.candidate_id for c in candidates}) == len(candidates) == 2
    assert sorted(c.statement for c in candidates) == ["他把回款放在第一位", "他追问对照组"]

    def always_cut_off(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        raise LLMTruncated("hit max_tokens")

    with pytest.raises(LLMTruncated):  # a single entry cannot be split further
        pf.extract_chunk(FakeLLM(always_cut_off), chunk, pf.consented_facets(plain), settings)


def test_chunks_split_at_the_size_limit(
    store: PersonaStore, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pf, "CHUNK_CHARS", 40)
    chat = store.list_sources()[1]
    chunks = pf.chunks_for(store, chat, pf.consented_facets(store), settings)
    assert len(chunks) == 2 and all(len(c.entries) == 1 for c in chunks)
    assert chunks[0].text.startswith("[1] 2026-09-01 · 群_2026-09\n语境：李四：这单签了，首付 10%\n本人：")


@pytest.mark.usefixtures("gated_life_facets")
def test_extraction_counts_what_it_dropped_and_why(store: PersonaStore, settings: Settings) -> None:
    report = pf.build_profile(store, FakeLLM(handler), settings)
    # Per entry the handler adds an unconsented 9.3 and a quote of entry 99; the chat adds one fabricated quote.
    assert report.extraction == ExtractStats(
        returned=15,
        kept=4,
        off_facet=5,
        unsupported=6,
        quotes_unmatched=1,
        quotes_misnumbered=5,
        unknown_facets={"9.3": 5},
    )
    q, chat = (s.source_id for s in store.list_sources())
    assert store.extraction_stats() == {
        q: (
            1,
            ExtractStats(
                returned=8, kept=2, off_facet=3, unsupported=3, quotes_misnumbered=3, unknown_facets={"9.3": 3}
            ),
        ),
        chat: (
            1,
            ExtractStats(
                returned=7,
                kept=2,
                off_facet=2,
                unsupported=3,
                quotes_unmatched=1,
                quotes_misnumbered=2,
                unknown_facets={"9.3": 2},
            ),
        ),
    }
    assert pf.source_memories(store)[chat].nothing_found_reason == ""  # it supports memories


def test_a_source_without_memories_says_why(settings: Settings) -> None:
    def answer(found: list[dict[str, Any]]) -> Any:
        return lambda system, user, schema: {"items": found} if schema is pf.ExtractDraft else {"items": []}

    store = PersonaStore(":memory:")
    store.put_source(parse_chat("群_2026-09.txt", CHAT, settings))
    sid = store.list_sources()[0].source_id
    memory = pf.source_memories(store)[sid]
    assert (memory.chunks_extracted, memory.extraction, memory.nothing_found_reason) == (0, None, "")

    pf.build_profile(store, FakeLLM(answer([])), settings)
    memory = pf.source_memories(store)[sid]
    assert memory.build_status == "no_items" and memory.chunks_extracted == 1
    assert memory.nothing_found_reason == "模型没有从中提炼出结论"

    store.put_source(parse_chat("群_2026-10.txt", CHAT.replace("09-0", "10-0"), settings))
    sid = store.list_sources()[1].source_id
    misquoted = [
        {"facet_id": "4.2", "statement": "追问对照组", "quotes": [{"n": 2, "quote": "从来不看数据"}]},
        {"facet_id": "4.2", "statement": "编号越界", "quotes": [{"n": 9, "quote": "对照组"}]},
        {"facet_id": "D4", "statement": "没有这个细项", "quotes": [{"n": 2, "quote": "对照组"}]},
        {"facet_id": "D4", "statement": "还是没有", "quotes": [{"n": 2, "quote": "对照组"}]},
        {
            "facet_id": "思考方式与追问习惯之类的很长很长名字",
            "statement": "名字太长",
            "quotes": [{"n": 2, "quote": "对照组"}],
        },
        {"facet_id": "4.2", "statement": " ", "quotes": [{"n": 2, "quote": "对照组"}]},
    ]
    pf.build_profile(store, FakeLLM(answer(misquoted)), settings)
    memory = pf.source_memories(store)[sid]
    assert memory.extraction is not None and memory.extraction.unknown_facets == {
        "D4": 2,
        "思考方式与追问习惯之类的很长很长": 1,
    }
    assert memory.nothing_found_reason == (
        "模型提炼了 6 条结论，校验后全部丢弃：引文与原文对不上 1 处，引用了不存在的条目 1 处，"
        "细项不在可用列表里 3 条（模型写的是 “D4”×2、“思考方式与追问习惯之类的很长很长”×1），结论为空 1 条"
    )
    legacy = ExtractStats(returned=2, off_facet=2)  # counted before facets and empty statements were told apart
    assert pf.nothing_found_reason(legacy) == "模型提炼了 2 条结论，校验后全部丢弃：细项不可用或结论为空 2 条"


@pytest.mark.parametrize(
    "written, facet",
    [
        ("2.1", "2.1"),
        (" 8.2 正在做的事", "8.2"),
        ("8.2：近期在做的事", "8.2"),
        ("细项 8．2", "8.2"),
        ("4.2 / 4.1", "4.2"),
        ("D8", "D8"),
        ("D8 最近在关注", "D8 最近在关注"),
        ("8.2.1", "8.2.1"),
        ("2026.10", "2026.10"),
    ],
)
def test_facet_ids_are_read_from_how_models_write_them(written: str, facet: str) -> None:
    assert pf.facet_id(written) == facet


@pytest.mark.usefixtures("gated_life_facets")
def test_a_facet_written_with_its_name_is_kept(settings: Settings) -> None:
    store = PersonaStore(":memory:")
    store.put_source(parse_chat("群_2026-09.txt", CHAT, settings))
    named = [
        {"facet_id": "4.2 追问习惯", "statement": "追问对照组", "quotes": [{"n": 2, "quote": "对照组是谁挑的"}]},
        {"facet_id": "D4", "statement": "说不清细项", "quotes": [{"n": 2, "quote": "对照组"}]},
    ]
    report = pf.build_profile(
        store, FakeLLM(lambda s, u, schema: {"items": named if schema is pf.ExtractDraft else []}), settings
    )
    assert [c.facet_id for c in store.list_candidates()] == ["4.2"]
    assert report.extraction.kept == 1 and report.extraction.unknown_facets == {"D4": 1}


def test_only_the_chunks_that_found_nothing_are_extracted_again(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pf, "CHUNK_CHARS", 40)  # one chunk per entry
    store = PersonaStore(":memory:")
    store.put_source(parse_chat("群_2026-09.txt", CHAT, settings))
    store.put_source(parse_chat("群_2026-10.txt", CHAT.replace("09-0", "10-0"), settings))
    sep, oct_ = (s.source_id for s in store.list_sources())

    def money_only(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        found = [n for n, text in entries(user).items() if "钱进了账户" in text]
        quotes = [{"n": n, "quote": "钱进了账户"} for n in found]
        items = [{"facet_id": "2.1", "statement": "回款第一", "quotes": quotes}] if found else []
        return {"items": items} if schema is pf.ExtractDraft else {"items": []}

    assert pf.build_profile(store, FakeLLM(money_only), settings).chunks_extracted == 4
    assert store.empty_chunks() == {sep: 1, oct_: 1}
    kept = {c.candidate_id for c in store.list_candidates()}

    assert store.reextract_source("src_missing", empty_only=True) is None
    assert store.reextract_source(sep, empty_only=True) == 1
    assert {c.candidate_id for c in store.list_candidates()} == kept  # chunks with candidates are untouched
    assert store.reextract_source(sep, empty_only=True) == 0  # nothing left to forget: not marked again
    llm = FakeLLM(handler)
    report = pf.build_profile(store, llm, settings)
    assert report.chunks_extracted == 1 and len([n for n, _, _ in llm.calls if n == "ExtractDraft"]) == 1
    assert store.empty_chunks() == {oct_: 1}
    assert not pf.profile_stale(store)


def test_a_build_views_the_corpus_once_and_cuts_the_same_chunks(
    store: PersonaStore, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.pseudonymize_others = True
    allowed = pf.consented_facets(store)
    sources = store.list_sources()
    per_source = [c for s in sources for c in pf.chunks_for(store, s, allowed, settings)]
    assert "他人" in "".join(c.text for c in per_source)  # the view pseudonymised 李四 in the context
    views: list[str | None] = []
    original = pf.expression_view

    def counted(*args: Any, **kwargs: Any) -> Any:
        views.append(kwargs.get("source_id"))
        return original(*args, **kwargs)

    monkeypatch.setattr(pf, "expression_view", counted)
    assert pf.corpus_chunks(store, sources, allowed, settings) == per_source
    assert pf.pending_chunks(store, settings) == len(per_source)
    report = pf.build_profile(store, FakeLLM(handler), settings)
    assert report.chunks_total == len(per_source)
    assert views == [None, None, None]


def test_only_questionnaire_extraction_asks_to_cover_every_stated_answer(
    store: PersonaStore, settings: Settings
) -> None:
    systems: dict[str, str] = {}

    def record(system: str, user: str, schema: type[BaseModel]) -> BaseModel | dict[str, Any]:
        if schema is pf.ExtractDraft:
            systems["questionnaire" if "questionnaire" in system else "chat"] = system
        return handler(system, user, schema)

    pf.build_profile(store, FakeLLM(record), settings)
    assert pf.QUESTIONNAIRE_COVERAGE.strip() in systems["questionnaire"]
    assert "都要被至少一条结论引用" not in systems["chat"]


def test_item_as_of_trims_later_and_undated_evidence(store: PersonaStore, settings: Settings) -> None:
    pf.build_profile(store, FakeLLM(handler), settings)
    money = store.list_items("2.1")[0]
    assert item_as_of(money, D(2026, 8, 31)) is not None
    assert item_as_of(money, D(2026, 8, 29)) is None
    trimmed = item_as_of(money, D(2026, 8, 30))
    assert trimmed is not None and trimmed.classes() == {EvidenceClass.SELF_REPORT}


def test_reviews_follow_items_through_a_re_merge(store: PersonaStore, settings: Settings) -> None:
    from twin.persona.items import PReview, carry_reviews
    from twin.persona.schema import ReviewStatus

    pf.build_profile(store, FakeLLM(handler), settings)
    old = store.list_items("2.1", raw=True)[0]
    review = PReview(status=ReviewStatus.CONFIRMED, reviewed_at="2026-10-03T10:00:00")
    grown = old.model_copy(
        update={"item_id": "pi_grown", "member_candidate_ids": [*old.member_candidate_ids, "pc_new"]}
    )
    split = old.model_copy(update={"item_id": "pi_split", "member_candidate_ids": old.member_candidate_ids[:1]})
    assert carry_reviews([old], [grown, split], {old.item_id: review}) == {"pi_grown": review}
    rejected = PReview(status=ReviewStatus.REJECTED, reviewed_at="2026-10-03T10:00:00")
    other = old.model_copy(update={"item_id": "pi_other", "member_candidate_ids": ["pc_new"]})
    assert carry_reviews([old, other], [grown], {old.item_id: review, "pi_other": rejected}) == {"pi_grown": rejected}

    store.set_review(old.item_id, review)
    store.replace_facet_items("2.1", [grown])
    assert store.reviews() == {"pi_grown": review}  # the old item's review moved, nothing left dangling


def test_reviews_follow_re_extracted_items_by_evidence_and_wording() -> None:
    from twin.persona.items import PersonaItem, PEvidence, PReview, carry_reviews
    from twin.persona.schema import ReviewStatus, SourceKind

    def item(item_id: str, statement: str, expressions: list[str], members: list[str]) -> PersonaItem:
        evidence = [
            PEvidence(
                expression_id=e,
                source_id="s1",
                source_kind=SourceKind.DOCUMENT,
                evidence_class=EvidenceClass.BEHAVIOR,
                quote="原话",
            )
            for e in expressions
        ]
        return PersonaItem(
            item_id=item_id, facet_id="2.1", statement=statement, evidence=evidence, member_candidate_ids=members
        )

    at = "2026-10-14T10:00:00"
    confirmed = PReview(status=ReviewStatus.CONFIRMED, reviewed_at=at)
    rejected = PReview(status=ReviewStatus.REJECTED, reviewed_at=at)
    money = item("pi_money", "做事先看回款", ["e1"], ["pc_a"])
    # Two traits drawn from the same expression: the wording decides which one continues the reviewed item.
    paid = item("pi_paid", "做事优先看回款", ["e1"], ["pc_x"])
    risk = item("pi_risk", "签约前先问风险", ["e1"], ["pc_y"])
    assert carry_reviews([money], [risk, paid], {"pi_money": confirmed}) == {"pi_paid": confirmed}
    # A similar wording quoting nothing the old item quoted is a different occasion, not a re-extraction.
    elsewhere = item("pi_elsewhere", "做事先看回款", ["e9"], ["pc_z"])
    assert carry_reviews([money], [elsewhere], {"pi_money": confirmed}) == {}
    # An edit is matched by the person's wording as well as the extracted one.
    edited = PReview(status=ReviewStatus.EDITED, statement="签约前先问风险", reviewed_at=at)
    vague = item("pi_vague", "看重安全", ["e1"], ["pc_b"])
    assert carry_reviews([vague], [paid, risk], {"pi_vague": edited}) == {"pi_risk": edited}
    # Old items merged into one new item: the rejection wins, as with surviving candidates.
    twin = item("pi_twin", "做事先看回款", ["e1"], ["pc_c"])
    assert carry_reviews([money, twin], [paid], {"pi_money": confirmed, "pi_twin": rejected}) == {"pi_paid": rejected}
    # A survivor keeps its review by candidates; nothing moves by wording while any candidate survives (a split).
    grown = item("pi_grown", "做事先看回款", ["e1"], ["pc_a", "pc_new"])
    assert carry_reviews([money], [grown, paid], {"pi_money": confirmed}) == {"pi_grown": confirmed}
    both = item("pi_both", "做事先看回款", ["e1"], ["pc_a", "pc_d"])
    half = item("pi_half", "做事先看回款", ["e1"], ["pc_a"])
    assert carry_reviews([both], [half, paid], {"pi_both": confirmed}) == {}


def test_statement_prompts_omit_pronoun_subjects() -> None:
    assert "不加人称代词主语" in pf.EXTRACT_SYSTEM and "不加人称代词主语" in pf.MERGE_SYSTEM
    assert "不加人称代词主语" in pf.CandidateDraft.model_fields["statement"].description
    assert "不加人称代词主语" in pf.MergedDraft.model_fields["statement"].description
    assert "在成都做产品经理" in pf.EXTRACT_SYSTEM
    assert "做决定前喜欢先睡一觉" in pf.EXTRACT_SYSTEM
    assert not any(word in pf.EXTRACT_SYSTEM for word in ("回款", "首付", "公曰", "奏称", "升迁"))


@pytest.mark.usefixtures("gated_life_facets")
def test_a_failed_merge_keeps_candidates_and_is_merged_next_build(store: PersonaStore, settings: Settings) -> None:
    def merge_times_out(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is pf.MergeDraft:
            raise LLMError("timed out")
        return handler(system, user, schema)

    first = pf.build_profile(store, FakeLLM(merge_times_out), settings)
    assert first.failures == [] and first.degraded == ["merge 2.1: LLMError"]
    assert store.get_meta("built_at") is not None and store.get_meta("merge:2.1") is None
    assert sorted(i.statement for i in store.list_items("2.1")) == ["他把回款放在第一位"] * 2
    llm = FakeLLM(handler)
    second = pf.build_profile(store, llm, settings)
    assert second.degraded == [] and second.facets_merged == 1
    assert [name for name, _, _ in llm.calls] == ["MergeDraft"]
    assert [i.statement for i in store.list_items("2.1")] == ["他认为钱进了账户才算收入"]


def test_a_failed_merge_batch_is_merged_again_in_halves(store: PersonaStore, settings: Settings) -> None:
    pf.build_profile(store, FakeLLM(handler), settings)
    base = [c for c in store.list_candidates() if c.facet_id == "2.1"]
    candidates = [c.model_copy(update={"candidate_id": f"pc_{n:016x}"}) for n in range(4) for c in base[:1]]
    sizes: list[int] = []

    def long_batches_time_out(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        ids = re.findall(r"\[(pc_[0-9a-f]+)\]", user)
        sizes.append(len(ids))
        if len(ids) > 2:
            raise LLMError("timed out")
        return {"items": [{"statement": "合并", "candidate_ids": ids}]}

    with pytest.raises(pf.MergeDegraded) as degraded:
        pf.merge_facet(FakeLLM(long_batches_time_out), "2.1", candidates, settings)
    assert sizes == [4, 2, 2]
    assert [i.member_candidate_ids for i in degraded.value.items] == [
        [c.candidate_id for c in candidates[:2]],
        [c.candidate_id for c in candidates[2:]],
    ]

    def budget_stop(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        raise BudgetExceeded("budget")

    with pytest.raises(BudgetExceeded):
        pf.merge_facet(FakeLLM(budget_stop), "2.1", candidates, settings)
