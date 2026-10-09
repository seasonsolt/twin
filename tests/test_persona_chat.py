from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM, OpenAICompatLLM
from twin.persona import chat as pc
from twin.persona import profile as pf
from twin.persona.items import PersonaItem, PEvidence, PReview
from twin.persona.schema import ChatDraft, ChatReply, ChatTurn, EvidenceClass, Expression, ReviewStatus, SourceKind
from twin.persona.sources import parse_chat, parse_questionnaire
from twin.persona.store import PersonaStore

D = dt.date

QUESTIONNAIRE = """**4. 排序。**　*偏好 · 2.1*

回答：结果第一，钱进了账户才算数。

**13.大单第一句？**　*情境 · 3.4*

回答：首付多少？
"""

CHAT = """2026-09-01 10:02 李四：这单签了，首付 10%
2026-09-01 10:05 张三：首付不到 30% 不开工，说白了钱进了账户才叫收入
2026-09-20 09:00 李四：数据看着不错
2026-09-20 09:01 张三：我就问一句，对照组是谁挑的？
"""


def extract_handler(system: str, user: str, schema: type[BaseModel]) -> dict[str, Any]:
    entries = {int(n): t for n, t in re.findall(r"\[(\d+)\][^\n]*\n(?:语境：[^\n]*\n)?本人：([^\n]*)", user)}
    items = []
    for n, text in entries.items():
        if "钱进了账户" in text:
            items.append(
                {"facet_id": "2.1", "statement": "他把回款放第一", "quotes": [{"n": n, "quote": "钱进了账户"}]}
            )
        if "对照组" in text:
            items.append(
                {"facet_id": "4.2", "statement": "他追问对照组", "quotes": [{"n": n, "quote": "对照组是谁挑的"}]}
            )
    if schema is pf.MergeDraft:
        ids = re.findall(r"\[(pc_[0-9a-f]+)\]", user)
        return {"items": [{"statement": "他认为钱进了账户才算收入", "candidate_ids": ids}]}
    return {"items": items}


@pytest.fixture
def settings() -> Settings:
    return Settings(target_name="张三", max_workers=2)


@pytest.fixture
def store(settings: Settings) -> PersonaStore:
    s = PersonaStore(":memory:")
    s.put_source(parse_questionnaire("q_2026-08-30.md", QUESTIONNAIRE, settings))
    s.put_source(parse_chat("群.txt", CHAT, settings))
    pf.build_profile(s, FakeLLM(extract_handler), settings)
    return s


@pytest.mark.parametrize("contract", [ChatDraft, ChatReply])
@pytest.mark.parametrize("mode", ["grounded", "general", "inferred", "abstain"])
def test_chat_modes_and_legacy_compatibility(contract: type[ChatDraft] | type[ChatReply], mode: str) -> None:
    data = {"reply": "测试回答", "citations": [], "confidence": 0.9, "abstain_reason": "", "retrieved_ids": []}
    answer = contract.model_validate({**data, "mode": mode})
    assert answer.mode == mode and answer.abstain == (mode == "abstain")
    assert contract.model_validate_json(answer.model_dump_json()) == answer
    if isinstance(answer, ChatReply):
        assert answer.quotes_removed == 0
        assert contract.model_validate({**data, "mode": mode, "quotes_removed": 2}).quotes_removed == 2
        if mode in ("general", "inferred"):
            assert answer.confidence == 0.5
    for abstain in (True, False):
        legacy = contract.model_validate({**data, "abstain": abstain})
        assert legacy.mode == ("abstain" if abstain else "grounded")
    with pytest.raises(ValidationError, match="abstain must match mode"):
        contract.model_validate({**data, "mode": mode, "abstain": mode != "abstain"})
    with pytest.raises(ValidationError):
        contract.model_validate({**data, "mode": "unknown"})


@pytest.mark.parametrize("extract_effort", [None, "high"])
def test_chat_keeps_instance_reasoning_effort_without_extraction_override(
    store: PersonaStore, settings: Settings, monkeypatch: pytest.MonkeyPatch, extract_effort: Any
) -> None:
    settings.llm.reasoning_effort = "none"
    settings.llm.reasoning_effort_extract = extract_effort
    requests: list[dict[str, Any]] = []
    options: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        requests.append(kwargs)
        content = json.dumps({"reply": "资料里没有记录。", "citations": [], "confidence": 0.2, "abstain": True})
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=content))]
        )

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    llm = OpenAICompatLLM("m", client=client, reasoning_effort=settings.llm.reasoning_effort)
    original = llm.structured

    def structured(**kwargs: Any) -> BaseModel:
        options.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(llm, "structured", structured)
    chat = pc.PersonaChat(store, llm, HashingEmbedder(), settings)
    assert chat.reply([ChatTurn(role="user", content="我选择什么？")], persist=False).abstain
    assert len(requests) == len(options) == 1
    assert "reasoning_effort" not in options[0]
    assert requests[0]["reasoning_effort"] == "none"


def test_prompt_quotation_and_general_rules(store: PersonaStore, settings: Settings) -> None:
    ctx = pc.PersonaChat(store, FakeLLM(lambda *a: {}), HashingEmbedder(), settings).retrieve("问题")
    prompt = pc.chat_system_prompt(settings.target_name, ctx)
    assert '引号（「」『』“”""）只能包住逐字出现在【说话样本】或【检索资料】中的文字' in prompt
    assert "强调、转述或术语不要加引号" in prompt and "绝不能把转述当作本人的原话" in prompt
    assert "开头用一句简短的话说明这是通用知识、不是本人观点" in prompt
    assert "mode 设为 general" in prompt and "citations 可以为空" in prompt
    assert "confidence 不超过 0.5" in prompt
    assert "citations 填你用到的资料编号（方括号里的原样复制，如 pi_1a2b3c4d5e6f）" in prompt
    assert '标了"本人已确认"的条目最可靠，优先依据它们' in prompt
    assert "最多 2 个；寒暄等不涉及任何细项时为空列表" in prompt
    output_format = prompt.split("## 输出格式\n", 1)[1].split("## 核心画像", 1)[0]
    assert "少量使用 Markdown" in output_format
    assert "日常聊天保持自然的简短段落，最多加粗一两个关键词" in output_format
    assert "步骤或选项用列表" in output_format
    assert "只有真正的并列对比才用表格" in output_format
    assert "代码块只用于代码或命令" in output_format
    assert "标题不得高于四级（####），通常不用标题" in output_format
    assert "绝不使用 HTML" in output_format
    assert "<<<META>>>" in pc.STREAM_FORMAT
    assert "不要用 JSON 或代码块包裹整篇回复" in pc.STREAM_FORMAT


def test_prompt_ordered_mode_checklist_and_style() -> None:
    prompt = pc.chat_system_prompt("测试本人", pc.PersonaContext([], [], [], []))
    checklist = prompt.split("## 写回复前，按顺序检查", 1)[1].split("## 整体 mode 与弃权", 1)[0]
    personal, restricted, general = (checklist.index(f"{n}. ") for n in (1, 2, 3))
    assert personal < restricted < general
    assert "只在内部判断，不输出检查过程" in checklist
    assert "只查【核心画像】和【检索资料】" in checklist[personal:restricted]
    assert "不确定资料是否包含某个个人事实，就按没有覆盖处理" in checklist
    assert "不能把个人问题改成通用回答来掩盖缺失" in checklist
    assert "即使有相关资料，也只对这部分说明需要本人确认" in checklist[restricted:general]
    assert "评价某个具体的他人" in checklist[restricted:general]
    assert "其余能回答的部分继续回答" in checklist[restricted:general]
    assert "通用知识、方法、一般话题的看法" in checklist[general:]
    assert "充分帮助，给出判断、理由或可执行步骤" in checklist[general:]
    assert "不能因档案没有相关内容就说得问本人" in checklist[general:]
    assert "不编造个人事实、数字、人名、日期、事件或生活细节" in prompt
    assert "不用常识补齐个人信息" in prompt
    assert "模仿句子长短、用词、口头禅和直接程度，用第一人称" in prompt
    assert "不要用助手腔（作为一个……、希望对你有帮助）" in prompt
    assert "寒暄和简单问题一两句" in prompt
    assert "把判断、理由和具体做法说完整" in prompt


def test_prompt_substantive_answers_are_not_abstentions() -> None:
    prompt = pc.chat_system_prompt("测试本人", pc.PersonaContext([], [], [], []))
    modes = prompt.split("## 整体 mode 与弃权\n", 1)[1].split("## 规则", 1)[0]
    assert "有资料依据的实质回答 mode 设为 grounded" in modes
    assert (
        "通用实质回答 mode 设为 general，按间接依据的推测设为 inferred；三者 abstain 都为 false，abstain_reason 为空"
        in modes
    )
    assert "混合请求按实质回答部分选择 mode" in modes
    assert "只有没有实质回答、只能说明无资料或需要本人确认时，mode 设为 abstain，abstain 为 true" in modes
    assert "具体得我本人定或细节得由我本人来定，不算弃权" in modes
    assert "mode 保持 grounded/general，abstain=false" in modes
    assert "不要为了避免弃权而给个人问题编造答案" in modes


@pytest.mark.parametrize("cited", [True, False])
def test_general_reply_confidence_and_demand(store: PersonaStore, settings: Settings, cited: bool) -> None:
    item_id = store.list_items("2.1")[0].item_id
    llm = FakeLLM(
        lambda *a: {
            "reply": "这不是我本人的经验，一般来说先列预算。",
            "mode": "general",
            "citations": [item_id] if cited else [],
            "confidence": 0.9,
            "topic_facets": ["2.1"],
            "abstain_reason": "不应保留",
        }
    )
    chat = pc.PersonaChat(store, llm, HashingEmbedder(), settings)
    reply = chat.reply([ChatTurn(role="user", content="如何做预算？")])
    assert reply.mode == "general" and not reply.abstain and not reply.abstain_reason
    assert reply.confidence == 0.5 and reply.topic_facets == ["2.1"]
    entry = json.loads(store._db.execute("SELECT json FROM p_chat_log").fetchone()[0])
    assert entry["mode"] == "general" and entry["abstain"] is False
    assert store.chat_demand() == {}
    # Legacy logs have no mode and still contribute demand.
    with store._tx() as db:
        db.execute(
            "INSERT INTO p_chat_log (at, abstain, json) VALUES (?, ?, ?)",
            ("2026-01-01", 1, json.dumps({"abstain": True, "topic_facets": ["2.1"]})),
        )
    assert store.chat_demand() == {"2.1": (1, 1)}


def own_words_id(chat: pc.PersonaChat, question: str) -> str:
    pc.index_persona(chat.store, chat.embedder, chat.settings)
    return next(e.expression_id for e, _ in chat.retrieve(question).expressions if e.is_target)


@pytest.mark.parametrize("answered", [True, False])
def test_reply_that_misses_the_asked_item_is_finalized_as_abstain(
    store: PersonaStore, settings: Settings, answered: bool
) -> None:
    question = "Which store did I redeem the coupon at?"
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), HashingEmbedder(), settings)
    cited = own_words_id(chat, question)
    draft = {
        "asked": "the store where the coupon was redeemed",
        "reply": "我是在邮箱里兑换的那张优惠券。",
        "citations": [cited],
        "confidence": 0.99,
        "mode": "grounded",
        "answered": answered,
    }
    chat.llm = FakeLLM(lambda *a: draft)
    reply = chat.reply([ChatTurn(role="user", content=question)])
    assert reply.reply == draft["reply"] and reply.citations == [cited]
    if answered:
        assert (reply.mode, reply.abstain, reply.confidence, reply.abstain_reason) == ("grounded", False, 0.99, "")
    else:
        assert (reply.mode, reply.abstain, reply.confidence) == ("abstain", True, pc.UNCITED_CONFIDENCE_CAP)
        assert "the store where the coupon was redeemed" in reply.abstain_reason
    entry = json.loads(store._db.execute("SELECT json FROM p_chat_log").fetchone()[0])
    assert entry["abstain"] is not answered and entry["mode"] == reply.mode
    assert ChatReply.model_validate_json(reply.model_dump_json()) == reply


def test_missed_item_keeps_model_reason_and_leaves_other_modes_alone(store: PersonaStore, settings: Settings) -> None:
    drafts = iter(
        [
            {
                "reply": "没记这个。",
                "citations": [],
                "confidence": 0.9,
                "answered": False,
                "abstain_reason": "资料没有店名",
            },
            {"reply": "一般来说先列预算。", "citations": [], "mode": "general", "confidence": 0.9, "answered": False},
        ]
    )
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: next(drafts)), HashingEmbedder(), settings)
    ask = [ChatTurn(role="user", content="哪家店？")]
    missed, general = chat.reply(ask, persist=False), chat.reply(ask, persist=False)
    assert missed.abstain and missed.mode == "abstain" and missed.abstain_reason == "资料没有店名"
    assert general.mode == "general" and not general.abstain and general.confidence == 0.5


def test_streamed_reply_that_misses_the_asked_item_is_abstained(store: PersonaStore, settings: Settings) -> None:
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), HashingEmbedder(), settings)
    cited = own_words_id(chat, "哪家店？")
    meta = {"asked": "店名", "answered": False, "citations": [cited], "confidence": 0.95, "mode": "grounded"}

    class Streaming(FakeLLM):
        async def stream(self, **kwargs: Any) -> Any:
            assert "asked" in kwargs["system"] and "answered" in kwargs["system"]
            yield "我是在邮箱里兑换的。\n<<<META>>>\n" + json.dumps(meta, ensure_ascii=False)

    chat.llm = Streaming(lambda *a: {})

    async def run() -> list[Any]:
        return [x async for x in chat.stream_reply([ChatTurn(role="user", content="哪家店？")], persist=False)]

    final = asyncio.run(run())[-1]
    assert isinstance(final, ChatReply)
    assert (final.mode, final.abstain, final.confidence) == ("abstain", True, pc.UNCITED_CONFIDENCE_CAP)


def test_prompt_inference_branch_sits_in_the_personal_step_before_abstaining() -> None:
    prompt = pc.chat_system_prompt("测试本人", pc.PersonaContext([], [], [], []))
    checklist = prompt.split("## 写回复前，按顺序检查", 1)[1].split("## 整体 mode 与弃权", 1)[0]
    personal, restricted = checklist.index("1. "), checklist.index("2. ")
    step = checklist[personal:restricted]
    infer, abstain = step.index("归为 inferred"), step.index("就用本人的口吻简短说明资料里没记这件事")
    assert infer < abstain
    assert "发生过什么、在哪、何时、谁，以及本人生活里的事实数字（几个孩子、收入、日期、实付价格）才是事实回忆" in step
    assert "本人会给出的个人估计（认为多少比例的人支持、可能性有多大、会做几次" in step
    assert step.index("个人估计") < infer
    assert "没有相关的间接依据，或问的是事实回忆" in step
    modes = prompt.split("## 整体 mode 与弃权\n", 1)[1].split("## 规则", 1)[0]
    assert "我没直接说过，但按我……，大概会……" in modes
    assert "不把推测说成我说过或做过的事，不编造经历" in modes
    assert "citations 至少填一条用到的间接资料，没有就改为 abstain" in modes
    assert "confidence 不超过 0.5" in modes
    assert "对方限定了输出格式时，只按输出格式一节的规则给出该值，推测的身份由 mode 标明" in modes
    assert "inferred 或 abstain" in pc.STREAM_FORMAT


def test_prompt_format_constraint_forbids_prefixed_commentary_in_every_substantive_mode() -> None:
    prompt = pc.chat_system_prompt("测试本人", pc.PersonaContext([], [], [], []))
    fmt = prompt.split("## 输出格式\n", 1)[1].split("少量使用 Markdown", 1)[0]
    assert "只回选项标签、只回一个数字" in fmt
    assert "无论 mode 是 grounded、general 还是 inferred" in fmt
    assert "正文都恰好是该标签或数字，不加前缀、单位、解释，也不加说明通用知识或推测的句子" in fmt
    assert "回答的身份由 mode 标明" in fmt
    assert "对方限定了输出格式时除外，见输出格式" in prompt


INFERENCE: dict[str, Any] = {
    "asked": "遇到延期项目会选哪个选项",
    "reply": "我没直接说过，但按我一贯不开工的原则，大概会选 B。",
    "confidence": 0.95,
    "mode": "inferred",
    "topic_facets": ["2.1"],
    "abstain_reason": "不应保留",
}


def test_inferred_reply_with_citation_is_capped_and_logged(store: PersonaStore, settings: Settings) -> None:
    item_id = store.list_items("2.1")[0].item_id
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {**INFERENCE, "citations": [item_id]}), HashingEmbedder(), settings)
    reply = chat.reply([ChatTurn(role="user", content="如果项目延期你会选哪个？")])
    assert (reply.mode, reply.abstain, reply.abstain_reason) == ("inferred", False, "")
    assert reply.confidence == pc.INFERRED_CONFIDENCE_CAP == 0.5 and reply.citations == [item_id]
    assert reply.reply == INFERENCE["reply"]
    entry = json.loads(store._db.execute("SELECT json FROM p_chat_log").fetchone()[0])
    assert entry["mode"] == "inferred" and entry["abstain"] is False
    assert ChatReply.model_validate_json(reply.model_dump_json()) == reply
    # No direct evidence existed, so the question counts as asked and as a gap.
    assert store.chat_demand() == {"2.1": (1, 1)}


@pytest.mark.parametrize("citations", [[], ["pi_unknown"]])
def test_inferred_reply_without_a_valid_citation_abstains(
    store: PersonaStore, settings: Settings, citations: list[str]
) -> None:
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {**INFERENCE, "citations": citations}), HashingEmbedder(), settings)
    reply = chat.reply([ChatTurn(role="user", content="如果项目延期你会选哪个？")], persist=False)
    assert (reply.mode, reply.abstain, reply.citations) == ("abstain", True, [])
    assert reply.confidence == pc.UNCITED_CONFIDENCE_CAP and reply.abstain_reason == "不应保留"
    bare = {k: v for k, v in INFERENCE.items() if k != "abstain_reason"}
    chat.llm = FakeLLM(lambda *a: {**bare, "citations": citations})
    reply = chat.reply([ChatTurn(role="user", content="如果项目延期你会选哪个？")], persist=False)
    assert reply.abstain and "不做推测" in reply.abstain_reason


def test_inferred_reply_that_misses_the_asked_item_abstains(store: PersonaStore, settings: Settings) -> None:
    item_id = store.list_items("2.1")[0].item_id
    draft = {**INFERENCE, "citations": [item_id], "answered": False}
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {**draft, "abstain_reason": ""}), HashingEmbedder(), settings)
    reply = chat.reply([ChatTurn(role="user", content="如果项目延期你会选哪个？")], persist=False)
    assert (reply.mode, reply.abstain, reply.confidence) == ("abstain", True, pc.UNCITED_CONFIDENCE_CAP)
    assert INFERENCE["asked"] in reply.abstain_reason


def test_streamed_inferred_reply_matches_the_blocking_path(store: PersonaStore, settings: Settings) -> None:
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), HashingEmbedder(), settings)
    cited = own_words_id(chat, "如果项目延期你会选哪个？")
    meta = {k: v for k, v in INFERENCE.items() if k not in ("reply", "abstain_reason")} | {"citations": [cited]}

    class Streaming(FakeLLM):
        async def stream(self, **kwargs: Any) -> Any:
            assert "inferred" in kwargs["system"]
            yield INFERENCE["reply"] + "\n<<<META>>>\n" + json.dumps(meta, ensure_ascii=False)

    question = [ChatTurn(role="user", content="如果项目延期你会选哪个？")]
    draft = {**INFERENCE, "citations": [cited], "abstain_reason": ""}
    blocking = pc.PersonaChat(store, FakeLLM(lambda *a: draft), HashingEmbedder(), settings).reply(
        question, persist=False
    )
    chat.llm = Streaming(lambda *a: {})

    async def run(citations: list[str]) -> ChatReply:
        meta["citations"] = citations
        final = [x async for x in chat.stream_reply(question, persist=False)][-1]
        assert isinstance(final, ChatReply)
        return final

    streamed = asyncio.run(run([cited]))
    assert streamed == blocking and streamed.mode == "inferred" and streamed.confidence == 0.5
    uncited = asyncio.run(run([]))
    assert (uncited.mode, uncited.abstain, uncited.confidence) == ("abstain", True, pc.UNCITED_CONFIDENCE_CAP)


def test_reply_language_follows_the_asker(store: PersonaStore, settings: Settings) -> None:
    ctx = pc.PersonaChat(store, FakeLLM(lambda *a: {}), HashingEmbedder(), settings).retrieve("问题")
    prompt = pc.chat_system_prompt(settings.target_name, ctx)
    rules = prompt.split("## 规则\n", 1)[1].split("## 输出格式", 1)[0]
    assert "7. 回复语言跟随对方最后一句话" in rules
    assert "对方用英文，整段回复（包括说明是通用知识、没有记录或需要本人确认的句子）都用英文" in rules
    assert "对方用中文就用中文" in rules and "引用的原话保持原文逐字，不翻译、不改写" in rules
    for text in ("Which store did I redeem the coupon at?", "你怎么看签大单？"):
        user = pc.chat_user_message([ChatTurn(role="user", content=text)], ctx)
        assert user.endswith(f"对方：{text}\n\n请回复对方的最后一句话，语言与这句话一致。")


def test_english_reply_keeps_verbatim_chinese_quotes(store: PersonaStore, settings: Settings) -> None:
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), HashingEmbedder(), settings)
    cited = own_words_id(chat, "钱进了账户")
    reply_text = "I put it as 「钱进了账户」, and I never said “revenue is whatever you invoice”."
    chat.llm = FakeLLM(lambda *a: {"reply": reply_text, "citations": [cited], "confidence": 0.8})
    reply = chat.reply([ChatTurn(role="user", content="How do you define income?")], persist=False)
    assert reply.reply == "I put it as 「钱进了账户」, and I never said revenue is whatever you invoice."
    assert reply.quotes_removed == 1 and not reply.abstain


def test_index_is_incremental_and_follows_the_embedding_space(store: PersonaStore, settings: Settings) -> None:
    embedder = HashingEmbedder()
    first = pc.index_persona(store, embedder, settings)
    assert first == {
        "items": 2,
        "expressions": 4,
    }  # two questionnaire answers and two chat messages
    assert pc.index_persona(store, embedder, settings) == {"items": 0, "expressions": 0}
    other = HashingEmbedder(dim=256)
    assert pc.index_persona(store, other, settings) == {"items": 2, "expressions": 4}
    assert store.get_vectors("items")[1].shape == (2, 256)


def test_retrieve_respects_as_of(store: PersonaStore, settings: Settings) -> None:
    embedder = HashingEmbedder()
    pc.index_persona(store, embedder, settings)
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: {}), embedder, settings)
    ctx = chat.retrieve("对照组和数据", as_of=D(2026, 9, 10))
    texts = [e.text for e, _ in ctx.expressions]
    assert all("对照组" not in t for t in texts)  # said on 09-20, after as_of
    assert {i.facet_id for i, _ in ctx.items} | {i.facet_id for i in ctx.core} == {"2.1"}
    assert ctx.voice == ["首付不到 30% 不开工，说白了钱进了账户才叫收入"]  # chat words only
    full = chat.retrieve("对照组")
    assert any("对照组" in e.text for e, _ in full.expressions) and len(full.voice) == 2


def test_reply_filters_citations_and_caps_confidence(store: PersonaStore, settings: Settings) -> None:
    embedder = HashingEmbedder()
    pc.index_persona(store, embedder, settings)
    item_id = store.list_items("2.1")[0].item_id
    cite = {"reply": "钱到账才算。", "citations": [f"[{item_id}]", "pi_fake"], "confidence": 0.9, "abstain": False}
    answers = iter(
        [
            {**cite, "topic_facets": ["2.1", "x.9"]},
            {
                "reply": "这个我没想过。",
                "citations": [],
                "confidence": 0.8,
                "abstain": True,
                "abstain_reason": "无依据",
                "topic_facets": ["9.4"],
            },
            cite,
        ]
    )
    llm = FakeLLM(lambda s, u, schema: next(answers))
    chat = pc.PersonaChat(store, llm, embedder, settings)
    history = [ChatTurn(role="user", content="你怎么看签大单？")]
    first = chat.reply(history)
    assert first.citations == [item_id] and first.confidence == 0.6  # rests on an unreviewed item only
    assert first.topic_facets == ["2.1"] and not first.abstain
    _, system, user = llm.calls[0]
    assert "张三的数字分身" in system and "说白了钱进了账户才叫收入" in system  # voice sample
    assert "2.1 核心价值排序；" in system and "；本人已确认" not in system
    assert user.endswith("对方：你怎么看签大单？\n\n请回复对方的最后一句话，语言与这句话一致。")
    history += [ChatTurn(role="twin", content=first.reply), ChatTurn(role="user", content="你喜欢什么运动？")]
    second = chat.reply(history, as_of=D(2026, 9, 30))
    assert second.abstain and second.confidence == 0.3 and second.abstain_reason == "无依据"
    assert "你：钱到账才算。" in llm.calls[1][2] and "2026-09-30（含）以前" in llm.calls[1][1]
    assert store.chat_demand() == {"2.1": (1, 0), "9.4": (1, 1)}

    store.set_review(item_id, PReview(status=ReviewStatus.CONFIRMED, reviewed_at="2026-10-03T10:00:00"))
    third = chat.reply([ChatTurn(role="user", content="签大单看什么？")])
    assert third.confidence == 0.9 and "；本人已确认" in llm.calls[2][1] + llm.calls[2][2]
    with pytest.raises(ValueError, match="last message"):
        chat.reply(history[:2])


def test_reviews_edit_and_reject_what_the_twin_sees(store: PersonaStore, settings: Settings) -> None:
    embedder = HashingEmbedder()
    money, probe = store.list_items("2.1")[0], store.list_items("4.2")[0]
    now = "2026-10-03T10:00:00"
    store.set_review(money.item_id, PReview(status=ReviewStatus.EDITED, statement="他只认到账的钱", reviewed_at=now))
    store.set_review(probe.item_id, PReview(status=ReviewStatus.REJECTED, reviewed_at=now))
    edited = store.get_item(money.item_id)
    assert edited is not None and edited.statement == "他只认到账的钱" and edited.extracted_statement == money.statement
    assert [i.item_id for i in store.list_items()] == [money.item_id]
    assert len(store.list_items(include_rejected=True)) == 2
    pc.index_persona(store, embedder, settings)
    ctx = pc.PersonaChat(store, FakeLLM(lambda *a: {}), embedder, settings).retrieve("对照组")
    assert probe.item_id not in ctx.ids and money.item_id in ctx.trusted
    with pytest.raises(KeyError):
        store.set_review("pi_missing", None)


@pytest.mark.parametrize("material", ["item", "core", "expression", "narrated", "voice", "question"])
@pytest.mark.parametrize("cited", [False, True])
def test_reply_quote_guard_uses_prompt_material(
    store: PersonaStore, settings: Settings, monkeypatch: pytest.MonkeyPatch, material: str, cited: bool
) -> None:
    words = "先核对虚构数据"
    item = PersonaItem(
        item_id="pi_quote",
        facet_id="4.2",
        statement="他有虚构推断观点",
        evidence=[
            PEvidence(
                expression_id="expr_quote",
                source_id="source_quote",
                source_kind=SourceKind.DOCUMENT,
                evidence_class=EvidenceClass.BEHAVIOR,
                quote=words,
            )
        ],
    )
    expression = Expression(
        expression_id="expr_quote",
        source_id="source_quote",
        idx=0,
        speaker=settings.target_name,
        is_target=True,
        text=words,
        narrated=material == "narrated",
    )
    ctx = pc.PersonaContext(
        items=[(item, 1.0)] if material == "item" else [],
        core=[item] if material == "core" else [],
        expressions=[(expression, 1.0)] if material in {"expression", "narrated"} else [],
        voice=[words] if material == "voice" else [],
    )
    question = f"你怎么看{words}？" if material == "question" else "你怎么看？"
    draft = f' \t「{words}」；“虚构飞船旅行”\n"他有虚构推断观点"、『术语』。 \n'
    llm = FakeLLM(lambda *a: {"reply": draft, "citations": sorted(ctx.ids) if cited else [], "confidence": 0.9})
    chat = pc.PersonaChat(store, llm, HashingEmbedder(), settings)
    monkeypatch.setattr(chat, "retrieve", lambda *a: ctx)
    reply = chat.reply([ChatTurn(role="user", content=question)])
    assert reply.reply == f" \t「{words}」；虚构飞船旅行\n他有虚构推断观点、『术语』。 \n"
    assert reply.quotes_removed == 2
    assert ChatReply.model_validate_json(reply.model_dump_json()) == reply
    assert words in llm.calls[0][1] + llm.calls[0][2]


def test_quote_guard_rejects_unseen_material(
    store: PersonaStore, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    item = store.list_items("2.1")[0]
    evidence = item.evidence[-1]
    item = item.model_copy(
        update={
            "evidence": [
                evidence.model_copy(update={"quote": "从未展示的旧证据"}),
                evidence.model_copy(update={"quote": "甲" * pc.QUOTE_CHARS + "裁掉的证据尾巴"}),
            ]
        }
    )
    expression = store.list_expressions(target_only=True)[0].model_copy(
        update={"text": "乙" * pc.TEXT_CHARS + "裁掉的表达尾巴"}
    )
    ctx = pc.PersonaContext([(item, 1.0)], [(expression, 1.0)], [], ["丙" * pc.VOICE_MAX_CHARS + "裁掉的样本尾巴"])
    draft = "「从未展示的旧证据」「裁掉的证据尾巴」「裁掉的表达尾巴」「裁掉的样本尾巴」「问题以前的话」"
    llm = FakeLLM(lambda *a: {"reply": draft, "citations": [], "confidence": 0.5})
    chat = pc.PersonaChat(store, llm, HashingEmbedder(), settings)
    monkeypatch.setattr(chat, "retrieve", lambda *a: ctx)
    reply = chat.reply([ChatTurn(role="user", content="问题以前的话"), ChatTurn(role="user", content="最后的问题")])
    assert reply.reply == draft.replace("「", "").replace("」", "") and reply.quotes_removed == 5


def test_long_expression_is_shown_around_the_passage_the_query_matches() -> None:
    text = "我平时喜欢听歌。" * 90 + "最有满足感的是写下自己的音乐历程并现场演出。"
    excerpt = pc._excerpt(text, "怎样表达音乐最有满足感", pc.TEXT_CHARS)
    assert len(excerpt) == pc.TEXT_CHARS and excerpt.startswith("…")
    assert excerpt.endswith("最有满足感的是写下自己的音乐历程并现场演出。")
    assert pc._excerpt(text, "毫不相关", pc.TEXT_CHARS) == pc._clip(text, pc.TEXT_CHARS)
    assert pc._excerpt("短句。", "音乐", pc.TEXT_CHARS) == "短句。"


def test_rendered_and_quotable_expressions_follow_the_query() -> None:
    e = Expression(
        expression_id="e1",
        source_id="s",
        idx=0,
        speaker="me",
        is_target=True,
        text="闲聊。" * 300 + "我在城东超市兑换了优惠券。",
    )
    ctx = pc.PersonaContext([], [(e, 1.0)], [], [], query="优惠券在哪个超市兑换")
    assert "城东超市兑换了优惠券" in pc.chat_user_message([ChatTurn(role="user", content="?")], ctx)
    assert any("城东超市" in m for m in pc._quote_materials(ctx))


def number_draft(**changes: Any) -> dict[str, Any]:
    return {**INFERENCE, "asked": "认为多少百分比的人支持该政策", "reply": "55", "abstain_reason": "", **changes}


def test_numeric_estimate_is_inferred_with_citation_and_keeps_the_bare_number(
    store: PersonaStore, settings: Settings
) -> None:
    item_id = store.list_items("2.1")[0].item_id
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: number_draft(citations=[item_id])), HashingEmbedder(), settings)
    reply = chat.reply([ChatTurn(role="user", content='{"question": "What percentage support it?"}')], persist=False)
    assert (reply.reply, reply.mode, reply.abstain, reply.citations) == ("55", "inferred", False, [item_id])
    assert reply.confidence == pc.INFERRED_CONFIDENCE_CAP


def test_numeric_fact_without_evidence_stays_abstained(store: PersonaStore, settings: Settings) -> None:
    draft = number_draft(
        asked="孩子的个数",
        reply="资料里没有记这件事。",
        mode="abstain",
        confidence=0.1,
        abstain_reason="无记录",
        citations=[],
    )
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: draft), HashingEmbedder(), settings)
    reply = chat.reply([ChatTurn(role="user", content="你有几个孩子？")], persist=False)
    assert (reply.mode, reply.abstain, reply.citations) == ("abstain", True, [])
    assert reply.reply == "资料里没有记这件事。" and reply.confidence <= pc.UNCITED_CONFIDENCE_CAP
    # A number claimed as inference without any retrieved basis is not allowed through either.
    guess = number_draft(asked="孩子的个数", reply="2", citations=[])
    chat.llm = FakeLLM(lambda *a: guess)
    assert chat.reply([ChatTurn(role="user", content="你有几个孩子？")], persist=False).abstain


@pytest.mark.parametrize(
    ("question", "fallback"),
    [("你有几个孩子？", pc.EMPTY_REPLY["zh"]), ("How many children do you have?", pc.EMPTY_REPLY["en"])],
)
@pytest.mark.parametrize("blank", ["", "  \n\t"])
@pytest.mark.parametrize("mode", ["grounded", "general", "inferred", "abstain"])
def test_finalized_reply_is_never_empty(
    store: PersonaStore, settings: Settings, question: str, fallback: str, blank: str, mode: str
) -> None:
    item_id = store.list_items("2.1")[0].item_id
    draft = number_draft(reply=blank, citations=[item_id], mode=mode, abstain_reason="")
    chat = pc.PersonaChat(store, FakeLLM(lambda *a: draft), HashingEmbedder(), settings)
    reply = chat.reply([ChatTurn(role="user", content=question)], persist=False)
    assert (reply.reply, reply.mode, reply.abstain) == (fallback, "abstain", True)
    assert reply.abstain_reason and reply.confidence <= pc.UNCITED_CONFIDENCE_CAP


async def collect(chat: pc.PersonaChat, question: list[ChatTurn]) -> list[Any]:
    return [x async for x in chat.stream_reply(question, persist=False)]


def test_streamed_empty_body_is_replaced_in_the_final_reply(store: PersonaStore, settings: Settings) -> None:
    cited = store.list_items("2.1")[0].item_id
    meta = {k: v for k, v in number_draft(citations=[cited]).items() if k not in ("reply", "abstain_reason")}
    question = [ChatTurn(role="user", content="How many children do you have?")]

    class OnlyMetadata(FakeLLM):
        async def stream(self, **kwargs: Any) -> Any:
            yield "<<<META>>>\n" + json.dumps(meta, ensure_ascii=False)

    class NoDelimiter(FakeLLM):
        async def stream(self, **kwargs: Any) -> Any:
            yield "\n"

    for llm in (OnlyMetadata(lambda *a: {}), NoDelimiter(lambda *a: {})):
        chat = pc.PersonaChat(store, llm, HashingEmbedder(), settings)
        final = asyncio.run(collect(chat, question))[-1]
        assert isinstance(final, ChatReply)
        assert (final.reply, final.mode, final.abstain) == (pc.EMPTY_REPLY["en"], "abstain", True)
