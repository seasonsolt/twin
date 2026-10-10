"""Entirely invented run artifacts; no downloaded benchmark data or model calls."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from twin import cli
from twin.cli import app
from twin.evals import scorecard as sc


def lme_row(qid: str, qtype: str, score: float | None, mode: str = "grounded", status: str = "ok") -> dict[str, Any]:
    return {
        "question_id": qid,
        "question_type": qtype,
        "status": status,
        "score": score,
        "hypothesis": "PRIVATE_REPLY_MARKER",
        "persona": {"mode": mode, "abstain": mode == "abstain"},
    }


def pm_row(qid: str, correct: bool, *, format_failure: bool = False, status: str = "ok") -> dict[str, Any]:
    return {
        "question_id": qid,
        "question_type": "recall_user_shared_facts",
        "status": status,
        "score": correct,
        "format_failure": format_failure,
        "persona": {"mode": "inferred"},
    }


def t2k_row(item: str, exact: int, kind: str = "categorical") -> dict[str, Any]:
    return {
        "participant": "a" * 64,
        "question_id": "QID1",
        "item_id": item,
        "kind": kind,
        "gold_missing": False,
        "status": "ok",
        "scores": {"exact_match": exact if kind == "categorical" else None},
        "persona": {"mode": "inferred"},
    }


def write_run(run: Path, rows: list[dict[str, Any]], **report: Any) -> None:
    run.mkdir(parents=True, exist_ok=True)
    (run / "records.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (run / "report.json").write_text(json.dumps({"pending": 0, "dry_run": False, "fingerprints": {}, **report}))


def lme_suite(root: Path, runs: list[list[float | None]]) -> Path:
    for index, scores in enumerate(runs, 1):
        rows = [lme_row(f"q{i}", "temporal-reasoning" if i % 2 else "multi-session", s) for i, s in enumerate(scores)]
        write_run(root / "longmemeval" / f"r{index}", rows, judges=["j0", "j1"])
    return root


def test_scorecard_aggregates_repeats_and_counts_failures_as_wrong(tmp_path: Path) -> None:
    lme_suite(tmp_path, [[1.0, 0.0, 0.5, None], [1.0, 1.0, 0.0, None]])
    write_run(
        tmp_path / "personamem" / "r1",
        [
            pm_row("p1", True),
            pm_row("p2", False, format_failure=True),
            pm_row("p3", False, status="preparation_failed"),
        ],
    )
    write_run(
        tmp_path / "twin2k500" / "r1",
        [t2k_row("1", 1), t2k_row("2", 0), t2k_row("3", 0, kind="numeric")],
        human_test_retest={"categorical_accuracy": 0.75},
        bounded_numeric_scored=1,
        mean_normalized_absolute_error=0.2,
    )
    card = sc.build_scorecard(tmp_path, {"split": "dev"})
    lme, pm, t2k = (card["benchmarks"][name] for name in sc.BENCHMARKS)
    assert lme["repeats"] == 2 and lme["items"] == 4
    assert lme["headline"]["min"] == pytest.approx(0.375) and lme["headline"]["max"] == pytest.approx(0.5)
    assert lme["types"] == {"multi-session": pytest.approx(0.625), "temporal-reasoning": pytest.approx(0.25)}
    assert lme["judges"]["mean"] == 2
    assert pm["headline"]["mean"] == pytest.approx(1 / 3)
    assert pm["outcomes"]["correct"] == 1 and pm["outcomes"]["format"] == 1 and pm["outcomes"]["preparation"] == 1
    assert t2k["items"] == 2 and t2k["headline"]["mean"] == 0.5 and t2k["human_test_retest"]["mean"] == 0.75
    assert t2k["outcomes"]["wrong_inferred"] == 1
    sc.write_scorecard(tmp_path, card, None)
    for name in ("scorecard.json", "scorecard.md"):
        text = (tmp_path / name).read_text()
        assert "PRIVATE_REPLY_MARKER" not in text
        assert (tmp_path / name).stat().st_mode & 0o777 == 0o600


def test_comparison_reports_moved_items_and_noise(tmp_path: Path) -> None:
    base = sc.build_scorecard(lme_suite(tmp_path / "a", [[0.0, 1.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]]), {"split": "dev"})
    cand = sc.build_scorecard(lme_suite(tmp_path / "b", [[1.0, 0.0, 1.0, 1.0], [1.0, 0.0, 1.0, 0.0]]), {"split": "dev"})
    result = sc.compare(cand, base)["longmemeval"]
    assert result["fixed"] == ["q0", "q2", "q3"] and result["broken"] == ["q1"]
    assert result["beyond_noise"] and result["delta"] == pytest.approx(0.375)
    single = sc.build_scorecard(lme_suite(tmp_path / "c", [[1.0, 1.0, 1.0, 1.0]]), {"split": "dev"})
    assert not sc.compare(single, base)["longmemeval"]["beyond_noise"]
    assert "单次运行" in sc.render_markdown(single, sc.compare(single, base))
    with pytest.raises(ValueError):
        sc.compare(cand, {**base, "split": "formal"})
    other = sc.build_scorecard(lme_suite(tmp_path / "d", [[1.0, 1.0, 1.0]]), {"split": "dev"})
    with pytest.raises(ValueError):
        sc.compare(other, base)


def test_scorecard_rejects_incomplete_or_mismatched_runs(tmp_path: Path) -> None:
    lme_suite(tmp_path / "a", [[1.0, 0.0], [1.0]])
    with pytest.raises(ValueError):
        sc.build_scorecard(tmp_path / "a", {})
    write_run(tmp_path / "b" / "personamem" / "r1", [pm_row("p1", True)], pending=1)
    with pytest.raises(ValueError):
        sc.build_scorecard(tmp_path / "b", {})
    (tmp_path / "c").mkdir()
    with pytest.raises(ValueError):
        sc.build_scorecard(tmp_path / "c", {})


def test_suite_runs_every_repeat_and_writes_a_comparable_scorecard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, int | None, str, bool]] = []

    def fake_lme(settings: Any, dataset: Path, run: Path, **options: Any) -> dict[str, Any]:
        calls.append(("lme", options["per_type"], options["split"], bool(settings.judges)))
        write_run(run, [lme_row("q0", "multi-session", 1.0)], judges=["j0"])
        return {"preparation_failures": 0, "prediction_failures": 0, "judge_failures": 0, "missing": 0}

    def fake_pm(settings: Any, questions: Path, contexts: Path, run: Path, **options: Any) -> dict[str, Any]:
        calls.append(("pm", options["sample"], options["split"], bool(settings.judges)))
        write_run(run, [pm_row("p1", False, status="preparation_failed")])
        return {"preparation_failures": 1}

    monkeypatch.setattr(cli, "_run_longmemeval", fake_lme)
    monkeypatch.setattr(cli, "_run_personamem", fake_pm)
    config = tmp_path / "twin.toml"
    config.write_text('[[judges]]\nprovider = "anthropic"\nmodel = "judge"\n')
    data = tmp_path / "data.json"
    data.write_text("{}")
    out = tmp_path / "suite"
    args = ["--config", str(config), "eval-suite", "--out", str(out), "--repeats", "2", "--configured-judges"]
    args += ["--longmemeval", str(data)]
    result = CliRunner().invoke(app, [*args, "--personamem-questions", str(data), "--personamem-contexts", str(data)])
    assert result.exit_code == 1 and "personamem" in result.output
    assert sorted(calls) == [("lme", 3, "dev", True)] * 2 + [("pm", 24, "dev", False)] * 2
    card = json.loads((out / "scorecard.json").read_text())
    assert card["split"] == "dev" and card["repeats"] == 2 and card["sizes"] == {"lme": 3, "pm": 24, "t2k": 4}
    assert card["judges"] == ["judge"]
    assert card["benchmarks"]["personamem"]["outcomes"]["preparation"] == 2

    calls.clear()
    second = tmp_path / "suite2"
    result = CliRunner().invoke(
        app,
        [
            "--config",
            str(config),
            "eval-suite",
            "--out",
            str(second),
            "--longmemeval",
            str(data),
            "--baseline",
            str(out / "scorecard.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert calls == [("lme", 3, "dev", False)] * 2
    assert json.loads((second / "scorecard.json").read_text())["comparison"]["longmemeval"]["delta"] == 0
    assert "与基线相比" in (second / "scorecard.md").read_text()

    rebuilt = CliRunner().invoke(app, ["eval-scorecard", str(out)])
    assert rebuilt.exit_code == 0 and json.loads((out / "scorecard.json").read_text())["split"] == "dev"
    assert CliRunner().invoke(app, ["--config", str(config), "eval-suite", "--out", str(out)]).exit_code == 1
    assert CliRunner().invoke(app, [*args, "--split", "holdout"]).exit_code == 1
