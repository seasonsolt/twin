"""Offline integration coverage of public benchmarks using the production persona chain."""

from __future__ import annotations

import datetime as dt
import json
import re
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
from twin.llm import FakeLLM
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
    assert [r["model_response"] for r in rows[:8]] == [response for response, _ in replies]
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
        from twin.evals.harness import Judge

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
