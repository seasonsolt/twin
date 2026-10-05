from __future__ import annotations

import datetime as dt
import re
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.llm import FakeLLM, LLMTruncated
from twin.persona import profile as pf
from twin.persona.items import item_as_of
from twin.persona.schema import EvidenceClass
from twin.persona.sources import parse_biography, parse_chat, parse_questionnaire
from twin.persona.store import PersonaStore

D = dt.date

QUESTIONNAIRE = """**4. 把下面几项排序。**　*偏好 · 2.1*

回答：结果第一，钱进了账户才算数。

**13.【测试题】合作方提出一个大单，你第一句会说什么？**　*情境 · 3.4 3.6*

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
    assert all("首付多少" not in u for u in users)  # held-out test answers never reach extraction
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


def test_failed_chunk_is_reported_and_retried_next_build(store: PersonaStore, settings: Settings) -> None:
    def flaky(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is pf.ExtractDraft and "对照组" in user:
            raise RuntimeError("boom")
        return handler(system, user, schema)

    first = pf.build_profile(store, FakeLLM(flaky), settings)
    assert len(first.failures) == 1 and "boom" in first.failures[0] and first.chunks_extracted == 1
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


BIOGRAPHY = "# 1854 年\n\n公议进兵，众请速攻。公曰：宁可屯兵不进，不可轻进致败。遂坚守不出。\n"


def test_biography_narration_is_labelled_and_only_own_words_carry_style(settings: Settings) -> None:
    store = PersonaStore(":memory:")
    store.put_source(parse_biography("年谱.md", BIOGRAPHY, settings))
    seen: list[tuple[str, str]] = []

    def bio(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        seen.append((system, user))
        if schema is pf.MergeDraft:
            return {"items": [{"statement": "合并", "candidate_ids": re.findall(r"\[(pc_[0-9a-f]+)\]", user)}]}
        return {
            "items": [
                {"facet_id": "3.1", "statement": "他宁守勿冒进", "quotes": [{"n": 1, "quote": "遂坚守不出"}]},
                {
                    "facet_id": "6.3",
                    "statement": "他用对举句",
                    "quotes": [{"n": 1, "quote": "宁可屯兵不进，不可轻进致败", "own_words": True}],
                },
                {"facet_id": "6.1", "statement": "他说话简短", "quotes": [{"n": 1, "quote": "众请速攻"}]},
            ]
        }

    report = pf.build_profile(store, FakeLLM(bio), settings)
    system, user = seen[0]
    assert "记述：公议进兵" in user and "本人：" not in user and "第三人称的传记类资料" in system
    items = {i.facet_id: i for i in store.list_items()}
    assert set(items) == {"3.1", "6.3"}  # the style claim resting on narration alone is dropped
    assert items["3.1"].evidence[0].own_words is False and items["3.1"].evidence[0].date == D(1854, 7, 1)
    assert items["6.3"].evidence[0].own_words is True and report.failures == []
