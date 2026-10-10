"""Entirely invented data; no downloaded conversations or credentials."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from typer.testing import CliRunner

from twin.cli import app
from twin.config import BudgetSettings, LLMSettings, Settings
from twin.embed import HashingEmbedder, Matrix
from twin.evals import longmemeval as lm
from twin.evals.harness import Judge
from twin.llm import FakeLLM
from twin.usage import BudgetExceeded, active_recorder


def item(qid: str = "invented-1", category: str = "single-session-assistant") -> dict[str, Any]:
    return {
        "question_id": qid,
        "question_type": category,
        "question": "Which fictional cobalt telescope did you recommend?",
        "question_date": "2024/01/05 (Fri) 10:00",
        "answer": "GOLD_ONLY_MARKER",
        "answer_session_ids": ["s1"],
        "haystack_session_ids": ["s1", "s2"],
        "haystack_dates": ["2024/01/01 (Mon) 09:00", "2024/01/03 (Wed) 09:00"],
        "haystack_sessions": [
            [
                {"role": "user", "content": "I need a cobalt telescope.", "has_answer": True},
                {"role": "assistant", "content": "I recommend the fictional cobalt telescope Atlas."},
            ],
            [
                {"role": "user", "content": "The cobalt telescope should fit a small desk."},
                {"role": "assistant", "content": "The cobalt telescope Atlas still fits."},
            ],
        ],
        "unknown": "UNKNOWN_MARKER",
    }


def dataset(tmp_path: Path, items: list[dict[str, Any]] | None = None) -> Path:
    path = tmp_path / "invented.json"
    path.write_text(json.dumps(items if items is not None else [item()]))
    return path


def test_loader_discards_gold_metadata_and_preserves_roles_dates_numeric_answers(tmp_path: Path) -> None:
    raw = item()
    raw["answer"] = 18
    raw["haystack_sessions"][0][0]["unknown"] = "TURN_UNKNOWN"
    case = lm.load_dataset(dataset(tmp_path, [raw]))[0]
    assert type(case.gold.answer) is int and case.gold.answer == 18
    assert case.gold.answer_session_ids == ("s1",)
    boundary = asdict(case.input)
    text = json.dumps(boundary)
    assert all(marker not in text for marker in ("has_answer", "unknown", "answer_session_ids", "TURN_UNKNOWN"))
    assert [turn.role for turn in case.input.sessions[0].turns] == ["user", "assistant"]
    assert case.input.question_date == raw["question_date"]
    assert [session.date for session in case.input.sessions] == raw["haystack_dates"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("answer", True),
        ("answer", float("nan")),
        ("answer", {"text": "secret"}),
        ("question", " "),
        ("question_type", "personal"),
        ("question_date", "2024-01-05"),
        ("question_date", "2024/01/05 (Mon) 10:00"),
        ("question_date", "2024/02/30 (Fri) 10:00"),
        ("haystack_dates", ["2024/01/01 (Mon) 09:00"]),
        ("haystack_sessions", [[]]),
        ("answer_session_ids", ["not-in-history"]),
        ("answer_session_ids", ["s1", "s1"]),
        ("haystack_sessions", [[{"role": "system", "content": "SECRET"}], []]),
    ],
)
def test_loader_rejects_invalid_data_without_echoing_values(tmp_path: Path, field: str, value: Any) -> None:
    raw = item()
    raw[field] = value
    with pytest.raises(ValueError, match="Invalid LongMemEval dataset") as error:
        lm.load_dataset(dataset(tmp_path, [raw]))
    assert "SECRET" not in str(error.value) and "GOLD_ONLY" not in str(error.value)
    assert error.value.__suppress_context__


def test_unique_question_ids_and_selection(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        lm.load_dataset(dataset(tmp_path, [item(), item()]))
    cases = lm.load_dataset(dataset(tmp_path, [item(str(i)) for i in range(5)]))
    assert [case.input.question_id for case in lm.select_cases(cases)] == ["0", "1", "2"]
    assert [case.input.question_id for case in lm.select_cases(cases, offset=2, limit=2)] == ["2", "3"]
    with pytest.raises(ValueError):
        lm.select_cases(cases, offset=5)


class SpyEmbedder(HashingEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> Matrix:
        self.texts.extend(texts)
        return super().embed(texts)


def test_retrieval_both_roles_order_dates_bounds_and_no_gold(tmp_path: Path) -> None:
    raw = item()
    raw["haystack_sessions"][1] += [
        {"role": "user", "content": f"Unrelated filler {i}: " + "z" * 2400} for i in range(15)
    ]
    case = lm.load_dataset(dataset(tmp_path, [raw]))[0]
    embedder = SpyEmbedder()
    llm = FakeLLM(lambda *_: {"hypothesis": "Atlas"})
    assert lm.HistoryBaseline(llm, embedder, Settings()).predict(case.input) == "Atlas"
    prompt = json.loads(llm.calls[0][2])
    history = prompt["history"]
    assert {excerpt["role"] for excerpt in history} == {"user", "assistant"}
    assert any("recommend" in excerpt["content"] for excerpt in history)
    assert prompt["question_date"] == raw["question_date"]
    positions = [(excerpt["session_id"], excerpt["turn"], excerpt["part"]) for excerpt in history]
    assert positions == sorted(positions)
    assert len(history) <= lm.TOP_K
    assert sum(len(json.dumps(excerpt, ensure_ascii=False)) for excerpt in history) <= lm.CONTEXT_CHARS
    assert all(len(excerpt["content"]) <= lm.CHUNK_CHARS for excerpt in history)
    assert {excerpt["date"] for excerpt in history} <= set(raw["haystack_dates"])
    all_backend_text = " ".join([*embedder.texts, llm.calls[0][2]])
    assert all(marker not in all_backend_text for marker in ("GOLD_ONLY", "has_answer", "UNKNOWN_MARKER"))
    assert sum(len(turn["content"]) for session in raw["haystack_sessions"] for turn in session) > len(llm.calls[0][2])


def no_backend(*args: Any, **kwargs: Any) -> Any:
    pytest.fail("dry-run or invalid output constructed a backend")


def test_cli_dryrun_no_backend_and_private_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    for name in ("make_llm", "make_embedder", "make_panel"):
        monkeypatch.setattr(lm, name, no_backend)
    out = tmp_path / "private" / "run"
    result = CliRunner().invoke(
        app, ["eval-longmemeval", "--dataset", str(dataset(tmp_path)), "--out", str(out), "--dry-run", "--score"]
    )
    assert result.exit_code == 0, result.exception
    report = json.loads((out / "report.json").read_text())
    assert report["selected"] == report["missing"] == 1
    assert report["completed"] == 0 and report["accuracy_selected"] is None
    assert (out / "hypotheses.jsonl").read_text() == ""
    assert json.loads((out / "usage.json").read_text())["totals"]["calls"] == 0
    assert out.stat().st_mode & 0o777 == 0o700
    assert all((out / name).stat().st_mode & 0o777 == 0o600 for name in lm.ARTIFACTS)
    # Even a dry run must never truncate a previous run.
    before = {name: (out / name).read_bytes() for name in lm.ARTIFACTS}
    again = CliRunner().invoke(app, ["eval-longmemeval", "--dataset", "missing", "--out", str(out), "--dry-run"])
    assert again.exit_code == 1
    assert before == {name: (out / name).read_bytes() for name in lm.ARTIFACTS}


def test_output_rejected_before_input_or_backends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = Path(__file__).resolve().parents[1]
    assert lm.validate_output(Path("~/invented-longmemeval-run")) == Path.home() / "invented-longmemeval-run"
    monkeypatch.setattr(lm, "load_dataset", no_backend)
    result = CliRunner().invoke(app, ["eval-longmemeval", "--dataset", "missing", "--out", str(root / "private-run")])
    assert result.exit_code == 1
    assert not (root / "private-run").exists()
    out = tmp_path / "outside"
    out.mkdir()
    (out / "hypotheses.jsonl").symlink_to(root / "README.md")
    with pytest.raises(ValueError):
        lm.validate_output(out)
    linked_repo = tmp_path / "repo-link"
    linked_repo.symlink_to(root, target_is_directory=True)
    with pytest.raises(ValueError):
        lm.validate_output(linked_repo / "run")


def test_prediction_judge_failures_denominator_export_and_incremental_usage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = lm.load_dataset(dataset(tmp_path, [item(str(i)) for i in range(3)]))
    out = tmp_path / "run"
    calls = 0

    def predict(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 2:
            assert len((out / "hypotheses.jsonl").read_text().splitlines()) == 1
            assert json.loads((out / "usage.json").read_text())["totals"]["calls"] > 0
            raise RuntimeError("SECRET_KEY historical content")
        return {"hypothesis": "Atlas"}

    judge_calls = 0

    def grade(*_: Any) -> dict[str, Any]:
        nonlocal judge_calls
        judge_calls += 1
        if judge_calls == 2:
            raise RuntimeError("SECRET_KEY judge content")
        return {"correct": True}

    monkeypatch.setattr(lm, "make_llm", lambda *_: FakeLLM(predict))
    monkeypatch.setattr(lm, "make_embedder", lambda *_: HashingEmbedder())
    monkeypatch.setattr(lm, "make_panel", lambda *_: (Judge(FakeLLM(grade), "low"),))
    report = lm.run_evaluation(cases, out, Settings(), score=True, system="retrieval")
    assert report["selected"] == 3 and report["completed"] == 2
    assert report["prediction_failures"] == report["judge_failures"] == 1
    assert report["scored"] == 1 and report["unscored"] == 2
    assert report["accuracy_selected"] == pytest.approx(1 / 3)
    assert report["accuracy_scored"] == 1
    assert report["categories"]["single-session-assistant"]["selected"] == 3
    exported = [json.loads(line) for line in (out / "hypotheses.jsonl").read_text().splitlines()]
    assert [row["question_id"] for row in exported] == ["0", "2"]
    assert all(set(row) == {"question_id", "hypothesis"} for row in exported)
    assert all("SECRET_KEY" not in (out / name).read_text() for name in lm.ARTIFACTS)


def test_budget_stop_marks_remaining_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = lm.load_dataset(dataset(tmp_path, [item(str(i)) for i in range(3)]))
    calls = 0

    def predict(*_: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        recorder = active_recorder()
        assert recorder is not None and recorder.max_cost_usd == 0
        recorder.stop = BudgetExceeded("invented budget stop")
        raise recorder.stop

    monkeypatch.setattr(lm, "make_llm", lambda *_: FakeLLM(predict))
    monkeypatch.setattr(lm, "make_embedder", lambda *_: HashingEmbedder())
    monkeypatch.setattr(lm, "make_panel", no_backend)
    report = lm.run_evaluation(
        cases, tmp_path / "run", Settings(budget=BudgetSettings(max_cost_usd=0)), score=True, system="retrieval"
    )
    assert calls == 1
    assert report["prediction_failures"] == 1 and report["missing"] == 2
    assert report["accuracy_selected"] == 0 and report["unscored"] == 3


@pytest.mark.parametrize(
    ("category", "qid", "word"),
    [
        ("single-session-user", "q", "full reference"),
        ("single-session-assistant", "q", "partial answers fail"),
        ("multi-session", "q", "equivalent"),
        ("single-session-preference", "q", "not every"),
        ("temporal-reasoning", "q", "differ by one"),
        ("knowledge-update", "q", "Older information"),
        ("single-session-user", "q_abs", "unavailable"),
        ("single-session-user", "q_abs_middle", "unavailable"),
    ],
)
def test_type_specific_custom_judging_and_strict_boolean(tmp_path: Path, category: str, qid: str, word: str) -> None:
    raw = copy.deepcopy(item(qid, category))
    raw["answer"] = 18.5
    case = lm.load_dataset(dataset(tmp_path, [raw]))[0]
    llm = FakeLLM(lambda *_: {"correct": True})
    assert lm.judge_answer(case, "Atlas", Judge(llm, "low")) is True
    assert word in llm.calls[0][1]
    assert json.loads(llm.calls[0][2])["answer"] == 18.5
    with pytest.raises(ValidationError):
        lm.Verdict(correct="yes")  # type: ignore[arg-type]


def test_reader_and_judge_configuration_used(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from twin.evals import personal

    settings = Settings(
        llm=LLMSettings(model="main"),
        chat_llm=LLMSettings(model="reader"),
        judges=[LLMSettings(model="preferred-judge", effort_twin="low")],
    )
    models: list[str | None] = []

    def make(config: LLMSettings, *_: Any) -> FakeLLM:
        models.append(config.model)
        return FakeLLM(lambda *_: {"correct": True} if config.model == "preferred-judge" else {"hypothesis": "Atlas"})

    monkeypatch.setattr(lm, "make_llm", make)
    monkeypatch.setattr(personal, "make_llm", make)
    monkeypatch.setattr(lm, "make_embedder", lambda *_: HashingEmbedder())
    cases = lm.load_dataset(dataset(tmp_path))
    report = lm.run_evaluation(cases, tmp_path / "run", settings, score=True, system="retrieval")
    assert models == ["reader", "preferred-judge"]
    assert report["scored"] == 1


def test_cli_invalid_config_does_not_log_sensitive_values(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('[llm]\nprovider = "SECRET_CONFIG_VALUE"\n')
    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config),
            "eval-longmemeval",
            "--dataset",
            str(dataset(tmp_path)),
            "--out",
            str(tmp_path / "run"),
            "--dry-run",
        ],
    )
    assert result.exit_code == 1
    assert "SECRET_CONFIG_VALUE" not in result.output
    assert not (tmp_path / "run").exists()


def test_partial_panel_failure_never_produces_successful_score(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = lm.load_dataset(dataset(tmp_path))
    monkeypatch.setattr(lm, "make_llm", lambda *_: FakeLLM(lambda *_: {"hypothesis": "Atlas"}))
    monkeypatch.setattr(lm, "make_embedder", lambda *_: HashingEmbedder())
    monkeypatch.setattr(
        lm,
        "make_panel",
        lambda *_: (
            Judge(FakeLLM(lambda *_: {"correct": True}), "low"),
            Judge(FakeLLM(lambda *_: {"correct": "yes"}), "low"),
        ),
    )
    report = lm.run_evaluation(cases, tmp_path / "run", Settings(), score=True, system="retrieval")
    assert report["completed"] == 1 and report["judge_failed_calls"] == 1
    assert report["scored"] == 0 and report["accuracy_selected"] == 0
    assert report["accuracy_scored"] is None


def test_backend_construction_failure_records_every_selected_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cases = lm.load_dataset(dataset(tmp_path, [item("a"), item("b")]))

    def fail(*_: Any) -> Any:
        raise RuntimeError("SECRET_BACKEND_CONFIG")

    monkeypatch.setattr(lm, "make_llm", fail)
    monkeypatch.setattr(lm, "make_embedder", no_backend)
    monkeypatch.setattr(lm, "make_panel", no_backend)
    out = tmp_path / "run"
    report = lm.run_evaluation(cases, out, Settings(), score=True, system="retrieval")
    assert report["selected"] == report["prediction_failures"] == 2
    assert report["completed"] == report["scored"] == 0
    assert report["accuracy_selected"] == 0
    assert (out / "hypotheses.jsonl").read_text() == ""
    assert all("SECRET_BACKEND_CONFIG" not in (out / name).read_text() for name in lm.ARTIFACTS)


def test_duplicate_session_ids_future_dates_and_blank_turns(tmp_path: Path) -> None:
    raw = item()
    raw["haystack_session_ids"] = ["s1", "s1"]
    raw["haystack_dates"][1] = "2024/01/08 (Mon) 10:00"
    raw["haystack_sessions"][0][0]["content"] = "  "
    case = lm.load_dataset(dataset(tmp_path, [raw]))[0]
    assert [session.source_index for session in case.input.sessions] == [0, 1]
    assert [session.session_id for session in case.input.sessions] == ["s1", "s1"]
    assert case.input.sessions[0].turns[0].content == "  "
    llm = FakeLLM(lambda *_: {"hypothesis": "Atlas"})
    baseline = lm.HistoryBaseline(llm, HashingEmbedder(), Settings())
    baseline.predict(case.input)
    history = json.loads(llm.calls[0][2])["history"]
    assert {excerpt["session_index"] for excerpt in history} == {0, 1}
    assert any(excerpt["date"] == raw["haystack_dates"][1] for excerpt in history)
    assert all(excerpt["content"].strip() for excerpt in history)
    assert [(excerpt["session_index"], excerpt["turn"]) for excerpt in history] == [(0, 1), (1, 0), (1, 1)]
    assert len({entry["ref"] for entry in baseline.retrieval_manifest}) == 3


def test_all_blank_history_predicts_insufficient_evidence_without_embedding(tmp_path: Path) -> None:
    raw = item()
    for session in raw["haystack_sessions"]:
        for turn in session:
            turn["content"] = " \n"
    case = lm.load_dataset(dataset(tmp_path, [raw]))[0]
    embedder = SpyEmbedder()
    llm = FakeLLM(lambda *_: {"hypothesis": "Insufficient evidence."})
    baseline = lm.HistoryBaseline(llm, embedder, Settings())
    assert baseline.predict(case.input) == "Insufficient evidence."
    assert embedder.texts == [] and baseline.retrieval_manifest == []
    assert json.loads(llm.calls[0][2])["history"] == []
    assert "insufficient" in llm.calls[0][1]


def test_late_message_evidence_is_chunked_and_retrieved_deterministically(tmp_path: Path) -> None:
    raw = item()
    raw["question"] = "What is the zirconium observatory password?"
    raw["haystack_sessions"][0][1]["content"] = "Filler " * 600 + "zirconium observatory password: invented-Aster"
    case = lm.load_dataset(dataset(tmp_path, [raw]))[0]
    embedder = SpyEmbedder()
    llm = FakeLLM(lambda *_: {"hypothesis": "invented-Aster"})
    baseline = lm.HistoryBaseline(llm, embedder, Settings())
    baseline.predict(case.input)
    first_manifest = copy.deepcopy(baseline.retrieval_manifest)
    assert any("invented-Aster" in excerpt["content"] for excerpt in json.loads(llm.calls[0][2])["history"])
    assert any(entry["part"] > 0 for entry in first_manifest)
    baseline.predict(case.input)
    assert first_manifest == baseline.retrieval_manifest
    assert llm.calls[0][2] == llm.calls[1][2]


def test_two_case_indexes_and_prediction_prompts_are_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, second = item("first"), item("second")
    for session in first["haystack_sessions"]:
        for turn in session:
            turn["content"] = "FIRST_PRIVATE_MARKER cobalt telescope"
    for session in second["haystack_sessions"]:
        for turn in session:
            turn["content"] = "SECOND_PRIVATE_MARKER cobalt telescope"
    cases = lm.load_dataset(dataset(tmp_path, [first, second]))
    embedder = SpyEmbedder()
    second_embedding_start = 0
    calls = 0

    def predict(*_: Any) -> dict[str, Any]:
        nonlocal calls, second_embedding_start
        calls += 1
        if calls == 1:
            second_embedding_start = len(embedder.texts)
        return {"hypothesis": "Atlas"}

    llm = FakeLLM(predict)
    monkeypatch.setattr(lm, "make_llm", lambda *_: llm)
    monkeypatch.setattr(lm, "make_embedder", lambda *_: embedder)
    report = lm.run_evaluation(cases, tmp_path / "run", Settings(), system="retrieval")
    assert report["completed"] == 2
    assert "FIRST_PRIVATE_MARKER" not in llm.calls[1][2]
    assert "SECOND_PRIVATE_MARKER" in llm.calls[1][2]
    assert all("FIRST_PRIVATE_MARKER" not in text for text in embedder.texts[second_embedding_start:])
    assert any("SECOND_PRIVATE_MARKER" in text for text in embedder.texts[second_embedding_start:])


def test_abstention_subset_remains_in_original_type_metrics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = lm.load_dataset(dataset(tmp_path, [item("q_abs_middle"), item("q")]))
    monkeypatch.setattr(lm, "make_llm", lambda *_: FakeLLM(lambda *_: {"hypothesis": "Insufficient evidence."}))
    monkeypatch.setattr(lm, "make_embedder", lambda *_: HashingEmbedder())
    monkeypatch.setattr(lm, "make_panel", lambda *_: (Judge(FakeLLM(lambda *_: {"correct": True}), "low"),))
    report = lm.run_evaluation(cases, tmp_path / "run", Settings(), score=True, system="retrieval")
    assert set(report["categories"]) == set(lm.QUESTION_TYPES)
    assert report["selected"] == report["categories"]["single-session-assistant"]["selected"] == 2
    assert report["abstention"]["selected"] == 1
    assert report["accuracy_selected"] == report["abstention"]["accuracy_selected"] == 1


def test_cli_actual_without_config_reports_failure_and_nonzero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for key in ("TWIN_CONFIG", "TWIN_LLM_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    path = dataset(tmp_path)
    out = tmp_path / "run"
    result = CliRunner().invoke(app, ["eval-longmemeval", "--dataset", str(path), "--out", str(out)])
    assert result.exit_code == 1
    report = json.loads((out / "report.json").read_text())
    assert report["selected"] == report["prediction_failures"] == 1
    assert report["completed"] == 0 and report["pending"] == 0
    assert "prediction_failures=1" in result.output and "GOLD_ONLY" not in result.output
    assert report["fingerprints"]["dataset_sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert len(report["fingerprints"]["configuration"]) == 64
    assert not (tmp_path / "twin.toml").exists()


@pytest.mark.parametrize("failed_stage", ["prediction", "judge", "budget"])
def test_cli_failure_status_after_persisted_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failed_stage: str
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TWIN_CONFIG", raising=False)

    def fail(*_: Any) -> dict[str, Any]:
        if failed_stage == "budget":
            recorder = active_recorder()
            assert recorder is not None
            recorder.stop = BudgetExceeded("SECRET_STOP")
            raise recorder.stop
        raise RuntimeError("SECRET_FAILURE")

    monkeypatch.setattr(
        lm, "make_llm", lambda *_: FakeLLM(fail if failed_stage != "judge" else lambda *_: {"hypothesis": "Atlas"})
    )
    monkeypatch.setattr(lm, "make_embedder", lambda *_: HashingEmbedder())
    monkeypatch.setattr(lm, "make_panel", lambda *_: (Judge(FakeLLM(fail), "low"),))
    out = tmp_path / "run"
    result = CliRunner().invoke(
        app,
        [
            "eval-longmemeval",
            "--system",
            "retrieval",
            "--dataset",
            str(dataset(tmp_path, [item("a"), item("b")])),
            "--out",
            str(out),
            "--score",
        ],
    )
    assert result.exit_code == 1
    report = json.loads((out / "report.json").read_text())
    assert report["prediction_failures"] or report["judge_failures"]
    assert report["accuracy_selected"] == 0 and report["pending"] == 0
    if failed_stage == "budget":
        assert report["missing"] == 1 and report["budget_stopped"]
    assert "SECRET" not in result.output


def test_report_and_usage_do_not_serialize_custom_backend_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = FakeLLM(lambda *_: {"hypothesis": "Atlas"})
    llm.name = "https://user:SECRET_ID@private-host/v1"
    judge = FakeLLM(lambda *_: {"correct": True})
    judge.name = "PRIVATE_JUDGE_ID"
    monkeypatch.setattr(lm, "make_llm", lambda *_: llm)
    monkeypatch.setattr(lm, "make_embedder", lambda *_: HashingEmbedder())
    monkeypatch.setattr(lm, "make_panel", lambda *_: (Judge(judge, "low"),))
    out = tmp_path / "run"
    report = lm.run_evaluation(lm.load_dataset(dataset(tmp_path)), out, Settings(), score=True, system="retrieval")
    assert report["judges"] == ["j0"]
    assert len(report["fingerprints"]["runtime_configuration"]) == 64
    for name in lm.ARTIFACTS:
        assert "SECRET_ID" not in (out / name).read_text()
        assert "PRIVATE_JUDGE_ID" not in (out / name).read_text()


def test_per_type_sample_is_seeded_balanced_and_in_source_order(tmp_path: Path) -> None:
    items = [item(f"{t}-{i}", t) for t in lm.QUESTION_TYPES for i in range(4)]
    cases = lm.load_dataset(dataset(tmp_path, items))
    selected = lm.select_cases(cases, per_type=2)
    assert selected == lm.select_cases(cases, per_type=2)
    assert all(sum(c.question_type == t for c in selected) == 2 for t in lm.QUESTION_TYPES)
    order = [c.input.question_id for c in cases]
    assert [order.index(c.input.question_id) for c in selected] == sorted(
        order.index(c.input.question_id) for c in selected
    )
    with pytest.raises(ValueError):
        lm.select_cases(cases, per_type=5)


def test_dev_split_never_draws_formal_questions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lm, "FORMAL_PER_TYPE", 2)
    items = [item(f"{t}-{i}", t) for t in lm.QUESTION_TYPES for i in range(5)]
    cases = lm.load_dataset(dataset(tmp_path, items))
    formal = {c.input.question_id for c in lm.select_cases(cases, per_type=2)}
    dev = lm.select_cases(cases, per_type=3, split="dev")
    assert dev == lm.select_cases(cases, per_type=3, split="dev")
    assert not formal & {c.input.question_id for c in dev}
    assert all(sum(c.question_type == t for c in dev) == 3 for t in lm.QUESTION_TYPES)
    for options in ({"per_type": 4, "split": "dev"}, {"split": "dev"}, {"per_type": 1, "split": "holdout"}):
        with pytest.raises(ValueError):
            lm.select_cases(cases, **options)  # type: ignore[arg-type]
