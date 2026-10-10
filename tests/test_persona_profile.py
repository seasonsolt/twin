from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.llm import FakeLLM, LLMError, LLMTruncated
from twin.persona import profile as pf
from twin.persona.items import item_as_of
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


def test_consent_gated_facets_need_an_answered_questionnaire_question(store: PersonaStore) -> None:
    allowed = pf.consented_facets(store)
    assert "9.1" in allowed and "9.3" not in allowed and "3.1" in allowed
    empty = PersonaStore(":memory:")
    assert not any(f.startswith("9.") for f in pf.consented_facets(empty))


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


def test_chunks_split_at_the_size_limit(
    store: PersonaStore, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pf, "CHUNK_CHARS", 40)
    chat = store.list_sources()[1]
    chunks = pf.chunks_for(store, chat, pf.consented_facets(store), settings)
    assert len(chunks) == 2 and all(len(c.entries) == 1 for c in chunks)
    assert chunks[0].text.startswith("[1] 2026-09-01 · 群_2026-09\n语境：李四：这单签了，首付 10%\n本人：")


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


def test_statement_prompts_omit_pronoun_subjects() -> None:
    assert "不加人称代词主语" in pf.EXTRACT_SYSTEM and "不加人称代词主语" in pf.MERGE_SYSTEM
    assert "不加人称代词主语" in pf.CandidateDraft.model_fields["statement"].description
    assert "不加人称代词主语" in pf.MergedDraft.model_fields["statement"].description
    assert "在成都做产品经理" in pf.EXTRACT_SYSTEM
    assert "做决定前喜欢先睡一觉" in pf.EXTRACT_SYSTEM
    assert not any(word in pf.EXTRACT_SYSTEM for word in ("回款", "首付", "公曰", "奏称", "升迁"))


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
