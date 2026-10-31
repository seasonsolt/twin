"""继承人安全评测 (P2.9) runs offline with a fake model: the made-up will gives each heir what it says, the avoided
topic in its own words is stopped before any model, and the judges' verdicts and the markers are scored as the module
says."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.evals.harness import Judge
from twin.evals.heirs import CASES, FACT, HEIRS, Record, Verdict, run
from twin.llm import FakeLLM


class Twin(FakeLLM):
    """Answers every chat with everything it was shown, so whatever reaches the model shows in the reply."""

    def __init__(self) -> None:
        super().__init__(self.handle)

    def handle(self, system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ != "ChatDraft":
            return {}
        shown = "；".join(f.marker for f in FACT.values() if f.marker in system + user)
        meta = {"citations": [], "confidence": 0.9, "mode": "general", "asked": "事", "answered": True}
        return {"reply": f"我记得：{shown or '没什么'}", **meta}


def judge(answer: bool) -> Judge:
    return Judge(FakeLLM(lambda s, u, schema: {"yes": answer, "reason": "x"} if schema is Verdict else {}), "low")


def test_no_question_carries_a_marker_so_finding_one_means_the_fact_got_through() -> None:
    for case in CASES:
        for text in case.turns:
            assert not [f.marker for f in FACT.values() if f.marker in text], case.case_id


def test_every_case_has_its_own_id() -> None:
    assert len({case.case_id for case in CASES}) == len(CASES)


def test_the_eval_runs_every_case_and_scores_what_reached_the_model() -> None:
    records, summary = run(Twin(), HashingEmbedder(), Settings(), [("j0", judge(False))], workers=2)
    assert len(records) == len(CASES) and not any(r.error for r in records)
    # The will keeps each withheld fact from the model: nothing leaks, whatever the style.
    assert summary["leak"]["hits"] == 0 and summary["leak"]["shown"] == 0, [
        (r.case_id, r.turns[-1]) for r in records if r.outcome
    ]
    # The avoided topic in its own words is stopped before any model. Without them, and with no vectors to tell
    # (hashing), the fact reaches this twin, which does not keep to the prompt: it says it, and is not blocked.
    avoids = [r for r in records if r.group == "avoid"]
    assert all(r.hard_block == (r.style == "direct") for r in avoids), [(r.case_id, r.hard_block) for r in avoids]
    assert all(r.outcome is r.hard_block for r in avoids)
    assert summary["avoid"]["hard"] == summary["avoid"]["hits"] == len(HEIRS)
    # What the will gives is answered (its marker is in the reply).
    assert summary["answer"]["rate"] == 1.0
    assert set(summary["leak"]["by_heir"]) == {h.name for h in HEIRS}


def test_a_judge_that_fails_leaves_the_others_and_none_at_all_fails_the_case() -> None:
    def down(s: str, u: str, schema: type[BaseModel]) -> Any:
        raise RuntimeError("down")

    some = [c for c in CASES if c.group == "leak"][:2]
    records, _ = run(Twin(), HashingEmbedder(), Settings(), [("j0", judge(True)), ("j1", Judge(FakeLLM(down), "low"))],
                     cases=some)  # fmt: skip
    assert all(r.judges == {"j0": True} and r.reasons["j1"].startswith("error") and r.outcome for r in records)
    records, _ = run(Twin(), HashingEmbedder(), Settings(), [("j1", Judge(FakeLLM(down), "low"))], cases=some)
    assert all(r.error and r.outcome is None for r in records)


def test_a_judge_saying_a_fact_was_given_away_is_a_leak_and_an_avoided_topic_talked_about() -> None:
    leak = Record("c", "小满", "leak", "direct", "debt", 0, judges={"j0": False, "j1": True})
    talked = Record("c", "小满", "avoid", "rephrased", "teahouse", 0, judges={"j0": True})
    stopped = Record("c", "小满", "avoid", "direct", "teahouse", 0, hard_block=True)
    failed = Record("c", "小满", "leak", "direct", "debt", 0, error="LLMError")
    assert leak.outcome is True and talked.outcome is False and stopped.outcome is True and failed.outcome is None
