"""Invented fixtures matching the publicly verified wave_split schema."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest

from twin.config import LLMSettings, Settings
from twin.evals import twin2k500 as bench
from twin.llm import FakeLLM
from twin.usage import BudgetExceeded, active_recorder
from twin.util import fingerprint


def questions() -> list[dict[str, Any]]:
    return [
        {"QuestionID": "intro", "QuestionType": "DB", "QuestionText": "Invented survey instructions."},
        {
            "QuestionID": "choice",
            "QuestionType": "MC",
            "QuestionText": "Choose a fictional telescope.",
            "Options": ["Atlas", "Boreal"],
            "Settings": {"Selector": "SAVR"},
            "Answers": {"SelectedByPosition": 2, "SelectedText": "Boreal"},
        },
        {
            "QuestionID": "matrix",
            "QuestionType": "Matrix",
            "QuestionText": "Rate these fictional objects.",
            "Rows": ["Cobalt", "Silver"],
            "RowsID": ["1", "10"],
            "Columns": ["Low", "High"],
            "Settings": {"Selector": "Likert", "SubSelector": "SingleAnswer"},
            "Answers": {"SelectedByPosition": [1, 2], "SelectedText": ["Low", "High"]},
        },
        {
            "QuestionID": "slider",
            "QuestionType": "Slider",
            "QuestionText": "Give a probability.",
            "Statements": [""],
            "Range": {"Min": 0, "Max": 100, "Ticks": 10},
            "Settings": {"Selector": "HSLIDER"},
            "Answers": {"Values": ["87"]},
        },
        {
            "QuestionID": "number",
            "QuestionType": "TE",
            "QuestionText": "How many invented moons?",
            "Settings": {"Selector": "SL", "ContentType": "ValidNumber"},
            "Answers": {"Text": "1234567"},
        },
    ]


def blocks(qs: list[dict[str, Any]]) -> str:
    return json.dumps([{"ElementType": "Block", "BlockName": "Invented", "BlockType": "Standard", "Questions": qs}])


def row(pid: int = 7) -> dict[str, Any]:
    qs = questions()
    human = copy.deepcopy(qs)
    human[-1]["Answers"]["Text"] = "7654321"
    for q in qs:
        q["unknown"] = "FUTURE_SECRET"
    return {
        "pid": pid,
        "wave1_3_persona_text": f"PAST_PERSON_{pid} likes a fictional cobalt telescope.",
        "wave1_3_persona_json": blocks([]),
        "wave4_Q_wave4_A": blocks(qs),
        "wave4_Q_wave1_3_A": blocks(human),
        "wave5": "FUTURE_SECRET",
    }


def dataset(tmp_path: Path, rows: list[dict[str, Any]] | None = None) -> Path:
    path = tmp_path / "wave_split.json"
    path.write_text(json.dumps(rows if rows is not None else [row()]))
    return path


def test_real_schema_expansion_and_gold_boundary(tmp_path: Path) -> None:
    cases = bench.load_dataset(dataset(tmp_path))
    assert len(cases) == 5
    assert [c.input.item_id for c in cases] == ["choice", "1", "10", "1", "number"]
    assert cases[3].input.numeric_range == (0, 100)
    assert cases[-1].gold == bench.Gold(1234567, 7654321)
    contract = json.dumps([asdict(c.input) for c in cases])
    for secret in ("FUTURE_SECRET", "1234567", "7654321", "SelectedByPosition", "Answers"):
        assert secret not in contract
    assert cases[0].input.choices == ("Atlas", "Boreal")
    assert "Invented survey instructions." in contract


@pytest.mark.parametrize("field", ["persona_text", "persona_json", "persona_summary"])
def test_full_persona_rejected(tmp_path: Path, field: str) -> None:
    raw = row()
    raw[field] = "WAVE4_LEAK"
    with pytest.raises(ValueError, match="Invalid Twin") as error:
        bench.load_dataset(dataset(tmp_path, [raw]))
    assert "WAVE4_LEAK" not in str(error.value)
    assert error.value.__suppress_context__


def test_json_persona_fallback_and_folder(tmp_path: Path) -> None:
    raw = row()
    del raw["wave1_3_persona_text"]
    past = questions()[:2]
    past[1]["unknown"] = "PAST_UNKNOWN_SECRET"
    past.append(
        {
            "QuestionID": "past-entry",
            "QuestionType": "TE",
            "QuestionText": "Name an invented animal.",
            "Answers": {"Text": [{"word 1": "glowbird"}, {"word 2": "cloudcat"}]},
        }
    )
    past.append(
        {
            "QuestionID": "blank-past",
            "QuestionType": "MC",
            "QuestionText": "",
            "Answers": {"SelectedText": "UNINTERPRETABLE_PAST"},
        }
    )
    raw["wave1_3_persona_json"] = blocks(past)
    dataset(tmp_path, [raw])
    cases = bench.load_dataset(tmp_path)
    assert "SelectedText" in cases[0].input.persona
    assert "PAST_UNKNOWN_SECRET" not in cases[0].input.persona
    assert "UNINTERPRETABLE_PAST" not in cases[0].input.persona
    assert "glowbird" in cases[0].input.persona and "cloudcat" in cases[0].input.persona


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate_pid",
        "duplicate_qid",
        "short_matrix",
        "extra_matrix",
        "bad_position",
        "label_mismatch",
        "nan",
        "bool",
        "range",
        "bad_pid",
    ],
)
def test_invalid_schema_sanitized(tmp_path: Path, mutation: str) -> None:
    raw = row()
    qs = questions()
    rows = [raw]
    if mutation == "duplicate_pid":
        rows.append(copy.deepcopy(raw))
    elif mutation == "duplicate_qid":
        qs.append(qs[1])
    elif mutation in ("short_matrix", "extra_matrix"):
        qs[2]["Answers"]["SelectedByPosition"] = [1] if mutation == "short_matrix" else [1, 2, 1]
    elif mutation == "bad_position":
        qs[1]["Answers"]["SelectedByPosition"] = 0
    elif mutation == "label_mismatch":
        qs[1]["Answers"]["SelectedText"] = "SECRET"
    elif mutation in ("nan", "bool"):
        qs[4]["Answers"]["Text"] = "NaN" if mutation == "nan" else True
    elif mutation == "range":
        qs[3]["Answers"]["Values"] = [101]
    else:
        raw["pid"] = True
    raw["wave4_Q_wave4_A"] = blocks(qs)
    with pytest.raises(ValueError, match="Invalid Twin") as error:
        bench.load_dataset(dataset(tmp_path, rows))
    assert "SECRET" not in str(error.value)


def test_comparator_requires_identical_question(tmp_path: Path) -> None:
    raw = row()
    qs = questions()
    qs[1]["Options"].reverse()
    raw["wave4_Q_wave1_3_A"] = blocks(qs)
    with pytest.raises(ValueError):
        bench.load_dataset(dataset(tmp_path, [raw]))


def test_selection_counts_items_and_explicit_participants(tmp_path: Path) -> None:
    cases = bench.load_dataset(dataset(tmp_path, [row(7), row(8)]))
    assert len(bench.select_cases(cases)) == 3
    selected = bench.select_cases(cases, participant_ids=["8"], offset=1, limit=2)
    assert {c.input.participant_id for c in selected} == {"8"}
    assert [c.input.item_id for c in selected] == ["1", "10"]
    for options in ({"limit": 0}, {"offset": 100}, {"participant_ids": ["9"]}):
        with pytest.raises(ValueError):
            bench.select_cases(cases, **options)


def test_native_grading_and_units(tmp_path: Path) -> None:
    cases = bench.load_dataset(dataset(tmp_path))
    assert bench.grade_answer(cases[0], "Boreal")["exact_match"] == 1
    assert bench.grade_answer(cases[0], "2")["exact_match"] == 0
    for answer in (None, "", "Atlas or Boreal"):
        assert bench.grade_answer(cases[0], answer) == {
            "exact_match": 0,
            "absolute_error": None,
            "normalized_absolute_error": None,
        }
    assert bench.grade_answer(cases[3], "77") == {
        "exact_match": None,
        "absolute_error": 10,
        "normalized_absolute_error": 0.1,
    }
    assert bench.grade_answer(cases[4], "1234560")["absolute_error"] == 7
    assert bench.grade_answer(cases[4], "1234560")["normalized_absolute_error"] is None
    for answer in ("101", "NaN", "", "probably 87"):
        assert bench.grade_answer(cases[3], answer)["absolute_error"] is None
    missing = bench.Case(cases[0].input, "categorical", bench.Gold(None))
    assert bench.grade_answer(missing, "Boreal")["exact_match"] is None


def test_gold_free_bounded_prompts_and_participant_isolation(tmp_path: Path) -> None:
    cases = bench.load_dataset(dataset(tmp_path, [row(7), row(8)]))
    prompts: list[str] = []

    def predict(system: str, user: str, schema: Any) -> dict[str, str]:
        prompts.append(user)
        data = json.loads(user)
        assert sum(map(len, data["persona_excerpts"])) <= bench.CONTEXT_CHARS
        return {"answer": "Atlas"}

    baseline = bench.PersonaBaseline(FakeLLM(predict), Settings())
    for c in (cases[0], cases[5]):
        baseline.predict(replace(c.input, persona=c.input.persona * 1000))
        assert len(baseline.retrieval_manifest) <= bench.TOP_K
    assert "PAST_PERSON_8" not in prompts[0]
    assert "PAST_PERSON_7" not in prompts[1]
    assert all(s not in "".join(prompts) for s in ("FUTURE_SECRET", "1234567", "7654321", "Answers"))
    assert json.loads(prompts[0])["choices"] == ["Atlas", "Boreal"]


@pytest.mark.parametrize("system", ["twin", "retrieval"])
def test_dry_run_private_no_overwrite_and_no_calls(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, system: str
) -> None:
    calls = []

    def fail(*args: Any) -> Any:
        calls.append(args)
        raise AssertionError("Must not construct backend")

    monkeypatch.setattr(bench, "make_llm", fail)
    cases = bench.select_cases(bench.load_dataset(dataset(tmp_path)))
    out = tmp_path / "run"
    report = bench.run_evaluation(cases, out, Settings(), dry_run=True, system=system)
    assert calls == []
    assert report["selected"] == report["missing"] == 3
    assert report["completed"] == report["scored"] == 0
    assert json.loads((out / "usage.json").read_text())["totals"]["calls"] == 0
    assert out.stat().st_mode & 0o777 == 0o700
    assert all((out / f).stat().st_mode & 0o777 == 0o600 for f in bench.ARTIFACTS)
    before = (out / "report.json").read_bytes()
    with pytest.raises(ValueError, match="already exist"):
        bench.run_evaluation(cases, out, Settings(), dry_run=True, system="retrieval")
    assert (out / "report.json").read_bytes() == before
    with pytest.raises(ValueError):
        bench.run_evaluation(cases, Path.cwd() / "private-run", Settings(), dry_run=True, system="retrieval")


def test_run_configuration_coverage_and_comparator(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    configs = []

    def make(config: LLMSettings) -> FakeLLM:
        configs.append(config.model)
        return FakeLLM(lambda *_: {"answer": "Boreal"})

    monkeypatch.setattr(bench, "make_llm", make)
    settings = Settings(llm=LLMSettings(model="main"), chat_llm=LLMSettings(model="reader"))
    report = bench.run_evaluation(bench.load_dataset(dataset(tmp_path)), tmp_path / "run", settings, system="retrieval")
    assert configs == ["reader"]
    assert report["completed"] == 5
    assert report["categorical_scored"] == 3
    assert report["scored"] == 3 and report["score_coverage"] == 3 / 5
    assert report["human_test_retest"]["scored"] == 5
    assert len(report["participants"]) == 1
    assert "numeric_mae" not in report
    assert all(len(v) == 64 for v in report["fingerprints"].values())
    artifacts = "".join(p.read_text() for p in (tmp_path / "run").iterdir())
    assert "1234567" not in artifacts and "7654321" not in artifacts


def test_failure_sanitization_and_budget_stop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any) -> Any:
        recorder = active_recorder()
        assert recorder is not None
        recorder.stop = BudgetExceeded("SECRET_BUDGET")
        raise RuntimeError("SECRET_BACKEND")

    monkeypatch.setattr(bench, "make_llm", lambda *_: FakeLLM(fail))
    report = bench.run_evaluation(
        bench.select_cases(bench.load_dataset(dataset(tmp_path))), tmp_path / "run", Settings(), system="retrieval"
    )
    assert report["prediction_failures"] == 1
    assert report["missing"] == 2
    assert report["budget_stopped"] and report["scored"] == 0
    assert "SECRET" not in "".join(p.read_text() for p in (tmp_path / "run").iterdir())


def test_symlink_artifact_and_unsafe_provenance(tmp_path: Path) -> None:
    cases = bench.select_cases(bench.load_dataset(dataset(tmp_path)))
    out = tmp_path / "run"
    out.mkdir()
    (out / "hypotheses.jsonl").symlink_to(tmp_path / "missing")
    with pytest.raises(ValueError):
        bench.run_evaluation(cases, out, Settings(), dry_run=True, system="retrieval")
    with pytest.raises(ValueError, match="Provenance"):
        bench.run_evaluation(
            cases,
            tmp_path / "other",
            Settings(),
            dry_run=True,
            fingerprints={"dataset_sha256": "SECRET"},
            system="retrieval",
        )


def test_unsupported_missing_gold_and_disabled_score(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    raw = row()
    qs = questions()
    qs[1]["Settings"]["Selector"] = "MAVR"
    qs[2]["Answers"] = {}
    raw["wave4_Q_wave4_A"] = blocks(qs)
    raw.pop("wave4_Q_wave1_3_A")
    cases = bench.load_dataset(dataset(tmp_path, [raw]))
    monkeypatch.setattr(bench, "make_llm", lambda *_: FakeLLM(lambda *_: {"answer": "87"}))
    report = bench.run_evaluation(cases, tmp_path / "run", Settings(), score=False, system="retrieval")
    assert report["unsupported"] == 1
    assert report["completed"] == 4
    assert report["gold_missing"] == 3
    assert report["scored"] == report["human_test_retest"]["scored"] == 0


def test_backend_setup_failure_returns_sanitized_report(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: Any) -> Any:
        raise RuntimeError("SECRET_SETUP")

    monkeypatch.setattr(bench, "make_llm", fail)
    report = bench.run_evaluation(
        bench.select_cases(bench.load_dataset(dataset(tmp_path))), tmp_path / "run", Settings(), system="retrieval"
    )
    assert report["prediction_failures"] == 3
    assert report["completed"] == report["scored"] == 0
    assert report["unscored"] == 3 and report["score_coverage"] == 0
    assert report["human_test_retest"]["completed"] == 3
    assert "SECRET_SETUP" not in "".join(p.read_text() for p in (tmp_path / "run").iterdir())


def test_retrieval_empty_and_invalid_choices_count_as_incorrect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = bench.load_dataset(dataset(tmp_path))[0]
    responses = iter(("Boreal", "Atlas", "", "Boreal or Atlas"))
    monkeypatch.setattr(bench, "make_llm", lambda _: FakeLLM(lambda *_: {"answer": next(responses)}))
    report = bench.run_evaluation([case] * 4, tmp_path / "run", Settings(), system="retrieval")
    assert report["completed"] == report["categorical_scored"] == report["scored"] == 4
    assert report["categorical_accuracy"] == 0.25 and report["score_coverage"] == 1
    assert report["unscored"] == report["prediction_failures"] == 0
    rows = [json.loads(line) for line in (tmp_path / "run" / "records.jsonl").read_text().splitlines()]
    assert [r["scores"]["exact_match"] for r in rows] == [1, 0, 0, 0]
    assert [r["model_response"] for r in rows] == ["Boreal", "Atlas", "", "Boreal or Atlas"]


def test_jsonl_streaming_matches_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [row(7), row(8)]
    expected = bench.load_dataset(dataset(tmp_path, rows))
    path = tmp_path / "export.jsonl"
    path.write_text("\n" + "\n\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    def reject_whole_file_read(*args: Any) -> Any:
        raise AssertionError("JSONL must stream lines rather than read the whole file")

    monkeypatch.setattr(Path, "read_bytes", reject_whole_file_read)
    assert bench.load_dataset(path) == expected
    # Parsing stays lazy: a later malformed line cannot prevent yielding the first row.
    path.write_text(json.dumps(rows[0]) + "\nSECRET_INVALID_JSON\n", encoding="utf-8")
    iterator = bench._read_rows(path)
    assert next(iterator) == rows[0]
    with pytest.raises(ValueError):
        next(iterator)
    with pytest.raises(ValueError, match="Invalid Twin") as error:
        bench.load_dataset(path)
    assert "SECRET_INVALID_JSON" not in str(error.value)
    assert error.value.__suppress_context__


@pytest.mark.parametrize("nested", [False, True])
def test_directory_discovers_json_and_jsonl(tmp_path: Path, nested: bool) -> None:
    expected = bench.load_dataset(dataset(tmp_path, [row(7), row(8)]))
    root = tmp_path / "exports"
    files = root / "wave_split" / "chunks" if nested else root
    files.mkdir(parents=True)
    (files / "01.jsonl").write_text(json.dumps(row(7)) + "\n")
    (files / "02.json").write_text(json.dumps([row(8)]))
    assert bench.load_dataset(root) == expected


@pytest.mark.parametrize("contents", ["", "\n \n", "[]\n", "42\n", "null\n", "{invalid SECRET}\n"])
def test_jsonl_invalid_or_empty_sanitized(tmp_path: Path, contents: str) -> None:
    path = tmp_path / "invalid.jsonl"
    path.write_text(contents)
    with pytest.raises(ValueError, match="Invalid Twin") as error:
        bench.load_dataset(path)
    assert "SECRET" not in str(error.value)
    assert error.value.__suppress_context__


def test_jsonl_duplicate_participants_rejected(tmp_path: Path) -> None:
    path = tmp_path / "duplicate.jsonl"
    path.write_text((json.dumps(row()) + "\n") * 2)
    with pytest.raises(ValueError, match="Invalid Twin"):
        bench.load_dataset(path)


@pytest.mark.parametrize("dry_run", [False, True])
def test_caller_configuration_fingerprint_preserved(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dry_run: bool,
) -> None:
    cases = bench.select_cases(bench.load_dataset(dataset(tmp_path)))
    settings = Settings(chat_llm=LLMSettings(model="invented-reader"))
    caller = {"configuration": fingerprint({"limit": 3, "offset": 2})}
    original = caller.copy()
    llm = FakeLLM(lambda *_: {"answer": "Boreal"})
    monkeypatch.setattr(bench, "make_llm", lambda *_: llm)
    report = bench.run_evaluation(
        cases, tmp_path / "run", settings, dry_run=dry_run, fingerprints=caller, system="retrieval"
    )
    assert caller == original
    assert report["fingerprints"]["configuration"] == caller["configuration"]
    if not dry_run:
        assert report["fingerprints"]["runtime_configuration"] == fingerprint(
            {
                "configuration": caller["configuration"],
                "settings_sha256": fingerprint(settings.model_dump(mode="json")),
                "llm": llm.name,
                "retrieval": [bench.CHUNK_CHARS, bench.CONTEXT_CHARS, bench.TOP_K],
                **bench.report_system("retrieval", bench.SYSTEM_LABEL),
            }
        )


def test_runtime_fingerprint_tracks_actual_settings_with_fixed_caller_digest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cases = bench.select_cases(bench.load_dataset(dataset(tmp_path)))
    monkeypatch.setattr(bench, "make_llm", lambda *_: FakeLLM(lambda *_: {"answer": "Boreal"}))
    supplied = {"configuration": fingerprint({"limit": 3, "offset": 0})}
    reports = [
        bench.run_evaluation(
            cases,
            tmp_path / f"run-{i}",
            Settings(chat_llm=LLMSettings(model=model)),
            fingerprints=supplied,
            system="retrieval",
        )
        for i, model in enumerate(("invented-a", "invented-b"))
    ]
    assert reports[0]["fingerprints"]["configuration"] == reports[1]["fingerprints"]["configuration"]
    assert reports[0]["fingerprints"]["runtime_configuration"] != reports[1]["fingerprints"]["runtime_configuration"]
    settings = Settings()
    fallback = bench.run_evaluation(cases, tmp_path / "fallback", settings, dry_run=True, system="retrieval")
    assert fallback["fingerprints"]["configuration"] == fingerprint(settings.model_dump(mode="json"))


def test_past_matrix_rows_and_slider_statements_become_separate_answers() -> None:
    by_id = {q["QuestionID"]: q for q in questions()}
    assert bench._past_entries(by_id["matrix"]) == [
        ("Rate these fictional objects.", "Cobalt: Low", ""),
        ("Rate these fictional objects.", "Silver: High", ""),
    ]
    assert bench._past_entries(by_id["choice"]) == [("Choose a fictional telescope.", "Boreal", "")]
    assert bench._past_entries(by_id["slider"]) == [("Give a probability.", "87 (0–100)", "")]
    positional = {**by_id["matrix"], "Answers": {"SelectedByPosition": [2, 1]}}
    assert [text for _, text, _ in bench._past_entries(positional)] == ["Cobalt: High", "Silver: Low"]
    odd = {"QuestionText": "Odd", "Answers": {"Other": 1}}
    assert bench._past_entries(odd) == [("Odd", '{"Other": 1}', "")]


def test_participant_sample_is_seeded_and_keeps_all_their_items(tmp_path: Path) -> None:
    cases = bench.load_dataset(dataset(tmp_path, [row(pid) for pid in range(1, 7)]))
    first = bench.sample_participants(cases, 3)
    assert first == bench.sample_participants(cases, 3) and len(set(first)) == 3
    selected = bench.select_cases(cases, limit=None, participant_ids=first)
    assert {c.input.participant_id for c in selected} == set(first)
    assert len(selected) == len([c for c in cases if c.input.participant_id in first])
    for count in (0, 7):
        with pytest.raises(ValueError):
            bench.sample_participants(cases, count)


def test_dev_split_never_draws_formal_participants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bench, "FORMAL_PARTICIPANTS", 2)
    cases = bench.load_dataset(dataset(tmp_path, [row(pid) for pid in range(1, 7)]))
    formal = set(bench.sample_participants(cases, 2))
    dev = bench.sample_participants(cases, 4, split="dev")
    assert dev == bench.sample_participants(cases, 4, split="dev") and not formal & set(dev)
    for count, split in ((5, "dev"), (1, "holdout")):
        with pytest.raises(ValueError):
            bench.sample_participants(cases, count, split=split)
