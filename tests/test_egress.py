"""Offline permission tests using invented endpoints, replies and temporary ledgers."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from twin import cli
from twin.config import (
    ASRSettings,
    BackendSettings,
    EmbedSettings,
    LLMSettings,
    Settings,
    TTSSettings,
    egress_of,
)
from twin.egress import EgressDenied, egress_status, require_configured_egress, require_egress
from twin.embed import HashingEmbedder
from twin.identity import Decision, Identity
from twin.llm import FakeLLM
from twin.media.check import DEFAULT_SENTENCES
from twin.media.schema import ASRCapabilities, Transcription, TranscriptionRequest
from twin.media.tts import SilentSynthesizer
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.backends import Backends

SECTIONS = [LLMSettings, EmbedSettings, TTSSettings, ASRSettings]
EXTERNAL_URL = "https://invented-user:invented-password@backend.invalid/v1/private?key=invented-query#secret"
HEADERS = {"X-Twin": "1"}
REPLY = {
    "reply": "虚构回答：先验证。",
    "citations": [],
    "confidence": 0.5,
    "abstain": False,
    "abstain_reason": "",
    "retrieved_ids": [],
}
BODY = {"kind": "chat_reply", "answer": REPLY}
FIXTURE = Path(__file__).parent / "fixtures" / "personal_eval"


def fake_llm() -> FakeLLM:
    return FakeLLM(lambda *_: {})


@pytest.fixture(autouse=True)
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "TWIN_CONFIG",
        "DTWIN_CONFIG",
        "OPENAI_BASE_URL",
        "ANTHROPIC_BASE_URL",
        "TWIN_LLM_KEY",
        "TWIN_EMBED_KEY",
        "TWIN_TTS_KEY",
        "TWIN_ASR_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("section_type", SECTIONS)
@pytest.mark.parametrize(
    ("url", "external", "host"),
    [
        ("http://localhost:8000/v1", False, "localhost"),
        ("http://127.0.0.1/v1", False, "127.0.0.1"),
        ("http://127.42.1.9/v1", False, "127.42.1.9"),
        ("http://[::1]:8000/v1", False, "::1"),
        ("http://192.168.1.5/v1", True, "192.168.1.5"),
        ("http://10.0.0.1/v1", True, "10.0.0.1"),
        ("http://[fd00::1]/v1", True, "fd00::1"),
        ("https://backend.invalid/v1", True, "backend.invalid"),
        (EXTERNAL_URL, True, "backend.invalid"),
        (None, True, None),
        ("not-a-url?key=secret", True, None),
        ("http://[invalid", True, None),
    ],
)
def test_openai_classification(section_type: Any, url: str | None, external: bool, host: str | None) -> None:
    section = section_type(provider="openai_compat", base_url=url)
    info = egress_of(section)
    assert info.external is external and info.host == host and not info.declared
    if not external:
        assert info.reason == "本机地址，未声明是否转发"
    assert all(value not in repr(info) for value in ("invented-password", "invented-query", "/private"))
    with pytest.raises(FrozenInstanceError):
        info.external = False  # type: ignore[misc]


@pytest.mark.parametrize(
    ("section", "kind", "external"),
    [
        (LLMSettings(provider="anthropic"), "llm", True),
        (LLMSettings(provider="claude_cli"), "llm", True),
        (EmbedSettings(), "embed", False),
        (TTSSettings(), "tts", False),
        (TTSSettings(provider="cloudflare", base_url="http://localhost/relay"), "tts", True),
        (ASRSettings(provider="cloudflare", base_url="http://localhost/relay"), "asr", True),
    ],
)
def test_provider_rules_and_explicit_override(section: BackendSettings, kind: str, external: bool) -> None:
    info = egress_of(section)
    assert info.kind == kind and info.external is external and not info.declared
    for declaration in ("local", "external"):
        declared = section.model_copy(update={"egress": declaration})
        info = egress_of(declared)
        assert info.external is (declaration == "external") and info.declared


@pytest.mark.parametrize("section_type", SECTIONS)
def test_env_matches_factory_resolution(section_type: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9000/v1?key=hidden")
    section = section_type(provider="openai_compat")
    info = egress_of(section)
    if section_type in (LLMSettings, EmbedSettings):
        assert info.host == "localhost" and not info.external
    else:
        assert info.host is None and info.external  # Speech factories require configured base_url.
    section.base_url = EXTERNAL_URL
    assert egress_of(section).host == "backend.invalid" and egress_of(section).external


def test_anthropic_env_host_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    assert egress_of(LLMSettings(provider="anthropic")).host == "api.anthropic.com"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", EXTERNAL_URL)
    info = egress_of(LLMSettings(provider="anthropic", base_url="http://localhost"))
    assert info.host == "backend.invalid" and info.external


@pytest.mark.parametrize("section_type", SECTIONS)
def test_latest_ledger_decision_and_scope_isolation(section_type: Any, tmp_path: Path) -> None:
    section = section_type(provider="openai_compat", base_url=EXTERNAL_URL)
    kind = egress_of(section).kind
    with PersonaStore(tmp_path / "ledger.db") as store:
        store.append_consent("facet:9.1", Decision.GRANT, "cli")
        other_kind = "embed" if kind == "llm" else "llm"
        store.append_consent(f"egress:{other_kind}", Decision.GRANT, "cli")
        for decision in (None, Decision.GRANT, Decision.REVOKE, Decision.GRANT, Decision.DECLINE):
            if decision is not None:
                store.append_consent(f"egress:{kind}", decision, "cli")
            identity = Identity.from_parts("虚构本人", [], store.consent_events())
            for source in (store, identity):
                if decision is Decision.GRANT:
                    require_egress(section, kind, source)
                else:
                    with pytest.raises(EgressDenied) as error:
                        require_egress(section, kind, source)
                    assert f"twin identity grant egress:{kind}" in str(error.value)
                    assert "backend.invalid" in str(error.value)
                    assert "invented-password" not in str(error.value)
        local = section.model_copy(update={"base_url": "http://localhost/v1"})
        require_egress(local, kind, store)
        relay = local.model_copy(update={"egress": "external"})
        with pytest.raises(EgressDenied):
            require_egress(relay, kind, store)


def test_local_does_not_open_store_and_kind_mismatch_is_rejected(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "absent.db")
    for section in (settings.embed, settings.tts, LLMSettings(base_url="http://localhost/v1")):
        require_configured_egress(settings, section)
    assert not settings.db_path.exists()
    with pytest.raises(ValueError, match="类型不匹配"):
        require_egress(settings.embed, "llm", Identity.from_parts("虚构", [], []))


@pytest.mark.parametrize("kind", ["llm", "embed"])
def test_web_default_refuses_before_factory_and_other_routes_work(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(db_path=tmp_path / "web.db", llm=LLMSettings(base_url="http://localhost/v1"))
    section = (
        LLMSettings(base_url=EXTERNAL_URL)
        if kind == "llm"
        else EmbedSettings(provider="openai_compat", base_url=EXTERNAL_URL)
    )
    setattr(settings, kind, section)
    calls: list[str] = []

    def factory(_: Any) -> Any:
        calls.append(kind)
        raise AssertionError("refused backend must never construct")

    monkeypatch.setattr(f"twin.web.backends.make_{'llm' if kind == 'llm' else 'embedder'}", factory)
    injected = {"embedder_factory": HashingEmbedder} if kind == "llm" else {"llm_factory": fake_llm}
    web = create_app(settings, **injected)
    assert not calls and not settings.db_path.exists()
    with TestClient(web, base_url="http://localhost") as client:
        assert client.get("/").status_code == 200
        for path, body in (
            ("/api/persona/build", {}),
            ("/api/persona/chat", {"messages": [{"role": "user", "content": "虚构问题"}]}),
        ):
            response = client.post(path, json=body, headers=HEADERS)
            assert response.status_code == 403
            assert list(response.json()) == ["detail"]
            assert f"twin identity grant egress:{kind}" in response.json()["detail"]
            assert "invented-password" not in response.text
        status = client.get("/api/status")
        assert status.status_code == 200
        row = next(row for row in status.json()["egress"] if row["kind"] == kind)
        assert row == dict(
            kind=kind, provider="openai_compat", host="backend.invalid", external=True, declared=False, granted=False
        )
        assert client.get("/api/persona/sources").status_code == 200
    assert not calls


def test_web_default_tts_refuses_and_injected_factories_bypass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "web.db", tts=TTSSettings(provider="cloudflare", base_url=EXTERNAL_URL))
    calls: list[str] = []

    def factory(_: Any) -> SilentSynthesizer:
        calls.append("tts")
        return SilentSynthesizer()

    monkeypatch.setattr("twin.web.media.make_synthesizer", factory)
    web = create_app(settings)
    with TestClient(web, base_url="http://localhost") as client:
        assert client.get("/").status_code == 200 and not calls
        assert client.post("/api/media/script", json=BODY, headers=HEADERS).status_code == 200
        cap = client.get("/api/media/capabilities").json()
        assert cap["available"] is False and "egress:tts" in cap["error"]
        response = client.post("/api/media/audio", json=BODY, headers=HEADERS)
        assert response.status_code == 403 and "egress:tts" in response.json()["detail"]
    assert not calls
    with TestClient(
        create_app(
            settings, llm_factory=fake_llm, embedder_factory=HashingEmbedder, synthesizer_factory=SilentSynthesizer
        ),
        base_url="http://localhost",
    ) as client:
        assert client.get("/api/status").json()["llm"]["name"] == "fake"
        assert client.post("/api/media/audio", json=BODY, headers=HEADERS).status_code == 200
    assert not calls


@pytest.mark.parametrize("kind", ["llm", "embed", "judge"])
def test_lazy_grants_and_revocation_require_new_construction(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        db_path=tmp_path / "web.db",
        llm=LLMSettings(base_url=EXTERNAL_URL),
        embed=EmbedSettings(provider="openai_compat", base_url=EXTERNAL_URL),
        judges=[LLMSettings(base_url=EXTERNAL_URL)],
    )
    calls: list[str] = []

    def llm_factory(*_: Any) -> FakeLLM:
        calls.append("llm")
        return fake_llm()

    def embed_factory(*_: Any) -> HashingEmbedder:
        calls.append("embed")
        return HashingEmbedder()

    monkeypatch.setattr("twin.web.backends.make_llm", llm_factory)
    monkeypatch.setattr("twin.web.backends.make_embedder", embed_factory)
    backends = Backends(settings, None, None)
    method = "judges" if kind == "judge" else ("embedder" if kind == "embed" else "llm")
    scope = f"egress:{'llm' if kind == 'judge' else kind}"
    with pytest.raises(EgressDenied):
        getattr(backends, method)()
    assert not calls
    with PersonaStore(settings.db_path) as store:
        store.append_consent(scope, Decision.GRANT, "cli")
    cached = getattr(backends, method)()
    assert len(calls) == 1
    with PersonaStore(settings.db_path) as store:
        store.append_consent(scope, Decision.REVOKE, "cli")
    assert getattr(backends, method)() is cached and len(calls) == 1
    # Injecting the main factory does not bypass checks on configured judges.
    restarted = Backends(settings, fake_llm if kind == "judge" else None, None)
    with pytest.raises(EgressDenied):
        getattr(restarted, method)()
    assert len(calls) == 1


def test_default_tts_grant_is_lazy_and_cached_until_restart(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "web.db", tts=TTSSettings(provider="cloudflare", base_url=EXTERNAL_URL))
    calls: list[str] = []

    def factory(_: Any) -> SilentSynthesizer:
        calls.append("tts")
        return SilentSynthesizer()

    monkeypatch.setattr("twin.web.media.make_synthesizer", factory)
    web = create_app(settings)
    with PersonaStore(settings.db_path) as store:
        store.append_consent("egress:tts", Decision.GRANT, "cli")
    with TestClient(web, base_url="http://localhost") as client:
        assert not calls
        assert client.post("/api/media/audio", json=BODY, headers=HEADERS).status_code == 200
        with PersonaStore(settings.db_path) as store:
            store.append_consent("egress:tts", Decision.REVOKE, "cli")
        assert client.post("/api/media/audio", json=BODY, headers=HEADERS).status_code == 200
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.post("/api/media/audio", json=BODY, headers=HEADERS).status_code == 403
    assert calls == ["tts"]


@pytest.mark.parametrize("kind", ["llm", "embed"])
@pytest.mark.parametrize("command", ["build", "chat"])
def test_cli_persona_checks_even_monkeypatched_factories(
    kind: str, command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "twin.toml"
    # Main local model allows the embed boundary to be reached without a separate llm grant.
    config.write_text(
        'db_path = "ledger.db"\n[llm]\nbase_url = "'
        + (EXTERNAL_URL if kind == "llm" else "http://localhost/v1")
        + '"\n[embed]\nprovider = "openai_compat"\nbase_url = "'
        + EXTERNAL_URL
        + '"\n'
    )
    calls: list[str] = []
    monkeypatch.setattr(cli, "make_llm", lambda _: calls.append("llm") or fake_llm())
    monkeypatch.setattr(cli, "make_embedder", lambda _: calls.append("embed") or HashingEmbedder())
    args = ["--config", str(config), "persona", command]
    if command == "chat":
        args.append("虚构问题")
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 1 and f"twin identity grant egress:{kind}" in result.output
    assert kind not in calls and "invented-password" not in result.output


@pytest.mark.parametrize("blocked", ["llm", "embed", "judge-1", "judge-2"])
def test_cli_eval_preflights_each_backend_before_any_factory(
    blocked: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "twin.toml"
    local = "http://localhost/v1"
    config.write_text(
        'db_path = "ledger.db"\n[llm]\nbase_url = "'
        + (EXTERNAL_URL if blocked == "llm" else local)
        + '"\n[embed]\nprovider = "openai_compat"\nbase_url = "'
        + (EXTERNAL_URL if blocked == "embed" else local)
        + '"\n'
        + "".join(
            '[[judges]]\nbase_url = "' + (EXTERNAL_URL if blocked == f"judge-{i}" else local) + '"\n' for i in (1, 2)
        )
    )
    calls: list[str] = []
    monkeypatch.setattr(cli, "make_llm", lambda _: calls.append("llm") or fake_llm())
    monkeypatch.setattr(cli, "make_embedder", lambda _: calls.append("embed") or HashingEmbedder())
    monkeypatch.setattr("twin.evals.personal.make_panel", lambda _: calls.append("panel"))
    result = CliRunner().invoke(
        cli.app,
        [
            "--config",
            str(config),
            "eval",
            "--evalset",
            str(FIXTURE / "evalset.json"),
            "--persona-ref",
            str(FIXTURE / "persona.txt"),
            "--out",
            str(tmp_path / "report"),
        ],
    )
    kind = "embed" if blocked == "embed" else "llm"
    assert result.exit_code == 1 and f"egress:{kind}" in result.output
    assert "backend.invalid" in result.output and "invented-password" not in result.output
    assert not calls


def test_cli_speak_refuses_before_default_factory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('db_path = "ledger.db"\n[tts]\nprovider = "cloudflare"\nbase_url = "' + EXTERNAL_URL + '"\n')
    source = tmp_path / "reply.json"
    source.write_text(json.dumps(REPLY))
    calls: list[str] = []
    monkeypatch.setattr("twin.config.make_synthesizer", lambda _: calls.append("tts"))
    result = CliRunner().invoke(
        cli.app, ["--config", str(config), "media", "speak", str(source), "--out", str(tmp_path / "audio")]
    )
    assert result.exit_code == 1 and "twin identity grant egress:tts" in result.output
    assert not calls and not (tmp_path / "audio").exists()


def test_cli_speak_grant_and_next_process_revoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "twin.toml"
    config.write_text('db_path = "ledger.db"\n[tts]\nprovider = "cloudflare"\nbase_url = "' + EXTERNAL_URL + '"\n')
    source = tmp_path / "reply.json"
    source.write_text(json.dumps(REPLY))
    calls: list[str] = []

    def factory(_: Any) -> SilentSynthesizer:
        calls.append("tts")
        synth = SilentSynthesizer()
        synth.name = "invented-speech"
        return synth

    monkeypatch.setattr("twin.config.make_synthesizer", factory)
    runner = CliRunner()
    prefix = ["--config", str(config)]
    assert runner.invoke(cli.app, [*prefix, "identity", "grant", "egress:tts"]).exit_code == 0
    args = [*prefix, "media", "speak", str(source), "--out", str(tmp_path / "audio")]
    granted = runner.invoke(cli.app, args)
    assert granted.exit_code == 0, granted.output
    assert REPLY["reply"] not in granted.output
    assert runner.invoke(cli.app, [*prefix, "identity", "revoke", "egress:tts"]).exit_code == 0
    refused = runner.invoke(cli.app, args)
    assert refused.exit_code == 1 and "egress:tts" in refused.output
    assert calls == ["tts"]


def test_cli_media_check_fixed_synthetic_sentences_need_no_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(
        'db_path = "ledger.db"\n[tts]\nprovider = "cloudflare"\nbase_url = "'
        + EXTERNAL_URL
        + '"\n[asr]\nprovider = "cloudflare"\nbase_url = "'
        + EXTERNAL_URL
        + '"\n'
    )
    received: list[TranscriptionRequest] = []
    texts = iter(DEFAULT_SENTENCES)

    class Recognizer:
        name = "invented-asr"
        identity = "invented-asr-fingerprint"
        capabilities = ASRCapabilities()

        def transcribe(self, request: TranscriptionRequest) -> Transcription:
            received.append(request)
            return Transcription(text=next(texts))

    monkeypatch.setattr("twin.config.make_synthesizer", lambda _: SilentSynthesizer())
    monkeypatch.setattr("twin.config.make_recognizer", lambda _: Recognizer())
    result = CliRunner().invoke(cli.app, ["--config", str(config), "media", "check", "--out", str(tmp_path / "report")])
    assert result.exit_code == 0, result.output
    assert len(received) == len(DEFAULT_SENTENCES)
    assert not (tmp_path / "ledger.db").exists()


def test_identity_show_and_status_include_every_backend_and_judges(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(
        'db_path = "ledger.db"\n[llm]\nbase_url = "'
        + EXTERNAL_URL
        + '"\negress = "external"\n[[judges]]\nprovider = "claude_cli"\n'
        + '[[judges]]\nbase_url = "http://localhost/v1"\n'
    )
    runner = CliRunner()
    assert runner.invoke(cli.app, ["--config", str(config), "identity", "grant", "egress:llm"]).exit_code == 0
    result = runner.invoke(cli.app, ["--config", str(config), "identity", "show"])
    assert result.exit_code == 0
    assert "出境" in result.output and "llm（评委 1）" in result.output and "llm（评委 2）" in result.output
    assert "llm | openai_compat | backend.invalid | 外部 | 已声明 | 已授权" in result.output
    assert "embed | hashing | 未知 | 本机 | 推断 | 无需" in result.output
    assert "tts | silent | 未知 | 本机 | 推断 | 无需" in result.output
    assert "llm（评委 2） | openai_compat | localhost | 本机 | 推断 | 无需" in result.output
    assert "asr | openai_compat | 未知 | 外部 | 推断 | 未授权" in result.output
    assert "invented-password" not in result.output
    settings = Settings.model_validate({"db_path": tmp_path / "ledger.db", "judges": [{}, {}]})
    with PersonaStore(settings.db_path) as store:
        rows = egress_status(settings, store)
    assert len(rows) == 6 and rows[-1]["granted"] is True
    with TestClient(
        create_app(settings, llm_factory=fake_llm, embedder_factory=HashingEmbedder), base_url="http://localhost"
    ) as client:
        assert client.get("/api/status").json()["egress"] == rows
