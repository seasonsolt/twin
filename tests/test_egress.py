"""Offline classification and configured-backend tests using invented data."""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from twin import cli
from twin.config import ASRSettings, BackendSettings, EmbedSettings, LLMSettings, Settings, TTSSettings, egress_of
from twin.egress import egress_status
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.check import DEFAULT_SENTENCES
from twin.media.schema import ASRCapabilities, Transcription, TranscriptionRequest
from twin.media.tts import SilentSynthesizer
from twin.persona.items import PersonaItem
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


def fake_llm() -> FakeLLM:
    return FakeLLM(lambda *_: REPLY)


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
    info = egress_of(section_type(provider="openai_compat", base_url=url))
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
        info = egress_of(section.model_copy(update={"egress": declaration}))
        assert info.external is (declaration == "external") and info.declared


@pytest.mark.parametrize("section_type", SECTIONS)
def test_env_matches_factory_resolution(section_type: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "http://localhost:9000/v1?key=hidden")
    section = section_type(provider="openai_compat")
    info = egress_of(section)
    if section_type in (LLMSettings, EmbedSettings):
        assert info.host == "localhost" and not info.external
    else:
        assert info.host is None and info.external
    section.base_url = EXTERNAL_URL
    assert egress_of(section).host == "backend.invalid" and egress_of(section).external


def test_anthropic_env_host_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    assert egress_of(LLMSettings(provider="anthropic")).host == "api.anthropic.com"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", EXTERNAL_URL)
    info = egress_of(LLMSettings(provider="anthropic", base_url="http://localhost"))
    assert info.host == "backend.invalid" and info.external


@pytest.mark.parametrize("kind", ["llm", "embed", "judge"])
def test_external_web_backends_construct_normally_and_cache(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(
        db_path=tmp_path / "web.db",
        llm=LLMSettings(base_url=EXTERNAL_URL),
        embed=EmbedSettings(provider="openai_compat", base_url=EXTERNAL_URL),
        judges=[LLMSettings(base_url=EXTERNAL_URL)],
    )
    calls: list[str] = []
    monkeypatch.setattr("twin.web.backends.make_llm", lambda *_: calls.append("llm") or fake_llm())
    monkeypatch.setattr("twin.web.backends.make_embedder", lambda *_: calls.append("embed") or HashingEmbedder())
    backends = Backends(settings, None, None)
    method = "judges" if kind == "judge" else "embedder" if kind == "embed" else "llm"
    assert not calls
    cached = getattr(backends, method)()
    assert getattr(backends, method)() is cached and len(calls) == 1
    assert not settings.db_path.exists()


def test_external_web_chat_and_status_without_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(
        db_path=tmp_path / "web.db",
        llm=LLMSettings(base_url=EXTERNAL_URL),
        embed=EmbedSettings(provider="openai_compat", base_url=EXTERNAL_URL),
    )
    monkeypatch.setattr("twin.web.backends.make_llm", lambda *_: fake_llm())
    monkeypatch.setattr("twin.web.backends.make_embedder", lambda *_: HashingEmbedder())
    with PersonaStore(settings.db_path) as store:
        store.replace_facet_items(
            "2.1", [PersonaItem(item_id="invented", facet_id="2.1", statement="合成测试条目", evidence=[])]
        )
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        response = client.post(
            "/api/persona/chat", json={"messages": [{"role": "user", "content": "虚构问题"}]}, headers=HEADERS
        )
        assert response.status_code == 202
        assert client.get("/api/status").json()["egress"] == egress_status(settings)


def test_external_tts_is_lazy_and_cached_without_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "web.db", tts=TTSSettings(provider="cloudflare", base_url=EXTERNAL_URL))
    calls: list[str] = []
    monkeypatch.setattr("twin.web.media.make_synthesizer", lambda _: calls.append("tts") or SilentSynthesizer())
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert not calls
        assert client.get("/api/media/capabilities").status_code == 200
        for _ in range(2):
            assert client.post("/api/media/audio", json=BODY, headers=HEADERS).status_code == 200
    assert calls == ["tts"]


@pytest.mark.parametrize("command", ["build", "chat"])
def test_external_cli_persona_backends_without_grant(
    command: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(
        f'db_path = "persona.db"\n[llm]\nbase_url = "{EXTERNAL_URL}"\n'
        f'[embed]\nprovider = "openai_compat"\nbase_url = "{EXTERNAL_URL}"\n'
    )
    calls: list[str] = []
    monkeypatch.setattr(cli, "make_llm", lambda _: calls.append("llm") or fake_llm())
    monkeypatch.setattr(cli, "make_embedder", lambda _: calls.append("embed") or HashingEmbedder())
    args = ["--config", str(config), "persona", command]
    if command == "chat":
        args.append("虚构问题")
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 0, result.output
    assert calls == ["llm", "embed"]
    assert "invented-password" not in result.output


def test_external_cli_speak_without_grant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(f'db_path = "persona.db"\n[tts]\nprovider = "cloudflare"\nbase_url = "{EXTERNAL_URL}"\n')
    source = tmp_path / "reply.json"
    source.write_text(json.dumps(REPLY))
    calls: list[str] = []

    def factory(_: Any) -> SilentSynthesizer:
        calls.append("tts")
        synth = SilentSynthesizer()
        synth.name = "invented-speech"
        return synth

    monkeypatch.setattr("twin.config.make_synthesizer", factory)
    result = CliRunner().invoke(
        cli.app, ["--config", str(config), "media", "speak", str(source), "--out", str(tmp_path / "audio")]
    )
    assert result.exit_code == 0, result.output
    assert calls == ["tts"] and REPLY["reply"] not in result.output


def test_cli_media_check_fixed_synthetic_sentences_need_no_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(
        f'db_path = "persona.db"\n[tts]\nprovider = "cloudflare"\nbase_url = "{EXTERNAL_URL}"\n'
        f'[asr]\nprovider = "cloudflare"\nbase_url = "{EXTERNAL_URL}"\n'
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
    assert not (tmp_path / "persona.db").exists()


def test_identity_show_and_status_include_every_backend_and_judges(tmp_path: Path) -> None:
    config = tmp_path / "twin.toml"
    config.write_text(
        f'db_path = "persona.db"\n[llm]\nbase_url = "{EXTERNAL_URL}"\negress = "external"\n'
        '[[judges]]\nprovider = "claude_cli"\n[[judges]]\nbase_url = "http://localhost/v1"\n'
    )
    result = CliRunner().invoke(cli.app, ["--config", str(config), "identity", "show"])
    assert result.exit_code == 0
    for row in (
        "llm | openai_compat | backend.invalid | 外部 | 声明",
        "embed | hashing | 未知 | 本机 | 推断",
        "tts | silent | 未知 | 本机 | 推断",
        "llm（评委 1） | claude_cli",
        "llm（评委 2） | openai_compat | localhost | 本机 | 推断",
        "asr | openai_compat | 未知 | 外部 | 推断",
    ):
        assert row in result.output
    assert all(text not in result.output for text in ("invented-password", "已授权", "未授权"))
    assert not (tmp_path / "persona.db").exists()
    rows = egress_status(Settings(judges=[LLMSettings(), LLMSettings()]))
    assert len(rows) == 7
    assert all(set(row) == {"kind", "provider", "host", "external", "declared"} for row in rows)
