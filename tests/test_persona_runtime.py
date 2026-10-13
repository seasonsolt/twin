"""Offline integration coverage of public benchmarks using the production persona chain."""

from __future__ import annotations

import datetime as dt
import json
import re
import threading
import time
from collections.abc import Callable
from contextlib import suppress
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import LLMSettings, Settings
from twin.embed import HashingEmbedder
from twin.evals import longmemeval as lm
from twin.evals import persona_runtime as pr
from twin.evals import personamem as pm
from twin.evals import twin2k500 as tw
from twin.evals.harness import Judge
from twin.llm import FakeLLM, LLMError
from twin.persona.chat import EMPTY_REPLY
from twin.persona.profile import BuildReport, consented_facets
from twin.persona.schema import ChatDraft, EvidenceClass, SourceKind, evidence_class
from twin.persona.sources import parse_chat
from twin.persona.store import PersonaStore
from twin.usage import BudgetExceeded, UsageRecorder, active_recorder, record_usage


def fake_persona(response: str = "Atlas", *, abstain: bool = False) -> FakeLLM:
    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is ChatDraft:
            ids = re.findall(r"\[(src_[^\]]+)\]", user)
            return {
                "reply": response,
                "citations": ids[:1],
                "confidence": 0.8,
                "abstain": abstain,
                "mode": "abstain" if abstain else "grounded",
            }
        return {"items": []}

    return FakeLLM(answer)


def records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (path / "records.jsonl").read_text().splitlines()]


def test_parser_no_target_is_explicit_and_preserves_roles(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "isolated.db", target_name=pr.TARGET)
    raw = json.dumps([{"sender": "assistant", "content": "assistant evidence"}])
    with pytest.raises(ValueError, match="no message"):
        parse_chat("s.json", raw, settings)
    parsed = parse_chat("s.json", raw, settings, allow_no_target=True)
    assert parsed.source.n_target == 0
    assert len(parsed.expressions) == 1 and not parsed.expressions[0].is_target
    assert parsed.expressions[0].context == ""


def test_real_pipeline_isolated_cache_reopens_and_private_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    production = tmp_path / "production.db"
    with PersonaStore(production) as store:
        store.set_identity("SECRET_OWNER", "SECRET_ABOUT", None)
    original = production.read_bytes()
    init = PersonaStore.__init__
    opened: list[Path] = []

    def guarded(self: PersonaStore, path: Path | str) -> None:
        assert Path(path) != production
        opened.append(Path(path))
        init(self, path)

    monkeypatch.setattr(PersonaStore, "__init__", guarded)
    llm = fake_persona()
    runtime = pr.PersonaRuntime(
        Settings(db_path=production, target_name="SECRET_OWNER", target_aliases=["assistant"]), llm, HashingEmbedder()
    )
    sources = (
        pr.SourceInput(
            "history",
            "chat",
            (
                ("system", "SYSTEM_DATA", ""),
                ("assistant", "ASSISTANT_DATA", ""),
                ("user", "I prefer Atlas", "2025-01-02"),
            ),
        ),
    )
    recorder = UsageRecorder()
    try:
        with record_usage(recorder):
            first = runtime.predict("person", sources, "Which project?")
            metadata = runtime.metadata
            second = runtime.predict("person", sources, "Which project again?")
        assert first.reply == second.reply == "Atlas"
        assert not metadata["cache_hit"] and runtime.metadata["cache_hit"]
        assert set(metadata["stages"]) == {"preparation", "index", "answer"}
        assert set(runtime.metadata["stages"]) == {"answer"}
        assert sum(call[0] == "ExtractDraft" for call in llm.calls) == 1
        db = next(runtime.root.glob("*.db"))
        assert runtime.root.stat().st_mode & 0o777 == 0o700
        assert db.stat().st_mode & 0o777 == 0o600
        with PersonaStore(db) as store:
            assert store.get_meta("identity:name") == pr.TARGET
            assert not store.get_meta("identity:about")
            expressions = store.list_expressions()
            assert [e.is_target for e in expressions] == [False, False, True]
            assert "SYSTEM_DATA" in expressions[-1].context
            assert store.get_meta("built_at")
            assert store.get_vectors("expressions")[0] and first.retrieved_ids
        material = repr(llm.calls)
        assert "SECRET_OWNER" not in material and "SECRET_ABOUT" not in material
        assert all(path.is_relative_to(runtime.root) for path in opened)
        assert {r.stage for r in recorder.rows} == {"persona.preparation", "persona.index", "persona.answer"}
    finally:
        runtime.close()
    assert not runtime.root.exists() and production.read_bytes() == original


def test_prefixes_and_subjects_cache_separately(tmp_path: Path) -> None:
    llm = fake_persona()
    runtime = pr.PersonaRuntime(Settings(), llm, HashingEmbedder())
    one = (pr.SourceInput("h", "chat", (("user", "PAST", ""),)),)
    future = (replace(one[0], entries=(*one[0].entries, ("user", "FUTURE", ""))),)
    try:
        for subject, sources in (("a", one), ("a", future), ("b", one), ("a", one)):
            runtime.predict(subject, sources, "question")
        assert len(list(runtime.root.glob("*.db"))) == 3
        assert runtime.metadata["cache_hit"]
        assert "FUTURE" not in llm.calls[-1][2]
        assert sum(c[0] == "ExtractDraft" for c in llm.calls) == 3
    finally:
        runtime.close()


@pytest.mark.parametrize("failure", ["partial", "parser", "index", "budget"])
def test_failed_preparation_cached_and_never_answers(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = fake_persona()
    runtime = pr.PersonaRuntime(Settings(), llm, HashingEmbedder())
    calls = 0

    def fail(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        if failure == "partial":
            return BuildReport(failures=["PRIVATE_DETAILS"])
        if failure == "budget":
            recorder = active_recorder()
            assert recorder is not None
            recorder.stop = BudgetExceeded("PRIVATE_BUDGET")
            return BuildReport()
        raise ValueError("PRIVATE_DETAILS")

    monkeypatch.setattr(
        pr,
        {"partial": "build_profile", "budget": "build_profile", "parser": "parse_source", "index": "index_persona"}[
            failure
        ],
        fail,
    )
    try:
        with suppress(BudgetExceeded), record_usage(UsageRecorder()):
            for _ in range(2):
                with pytest.raises(pr.PreparationError):
                    runtime.predict("a", (pr.SourceInput("h", "chat", (("user", "PAST", ""),)),), "question")
        assert calls == 1 and runtime.metadata["cache_hit"] and runtime.metadata["preparation_failure"]
        assert not any(c[0] == "ChatDraft" for c in llm.calls)
    finally:
        runtime.close()


def test_lme_retains_future_and_assistant_only_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = fake_persona()
    monkeypatch.setattr(lm, "make_llm", lambda _: llm)
    monkeypatch.setattr(lm, "make_embedder", lambda _: HashingEmbedder())
    source_rows: list[Any] = []
    original = pr.parse_source

    def inspect(source: pr.SourceInput, settings: Settings) -> Any:
        parsed = original(source, settings)
        source_rows.append(parsed)
        return parsed

    monkeypatch.setattr(pr, "parse_source", inspect)
    question = lm.QuestionInput(
        "q",
        "project?",
        "2024/01/01 (Mon) 10:00",
        (
            lm.Session(0, "assistant", "2025/01/01 (Wed) 10:00", (lm.Turn("assistant", "assistant-only"),)),
            lm.Session(1, "user", "2025/01/02 (Thu) 10:00", (lm.Turn("user", "Atlas"),)),
        ),
    )
    case = lm.Case(question, "single-session-assistant", lm.Gold("GOLD_SECRET", ("assistant",)))
    report = lm.run_evaluation([case], tmp_path / "out", Settings())
    assert report["system"] == "twin" and report["completed"] == 1
    assert source_rows[0].source.n_target == 0
    assert source_rows[1].expressions[0].date == dt.date(2025, 1, 2)
    assert "Atlas" in llm.calls[-1][2] and "GOLD_SECRET" not in repr(llm.calls)
    assert records(tmp_path / "out")[0]["persona"]["as_of"] is None
    assert "今天是 2024-01-01。" in llm.calls[-1][1]


def test_personamem_raw_response_official_score_and_prefix_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = "My answer is (b), because it matches your preference."
    llm = fake_persona(response)
    models = []

    def make(config: LLMSettings) -> FakeLLM:
        models.append(config.model)
        return llm

    monkeypatch.setattr(pm, "make_llm", make)
    monkeypatch.setattr(pm, "make_embedder", lambda _: HashingEmbedder())
    history = (pm.Turn("system", "data only"), pm.Turn("user", "I prefer Atlas"))
    question = pm.QuestionInput("q", "project?", ("A", "B", "C", "D"), history, subject_id="person")
    cases = [pm.Case(replace(question, question_id=str(i)), pm.QUESTION_TYPES[0], pm.Gold("b", "b")) for i in range(2)]
    report = pm.run_evaluation(
        cases,
        tmp_path / "out",
        Settings(llm=LLMSettings(model="eval-main"), chat_llm=LLMSettings(model="production-private")),
        score=True,
    )
    assert models == ["eval-main"]
    assert report["correct"] == 2 and report["format_failures"] == 2
    rows = records(tmp_path / "out")
    assert all(r["model_response"] == response and r["selection"] is None for r in rows)
    assert rows[1]["persona"]["cache_hit"]
    assert sum(c[0] == "ExtractDraft" for c in llm.calls) == 1


@pytest.mark.usefixtures("gated_life_facets")
def test_twin_questionnaire_reuse_and_no_consent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = fake_persona("B")
    monkeypatch.setattr(tw, "make_llm", lambda _: llm)
    monkeypatch.setattr(tw, "make_embedder", lambda _: HashingEmbedder())
    seen: list[Any] = []
    original = pr.build_profile

    def inspect(store: PersonaStore, *args: Any, **kwargs: Any) -> BuildReport:
        source = store.list_sources()[0]
        assert source.kind == SourceKind.QUESTIONNAIRE
        assert evidence_class(source.kind) == EvidenceClass.SELF_REPORT
        expressions = store.list_expressions()
        assert expressions[0].context == "Past question?" and expressions[0].text == "Past answer"
        assert not expressions[0].facets_hint
        assert not any(f.startswith("9.") for f in consented_facets(store))
        seen.append(consented_facets(store))
        return original(store, *args, **kwargs)

    monkeypatch.setattr(pr, "build_profile", inspect)
    q = tw.QuestionInput(
        "participant",
        "q",
        "q",
        "MC",
        "Current question?",
        (),
        ("A", "B"),
        None,
        "legacy",
        (("Past question?", "Past answer", ""),),
    )
    cases = [
        tw.Case(replace(q, question_id=str(i)), "categorical", tw.Gold("GOLD_SECRET", "HUMAN_SECRET")) for i in range(2)
    ]
    report = tw.run_evaluation(cases, tmp_path / "out", Settings())
    assert report["completed"] == 2 and len(seen) == 1
    assert "GOLD_SECRET" not in repr(llm.calls) and "HUMAN_SECRET" not in repr(llm.calls)
    assert records(tmp_path / "out")[1]["persona"]["cache_hit"]


@pytest.mark.parametrize("score", [True, False])
def test_twin_categorical_attempts_and_unscored_boundaries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, score: bool
) -> None:
    replies = [
        ("B", False),
        ("A", False),
        ("B or A", False),
        ("  ", True),
        ("B", True),
        ("B", False),
        ("invalid", False),
        ("5", True),
    ]
    remaining = iter(replies)

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is ChatDraft:
            response, abstain = next(remaining)
            return {"reply": response, "citations": [], "confidence": 0.5, "abstain": abstain}
        return {"items": []}

    llm = FakeLLM(answer)
    monkeypatch.setattr(tw, "make_llm", lambda _: llm)
    monkeypatch.setattr(tw, "make_embedder", lambda _: HashingEmbedder())
    question = tw.QuestionInput("p", "q", "q", "MC", "?", (), ("A", "B"), None, "Past self-report")
    categorical = tw.Case(question, "categorical", tw.Gold("B"))
    numeric = tw.Case(
        replace(question, question_type="Slider", choices=(), numeric_range=(0, 10)), "numeric", tw.Gold(5)
    )
    cases = [categorical] * 5 + [
        replace(categorical, gold=tw.Gold(None)),
        numeric,
        numeric,
        replace(categorical, kind="unsupported"),
    ]
    out = tmp_path / "run"
    report = tw.run_evaluation(cases, out, Settings(), score=score)
    rows = records(out)
    expected = [1, 0, 0, 0, 0, None, None, None, None] if score else [None] * 9
    assert [r["scores"]["exact_match"] for r in rows] == expected
    assert all(r["scores"]["absolute_error"] is None for r in rows)
    # A blank reply is finalized into an honest abstention text instead of staying empty.
    shown = [EMPTY_REPLY["en"] if not response.strip() else response for response, _ in replies]
    assert [r["model_response"] for r in rows[:8]] == shown
    assert [r["format_failure"] for r in rows[:8]] == [False, False, True, True, False, False, True, False]
    assert [r["persona"]["abstain"] for r in rows[:8]] == [abstain for _, abstain in replies]
    hypotheses = [json.loads(line) for line in (out / "hypotheses.jsonl").read_text().splitlines()]
    assert [h["answer"] for h in hypotheses] == ["B", "A", None, None, "B", "B", None, 5]
    assert report["completed"] == 8 and report["unsupported"] == report["missing"] == 1
    assert report["gold_missing"] == 1 and report["format_failures"] == 3
    assert report["preparation_failures"] == report["prediction_failures"] == 0
    assert report["categorical_scored"] == report["scored"] == (5 if score else 0)
    assert report["categorical_accuracy"] == (0.2 if score else None)
    assert report["unscored"] == (4 if score else 9)
    assert report["score_coverage"] == (5 / 9 if score else 0)
    assert report["human_test_retest"]["scored"] == 0
    assert report["human_test_retest"]["missing"] == 9
    assert all(group["scored"] == report["scored"] for group in report["participants"].values())
    assert report["items"]["q/q"]["categorical_accuracy"] == report["categorical_accuracy"]
    assert sum(call[0] == "ChatDraft" for call in llm.calls) == 8
    assert sum(call[0] == "ExtractDraft" for call in llm.calls) == 1


@pytest.mark.parametrize("stage", ["preparation", "answer"])
def test_twin_runtime_failures_remain_unscored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str) -> None:
    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if (schema is ChatDraft) == (stage == "answer"):
            raise RuntimeError("SECRET_FAILURE")
        return {"items": []}

    llm = FakeLLM(answer)
    monkeypatch.setattr(tw, "make_llm", lambda _: llm)
    monkeypatch.setattr(tw, "make_embedder", lambda _: HashingEmbedder())
    question = tw.QuestionInput("p", "q", "q", "MC", "?", (), ("A", "B"), None, "Past self-report")
    case = tw.Case(question, "categorical", tw.Gold("B", "B"))
    out = tmp_path / "run"
    report = tw.run_evaluation([case] * 2, out, Settings())
    assert report["completed"] == report["scored"] == 0
    assert report["unscored"] == 2 and report["score_coverage"] == 0
    assert report["format_failures"] == 0
    assert report["preparation_failures"] == (2 if stage == "preparation" else 0)
    assert report["prediction_failures"] == (2 if stage == "answer" else 0)
    assert report["human_test_retest"]["scored"] == 2
    rows = records(out)
    assert all(all(value is None for value in row["scores"].values()) for row in rows)
    assert rows[1]["persona"]["cache_hit"]
    assert sum(call[0] == "ExtractDraft" for call in llm.calls) == 1
    assert sum(call[0] == "ChatDraft" for call in llm.calls) == (0 if stage == "preparation" else 2)
    assert "SECRET_FAILURE" not in (out / "records.jsonl").read_text()


@pytest.mark.parametrize("history", [(), (pm.Turn("assistant", "only other"),), (pm.Turn("user", "   "),)])
def test_empty_or_non_target_history_abstention_is_success(
    history: tuple[pm.Turn, ...], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pm, "make_llm", lambda _: fake_persona("Not enough evidence", abstain=True))
    monkeypatch.setattr(pm, "make_embedder", lambda _: HashingEmbedder())
    case = pm.Case(pm.QuestionInput("q", "?", ("a", "b", "c", "d"), history), pm.QUESTION_TYPES[0], pm.Gold("a", "a"))
    report = pm.run_evaluation([case], tmp_path / "out", Settings(), score=True)
    assert report["completed"] == 1 and report["preparation_failures"] == report["prediction_failures"] == 0
    assert records(tmp_path / "out")[0]["persona"]["abstain"]


def test_nonempty_profile_candidates_merge_index_and_answer() -> None:
    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ == "ExtractDraft":
            return {
                "items": [
                    {"facet_id": "2.1", "statement": "Prefers Atlas", "quotes": [{"n": 1, "quote": "I prefer Atlas"}]},
                    {"facet_id": "2.1", "statement": "Chooses Atlas", "quotes": [{"n": 1, "quote": "Atlas"}]},
                ]
            }
        if schema.__name__ == "MergeDraft":
            ids = re.findall(r"\[(pc_[0-9a-f]+)\]", user)
            assert ids
            return {"items": [{"statement": "Prefers Atlas", "candidate_ids": ids}]}
        assert schema is ChatDraft and "Prefers Atlas" in user
        return {"reply": "Atlas", "citations": [], "confidence": 0.5}

    llm = FakeLLM(answer)
    runtime = pr.PersonaRuntime(Settings(), llm, HashingEmbedder())
    try:
        reply = runtime.predict("a", (pr.SourceInput("h", "chat", (("user", "I prefer Atlas", ""),)),), "project?")
        assert reply.reply == "Atlas"
        with PersonaStore(next(runtime.root.glob("*.db"))) as store:
            assert len(store.list_candidates()) == 2 and len(store.list_items()) == 1
            assert store.get_vectors("items")[0] == [store.list_items()[0].item_id]
        assert [call[0] for call in llm.calls] == ["ExtractDraft", "MergeDraft", "ChatDraft"]
    finally:
        runtime.close()


def test_answer_failure_keeps_successful_preparation_and_cleanup() -> None:
    calls = 0

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        nonlocal calls
        if schema is ChatDraft:
            calls += 1
            if calls == 1:
                raise RuntimeError("SECRET_ANSWER")
            return {"reply": "Atlas", "citations": [], "confidence": 0.5}
        return {"items": []}

    llm = FakeLLM(answer)
    runtime = pr.PersonaRuntime(Settings(), llm, HashingEmbedder())
    source = (pr.SourceInput("h", "chat", (("user", "Atlas", ""),)),)
    try:
        with pytest.raises(RuntimeError):
            runtime.predict("a", source, "project?")
        runtime.predict("a", source, "project?")
        assert runtime.metadata["cache_hit"] and sum(c[0] == "ExtractDraft" for c in llm.calls) == 1
    finally:
        runtime.close()
    assert not runtime.root.exists()


@pytest.mark.parametrize("response", ["B or A", "The answer is B", "1", "(B)"])
def test_twin_ambiguous_labels_are_format_failures(response: str) -> None:
    question = tw.QuestionInput("p", "q", "q", "MC", "?", (), ("A", "B"), None, "")
    assert tw.parse_prediction(question, response) is None


def test_runtime_settings_and_legal_input_fingerprints() -> None:
    sources = (pr.SourceInput("history", "chat", (("user", "PAST", ""),)),)
    settings = Settings()
    key = pr.preparation_key("p", sources, settings)
    assert key != pr.preparation_key("other", sources, settings)
    assert key != pr.preparation_key("p", sources, settings.model_copy(update={"llm": LLMSettings(model="other")}))
    assert key == pr.preparation_key("p", sources, settings.model_copy(update={"db_path": Path("elsewhere")}))


def test_twin_empty_structured_history_does_not_fall_back_to_legacy_text() -> None:
    question = tw.QuestionInput("p", "q", "q", "MC", "?", (), ("A", "B"), None, "LEGACY", ())
    source = tw.TwinSystem.sources(question)[0]
    assert source.entries == () and not source.narrated
    assert pr.parse_source(source, Settings()) is None
    text_source = tw.TwinSystem.sources(replace(question, past_questionnaire=None))[0]
    assert text_source.narrated and text_source.entries[0][1] == "LEGACY"


@pytest.mark.parametrize("benchmark", ["longmemeval", "personamem", "twin2k500"])
def test_runtime_fingerprint_preserves_scoring_protocol(
    benchmark: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module: Any = {"longmemeval": lm, "personamem": pm, "twin2k500": tw}[benchmark]
    monkeypatch.setattr(module, "make_llm", lambda _: fake_persona())
    monkeypatch.setattr(module, "make_embedder", lambda _: HashingEmbedder())
    if benchmark == "longmemeval":
        monkeypatch.setattr(lm, "make_panel", lambda _: (Judge(FakeLLM(lambda *_: {"correct": True}), "low"),))
        case: Any = lm.Case(lm.QuestionInput("q", "?", "", ()), "single-session-user", lm.Gold("Atlas", ()))
    elif benchmark == "personamem":
        case = pm.Case(pm.QuestionInput("q", "?", ("a", "b", "c", "d"), ()), pm.QUESTION_TYPES[0], pm.Gold("a", "a"))
    else:
        q = tw.QuestionInput("p", "q", "q", "MC", "?", (), ("A", "B"), None, "")
        case = tw.Case(q, "categorical", tw.Gold("A"))
    reports = [
        module.run_evaluation([case], tmp_path / str(i), Settings(), score=score)
        for i, score in enumerate((False, True))
    ]
    assert reports[0]["fingerprints"]["runtime_configuration"] != reports[1]["fingerprints"]["runtime_configuration"]
    if benchmark == "longmemeval":
        changed = module.run_evaluation(
            [case], tmp_path / "judge", Settings(judges=[LLMSettings(model="different")]), score=True
        )
        assert changed["fingerprints"]["runtime_configuration"] != reports[1]["fingerprints"]["runtime_configuration"]
        changed_again = module.run_evaluation(
            [case], tmp_path / "judge2", Settings(judges=[LLMSettings(model="different-again")]), score=True
        )
        assert (
            changed["fingerprints"]["runtime_configuration"] != changed_again["fingerprints"]["runtime_configuration"]
        )


def test_a_timed_out_merge_still_answers_from_unmerged_candidates() -> None:
    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ == "ExtractDraft":
            return {
                "items": [
                    {"facet_id": "2.1", "statement": "Prefers Atlas", "quotes": [{"n": 1, "quote": "I prefer Atlas"}]},
                    {"facet_id": "2.1", "statement": "Chooses Atlas", "quotes": [{"n": 1, "quote": "Atlas"}]},
                ]
            }
        if schema.__name__ == "MergeDraft":
            raise LLMError("timed out")
        assert schema is ChatDraft and "Prefers Atlas" in user and "Chooses Atlas" in user
        return {"reply": "Atlas", "citations": [], "confidence": 0.5}

    runtime = pr.PersonaRuntime(Settings(), FakeLLM(answer), HashingEmbedder())
    try:
        reply = runtime.predict("a", (pr.SourceInput("h", "chat", (("user", "I prefer Atlas", ""),)),), "project?")
        assert reply.reply == "Atlas"
        assert runtime.metadata["preparation_degraded"] == ["merge 2.1: LLMError"]
        assert "preparation_failure" not in runtime.metadata
    finally:
        runtime.close()


def atlas_build(*, merge_fails: bool = False, wait: Callable[[], object] | None = None) -> FakeLLM:
    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema.__name__ == "ExtractDraft":
            if wait is not None:
                wait()
            return {
                "items": [
                    {"facet_id": "2.1", "statement": "Prefers Atlas", "quotes": [{"n": 1, "quote": "I prefer Atlas"}]},
                    {"facet_id": "2.1", "statement": "Chooses Atlas", "quotes": [{"n": 1, "quote": "Atlas"}]},
                ]
            }
        if schema.__name__ == "MergeDraft":
            if merge_fails:
                raise LLMError("timed out")
            return {"items": [{"statement": "Prefers Atlas", "candidate_ids": re.findall(r"\[(pc_[0-9a-f]+)\]", user)}]}
        assert schema is ChatDraft and "Prefers Atlas" in user
        return {"reply": "Atlas", "citations": [], "confidence": 0.5}

    return FakeLLM(answer)


def cached_predict(cache: pr.ProfileCache, llm: FakeLLM) -> dict[str, Any]:
    runtime = pr.PersonaRuntime(Settings(), llm, HashingEmbedder(), cache)
    try:
        source = (pr.SourceInput("h", "chat", (("user", "I prefer Atlas", ""),)),)
        assert runtime.predict("a", source, "project?").reply == "Atlas"
        return runtime.metadata
    finally:
        runtime.close()


def test_profile_cache_reuses_each_repeats_own_build_until_build_code_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "profiles"
    first = atlas_build()
    assert cached_predict(pr.ProfileCache(root, "r1"), first)["profile_cache"] == "miss"
    assert [call[0] for call in first.calls] == ["ExtractDraft", "MergeDraft", "ChatDraft"]
    (cached,) = root.glob("*-r1.db")
    assert cached.stat().st_mode & 0o777 == 0o600 and root.stat().st_mode & 0o777 == 0o700

    again = atlas_build()
    metadata = cached_predict(pr.ProfileCache(root, "r1"), again)
    assert metadata["profile_cache"] == "hit" and metadata["stages"]["preparation"]["calls"] == 0
    assert [call[0] for call in again.calls] == ["ChatDraft"]

    assert cached_predict(pr.ProfileCache(root, "r2"), atlas_build())["profile_cache"] == "miss"
    monkeypatch.setattr(pr, "build_code_fingerprint", lambda: "changed")
    assert cached_predict(pr.ProfileCache(root, "r1"), atlas_build())["profile_cache"] == "miss"


def test_repeats_sharing_a_slot_build_once_and_the_others_restore(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    started = threading.Event()
    release = threading.Event()

    def held() -> None:
        started.set()
        assert release.wait(10)

    # The first build holds extraction open until the others are queued on the same slot.
    builder, waiters = atlas_build(wait=held), [atlas_build(), atlas_build()]
    results: list[dict[str, Any]] = []

    def run(llm: FakeLLM) -> None:
        results.append(cached_predict(pr.ProfileCache(root, "r1"), llm))

    threads = [threading.Thread(target=run, args=(llm,)) for llm in [builder, *waiters]]
    threads[0].start()
    assert started.wait(10)
    for thread in threads[1:]:
        thread.start()
    time.sleep(0.2)
    release.set()
    for thread in threads:
        thread.join(10)
    assert sorted(r["profile_cache"] for r in results) == ["hit", "hit", "miss"]
    assert [call[0] for call in builder.calls] == ["ExtractDraft", "MergeDraft", "ChatDraft"]
    assert all([call[0] for call in llm.calls] == ["ChatDraft"] for llm in waiters)
    assert len(list(root.glob("*-r1.db"))) == 1


def test_profile_cache_skips_degraded_and_failed_builds(tmp_path: Path) -> None:
    root = tmp_path / "profiles"
    assert cached_predict(pr.ProfileCache(root, "r1"), atlas_build(merge_fails=True))["profile_cache"] == "miss"
    assert not list(root.glob("*.db"))

    def broken(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        raise LLMError("down")

    runtime = pr.PersonaRuntime(Settings(), FakeLLM(broken), HashingEmbedder(), pr.ProfileCache(root, "r1"))
    try:
        with pytest.raises(pr.PreparationError):
            runtime.predict("a", (pr.SourceInput("h", "chat", (("user", "I prefer Atlas", ""),)),), "project?")
    finally:
        runtime.close()
    assert not list(root.glob("*.db"))


def atlas_sources(subject: str, text: str = "I prefer Atlas") -> tuple[pr.SourceInput, ...]:
    return (pr.SourceInput("h", "chat", (("user", f"{text} ({subject})", ""),)),)


def test_parallel_preparation_reports_each_subject_as_if_built_on_its_first_question(tmp_path: Path) -> None:
    # Both builds wait for each other inside extraction, so their calls interleave in one recorder.
    llm = atlas_build(wait=threading.Barrier(2, timeout=10).wait)
    runtime = pr.PersonaRuntime(Settings(), llm, HashingEmbedder(), pr.ProfileCache(tmp_path, "r1"))
    try:
        with record_usage(UsageRecorder()):
            runtime.prepare([(s, atlas_sources(s)) for s in "aba"], workers=2)
            assert sorted(call[0] for call in llm.calls) == ["ExtractDraft"] * 2 + ["MergeDraft"] * 2
            for subject in "ab":
                assert runtime.predict(subject, atlas_sources(subject), "project?").reply == "Atlas"
                metadata = runtime.metadata
                assert not metadata["cache_hit"] and metadata["profile_cache"] == "miss"
                assert metadata["stages"]["preparation"]["calls"] == 2
            runtime.predict("a", atlas_sources("a"), "project again?")
            assert runtime.metadata["cache_hit"] and set(runtime.metadata["stages"]) == {"answer"}
        assert sum(call[0] == "ExtractDraft" for call in llm.calls) == 2 and len(list(tmp_path.glob("*.db"))) == 2
    finally:
        runtime.close()


def test_a_failed_parallel_preparation_fails_only_its_subject(monkeypatch: pytest.MonkeyPatch) -> None:
    build = pr.build_profile

    def flaky(store: PersonaStore, llm: Any, settings: Settings, **options: Any) -> BuildReport:
        if any("BROKEN" in e.text for e in store.list_expressions()):
            return BuildReport(failures=["extract: LLMError"])
        return build(store, llm, settings, **options)

    monkeypatch.setattr(pr, "build_profile", flaky)
    llm = atlas_build()
    runtime = pr.PersonaRuntime(Settings(), llm, HashingEmbedder())
    broken = atlas_sources("b", "BROKEN")
    try:
        with record_usage(UsageRecorder()):
            runtime.prepare([("a", atlas_sources("a")), ("b", broken)], workers=2)
            assert runtime.predict("a", atlas_sources("a"), "project?").reply == "Atlas"
            with pytest.raises(pr.PreparationError):
                runtime.predict("b", broken, "project?")
            assert runtime.metadata["preparation_failure"] and not runtime.metadata["cache_hit"]
            assert runtime.metadata["preparation_failures"] == ["extract: LLMError"]
            with pytest.raises(pr.PreparationError):
                runtime.predict("b", broken, "project again?")
            assert runtime.metadata["cache_hit"] and runtime.metadata["preparation_failure"]
        assert sum(call[0] == "ChatDraft" for call in llm.calls) == 1
    finally:
        runtime.close()


def test_one_preparation_worker_still_builds_before_answering() -> None:
    llm = atlas_build()
    runtime = pr.PersonaRuntime(Settings(), llm, HashingEmbedder())
    try:
        with record_usage(UsageRecorder()):
            runtime.prepare([("a", atlas_sources("a")), ("b", atlas_sources("b"))], workers=1)
            assert [call[0] for call in llm.calls] == ["ExtractDraft", "MergeDraft"] * 2
            runtime.predict("a", atlas_sources("a"), "project?")
            assert not runtime.metadata["cache_hit"] and "preparation" in runtime.metadata["stages"]
    finally:
        runtime.close()


def echo_persona(parties: int) -> FakeLLM:
    """Answers with the question's own marker, and only once ``parties`` answers are in flight together."""
    barrier = threading.Barrier(parties, timeout=10)

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is ChatDraft:
            barrier.wait()
            marker = re.findall(r"marker-\w+", user)[-1]
            return {"reply": marker, "citations": [], "confidence": 0.5, "mode": "general"}
        return {"items": []}

    return FakeLLM(answer)


def test_benchmark_answers_concurrently_and_records_in_question_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = echo_persona(3)
    monkeypatch.setattr(pm, "make_llm", lambda _: llm)
    monkeypatch.setattr(pm, "make_embedder", lambda _: HashingEmbedder())
    cases = [
        pm.Case(
            pm.QuestionInput(
                f"q{i}", f"marker-q{i}?", ("A", "B", "C", "D"), (pm.Turn("user", f"I prefer Atlas {s}"),), subject_id=s
            ),
            pm.QUESTION_TYPES[0],
            pm.Gold("b", "b"),
        )
        for i, s in enumerate("aab")
    ]
    report = pm.run_evaluation(cases, tmp_path / "out", Settings(), answer_workers=3)
    rows = records(tmp_path / "out")
    assert report["completed"] == 3 and [r["question_id"] for r in rows] == ["q0", "q1", "q2"]
    # Each row keeps its own thread's answer and the build lands on each subject's first question.
    assert [r["model_response"] for r in rows] == [f"marker-q{i}" for i in range(3)]
    assert [r["persona"]["reply"] for r in rows] == [f"marker-q{i}" for i in range(3)]
    assert [r["persona"]["cache_hit"] for r in rows] == [False, True, False]
    hypotheses = [json.loads(line) for line in (tmp_path / "out" / "hypotheses.jsonl").read_text().splitlines()]
    assert [h["question_id"] for h in hypotheses] == ["q0", "q1", "q2"]


def test_twin2k500_and_longmemeval_answer_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    llm = echo_persona(2)
    for module in (tw, lm):
        monkeypatch.setattr(module, "make_llm", lambda _: llm)
        monkeypatch.setattr(module, "make_embedder", lambda _: HashingEmbedder())
    item = tw.QuestionInput(
        "participant", "q", "q", "TE", "marker-x?", (), (), None, "legacy", (("Past question?", "Past answer", ""),)
    )
    items = [
        tw.Case(replace(item, question_id=str(i), question=f"marker-t{i}?"), "numeric", tw.Gold(None, None))
        for i in range(2)
    ]
    tw.run_evaluation(items, tmp_path / "t2k", Settings(), answer_workers=2)
    assert [r["model_response"] for r in records(tmp_path / "t2k")] == ["marker-t0", "marker-t1"]
    session = lm.Session(0, "s", "2025/01/02 (Thu) 10:00", (lm.Turn("user", "Atlas"),))
    questions = [
        lm.Case(lm.QuestionInput(f"q{i}", f"marker-l{i}?", "2025/01/03 (Fri) 10:00", (session,)), "single-session-user",
                lm.Gold("Atlas", ("s",)))
        for i in range(2)
    ]  # fmt: skip
    lm.run_evaluation(questions, tmp_path / "lme", Settings(), answer_workers=2)
    assert [r["hypothesis"] for r in records(tmp_path / "lme")] == ["marker-l0", "marker-l1"]


def test_limited_llm_caps_calls_in_flight_across_wrappers() -> None:
    lock, active, peak = threading.Lock(), [0], [0]

    def answer(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        threading.Event().wait(0.02)
        with lock:
            active[0] -= 1
        return {"items": []}

    class Empty(BaseModel):
        items: list[str] = []

    slots = threading.Semaphore(2)
    wrapped = [pr.limit_calls(FakeLLM(answer), slots) for _ in range(2)]
    assert pr.limit_calls(wrapped[0], None) is wrapped[0] and wrapped[0].name == FakeLLM(answer).name
    threads = [
        threading.Thread(target=lambda llm=llm: llm.structured(system="s", user="u", schema=Empty))
        for llm in wrapped * 4
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert peak[0] == 2


def test_in_order_yields_in_input_order_and_raises_at_the_failing_item() -> None:
    def slow_first(n: int) -> int:
        if n == 0:
            threading.Event().wait(0.05)
        if n == 3:
            raise ValueError("boom")
        return n * 10

    seen = []
    with pytest.raises(ValueError, match="boom"):
        for item, result in pr.in_order(slow_first, [0, 1, 2, 3, 4], 3):
            seen.append((item, result))
    assert seen == [(0, 0), (1, 10), (2, 20)]


def test_benchmark_prepares_subjects_in_parallel_before_answering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    llm = fake_persona("(b)")
    monkeypatch.setattr(pm, "make_llm", lambda _: llm)
    monkeypatch.setattr(pm, "make_embedder", lambda _: HashingEmbedder())
    cases = [
        pm.Case(
            pm.QuestionInput(
                f"q{i}", "project?", ("A", "B", "C", "D"), (pm.Turn("user", f"I prefer Atlas {s}"),), subject_id=s
            ),
            pm.QUESTION_TYPES[0],
            pm.Gold("b", "b"),
        )
        for i, s in enumerate("aab")
    ]
    pm.run_evaluation(cases, tmp_path / "out", Settings(), prepare_workers=2)
    names = [call[0] for call in llm.calls]
    assert names.index("ChatDraft") > max(i for i, name in enumerate(names) if name == "ExtractDraft")
    rows = records(tmp_path / "out")
    assert [r["persona"]["cache_hit"] for r in rows] == [False, True, False]
    assert all("preparation" in r["persona"]["stages"] for r in (rows[0], rows[2]))


def test_judges_stay_within_their_own_cap_while_answers_run_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lock = threading.Lock()
    running = peak = 0

    def judge(*_: Any) -> dict[str, Any]:
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return {"correct": True}

    monkeypatch.setattr(lm, "make_llm", lambda _: fake_persona())
    monkeypatch.setattr(lm, "make_embedder", lambda _: HashingEmbedder())
    monkeypatch.setattr(lm, "make_panel", lambda _: (Judge(FakeLLM(judge), "low"), Judge(FakeLLM(judge), "low")))
    session = lm.Session(0, "s", "2024/01/01 (Mon) 10:00", (lm.Turn("user", "I prefer Atlas"),))
    cases = [
        lm.Case(lm.QuestionInput(f"q{i}", "project?", "2024/01/02 (Tue) 10:00", (session,)), "multi-session",
                lm.Gold("Atlas", ("s",)))
        for i in range(6)
    ]  # fmt: skip
    report = lm.run_evaluation(
        cases, tmp_path / "out", Settings(), score=True, answer_workers=6, judge_slots=threading.Semaphore(1)
    )
    assert report["completed"] == 6 and peak == 1
