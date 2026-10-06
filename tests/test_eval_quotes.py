"""Offline quote verification with invented text only."""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.evals.harness import Judge
from twin.evals.personal import (
    PersonaSystem,
    compare_reports,
    extract_quotes,
    load_evalset,
    normalize_quote,
    read_records,
    run_evaluation,
    run_persona_evaluation,
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
    Scenario,
    SystemSpec,
)
from twin.llm import FakeLLM
from twin.persona.chat import PersonaChat, index_persona
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.profile import ExtractDraft
from twin.persona.schema import ChatDraft, ChatReply, EvidenceClass, SourceKind
from twin.persona.sources import parse_text, pseudonym
from twin.persona.store import PersonaStore

FIXTURE = Path(__file__).parent / "fixtures" / "personal_eval"
DAY = dt.date(2026, 1, 1)


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith(("TWIN_", "DTWIN_", "OPENAI_", "ANTHROPIC_")):
            monkeypatch.delenv(name)
    monkeypatch.setenv("TWIN_LLM_KEY", "invented-offline-key")
    monkeypatch.setenv("TWIN_EMBED_KEY", "invented-offline-key")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            '「春天沿河散步」『夏天沿河散步』“秋天沿河散步”"冬天沿河散步"',
            ["春天沿河散步", "夏天沿河散步", "秋天沿河散步", "冬天沿河散步"],
        ),
        ("「他说『先核对数据』然后“再核对日期”」", ["他说『先核对数据』然后“再核对日期”", "先核对数据", "再核对日期"]),
        ("「外层「内层四字」后面四字」", ["外层「内层四字」后面四字", "内层四字"]),
        ('“外层里有"ASCII Words"和『中文四字』”', ['外层里有"ASCII Words"和『中文四字』', "ASCII Words", "中文四字"]),
        ("」未打开』没打开” 「未关闭 “也未关闭", []),
        ("「未关闭『完整四字』", ["完整四字"]),
        ("「错配四字』", []),
        ("「错配』仍然完整」", ["错配』仍然完整"]),
        ('「词语」『三个字』“Ａ，Ｂ Ｃ”"! ? ..."「四个汉字」', ["四个汉字"]),
        ('" ＡＢＣＤ， "', [" ＡＢＣＤ， "]),
        ("「重复四字」「重复四字」", ["重复四字", "重复四字"]),
        (r'\"不是引号\" "真实四字"', ["真实四字"]),
        (r'"他说\"先核对数据\"再决定"', [r"他说\"先核对数据\"再决定"]),
        ("没有引用，'单引号不算引用'。", []),
    ],
)
def test_extract_quotes(text: str, expected: list[str]) -> None:
    assert extract_quotes(text) == expected


def test_normalize_quote() -> None:
    assert normalize_quote(" ＡＢＣＤ，ＥＦ！\n「核 对：数据」") == "abcdef核对数据"
    assert normalize_quote("Café — ＣＡＦÉ") == "cafécafé"
    assert normalize_quote("甲+乙€") == "甲+乙€"  # Symbols are not punctuation.
    assert extract_quotes('"ﬃx"') == ["ﬃx"]  # Length is checked after NFKC.


def question() -> CaseInput:
    return CaseInput(
        case_id="invented",
        scenario=Scenario.PERSONAL,
        mode="persona",
        payload=QuestionInput(id="invented", category="fact", prompt="虚构问题"),
    )


def add_document(store: PersonaStore, settings: Settings, name: str, text: str, date: dt.date | None = DAY) -> str:
    parsed = parse_text(SourceKind.DOCUMENT, name, text, settings, date)
    store.put_source(parsed)
    return parsed.expressions[0].expression_id


def item(store: PersonaStore, expression_id: str, quote: str, statement: str = "我会保持虚构耐心。") -> PersonaItem:
    entry = store.get_expression(expression_id)
    assert entry is not None
    result = PersonaItem(
        item_id="pi_invented",
        facet_id="1.1",
        statement=statement,
        evidence=[
            PEvidence(
                expression_id=expression_id,
                source_id=entry.source_id,
                source_kind=SourceKind.DOCUMENT,
                evidence_class=EvidenceClass.BEHAVIOR,
                date=entry.date,
                quote=quote,
            )
        ],
    )
    store.replace_facet_items("1.1", [result])
    return result


def system(store: PersonaStore, settings: Settings, text: str, citations: list[str]) -> PersonaSystem:
    llm = FakeLLM(
        lambda s, u, schema: {"reply": text, "citations": citations, "confidence": 0.8, "abstain": not citations}
    )
    embedder = HashingEmbedder()
    index_persona(store, embedder, settings)

    class MetricChat(PersonaChat):
        def reply(self, messages: Any, as_of: dt.date | None = None, *, persist: bool = True) -> ChatReply:
            # Feed the original draft to the metric so its fixtures remain independent of the runtime guard.
            reply = super().reply(messages, as_of, persist=persist)
            return reply.model_copy(update={"reply": text, "quotes_removed": 0})

    return PersonaSystem(MetricChat(store, llm, embedder, settings))


def test_classification_fabrication_elsewhere_and_repeated_quotes(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    settings = Settings(target_name="虚构林沐")
    with PersonaStore(":memory:") as store:
        ref = add_document(store, settings, "cited.txt", "我总是先核对数据。 ABCDEF")
        adapter = system(
            store,
            settings,
            '「我总是先核对数据。」“我总是先核对数据”『我喜欢沿着河边散步』"我曾驾驶飞船旅行"“ＡＢＣＤ，ＥＦ”',
            [ref],
        )
        # Allowed corpus material need not have been retrieved (or even indexed) for this turn.
        add_document(store, settings, "other.txt", "我喜欢沿着河边散步。")
        prediction = adapter.predict(question(), as_of=None, repeat=0)
        assert prediction.raw["quotes"] == {"total": 5, "cited": 3, "elsewhere": 1, "question": 0, "unverified": 1}
        assert len(adapter.chat.llm.calls) == 1
        assert set(prediction.raw) == {"artifacts", "quotes", "quotes_removed", "mode"}
        assert prediction.raw["quotes_removed"] == 0
        assert prediction.raw["mode"] == "grounded"
        assert "飞船" not in json.dumps(prediction.raw, ensure_ascii=False)
        assert "飞船" not in caplog.text and "虚构问题" not in caplog.text
        assert store._db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 0


def test_question_spans_follow_material_precedence(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    settings = Settings(target_name="虚构林沐")
    prompt = "虚构问题：我总是先核对数据；我喜欢沿着河边散步；如何理解ＡＢＣＤ，ＥＦ？"
    case = question().model_copy(update={"payload": QuestionInput(id="invented", category="fact", prompt=prompt)})
    with PersonaStore(":memory:") as store:
        ref = add_document(store, settings, "cited.txt", "我总是先核对数据。")
        add_document(store, settings, "other.txt", "我喜欢沿着河边散步。")
        text = '「我总是先核对数据」『我喜欢沿着河边散步』"abcd ef"“ABCDEF”「我曾驾驶飞船旅行」'
        adapter = system(store, settings, text, [ref])
        prediction = adapter.predict(case, as_of=None, repeat=0)
        assert prediction.raw["quotes"] == {
            "total": 5,
            "cited": 1,
            "elsewhere": 1,
            "question": 2,
            "unverified": 1,
        }
        assert len(adapter.chat.llm.calls) == 1
        assert "abcd" not in json.dumps(prediction.raw)
        assert prompt not in caplog.text and text not in caplog.text
        assert "abcd ef" not in caplog.text and "飞船" not in caplog.text
        assert store._db.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 0


@pytest.mark.parametrize("cite_item", [False, True])
@pytest.mark.parametrize("cited", [False, True])
def test_pseudonymized_and_raw_names_match_visible_material(cite_item: bool, cited: bool) -> None:
    settings = Settings(target_name="虚构林沐", pseudonymize_others=True)
    with PersonaStore(":memory:") as store:
        parsed = parse_text(
            SourceKind.CHAT,
            "invented-chat.txt",
            "2026-01-01 10:00 虚构许舟：要核对日期吗？\n2026-01-01 10:01 虚构林沐：我和虚构许舟先核对日期。",
            settings,
        )
        store.put_source(parsed)
        own = parsed.expressions[-1]
        profile = item(store, own.expression_id, own.text)
        viewed_quote = own.text.replace("虚构许舟", pseudonym("虚构许舟"))
        adapter = system(
            store,
            settings,
            f"「{viewed_quote}」『{own.text}』",
            [profile.item_id if cite_item else own.expression_id] if cited else [],
        )
        prediction = adapter.predict(question(), as_of=DAY, repeat=0)
        assert prediction.raw["quotes"] == {
            "total": 2,
            "cited": 2 if cited else 0,
            "elsewhere": 0 if cited else 2,
            "question": 0,
            "unverified": 0,
        }
        material = adapter.chat.llm.calls[0][1] + adapter.chat.llm.calls[0][2]
        assert viewed_quote in material and "虚构许舟" not in material


def test_no_quotes_or_short_terms_are_measured_zero() -> None:
    with PersonaStore(":memory:") as store:
        adapter = system(store, Settings(target_name="虚构林沐"), '「术语」『三个字』“Ａ，Ｂ Ｃ”"...."', [])
        assert adapter.predict(question(), as_of=None, repeat=0).raw["quotes"] == {
            "total": 0,
            "cited": 0,
            "elsewhere": 0,
            "question": 0,
            "unverified": 0,
        }


def test_cited_item_statement_and_uncited_evidence() -> None:
    settings = Settings(target_name="虚构林沐")
    with PersonaStore(":memory:") as store:
        ref = add_document(store, settings, "cited.txt", "我总是先核对数据。")
        profile = item(store, ref, "我总是先核对数据。")
        adapter = system(store, settings, "「我会保持虚构耐心」『我总是先核对数据』", [profile.item_id])
        assert adapter.predict(question(), as_of=None, repeat=0).raw["quotes"] == {
            "total": 2,
            "cited": 2,
            "elsewhere": 0,
            "question": 0,
            "unverified": 0,
        }
        uncited = system(store, settings, "「我会保持虚构耐心」『我总是先核对数据』", [])
        assert uncited.predict(question(), as_of=None, repeat=0).raw["quotes"] == {
            "total": 2,
            "cited": 0,
            "elsewhere": 1,
            "question": 0,
            "unverified": 1,
        }


@pytest.mark.parametrize("hidden_kind", ["future", "undated", "other_speaker"])
def test_hidden_expression_is_not_elsewhere(hidden_kind: str) -> None:
    settings = Settings(target_name="虚构林沐")
    quote = "我曾驾驶虚构飞船。"
    with PersonaStore(":memory:") as store:
        ref = add_document(store, settings, "cited.txt", "我总是先核对数据。")
        parsed = parse_text(SourceKind.DOCUMENT, "hidden.txt", quote, settings, DAY)
        updates: dict[str, Any] = {
            "future": {"date": DAY + dt.timedelta(days=1)},
            "undated": {"date": None},
            "other_speaker": {"is_target": False, "speaker": "虚构许舟"},
        }[hidden_kind]
        parsed.expressions[0] = parsed.expressions[0].model_copy(update=updates)
        store.put_source(parsed)
        adapter = system(store, settings, f"「{quote}」", [ref])
        assert adapter.predict(question(), as_of=DAY, repeat=0).raw["quotes"] == {
            "total": 1,
            "cited": 0,
            "elsewhere": 0,
            "question": 0,
            "unverified": 1,
        }
        if hidden_kind in {"future", "undated"}:
            assert adapter.predict(question(), as_of=None, repeat=0).raw["quotes"]["elsewhere"] == 1


def test_as_of_filters_item_evidence_too() -> None:
    settings = Settings(target_name="虚构林沐")
    with PersonaStore(":memory:") as store:
        past = add_document(store, settings, "past.txt", "我总是先核对数据。")
        future = add_document(store, settings, "future.txt", "我明天驾驶虚构飞船。", DAY + dt.timedelta(days=1))
        future_item = item(store, future, "我明天驾驶虚构飞船。")
        profile = item(store, past, "我总是先核对数据。")
        profile.evidence += future_item.evidence
        store.replace_facet_items("1.1", [profile])
        adapter = system(store, settings, "「我明天驾驶虚构飞船」", [profile.item_id])
        assert adapter.predict(question(), as_of=DAY, repeat=0).raw["quotes"]["unverified"] == 1
        assert adapter.predict(question(), as_of=None, repeat=0).raw["quotes"]["cited"] == 1


def test_quote_boundary_failure_hides_text(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    secret = "虚构问题 虚构回答 虚构原话"
    settings = Settings(target_name="虚构林沐")
    with PersonaStore(":memory:") as store:
        adapter = system(store, settings, "「虚构原话」", [])

        def fails(*args: Any, **kwargs: Any) -> Any:
            raise RuntimeError(secret)

        monkeypatch.setattr("twin.evals.personal.expression_view", fails)
        with pytest.raises(RuntimeError, match="详情已隐藏") as caught:
            adapter.predict(question(), as_of=None, repeat=0)
        assert secret not in str(caught.value) and caught.value.__suppress_context__
        assert secret not in caplog.text


class CountedSystem:
    spec = SystemSpec(
        system_id="invented",
        label="invented",
        supports_as_of=False,
        supports_abstain=False,
        supports_confidence=False,
    )

    def predict(self, case_input: CaseInput, *, as_of: dt.date | None, repeat: int) -> Prediction:
        counts = {"total": 0, "cited": 0, "elsewhere": 0, "unverified": 0}
        if case_input.case_id == "f1":
            counts = (
                {"total": 4, "cited": 2, "elsewhere": 0, "question": 1, "unverified": 1}
                if repeat == 0
                else {"total": 1, "cited": 0, "elsewhere": 1, "unverified": 0}
            )
        if case_input.case_id == "s1" and repeat == 0:
            counts = {"total": 2, "cited": 0, "elsewhere": 0, "unverified": 2}
        return Prediction(
            case_id=case_input.case_id,
            system_id=self.spec.system_id,
            mode=case_input.mode,
            repeat=repeat,
            text="虚构回答",
            payload=QuestionOutput(reply="虚构回答"),
            raw={"quotes": counts},
        )


def grade(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    if schema.__name__ == "_Style":
        return {"persona": 4, "quality": 3, "reason": "虚构评价"}
    if schema.__name__ == "_Quality":
        return {"quality": 3, "reason": "虚构评价"}
    return {"score": 1, "reason": "虚构评价"}


def counted_report() -> Report:
    return run_evaluation(
        load_evalset(FIXTURE / "evalset.json"),
        CountedSystem(),
        (Judge(FakeLLM(grade), "low"),),
        FIXTURE / "persona.txt",
        repeats=2,
    )


def test_summary_pools_spans_not_repeat_rates_or_judge_calls(tmp_path: Path) -> None:
    report = counted_report()
    summary = summarize(report)
    assert summary["fact"]["quotes"] == {
        "n_replies": 6,
        "n_missing": 0,
        "replies_with_quotes": 2,
        "total": 5,
        "cited": 2,
        "elsewhere": 1,
        "question": 1,
        "unverified": 1,
        "quotes_removed": 0,
        "cited_rate": 2 / 5,
        "elsewhere_rate": 1 / 5,
        "question_rate": 1 / 5,
        "unverified_rate": 1 / 5,
    }
    assert summary["overall"]["quotes"]["total"] == 7
    assert summary["overall"]["quotes"]["n_replies"] == 12
    assert summary["overall"]["quotes"]["replies_with_quotes"] == 3
    assert summary["overall"]["quotes"]["unverified_rate"] == 3 / 7
    assert summary["overall"]["quotes"]["question_rate"] == 1 / 7
    assert summary["general"]["quotes"]["total"] == 0
    assert summary["general"]["quotes"]["unverified_rate"] is None
    assert summary["general"]["quotes"]["question_rate"] is None
    failed = report.model_copy(
        update={
            "judgements": tuple(
                row.model_copy(update={"status": JudgeStatus.FAILED, "score": None}) for row in report.judgements
            )
        }
    )
    assert summarize(failed)["overall"]["quotes"] == summary["overall"]["quotes"]
    write_outputs(tmp_path / "run", report, Settings())
    markdown = (tmp_path / "run" / "report.md").read_text()
    assert "spans=5" in markdown and "unverified=1 (0.2)" in markdown and "## overall" in markdown
    assert "question=1 (0.2)" in markdown
    assert markdown.count("原话：") == len(summary)
    assert "虚构回答" not in markdown


def test_runtime_quotes_removed_are_reported(tmp_path: Path) -> None:
    settings = Settings(target_name="虚构林沐")
    with PersonaStore(":memory:") as store:
        ref = add_document(store, settings, "cited.txt", "我总是先核对数据。")
        llm = FakeLLM(
            lambda *a: {
                "reply": "「我总是先核对数据」；『我曾驾驶飞船旅行』",
                "citations": [ref],
                "confidence": 0.8,
            }
        )
        embedder = HashingEmbedder()
        index_persona(store, embedder, settings)
        prediction = PersonaSystem(PersonaChat(store, llm, embedder, settings)).predict(
            question(), as_of=None, repeat=0
        )
        assert prediction.text == "「我总是先核对数据」；我曾驾驶飞船旅行"
        assert prediction.raw["quotes_removed"] == 1
        assert prediction.raw["quotes"] == {"total": 1, "cited": 1, "elsewhere": 0, "question": 0, "unverified": 0}
    report = counted_report()
    report = report.model_copy(
        update={
            "predictions": (
                report.predictions[0].model_copy(update={"raw": prediction.raw}),
                *report.predictions[1:],
            )
        }
    )
    assert summarize(report)["fact"]["quotes"]["quotes_removed"] == 1
    assert summarize(report)["overall"]["quotes"]["quotes_removed"] == 1
    write_outputs(tmp_path / "guarded", report, settings)
    loaded = read_records(tmp_path / "guarded" / "records.json")
    assert summarize(loaded)["overall"]["quotes"]["quotes_removed"] == 1
    assert "quotes_removed=1" in (tmp_path / "guarded" / "report.md").read_text()


def test_old_records_and_partial_coverage_compare_without_zero_filling(tmp_path: Path) -> None:
    new = counted_report()
    old = new.model_copy(update={"predictions": tuple(p.model_copy(update={"raw": {}}) for p in new.predictions)})
    write_outputs(tmp_path / "old", old, Settings())
    loaded = read_records(tmp_path / "old" / "records.json")
    assert "quotes" not in summarize(loaded)["fact"]
    assert "quotes" not in summarize(loaded)["overall"]
    assert "quotes" not in compare_reports(loaded, loaded)["categories"]["fact"]
    comparison = compare_reports(loaded, new)
    assert comparison["categories"]["fact"]["quotes"]["A"] is None
    assert comparison["categories"]["fact"]["quotes"]["B"]["unverified_rate"] == 1 / 5
    assert comparison["categories"]["overall"]["quotes"]["B"]["unverified_rate"] == 3 / 7
    assert compare_reports(new, new)["categories"]["fact"]["quotes"]["A"]["unverified_rate"] == 1 / 5
    partial = new.model_copy(update={"predictions": (old.predictions[0], *new.predictions[1:])})
    block = summarize(partial)["fact"]["quotes"]
    assert block["n_replies"] == 5 and block["n_missing"] == 1 and block["total"] == 1
    write_comparison(tmp_path / "comparison", loaded, new, Settings())
    markdown = (tmp_path / "comparison" / "report.md").read_text()
    assert "A absent；B" in markdown and "unverified=1 (0.2)" in markdown


def test_old_quote_blocks_without_question_load_and_compare(tmp_path: Path) -> None:
    new = counted_report()
    predictions = []
    for prediction in new.predictions:
        counts = dict(prediction.raw["quotes"])
        counts["unverified"] += counts.pop("question", 0)
        predictions.append(prediction.model_copy(update={"raw": {"quotes": counts}}))
    old = new.model_copy(update={"predictions": tuple(predictions)})
    write_outputs(tmp_path / "old", old, Settings())
    loaded = read_records(tmp_path / "old" / "records.json")
    assert all("question" not in p.raw["quotes"] for p in loaded.predictions)
    block = summarize(loaded)["fact"]["quotes"]
    assert block["question"] == 0 and block["question_rate"] == 0
    assert block["total"] == 5 and block["unverified"] == 2
    comparison = compare_reports(loaded, new)
    assert comparison["categories"]["fact"]["quotes"]["A"]["question_rate"] == 0
    assert comparison["categories"]["fact"]["quotes"]["B"]["question_rate"] == 1 / 5
    write_comparison(tmp_path / "comparison", loaded, new, Settings())
    markdown = (tmp_path / "comparison" / "report.md").read_text()
    assert "question=0 (0.0)" in markdown and "question=1 (0.2)" in markdown


@pytest.mark.parametrize("value", [-1, True, 1.0, "1", None, 0, 2])
def test_invalid_question_counts_are_rejected(value: Any, caplog: pytest.LogCaptureFixture) -> None:
    report = counted_report()
    first = report.predictions[0]
    counts = {**first.raw["quotes"], "question": value}
    invalid = report.model_copy(
        update={
            "predictions": (
                first.model_copy(update={"raw": {"quotes": counts}}),
                *report.predictions[1:],
            )
        }
    )
    with pytest.raises(ValueError, match="原话计数无效（详情已隐藏）"):
        summarize(invalid)
    with pytest.raises(ValueError, match="原话计数无效（详情已隐藏）"):
        compare_reports(report, invalid)
    assert "虚构回答" not in caplog.text


def test_update_quotes_use_current_private_memory(tmp_path: Path) -> None:
    path = tmp_path / "update.json"
    path.write_text(
        json.dumps(
            [
                {
                    "id": "invented-update",
                    "category": "update",
                    "question": "虚构问题：我选择什么？",
                    "answer": "桂花茶",
                    "add_fact": "我选择桂花茶。",
                    "modified_fact": "我选择薄荷茶。",
                    "modified_answer": "薄荷茶",
                }
            ]
        )
    )

    def backend(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
        if schema is ExtractDraft:
            return {"items": []}
        assert schema is ChatDraft
        material = user.split("【对话】")[0]
        text = "我选择桂花茶。" if "桂花茶" in material else "我选择薄荷茶。"
        return {
            "reply": f"「{text}」",
            "citations": re.findall(r"\[([^\]\n]+)\]", material),
            "confidence": 0.8,
            "abstain": False,
        }

    settings = Settings(db_path=tmp_path / "never-created.db", target_name="虚构林沐")
    report = run_persona_evaluation(
        load_evalset(path),
        FakeLLM(backend),
        HashingEmbedder(),
        settings,
        (Judge(FakeLLM(grade), "low"),),
        FIXTURE / "persona.txt",
        repeats=2,
    )
    block = summarize(report)["update"]["quotes"]
    assert block["n_replies"] == 6 and block["replies_with_quotes"] == block["total"] == 4
    assert block["cited"] == 4 and block["elsewhere"] == block["unverified"] == 0
    assert block["unverified_rate"] == 0 and block["quotes_removed"] == 2
    assert summarize(report)["overall"]["quotes"] == block
    assert compare_reports(report, report)["categories"]["update"]["quotes"]["B"] == block
    assert not settings.db_path.exists()
