"""Development regression cases stay isolated from validation and final evaluation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from twin.evals.schema import (
    BiographyExpected,
    BiographyInput,
    Case,
    CaseInput,
    FailurePolicy,
    PairingPolicy,
    Purpose,
    Report,
    Scenario,
    Split,
)


def _case(purpose: Purpose, split: Split = Split.DEV, case_id: str = "case-1") -> Case:
    return Case(
        input=CaseInput(
            case_id=case_id,
            scenario=Scenario.BIOGRAPHY,
            mode="named",
            payload=BiographyInput(id=case_id, type="stance", prompt="Answer-free question"),
        ),
        expected=BiographyExpected(gold="Human-approved answer"),
        split=split,
        purpose=purpose,
        group_id="source-1",
        date=None,
    )


def _report(purpose: Purpose, cases: tuple[Case, ...] = ()) -> Report:
    return Report(
        scenario=cases[0].input.scenario if cases else Scenario.BIOGRAPHY,
        purpose=purpose,
        systems=(),
        judges=(),
        failure_policy=FailurePolicy.ALL_JUDGES_REQUIRED,
        pairing_policy=PairingPolicy.ALL_SYSTEMS_INTERSECTION,
        cases=cases,
    )


@pytest.mark.parametrize("purpose", list(Purpose))
@pytest.mark.parametrize("split", list(Split))
def test_case_purpose_split_contract(purpose: Purpose, split: Split) -> None:
    if purpose is Purpose.DEVELOPMENT_REGRESSION and split is not Split.DEV:
        with pytest.raises(
            ValidationError, match=f"case case-1: development_regression purpose requires dev split.*{split}"
        ):
            _case(purpose, split)
    else:
        case = _case(purpose, split)
        assert Case.model_validate_json(case.model_dump_json()) == case


@pytest.mark.parametrize("report_purpose", list(Purpose))
@pytest.mark.parametrize("case_purpose", list(Purpose))
def test_report_accepts_only_matching_case_purpose(report_purpose: Purpose, case_purpose: Purpose) -> None:
    case = _case(case_purpose)
    if report_purpose is case_purpose:
        report = _report(report_purpose, (case,))
        assert Report.model_validate_json(report.model_dump_json()) == report
    else:
        with pytest.raises(
            ValidationError, match=f"{report_purpose} report accepts only {report_purpose} cases.*case-1"
        ):
            _report(report_purpose, (case,))


@pytest.mark.parametrize("purpose", list(Purpose))
def test_empty_report_is_valid(purpose: Purpose) -> None:
    assert _report(purpose).cases == ()


def test_report_error_names_first_few_incompatible_cases() -> None:
    cases = (
        _case(Purpose.FINAL_EVAL, case_id="accepted"),
        *(_case(Purpose.DEVELOPMENT_REGRESSION, case_id=f"development-{i}") for i in range(7)),
    )
    with pytest.raises(ValidationError) as error:
        _report(Purpose.FINAL_EVAL, cases)
    message = error.value.errors()[0]["msg"]
    assert "accepted" not in message
    for i in range(5):
        assert f"development-{i}" in message
    assert "development-5" not in message
    assert "and 2 more" in message
