"""Shared evaluation contracts; no runtime, aggregation or compatibility conversion."""

from __future__ import annotations

import datetime as dt
from enum import StrEnum
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, SerializerFunctionWrapHandler, model_serializer, model_validator

SCHEMA_VERSION: Literal[2] = 2

type QuestionCategory = Literal["fact", "unanswerable", "style", "general", "update"]


class Scenario(StrEnum):
    PERSONAL = "personal"
    BIOGRAPHY = "biography"  # Read-only compatibility with archived v1 records.


class Split(StrEnum):
    DEV = "dev"
    VALIDATION = "validation"
    TEST = "test"


class Purpose(StrEnum):
    FINAL_EVAL = "final_eval"
    VALIDATION = "validation"
    DEVELOPMENT_REGRESSION = "development_regression"


class JudgeStatus(StrEnum):
    OK = "ok"
    FAILED = "failed"
    NOT_CALLED = "not_called"


class FailurePolicy(StrEnum):
    ALL_JUDGES_REQUIRED = "all_judges_required"
    MEAN_OF_SUCCESSFUL = "mean_of_successful"


class PairingPolicy(StrEnum):
    ALL_SYSTEMS_INTERSECTION = "all_systems_intersection"
    PER_CONTROL_INTERSECTION = "per_control_intersection"


class _Contract(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class QuestionInput(_Contract):
    """Answer-free question contract for personal evaluation."""

    kind: Literal["personal"] = "personal"
    id: str
    category: QuestionCategory
    prompt: str


class QuestionExpected(_Contract):
    kind: Literal["personal"] = "personal"
    answer: str | None = None
    evidence: str | list[str] | None = None
    source_group: str | None = None
    add_fact: str | None = None
    modified_fact: str | None = None
    modified_answer: str | None = None


class QuestionOutput(_Contract):
    kind: Literal["personal"] = "personal"
    reply: str


class BiographyInput(_Contract):
    """Legacy v1 payload, retained only for lossless archived-record reading."""

    kind: Literal["biography"] = "biography"
    id: str
    type: Literal["decision", "stance", "voice", "trap"]
    prompt: str


class CaseInput(_Contract):
    """The only case data exposed to a system under test."""

    case_id: str
    scenario: Scenario
    mode: str
    payload: QuestionInput | BiographyInput

    @model_validator(mode="after")
    def _check_scenario(self) -> Self:
        if self.scenario.value != self.payload.kind:
            raise ValueError("scenario must match payload kind")
        return self


class BiographyEvidence(_Contract):
    source: str
    quote: str


class BiographyExpected(_Contract):
    kind: Literal["biography"] = "biography"
    gold: str
    key_points: list[str] = Field(default_factory=list)
    evidence: list[BiographyEvidence] = Field(default_factory=list)


class Case(_Contract):
    input: CaseInput
    expected: QuestionExpected | BiographyExpected
    split: Split
    purpose: Purpose
    group_id: str
    date: dt.date | None
    facet_ids: tuple[str, ...] = ()
    taxonomy_version: str | None = None
    sources: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_expected(self) -> Self:
        if self.input.payload.kind != self.expected.kind:
            raise ValueError("expected kind must match input payload kind")
        return self

    @model_validator(mode="after")
    def _check_development_split(self) -> Self:
        if self.purpose is Purpose.DEVELOPMENT_REGRESSION and self.split is not Split.DEV:
            raise ValueError(
                f"case {self.input.case_id}: development_regression purpose requires dev split, got {self.split.value}"
            )
        return self


class SystemSpec(_Contract):
    """Public identity and capabilities, without endpoints or credentials."""

    system_id: str
    label: str
    fingerprint: str | None = None
    supports_as_of: bool
    supports_abstain: bool
    supports_confidence: bool
    knowledge_boundary: dt.date | None = None


class Citation(_Contract):
    ref_id: str
    reason: str


class BiographyOutput(_Contract):
    kind: Literal["biography"] = "biography"
    reply: str


class Prediction(_Contract):
    """Absent capabilities remain None; raw preserves the legacy system output."""

    case_id: str
    system_id: str
    mode: str
    repeat: int
    text: str
    confidence: float | None = None
    support: float | None = None
    abstain: bool | None = None
    abstain_reason: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    payload: QuestionOutput | BiographyOutput
    raw: dict[str, Any] = Field(default_factory=dict)


class QuestionMatch(_Contract):
    actual_index: int
    predicted_index: int | None
    reason: str


class Judgement(_Contract):
    """One judge call; verdict retains rubric-specific fields without reinterpretation."""

    case_id: str
    system_id: str
    against_system_id: str | None = None
    repeat: int
    judge_id: str
    rubric_id: str
    rubric_version: str
    status: JudgeStatus
    score: float | None = None
    verdict: str | bool | dict[str, Any] | None = None
    reason: str | None = None
    matches: list[QuestionMatch] = Field(default_factory=list)
    order_map: dict[str, str | int] | None = None
    error: str | None = None

    @model_validator(mode="after")
    def _check_score(self) -> Self:
        if self.status is not JudgeStatus.OK and self.score is not None:
            raise ValueError("failed or uncalled judgements must have score None")
        return self


class Report(_Contract):
    """Aggregate judge -> repeat -> case -> group, never treating calls as independent cases.

    Generic metrics/paired retain legacy metadata, case scores and statistical strategies;
    failure counts retain system/reason or answer/judge scopes, without inventing call rows.
    """

    schema_version: Literal[1, 2] = SCHEMA_VERSION
    method: Literal["v1", "v2"] | None = None
    scenario: Scenario
    purpose: Purpose
    systems: tuple[SystemSpec, ...]
    judges: tuple[str, ...]
    failure_policy: FailurePolicy
    pairing_policy: PairingPolicy
    built_until: dt.date | None = None
    cutoff: dt.date | None = None
    until: dt.date | None = None
    fingerprints: dict[str, str] = Field(default_factory=dict)
    cases: tuple[Case, ...] = ()
    predictions: tuple[Prediction, ...] = ()
    judgements: tuple[Judgement, ...] = ()
    metrics: dict[str, Any] = Field(default_factory=dict)
    paired: dict[str, Any] = Field(default_factory=dict)
    failures: dict[str, Any] = Field(default_factory=dict)
    skipped: dict[str, int] = Field(default_factory=dict)
    warnings: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def _serialize(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        result: dict[str, Any] = handler(self)
        if self.method is None:
            result.pop("method", None)
        return result

    @model_validator(mode="after")
    def _check_case_purposes(self) -> Self:
        incompatible = [case.input.case_id for case in self.cases if case.purpose is not self.purpose]
        if incompatible:
            shown = ", ".join(incompatible[:5])
            remainder = f" (and {len(incompatible) - 5} more)" if len(incompatible) > 5 else ""
            raise ValueError(
                f"{self.purpose.value} report accepts only {self.purpose.value} cases; "
                f"incompatible case ids: {shown}{remainder}"
            )
        return self
