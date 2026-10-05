"""Offline preset-only speech and shared identity-label checks, using invented data."""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any, get_args

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from typer.testing import CliRunner

from twin.cli import app as cli
from twin.config import Settings, TTSSettings, make_synthesizer
from twin.identity import Identity
from twin.media.schema import (
    CHAT_NOTICE,
    EXPLICIT_LABEL,
    MediaManifest,
    MediaScript,
    SpeechRequest,
    SynthCapabilities,
    VoiceSpec,
    disclaimer,
)
from twin.media.tts import MediaRejected, MediaTimeout, MediaUnavailable, OpenAICompatSpeech
from twin.web.app import STATIC_DIR, create_app

BASE = "https://speech.invalid/v1"
KEY = "invented-voice-test-secret"


@pytest.fixture(autouse=True)
def own_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    for variable in ("TWIN_CONFIG", "DTWIN_CONFIG", "OPENAI_BASE_URL", "ANTHROPIC_BASE_URL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("TWIN_TTS_KEY", KEY)
    monkeypatch.setattr("twin.media.tts.time.sleep", lambda _: None)


@pytest.mark.parametrize("voice", ["default", "Junhao", "preset_2.en-1", "a" * 64])
def test_preset_id_format(voice: str) -> None:
    assert TTSSettings(voice=voice).voice == voice


@pytest.mark.parametrize(
    "voice",
    [
        "",
        ".",
        "..",
        "a" * 65,
        "默认",
        "preset name",
        "preset\n",
        "/tmp/voice.wav",
        "./voice.wav",
        "../voice.wav",
        "~/voice.wav",
        r"C:\voices\sample.wav",
        "https://speech.invalid/voice",
        "file:///tmp/voice.wav",
        "data:audio/wav;base64,AAAA",
        "blob:invented-reference",
        "@reference",
        "preset?audio=sample",
    ],
)
def test_voice_paths_urls_and_data_are_rejected_in_chinese(voice: str) -> None:
    with pytest.raises(ValidationError) as caught:
        TTSSettings(voice=voice)
    message = caught.value.errors(include_input=False)[0]["msg"]
    assert "仅支持预置音色" in message and "禁止声音复刻" in message


@pytest.mark.parametrize("provider", ["silent", "cloudflare"])
def test_fixed_backend_allowlists(provider: str) -> None:
    settings = TTSSettings.model_validate({"provider": provider, "base_url": BASE})
    synth = make_synthesizer(settings)
    assert synth.capabilities.voices == ["default"]
    with pytest.raises(MediaRejected, match=r"missing.*共 1 个预置音色"):
        make_synthesizer(settings.model_copy(update={"voice": "missing"}))
    with pytest.raises(MediaRejected, match=r"missing.*共 1 个预置音色"):
        synth.synthesize(SpeechRequest(text="虚构测试句。", voice=VoiceSpec(voice_id="missing")))


@pytest.mark.parametrize("status", [200, 404, 405])
def test_voice_discovery_is_lazy_cached_and_uses_speech_transport(status: int) -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert request.extensions["timeout"] == dict.fromkeys(("connect", "read", "write", "pool"), 7.0)
        if request.method == "GET":
            assert str(request.url) == BASE + "/voices"
            assert request.content == b""
            return httpx.Response(status, json={"voices": ["Junhao", "preset.en"]})
        assert str(request.url) == BASE + "/audio/speech"
        assert json.loads(request.content)["voice"] == "Junhao"
        return httpx.Response(200, content=b"ID3-invented", headers={"content-type": "audio/mpeg"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        synth = OpenAICompatSpeech("invented-model", BASE, voice=VoiceSpec(voice_id="Junhao"), timeout=7, client=client)
        assert synth.identity and not calls
        declared = synth.capabilities
        assert declared.voices == (["Junhao", "preset.en"] if status == 200 else None)
        assert synth.capabilities is declared
        synth.synthesize(SpeechRequest(text="虚构测试句。", voice=synth.voice, audio_format="mp3"))
        synth.synthesize(SpeechRequest(text="另一测试句。", voice=synth.voice, audio_format="mp3"))
    assert [request.method for request in calls] == ["GET", "POST", "POST"]
    assert SynthCapabilities.model_validate({}).voices is None


@pytest.mark.parametrize("voices", [[], ["Junhao", "preset.en"]])
def test_first_synthesis_rejects_unknown_configured_voice_before_post(voices: list[str]) -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"voices": voices})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        synth = OpenAICompatSpeech("invented-model", BASE, voice=VoiceSpec(voice_id="missing"), client=client)
        assert not calls
        for _ in range(2):
            with pytest.raises(MediaRejected) as caught:
                synth.synthesize(SpeechRequest(text="虚构测试句。", voice=synth.voice))
            assert "missing" in str(caught.value) and f"共 {len(voices)} 个预置音色" in str(caught.value)
    assert calls == ["GET"]


def test_allowlist_also_checks_request_voice() -> None:
    calls: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={"voices": ["default"]})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        synth = OpenAICompatSpeech("invented-model", BASE, client=client)
        with pytest.raises(MediaRejected, match="missing"):
            synth.synthesize(SpeechRequest(text="虚构测试句。", voice=VoiceSpec(voice_id="missing")))
    assert calls == ["GET"]


@pytest.mark.parametrize("failure", [302, 401, 403, 408, 429, 500, "timeout", "transport"])
def test_voice_discovery_errors_are_unified_and_secret_free(failure: int | str) -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if failure == "timeout":
            raise httpx.ReadTimeout(f"{KEY} {BASE}", request=request)
        if failure == "transport":
            raise httpx.ConnectError(f"{KEY} {BASE}", request=request)
        assert isinstance(failure, int)
        return httpx.Response(failure, text=f"{KEY} {BASE}")

    kind = (
        MediaTimeout
        if failure in (408, "timeout")
        else MediaRejected
        if failure in (302, 401, 403)
        else MediaUnavailable
    )
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        synth = OpenAICompatSpeech("invented-model", BASE, client=client, max_retries=1)
        with pytest.raises(kind) as caught:
            _ = synth.capabilities
    rendered = "".join(traceback.format_exception(caught.value))
    assert KEY not in rendered and BASE not in rendered
    assert len(calls) == (1 if failure in (302, 401, 403) else 2)
    assert all(request.method == "GET" for request in calls)


@pytest.mark.parametrize("body", [b"not JSON", b"[]", b"{}", b'{"voices":"default"}', b'{"voices":[1]}'])
def test_invalid_voice_discovery_is_not_silently_accepted(body: bytes) -> None:
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))) as client:
        synth = OpenAICompatSpeech("invented-model", BASE, client=client)
        with pytest.raises(MediaUnavailable, match="invalid voices"):
            _ = synth.capabilities


def test_voice_discovery_failures_can_be_retried() -> None:
    calls = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503) if calls == 1 else httpx.Response(200, json={"voices": ["default"]})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        synth = OpenAICompatSpeech("invented-model", BASE, client=client, max_retries=0)
        with pytest.raises(MediaUnavailable):
            _ = synth.capabilities
        assert synth.capabilities.voices == ["default"]
        assert synth.capabilities.voices == ["default"]
    assert calls == 2


def test_identity_voice_is_additive_and_cli_reads_configuration(tmp_path: Path) -> None:
    legacy = {"name": "虚构人物", "aliases": []}
    assert Identity.model_validate(legacy).voice is None
    identity = Identity(name="虚构人物", aliases=[], voice="Junhao")
    assert Identity.model_validate_json(identity.model_dump_json()).voice == "Junhao"
    config = tmp_path / "twin.toml"
    config.write_text('target_name = "虚构人物"\ndb_path = "identity.db"\n[tts]\nvoice = "Junhao"\n', encoding="utf-8")
    result = CliRunner().invoke(cli, ["--config", str(config), "identity", "show"])
    assert result.exit_code == 0, result.exception
    assert "音色：Junhao（预置音色；声音复刻与照片驱动形象在本版本禁止）" in result.stdout


def test_literal_contracts_match_label_source() -> None:
    for model, field in ((MediaScript, "explicit_label"), (MediaManifest, "label")):
        assert get_args(model.model_fields[field].annotation) == (EXPLICIT_LABEL,)
        assert model.model_fields[field].default == EXPLICIT_LABEL


def test_static_assets_do_not_duplicate_labels_or_privacy_claims() -> None:
    for path in STATIC_DIR.rglob("*"):
        if path.is_file():
            content = path.read_bytes()
            for text in (EXPLICIT_LABEL, "不代表", "数据只保存在本机"):
                assert text.encode() not in content, path


def test_disclaimer_wording() -> None:
    prefix = "所有推演结果均为模拟，供个人使用参考，不代表虚构人物本人的意见或决定。"
    assert disclaimer("虚构人物", False) == prefix + "数据只保存在本机。"
    assert disclaimer("虚构人物", True) == prefix + "部分数据经配置的外部服务处理，详见页面顶部的出境提示。"
    assert CHAT_NOTICE == (
        "分身以本人身份、第一人称作答，只依据人格档案和本人原话；"
        "没有依据时会直说并标注“需要本人确认”。回复是模拟，不代表本人意见。"
    )


@pytest.mark.parametrize("backend", ["llm", "embed", "tts", "asr", "judge"])
def test_status_labels_follow_configured_external_backends(backend: str, tmp_path: Path) -> None:
    configuration: dict[str, Any] = {
        "target_name": "虚构人物",
        "db_path": tmp_path / "status.db",
        "llm": {"egress": "local"},
        "embed": {"egress": "local"},
        "tts": {"egress": "local"},
        "asr": {"egress": "local"},
    }
    if backend == "judge":
        configuration["judges"] = [{"base_url": BASE, "egress": "external"}]
    else:
        configuration[backend] = {"base_url": BASE, "egress": "external"}
    settings = Settings.model_validate(configuration)
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        response = client.get("/api/status")
    assert response.status_code == 200
    status = response.json()
    assert status["labels"] == {
        "explicit": EXPLICIT_LABEL,
        "disclaimer": disclaimer("虚构人物", True),
        "chat_notice": CHAT_NOTICE,
    }


def test_local_backends_do_not_claim_external_processing(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {
            "db_path": tmp_path / "local.db",
            "llm": {"egress": "local"},
            "asr": {"egress": "local"},
        }
    )
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.get("/api/status").json()["labels"]["disclaimer"] == disclaimer(settings.target_name, False)


def test_web_capability_discovery_stays_lazy_and_errors_are_contained(tmp_path: Path) -> None:
    calls: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(401, text=KEY)

    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        synth = OpenAICompatSpeech("invented-model", BASE, client=transport)
        settings = Settings(db_path=tmp_path / "lazy.db")
        with TestClient(create_app(settings, synthesizer_factory=lambda: synth), base_url="http://localhost") as client:
            assert client.get("/api/status").status_code == 200
            assert not calls
            response = client.get("/api/media/capabilities")
    assert response.status_code == 200 and response.json()["available"] is False
    assert KEY not in response.text and BASE not in response.text
    assert len(calls) == 1
