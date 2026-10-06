from __future__ import annotations

import pytest

from twin.config import Settings
from twin.persona import questionnaire as pq
from twin.persona.dimensions import FACET_BY_ID, FACETS
from twin.persona.store import PersonaStore


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="张三")


def test_question_bank_is_optional_and_covers_nine_topics() -> None:
    assert len(pq.QUESTIONS) == 20 and len({q.qid for q in pq.QUESTIONS}) == 20
    assert {f for q in pq.QUESTIONS for f in q.facets} == {f.facet_id for f in FACETS}
    assert all(f in FACET_BY_ID for q in pq.QUESTIONS for f in q.facets)
    assert {q.section for q in pq.QUESTIONS} == {
        "经历与身份",
        "看重什么",
        "怎么做决定",
        "怎么思考",
        "擅长什么",
        "说话方式",
        "和人相处",
        "最近在关注",
        "生活与喜好",
    }
    assert all(q.optional for q in pq.QUESTIONS)
    assert not any(word in q.text for q in pq.QUESTIONS for word in ("汇报", "下属", "预算", "考核", "授权", "投不投"))


def test_drafts_are_trimmed_validated_and_kept(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        assert pq.load_round(store, "initial").status == "empty"
        state = pq.save_draft(store, "initial", {"q01": "  住在成都  ", "q02": "   "})
        assert state.status == "draft" and state.answers == {"q01": "住在成都"}
        assert pq.load_round(store, "initial").answers == state.answers
        with pytest.raises(ValueError, match="没有这些题目"):
            pq.save_draft(store, "initial", {"q99": "x"})
        with pytest.raises(ValueError, match="不能超过"):
            pq.save_draft(store, "initial", {"q01": "字" * (pq.MAX_ANSWER_CHARS + 1)})


def test_submit_imports_all_answers_and_replaces_previous_import(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        with pytest.raises(ValueError, match="还没有回答任何问题"):
            pq.submit_initial(store, settings, {})
        first = pq.submit_initial(store, settings, {"q01": "住在成都", "q13": "今天想歇歇", "q20": "六点起"})
        assert [e.text for e in first.expressions] == ["住在成都", "今天想歇歇", "六点起"]
        assert first.expressions[-1].facets_hint == ["9.2", "9.3", "9.4"]
        assert {"9.1", "9.5"} <= set(first.source.declined_facets)
        second = pq.submit_initial(store, settings, {"q01": "住在重庆"})
        assert [s.source_id for s in store.list_sources()] == [second.source.source_id]
        state = pq.load_round(store, "initial")
        assert state.status == "submitted" and state.source_id == second.source.source_id and state.submitted_at
        assert "retest_from" not in pq.round_view(store, "initial")


def test_old_draft_answers_are_not_shown_under_new_questions() -> None:
    with PersonaStore(":memory:") as store:
        store.set_meta(
            "questionnaire:initial",
            pq.RoundState(
                round="initial",
                version="q-v0",
                answers={"q01": "旧回答"},
                source_id="old-source",
            ).model_dump_json(),
        )
        state = pq.load_round(store, "initial")
        assert state.answers == {} and state.version == pq.QUESTIONNAIRE_VERSION
        assert state.source_id == "old-source"
