"""Invented PersonaMem fixtures only: no upstream conversations or credentials."""

from __future__ import annotations

import csv
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from twin.config import Settings
from twin.embed import HashingEmbedder, Matrix
from twin.evals import personamem as pm
from twin.llm import FakeLLM
from twin.usage import BudgetExceeded, active_recorder


def item(qid: str = "invented-1", *, sid: str = "shared-1", cutoff: int = 3) -> dict[str, Any]:
    return {
        "question_id": qid,
        "question_type": pm.QUESTION_TYPES[0],
        "user_question_or_message": "Which invented cobalt telescope fits my desk?",
        "all_options": json.dumps(["(a) Atlas", "(b) Boreal", "(c) Coral", "(d) Delta"]),
        "correct_answer": "(b)",
        "shared_context_id": sid,
        "end_index_in_shared_context": cutoff,
        "question_date": "2025-01-05",
        "groundtruth_info": "GOLD_METADATA_MARKER",
        "unknown": "UNKNOWN_MARKER",
    }


def history() -> list[dict[str, Any]]:
    return [
        {"role": "system", "content": "Invented user profile: small desk.", "date": "2025-01-01"},
        {"role": "user", "content": "I need a cobalt telescope.", "date": "2025-01-02", "has_answer": True},
        {"role": "assistant", "content": "The fictional Boreal fits.", "date": "2025-01-03"},
        {"role": "user", "content": "FUTURE_GOLD_MARKER: Correct answer is (b).", "date": "2025-01-06"},
    ]


def dataset(
    tmp_path: Path,
    rows: list[dict[str, Any]] | None = None,
    contexts: dict[str, list[dict[str, Any]]] | None = None,
) -> tuple[Path, Path]:
    questions, context_path = tmp_path / "questions.csv", tmp_path / "contexts.jsonl"
    rows = rows if rows is not None else [item()]
    with questions.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    context_path.write_text(
        "".join(
            json.dumps({sid: turns}) + "\n"
            for sid, turns in (contexts if contexts is not None else {"shared-1": history()}).items()
        )
    )
    return questions, context_path


class SpyEmbedder(HashingEmbedder):
    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    def embed(self, texts: list[str]) -> Matrix:
        self.texts.extend(texts)
        return super().embed(texts)


def forbidden(*args: Any, **kwargs: Any) -> Any:
    pytest.fail("unexpected backend construction or call")


def test_exclusive_cutoff_and_whitelisted_answer_free_contract(tmp_path: Path) -> None:
    raw = item()
    case = pm.load_dataset(*dataset(tmp_path, [raw]))[0]
    boundary = json.dumps(asdict(case.input))
    for marker in ("FUTURE_GOLD", "correct_answer", "gold", "has_answer", "UNKNOWN", "GOLD_METADATA"):
        assert marker not in boundary
    assert [turn.role for turn in case.input.history] == ["system", "user", "assistant"]
    assert [turn.date for turn in case.input.history] == ["2025-01-01", "2025-01-02", "2025-01-03"]
    assert case.input.question_date == "2025-01-05"
    assert case.gold.correct_answer == "(b)" and case.gold.selection == "b"
    embedder = SpyEmbedder()
    llm = FakeLLM(lambda *_: {"selection": "b"})
    assert pm.HistoryBaseline(llm, embedder, Settings()).predict(case.input) == "<final_answer>(b)"
    all_text = " ".join([*embedder.texts, llm.calls[0][1], llm.calls[0][2]])
    assert all(marker not in all_text for marker in ("FUTURE_GOLD", "correct_answer", "has_answer", "GOLD_METADATA"))
    prompt = json.loads(llm.calls[0][2])
    assert prompt["options"] == json.loads(raw["all_options"])
    assert {turn["role"] for turn in prompt["history"]} == {"system", "user", "assistant"}
    assert "system-role messages" in llm.calls[0][1]


def test_shared_context_different_cutoffs_never_share_future_input(tmp_path: Path) -> None:
    cases = pm.load_dataset(*dataset(tmp_path, [item("early", cutoff=1), item("later", cutoff=4)]))
    assert len(cases[0].input.history) == 1 and len(cases[1].input.history) == 4
    embedder = SpyEmbedder()
    llm = FakeLLM(lambda *_: {"selection": "a"})
    baseline = pm.HistoryBaseline(llm, embedder, Settings())
    baseline.predict(cases[1].input)
    embedder.texts.clear()
    baseline.predict(cases[0].input)
    assert "FUTURE_GOLD" not in " ".join([*embedder.texts, llm.calls[-1][2]])
    assert all(entry["turn"] == 0 for entry in baseline.retrieval_manifest)


@pytest.mark.parametrize("encoded", [json.dumps(["one", "two", "three", "four"]), "['one', 'two', 'three', 'four']"])
def test_option_parsing(encoded: str) -> None:
    assert pm.parse_options(encoded) == ("one", "two", "three", "four")


@pytest.mark.parametrize(
    "value",
    [
        "garbage",
        "[]",
        '["a", "b", "c"]',
        '["(b) X", "(a) Y", "(c) Z", "(d) W"]',
        '["(a) X", "Y", "(c) Z", "(d) W"]',
        '["X", "Y", 3, "W"]',
        "__import__('os').getcwd()",
    ],
)
def test_options_invalid_and_sanitized(value: str) -> None:
    with pytest.raises(ValueError, match="Invalid PersonaMem options") as error:
        pm.parse_options(value)
    assert value not in str(error.value)


@pytest.mark.parametrize(("value", "expected"), [(0, "a"), (1, "b"), (3, "d"), ("2", "c"), ("(C)", "c"), (" a ", "a")])
def test_numeric_labels_are_zero_based_and_letters_case_insensitive(value: str | int, expected: str) -> None:
    assert pm.normalize_selection(value) == expected


@pytest.mark.parametrize("value", [True, -1, 4, "4", "a or b", "", "Atlas"])
def test_ambiguous_selection_rejected(value: Any) -> None:
    with pytest.raises(ValueError):
        pm.normalize_selection(value)


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        ("<final_answer>(B)</final_answer>", True),
        ("Reason (a), then <final_answer>(b)", True),
        ("(b) <final_answer>unparseable", True),
        ("(a) <final_answer>(d)", False),
        ("<final_answer>(a) or (b)", False),
        ("<final_answer>b", True),
        ("<final_answer>1", False),
        ("No choice", False),
    ],
)
def test_verified_official_choice_extraction(response: str, expected: bool) -> None:
    assert pm.official_score(response, "(b)") is expected


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("end_index_in_shared_context", -1),
        ("end_index_in_shared_context", 5),
        ("end_index_in_shared_context", "1.5"),
        ("shared_context_id", "absent"),
        ("question_type", "SECRET_CATEGORY"),
        ("correct_answer", "SECRET_GOLD"),
        ("user_question_or_message", ""),
    ],
)
def test_loader_validation_sanitizes_errors(tmp_path: Path, field: str, value: Any) -> None:
    raw = item()
    raw[field] = value
    with pytest.raises(ValueError, match="Invalid PersonaMem dataset") as error:
        pm.load_dataset(*dataset(tmp_path, [raw]))
    assert "SECRET" not in str(error.value) and error.value.__suppress_context__


def test_missing_dates_empty_prefix_and_duplicate_ids(tmp_path: Path) -> None:
    raw = item(cutoff=0)
    raw.pop("question_date")
    case = pm.load_dataset(*dataset(tmp_path, [raw]))[0]
    assert case.input.history == () and case.input.question_date == ""
    llm = FakeLLM(lambda *_: {"selection": "c"})
    embedder = SpyEmbedder()
    pm.HistoryBaseline(llm, embedder, Settings()).predict(case.input)
    assert embedder.texts == []
    with pytest.raises(ValueError):
        pm.load_dataset(*dataset(tmp_path, [item(), item()]))


def test_invalid_context_and_duplicate_context_keys(tmp_path: Path) -> None:
    paths = dataset(tmp_path)
    paths[1].write_text(paths[1].read_text() * 2)
    with pytest.raises(ValueError):
        pm.load_dataset(*paths)
    bad = history()
    bad[0]["role"] = "SECRET_ROLE"
    with pytest.raises(ValueError):
        pm.load_dataset(*dataset(tmp_path, contexts={"shared-1": bad}))


def test_select_default_three_and_offsets(tmp_path: Path) -> None:
    cases = pm.load_dataset(*dataset(tmp_path, [item(str(i)) for i in range(5)]))
    assert [case.input.question_id for case in pm.select_cases(cases)] == ["0", "1", "2"]
    assert [case.input.question_id for case in pm.select_cases(cases, limit=2, offset=2)] == ["2", "3"]
    for limit, offset in [(0, 0), (1, -1), (3, 5)]:
        with pytest.raises(ValueError):
            pm.select_cases(cases, limit=limit, offset=offset)


def test_retrieval_bounds_and_per_case_isolation(tmp_path: Path) -> None:
    first = history()[:3] + [{"role": "user", "content": "cobalt " + "z" * 3200} for _ in range(20)]
    cases = pm.load_dataset(
        *dataset(
            tmp_path,
            [item("first", cutoff=len(first)), item("second", sid="shared-2", cutoff=1)],
            {"shared-1": first, "shared-2": [{"role": "user", "content": "ONLY_SECOND"}]},
        )
    )
    llm = FakeLLM(lambda *_: {"selection": "a"})
    baseline = pm.HistoryBaseline(llm, SpyEmbedder(), Settings())
    baseline.predict(cases[0].input)
    evidence = json.loads(llm.calls[0][2])["history"]
    assert len(evidence) <= pm.TOP_K
    assert sum(len(json.dumps(excerpt, ensure_ascii=False)) for excerpt in evidence) <= pm.CONTEXT_CHARS
    assert all(len(excerpt["content"]) <= pm.CHUNK_CHARS for excerpt in evidence)
    assert [(ex["turn"], ex["part"]) for ex in evidence] == sorted((ex["turn"], ex["part"]) for ex in evidence)
    baseline.predict(cases[1].input)
    assert "cobalt" not in json.dumps(json.loads(llm.calls[-1][2])["history"])
    assert "ONLY_SECOND" in llm.calls[-1][2]
    assert len(baseline.retrieval_manifest) == 1


def test_dryrun_zero_calls_private_artifacts_no_overwrite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = pm.load_dataset(*dataset(tmp_path))
    monkeypatch.setattr(pm, "make_llm", forbidden)
    monkeypatch.setattr(pm, "make_embedder", forbidden)
    out = tmp_path / "private" / "run"
    report = pm.run_evaluation(cases, out, Settings(), dry_run=True, score=True, system="retrieval")
    assert report["selected"] == report["missing"] == 1
    assert report["completed"] == report["scored"] == report["prediction_failures"] == 0
    assert report["accuracy_selected"] is report["accuracy_scored"] is None
    assert json.loads((out / "usage.json").read_text())["totals"]["calls"] == 0
    assert (out / "hypotheses.jsonl").read_text() == ""
    assert out.stat().st_mode & 0o777 == 0o700
    assert all((out / name).stat().st_mode & 0o777 == 0o600 for name in pm.ARTIFACTS)
    before = {name: (out / name).read_bytes() for name in pm.ARTIFACTS}
    with pytest.raises(ValueError, match="already contains"):
        pm.run_evaluation(cases, out, Settings(), dry_run=True, system="retrieval")
    assert before == {name: (out / name).read_bytes() for name in pm.ARTIFACTS}
    assert "correct_answer" not in (out / "records.jsonl").read_text()


def test_output_and_provenance_validation_before_backends(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = pm.load_dataset(*dataset(tmp_path))
    monkeypatch.setattr(pm, "make_llm", forbidden)
    root = Path(__file__).resolve().parents[1]
    with pytest.raises(ValueError):
        pm.run_evaluation(cases, root / "private-run", Settings(), system="retrieval")
    out = tmp_path / "external"
    out.mkdir()
    (out / "hypotheses.jsonl").symlink_to(root / "README.md")
    with pytest.raises(ValueError):
        pm.run_evaluation(cases, out, Settings(), system="retrieval")
    for provenance in ({"configuration": "SECRET"}, {"unknown": "f" * 64}):
        with pytest.raises(ValueError):
            pm.run_evaluation(cases, tmp_path / "fresh", Settings(), fingerprints=provenance, system="retrieval")
    assert not (tmp_path / "fresh").exists()


def test_exact_scoring_failure_denominators_and_private_gold(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [item(str(i)) for i in range(3)]
    rows[2]["question_type"] = pm.QUESTION_TYPES[1]
    cases = pm.load_dataset(*dataset(tmp_path, rows))
    outputs = iter([{"selection": "b"}, {"selection": "a"}, {"selection": "SECRET_BAD_OUTPUT"}])
    llm = FakeLLM(lambda *_: next(outputs))
    monkeypatch.setattr(pm, "make_llm", lambda *_: llm)
    monkeypatch.setattr(pm, "make_embedder", lambda *_: HashingEmbedder())
    out = tmp_path / "run"
    report = pm.run_evaluation(
        cases,
        out,
        Settings(),
        score=True,
        fingerprints={"questions_sha256": "a" * 64, "contexts_sha256": "b" * 64},
        system="retrieval",
    )
    assert report["selected"] == 3 and report["completed"] == report["scored"] == 2
    assert report["prediction_failures"] == report["unscored"] == 1 and report["missing"] == 0
    assert report["accuracy_selected"] == pytest.approx(1 / 3)
    assert report["accuracy_scored"] == 0.5
    assert report["categories"][pm.QUESTION_TYPES[0]]["accuracy_selected"] == 0.5
    assert report["categories"][pm.QUESTION_TYPES[1]]["prediction_failures"] == 1
    predictions = [json.loads(line) for line in (out / "hypotheses.jsonl").read_text().splitlines()]
    assert predictions[0]["model_response"] == "<final_answer>(b)" and predictions[0]["selection"] == "b"
    assert all("correct_answer" not in prediction and "gold_selection" not in prediction for prediction in predictions)
    records = [json.loads(line) for line in (out / "records.jsonl").read_text().splitlines()]
    assert records[0]["correct_answer"] == "(b)" and records[0]["gold_selection"] == "b"
    assert all("SECRET_BAD_OUTPUT" not in (out / name).read_text() for name in pm.ARTIFACTS)
    assert len(llm.calls) == 3  # No judge calls.
    assert len(report["fingerprints"]["runtime_configuration"]) == 64


def test_setup_failure_counts_all_and_sanitizes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = pm.load_dataset(*dataset(tmp_path, [item("a"), item("b")]))

    def fail(*_: Any) -> Any:
        raise RuntimeError("SECRET_BACKEND_CONFIG")

    monkeypatch.setattr(pm, "make_llm", fail)
    monkeypatch.setattr(pm, "make_embedder", forbidden)
    out = tmp_path / "run"
    report = pm.run_evaluation(cases, out, Settings(), score=True, system="retrieval")
    assert report["selected"] == report["prediction_failures"] == 2
    assert report["completed"] == report["scored"] == report["missing"] == 0
    assert report["accuracy_selected"] == 0 and report["accuracy_scored"] is None
    assert all("SECRET_BACKEND_CONFIG" not in (out / name).read_text() for name in pm.ARTIFACTS)


def test_budget_stop_counts_failure_then_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = pm.load_dataset(*dataset(tmp_path, [item("a"), item("b"), item("c")]))

    def stop(*_: Any) -> dict[str, str]:
        recorder = active_recorder()
        assert recorder is not None
        recorder.stop = BudgetExceeded("SECRET_BUDGET")
        raise recorder.stop

    monkeypatch.setattr(pm, "make_llm", lambda *_: FakeLLM(stop))
    monkeypatch.setattr(pm, "make_embedder", lambda *_: HashingEmbedder())
    report = pm.run_evaluation(cases, tmp_path / "run", Settings(), score=True, system="retrieval")
    assert report["budget_stopped"] and report["selected"] == 3
    assert report["prediction_failures"] == 1 and report["missing"] == 2
    assert report["completed"] == report["scored"] == 0
    assert report["accuracy_selected"] == 0 and report["accuracy_scored"] is None


def test_structured_choice_strict_and_score_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for invalid in ("(b)", "B", "b or c", 1, True):
        with pytest.raises(ValidationError):
            pm.Answer.model_validate({"selection": invalid})
    cases = pm.load_dataset(*dataset(tmp_path))
    monkeypatch.setattr(pm, "make_llm", lambda *_: FakeLLM(lambda *_: {"selection": "b"}))
    monkeypatch.setattr(pm, "make_embedder", lambda *_: HashingEmbedder())
    out = tmp_path / "run"
    report = pm.run_evaluation(cases, out, Settings(), system="retrieval")
    assert report["completed"] == 1 and report["scored"] == 0
    assert report["accuracy_selected"] is report["accuracy_scored"] is None
    assert "correct_answer" not in (out / "records.jsonl").read_text()


def test_gold_changes_do_not_change_inputs_or_predictions(tmp_path: Path) -> None:
    rows = [item("same")]
    before = pm.load_dataset(*dataset(tmp_path, rows))[0]
    rows[0]["correct_answer"] = "3"
    after = pm.load_dataset(*dataset(tmp_path, rows))[0]
    assert before.input == after.input
    assert before.gold.selection == "b" and after.gold.selection == "d"
    llm = FakeLLM(lambda *_: {"selection": "b"})
    baseline = pm.HistoryBaseline(llm, SpyEmbedder(), Settings())
    assert baseline.predict(before.input) == baseline.predict(after.input)
    assert llm.calls[0] == llm.calls[1]


def test_usage_hashes_custom_backend_identity(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = pm.load_dataset(*dataset(tmp_path))
    llm = FakeLLM(lambda *_: {"selection": "a"})
    llm.name = "SECRET_CUSTOM_MODEL"
    embedder = HashingEmbedder()
    embedder.name = "SECRET_CUSTOM_EMBEDDER"
    monkeypatch.setattr(pm, "make_llm", lambda *_: llm)
    monkeypatch.setattr(pm, "make_embedder", lambda *_: embedder)
    out = tmp_path / "run"
    pm.run_evaluation(cases, out, Settings(), system="retrieval")
    calls = [json.loads(line) for line in (out / "calls.jsonl").read_text().splitlines()]
    assert len(calls) == 3
    assert all(row["model"].startswith("sha256:") and row["backend"].startswith("sha256:") for row in calls)
    assert all("SECRET_CUSTOM" not in (out / name).read_text() for name in pm.ARTIFACTS)
    stages = json.loads((out / "usage.json").read_text())["stages"]
    assert {row["stage"] for row in stages} == {"personamem.retrieval", "personamem.prediction"}


def test_random_sample_is_seeded_and_in_source_order(tmp_path: Path) -> None:
    cases = pm.load_dataset(*dataset(tmp_path, [item(str(i)) for i in range(8)]))
    selected = [c.input.question_id for c in pm.select_cases(cases, sample=4)]
    assert selected == [c.input.question_id for c in pm.select_cases(cases, sample=4)]
    assert len(selected) == 4 and selected == sorted(selected, key=int)
    for sample in (0, 9):
        with pytest.raises(ValueError):
            pm.select_cases(cases, sample=sample)


def test_dev_split_never_shares_a_context_with_the_formal_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pm, "FORMAL_SAMPLE", 2)
    sids = [f"shared-{i}" for i in range(6)]
    rows = [item(f"{s}-{q}", sid=s) for s in sids for q in range(2)]
    cases = pm.load_dataset(*dataset(tmp_path, rows, {s: history() for s in sids}))
    formal = {c.input.subject_id for c in pm.select_cases(cases, sample=2)}
    dev = pm.select_cases(cases, sample=4, split="dev")
    assert dev == pm.select_cases(cases, sample=4, split="dev") and len(dev) == 4
    assert not formal & {c.input.subject_id for c in dev}
    rest = sum(c.input.subject_id not in formal for c in cases)
    for options in ({"sample": rest + 1, "split": "dev"}, {"split": "dev"}, {"sample": 1, "split": "holdout"}):
        with pytest.raises(ValueError):
            pm.select_cases(cases, **options)  # type: ignore[arg-type]
