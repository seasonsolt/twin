"""No real personal material: all cases and reference text are invented fixtures."""

from __future__ import annotations

import datetime as dt
import json
import logging
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
    select_cases,
    summarize,
    write_comparison,
    write_outputs,
)
from twin.evals.schema import (
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
from twin.persona.chat import PersonaChat
from twin.persona.schema import ChatDraft
from twin.persona.store import PersonaStore
from twin.usage import UsageRecorder, record_usage

FIXTURE = Path(__file__).parent / "fixtures" / "personal_eval"


def grade(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
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
    config.write_text('target_name = "虚构林沐"\ndb_path = "fixture.db"\n')
    llm = FakeLLM(grade)
    monkeypatch.setattr("twin.cli.make_llm", lambda s: llm)
    monkeypatch.setattr("twin.evals.personal.make_llm", lambda s, section: llm)
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
    report = read_records(out / "records.json")
    assert len(report.predictions) == 12 and report.metrics["repeats"] == 2
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
