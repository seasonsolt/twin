from __future__ import annotations

import pytest

from twin.config import Settings
from twin.persona import questionnaire as pq
from twin.persona.dimensions import FACET_BY_ID, FACETS
from twin.persona.store import PersonaStore


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="张三")


def test_question_bank_covers_every_facet_with_six_test_questions() -> None:
    assert len(pq.QUESTIONS) == 36 and len({q.qid for q in pq.QUESTIONS}) == 36
    assert {f for q in pq.QUESTIONS for f in q.facets} == {f.facet_id for f in FACETS}
    assert all(f in FACET_BY_ID for q in pq.QUESTIONS for f in q.facets)
    assert [q.number for q in pq.QUESTIONS if q.test] == [13, 14, 18, 25, 28, 30]
    assert all(q.facets[0].startswith("9.") for q in pq.QUESTIONS if q.optional)
    assert [q.qid for q in pq.questions_of("retest")] == ["q13", "q14", "q18", "q25", "q28", "q30"]


def test_drafts_are_trimmed_validated_and_kept(settings: Settings) -> None:
    store = PersonaStore(":memory:")
    assert pq.load_round(store, "initial").status == "empty"
    state = pq.save_draft(store, "initial", {"q01": "  我负责运营  ", "q02": "   "})
    assert state.status == "draft" and state.answers == {"q01": "我负责运营"}
    assert pq.load_round(store, "initial").answers == {"q01": "我负责运营"}
    with pytest.raises(ValueError, match="不属于这一轮"):
        pq.save_draft(store, "retest", {"q01": "x"})
    with pytest.raises(ValueError, match="不能超过"):
        pq.save_draft(store, "initial", {"q01": "字" * (pq.MAX_ANSWER_CHARS + 1)})


def test_submit_imports_through_the_questionnaire_parser_and_replaces_the_previous_import(settings: Settings) -> None:
    store = PersonaStore(":memory:")
    with pytest.raises(ValueError, match="还没有回答任何建档题目"):
        pq.submit_initial(store, settings, {"q13": "首付多少？"})  # test answers alone build nothing
    with pytest.raises(ValueError, match="请先提交第一轮"):
        pq.submit_retest(store, {"q13": "首付多少？"})
    first = pq.submit_initial(store, settings, {"q01": "我负责运营", "q13": "首付多少？", "q34": "六点起"})
    rows = {e.context.split("：")[0]: e for e in first.expressions}
    assert rows["问卷第 13 题"].held_out and not rows["问卷第 1 题"].held_out
    assert rows["问卷第 34 题"].facets_hint == ["9.2", "9.4"]
    assert first.source.declined_facets == ["9.1", "9.3", "9.5"]  # skipped optional questions
    assert [s.source_id for s in store.list_sources()] == [first.source.source_id]

    second = pq.submit_initial(store, settings, {"q01": "我负责运营和产品"})
    assert [s.source_id for s in store.list_sources()] == [second.source.source_id]
    state = pq.load_round(store, "initial")
    assert state.status == "submitted" and state.source_id == second.source.source_id and state.submitted_at

    retest = pq.submit_retest(store, {"q13": "先问首付", "q14": ""})
    assert retest.status == "submitted" and retest.answers == {"q13": "先问首付"}
    view = pq.round_view(store, "retest")
    assert view["retest_from"] and len(view["questions"]) == 6  # type: ignore[arg-type]
