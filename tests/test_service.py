from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from twin.api import create_api
from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.mcp_server import TwinTools
from twin.media.schema import EXPLICIT_LABEL
from twin.persona.chat import PersonaChat, index_persona
from twin.persona.items import PersonaItem, PEvidence
from twin.persona.schema import EvidenceClass, SourceKind
from twin.persona.sources import parse_chat
from twin.persona.store import PersonaStore
from twin.service import ServiceAnswer, answer_question


@pytest.fixture
def grounded_chat() -> Iterator[tuple[PersonaChat, list[str]]]:
    settings = Settings(target_name="张三")
    with PersonaStore(":memory:") as store:
        store.put_source(
            parse_chat(
                "群.txt",
                "2025-01-01 10:00 李四：怎么看？\n"
                "2025-01-01 10:01 张三：我与李四先核实证据\n"
                "2025-02-01 10:00 张三：我与李四再检查新资料\n",
                settings,
            )
        )
        own = store.list_expressions(target_only=True)
        item = PersonaItem(
            item_id="pi_service",
            facet_id="2.1",
            statement="他优先核实证据",
            evidence=[
                PEvidence(
                    expression_id=e.expression_id,
                    source_id=e.source_id,
                    source_kind=SourceKind.CHAT,
                    evidence_class=EvidenceClass.BEHAVIOR,
                    date=e.date,
                    quote=e.text,
                )
                for e in own
            ],
        )
        store.replace_facet_items("2.1", [item])
        refs = [item.item_id, *(e.expression_id for e in own)]
        llm = FakeLLM(
            lambda *args: {
                "reply": "先核实证据。",
                "citations": refs,
                "confidence": 0.9,
                "abstain": False,
                "topic_facets": ["2.1"],
            }
        )
        embedder = HashingEmbedder()
        index_persona(store, embedder, settings)
        yield PersonaChat(store, llm, embedder, settings), refs


def test_resolves_privacy_view_citations_and_label(grounded_chat: tuple[PersonaChat, list[str]]) -> None:
    chat, refs = grounded_chat
    answer = answer_question(chat, "怎么做？", None)
    assert answer.answer == "先核实证据。" and answer.confidence == 0.9
    assert answer.schema_version == 1 and answer.label == EXPLICIT_LABEL and answer.mode == "grounded"
    assert answer.persona_name == "张三" and answer.generated_at.utcoffset() == dt.timedelta(0)
    assert [c.ref_id for c in answer.citations] == refs
    assert [c.kind for c in answer.citations] == ["item", "expression", "expression"]
    assert answer.citations[0].quote == answer.citations[-1].quote
    assert all("李四" not in c.quote and "他人" in c.quote for c in answer.citations)
    assert all(c.source_kind == "chat" for c in answer.citations)
    assert chat.store.chat_demand() == {}
    with pytest.raises(ValidationError):
        answer.answer = "changed"
    with pytest.raises(ValidationError):
        answer.citations[0].quote = "changed"
    assert ServiceAnswer.model_validate_json(answer.model_dump_json()) == answer


def test_as_of_filters_future_and_undated_evidence(grounded_chat: tuple[PersonaChat, list[str]]) -> None:
    chat, refs = grounded_chat
    item = chat.store.list_items()[0]
    chat.store.replace_facet_items(
        item.facet_id,
        [item.model_copy(update={"evidence": [*item.evidence, item.evidence[-1].model_copy(update={"date": None})]})],
    )
    horizon = dt.date(2025, 1, 1)
    answer = answer_question(chat, "怎么做？", horizon)
    assert answer.as_of == horizon
    assert [c.ref_id for c in answer.citations] == refs[:2]
    assert answer.citations[0].quote == answer.citations[1].quote
    assert all(c.date == horizon for c in answer.citations)
    assert "新资料" not in answer.model_dump_json()
    assert answer_question(chat, "怎么做？", dt.date(2024, 12, 31)).citations == []


def test_abstention_passthrough(grounded_chat: tuple[PersonaChat, list[str]]) -> None:
    chat, _ = grounded_chat
    draft: dict[str, Any] = {
        "reply": "需要本人确认。",
        "citations": [],
        "confidence": 0.2,
        "abstain": True,
        "abstain_reason": "资料中没有依据",
    }
    chat.llm = FakeLLM(lambda *args: draft)
    answer = answer_question(chat, "未知问题", None)
    assert answer.abstain and answer.abstain_reason == draft["abstain_reason"] and answer.mode == "abstain"
    assert answer.answer == draft["reply"] and answer.confidence == 0.2 and not answer.citations
    assert chat.store.chat_demand() == {}


def test_general_mode_passthrough(grounded_chat: tuple[PersonaChat, list[str]]) -> None:
    chat, _ = grounded_chat
    chat.llm = FakeLLM(
        lambda *args: {
            "reply": "这不是我本人的经验，一般来说先做预算。",
            "mode": "general",
            "confidence": 0.9,
            "citations": [],
        }
    )
    answer = answer_question(chat, "如何做预算？", None)
    assert answer.mode == "general" and not answer.abstain and not answer.abstain_reason
    assert answer.confidence == 0.5 and not answer.citations
    assert ServiceAnswer.model_validate_json(answer.model_dump_json()) == answer
    assert chat.store.chat_demand() == {}


def test_question_limit_before_model_call(grounded_chat: tuple[PersonaChat, list[str]]) -> None:
    chat, _ = grounded_chat
    assert isinstance(chat.llm, FakeLLM)
    with pytest.raises(ValueError, match="问题不能超过 2000") as exc:
        answer_question(chat, "私" * 2001, None)
    assert "私" not in str(exc.value) and not chat.llm.calls
    answer_question(chat, "问" * 2000, None)
    assert len(chat.llm.calls) == 1


def test_api_and_mcp_share_evidence_backed_answer(
    grounded_chat: tuple[PersonaChat, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    chat, _ = grounded_chat
    token = secrets.token_urlsafe(32)
    monkeypatch.setenv("TWIN_API_TOKEN", token)
    horizon = dt.date(2025, 1, 1)
    expected = answer_question(chat, "怎么做？", horizon)
    with TestClient(create_api(chat.settings, lambda: chat), base_url="http://localhost") as client:
        response = client.post(
            "/v1/ask",
            json={"question": "怎么做？", "as_of": horizon.isoformat()},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    http_answer = ServiceAnswer.model_validate(response.json())
    mcp_answer = ServiceAnswer.model_validate(
        TwinTools(chat.settings, lambda: chat).ask_twin("怎么做？", horizon.isoformat()).structuredContent
    )
    for answer in (http_answer, mcp_answer):
        assert answer.model_dump(exclude={"generated_at"}) == expected.model_dump(exclude={"generated_at"})
        assert answer.citations and "李四" not in answer.model_dump_json()
    assert chat.store.chat_demand() == {}
