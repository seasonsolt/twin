"""System settings: the administrator's switches for speech and video, the token quota, common parameters, the
models' addresses and names, the keys (written, never read back), the views of twin.toml and the keys, and the
upgrade of every twin's memory kernel and ledger."""

from __future__ import annotations

import datetime as dt
import json
import os
import stat
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_web_gpu import Fake

from twin.config import (
    EmbedSettings,
    KernelSettings,
    LibrarySettings,
    LLMSettings,
    Settings,
    TTSSettings,
    VideoSettings,
)
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.collector import ATTRIBUTION_VERSION, CLEANUP_VERSION
from twin.media.tts import SilentSynthesizer, SpeechSynthesizer
from twin.ops.envfile import load_env_file, write_env_value
from twin.persona.kernel import KERNEL
from twin.persona.ledger import LEDGER_VERSION
from twin.persona.sources import parse_note
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web.gpu import GpuMonitor, targets
from twin.web.jobs import PersonaProcessing
from twin.web.personas import Personas
from twin.web.system import ModelBody, SystemSettings

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


def editable(body: dict[str, Any], name: str) -> dict[str, Any]:
    return next(m for m in body["editable_models"] if m["name"] == name)


def test_admin_points_models_elsewhere(tmp_path: Path) -> None:
    settings = configured(
        tmp_path,
        llm=LLMSettings(base_url="http://127.0.0.1:8000/v1", model="m-toml"),
        embed=EmbedSettings(provider="openai_compat", base_url="http://127.0.0.1:18791/v1"),
    )
    client = client_for(settings)
    app = client.app
    body = client.get("/api/admin/system").json()
    assert editable(body, "llm") | {"changed_at": None} == {
        "name": "llm",
        "section": "[llm]",
        "use": "整理记忆、校对转写",
        "base_url": "http://127.0.0.1:8000/v1",
        "model": "m-toml",
        "locked": None,
        "custom": False,
        "changed_at": None,
        "changed_by": None,
    }
    assert "没有配置 [chat_llm]" in editable(body, "chat_llm")["locked"]

    changed = client.put(
        "/api/admin/system/models/llm", json={"base_url": "https://llm.example.com/v1/", "model": "m-new"}, headers=CSRF
    )
    assert changed.status_code == 200
    assert editable(changed.json(), "llm")["base_url"] == "https://llm.example.com/v1"
    assert changed.json()["models"][0]["address"] == "llm.example.com"
    # Every twin's copy of the settings shares the section, so all of them use the new address at once.
    assert app.state.personas.settings_for(app.state.personas.data["default"]).llm.model == "m-new"
    system: SystemSettings = app.state.system
    assert system.generation == 1 and system.audit()[0]["model"] == ["m-toml", "m-new"]

    # Only the model name: the address stays twin.toml's. Kept across a restart.
    client.put("/api/admin/system/models/embed", json={"model": "bge-other"}, headers=CSRF)
    again = configured(
        tmp_path,
        llm=LLMSettings(base_url="http://127.0.0.1:8000/v1", model="m-toml"),
        embed=EmbedSettings(provider="openai_compat", base_url="http://127.0.0.1:18791/v1"),
    )
    SystemSettings(again)
    assert (again.llm.base_url, again.llm.model) == ("https://llm.example.com/v1", "m-new")
    assert (again.embed.base_url, again.embed.model) == ("http://127.0.0.1:18791/v1", "bge-other")

    for bad in ("ftp://host/v1", "http://user:pass@host/v1", "http://host/v1?key=1"):
        refused = client.put("/api/admin/system/models/llm", json={"base_url": bad}, headers=CSRF)
        assert refused.status_code == 400 and "http://" in refused.json()["detail"]
    assert client.put("/api/admin/system/models/chat_llm", json={"model": "x"}, headers=CSRF).status_code == 400
    assert client.put("/api/admin/system/models/judges", json={"model": "x"}, headers=CSRF).status_code == 404

    back = client.put("/api/admin/system/models/llm", json={}, headers=CSRF).json()
    assert editable(back, "llm")["base_url"] == "http://127.0.0.1:8000/v1" and not editable(back, "llm")["custom"]
    assert settings.llm.model == "m-toml"


def test_models_of_other_providers_stay_in_twin_toml(tmp_path: Path) -> None:
    system = SystemSettings(Settings(db_path=tmp_path / "twin.db", llm=LLMSettings(provider="claude_cli")))
    assert "Claude CLI" in str(system.model_locked("llm")) and system.model_locked("embed")
    with pytest.raises(ValueError, match=r"只能在 twin\.toml"):
        system.set_model("llm", ModelBody(model="x"), None)


def test_admin_replaces_keys_without_reading_them(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / "server.env"
    env.write_text("# 服务器密钥\nOTHER_VALUE=keep\nTEST_SYSTEM_TTS_KEY=old\n")
    env.chmod(0o600)
    monkeypatch.setenv("TWIN_ENV_FILE", str(env))
    monkeypatch.setenv("TEST_SYSTEM_TTS_KEY", "old")
    client = client_for(configured(tmp_path))
    secret = "sk-new #with space"
    body = client.put("/api/admin/system/keys/TEST_SYSTEM_TTS_KEY", json={"value": secret}, headers=CSRF).json()
    assert next(k for k in body["keys"] if k["env"] == "TEST_SYSTEM_TTS_KEY")["set"] is True
    assert body["env_file"] == "server.env"
    assert secret not in json.dumps(body) and secret not in (tmp_path / "system-audit.jsonl").read_text()
    assert body["audit"][0] | {"at": None} == {
        "at": None,
        "by": None,
        "action": "key",
        "env": "TEST_SYSTEM_TTS_KEY",
        "set": True,
    }
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "system-audit.jsonl").stat().st_mode) == 0o600
    assert env.read_text().splitlines()[:2] == ["# 服务器密钥", "OTHER_VALUE=keep"]
    assert os.environ["TEST_SYSTEM_TTS_KEY"] == secret
    # The file reads back as written.
    monkeypatch.delenv("TEST_SYSTEM_TTS_KEY")
    assert load_env_file(env) == ["OTHER_VALUE", "TEST_SYSTEM_TTS_KEY"] and os.environ["TEST_SYSTEM_TTS_KEY"] == secret

    assert client.put("/api/admin/system/keys/PATH", json={"value": "x"}, headers=CSRF).status_code == 404
    refused = client.put("/api/admin/system/keys/TEST_SYSTEM_TTS_KEY", json={"value": "a\nB=c"}, headers=CSRF)
    assert refused.status_code == 400 and "换行" in refused.json()["detail"]

    removed = client.put("/api/admin/system/keys/TEST_SYSTEM_TTS_KEY", json={}, headers=CSRF).json()
    assert next(k for k in removed["keys"] if k["env"] == "TEST_SYSTEM_TTS_KEY")["set"] is False
    assert "TEST_SYSTEM_TTS_KEY" not in env.read_text() and "TEST_SYSTEM_TTS_KEY" not in os.environ

    env.chmod(0o644)
    refused = client.put("/api/admin/system/keys/TEST_SYSTEM_TTS_KEY", json={"value": "x"}, headers=CSRF)
    assert refused.status_code == 409 and "chmod 600" in refused.json()["detail"]


def test_env_values_read_back_as_written(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env = tmp_path / ".env"
    for value in ("plain", "with space", "#hash", "'single", 'dou"ble', "a'b\"c", "中文值"):
        write_env_value(env, "TEST_ROUND_TRIP", value)
        monkeypatch.delenv("TEST_ROUND_TRIP", raising=False)
        load_env_file(env)
        assert os.environ["TEST_ROUND_TRIP"] == value
    with pytest.raises(ValueError, match="单引号和双引号"):
        write_env_value(env, "TEST_ROUND_TRIP", "a 'b\"c")
    with pytest.raises(ValueError, match="变量名"):
        write_env_value(env, "BAD-NAME", "x")
    write_env_value(env, "TEST_ROUND_TRIP", None)
    assert env.read_text() == "" and stat.S_IMODE(env.stat().st_mode) == 0o600


def test_admin_switches_work_and_ledger_off_but_never_chat(tmp_path: Path) -> None:
    client = client_for(Settings(db_path=tmp_path / "twin.db"))
    assert client.get("/api/whoami").json()["features"] == {"work": True, "ledger": True}
    assert client.get("/api/persona/work").status_code == 200
    assert client.get("/api/persona/ledger").status_code == 200

    body = client.put("/api/admin/system/features/work", json={"enabled": False}, headers=CSRF).json()
    assert body["features"]["work"] | {"changed_at": None} == {
        "label": "工作",
        "enabled": False,
        "changed_at": None,
        "changed_by": None,
    }
    client.put("/api/admin/system/features/ledger", json={"enabled": False}, headers=CSRF)
    assert client.get("/api/whoami").json()["features"] == {"work": False, "ledger": False}
    for path in ("/api/persona/work", "/api/persona/work/t1/stop", "/api/persona/ledger/brief"):
        refused = client.get(path) if "stop" not in path else client.post(path, headers=CSRF)
        assert refused.status_code == 403 and refused.json()["code"] == "feature_off", path
    assert client.get("/api/persona/work").json()["detail"] == "管理员已关闭工作"
    # Chat and everything else stay.
    assert client.get("/api/status").status_code == 200
    assert client.get("/api/persona/workspace-like").status_code != 403
    refused = client.put("/api/admin/system/features/chat", json={"enabled": False}, headers=CSRF)
    assert refused.status_code == 404 and "聊天不能关闭" in refused.json()["detail"]
    system: SystemSettings = client.app.state.system
    assert system.audit()[0] | {"at": None} == {
        "at": None,
        "by": None,
        "action": "feature",
        "feature": "ledger",
        "enabled": False,
    }
    # Kept across a restart; switching back on brings the page back.
    assert not SystemSettings(Settings(db_path=tmp_path / "twin.db")).feature_on("work")
    client.put("/api/admin/system/features/work", json={"enabled": True}, headers=CSRF)
    assert client.get("/api/persona/work").status_code == 200


def test_admin_changes_common_parameters_at_once(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", library=LibrarySettings(max_pending=20))
    client = client_for(settings)
    params = {p["key"]: p for p in client.get("/api/admin/system").json()["params"]}
    assert params["library.max_pending"] | {"help": None} == {
        "key": "library.max_pending",
        "label": "每人排队转写上限",
        "help": None,
        "unit": "条",
        "value": 20,
        "default": 20,
        "custom": False,
        "changed_at": None,
        "changed_by": None,
    }
    assert params["kernel.auto_rebuild"]["value"] is True

    body = client.put("/api/admin/system/params/library.max_pending", json={"value": 3}, headers=CSRF).json()
    changed = next(p for p in body["params"] if p["key"] == "library.max_pending")
    assert (changed["value"], changed["default"], changed["custom"]) == (3, 20, True)
    assert settings.library.max_pending == 3
    assert client.get("/api/library").json()["max_pending"] == 3

    # Every twin's copy of the settings shares the section, so a twin made later follows too.
    client.put("/api/admin/system/params/kernel.auto_rebuild", json={"value": False}, headers=CSRF)
    registry: Personas = client.app.state.personas
    other = client.post("/api/personas", json={"name": "另一个"}, headers=CSRF).json()["id"]
    assert not registry.settings_for("default").kernel.auto_rebuild
    assert not registry.settings_for(other).kernel.auto_rebuild

    for key, value, message in [
        ("library.max_pending", 0, "每人排队转写上限要大于 0"),
        ("library.max_pending", 1.5, "每人排队转写上限请填整数"),
        ("library.max_pending", True, "请填数字"),
        ("library.headroom_gb", -1, "磁盘安全余量不能小于 0"),
        ("kernel.auto_rebuild", 1, "请填开或关"),
    ]:
        refused = client.put(f"/api/admin/system/params/{key}", json={"value": value}, headers=CSRF)
        assert refused.status_code == 400 and refused.json()["detail"] == message, (key, value)
    assert settings.library.max_pending == 3
    assert client.put("/api/admin/system/params/max_workers", json={"value": 9}, headers=CSRF).status_code == 404

    system: SystemSettings = client.app.state.system
    assert system.audit()[0] | {"at": None} == {
        "at": None,
        "by": None,
        "action": "param",
        "param": "kernel.auto_rebuild",
        "value": [True, False],
    }
    # Kept across a restart; an empty value goes back to twin.toml.
    restarted = Settings(db_path=tmp_path / "twin.db", library=LibrarySettings(max_pending=20))
    SystemSettings(restarted)
    assert restarted.library.max_pending == 3 and not restarted.kernel.auto_rebuild
    client.put("/api/admin/system/params/library.max_pending", json={}, headers=CSRF)
    assert settings.library.max_pending == 20
    # A damaged stored value falls back to twin.toml rather than failing the server.
    stored = json.loads((tmp_path / "system.json").read_text())
    stored["params"]["kernel.max_auto_rebuild_chunks"] = {"value": -5}
    (tmp_path / "system.json").write_text(json.dumps(stored))
    fallback = Settings(db_path=tmp_path / "twin.db")
    SystemSettings(fallback)
    assert fallback.kernel.max_auto_rebuild_chunks == 400


def test_admin_upgrades_every_twins_kernel(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", kernel=KernelSettings(auto_rebuild=False))
    with PersonaStore(settings.db_path) as store:
        store.put_source(parse_note("我喜欢写程序", settings))
        store.mark_profile_built(
            dt.datetime.now(dt.UTC).isoformat(), store.get_meta("sources_changed_at"), replace(KERNEL, prompt="old")
        )
    queued: list[bool] = []
    monkeypatch.setattr(PersonaProcessing, "queue", lambda self: queued.append(True))
    application = create_app(
        settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder
    )
    with TestClient(application, base_url="http://localhost", headers=CSRF) as client:
        assert not queued  # automatic upgrade is off
        other = client.post("/api/personas", json={"name": "新分身"}).json()["id"]
        components = client.get("/api/admin/system/components").json()
        assert components["kernel"]["version"] == KERNEL.__dict__
        twins = {t["id"]: t for t in components["kernel"]["twins"]}
        assert twins["default"] | {"version": None} == {
            "id": "default",
            "name": "本人",
            "version": None,
            "built": replace(KERNEL, prompt="old").__dict__,
            "scope": "full",
            "pending_chunks": 1,
            "state": "awaiting_confirmation",
        }
        assert twins[other]["name"] == "新分身" and twins[other]["scope"] == "none"
        assert components["ledger"] | {"twins": None} == {"version": LEDGER_VERSION, "enabled": True, "twins": None}
        assert components["library"] == {"attribution": ATTRIBUTION_VERSION, "cleanup": CLEANUP_VERSION}

        # Only the twin built on the older kernel is rebuilt.
        body = client.post("/api/admin/system/components/kernel").json()
        assert body["queued"] == ["default"] and len(queued) == 1
        assert client.post("/api/admin/system/components/kernel", json={"persona_ids": [other]}).json()["queued"] == []
        missing = client.post("/api/admin/system/components/kernel", json={"persona_ids": ["nobody"]})
        assert missing.status_code == 404
        entry = application.state.system.audit()[0]
        assert (entry["action"], entry["personas"]) == ("kernel", ["default"])

        # Nothing to read again: no meeting yet. With the ledger off it cannot be upgraded.
        assert client.post("/api/admin/system/components/ledger").json()["queued"] == []
        client.put("/api/admin/system/features/ledger", json={"enabled": False})
        refused = client.post("/api/admin/system/components/ledger")
        assert refused.status_code == 409 and "承诺账本已关闭" in refused.json()["detail"]
        assert client.get("/api/admin/system/components").json()["ledger"]["twins"] == []


def test_members_cannot_see_or_upgrade_components(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    application = create_app(Settings(db_path=tmp_path / "twin.db"))
    monkeypatch.setattr(
        application.state.auth,
        "identity",
        lambda email: {"email": "member@example.com", "admin": False, "auth_enabled": False},
    )
    with TestClient(application, base_url="http://localhost", headers=CSRF) as client:
        assert client.get("/api/admin/system/components").status_code == 403
        assert client.post("/api/admin/system/components/kernel").status_code == 403
        assert client.put("/api/admin/system/params/library.max_pending", json={"value": 2}).status_code == 403


def test_admin_names_the_team_for_the_sidebar_and_the_sign_in_page(tmp_path: Path) -> None:
    client = client_for(Settings(db_path=tmp_path / "twin.db"))
    assert client.get("/api/admin/system").json()["team_name"] is None
    assert client.get("/api/whoami").json()["team_name"] is None
    assert client.get("/api/auth/methods").json()["team_name"] is None
    body = client.put("/api/admin/system/team", json={"name": "  产品  研发部 "}, headers=CSRF).json()
    assert body["team_name"] == "产品 研发部"
    assert client.get("/api/whoami").json()["team_name"] == "产品 研发部"
    assert client.get("/api/auth/methods").json()["team_name"] == "产品 研发部"
    system: SystemSettings = client.app.state.system
    assert system.audit()[0] | {"at": None} == {
        "at": None,
        "by": None,
        "action": "team_name",
        "name": [None, "产品 研发部"],
    }
    # Kept across a restart, and private like the rest of system.json.
    assert SystemSettings(Settings(db_path=tmp_path / "twin.db")).team_name() == "产品 研发部"
    assert stat.S_IMODE((tmp_path / "system.json").stat().st_mode) == 0o600
    for bad in ("一二三四五六七八九十一二三四五六七八九十一", "有\x07控制"):
        refused = client.put("/api/admin/system/team", json={"name": bad}, headers=CSRF)
        assert refused.status_code == 400, bad
    assert client.get("/api/whoami").json()["team_name"] == "产品 研发部"
    assert client.put("/api/admin/system/team", json={}, headers=CSRF).json()["team_name"] is None
    assert client.get("/api/auth/methods").json()["team_name"] is None
