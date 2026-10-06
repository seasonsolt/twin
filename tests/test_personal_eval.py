"""No real personal material: all cases and reference text are invented fixtures."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from typer.testing import CliRunner

from twin.cli import app
from twin.config import LLMSettings, Settings
from twin.embed import HashingEmbedder
from twin.evals.harness import Judge, run_judgements
from twin.evals.personal import (
    ARTIFACT_RE,
    PersonalRubric,
    PersonaSystem,
    compare_reports,
    ensure_output_directory,
    load_evalset,
    make_panel,
    read_records,
    run_evaluation,
    run_persona_evaluation,
    select_cases,
    summarize,
    write_comparison,
    write_outputs,
)
from twin.evals.schema import (
    Case,
    CaseInput,
    JudgeStatus,
    Prediction,
    QuestionInput,
    QuestionOutput,
    Report,
    SystemSpec,
)
from twin.evals.stats import bootstrap_grouped
from twin.llm import FakeLLM
from twin.persona.chat import PersonaChat, index_persona
from twin.persona.profile import ExtractDraft, build_profile
from twin.persona.schema import ChatDraft, SourceKind
from twin.persona.sources import parse_text
from twin.persona.store import PersonaStore
from twin.usage import UsageRecorder, record_usage

FIXTURE = Path(__file__).parent / "fixtures" / "personal_eval"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(("TWIN_", "DTWIN_", "OPENAI_", "ANTHROPIC_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TWIN_LLM_KEY", "invented-offline-key")
    monkeypatch.setenv("TWIN_EMBED_KEY", "invented-offline-key")


def grade(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    if schema is ExtractDraft:
        return {"items": []}
    if schema is ChatDraft:
        return {"reply": "INVENTED-ANSWER", "citations": [], "confidence": 0.2, "abstain": True}
    if schema.__name__ == "_Style":
        return {"persona": 4, "quality": 3, "reason": "虚构评价"}
    if schema.__name__ == "_Quality":
        return {"quality": 3, "reason": "虚构评价"}
    return {"score": 1 if "云朵城" not in user else 0, "reason": "虚构评价"}


class InventedSystem:
    spec = SystemSpec(
        system_id="invented",
        label="invented",
        supports_as_of=False,
        supports_abstain=False,
        supports_confidence=False,
    )

    def __init__(self, fail_repeat: int | None = None) -> None:
        self.inputs: list[CaseInput] = []
        self.fail_repeat = fail_repeat

    def predict(self, case_input: CaseInput, *, as_of: dt.date | None, repeat: int) -> Prediction:
        self.inputs.append(case_input)
        if repeat == self.fail_repeat:
            raise RuntimeError("INVENTED-QUESTION INVENTED-ANSWER")
        text = "<think>虚构回答</think>" if case_input.case_id == "f1" else f"虚构回答 r{repeat}"
        return Prediction(
            case_id=case_input.case_id,
            system_id=self.spec.system_id,
            mode=case_input.mode,
            repeat=repeat,
            text=text,
            payload=QuestionOutput(reply=text),
        )


def evaluate(
    *, repeats: int = 2, system: InventedSystem | None = None, panel: tuple[Judge, ...] | None = None
) -> Report:
    return run_evaluation(
        load_evalset(FIXTURE / "evalset.json"),
        system or InventedSystem(),
        panel or (Judge(FakeLLM(grade), "low"),),
        FIXTURE / "persona.txt",
        repeats=repeats,
    )


def test_summary_mode_counts_and_legacy_records(tmp_path: Path) -> None:
    report = evaluate()
    categories = {case.input.case_id: case.input.payload.category for case in report.cases}
    predictions = tuple(
        prediction.model_copy(
            update={
                "raw": {
                    "mode": "abstain"
                    if prediction.repeat
                    else "general"
                    if categories[prediction.case_id] == "general"
                    else "grounded"
                },
                "abstain": bool(prediction.repeat),
            }
        )
        for prediction in report.predictions
    )
    report = report.model_copy(update={"predictions": predictions})
    data = summarize(report)
    for category in ("fact", "unanswerable", "style", "general"):
        n = data[category]["n_cases"]
        assert data[category]["modes"] == {
            "grounded": 0 if category == "general" else n,
            "general": n if category == "general" else 0,
            "abstain": n,
        }
    assert data["update"]["modes"] == {"grounded": 0, "general": 0, "abstain": 0}
    assert data["overall"]["modes"] == {"grounded": 5, "general": 1, "abstain": 6}
    legacy = report.model_copy(update={"predictions": tuple(p.model_copy(update={"raw": {}}) for p in predictions)})
    assert summarize(legacy)["general"]["modes"] == {"grounded": 1, "general": 0, "abstain": 1}
    compared = compare_reports(legacy, report)
    assert compared["categories"]["general"]["modes"] == {
        "A": {"grounded": 1, "general": 0, "abstain": 1},
        "B": {"grounded": 0, "general": 1, "abstain": 1},
    }
    write_outputs(tmp_path, report, Settings(), allow_in_repo=True)
    assert (
        json.loads((tmp_path / "report.json").read_text())["categories"]["general"]["modes"] == data["general"]["modes"]
    )
    assert '回答模式：{"grounded": 0, "general": 1, "abstain": 1}' in (tmp_path / "report.md").read_text()


@pytest.mark.parametrize("mode", ["grounded", "general", "abstain"])
def test_persona_prediction_records_reply_mode(mode: str) -> None:
    llm = FakeLLM(lambda *a: {"reply": "虚构回答", "citations": [], "confidence": 0.2, "mode": mode})
    with PersonaStore(":memory:") as store:
        system = PersonaSystem(PersonaChat(store, llm, HashingEmbedder(), Settings(target_name="虚构林沐")))
        case = load_evalset(FIXTURE / "evalset.json")[0]
        prediction = system.predict(case.input, as_of=None, repeat=0)
        assert prediction.raw["mode"] == mode
        assert prediction.abstain == (mode == "abstain")


def test_loader_answer_free_grouping_and_updates() -> None:
    cases = load_evalset(FIXTURE / "evalset.json")
    assert len(cases) == 7
    assert [case.group_id for case in cases[:3]] == ["doc-a", "doc-a", "虚构笔记乙"]
    assert cases[3].group_id == "u1"
    assert cases[-1].expected.modified_answer == "薄荷茶"
    forbidden = {"answer", "evidence", "source_group", "source", "doc_id", "modified_fact", "add_fact"}
    for case in cases:
        assert not forbidden.intersection(case.input.payload.model_dump())
    assert len(select_cases(cases, ["fact", "general"])) == 4
    with pytest.raises(ValueError, match="categories"):
        select_cases(cases, ["bad"])


@pytest.mark.parametrize("doc_id", [0, 42, "doc-a", "42"])
def test_loader_normalizes_doc_id(tmp_path: Path, doc_id: int | str) -> None:
    item = json.loads((FIXTURE / "evalset.json").read_text())[0]
    item["doc_id"] = doc_id
    path = tmp_path / "bank.json"
    path.write_text(json.dumps([item]))
    (case,) = load_evalset(path)
    assert case.group_id == str(doc_id)
    assert case.expected.source_group == str(doc_id)


@pytest.mark.parametrize("doc_id", [True, False, 0.0, 1.5, -1, "", "   ", None, [], {}])
def test_loader_rejects_invalid_doc_id(tmp_path: Path, doc_id: Any) -> None:
    item = json.loads((FIXTURE / "evalset.json").read_text())[0]
    item["doc_id"] = doc_id
    path = tmp_path / "bank.json"
    path.write_text(json.dumps([item]))
    with pytest.raises(ValueError, match=r"f1.*字段 doc_id 必须是非负整数或非空字符串"):
        load_evalset(path)


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        ({"question": None}, "question"),
        ({"question": ""}, "question"),
        ({"category": "unknown"}, "category"),
        ({"answer": 123}, "answer"),
        ({"evidence": [123]}, "evidence"),
        ({"source": None}, "source"),
        ({"doc_id": []}, "doc_id"),
        ({"id": None}, "id"),
    ],
)
def test_loader_validation_never_echoes_text(tmp_path: Path, mutation: dict[str, Any], field: str) -> None:
    item = json.loads((FIXTURE / "evalset.json").read_text())[0]
    item.update({"question": "INVENTED-QUESTION", "answer": "INVENTED-ANSWER"})
    item.update(mutation)
    path = tmp_path / "bank.json"
    path.write_text(json.dumps([item]))
    with pytest.raises(ValueError) as caught:
        load_evalset(path)
    message = str(caught.value)
    assert field in message
    if field != "id":
        assert "f1" in message
    assert "INVENTED-QUESTION" not in message and "INVENTED-ANSWER" not in message
    assert caught.value.__suppress_context__ or caught.value.__context__ is None


@pytest.mark.parametrize("field", ["answer", "evidence", "source", "doc_id", "question"])
def test_loader_missing_fields_and_duplicates(tmp_path: Path, field: str) -> None:
    item = json.loads((FIXTURE / "evalset.json").read_text())[0]
    del item[field]
    path = tmp_path / "bank.json"
    path.write_text(json.dumps([item]))
    with pytest.raises(ValueError, match=f"f1.*{field}.*缺失"):
        load_evalset(path)
    items = json.loads((FIXTURE / "evalset.json").read_text())
    path.write_text(json.dumps([items[0], items[0]]))
    with pytest.raises(ValueError, match=r"f1.*id.*重复"):
        load_evalset(path)


@pytest.mark.parametrize("payload", ["{INVENTED-QUESTION", "{}", "[]", "[12]"])
def test_loader_invalid_json(tmp_path: Path, payload: str) -> None:
    path = tmp_path / "bank.json"
    path.write_text(payload)
    with pytest.raises(ValueError) as caught:
        load_evalset(path)
    assert "INVENTED-QUESTION" not in str(caught.value)


@pytest.mark.parametrize("field", ["add_fact", "modified_fact", "modified_answer"])
def test_update_requires_edit_fields(tmp_path: Path, field: str) -> None:
    item = json.loads((FIXTURE / "evalset.json").read_text())[-1]
    del item[field]
    path = tmp_path / "bank.json"
    path.write_text(json.dumps([item]))
    with pytest.raises(ValueError, match=f"m1.*{field}"):
        load_evalset(path)


def test_adapter_independent_answer_free_and_no_chat_log() -> None:
    llm = FakeLLM(grade)
    with PersonaStore(":memory:") as store:
        system = PersonaSystem(PersonaChat(store, llm, HashingEmbedder(), Settings(target_name="虚构林沐")))
        case = load_evalset(FIXTURE / "evalset.json")[0]
        for repeat in (0, 1):
            answer = system.predict(case.input, as_of=None, repeat=repeat)
            assert answer.repeat == repeat and answer.abstain
        assert all("桂花茶" not in user for _, _, user in llm.calls)
        assert all(user.count("对方：") == 1 for _, _, user in llm.calls)
        assert store._db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 0
        with pytest.raises(ValueError, match="update"):
            system.predict(load_evalset(FIXTURE / "evalset.json")[-1].input, as_of=None, repeat=0)


@pytest.mark.parametrize(
    ("case_id", "metric", "expected", "wording"),
    [
        ("f1", "accuracy", 1, "关键事实正确"),
        ("u1", "accuracy", 1, "不应编造"),
        ("s1", "persona", 4, "口吻、身份视角"),
        ("s1", "quality", 3, "内容是否有见地"),
        ("g1", "quality", 3, "准确、完整、切题"),
        ("m1", "accuracy", 1, "关键事实正确"),
    ],
)
def test_rubric_mapping(case_id: str, metric: str, expected: float, wording: str) -> None:
    case = next(case for case in load_evalset(FIXTURE / "evalset.json") if case.input.case_id == case_id)
    prediction = Prediction(
        case_id=case_id,
        system_id="invented",
        mode="persona",
        repeat=0,
        text="<answer>虚构回答",
        payload=QuestionOutput(reply="<answer>虚构回答"),
    )
    llm = FakeLLM(grade)
    rubric = PersonalRubric(metric, "虚构参考")
    row = run_judgements([case], [prediction], [Judge(llm, "low")], [rubric], 1)[0]
    assert row.score == expected and row.judge_id == "j0:fake"
    assert row.verdict == {"artifacts": True}
    assert wording in llm.calls[0][2]
    assert ("虚构参考" in llm.calls[0][2]) == (case_id == "s1")


@pytest.mark.parametrize("score", [-1, 0.25, 2, True, "1", float("nan")])
def test_invalid_rubric_score_fails_without_text(score: Any) -> None:
    case = load_evalset(FIXTURE / "evalset.json")[0]
    prediction = InventedSystem().predict(case.input, as_of=None, repeat=0)
    llm = FakeLLM(lambda s, u, schema: {"score": score, "reason": "INVENTED-ANSWER"})
    row = run_judgements([case], [prediction], [Judge(llm, "low")], [PersonalRubric("accuracy", "")], 1)[0]
    assert row.status is JudgeStatus.FAILED and row.score is None
    assert "INVENTED-ANSWER" not in (row.error or "")


@pytest.mark.parametrize("token", ["<|im_start|>", "<|im_end|>", "<think>", "</think>", "<answer>", "<|endoftext|>"])
def test_artifact_tokens(token: str) -> None:
    assert ARTIFACT_RE.search("虚构回答" + token)
    assert not ARTIFACT_RE.search("普通虚构回答")


def test_panel_fallback_and_positional_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[LLMSettings] = []

    def fake_factory(settings: LLMSettings, section: str) -> FakeLLM:
        called.append(settings)
        return FakeLLM(grade)

    monkeypatch.setattr("twin.evals.personal.make_llm", fake_factory)
    settings = Settings()
    assert len(make_panel(settings)) == 1 and called == [settings.llm]
    settings.judges = [LLMSettings(model="invented-a"), LLMSettings(model="invented-b")]
    panel = make_panel(settings)
    report = evaluate(panel=panel)
    assert report.judges == ("j0:fake", "j1:fake")
    assert {row.judge_id for row in report.judgements} == {"j0:fake", "j1:fake"}


def test_grouped_stats_after_repeat_average_and_update_skip() -> None:
    system = InventedSystem()
    report = evaluate(system=system)
    assert len(system.inputs) == 12 and all(i.case_id != "m1" for i in system.inputs)
    assert report.skipped == {"update": 1}
    data = summarize(report)
    fact = data["fact"]
    assert fact["n_cases"] == 3 and fact["judge_failure_rate"] == 0
    score = fact["metrics"]["accuracy"]
    assert score["n_scored"] == 3 and score["n_groups"] == 2
    assert score["mean"] == pytest.approx(2 / 3)
    assert score["ci95"] == bootstrap_grouped({"doc-a": [1, 1], "虚构笔记乙": [0]}, "personal:fact:accuracy")
    assert fact["artifact_answers"] == 2
    assert data["style"]["metrics"]["persona"]["mean"] == 4
    assert data["style"]["metrics"]["quality"]["mean"] == 3
    assert data["general"]["metrics"]["quality"]["ci95"] is None
    assert data["update"]["status"] == "not run" and "受控" in data["update"]["reason"]


def test_averages_panel_then_repeats() -> None:
    report = evaluate()
    rows = tuple(
        row.model_copy(update={"score": 0.5 if row.repeat == 1 else 1.0})
        if row.status is JudgeStatus.OK and row.case_id == "f1"
        else row
        for row in report.judgements
    )
    revised = report.model_copy(update={"judgements": rows})
    assert summarize(revised)["fact"]["metrics"]["accuracy"]["mean"] == pytest.approx((0.75 + 1 + 0) / 3)


def test_failure_policy_invalidates_all_metrics_and_repeats(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    def fails(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ == "_Style":
            raise RuntimeError("INVENTED-QUESTION INVENTED-ANSWER")
        return grade(system, user, schema)

    report = evaluate(panel=(Judge(FakeLLM(grade), "low"), Judge(FakeLLM(fails), "low")))
    style = summarize(report)["style"]
    assert style["judge_failure_rate"] == 0.5
    assert all(value["mean"] is None for value in style["metrics"].values())
    assert "INVENTED-QUESTION" not in caplog.text and "INVENTED-ANSWER" not in caplog.text
    assert "INVENTED-ANSWER" not in report.model_dump_json()
    predicted_failure = evaluate(system=InventedSystem(fail_repeat=1))
    fact = summarize(predicted_failure)["fact"]
    assert fact["prediction_failures"] == 3
    assert fact["metrics"]["accuracy"]["mean"] is None
    assert "INVENTED-ANSWER" not in predicted_failure.model_dump_json()


def test_compare_paired_groups_wins_losses_ties(tmp_path: Path) -> None:
    first = evaluate()
    changes = {"f1": 0, "f2": 1, "f3": 1}
    second = first.model_copy(
        update={
            "judgements": tuple(
                row.model_copy(update={"score": changes[row.case_id]})
                if row.status is JudgeStatus.OK and row.case_id in changes
                else row
                for row in first.judgements
            )
        }
    )
    write_outputs(tmp_path / "a", first, Settings())
    write_outputs(tmp_path / "b", second, Settings())
    a, b = read_records(tmp_path / "a" / "records.json"), read_records(tmp_path / "b" / "records.json")
    comparison = compare_reports(a, b)
    metric = comparison["categories"]["fact"]["metrics"]["accuracy"]
    assert metric["mean"] == 0
    assert (metric["wins"], metric["losses"], metric["ties"]) == (1, 1, 1)
    assert metric["ci95"] == bootstrap_grouped({"doc-a": [-1, 0], "虚构笔记乙": [1]}, "personal:compare:fact:accuracy")
    assert comparison["categories"]["update"]["status"] == "not run"
    failed = b.model_copy(
        update={
            "judgements": tuple(
                row.model_copy(update={"status": JudgeStatus.FAILED, "score": None}) if row.case_id == "f1" else row
                for row in b.judgements
            )
        }
    )
    assert compare_reports(a, failed)["categories"]["fact"]["metrics"]["accuracy"]["n_unpaired"] == 1
    changed = b.model_copy(update={"cases": (b.cases[0].model_copy(update={"group_id": "other"}), *b.cases[1:])})
    with pytest.raises(ValueError, match=r"f1.*不一致"):
        compare_reports(a, changed)
    with pytest.raises(ValueError, match="persona-ref"):
        compare_reports(a, b.model_copy(update={"fingerprints": {"persona_ref": "changed"}}))


def test_owner_only_outputs_redaction_and_no_summary_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    report = evaluate()
    settings = Settings()
    monkeypatch.setenv("TWIN_LLM_KEY", "SECRET-TEST-KEY")
    settings.llm.base_url = "https://invented.invalid/api"
    report = report.model_copy(update={"warnings": ("SECRET-TEST-KEY https://invented.invalid/api",)})
    out = tmp_path / "output"
    out.mkdir(mode=0o755)
    for name in ("records.json", "report.json", "report.md"):
        (out / name).write_text("old")
        (out / name).chmod(0o644)
    write_outputs(out, report, settings)
    assert out.stat().st_mode & 0o777 == 0o700
    for name in ("records.json", "report.json", "report.md"):
        assert (out / name).stat().st_mode & 0o777 == 0o600
    records = (out / "records.json").read_text()
    assert "SECRET-TEST-KEY" not in records and "https://invented.invalid/api" not in records
    assert read_records(out / "records.json").schema_version == 2
    for name in ("report.json", "report.md"):
        text = (out / name).read_text()
        assert "林沐" not in text and "桂花茶" not in text
    comparison_out = tmp_path / "comparison"
    write_comparison(comparison_out, report, report, settings)
    assert comparison_out.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in comparison_out.iterdir())


def test_cli_refuses_in_repo_before_reading_input(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    out = repo / "never-created-personal-eval"
    runner = CliRunner()
    result = runner.invoke(
        app, ["eval", "--evalset", "missing.json", "--persona-ref", "missing.txt", "--out", str(out)]
    )
    assert result.exit_code == 1 and "--allow-in-repo" in result.output
    assert not out.exists()
    result = runner.invoke(app, ["eval-compare", "missing-a", "missing-b", "--out", str(out)])
    assert result.exit_code == 1 and "--allow-in-repo" in result.output
    symlink = tmp_path / "linked-repo"
    symlink.symlink_to(repo, target_is_directory=True)
    with pytest.raises(ValueError, match="git 仓库"):
        ensure_output_directory(symlink / "output")
    ensure_output_directory(out, allow_in_repo=True)


def test_cli_fake_llm_outputs_and_captured_logs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    config = tmp_path / "twin.toml"
    config.write_text(
        'target_name = "虚构林沐"\ndb_path = "fixture.db"\n'
        '[llm]\negress = "external"\n[[judges]]\negress = "external"\n'
        '[embed]\nprovider = "openai_compat"\nbase_url = "https://embed.invalid/v1"\n'
    )
    llm = FakeLLM(grade)
    constructed: list[str] = []
    monkeypatch.setattr("twin.cli.make_llm", lambda s: constructed.append("llm") or llm)
    monkeypatch.setattr("twin.cli.make_embedder", lambda s: constructed.append("embed") or HashingEmbedder())
    monkeypatch.setattr("twin.evals.personal.make_llm", lambda s, section: constructed.append("judge") or llm)
    runner = CliRunner()
    out = tmp_path / "run"
    result = runner.invoke(
        app,
        [
            "--config",
            str(config),
            "eval",
            "--evalset",
            str(FIXTURE / "evalset.json"),
            "--persona-ref",
            str(FIXTURE / "persona.txt"),
            "--out",
            str(out),
            "--repeats",
            "2",
            "--categories",
            "fact,style,general,unanswerable,update",
        ],
    )
    assert result.exit_code == 0, result.output
    assert constructed == ["llm", "embed", "judge"]
    report = read_records(out / "records.json")
    assert len(report.predictions) == 18 and report.metrics["repeats"] == 2
    assert summarize(report)["update"]["n_cases"] == 3
    assert "update 已在临时副本上运行" in result.output
    with PersonaStore(tmp_path / "fixture.db") as store:
        assert not store.list_sources() and not store.list_items()
    text = result.output + caplog.text
    for case in report.cases:
        assert case.input.payload.prompt not in text
    assert "INVENTED-ANSWER" not in text
    for path in out.iterdir():
        assert path.stat().st_mode & 0o777 == 0o600
        if path.name in {"usage.json", "calls.jsonl"}:
            assert "INVENTED-ANSWER" not in path.read_text()
    compared = runner.invoke(
        app,
        [
            "--config",
            str(config),
            "eval-compare",
            str(out / "records.json"),
            str(out / "records.json"),
            "--out",
            str(tmp_path / "compare"),
        ],
    )
    assert compared.exit_code == 0, compared.output
    assert "win/loss/tie" in (tmp_path / "compare" / "report.md").read_text()


def test_usage_trace_never_contains_question_or_answer(tmp_path: Path) -> None:
    recorder = UsageRecorder()
    with record_usage(recorder):
        evaluate()
    recorder.write(tmp_path)
    for name in ("usage.json", "calls.jsonl"):
        text = (tmp_path / name).read_text()
        assert "桂花茶" not in text and "虚构回答" not in text


def test_v1_readable_and_v2_generic_contract() -> None:
    from twin.evals.schema import FailurePolicy, PairingPolicy, Purpose, Scenario

    legacy = Report(
        schema_version=1,
        scenario=Scenario.BIOGRAPHY,
        purpose=Purpose.FINAL_EVAL,
        systems=(),
        judges=(),
        failure_policy=FailurePolicy.ALL_JUDGES_REQUIRED,
        pairing_policy=PairingPolicy.ALL_SYSTEMS_INTERSECTION,
    )
    assert Report.model_validate_json(legacy.model_dump_json()) == legacy
    payload = QuestionInput(id="invented", category="general", prompt="虚构问题")
    assert QuestionInput.model_validate_json(payload.model_dump_json()) == payload
    with pytest.raises(ValidationError):
        QuestionInput.model_validate({**payload.model_dump(), "answer": "虚构答案"})


def update_cases(tmp_path: Path) -> tuple[Case, ...]:
    items = [
        {
            "id": item_id,
            "category": "update",
            "question": f"INVENTED-QUESTION-{item_id} 我选择什么？",
            "answer": added,
            "add_fact": f"我选择{added}。",
            "modified_fact": f"我选择{modified}。",
            "modified_answer": modified,
        }
        for item_id, added, modified in (("tea", "桂花茶", "薄荷茶"), ("port", "星港", "月港"))
    ]
    path = tmp_path / "updates.json"
    path.write_text(json.dumps(items), encoding="utf-8")
    return load_evalset(path)


def memory_grade(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    if schema is ExtractDraft:
        match = re.search(r"本人：(我选择[^。]+。)", user)
        return {
            "items": [{"facet_id": "1.1", "statement": match[1], "quotes": [{"n": 1, "quote": match[1]}]}]
            if match
            else []
        }
    if schema is ChatDraft:
        material = system + user.split("【对话】")[0]
        choices = [word for word in ("桂花茶", "薄荷茶", "星港", "月港") if word in material]
        assert len(choices) <= 1  # No stale profile evidence or expressions may survive an edit.
        return {
            "reply": choices[0] if choices else "资料里没有记录这个事实。",
            "citations": re.findall(r"\[([^\]\n]+)\]", material),
            "confidence": 0.8 if choices else 0.2,
            "abstain": not choices,
        }
    answer = re.search(r"回答：([^\n]+)", user)
    assert answer is not None
    if schema.__name__ == "_Refusal":
        assert "标准答案" not in user
        return {"score": int(answer[1] == "资料里没有记录这个事实。"), "reason": "虚构删除评分"}
    assert schema.__name__ == "_Accuracy"
    expected = re.search(r"标准答案：([^\n]+)", user)
    assert expected is not None
    return {"score": int(answer[1] == expected[1]), "reason": "虚构准确评分"}


def memory_settings(tmp_path: Path) -> Settings:
    return Settings(db_path=tmp_path / "original.db", target_name="虚构林沐", max_workers=8)


def seed_memory(settings: Settings) -> None:
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_text(SourceKind.DOCUMENT, "background.txt", "虚构背景：只用干净画笔。", settings))
        build_profile(store, FakeLLM(memory_grade), settings)
        index_persona(store, HashingEmbedder(), settings)


def test_update_protocol_six_scores_private_db_and_incremental_indexes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    cases = update_cases(tmp_path)
    settings = memory_settings(tmp_path)
    seed_memory(settings)
    settings.db_path.chmod(0o640)
    before = settings.db_path.read_bytes()
    mode = settings.db_path.stat().st_mode
    events: list[str] = []
    private_paths: list[Path] = []
    snapshots: list[tuple[set[str], set[str]]] = []
    extracted: list[int] = []
    parsed_dates: list[dt.date | None] = []
    real_parse = parse_text
    real_delete = PersonaStore.delete_source
    real_build = build_profile
    real_index = index_persona
    real_reply = PersonaChat.reply

    def parse(*args: Any) -> Any:
        events.append("import")
        parsed_dates.append(args[-1])
        return real_parse(*args)

    def delete(store: PersonaStore, source_id: str) -> bool:
        events.append("delete")
        assert store.path != settings.db_path
        return real_delete(store, source_id)

    def build(store: PersonaStore, llm: Any, local: Settings) -> Any:
        events.append("build")
        assert local.max_workers == 1 and local.db_path == store.path != settings.db_path
        private_paths.append(store.path)
        result = real_build(store, llm, local)
        extracted.append(result.chunks_extracted)
        return result

    def index(store: PersonaStore, embedder: Any, local: Settings) -> Any:
        events.append("index")
        result = real_index(store, embedder, local)
        item_refs = set(store.vector_shas("items"))
        expr_refs = set(store.vector_shas("expressions"))
        assert item_refs == {item.item_id for item in store.list_items()}
        assert expr_refs == {expr.expression_id for expr in store.list_expressions(target_only=True)}
        assert all(expr.date == dt.date.today() for expr in store.list_expressions() if "我选择" in expr.text)
        snapshots.append((item_refs, expr_refs))
        return result

    def reply(chat: PersonaChat, messages: Any, as_of: Any = None, *, persist: bool = True) -> Any:
        events.append("ask")
        assert as_of is None and persist is False
        return real_reply(chat, messages, as_of=as_of, persist=persist)

    monkeypatch.setattr("twin.evals.personal.parse_text", parse)
    monkeypatch.setattr("twin.evals.personal.build_profile", build)
    monkeypatch.setattr("twin.evals.personal.index_persona", index)
    monkeypatch.setattr(PersonaStore, "delete_source", delete)
    monkeypatch.setattr(PersonaChat, "reply", reply)
    llm = FakeLLM(memory_grade)
    panel = (Judge(FakeLLM(memory_grade), "low"), Judge(FakeLLM(memory_grade), "low"))
    recorder = UsageRecorder()
    with record_usage(recorder):
        report = run_persona_evaluation(
            cases, llm, HashingEmbedder(), settings, panel, FIXTURE / "persona.txt", repeats=2
        )
    recorder.write(tmp_path)
    one_item = [
        "import",
        "build",
        "index",
        "ask",
        "ask",
        "delete",
        "import",
        "build",
        "index",
        "ask",
        "ask",
        "delete",
        "build",
        "index",
        "ask",
        "ask",
    ]
    assert events == one_item * 2
    assert extracted == [1, 1, 0, 1, 1, 0]  # Existing source never gets re-extracted.
    assert parsed_dates == [dt.date.today()] * 4
    assert settings.db_path.read_bytes() == before
    assert settings.db_path.stat().st_mode == mode
    assert private_paths and all(not path.parent.exists() for path in private_paths)
    assert snapshots[0][0].isdisjoint(snapshots[1][0]) and not snapshots[2][0]
    assert len(snapshots[2][1]) == len(snapshots[5][1]) == 1
    assert report.skipped == {} and report.warnings == ()
    assert [case.input.case_id for case in report.cases] == [
        f"{item}@{step}" for item in ("tea", "port") for step in ("add", "modify", "delete")
    ]
    assert [case.group_id for case in report.cases] == ["tea"] * 3 + ["port"] * 3
    assert len(report.predictions) == 12
    assert [prediction.text for prediction in report.predictions] == [
        text
        for text in ("桂花茶", "薄荷茶", "资料里没有记录这个事实。", "星港", "月港", "资料里没有记录这个事实。")
        for _ in range(2)
    ]
    assert report.cases[1].expected.answer == "薄荷茶"
    assert report.cases[4].expected.answer == "月港"
    data = summarize(report)["update"]
    assert data["status"] == "run" and data["n_cases"] == 6 and data["judge_calls"] == 24
    assert data["metrics"]["accuracy"] == {
        "n_scored": 6,
        "n_groups": 2,
        "mean": 1.0,
        "ci95": bootstrap_grouped({"tea": [1, 1, 1], "port": [1, 1, 1]}, "personal:update:accuracy"),
    }
    assert all(row.rubric_version == "1" for row in report.judgements)
    with sqlite3.connect(f"{settings.db_path.resolve().as_uri()}?mode=ro", uri=True) as db:
        assert db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 0
    for secret in ("INVENTED-QUESTION", "桂花茶", "薄荷茶", "星港", "月港"):
        assert secret not in caplog.text
        for name in ("usage.json", "calls.jsonl"):
            assert secret not in (tmp_path / name).read_text()
    out = tmp_path / "records"
    write_outputs(out, report, settings)
    assert read_records(out / "records.json") == Report.model_validate_json(report.model_dump_json())
    for name in ("report.json", "report.md"):
        assert "INVENTED-QUESTION" not in (out / name).read_text()
        assert "桂花茶" not in (out / name).read_text()
    assert compare_reports(report, report)["categories"]["update"]["metrics"]["accuracy"]["ties"] == 6
    old = run_evaluation(cases, InventedSystem(), panel, FIXTURE / "persona.txt")
    assert compare_reports(old, report)["categories"]["update"]["status"] == "not run"
    assert compare_reports(report, old)["runs"]["A"]["update"]["status"] == "run"
    values = {"tea@add": 1, "tea@modify": 0.5, "tea@delete": 0, "port@add": 0.5, "port@modify": 1, "port@delete": 1}
    changed = report.model_copy(
        update={
            "judgements": tuple(
                row.model_copy(update={"score": values[row.case_id]}) if row.status is JudgeStatus.OK else row
                for row in report.judgements
            )
        }
    )
    score = summarize(changed)["update"]["metrics"]["accuracy"]
    assert score["mean"] == pytest.approx(4 / 6)
    assert score["ci95"] == bootstrap_grouped({"tea": [1, 0.5, 0], "port": [0.5, 1, 1]}, "personal:update:accuracy")
    delta = compare_reports(report, changed)["categories"]["update"]["metrics"]["accuracy"]
    assert (delta["wins"], delta["losses"], delta["ties"]) == (0, 3, 3)
    missing = report.model_copy(
        update={
            "predictions": tuple(p for p in report.predictions if not (p.case_id == "tea@delete" and p.repeat == 1))
        }
    )
    assert summarize(missing)["update"]["metrics"]["accuracy"]["n_scored"] == 5
    assert compare_reports(report, missing)["categories"]["update"]["metrics"]["accuracy"]["n_unpaired"] == 1


@pytest.mark.parametrize("failure_stage", ["parse", "extract", "build", "index", "judge", "chat"])
def test_update_failure_privacy_cleanup_and_original_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, failure_stage: str
) -> None:
    settings = memory_settings(tmp_path)
    seed_memory(settings)
    before = settings.db_path.read_bytes()
    paths: list[Path] = []
    secret = "INVENTED-QUESTION 我选择桂花茶。 INVENTED-ANSWER"
    original_init = PersonaStore.__init__

    def init(store: PersonaStore, path: Any) -> None:
        paths.append(Path(path))
        original_init(store, path)

    def fails(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError(secret)

    def backend(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if (
            (failure_stage == "extract" and schema is ExtractDraft)
            or (failure_stage == "judge" and schema.__name__ in {"_Accuracy", "_Refusal"})
            or (failure_stage == "chat" and schema is ChatDraft)
        ):
            raise RuntimeError(secret)
        return memory_grade(system, user, schema)

    monkeypatch.setattr(PersonaStore, "__init__", init)
    if failure_stage in {"parse", "build", "index"}:
        monkeypatch.setattr(
            "twin.evals.personal."
            + {"parse": "parse_text", "build": "build_profile", "index": "index_persona"}[failure_stage],
            fails,
        )
    llm = FakeLLM(backend)
    panel = (Judge(llm, "low"),)
    cases = update_cases(tmp_path)
    if failure_stage in {"judge", "chat"}:
        report = run_persona_evaluation(cases, llm, HashingEmbedder(), settings, panel, FIXTURE / "persona.txt")
        data = summarize(report)["update"]
        assert data["metrics"]["accuracy"]["mean"] is None
        assert data["judge_failures"] == (6 if failure_stage == "judge" else 0)
        assert data["prediction_failures"] == (6 if failure_stage == "chat" else 0)
        assert secret not in report.model_dump_json()
    else:
        with pytest.raises(RuntimeError, match="详情已隐藏") as caught:
            run_persona_evaluation(cases, llm, HashingEmbedder(), settings, panel, FIXTURE / "persona.txt")
        assert secret not in str(caught.value) and caught.value.__suppress_context__
    assert secret not in caplog.text
    assert settings.db_path.read_bytes() == before
    assert paths and all(not path.parent.exists() for path in paths)


def test_update_adapter_backups_live_wal_without_writing_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = memory_settings(tmp_path)
    llm = FakeLLM(memory_grade)
    original_index = index_persona
    copies: list[Path] = []

    def index(copy: PersonaStore, embedder: Any, local: Settings) -> Any:
        copies.append(copy.path)
        assert any(source.title == "wal" for source in copy.list_sources())
        assert any(expr.text == "虚构背景：只用干净画笔。" for expr in copy.list_expressions())
        return original_index(copy, embedder, local)

    monkeypatch.setattr("twin.evals.personal.index_persona", index)
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_text(SourceKind.DOCUMENT, "wal.txt", "虚构背景：只用干净画笔。", settings))
        before = settings.db_path.read_bytes()
        wal = settings.db_path.with_name(settings.db_path.name + "-wal")
        wal_before = wal.read_bytes()
        report = run_evaluation(
            update_cases(tmp_path),
            PersonaSystem(PersonaChat(store, llm, HashingEmbedder(), settings)),
            (Judge(llm, "low"),),
            FIXTURE / "persona.txt",
            max_workers=8,
        )
        assert summarize(report)["update"]["metrics"]["accuracy"]["mean"] == 1
        assert settings.db_path.read_bytes() == before and wal.read_bytes() == wal_before
        assert len(store.list_sources()) == 1 and not store.list_items()
        # The CLI entry uses a separate mode=ro connection rather than the live store handle.
        cli_report = run_persona_evaluation(
            update_cases(tmp_path),
            llm,
            HashingEmbedder(),
            settings,
            (Judge(llm, "low"),),
            FIXTURE / "persona.txt",
        )
        assert summarize(cli_report)["update"]["metrics"]["accuracy"]["mean"] == 1
        assert settings.db_path.read_bytes() == before and wal.read_bytes() == wal_before
    assert len(set(copies)) == 2 and all(not path.parent.exists() for path in copies)


def test_cli_update_category_excluded_does_not_edit_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('target_name = "虚构林沐"\ndb_path = "fixture.db"\n')
    llm = FakeLLM(grade)
    monkeypatch.setattr("twin.cli.make_llm", lambda s: llm)
    monkeypatch.setattr("twin.evals.personal.make_llm", lambda s, section: llm)
    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config),
            "eval",
            "--evalset",
            str(FIXTURE / "evalset.json"),
            "--persona-ref",
            str(FIXTURE / "persona.txt"),
            "--out",
            str(tmp_path / "out"),
            "--categories",
            "fact",
        ],
    )
    assert result.exit_code == 0, result.output
    report = read_records(tmp_path / "out" / "records.json")
    assert report.skipped == {"update": 0} and report.warnings == ()
    assert {schema for schema, _, _ in llm.calls} == {"ChatDraft", "_Accuracy"}
    assert "update 已" not in result.output


def test_update_retrieves_document_expressions_without_profile_items(tmp_path: Path) -> None:
    settings = memory_settings(tmp_path)
    seed_memory(settings)

    def backend(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is ExtractDraft:
            return {"items": []}
        return memory_grade(system, user, schema)

    llm = FakeLLM(backend)
    report = run_persona_evaluation(
        update_cases(tmp_path),
        llm,
        HashingEmbedder(),
        settings,
        (Judge(llm, "low"),),
        FIXTURE / "persona.txt",
    )
    assert summarize(report)["update"]["metrics"]["accuracy"]["mean"] == 1
    assert all(not any(c.ref_id.startswith("pi_") for c in p.citations) for p in report.predictions)
    assert all(p.citations for p in report.predictions if not p.case_id.endswith("@delete"))
