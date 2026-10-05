"""Renamed public names fail explicitly; legacy credentials are never used."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from twin import cli
from twin.config import (
    ASRSettings,
    EmbedSettings,
    LLMSettings,
    TTSSettings,
    load_settings,
    make_embedder,
    make_llm,
    make_recognizer,
    make_synthesizer,
)
from twin.embed import OpenAICompatEmbedder
from twin.llm import OpenAICompatLLM
from twin.media.asr import CloudflareWhisper, OpenAICompatTranscription
from twin.media.tts import CloudflareMeloTTS, OpenAICompatSpeech
from twin.util import RenameError, key_from_env

KEY_RENAMES = [
    ("DTWIN_LLM_KEY", "TWIN_LLM_KEY"),
    ("DTWIN_EMBED_KEY", "TWIN_EMBED_KEY"),
    ("DTWIN_TTS_KEY", "TWIN_TTS_KEY"),
    ("DTWIN_ASR_KEY", "TWIN_ASR_KEY"),
]
SECRET = "legacy-secret-never-display"
ENDPOINT = "http://127.0.0.1:8000/v1"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for name in ["DTWIN_CONFIG", "TWIN_CONFIG", *[name for pair in KEY_RENAMES for name in pair]]:
        monkeypatch.delenv(name, raising=False)


@pytest.mark.parametrize("args", [["init"], ["persona", "sources"], ["--config", "other.toml", "persona", "sources"]])
def test_cli_rejects_legacy_default_file(args: list[str]) -> None:
    old = Path("dtwin.toml")
    old.write_text(cli.CONFIG_TEMPLATE)
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 1
    assert "dtwin.toml 已改名为 twin.toml" in result.stderr
    assert "旧名称不再支持" in result.stderr
    assert old.read_text() == cli.CONFIG_TEMPLATE
    assert not Path("twin.toml").exists()
    assert not Path("data").exists()
    with pytest.raises(RenameError, match=r"dtwin\.toml 已改名为 twin\.toml"):
        load_settings()


def test_new_default_file_takes_precedence() -> None:
    Path("dtwin.toml").write_text("not valid TOML")
    Path("twin.toml").write_text('target_name = "新配置"\n')
    assert load_settings().target_name == "新配置"
    result = CliRunner().invoke(cli.app, ["persona", "sources"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("value", ["old.toml", ""])
def test_cli_rejects_legacy_config_env(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("DTWIN_CONFIG", value)
    result = CliRunner().invoke(cli.app, ["init"])
    assert result.exit_code == 1
    assert "DTWIN_CONFIG 已改名为 TWIN_CONFIG" in result.stderr
    assert not Path("twin.toml").exists()
    with pytest.raises(RenameError, match="DTWIN_CONFIG 已改名为 TWIN_CONFIG"):
        load_settings()


def test_new_config_env_takes_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    Path("custom.toml").write_text('target_name = "新环境变量"\n')
    monkeypatch.setenv("DTWIN_CONFIG", "missing-old.toml")
    monkeypatch.setenv("TWIN_CONFIG", "custom.toml")
    assert load_settings().target_name == "新环境变量"
    result = CliRunner().invoke(cli.app, ["persona", "sources"])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(("old", "new"), KEY_RENAMES)
@pytest.mark.parametrize("value", [None, "", "new-key"])
def test_key_rename_guard(monkeypatch: pytest.MonkeyPatch, old: str, new: str, value: str | None) -> None:
    monkeypatch.setenv(old, SECRET)
    if value is not None:
        monkeypatch.setenv(new, value)
    if value:
        assert key_from_env(new) == value
    else:
        with pytest.raises(RenameError) as caught:
            key_from_env(new)
        assert old in str(caught.value) and new in str(caught.value)
        assert "已改名" in str(caught.value) and SECRET not in str(caught.value)
    with pytest.raises(RenameError) as caught:
        key_from_env(old)
    assert old in str(caught.value) and new in str(caught.value)
    assert SECRET not in str(caught.value)


@pytest.mark.parametrize(("old", "new"), KEY_RENAMES)
@pytest.mark.parametrize("has_config", [False, True])
def test_loaded_settings_reject_legacy_keys(
    monkeypatch: pytest.MonkeyPatch, old: str, new: str, has_config: bool
) -> None:
    if has_config:
        Path("twin.toml").write_text(cli.CONFIG_TEMPLATE)
    monkeypatch.setenv(old, SECRET)
    with pytest.raises(RenameError) as caught:
        load_settings()
    assert old in str(caught.value) and new in str(caught.value)
    assert SECRET not in str(caught.value)
    monkeypatch.setenv(new, "new-key")
    load_settings()


def make_backend(family: str) -> object:
    if family == "LLM":
        return make_llm(LLMSettings(model="test", base_url=ENDPOINT))
    if family == "EMBED":
        return make_embedder(EmbedSettings(provider="openai_compat", base_url=ENDPOINT))
    if family == "TTS":
        return make_synthesizer(TTSSettings(provider="openai_compat", model="test", base_url=ENDPOINT))
    return make_recognizer(ASRSettings(model="test", base_url=ENDPOINT))


@pytest.mark.parametrize(("old", "new"), KEY_RENAMES)
def test_backend_factories_reject_legacy_keys(monkeypatch: pytest.MonkeyPatch, old: str, new: str) -> None:
    family = new.split("_")[1]
    monkeypatch.setenv(old, SECRET)
    with pytest.raises(RenameError) as caught:
        make_backend(family)
    assert old in str(caught.value) and new in str(caught.value)
    assert SECRET not in str(caught.value)
    monkeypatch.setenv(new, "new-key")
    make_backend(family)  # Construction only: no requests to the endpoint.


@pytest.mark.parametrize(("old", "new"), KEY_RENAMES)
def test_cli_reports_both_key_names(monkeypatch: pytest.MonkeyPatch, old: str, new: str) -> None:
    Path("twin.toml").write_text(
        f'[llm]\nmodel = "test"\nbase_url = "{ENDPOINT}"\n'
        f'[embed]\nprovider = "openai_compat"\nbase_url = "{ENDPOINT}"\n'
        f'[tts]\nprovider = "openai_compat"\nmodel = "test"\nbase_url = "{ENDPOINT}"\n'
        f'[asr]\nmodel = "test"\nbase_url = "{ENDPOINT}"\n'
    )
    monkeypatch.setenv(old, SECRET)
    args = ["persona", "build"] if new.split("_")[1] in {"LLM", "EMBED"} else ["media", "check", "--out", "report"]
    result = CliRunner().invoke(cli.app, args)
    assert result.exit_code == 1
    assert old in result.stderr and new in result.stderr
    assert "已改名" in result.stderr and SECRET not in result.output
    assert not Path("report").exists()
    if new == "TWIN_TTS_KEY":
        Path("reply.json").write_text(
            json.dumps(
                {
                    "reply": "验证。",
                    "citations": [],
                    "confidence": 0.8,
                    "abstain": False,
                    "abstain_reason": "",
                    "retrieved_ids": [],
                }
            )
        )
        result = CliRunner().invoke(cli.app, ["media", "speak", "reply.json", "--out", "audio"])
        assert result.exit_code == 1
        assert old in result.stderr and new in result.stderr
        assert "已改名" in result.stderr and SECRET not in result.output
        assert not Path("audio").exists()


@pytest.mark.parametrize("backend", ["llm", "embed", "tts_openai", "tts_cloudflare", "asr_openai", "asr_cloudflare"])
def test_direct_backends_reject_legacy_keys(monkeypatch: pytest.MonkeyPatch, backend: str) -> None:
    family = backend.split("_")[0].upper()
    old, new = next(pair for pair in KEY_RENAMES if pair[1] == f"TWIN_{family}_KEY")
    monkeypatch.setenv(old, SECRET)
    with pytest.raises(RenameError) as caught:
        if backend == "llm":
            OpenAICompatLLM("test", base_url=ENDPOINT, api_key_env=new)
        elif backend == "embed":
            OpenAICompatEmbedder("test", base_url=ENDPOINT, api_key_env=new)
        elif backend == "tts_openai":
            OpenAICompatSpeech("test", base_url=ENDPOINT, api_key_env=new)
        elif backend == "tts_cloudflare":
            CloudflareMeloTTS(base_url=ENDPOINT, api_key_env=new)
        elif backend == "asr_openai":
            OpenAICompatTranscription("test", base_url=ENDPOINT, api_key_env=new)
        else:
            CloudflareWhisper(base_url=ENDPOINT, api_key_env=new)
    assert old in str(caught.value) and new in str(caught.value)
    assert SECRET not in str(caught.value)
