"""Generic personal question/answer evaluation contracts."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from twin.evals import schema
from twin.evals.schema import CaseInput, Judgement, JudgeStatus, QuestionExpected


def _input_data(kind: str = "personal") -> dict[str, Any]:
    return {
        "case_id": "case-1",
        "scenario": kind,
        "mode": "named",
        "payload": {"kind": kind, "id": "b1", "category": "fact", "prompt": "question"},
    }


@pytest.mark.parametrize("field", ["gold", "answer", "expected", "evidence", "key_points", "human_feedback"])
@pytest.mark.parametrize("nested", [False, True])
def test_input_forbids_answers(field: str, nested: bool) -> None:
    data = _input_data()
    (data["payload"] if nested else data)[field] = "secret answer"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CaseInput.model_validate(data)


def test_unsupported_payload() -> None:
    with pytest.raises(ValidationError):
        CaseInput.model_validate(_input_data("unsupported"))


def _round_trip[M: BaseModel](model: M) -> M:
    loaded = type(model).model_validate_json(model.model_dump_json())
    assert loaded == model
    assert loaded.model_dump(mode="json") == model.model_dump(mode="json")
    return loaded


@pytest.mark.parametrize("status", [JudgeStatus.FAILED, JudgeStatus.NOT_CALLED])
def test_unsuccessful_judgement_has_no_score(status: JudgeStatus) -> None:
    row = Judgement(
        case_id="b1",
        system_id="twin",
        repeat=1,
        judge_id="judge-2",
        rubric_id="content",
        rubric_version="1",
        status=status,
        error="ValueError: synthetic judge failure" if status is JudgeStatus.FAILED else None,
    )
    assert _round_trip(row).score is None
    with pytest.raises(ValidationError, match="must have score None"):
        Judgement.model_validate(row.model_dump() | {"score": 0.0})


def test_pairwise_voice_and_trap_verdicts_are_lossless() -> None:
    base: dict[str, Any] = {
        "case_id": "voice-00",
        "system_id": "twin",
        "against_system_id": "rag",
        "repeat": 0,
        "judge_id": "judge-1",
        "rubric_id": "voice",
        "rubric_version": "1",
        "status": "ok",
        "score": 0.5,
        "verdict": {"closer": "tie"},
        "reason": "核对语气与句式",
        "order_map": {"A": "rag", "B": "twin"},
    }
    voice = _round_trip(Judgement.model_validate(base))
    assert voice.against_system_id == "rag"
    trap = _round_trip(
        Judgement.model_validate(
            base
            | {
                "case_id": "trap-00",
                "rubric_id": "trap",
                "against_system_id": None,
                "order_map": None,
                "score": 1.0,
                "verdict": {"fabricated": False},
            }
        )
    )
    assert trap.verdict == {"fabricated": False}
    _round_trip(QuestionExpected(answer="gold", evidence="quote"))


def test_all_contract_models_are_frozen_and_forbid_extras() -> None:
    models = [
        model
        for model in vars(schema).values()
        if isinstance(model, type) and issubclass(model, BaseModel) and model.__module__ == schema.__name__
    ]
    assert models
    for model in models:
        assert model.model_config["frozen"] is True
        assert model.model_config["extra"] == "forbid"
    request = CaseInput.model_validate(_input_data())
    with pytest.raises(ValidationError, match="frozen"):
        request.case_id = "changed"
    with pytest.raises(ValidationError, match="frozen"):
        request.payload.kind = "personal"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        schema.Citation.model_validate({"ref_id": "item-1", "reason": "reason", "secret": "not allowed"})
