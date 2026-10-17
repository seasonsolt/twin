"""System settings: the administrator's switches for speech and video, the token quota, and the read-only views of
twin.toml and the keys."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_web_gpu import Fake

from twin.config import (
    EmbedSettings,
    LibrarySettings,
    LLMSettings,
    Settings,
    TTSSettings,
    VideoSettings,
)
from twin.media.tts import SilentSynthesizer, SpeechSynthesizer
from twin.web import create_app
from twin.web.gpu import GpuMonitor, targets
from twin.web.system import SystemSettings

CSRF = {"X-Twin": "1"}
SPEECH: dict[str, Any] = {
    "kind": "chat_reply",
    "answer": {
        "reply": "首先认真核对所有资料。",
        "citations": [],
        "confidence": 0.8,
        "abstain": False,
        "abstain_reason": "",
        "retrieved_ids": [],
    },
    "persona_name": "合成人物",
    "segments": [0],
}


def speech() -> SpeechSynthesizer:
    synth = SilentSynthesizer()
    synth.name = "openai_compat:speech"
    return synth


def configured(tmp_path: Path, tts: str = "http://127.0.0.1:9/v1", **extra: Any) -> Settings:
    return Settings(
        db_path=tmp_path / "twin.db",
        tts=TTSSettings(provider="openai_compat", base_url=tts, model="tts-test", api_key_env="TEST_SYSTEM_TTS_KEY"),
        video=VideoSettings(provider="remote", command="configured-command"),
        **extra,
    )


def client_for(settings: Settings) -> TestClient:
    app = create_app(settings, synthesizer_factory=speech)
    monitor: GpuMonitor = app.state.gpu
    monitor.interval = 3600  # no background round during the test
    return TestClient(app, base_url="http://localhost")


def test_untouched_switches_follow_the_configuration(tmp_path: Path) -> None:
    system = SystemSettings(configured(tmp_path))
    assert system.enabled("tts") and system.enabled("video") and not system.off("tts")
    bare = SystemSettings(Settings(db_path=tmp_path / "bare" / "twin.db"))
    assert not bare.enabled("tts") and not bare.off("tts")
    assert bare.missing("video") == "twin.toml 里没有配置 [video]"
    with pytest.raises(ValueError, match=r"没有配置 \[tts\]"):
        bare.switch("tts", True, None)


def test_switches_persist_privately(tmp_path: Path) -> None:
    settings = configured(tmp_path)
    SystemSettings(settings).switch("tts", False, "admin@example.com")
    path = tmp_path / "system.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    stored = json.loads(path.read_text())["switches"]["tts"]
    assert stored["enabled"] is False and stored["by"] == "admin@example.com"
    again = SystemSettings(settings)
    assert again.off("tts") and again.enabled("video")
    # A damaged file falls back to the configuration rather than failing the server.
    path.write_text("{not json")
    assert SystemSettings(settings).enabled("tts")


def test_switching_speech_and_video_off(tmp_path: Path) -> None:
    client = client_for(configured(tmp_path))
    capabilities = client.get("/api/media/capabilities").json()
    assert capabilities["available"] and capabilities["video"]["available"]

    assert client.put("/api/admin/system/switches/tts", json={"enabled": False}, headers=CSRF).status_code == 200
    body = client.put("/api/admin/system/switches/video", json={"enabled": False}, headers=CSRF).json()
    assert body["switches"]["tts"]["enabled"] is False and body["switches"]["video"]["enabled"] is False
    capabilities = client.get("/api/media/capabilities").json()
    assert not capabilities["available"] and not capabilities["video"]["available"]
    refused = client.post("/api/media/audio", json=SPEECH, headers=CSRF)
    assert refused.status_code == 503 and refused.json()["detail"] == "管理员已关闭朗读"
    video = {key: value for key, value in SPEECH.items() if key != "segments"}
    refused = client.post("/api/media/video", json=video, headers=CSRF)
    assert refused.status_code == 503 and refused.json()["detail"] == "管理员已关闭视频"

    client.put("/api/admin/system/switches/tts", json={"enabled": True}, headers=CSRF)
    assert client.get("/api/media/capabilities").json()["available"]


def test_switch_needs_configuration(tmp_path: Path) -> None:
    client = client_for(Settings(db_path=tmp_path / "twin.db"))
    switches = client.get("/api/admin/system").json()["switches"]
    assert switches["video"] == {
        "configured": False,
        "enabled": False,
        "missing": "twin.toml 里没有配置 [video]",
        "changed_at": None,
        "changed_by": None,
    }
    refused = client.put("/api/admin/system/switches/video", json={"enabled": True}, headers=CSRF)
    assert refused.status_code == 409 and "重启" in refused.json()["detail"]
    assert client.put("/api/admin/system/switches/gpu", json={"enabled": True}, headers=CSRF).status_code == 404


def test_speech_service_is_checked_only_while_on(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SYSTEM_TTS_KEY", "sk-test-only")
    fake = Fake()
    try:
        fake.health = {"status": "ok"}
        settings = configured(tmp_path, tts=f"{fake.url}/v1")
        assert [(t.key, t.health_url) for t in targets(settings)] == [("tts", f"{fake.url}/healthz")]
        client = client_for(settings)
        tts = next(s for s in client.get("/api/admin/system").json()["services"] if s["key"] == "tts")
        assert tts["enabled"] and tts["latest"]["ok"] and tts["name"] == "朗读服务"
        assert fake.requests[0][1] == "/healthz" and fake.requests[0][2]["Authorization"] == "Bearer sk-test-only"

        client.put("/api/admin/system/switches/tts", json={"enabled": False}, headers=CSRF)
        asked = len(fake.requests)
        body = client.get("/api/admin/system?refresh=true").json()
        assert len(fake.requests) == asked
        assert not next(s for s in body["services"] if s["key"] == "tts")["enabled"]
        assert "sk-test-only" not in json.dumps(body)

        # A speech server without /healthz counts when it lists its models.
        fake.health_status = 404
        fake.paths["/v1/models"] = (200, {"data": [{"id": "tts-test"}]})
        monitor = GpuMonitor(settings, timeout=0.5)
        monitor.check()
        assert monitor.snapshot()["services"][0]["latest"]["ok"]
        assert [r[1] for r in fake.requests[-2:]] == ["/healthz", "/v1/models"]
    finally:
        fake.close()


def test_quota_changes_at_once(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", library=LibrarySettings(batch_tokens=1000, batch_hours=24))
    client = client_for(settings)
    quota = client.get("/api/admin/system").json()["quota"]
    assert (quota["limit"], quota["hours"], quota["used"], quota["custom"]) == (1000, 24, 0, False)
    body = client.put("/api/admin/system/quota", json={"batch_tokens": 5000, "batch_hours": 6}, headers=CSRF).json()
    assert (body["quota"]["limit"], body["quota"]["hours"], body["quota"]["custom"]) == (5000, 6, True)
    assert client.get("/api/library").status_code == 200
    assert client.put("/api/admin/system/quota", json={"batch_hours": 0}, headers=CSRF).status_code == 400
    body = client.put("/api/admin/system/quota", json={}, headers=CSRF).json()
    assert (body["quota"]["limit"], body["quota"]["hours"], body["quota"]["custom"]) == (1000, 24, False)


def test_views_name_keys_without_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TEST_SYSTEM_LLM_KEY", "sk-llm-test-only")
    monkeypatch.delenv("TEST_SYSTEM_TTS_KEY", raising=False)
    settings = configured(
        tmp_path,
        tts="http://user:secret@127.0.0.1:8001/v1",
        llm=LLMSettings(base_url="https://llm.example.com/v1", model="m-test", api_key_env="TEST_SYSTEM_LLM_KEY"),
        embed=EmbedSettings(provider="openai_compat", base_url="http://127.0.0.1:18791/v1"),
    )
    body = client_for(settings).get("/api/admin/system").json()
    keys = {k["env"]: k for k in body["keys"]}
    assert keys["TEST_SYSTEM_LLM_KEY"] == {"env": "TEST_SYSTEM_LLM_KEY", "use": "文字模型", "set": True}
    assert keys["TEST_SYSTEM_TTS_KEY"]["set"] is False
    assert body["models"][0] | {"external": True} == {
        "use": "整理记忆、校对转写",
        "section": "[llm]",
        "provider": "OpenAI 兼容",
        "model": "m-test",
        "address": "llm.example.com",
        "external": True,
    }
    assert ["地址", "127.0.0.1:8001"] in body["config"]["tts"]
    assert ["地址", "127.0.0.1:18791"] in body["config"]["embed"]
    text = json.dumps(body)
    assert "sk-llm-test-only" not in text and "secret" not in text and "configured-command" not in text
