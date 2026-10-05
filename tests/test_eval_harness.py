"""Exercise the generic executor with local, non-LLM systems and rubrics."""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from threading import Lock

import pytest
from pydantic import BaseModel

from twin.evals.harness import (
    Judge,
    PredictionFailure,
    PredictionRun,
    Rubric,
    ScoreKey,
    SystemUnderTest,
    aggregate_scores,
    paired_case_ids,
    run_judgements,
    run_predictions,
)
from twin.evals.schema import (
    BiographyExpected,
    BiographyInput,
    BiographyOutput,
    Case,
    CaseInput,
    FailurePolicy,
    Judgement,
    JudgeStatus,
    PairingPolicy,
    Prediction,
    Purpose,
    Scenario,
    Split,
    SystemSpec,
)
from twin.llm import Effort


class UnusedLLM:
    """Supply a judge identity while forbidding backend calls."""

    def __init__(self, name: str) -> None:
        self.name = name

    def structured[T: BaseModel](
        self,
        *,
        system: str,
        user: str,
        schema: type[T],
        effort: Effort = "medium",
        max_tokens: int | None = None,
    ) -> T:
        raise AssertionError("the test must not call an LLM")


def make_case(case_id: str, horizon: date | None = None) -> Case:
    return Case(
        input=CaseInput(
            case_id=case_id,
            scenario=Scenario.BIOGRAPHY,
            mode="named",
            payload=BiographyInput(id=case_id, type="decision", prompt="What would you do?"),
        ),
        expected=BiographyExpected(gold="SECRET ANSWER", key_points=["SECRET SCORING POINT"]),
        split=Split.DEV,
        purpose=Purpose.DEVELOPMENT_REGRESSION,
        group_id=case_id,
        date=horizon,
    )


@dataclass
class FakeSystem:
    system_id: str
    failures: set[tuple[str, int]] = field(default_factory=set)
    calls: list[tuple[CaseInput, date | None, int]] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)
    wrong_identity: bool = False

    @property
    def spec(self) -> SystemSpec:
        return SystemSpec(
            system_id=self.system_id,
            label=self.system_id,
            supports_as_of=True,
            supports_abstain=False,
            supports_confidence=False,
        )

    def predict(self, case_input: CaseInput, *, as_of: date | None, repeat: int) -> Prediction:
        assert type(case_input) is CaseInput
        assert not hasattr(case_input, "expected")
        assert "SECRET" not in case_input.model_dump_json()
        with self.lock:
            self.calls.append((case_input, as_of, repeat))
        time.sleep(0.001 * (3 - repeat))
        if (case_input.case_id, repeat) in self.failures:
            raise RuntimeError("system unavailable")
        text = f"{self.system_id}/{case_input.case_id}/{repeat}"
        return Prediction(
            case_id="wrong" if self.wrong_identity else case_input.case_id,
            system_id=self.system_id,
            mode=case_input.mode,
            repeat=repeat,
            text=text,
            payload=BiographyOutput(reply=text),
        )


@dataclass
class FakeRubric:
    rubric_id: str = "content"
    rubric_version: str = "1"
    scores: Mapping[tuple[str, int], float] = field(default_factory=dict)
    failures: set[tuple[str, int]] = field(default_factory=set)
    excluded_cases: set[str] = field(default_factory=set)
    applies_failure: bool = False
    wrong_identity: bool = False
    calls: list[tuple[str, str, int, str | None]] = field(default_factory=list)
    lock: Lock = field(default_factory=Lock)

    def applies(self, case: Case, prediction: Prediction) -> bool:
        if self.applies_failure:
            raise ValueError("applicability failed")
        return case.input.case_id not in self.excluded_cases

    def __call__(self, judge: Judge, case: Case, prediction: Prediction, against: Prediction | None) -> Judgement:
        assert case.expected == BiographyExpected(gold="SECRET ANSWER", key_points=["SECRET SCORING POINT"])
        against_id = against.system_id if against is not None else None
        with self.lock:
            self.calls.append((prediction.case_id, judge.llm.name, prediction.repeat, against_id))
        time.sleep(0.001 * (3 - prediction.repeat))
        if (judge.llm.name, prediction.repeat) in self.failures:
            raise RuntimeError("judge unavailable")
        return Judgement(
            case_id="wrong" if self.wrong_identity else prediction.case_id,
            system_id=prediction.system_id,
            against_system_id=against_id,
            repeat=prediction.repeat,
            judge_id=judge.llm.name,
            rubric_id=self.rubric_id,
            rubric_version=self.rubric_version,
            status=JudgeStatus.OK,
            score=self.scores.get((judge.llm.name, prediction.repeat), 1.0),
            verdict="same",
            reason="Local judgement",
        )


@dataclass
class EffortRubric(FakeRubric):
    """Score panel members differently by effort, with an optional partial-panel failure."""

    fail_high: bool = False

    def __call__(self, judge: Judge, case: Case, prediction: Prediction, against: Prediction | None) -> Judgement:
        result = super().__call__(judge, case, prediction, against)
        if self.fail_high and judge.effort == "high":
            raise RuntimeError("high-effort judge unavailable")
        return result.model_copy(update={"score": 1.0 if judge.effort == "low" else 0.0})


def panel() -> list[Judge]:
    return [Judge(UnusedLLM("first"), "low"), Judge(UnusedLLM("second"), "high")]


@pytest.mark.parametrize("max_workers", [1, 4])
def test_prediction_matrix_and_answer_free_horizons(max_workers: int) -> None:
    cases = [make_case("b", date(2020, 1, 2)), make_case("a")]
    systems = [FakeSystem("two"), FakeSystem("one")]
    sut_protocol: SystemUnderTest = systems[0]
    assert sut_protocol.spec.system_id == "two"
    horizons: list[str] = []

    def horizon(case: Case) -> date | None:
        horizons.append(case.input.case_id)
        return case.date

    result = run_predictions(cases, systems, 3, horizon, max_workers)
    assert not result.failures
    assert horizons == ["b", "a"]
    assert [(p.system_id, p.case_id, p.repeat) for p in result.predictions] == [
        (system, case, repeat) for system in ("two", "one") for case in ("b", "a") for repeat in range(3)
    ]
    for system in systems:
        assert len(system.calls) == 6
        assert sorted((c.case_id, str(as_of), repeat) for c, as_of, repeat in system.calls) == sorted(
            (case.input.case_id, str(case.date), repeat) for case in cases for repeat in range(3)
        )


def test_system_failure_is_not_a_prediction_and_is_deterministic() -> None:
    cases = [make_case("b"), make_case("a")]

    def run(workers: int) -> PredictionRun:
        return run_predictions(cases, [FakeSystem("one", failures={("b", 1), ("a", 0)})], 2, lambda c: c.date, workers)

    serial, parallel = run(1), run(4)
    assert serial.predictions == parallel.predictions
    for result in (serial, parallel):
        assert [(p.case_id, p.repeat) for p in result.predictions] == [("b", 0), ("a", 1)]
        assert tuple(failure._replace(error=None) for failure in result.failures) == (
            PredictionFailure("one", "b", 1, "RuntimeError: system unavailable"),
            PredictionFailure("one", "a", 0, "RuntimeError: system unavailable"),
        )
        assert all(isinstance(failure.error, RuntimeError) for failure in result.failures)


@pytest.mark.parametrize("max_workers", [1, 4])
def test_prediction_failure_retains_original_exception(max_workers: int) -> None:
    error = RuntimeError("original error")

    class FailingSystem(FakeSystem):
        def predict(self, case_input: CaseInput, *, as_of: date | None, repeat: int) -> Prediction:
            raise error

    result = run_predictions([make_case("a")], [FailingSystem("one")], 1, lambda c: None, max_workers)
    assert result.predictions == ()
    assert result.failures[0].error is error
    assert result.failures[0].reason == "RuntimeError: original error"
    assert PredictionFailure("one", "a", 0, "diagnostic").error is None


def test_misidentified_system_output_is_recorded_as_failure() -> None:
    result = run_predictions([make_case("a")], [FakeSystem("one", wrong_identity=True)], 1, lambda c: None, 1)
    assert not result.predictions
    assert result.failures[0].reason == "ValueError: prediction identity does not match its matrix cell"
    assert isinstance(result.failures[0].error, ValueError)


@pytest.mark.parametrize("repeats", [0, -1])
def test_invalid_repeats_make_no_system_calls(repeats: int) -> None:
    system = FakeSystem("one")
    with pytest.raises(ValueError, match="positive"):
        run_predictions([make_case("a")], [system], repeats, lambda c: None, 4)
    assert not system.calls


@pytest.mark.parametrize("max_workers", [1, 4])
def test_judgement_matrix_order_and_uncalled_rows(max_workers: int) -> None:
    cases = [make_case("b"), make_case("a")]
    predictions = run_predictions(cases, [FakeSystem("one"), FakeSystem("two")], 2, lambda c: None, 4).predictions
    active = FakeRubric()
    inactive = FakeRubric(rubric_id="optional", excluded_cases={"a", "b"})
    rubric_protocol: Rubric = active
    assert rubric_protocol.rubric_id == "content"
    rows = run_judgements(cases, predictions, panel(), [active, inactive], max_workers)
    assert len(rows) == 32
    assert len(active.calls) == 16
    assert not inactive.calls
    assert [(r.system_id, r.case_id, r.repeat, r.judge_id, r.rubric_id) for r in rows] == [
        (p.system_id, p.case_id, p.repeat, judge, rubric)
        for p in predictions
        for judge in ("j0:first", "j1:second")
        for rubric in ("content", "optional")
    ]
    assert all(r.status is JudgeStatus.OK and r.score == 1.0 for r in rows if r.rubric_id == "content")
    assert all(
        r.status is JudgeStatus.NOT_CALLED and r.score is None and r.error is None
        for r in rows
        if r.rubric_id == "optional"
    )
    scores = aggregate_scores(rows, FailurePolicy.ALL_JUDGES_REQUIRED)
    assert set(scores.values()) == {1.0}


def test_same_model_panel_members_have_distinct_ids_and_equal_aggregate_weight() -> None:
    cases = [make_case("a")]
    predictions = run_predictions(cases, [FakeSystem("one")], 1, lambda c: None, 1).predictions
    backend = UnusedLLM("shared")
    judges = [Judge(backend, "low"), Judge(backend, "high")]

    def run(workers: int) -> tuple[Judgement, ...]:
        return run_judgements(
            cases,
            predictions,
            judges,
            [EffortRubric(), EffortRubric(fail_high=True), FakeRubric(excluded_cases={"a"})],
            workers,
        )

    rows = run(1)
    assert rows == run(4)
    assert [row.judge_id for row in rows] == ["j0:shared"] * 3 + ["j1:shared"] * 3
    assert [row.status for row in rows] == [
        JudgeStatus.OK,
        JudgeStatus.OK,
        JudgeStatus.NOT_CALLED,
        JudgeStatus.OK,
        JudgeStatus.FAILED,
        JudgeStatus.NOT_CALLED,
    ]
    assert [row.score for row in rows] == [1.0, 1.0, None, 0.0, None, None]
    assert rows[4].error == "RuntimeError: high-effort judge unavailable"
    assert aggregate_scores(rows, FailurePolicy.MEAN_OF_SUCCESSFUL) == {("a", "one", None): 0.5}
    assert aggregate_scores(rows, FailurePolicy.ALL_JUDGES_REQUIRED) == {("a", "one", None): None}


def test_judge_failure_policies_and_repeat_denominators_are_deterministic() -> None:
    cases = [make_case("a")]
    predictions = run_predictions(cases, [FakeSystem("one")], 3, lambda c: None, 1).predictions

    def run(workers: int) -> tuple[Judgement, ...]:
        rubric = FakeRubric(
            scores={("first", 0): 1.0, ("second", 0): 0.0, ("first", 1): 1.0},
            failures={("second", 1), ("first", 2), ("second", 2)},
        )
        return run_judgements(cases, predictions, panel(), [rubric], workers)

    rows = run(1)
    assert rows == run(4)
    failed = [row for row in rows if row.status is JudgeStatus.FAILED]
    assert len(failed) == 3
    assert all(row.score is None and row.error == "RuntimeError: judge unavailable" for row in failed)
    assert aggregate_scores(rows, FailurePolicy.ALL_JUDGES_REQUIRED) == {("a", "one", None): None}
    assert aggregate_scores(rows, FailurePolicy.MEAN_OF_SUCCESSFUL) == {("a", "one", None): 0.75}
    for policy in FailurePolicy:
        assert aggregate_scores(failed, policy) == {("a", "one", None): None}


@pytest.mark.parametrize("applies_failure,wrong_identity", [(True, False), (False, True)])
def test_applicability_and_invalid_judgements_become_failed_rows(applies_failure: bool, wrong_identity: bool) -> None:
    cases = [make_case("a")]
    predictions = run_predictions(cases, [FakeSystem("one")], 1, lambda c: None, 1).predictions
    rubric = FakeRubric(applies_failure=applies_failure, wrong_identity=wrong_identity)
    rows = run_judgements(cases, predictions, panel(), [rubric], 4)
    assert all(row.case_id == "a" and row.status is JudgeStatus.FAILED and row.score is None for row in rows)
    assert all(row.error is not None and row.error.startswith("ValueError:") for row in rows)


def test_comparisons_match_case_and_repeat_and_keep_against_keys_separate() -> None:
    cases = [make_case("a")]
    predictions = run_predictions(cases, [FakeSystem("twin"), FakeSystem("rag")], 2, lambda c: None, 4).predictions
    primary = [p for p in predictions if p.system_id == "twin"]
    opponents = {p.repeat: p for p in predictions if p.system_id == "rag"}
    rubric = FakeRubric()
    absolute = run_judgements(cases, primary, panel(), [rubric], 1)
    relative = run_judgements(cases, primary, panel(), [rubric], 4, against=lambda p: opponents[p.repeat])
    assert all(row.against_system_id == "rag" for row in relative)
    assert aggregate_scores(absolute + relative, FailurePolicy.ALL_JUDGES_REQUIRED) == {
        ("a", "twin", None): 1.0,
        ("a", "twin", "rag"): 1.0,
    }
    calls_before = len(rubric.calls)
    with pytest.raises(ValueError, match="share case, mode and repeat"):
        run_judgements(cases, primary, panel(), [rubric], 4, against=lambda p: opponents[1])
    assert len(rubric.calls) == calls_before


def test_empty_and_uncalled_or_scoreless_aggregates() -> None:
    cases = [make_case("a")]
    assert not run_predictions([], [FakeSystem("one")], 1, lambda c: None, 4).predictions
    assert not run_judgements(cases, [], panel(), [FakeRubric()], 4)
    predictions = run_predictions(cases, [FakeSystem("one")], 1, lambda c: None, 1).predictions
    rows = run_judgements(cases, predictions, panel(), [FakeRubric(excluded_cases={"a"})], 1)
    scoreless = rows[0].model_copy(update={"status": JudgeStatus.OK})
    for policy in FailurePolicy:
        assert aggregate_scores([], policy) == {}
        assert aggregate_scores((*rows, scoreless), policy) == {("a", "one", None): None}


def test_pairing_policies_preserve_distinct_denominators() -> None:
    scores: dict[ScoreKey, float | None] = {
        ("b", "twin", None): 1.0,
        ("a", "twin", None): 0.0,
        ("c", "twin", None): 1.0,
        ("a", "rag", None): 1.0,
        ("b", "rag", None): 1.0,
        ("c", "rag", None): None,
        ("c", "generic", None): 1.0,
        ("a", "generic", None): 1.0,
        ("only-relative", "rag", "twin"): 1.0,
    }
    systems = ["rag", "generic", "twin"]
    assert paired_case_ids(scores, systems, PairingPolicy.ALL_SYSTEMS_INTERSECTION) == {
        "rag": ("a",),
        "generic": ("a",),
        "twin": ("a",),
    }
    assert paired_case_ids(scores, ["rag", "generic"], PairingPolicy.PER_CONTROL_INTERSECTION, control="twin") == {
        "rag": ("a", "b"),
        "generic": ("a", "c"),
    }
    assert paired_case_ids(scores, ["rag", "missing"], PairingPolicy.ALL_SYSTEMS_INTERSECTION) == {
        "rag": (),
        "missing": (),
    }
    assert paired_case_ids(scores, [], PairingPolicy.ALL_SYSTEMS_INTERSECTION) == {}
    with pytest.raises(ValueError, match="requires a control"):
        paired_case_ids(scores, systems, PairingPolicy.PER_CONTROL_INTERSECTION)
