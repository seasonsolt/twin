from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError
from typer.testing import CliRunner

from twin.cli import app
from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.identity import BIOMETRIC_SCOPES, ConsentEvent, Decision, Identity, Scope
from twin.llm import FakeLLM
from twin.persona.chat import ITEMS_NS, index_persona
from twin.persona.dimensions import FACETS, requires_consent
from twin.persona.profile import ExtractDraft, build_profile, consented_facets
from twin.persona.questionnaire import submit_initial
from twin.persona.schema import ParsedSource
from twin.persona.sources import parse_questionnaire
from twin.persona.store import PersonaStore

QUESTIONNAIRE = """**33.【可跳过】爱好？**　*开放 · 9.1*

回答：周末做模型。

**36.【可跳过】家庭？**　*开放 · 9.3*

回答：
"""


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("TWIN_CONFIG", raising=False)
    monkeypatch.delenv("DTWIN_CONFIG", raising=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(target_name="测试本人", target_aliases=["测试别名"], db_path=tmp_path / "persona.db", max_workers=1)


def event(seq: int = 1, scope: str = "facet:9.1", decision: Decision = Decision.GRANT) -> ConsentEvent:
    return ConsentEvent(
        seq=seq, scope=scope, decision=decision, at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC), origin="cli"
    )


@pytest.mark.parametrize(
    "scope",
    [
        *[f"facet:{f.facet_id}" for f in FACETS if requires_consent(f.facet_id)],
        "egress:llm",
        "egress:embed",
        "egress:tts",
        "egress:asr",
        *sorted(BIOMETRIC_SCOPES),
    ],
)
def test_valid_scope(scope: str) -> None:
    assert TypeAdapter(Scope).validate_python(scope) == scope


@pytest.mark.parametrize(
    "scope", ["", "facet:1.1", "facet:99.1", "facet:9.01", "egress:other", "biometric:other", " facet:9.1"]
)
def test_invalid_scope_has_chinese_error(scope: str) -> None:
    with pytest.raises(ValueError, match="无效授权范围"):
        TypeAdapter(Scope).validate_python(scope)


@pytest.mark.parametrize("scope", sorted(BIOMETRIC_SCOPES))
def test_biometric_grants_are_never_valid(scope: str) -> None:
    with pytest.raises(ValueError, match="本版本禁止授权生物特征"):
        event(scope=scope)
    with pytest.raises(ValueError, match="本版本禁止授权生物特征"):
        Identity(name="测试", aliases=[], consents={scope: Decision.GRANT})
    assert event(scope=scope, decision=Decision.REVOKE).decision is Decision.REVOKE
    assert event(scope=scope, decision=Decision.DECLINE).decision is Decision.DECLINE


def test_event_defaults_utc_validation_and_frozen_contracts() -> None:
    original = event()
    assert original.note == ""
    assert ConsentEvent.model_validate_json(original.model_dump_json()) == original
    offset = dt.datetime(2026, 1, 1, 8, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    assert ConsentEvent.model_validate({**original.model_dump(), "at": offset}).at == original.at
    for update in ({"at": dt.datetime(2026, 1, 1)}, {"origin": "other"}, {"note": "x" * 201}, {"seq": 0}):
        with pytest.raises(ValueError):
            ConsentEvent.model_validate({**original.model_dump(), **update})
    assert ConsentEvent.model_validate({**original.model_dump(), "note": "x" * 200}).note == "x" * 200
    with pytest.raises(ValidationError, match="frozen"):
        original.note = "change"
    identity = Identity.from_parts("测试", [], [])
    with pytest.raises(ValidationError, match="frozen"):
        identity.name = "change"


def test_identity_folds_by_seq_not_time_or_input_order() -> None:
    identity = Identity.from_parts(
        "测试",
        ["别名"],
        [event(3, decision=Decision.DECLINE), event(1), event(2, decision=Decision.REVOKE), event(4, "egress:llm")],
    )
    assert identity.name == "测试" and identity.aliases == ["别名"]
    assert identity.consents == {"facet:9.1": Decision.DECLINE, "egress:llm": Decision.GRANT}
    assert not identity.granted("facet:9.1") and identity.granted("egress:llm")
    assert not identity.granted("egress:embed")
    assert Identity.from_parts("测试", [], [event()]).granted("facet:9.1")
    assert not Identity.from_parts("测试", [], [event(), event(2, decision=Decision.REVOKE)]).granted("facet:9.1")


def create_legacy_db(path: Path, sources: list[ParsedSource]) -> None:
    # An actual pre-ledger schema, not a new store whose events have been cleared.
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE p_sources (
                source_id TEXT PRIMARY KEY, kind TEXT NOT NULL, first_date TEXT, json TEXT NOT NULL);
            CREATE TABLE p_expressions (
                expression_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, idx INTEGER NOT NULL, date TEXT,
                is_target INTEGER NOT NULL, held_out INTEGER NOT NULL, json TEXT NOT NULL);
        """)
        for parsed in sources:
            source = parsed.source
            db.execute(
                "INSERT INTO p_sources VALUES (?, ?, ?, ?)",
                (
                    source.source_id,
                    source.kind.value,
                    source.first_date.isoformat() if source.first_date else None,
                    source.model_dump_json(),
                ),
            )
            for expression in parsed.expressions:
                db.execute(
                    "INSERT INTO p_expressions VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        expression.expression_id,
                        expression.source_id,
                        expression.idx,
                        expression.date.isoformat() if expression.date else None,
                        int(expression.is_target),
                        int(expression.held_out),
                        expression.model_dump_json(),
                    ),
                )


def test_open_legacy_db_adds_table_and_preserves_questionnaire_derivation(settings: Settings) -> None:
    answered = parse_questionnaire("legacy.md", QUESTIONNAIRE, settings)
    declined = parse_questionnaire("declined.md", QUESTIONNAIRE.replace("周末做模型。", ""), settings)
    create_legacy_db(settings.db_path, [answered, declined])
    with PersonaStore(settings.db_path) as store:
        assert store.consent_events() == []
        assert store.get_source(answered.source.source_id) == answered.source
        assert not any(f.startswith("9.") for f in consented_facets(store))  # legacy decline wins across sources
        assert all(f.facet_id in consented_facets(store) for f in FACETS if not requires_consent(f.facet_id))
        store.delete_source(declined.source.source_id)
        assert "9.1" in consented_facets(store) and "9.3" not in consented_facets(store)
        assert store.consent_events() == []  # opening/reading does not backfill or rewrite legacy decisions
        store.append_consent("facet:9.1", Decision.REVOKE, "cli")
    with PersonaStore(settings.db_path) as store:
        assert store.consent_events()[0].seq == 1
        assert "9.1" not in consented_facets(store)


def test_ledger_override_is_per_scope_and_keeps_legacy_fallback_for_other_facets(settings: Settings) -> None:
    parsed = parse_questionnaire("legacy.md", QUESTIONNAIRE.replace("回答：\n", "回答：虚构的家庭内容。\n"), settings)
    create_legacy_db(settings.db_path, [parsed])
    with PersonaStore(settings.db_path) as store:
        assert {"9.1", "9.3"} <= consented_facets(store)
        store.append_consent("facet:9.1", Decision.REVOKE, "cli")
        store.append_consent("egress:llm", Decision.DECLINE, "web")
        assert "9.1" not in consented_facets(store) and "9.3" in consented_facets(store)
        assert "9.2" not in consented_facets(store)


def test_ledger_is_persistent_append_only_and_independent_of_source_deletion(settings: Settings) -> None:
    with PersonaStore(settings.db_path) as store:
        parsed = parse_questionnaire("q.md", QUESTIONNAIRE, settings)
        store.put_source(parsed)
        first = store.consent_events()
        grant = store.append_consent("egress:llm", Decision.GRANT, "web", "测试备注")
        revoke = store.append_consent("egress:llm", Decision.REVOKE, "cli")
        assert revoke.seq == grant.seq + 1 and grant.at.tzinfo is dt.UTC
        assert store.consent_events() == [*first, grant, revoke]
        with pytest.raises(ValueError):
            store.append_consent("biometric:face", Decision.GRANT, "cli")
        with pytest.raises(ValueError):
            store.append_consent("facet:1.1", Decision.GRANT, "cli")
        with pytest.raises(ValueError):
            store.append_consent("egress:tts", Decision.GRANT, "cli", "x" * 201)
        store.delete_source(parsed.source.source_id)
        assert store.consent_events() == [*first, grant, revoke]
    with PersonaStore(settings.db_path) as store:
        assert store.consent_events() == [*first, grant, revoke]
        assert "9.1" in consented_facets(store)  # recorded grant survives deleting its source


def test_questionnaire_submission_and_import_record_answers_and_skips(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        first = submit_initial(store, settings, {"q33": "周末做模型。"})
        events = store.consent_events()
        assert len(events) == 5 and all(e.origin == "questionnaire" and not e.note for e in events)
        assert {e.scope: e.decision for e in events} == {
            "facet:9.1": Decision.GRANT,
            "facet:9.2": Decision.DECLINE,
            "facet:9.3": Decision.DECLINE,
            "facet:9.4": Decision.DECLINE,
            "facet:9.5": Decision.DECLINE,
        }
        assert first.source.declined_facets == ["9.2", "9.3", "9.4", "9.5"]
        second = submit_initial(store, settings, {"q01": "负责测试。", "q36": "愿意公开的虚构家庭信息。"})
        assert store.get_source(first.source.source_id) is None
        assert len(store.consent_events()) == 10 and store.consent_events()[:5] == events
        assert "9.1" not in consented_facets(store) and "9.3" in consented_facets(store)
        assert second.source.declined_facets == ["9.1", "9.2", "9.4", "9.5"]
        store.put_source(parse_questionnaire("file.md", QUESTIONNAIRE, settings))
        assert "9.1" in consented_facets(store) and "9.3" not in consented_facets(store)
        store.append_consent("facet:9.1", Decision.REVOKE, "cli")
        assert "9.1" not in consented_facets(store)
        store.append_consent("facet:9.1", Decision.GRANT, "cli")
        assert "9.1" in consented_facets(store)
        store.append_consent("facet:9.1", Decision.DECLINE, "web")
        assert "9.1" not in consented_facets(store)


def extract_model(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    assert schema is ExtractDraft
    return {"items": [{"facet_id": "9.1", "statement": "他喜欢做模型", "quotes": [{"n": 1, "quote": "周末做模型"}]}]}


def test_revocation_next_build_removes_items_via_empty_merge_key(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        store.put_source(parse_questionnaire("q.md", QUESTIONNAIRE, settings))
        llm = FakeLLM(extract_model)
        assert build_profile(store, llm, settings).failures == []
        assert len(store.list_items("9.1")) == 1
        granted_key = store.get_meta("merge:9.1")
        store.append_consent("facet:9.1", Decision.REVOKE, "cli")
        report = build_profile(store, llm, settings)
        assert report.failures == [] and store.list_items("9.1", raw=True) == []
        assert store.get_meta("merge:9.1") != granted_key
        assert build_profile(store, llm, settings).facets_merged == 0


def test_revocation_index_persona_removes_revoked_item_vectors(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        store.put_source(parse_questionnaire("q.md", QUESTIONNAIRE, settings))
        llm = FakeLLM(extract_model)
        build_profile(store, llm, settings)
        revoked_ids = {i.item_id for i in store.list_items("9.1")}
        embedder = HashingEmbedder(dim=64)
        index_persona(store, embedder, settings)
        assert revoked_ids and revoked_ids <= set(store.get_vectors(ITEMS_NS)[0])
        store.append_consent("facet:9.1", Decision.REVOKE, "cli")
        build_profile(store, llm, settings)
        index_persona(store, embedder, settings)
        assert revoked_ids.isdisjoint(store.get_vectors(ITEMS_NS)[0])
        assert revoked_ids.isdisjoint(store.vector_shas(ITEMS_NS))


@pytest.fixture
def config(settings: Settings, tmp_path: Path) -> Path:
    path = tmp_path / "identity.toml"
    path.write_text(
        f'target_name = "测试本人"\ntarget_aliases = ["测试别名"]\ndb_path = "{settings.db_path}"\n', encoding="utf-8"
    )
    return path


def test_cli_show_legacy_fallback_without_personal_text(config: Path, settings: Settings) -> None:
    parsed = parse_questionnaire("legacy.md", QUESTIONNAIRE, settings)
    create_legacy_db(settings.db_path, [parsed])
    result = CliRunner().invoke(app, ["--config", str(config), "identity", "show"])
    assert result.exit_code == 0, result.exception
    assert "名字：测试本人" in result.stdout and "别名：测试别名" in result.stdout
    assert "facet:9.1 | 未记录（按问卷推导：已授权）" in result.stdout
    assert "facet:9.3 | 未记录（按问卷推导：未授权）" in result.stdout
    assert "周末做模型" not in result.output


def test_cli_grant_revoke_show_and_safe_validation(config: Path, settings: Settings) -> None:
    runner = CliRunner()
    prefix = ["--config", str(config), "identity"]
    for command in ("grant", "revoke"):
        result = runner.invoke(app, [*prefix, command, "facet:9.1", "--note", "不应输出的备注"])
        assert result.exit_code == 0, result.exception
        assert "twin persona build" in result.stdout and "不应输出的备注" not in result.output
    assert runner.invoke(app, [*prefix, "grant", "egress:llm"]).exit_code == 0
    assert runner.invoke(app, [*prefix, "revoke", "biometric:face"]).exit_code == 0
    result = runner.invoke(app, [*prefix, "show"])
    assert result.exit_code == 0 and "已撤回（revoke）" in result.stdout
    assert "egress:llm | 已授权（grant）" in result.stdout and "biometric:face" in result.stdout
    assert "cli" in result.stdout and "+00:00" in result.stdout and "不应输出的备注" not in result.output
    for scope, message in (
        ("facet:1.1", "无效授权范围"),
        ("biometric:voice_clone", "本版本禁止授权生物特征"),
        ("biometric:face", "本版本禁止授权生物特征"),
    ):
        result = runner.invoke(app, [*prefix, "grant", scope])
        assert result.exit_code != 0 and message in result.stderr
    result = runner.invoke(app, [*prefix, "grant", "egress:tts", "--note", "私密" * 101])
    assert result.exit_code != 0 and "私密" not in result.output
    with PersonaStore(settings.db_path) as store:
        assert len(store.consent_events()) == 4
        assert all(e.origin == "cli" for e in store.consent_events())


def test_cli_questionnaire_import_also_records_declines(config: Path, settings: Settings, tmp_path: Path) -> None:
    questionnaire = tmp_path / "q.md"
    questionnaire.write_text(QUESTIONNAIRE, encoding="utf-8")
    result = CliRunner().invoke(
        app, ["--config", str(config), "persona", "import", str(questionnaire), "--kind", "questionnaire"]
    )
    assert result.exit_code == 0, result.exception
    with PersonaStore(settings.db_path) as store:
        assert [(e.scope, e.decision, e.origin) for e in store.consent_events()] == [
            ("facet:9.1", Decision.GRANT, "questionnaire"),
            ("facet:9.3", Decision.DECLINE, "questionnaire"),
        ]
