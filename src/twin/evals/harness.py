"""Scenario-independent prediction execution, judging panels and legacy failure policies."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import NamedTuple, Protocol

from ..llm import LLM, Effort
from ..util import run_parallel
from .schema import Case, CaseInput, FailurePolicy, Judgement, JudgeStatus, PairingPolicy, Prediction, SystemSpec


class Judge(NamedTuple):
    """One member of the judging panel: its backend and the reasoning effort it judges with."""

    llm: LLM
    effort: Effort


class SystemUnderTest(Protocol):
    """A prepared system that receives only answer-free case input."""

    @property
    def spec(self) -> SystemSpec: ...

    def predict(self, case_input: CaseInput, *, as_of: date | None, repeat: int) -> Prediction: ...


class Rubric(Protocol):
    """An injected scoring rule; the panel owns applicability, exceptions and judge identity.

    The panel replaces the returned judge_id with its positional identity; rubrics do not
    know their judge's panel position. All other judgement identity fields must match the call.
    """

    @property
    def rubric_id(self) -> str: ...

    @property
    def rubric_version(self) -> str: ...

    def applies(self, case: Case, prediction: Prediction) -> bool: ...

    def __call__(self, judge: Judge, case: Case, prediction: Prediction, against: Prediction | None) -> Judgement: ...


class PredictionFailure(NamedTuple):
    """A failed matrix cell, never represented as a fabricated prediction."""

    system_id: str
    case_id: str
    repeat: int
    reason: str
    error: Exception | None = None


class PredictionRun(NamedTuple):
    """Successful predictions and failures, each retaining matrix order."""

    predictions: tuple[Prediction, ...]
    failures: tuple[PredictionFailure, ...]


class _PredictionJob(NamedTuple):
    system: SystemUnderTest
    case_input: CaseInput
    as_of: date | None
    repeat: int


class _JudgementJob(NamedTuple):
    case: Case
    prediction: Prediction
    judge: Judge
    judge_id: str
    rubric: Rubric
    against: Prediction | None


type ScoreKey = tuple[str, str, str | None]


def _error(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def run_predictions(
    cases: Sequence[Case],
    systems: Sequence[SystemUnderTest],
    repeats: int,
    as_of: Callable[[Case], date | None],
    max_workers: int,
) -> PredictionRun:
    """Run system × case × repeat, with zero-based repeats and deterministic result order.

    Compute the scenario's horizon once per case before any system call. Only CaseInput,
    the horizon and repeat reach the system; exceptions and misidentified outputs become failures.
    """
    if repeats < 1:
        raise ValueError("repeats must be positive")
    horizons = [as_of(case) for case in cases]
    jobs = [
        _PredictionJob(system, case.input, horizon, repeat)
        for system in systems
        for case, horizon in zip(cases, horizons, strict=True)
        for repeat in range(repeats)
    ]

    def predict(job: _PredictionJob) -> Prediction:
        result = job.system.predict(job.case_input, as_of=job.as_of, repeat=job.repeat)
        expected = (job.case_input.case_id, job.system.spec.system_id, job.case_input.mode, job.repeat)
        if (result.case_id, result.system_id, result.mode, result.repeat) != expected:
            raise ValueError("prediction identity does not match its matrix cell")
        if result.payload.kind != job.case_input.payload.kind:
            raise ValueError("prediction payload does not match its scenario")
        return result

    predictions: list[Prediction] = []
    failures: list[PredictionFailure] = []
    for job, result in zip(jobs, run_parallel(predict, jobs, max_workers), strict=True):
        if isinstance(result, Exception):
            failures.append(
                PredictionFailure(job.system.spec.system_id, job.case_input.case_id, job.repeat, _error(result), result)
            )
        else:
            predictions.append(result)
    return PredictionRun(tuple(predictions), tuple(failures))


def _judge_once(job: _JudgementJob) -> Judgement:
    prediction, judge, rubric = job.prediction, job.judge, job.rubric
    uncalled = Judgement(
        case_id=prediction.case_id,
        system_id=prediction.system_id,
        against_system_id=job.against.system_id if job.against is not None else None,
        repeat=prediction.repeat,
        judge_id=job.judge_id,
        rubric_id=rubric.rubric_id,
        rubric_version=rubric.rubric_version,
        status=JudgeStatus.NOT_CALLED,
    )
    try:
        if not rubric.applies(job.case, prediction):
            return uncalled
        result = rubric(judge, job.case, prediction, job.against)
        for field in ("case_id", "system_id", "against_system_id", "repeat", "rubric_id", "rubric_version"):
            if getattr(result, field) != getattr(uncalled, field):
                raise ValueError("judgement identity does not match its panel cell")
        return result.model_copy(update={"judge_id": job.judge_id})
    except Exception as error:
        return uncalled.model_copy(update={"status": JudgeStatus.FAILED, "error": _error(error)})


def run_judgements(
    cases: Sequence[Case],
    predictions: Sequence[Prediction],
    judges: Sequence[Judge],
    rubrics: Sequence[Rubric],
    max_workers: int,
    *,
    against: Callable[[Prediction], Prediction | None] | None = None,
) -> tuple[Judgement, ...]:
    """Record prediction × judge × rubric rows, including failures and not-called rows.

    An optional scenario selector supplies the comparison prediction. Case lookup and comparison
    identity are checked before any judging; comparisons must share case, mode and repeat.
    Selectors can return None for absolute rubrics. Filter predictions/rubrics or call again to
    score several comparisons. Row order follows supplied sequences, independent of worker count.
    The panel assigns j{index}:{llm.name} judge IDs using zero-based panel positions, replacing
    rubric-supplied IDs. Members sharing a model name remain distinct in every row and aggregate.
    """
    panel = [(judge, f"j{index}:{judge.llm.name}") for index, judge in enumerate(judges)]
    by_id = {case.input.case_id: case for case in cases}
    jobs: list[_JudgementJob] = []
    for prediction in predictions:
        case = by_id[prediction.case_id]
        if prediction.mode != case.input.mode or prediction.payload.kind != case.input.payload.kind:
            raise ValueError("prediction does not match its case")
        opponent = against(prediction) if against is not None else None
        if opponent is not None and (opponent.case_id, opponent.mode, opponent.repeat) != (
            prediction.case_id,
            prediction.mode,
            prediction.repeat,
        ):
            raise ValueError("comparison must share case, mode and repeat")
        jobs.extend(
            _JudgementJob(case, prediction, judge, judge_id, rubric, opponent)
            for judge, judge_id in panel
            for rubric in rubrics
        )
    outcomes = run_parallel(_judge_once, jobs, max_workers)
    rows: list[Judgement] = []
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            raise outcome
        rows.append(outcome)
    return tuple(rows)


def aggregate_scores(judgements: Sequence[Judgement], failure_policy: FailurePolicy) -> dict[ScoreKey, float | None]:
    """Aggregate one metric's panel scores by judge, then repeat, never pooling repeats.

    ALL_JUDGES_REQUIRED means any failed judge invalidates the
    case/system answer (including any of its repeats). MEAN_OF_SUCCESSFUL computes
    average successful judges within each repeat, then
    average successful repeats. Failed, not-called and score-less rows never contribute zero.
    Keys with no usable score remain None. Call separately for distinct metrics/rubrics;
    multiple rows for one panel-member judge_id within a repeat receive equal weight within
    that member. Model names alone do not identify panel members.
    """
    groups: dict[ScoreKey, dict[int, dict[str, list[float]]]] = {}
    failed: set[ScoreKey] = set()
    for row in judgements:
        key = (row.case_id, row.system_id, row.against_system_id)
        repeats = groups.setdefault(key, {})
        if row.status is JudgeStatus.FAILED:
            failed.add(key)
        elif row.status is JudgeStatus.OK and row.score is not None:
            repeats.setdefault(row.repeat, {}).setdefault(row.judge_id, []).append(row.score)
    scores: dict[ScoreKey, float | None] = {}
    for key, repeats in groups.items():
        if failure_policy is FailurePolicy.ALL_JUDGES_REQUIRED and key in failed:
            scores[key] = None
            continue
        repeat_scores: list[float] = []
        for panel in repeats.values():
            judge_scores = [sum(values) / len(values) for values in panel.values()]
            repeat_scores.append(sum(judge_scores) / len(judge_scores))
        scores[key] = sum(repeat_scores) / len(repeat_scores) if repeat_scores else None
    return scores


def paired_case_ids(
    scores: Mapping[ScoreKey, float | None],
    systems: Sequence[str],
    policy: PairingPolicy,
    control: str | None = None,
) -> dict[str, tuple[str, ...]]:
    """Return sorted absolute-score case IDs for each requested system.

    ALL_SYSTEMS_INTERSECTION gives every system the same common cases.
    PER_CONTROL_INTERSECTION intersects each system independently with the required control,
    as biography's content comparison does; the control need not be in systems. Relative
    scores (against_system_id is not None) are already paired and are not absolute scores.
    """
    if policy is PairingPolicy.PER_CONTROL_INTERSECTION and control is None:
        raise ValueError("per-control pairing requires a control")

    def available(system: str) -> set[str]:
        return {
            case_id
            for (case_id, system_id, against_id), score in scores.items()
            if system_id == system and against_id is None and score is not None
        }

    completed = {system: available(system) for system in systems}
    if policy is PairingPolicy.ALL_SYSTEMS_INTERSECTION:
        common = set.intersection(*completed.values()) if completed else set()
        return {system: tuple(sorted(common)) for system in systems}
    assert control is not None
    reference = available(control)
    return {system: tuple(sorted(case_ids & reference)) for system, case_ids in completed.items()}
