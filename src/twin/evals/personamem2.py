"""PersonaMem-v2 (text, 32k histories) through production Twin with the upstream multiple-choice scoring."""

from __future__ import annotations

import ast
import csv
import hashlib
import json
import os
import random
import re
import threading
from collections.abc import Iterable, Sequence
from contextlib import ExitStack, suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from ..config import Settings, make_embedder, make_llm
from ..usage import BudgetExceeded, UsageRecorder, record_usage
from ..util import fingerprint, open_private, private_directory
from .longmemeval import _write_usage
from .persona_runtime import (
    PersonaRuntime,
    ProfileCache,
    SourceInput,
    in_order,
    limit_calls,
    preparation_key,
    report_system,
)
from .personal import ensure_output_directory
from .personamem import Turn, _metrics

PREFERENCE_TYPES = (
    "ask_to_forget",
    "neutral_preferences",
    "anti_stereotypical_pref",
    "therapy_background",
    "health_and_medical_conditions",
    "stereotypical_pref",
    "sensitive_info",
)
LETTERS = "ABCD"
# Appended to every query by upstream inference.py before asking the model.
RECALL_SUFFIX = " Please recall my related preferences from our conversation history to give personalized responses."
ARTIFACTS = ("hypotheses.jsonl", "records.jsonl", "report.json", "calls.jsonl", "usage.json")
SAMPLE_SEED = "personamem-v2"
SPLITS = ("formal", "dev")
SPLIT_PERSONAS = {"formal": 8, "dev": 4}


@dataclass(frozen=True)
class QuestionInput:
    question_id: str
    question: str
    options: tuple[str, ...]
    history: tuple[Turn, ...]
    subject_id: str


@dataclass(frozen=True)
class Case:
    input: QuestionInput
    question_type: str
    gold: str
    scenario: str
    who: str
    updated: bool


@dataclass(frozen=True)
class Row:
    """One benchmark.csv question before its persona's history is read."""

    persona_id: str
    history_link: str
    query: str
    correct: str
    incorrect: tuple[str, ...]
    question_type: str
    scenario: str
    who: str
    updated: bool

    @property
    def question_id(self) -> str:
        digest = hashlib.sha256(f"{self.persona_id}\n{self.query}\n{self.correct}".encode()).hexdigest()
        return f"p{self.persona_id}-{digest[:10]}"


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError
    return value


def _query(value: str) -> str:
    """The CSV stores ``{'role': 'user', 'content': ...}`` as JSON or a Python literal; never execute it."""
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        parsed = ast.literal_eval(value)
    if not isinstance(parsed, dict) or parsed.get("role") != "user":
        raise ValueError
    return _text(parsed.get("content"))


def load_benchmark(path: Path) -> tuple[Row, ...]:
    """Whitelist the text benchmark's fields; question ids are content hashes because the CSV has none."""
    try:
        csv.field_size_limit(1 << 30)
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows: list[Row] = []
            for raw in csv.DictReader(stream):
                incorrect = json.loads(raw["incorrect_answers"])
                if not isinstance(incorrect, list) or len(incorrect) != 3:
                    raise ValueError
                question_type = raw["pref_type"]
                if question_type not in PREFERENCE_TYPES or raw["updated"] not in ("True", "False"):
                    raise ValueError
                rows.append(
                    Row(
                        str(int(raw["persona_id"])),
                        _text(raw["chat_history_32k_link"]),
                        _query(raw["user_query"]),
                        _text(raw["correct_answer"]),
                        tuple(_text(answer) for answer in incorrect),
                        question_type,
                        raw["conversation_scenario"],
                        raw["who"],
                        raw["updated"] == "True",
                    )
                )
        if not rows:
            raise ValueError
        # Upstream repeats a few identical rows; keep each question once.
        unique = {row.question_id: row for row in reversed(rows)}
        return tuple(row for row in rows if unique.pop(row.question_id, None) is not None)
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, SyntaxError, RecursionError, csv.Error):
        raise ValueError("Invalid PersonaMem-v2 benchmark CSV") from None


def split_personas(rows: Sequence[Row], split: str, count: int | None = None, seed: str = SAMPLE_SEED) -> list[str]:
    """Seeded persona draw: ``formal`` from every persona, ``dev`` only from personas the formal draw left out."""
    if split not in SPLITS:
        raise ValueError("split must be formal or dev")
    personas = sorted({row.persona_id for row in rows}, key=int)
    formal = sorted(random.Random(seed).sample(personas, SPLIT_PERSONAS["formal"]), key=int)
    if split == "formal" and count is None:
        return formal
    pool = personas if split == "formal" else [p for p in personas if p not in formal]
    count = count or SPLIT_PERSONAS[split]
    if not 1 <= count <= len(pool):
        raise ValueError("persona count out of range")
    return sorted(random.Random(f"{seed}:{split}").sample(pool, count), key=int)


def history_path(root: Path, link: str) -> Path:
    path = (root / link).resolve()
    if not path.is_relative_to(root.resolve()) or path.suffix != ".json":
        raise ValueError("History link escapes the dataset directory")
    return path


def missing_histories(rows: Iterable[Row], root: Path) -> list[str]:
    return sorted({row.history_link for row in rows if not history_path(root, row.history_link).is_file()})


def _history(path: Path) -> tuple[Turn, ...]:
    data = json.loads(path.read_text(encoding="utf-8"))
    turns = data["chat_history"] if isinstance(data, dict) else None
    if not isinstance(turns, list) or not turns:
        raise ValueError
    result = []
    for turn in turns:
        if not isinstance(turn, dict) or turn.get("role") not in ("system", "user", "assistant"):
            raise ValueError
        if not isinstance(turn.get("content"), str):
            raise ValueError
        result.append(Turn(turn["role"], turn["content"]))
    return tuple(result)


def options_for(row: Row) -> tuple[tuple[str, ...], str]:
    """Shuffle the four answers per question. Upstream seeds with Python's salted ``hash()``, which differs between
    processes, so a content-derived seed is used instead; the gold letter follows the shuffle."""
    options = [row.correct, *row.incorrect]
    random.Random(f"{SAMPLE_SEED}:{row.question_id}").shuffle(options)
    return tuple(options), LETTERS[options.index(row.correct)]


def load_cases(rows: Sequence[Row], personas: Sequence[str], root: Path) -> tuple[Case, ...]:
    """Questions of the chosen personas in source order, each with its persona's full 32k history, which upstream
    sends whole, including the assistant's persona system prompt."""
    chosen = [row for row in rows if row.persona_id in set(personas)]
    if not chosen:
        raise ValueError("No questions selected")
    missing = missing_histories(chosen, root)
    if missing:
        raise FileNotFoundError(f"{len(missing)} chat histories are not downloaded")
    histories: dict[str, tuple[Turn, ...]] = {}
    try:
        for row in chosen:
            if row.history_link not in histories:
                histories[row.history_link] = _history(history_path(root, row.history_link))
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        raise ValueError("Invalid PersonaMem-v2 chat history") from None
    cases = []
    for row in chosen:
        options, gold = options_for(row)
        cases.append(
            Case(
                QuestionInput(row.question_id, row.query + RECALL_SUFFIX, options, histories[row.history_link],
                              row.persona_id),
                row.question_type,
                gold,
                row.scenario,
                row.who,
                row.updated,
            )
        )  # fmt: skip
    return tuple(cases)


_PATTERNS = (
    r"\$\\boxed\{([A-Z])\}\$",
    r"\\boxed\{([A-Z])\}",
    r"Final Answer:\s*([A-Z])",
    r"final answer:\s*([A-Z])",
    r"Answer:\s*([A-Z])",
    r"answer:\s*([A-Z])",
    r"final answer is\s*\$?\\boxed\{([A-Z])\}\$?",
    r"final answer is\s*([A-Z])",
    r"the answer is\s*\$?\\boxed\{([A-Z])\}\$?",
    r"the answer is\s*([A-Z])",
    r"\b([A-Z])\.\s*$",
)


def extract_final_answer(response: str) -> str:
    """Upstream ``extract_final_answer``: the first matching pattern wins; empty when none matches."""
    for pattern in _PATTERNS:
        match = re.search(pattern, response, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).upper()
    return ""


class TwinSystem:
    def __init__(self, runtime: PersonaRuntime) -> None:
        self.runtime = runtime
        self.llm = runtime.llm

    @property
    def retrieval_manifest(self) -> list[dict[str, Any]]:
        """What this thread's last answer retrieved; empty when it failed before answering."""
        return [{"ref": ref} for ref in self.runtime.metadata.get("retrieved_ids", [])]

    @staticmethod
    def sources(question: QuestionInput) -> tuple[SourceInput, ...]:
        return (SourceInput("history", "chat", tuple((turn.role, turn.content, "") for turn in question.history)),)

    def prepare(self, questions: Iterable[QuestionInput], workers: int) -> None:
        self.runtime.prepare(
            (("personamem-v2:" + question.subject_id, self.sources(question)) for question in questions), workers
        )

    def predict(self, question: QuestionInput) -> str:
        reply = self.runtime.predict(
            "personamem-v2:" + question.subject_id,
            self.sources(question),
            json.dumps(
                {
                    "question": question.question,
                    "options": {letter: option for letter, option in zip(LETTERS, question.options, strict=True)},
                    "output": "Choose the option that best fits this user. Return exactly `Final Answer: X` with X "
                    "one of A, B, C or D.",
                },
                ensure_ascii=False,
            ),
        )
        return reply.reply


def validate_output(out: Path) -> Path:
    out = out.expanduser().resolve()
    ensure_output_directory(out)
    if out.exists() and not out.is_dir():
        raise ValueError("PersonaMem-v2 output must be a directory")
    if any((out / name).exists() or (out / name).is_symlink() for name in ARTIFACTS):
        raise ValueError("PersonaMem-v2 output already contains run artifacts; choose a fresh directory")
    return out


def run_evaluation(
    cases: Sequence[Case],
    out: Path,
    settings: Settings,
    *,
    dry_run: bool = False,
    fingerprints: dict[str, str] | None = None,
    profile_cache: ProfileCache | None = None,
    prepare_workers: int = 1,
    answer_workers: int = 1,
    call_slots: threading.Semaphore | None = None,
) -> dict[str, Any]:
    system_info = report_system("twin", "")
    if not cases:
        raise ValueError("No questions selected")
    identities = dict(fingerprints or {})
    if identities.keys() - {"dataset_sha256", "configuration", "runtime_configuration"} or any(
        not re.fullmatch(r"[a-f0-9]{64}", value) for value in identities.values()
    ):
        raise ValueError("Provenance must contain supported SHA-256 digests only")
    # Histories live in separate files, so the dataset identity covers the cases actually built from them.
    identities["dataset_sha256"] = fingerprint(
        {"benchmark": identities.get("dataset_sha256"), "cases": [asdict(case) for case in cases]}
    )
    out = validate_output(out)
    private_directory(out)
    out.chmod(0o700)
    for name in ARTIFACTS:
        os.close(os.open(out / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
    recorder = UsageRecorder(settings.pricing, settings.budget.max_cost_usd)
    rows: list[dict[str, Any]] = []
    system: TwinSystem | None = None
    with (
        ExitStack() as cleanup,
        suppress(BudgetExceeded),
        record_usage(recorder),
        open_private(out / "hypotheses.jsonl") as hypotheses,
        open_private(out / "records.jsonl") as records,
    ):
        if not dry_run:
            try:
                runtime = PersonaRuntime(
                    settings, limit_calls(make_llm(settings.llm), call_slots), make_embedder(settings.embed),
                    profile_cache,
                )  # fmt: skip
                cleanup.callback(runtime.close)
                system = TwinSystem(runtime)
                identities["runtime_configuration"] = fingerprint(
                    {"runtime": runtime.configuration, "adapter": "personamem-v2-mcq", "suffix": RECALL_SUFFIX}
                )
            except Exception:
                system = None
        if system is not None and recorder.stop is None:
            system.prepare((case.input for case in cases), prepare_workers)

        def evaluate(case: Case) -> dict[str, Any]:
            row: dict[str, Any] = {
                "question_id": case.input.question_id,
                "question_type": case.question_type,
                "scenario": case.scenario,
                "who": case.who,
                "updated": case.updated,
                "status": "dry_run" if dry_run else "prediction_failed",
                "retrieval": [],
                "score": None,
                "preparation_key": preparation_key(
                    "personamem-v2:" + case.input.subject_id, TwinSystem.sources(case.input), settings
                ),
            }
            if dry_run:
                return row
            if recorder.stop is not None:
                row["status"] = "budget_skipped"
                return row
            if system is None:
                row["error"] = "Backend construction failed (details hidden)"
                return row
            try:
                response = system.predict(case.input)
                scoring_start = perf_counter()
                selection = extract_final_answer(response)
                row.update(
                    status="ok",
                    model_response=response,
                    selection=selection or None,
                    format_failure=selection not in tuple(LETTERS),
                    gold_selection=case.gold,
                    score=selection == case.gold,
                    retrieval=system.retrieval_manifest,
                )
                row["scoring_seconds"] = perf_counter() - scoring_start
            except Exception:
                row["error"] = "Prediction failed (details hidden)"
            row["persona"] = system.runtime.metadata
            if system.runtime.metadata.get("preparation_failure"):
                row["status"] = "preparation_failed"
            return row

        for case, row in in_order(evaluate, cases, answer_workers):
            if row["status"] == "ok":
                hypothesis = {"question_id": case.input.question_id, "model_response": row["model_response"]}
                hypotheses.write(json.dumps(hypothesis, ensure_ascii=False) + "\n")
                hypotheses.flush()
            rows.append(row)
            records.write(json.dumps(row, ensure_ascii=False) + "\n")
            records.flush()
            _write_usage(recorder, out)
            report = {
                **system_info,
                "benchmark": "PersonaMem-v2 text 32k",
                "scoring": "upstream multiple-choice extraction (inference.py)",
                "dry_run": dry_run,
                "planned_preparations": len({r["preparation_key"] for r in rows}),
                "budget_stopped": recorder.stop is not None,
                "fingerprints": identities,
                "retrieval": {"engine": "PersonaChat", "target_only": True},
                **_metrics(rows, scored=not dry_run),
                "categories": {
                    category: _metrics([r for r in rows if r["question_type"] == category], scored=not dry_run)
                    for category in PREFERENCE_TYPES
                },
            }
            report["selected"] = len(cases)
            report["pending"] = len(cases) - len(rows)
            with open_private(out / "report.json") as stream:
                stream.write(json.dumps(report, ensure_ascii=False, indent=2))
    return report
