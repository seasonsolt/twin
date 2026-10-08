"""Identity persistence, speaker aliases and old media label compatibility."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.schema import AVATAR_PRESETS, AvatarSpec, MediaManifest, MediaScript
from twin.persona.chat import PersonaChat
from twin.persona.schema import ChatTurn
from twin.persona.sources import parse_chat, parse_note
from twin.persona.store import PersonaStore
from twin.service import ServiceAnswer, ServiceIdentity, answer_question, public_identity
from twin.web import create_app
from twin.web.jobs import PersonaProcessing


@pytest.mark.parametrize("label", ["AI 合成 · 模拟推演，不代表本人意见", "AI 合成，不代表本人意见", "other"])
def test_legacy_labels_are_ignored(label: str) -> None:
    records = [
        (MediaManifest, {"source_fingerprint": "test", "created_at": "2025-01-01T00:00:00Z"}),
        (ServiceIdentity, {"name": "测试", "avatar": None, "voice": None}),
        (AvatarSpec, AVATAR_PRESETS["chestnut"].model_dump()),
        (
            MediaScript,
            {
                "source_kind": "chat_reply",
                "source_fingerprint": "test",
                "persona_name": "测试",
                "as_of": None,
                "confidence": 0.8,
                "abstain": False,
                "segments": [],
                "citations": [],
            },
        ),
        (
            ServiceAnswer,
            {
                "answer": "测试。",
                "abstain": False,
                "abstain_reason": "",
                "confidence": 0.8,
                "citations": [],
                "as_of": None,
                "persona_name": "测试",
                "generated_at": "2025-01-01T00:00:00Z",
            },
        ),
    ]
    for model, data in records:
        field = "explicit_label" if model is MediaScript else "label"
        record = model.model_validate({**data, field: label})
        assert field not in record.model_dump()
        assert model.model_validate_json(record.model_dump_json()) == record


def test_identity_persistence_replacement_and_alias(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    queue = Mock()
    monkeypatch.setattr(PersonaProcessing, "queue", queue)
    settings = Settings(db_path=tmp_path / "twin.db", target_name="配置名字", target_aliases=["旧别名"])
    app = create_app(settings)
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get("/api/identity").json()["name_source"] == "config"
        assert client.put("/api/identity", json={"name": "新名字", "about": "喜欢散步"}).status_code == 403
        headers = {"X-Twin": "1"}
        data = client.put("/api/identity", json={"name": "新名字", "about": "喜欢散步"}, headers=headers).json()
        assert data["name"] == "新名字"
        assert data["about"] == "喜欢散步"
        assert data["name_source"] == "user"
        assert queue.call_count == 1
        with PersonaStore(settings.db_path) as store:
            original = store.list_sources()[0]
            assert original.title == "自我介绍"
            assert store.list_expressions()[0].text == "喜欢散步"
            assert store.list_expressions()[0].speaker == "新名字"
        client.put("/api/identity", json={"name": "新名字", "about": "喜欢散步"}, headers=headers)
        assert queue.call_count == 1
        client.put("/api/identity", json={"name": "新名字", "about": "喜欢做饭"}, headers=headers)
        assert queue.call_count == 2
        with PersonaStore(settings.db_path) as store:
            assert len(store.list_sources()) == 1
            assert store.get_source(original.source_id) is None
            assert store.list_expressions()[0].text == "喜欢做饭"
        status = client.get("/api/status").json()
        assert status["target_name"] == "新名字"
    assert settings.target_name == "配置名字"
    assert public_identity(settings).name == "新名字"
    for name in ("新名字", "配置名字", "旧别名"):
        parsed = parse_chat("chat.txt", f"2025-01-01 {name}：我喜欢散步", settings)
        assert parsed.expressions[0].is_target
        assert parsed.expressions[0].speaker == name
    with TestClient(create_app(settings), base_url="http://localhost") as client:
        assert client.get("/api/identity").json()["about"] == "喜欢做饭"
        client.put("/api/identity", json={"name": "新名字", "about": ""}, headers={"X-Twin": "1"})
    with PersonaStore(settings.db_path) as store:
        assert not store.list_sources()
        assert store.get_meta("identity:name") == "新名字"
        assert store.get_meta("identity:about") == ""


def test_chat_prompt_and_service_use_saved_name(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="配置名字")
    handler = Mock(
        return_value={"reply": "一般来说可以先做预算。", "mode": "general", "confidence": 0.5, "citations": []}
    )
    with PersonaStore(settings.db_path) as store:
        store.set_meta("identity:name", "用户名字")
        chat = PersonaChat(store, FakeLLM(handler), HashingEmbedder(), settings)
        answer = answer_question(chat, "怎么做预算？", None)
        assert "用户名字" in handler.call_args.args[0]
        assert answer.persona_name == "用户名字"
        store.set_meta("identity:name", "改后的名字")
        chat.reply([ChatTurn(role="user", content="怎么做预算？")], persist=False)
        assert "改后的名字" in handler.call_args.args[0]


def test_identity_and_note_replace_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(db_path=tmp_path / "twin.db", target_name="旧名字")
    original = parse_note("喜欢散步", settings, "自我介绍")
    with PersonaStore(settings.db_path) as store:
        store.set_identity("旧名字", "喜欢散步", original)
        monkeypatch.setattr(store, "put_source", Mock(side_effect=RuntimeError("写入失败")))
        with pytest.raises(RuntimeError, match="写入失败"):
            store.set_identity("新名字", "喜欢做饭", parse_note("喜欢做饭", settings, "自我介绍"))
        assert store.get_meta("identity:name") == "旧名字"
        assert store.get_meta("identity:about") == "喜欢散步"
        assert store.get_source(original.source.source_id) == original.source
        assert store.list_expressions()[0].text == "喜欢散步"


@pytest.mark.parametrize("name,about", [("", ""), ("  ", ""), ("字" * 21, ""), ("名字", "字" * 201)])
def test_identity_validation(tmp_path: Path, name: str, about: str) -> None:
    with TestClient(create_app(Settings(db_path=tmp_path / "twin.db")), base_url="http://localhost") as client:
        response = client.put("/api/identity", json={"name": name, "about": about}, headers={"X-Twin": "1"})
        assert response.status_code == 400
        assert not (tmp_path / "twin.db").exists()
