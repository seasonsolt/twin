from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError
from typer.testing import CliRunner

from twin.cli import app
from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.identity import Identity
from twin.llm import FakeLLM
from twin.persona.chat import ITEMS_NS, index_persona
from twin.persona.dimensions import FACETS, requires_consent
from twin.persona.profile import ExtractDraft, build_profile, consented_facets
from twin.persona.questionnaire import submit_initial
from twin.persona.sources import parse_questionnaire
from twin.persona.store import PersonaStore

QUESTIONNAIRE = """**33.【可跳过】爱好？**　*开放 · 9.1*

回答：周末做模型。

**36.【可跳过】家庭？**　*开放 · 9.3*

回答：
"""


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(target_name="测试本人", target_aliases=["测试别名"], db_path=tmp_path / "persona.db", max_workers=1)


def test_identity_shape() -> None:
    identity = Identity(name="测试", aliases=["别名"], voice="default", avatar="ink")
    assert identity.model_dump() == {
        "name": "测试",
        "aliases": ["别名"],
        "voice": "default",
        "avatar": "ink",
        "about": "",
        "name_source": "config",
    }
    assert Identity.model_validate_json(identity.model_dump_json()) == identity
    assert Identity(name="测试", aliases=[]).voice is None
    with pytest.raises(ValidationError, match="frozen"):
        identity.name = "change"


def test_questionnaire_derivation_answered_declined_and_not_answered(settings: Settings) -> None:
    answered = parse_questionnaire("q.md", QUESTIONNAIRE, settings)
    declined = parse_questionnaire("declined.md", QUESTIONNAIRE.replace("周末做模型。", ""), settings)
    with PersonaStore(settings.db_path) as store:
        assert all(f.facet_id in consented_facets(store) for f in FACETS if not requires_consent(f.facet_id))
        assert not any(f.startswith("9.") for f in consented_facets(store))
        store.put_source(answered)
        assert "9.1" in consented_facets(store)
        assert "9.2" not in consented_facets(store)  # not answered
        assert "9.3" not in consented_facets(store)  # declined
        store.put_source(declined)
        assert "9.1" not in consented_facets(store)  # decline wins across sources
        store.delete_source(declined.source.source_id)
        assert "9.1" in consented_facets(store)
    with PersonaStore(settings.db_path) as store:
        assert "9.1" in consented_facets(store)
        store.delete_source(answered.source.source_id)
        assert "9.1" not in consented_facets(store)


def test_existing_consent_table_is_untouched_and_never_read(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Deliberately incompatible ledger schema: even selecting its former columns would fail.
    with sqlite3.connect(settings.db_path) as db:
        db.execute("CREATE TABLE p_consent (obsolete TEXT)")
        db.execute("INSERT INTO p_consent VALUES ('legacy')")
    statements: list[str] = []
    connect = sqlite3.connect

    def traced_connect(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        db = connect(*args, **kwargs)
        db.set_trace_callback(statements.append)
        return db

    monkeypatch.setattr(sqlite3, "connect", traced_connect)
    with PersonaStore(settings.db_path) as store:
        parsed = parse_questionnaire("q.md", QUESTIONNAIRE, settings)
        store.put_source(parsed)
        assert "9.1" in consented_facets(store)
        assert store.get_meta("sources_changed_at")
    assert all("p_consent" not in statement.lower() for statement in statements)
    with connect(settings.db_path) as db:
        assert db.execute("SELECT * FROM p_consent").fetchall() == [("legacy",)]


def test_new_store_does_not_create_consent_table(settings: Settings) -> None:
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_questionnaire("q.md", QUESTIONNAIRE, settings))
    with sqlite3.connect(settings.db_path) as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name = 'p_consent'").fetchall() == []


def test_questionnaire_submission_replaces_derivation(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        first = submit_initial(store, settings, {"q19": "周末做模型。"})
        assert {f for f in first.source.declined_facets if f.startswith("9.")} == {"9.2", "9.3", "9.4"}
        assert "9.1" in consented_facets(store)
        second = submit_initial(store, settings, {"q01": "负责测试。", "q20": "虚构家庭信息。"})
        assert store.get_source(first.source.source_id) is None
        assert "9.1" not in consented_facets(store) and "9.3" in consented_facets(store)
        assert {f for f in second.source.declined_facets if f.startswith("9.")} == {"9.1", "9.5"}


def extract_model(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    assert schema is ExtractDraft
    return {"items": [{"facet_id": "9.1", "statement": "他喜欢做模型", "quotes": [{"n": 1, "quote": "周末做模型"}]}]}


def test_declining_questionnaire_next_build_removes_items_and_vectors(settings: Settings) -> None:
    with PersonaStore(":memory:") as store:
        parsed = parse_questionnaire("q.md", QUESTIONNAIRE, settings)
        store.put_source(parsed)
        llm = FakeLLM(extract_model)
        assert build_profile(store, llm, settings).failures == []
        ids = {i.item_id for i in store.list_items("9.1")}
        embedder = HashingEmbedder(dim=64)
        index_persona(store, embedder, settings)
        assert ids and ids <= set(store.get_vectors(ITEMS_NS)[0])
        old_key = store.get_meta("merge:9.1")
        store.put_source(parse_questionnaire("declined.md", QUESTIONNAIRE.replace("周末做模型。", ""), settings))
        report = build_profile(store, llm, settings)
        assert report.failures == [] and store.list_items("9.1", raw=True) == []
        assert store.get_meta("merge:9.1") != old_key
        index_persona(store, embedder, settings)
        assert ids.isdisjoint(store.get_vectors(ITEMS_NS)[0])
        assert ids.isdisjoint(store.vector_shas(ITEMS_NS))
        assert build_profile(store, llm, settings).facets_merged == 0


def test_cli_show_is_read_only(settings: Settings, tmp_path: Path) -> None:
    config = tmp_path / "identity.toml"
    config.write_text(
        f'target_name = "测试本人"\ntarget_aliases = ["测试别名"]\ndb_path = "{settings.db_path}"\n', encoding="utf-8"
    )
    runner = CliRunner()
    prefix = ["--config", str(config), "identity"]
    result = runner.invoke(app, [*prefix, "show"])
    assert result.exit_code == 0, result.exception
    assert "名字：测试本人" in result.stdout and "别名：测试别名" in result.stdout
    assert "音色：default" in result.stdout and "形象：default" in result.stdout
    assert "声明/推断" in result.stdout and "最新决定" not in result.stdout
    assert not settings.db_path.exists()
    for command in ("grant", "revoke"):
        assert runner.invoke(app, [*prefix, command, "egress:llm"]).exit_code != 0
