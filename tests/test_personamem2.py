from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.evals import personamem2 as pm2
from twin.evals.scorecard import benchmark_scorecard
from twin.llm import FakeLLM
from twin.persona.schema import ChatDraft

FIELDS = (
    "persona_id",
    "chat_history_32k_link",
    "user_query",
    "correct_answer",
    "incorrect_answers",
    "pref_type",
    "conversation_scenario",
    "who",
    "updated",
)


def link(persona: int) -> str:
    return f"data/chat_history_32k/chat_history_x_persona{persona}.json"


def write_dataset(root: Path, personas: range, per_persona: int = 2, *, histories: bool = True) -> Path:
    rows = []
    for persona in personas:
        for i in range(per_persona):
            query: Any = {"role": "user", "content": f"Question {i} for {persona}?"}
            rows.append(
                {
                    "persona_id": str(persona),
                    "chat_history_32k_link": link(persona),
                    # Upstream mixes JSON and Python-literal dicts.
                    "user_query": json.dumps(query) if i % 2 else repr(query),
                    "correct_answer": f"CORRECT {persona}-{i}",
                    "incorrect_answers": json.dumps([f"wrong {persona}-{i}-{k}" for k in range(3)]),
                    "pref_type": pm2.PREFERENCE_TYPES[i % len(pm2.PREFERENCE_TYPES)],
                    "conversation_scenario": "personal_email",
                    "who": "self",
                    "updated": "False",
                }
            )
        if histories:
            path = root / link(persona)
            path.parent.mkdir(parents=True, exist_ok=True)
            turns = [
                {"role": "system", "content": "You are an AI assistant helping a user with the following persona"},
                {"role": "user", "content": f"I always bake bread on Sundays ({persona})"},
                {"role": "assistant", "content": "Lovely."},
            ]
            path.write_text(json.dumps({"metadata": {"persona_id": persona}, "chat_history": turns}))
    path = root / "benchmark.csv"
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, FIELDS)
        writer.writeheader()
        writer.writerows([*rows, rows[0]])
    return path


def test_load_benchmark_parses_queries_and_drops_repeated_rows(tmp_path: Path) -> None:
    rows = pm2.load_benchmark(write_dataset(tmp_path, range(3)))
    assert len(rows) == 6 and len({row.question_id for row in rows}) == 6
    assert [row.query for row in rows[:2]] == ["Question 0 for 0?", "Question 1 for 0?"]
    bad = tmp_path / "bad.csv"
    bad.write_text("persona_id,user_query\n1,oops\n")
    with pytest.raises(ValueError, match="Invalid PersonaMem-v2"):
        pm2.load_benchmark(bad)


def test_splits_are_seeded_and_dev_never_uses_formal_personas(tmp_path: Path) -> None:
    rows = pm2.load_benchmark(write_dataset(tmp_path, range(20), histories=False))
    formal = pm2.split_personas(rows, "formal")
    dev = pm2.split_personas(rows, "dev")
    assert len(formal) == 8 and len(dev) == 4 and not set(formal) & set(dev)
    assert pm2.split_personas(rows, "formal") == formal and pm2.split_personas(rows, "dev", 12) != dev
    with pytest.raises(ValueError):
        pm2.split_personas(rows, "dev", 13)


def test_a_formal_count_stays_within_the_formal_personas(tmp_path: Path) -> None:
    rows = pm2.load_benchmark(write_dataset(tmp_path, range(20), histories=False))
    formal = pm2.split_personas(rows, "formal")
    assert pm2.split_personas(rows, "formal", 8) == formal
    assert set(pm2.split_personas(rows, "formal", 3)) <= set(formal)
    with pytest.raises(ValueError):
        pm2.split_personas(rows, "formal", 9)


def test_options_shuffle_reproducibly_and_gold_follows_the_correct_answer(tmp_path: Path) -> None:
    rows = pm2.load_benchmark(write_dataset(tmp_path, range(12), histories=False))
    golds = set()
    for row in rows:
        options, gold = pm2.options_for(row)
        assert pm2.options_for(row) == (options, gold)
        assert sorted(options) == sorted([row.correct, *row.incorrect]) and options["ABCD".index(gold)] == row.correct
        golds.add(gold)
    assert len(golds) > 1


def test_load_cases_reads_only_chosen_histories_and_rejects_escapes(tmp_path: Path) -> None:
    rows = pm2.load_benchmark(write_dataset(tmp_path, range(3)))
    cases = pm2.load_cases(rows, ["1"], tmp_path)
    assert [case.input.subject_id for case in cases] == ["1", "1"]
    assert cases[0].input.question.endswith(pm2.RECALL_SUFFIX)
    assert [turn.role for turn in cases[0].input.history] == ["system", "user", "assistant"]
    (tmp_path / link(2)).unlink()
    assert pm2.missing_histories(rows, tmp_path) == [link(2)]
    with pytest.raises(FileNotFoundError):
        pm2.load_cases(rows, ["2"], tmp_path)
    with pytest.raises(ValueError, match="escapes"):
        pm2.history_path(tmp_path, "../outside.json")


@pytest.mark.parametrize(
    ("response", "letter"),
    [
        ("Reasoning...\nFinal Answer: C", "C"),
        ("final answer: b", "B"),
        ("The answer is \\boxed{D}", "D"),
        ("I pick A.", "A"),
        ("B", ""),
        ("", ""),
    ],
)
def test_extract_final_answer_matches_upstream_patterns(response: str, letter: str) -> None:
    assert pm2.extract_final_answer(response) == letter


def picker(*, bare: bool = False) -> FakeLLM:
    """Answers with the letter of the option marked CORRECT, or a bare letter upstream cannot parse."""

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is ChatDraft:
            options = json.loads(re.findall(r"\{\"question\".*\}", user)[-1])["options"]
            letter = next(key for key, text in options.items() if text.startswith("CORRECT"))
            return {"reply": letter if bare else f"Final Answer: {letter}", "citations": [], "confidence": 0.5}
        return {"items": []}

    return FakeLLM(answer)


def test_run_scores_with_upstream_extraction_and_feeds_the_scorecard(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rows = pm2.load_benchmark(write_dataset(tmp_path, range(3)))
    cases = pm2.load_cases(rows, ["0", "2"], tmp_path)
    monkeypatch.setattr(pm2, "make_embedder", lambda _: HashingEmbedder())
    for run, llm in (("r1", picker()), ("r2", picker(bare=True))):
        monkeypatch.setattr(pm2, "make_llm", lambda _, llm=llm: llm)
        report = pm2.run_evaluation(cases, tmp_path / "suite" / "personamem2" / run, Settings(), answer_workers=2)
        assert report["completed"] == 4 and report["planned_preparations"] == 2
    first = [json.loads(line) for line in (tmp_path / "suite/personamem2/r1/records.jsonl").read_text().splitlines()]
    assert [row["score"] for row in first] == [True] * 4 and not any(row["format_failure"] for row in first)
    assert [row["persona"]["cache_hit"] for row in first] == [False, True, False, True]
    card = benchmark_scorecard("personamem2", tmp_path / "suite" / "personamem2")
    assert card["outcomes"]["correct"] == 4 and card["outcomes"]["format"] == 4
