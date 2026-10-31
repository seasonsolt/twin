"""危机识别评测 (P3.1) runs offline: each case is scored against its group, the guard's layers are counted, and the
sweep reads other thresholds from what was recorded."""

from __future__ import annotations

from typing import Any

import numpy as np
from pydantic import BaseModel

from twin.evals.crisis import CASES, KINDS, Record, run, would_stop
from twin.llm import FakeLLM
from twin.persona.crisis import EXAMPLES


class Close:
    """Every case's meaning is close to the crisis sentences, so the model's verdict decides what the words miss."""

    name = "close"
    cluster_threshold = 0.8

    def embed(self, texts: list[str]) -> Any:
        return np.ones((len(texts), 2))


def test_cases_are_their_own_and_none_is_a_guard_example() -> None:
    assert len({c.case_id for c in CASES}) == len(CASES)
    assert not [c.case_id for c in CASES if set(c.turns) & set(EXAMPLES)]
    assert {(c.group, c.kind) for c in CASES} == {(g, k) for g, kinds in KINDS.items() for k in kinds}


def test_the_eval_scores_each_case_by_its_group() -> None:
    stop = {c.turns[-1] for c in CASES if c.group == "stop"}

    def handle(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        return {"crisis": user.rsplit("\n", 1)[-1].split(". ", 1)[-1] in stop}

    records, summary = run(FakeLLM(handle), Close(), workers=2)
    assert len(records) == len(CASES) and summary["errors"] == 0
    # The model here is never wrong; what is stopped of the other group is stopped by the words alone.
    assert summary["recall"]["rate"] == 1.0 and summary["passed"]
    assert summary["false_blocked"] == sorted({r.case_id for r in records if r.group == "pass" and r.words})
    stopped = summary["recall"]["stopped"] + summary["false_block"]["stopped"]
    assert summary["by_layer"]["words"] + summary["by_layer"]["model"] == stopped
    assert summary["by_layer"]["words"] > 0 and summary["by_layer"]["close"] == 0
    assert all(r.similarity == 1.0 and r.model_says is (r.group == "stop") for r in records if not r.words)
    # Above every threshold here, so the sweep reads the same at each.
    assert {(row["recall"], row["false_block"]) for row in summary["sweep"]} == {(1.0, summary["false_block"]["rate"])}


def test_the_sweep_follows_the_words_then_closeness_then_the_model() -> None:
    def r(words: bool, similarity: float | None, says: bool | None) -> Record:
        return Record("c", "stop", "veiled", 0, words=words, similarity=similarity, model_says=says)

    assert would_stop(r(True, None, False), 0.9)
    assert not would_stop(r(False, 0.5, True), 0.6) and would_stop(r(False, 0.6, True), 0.6)
    assert not would_stop(r(False, 0.7, False), 0.6) and would_stop(r(False, 0.8, None), 0.6)
    assert not would_stop(r(False, 0.7, None), 0.6)  # the model down, and not close enough on its own
