"""Entirely invented data; no downloaded conversations or credentials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.evals import extraction as ex
from twin.evals.harness import Judge
from twin.llm import FakeLLM, LLMError, LLMInvalidOutput
from twin.persona.profile import ExtractDraft

EVIDENCE = "By the way, I keep three fictional cobalt kites in my garage."
OTHER = "Can you suggest a name for a kite club?"


def dataset(tmp_path: Path) -> Path:
    path = tmp_path / "lme.json"
    path.write_text(
        json.dumps(
            [
                {
                    "question_id": "q1",
                    "question_type": "single-session-user",
                    "question": "How many cobalt kites do I keep?",
                    "answer": "three",
                    "answer_session_ids": ["s1"],
                    "haystack_session_ids": ["s1"],
                    "haystack_dates": ["2024/01/01 (Mon) 09:00"],
                    "haystack_sessions": [
                        [
                            {"role": "user", "content": OTHER},
                            {"role": "assistant", "content": "Sky Riders."},
                            {"role": "user", "content": EVIDENCE, "has_answer": True},
                            {"role": "assistant", "content": "Nice collection."},
                        ]
                    ],
                }
            ]
        )
    )
    return path


def cases_file(tmp_path: Path) -> Path:
    path = tmp_path / "cases.jsonl"
    row = {
        "question_id": "q1",
        "session_id": "s1",
        "evidence_turns": [2],
        "question": "How many cobalt kites do I keep?",
        "answer": "three",
        "key_fact": "车库里放着三只钴蓝风筝",
        "tags": ["single-session-user", "self"],
    }
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n")
    return path


def extractor(items: list[dict[str, Any]] | Exception) -> FakeLLM:
    def handle(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        assert schema is ExtractDraft
        if isinstance(items, Exception):
            raise items
        return {"items": items}

    return FakeLLM(handle)


def judge(verdict: dict[str, Any] | Exception) -> list[tuple[str, Judge]]:
    def handle(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        assert schema is ex.ExtractVerdict and "车库里放着三只钴蓝风筝" in user
        if isinstance(verdict, Exception):
            raise verdict
        return verdict

    return [("j0:fake", Judge(FakeLLM(handle), "medium"))]


def kite(n: int, quote: str) -> dict[str, Any]:
    return {"facet_id": "9.1", "statement": "收藏三只钴蓝风筝", "quotes": [{"n": n, "quote": quote}]}


def run(tmp_path: Path, llm: FakeLLM, judges: list[tuple[str, Judge]], reps: int = 1) -> dict[str, Any]:
    cases = ex.load_cases(cases_file(tmp_path))
    return ex.run_eval(
        Settings(pseudonymize_others=False),
        llm,
        judges,
        cases,
        ex.load_sessions(dataset(tmp_path), cases),
        tmp_path / "out",
        reps=reps,
        workers=1,
    )


def rows(tmp_path: Path, name: str = "results.jsonl") -> list[dict[str, Any]]:
    path = tmp_path / "out" / "baseline" / name
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def test_chunk_is_cut_through_production_and_finds_the_evidence_entry(tmp_path: Path) -> None:
    case = ex.load_cases(cases_file(tmp_path))[0]
    cut = ex.cut_chunk(case, ex.load_sessions(dataset(tmp_path), [case])["s1"], Settings(pseudonymize_others=False))
    assert [e.text for e in cut.chunk.entries] == [OTHER, EVIDENCE]  # assistant turns never reach extraction
    assert cut.evidence_n == 2 and cut.chunk.entries[1].expression_id == cut.evidence_id


def test_a_kept_conclusion_the_judge_matches_is_recall(tmp_path: Path) -> None:
    verdict = {
        "kept_match": [1],
        "raw_match": [1],
        "match_reason": "1",
        "kept": [{"i": 1, "supported": True, "reason": ""}],
    }
    run(tmp_path, extractor([kite(2, "three fictional cobalt kites")]), judge(verdict))
    [row] = rows(tmp_path)
    assert row["grade"] == {"recall": 1.0, "recall_raw": 1.0, "grounded": 1.0}
    assert row["rep"] == 0 and row["kept"] == 1 and row["dropped"] == 0
    assert (tmp_path / "out" / "baseline" / "traces" / "q1.s1_rep0.json").is_file()


def test_recall_does_not_depend_on_which_entry_is_quoted_but_grounding_does(tmp_path: Path) -> None:
    verdict = {
        "kept_match": [1],
        "raw_match": [1],
        "match_reason": "1",
        "kept": [{"i": 1, "supported": False, "reason": "x"}],
    }
    run(tmp_path, extractor([kite(1, "a name for a kite club")]), judge(verdict))
    [row] = rows(tmp_path)
    assert row["grade"] == {"recall": 1.0, "recall_raw": 1.0, "grounded": 0.0}


def test_a_conclusion_dropped_for_its_quote_counts_only_toward_raw_recall(tmp_path: Path) -> None:
    verdict = {"kept_match": [], "raw_match": [1], "match_reason": "", "kept": []}
    run(tmp_path, extractor([kite(2, "four invented kites")]), judge(verdict))
    [row] = rows(tmp_path)
    assert row["grade"] == {"recall": 0.0, "recall_raw": 1.0, "grounded": None}
    assert row["dropped"] == 1 and row["meta"]["stats"]["quotes_unmatched"] == 1


def test_an_extraction_the_model_breaks_is_scored_as_missed_not_an_error(tmp_path: Path) -> None:
    verdict = {"kept_match": [], "raw_match": [], "match_reason": "", "kept": []}
    run(tmp_path, extractor(LLMInvalidOutput("bad json")), judge(verdict))
    [row] = rows(tmp_path)
    assert row["grade"]["recall"] == 0.0 and row["meta"]["failure"] == "LLMInvalidOutput"
    assert rows(tmp_path, "errors.jsonl") == []


def test_judge_and_transport_failures_go_to_errors_and_are_retried_on_resume(tmp_path: Path) -> None:
    summary = run(tmp_path, extractor([kite(2, "three fictional cobalt kites")]), judge(LLMError("down")))
    assert rows(tmp_path) == [] and summary["errors"] == 1
    assert rows(tmp_path, "errors.jsonl")[0]["failure_class"] == "judge_error"
    run(tmp_path, extractor(LLMError("proxy down")), judge(LLMError("unused")))
    assert [e["failure_class"] for e in rows(tmp_path, "errors.jsonl")] == ["judge_error", "extract_error"]

    verdict = {
        "kept_match": [1],
        "raw_match": [1],
        "match_reason": "",
        "kept": [{"i": 1, "supported": True, "reason": ""}],
    }
    summary = run(tmp_path, extractor([kite(2, "three fictional cobalt kites")]), judge(verdict), reps=2)
    assert len(rows(tmp_path)) == 2 and summary["errors"] == 0 and summary["recall"]["mean"] == 1.0
    summary = run(tmp_path, extractor(LLMError("must not run")), judge(LLMError("must not run")), reps=2)
    assert len(rows(tmp_path)) == 2  # every (case, rep) is done, so resume calls nothing


def test_a_judge_that_skips_a_kept_conclusion_fails_the_attempt(tmp_path: Path) -> None:
    verdict = {"kept_match": [1], "raw_match": [1], "match_reason": "", "kept": []}
    run(tmp_path, extractor([kite(2, "three fictional cobalt kites")]), judge(verdict))
    assert rows(tmp_path) == [] and rows(tmp_path, "errors.jsonl")[0]["failure_class"] == "judge_error"


def test_harness_must_be_approved_and_reapproved_after_a_change(tmp_path: Path) -> None:
    cases = cases_file(tmp_path)
    with pytest.raises(ex.HarnessChanged):
        ex.check_harness(tmp_path, cases, approve=False)
    ex.check_harness(tmp_path, cases, approve=True)
    ex.check_harness(tmp_path, cases, approve=False)
    cases.write_text(cases.read_text().replace("三只", "四只"))
    with pytest.raises(ex.HarnessChanged):
        ex.check_harness(tmp_path, cases, approve=False)


def test_served_model_names_match_across_proxy_prefixes_and_snapshots() -> None:
    assert ex.same_model("codex/gpt-6-luna", "gpt-6-luna")
    assert ex.same_model("codex/gpt-6-luna", "gpt-6-luna-2026-09-01")
    assert not ex.same_model("codex/gpt-6-luna", "gpt-6.1-sol")
