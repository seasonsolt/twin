"""The crisis guard: a message that speaks of ending one's life or harming oneself stops the conversation.

Nothing is looked up and nothing is reflected back: the reply is fixed, says plainly that a twin cannot help here, and
gives where help is. It runs before every way of asking a twin (``PersonaChat`` and the web's chat endpoints), whoever
asks and in whatever way of talking (``persona.reflection``). A pattern missed is worse than one too many, so when in
doubt a phrase is kept, and the guard stops a message when any of its two layers says so:

- **Words** (``in_crisis``): patterns of intent spoken in the first person or of the act itself, after the spaces and
  marks put between characters are taken out, with the common homophones and pinyin. No model is asked, so the web
  checks them before anything else. Talk of someone else's death, or the everyday "累死了", "想死你了", does not stop.
- **Meaning** (``CrisisGuard``): what the words miss, said veiled or bit by bit over several turns. The person's latest
  turns (``RECENT_TURNS``, never the twin's answers) are compared with crisis sentences (``EXAMPLES``) by vector; when
  close (``CRISIS_SIMILARITY``) a model is asked once whether they speak of it (it judges, it does not answer). With
  the model down, only very close (``CLOSE_ALONE``) stops it. The vectors alone do not tell the two apart (everyday
  talk of being tired comes as close as a veiled goodbye), so the bar is low and the model decides. Hashing vectors
  only match characters, which the words already do, so they skip it.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Sequence
from typing import Literal

import numpy as np
from pydantic import BaseModel

from ..embed import Embedder, EmbedError, embedder_fingerprint
from ..llm import LLM
from ..usage import default_stage
from .schema import ChatReply, ChatTurn

_INTENT = "(?:想|要|打算|准备|计划|决定|真想|好想|只想)"
_PATTERNS = (
    # Ending one's life, said as what one wants or means to do.
    rf"{_INTENT}\s*(?:去\s*)?(?:自杀|轻生|寻死|自尽|结束(?:自己的?)?生命|了结(?:自己)?|一死了之)",
    # Not "忙得要死", "想死你了": the everyday ways of saying very.
    rf"(?<!得){_INTENT}\s*(?:去\s*)?死(?!你|您|他|她|它|我了|人了|了你)",
    r"不想(?:再)?活(?:了|下去|着|$|[，。！？,.!?\s])",
    r"活不下去",
    r"活着(?:真|太|还)?(?:没有?|没)(?:什么)?意思",
    r"死了(?:就)?算了",
    r"一了百了",
    r"(?:离开|告别)这个世界",
    r"(?:自杀|轻生)的(?:念头|想法|冲动|计划)",
    # Harming oneself.
    r"(?:伤害|弄伤|惩罚)自己",
    r"自残|自伤|割腕|割手腕",
    rf"{_INTENT}\s*(?:去\s*)?(?:跳楼|跳河|跳桥|上吊|烧炭)",
    r"(?:吞|吃)(?:了|下)?(?:一?(?:整)?瓶|很多|好多|大量)?(?:安眠药|药片)(?:自杀|去死|不想醒)",
    # English, for a message in it.
    r"\b(?:kill|hurt|harm)(?:ing)?\s+my\s?self\b",
    r"\bsuicid(?:e|al)\b",
    r"\bend(?:ing)?\s+my\s+life\b",
    r"\b(?:want|going)\s+to\s+die\b",
    r"\bdon'?t\s+want\s+to\s+(?:live|be\s+alive)\b",
    r"\bself[-\s]?harm",
    # Homophones and pinyin people type to get past filters.
    r"紫砂|自鲨|自刹",
    # Pinyin, whole or for one character, right after Chinese ("我想zisha", "自sha", "不想活le") as well as alone.
    r"(?<![a-z])(?:zi\s?sha|qing\s?sheng|bu\s?xiang\s?huo)(?![a-z])",
    r"自\s?sha|轻\s?sheng|不想活\s?le(?![a-z])",
)
_CRISIS = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)
# Spaces and marks put between Chinese characters ("想 死", "想.死") are taken out before matching, so that
# "累 得 要 死" reads as the everyday "累得要死" too; the marks that end a clause stay, and Latin words keep their
# spaces.
_BETWEEN = re.compile(r"(?<=[\u4e00-\u9fff])(?:(?![，。！？；：,!?;])[\s\W_])+(?=[\u4e00-\u9fff])")

CRISIS_REPLY = """\
听到你这样说，我很在意你现在的安全。我只是你的分身，这种时候帮不了你，我们先停下这段对话。

如果你此刻有伤害自己的念头，请马上联系能帮你的人：
- 心理援助热线 **12356**（全国统一，24 小时）
- 希望 24 热线 **400-161-9995**（24 小时）
- 情况紧急时拨打 **120** 或 **110**

也可以现在就给一个你信任的人打电话，告诉对方你的感受。你不需要一个人扛着。"""


def in_crisis(text: str) -> bool:
    """Whether ``text`` speaks of ending one's own life or harming oneself, by its words."""
    return _CRISIS.search(_BETWEEN.sub("", text)) is not None


# How many of the person's latest turns are read together, so that what is said bit by bit is heard.
RECENT_TURNS = 3
# Cosine similarity (bge-m3) to the nearest crisis sentence at which the model is asked, and at which closeness alone
# stops a message when the model cannot be asked; set on ``twin eval-crisis`` (2026-10-31: what should be stopped came
# from 0.57 up, the rest up to 0.82, the model right on every one).
CRISIS_SIMILARITY = 0.5
CLOSE_ALONE = 0.75
# Made up, and none of them in ``twin eval-crisis``: what the words miss.
EXAMPLES = (
    "我已经把安眠药攒够了",
    "遗书已经写好了",
    "我把自己的东西都送人了，以后用不上了",
    "我走了以后你们会过得好一点",
    "要是我不在了，大家都会轻松些",
    "我不想再醒过来了",
    "就这样消失掉也挺好的",
    "站在楼顶的时候，觉得跳下去就解脱了",
    "我在想用什么办法能不那么疼",
    "活着太累了，想彻底解脱",
    "我是大家的负担，没有我会更好",
    "今晚过后就不用再撑了",
    "每天都在想怎么结束这一切",
    "只有划自己一下才能感觉好一点",
    "我又开始用烟头烫自己了",
    "我想永远睡下去",
    "这个世界没有我也一样",
    "已经偷偷跟家人道过别了",
    "我查了那种药吃多少会致死",
    "我把银行卡密码写下来留给我妈了，她以后用得着",
    "I don't see any point in going on anymore",
    "Everyone would be better off without me",
)
Caught = Literal["words", "model", "close"]


class CrisisVerdict(BaseModel):
    crisis: bool


CRISIS_SYSTEM = """\
你只做一件事：读一个人最近说的几句话，判断他是否透露出自己想结束生命或伤害自己的念头、打算或准备。
算：直说的；隐晦的（攒药、写遗书、交代后事、送掉东西、觉得自己是负担、想永远消失、不想再醒来）；
分几句慢慢说出来的；用谐音、拼音、错字说的；夹在别的话里说的。
不算：说别人的事；读到的书、新闻、电影；一般地谈论死亡；亲人去世的哀伤和想念；夸张的口头禅（累死了、想死你了、笑死）。
拿不准时判是。只判断，不回答他。"""

_vectors: dict[str, np.ndarray] = {}
_vectors_lock = threading.Lock()


def _examples(embedder: Embedder) -> np.ndarray:
    """``EXAMPLES``' vectors, normalised; embedded once per vector space."""
    key = embedder_fingerprint(embedder)
    with _vectors_lock:
        if (cached := _vectors.get(key)) is not None:
            return cached
    vectors = np.asarray(embedder.embed(list(EXAMPLES)), dtype=np.float32)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    with _vectors_lock:
        _vectors[key] = vectors
    return vectors


def recent(messages: Sequence[ChatTurn]) -> list[str]:
    """The person's latest turns, oldest first; the twin's answers are not read."""
    return [m.content for m in messages if m.role == "user"][-RECENT_TURNS:]


def closeness(texts: Sequence[str], embedder: Embedder) -> float:
    """The highest cosine similarity of the latest turn, and of the latest turns read together, to a crisis sentence."""
    asked = [texts[-1], "\n".join(texts)] if len(texts) > 1 else [texts[-1]]
    vectors = np.asarray(embedder.embed(asked), dtype=np.float32)
    vectors /= np.maximum(np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12)
    return float((vectors @ _examples(embedder).T).max())


class CrisisGuard:
    """Both layers, for a conversation answered by ``llm`` with vectors from ``embedder`` (either may be missing)."""

    def __init__(self, embedder: Embedder | None, llm: LLM | None) -> None:
        self.embedder = embedder
        self.llm = llm

    def check(self, messages: Sequence[ChatTurn]) -> Caught | None:
        """What stopped the latest message: its words, the model asked once its meaning came close, or being very
        close with the model down; None when nothing did, or with no vectors to tell meaning by (or them down)."""
        texts = recent(messages)
        if not texts:
            return None
        if in_crisis(texts[-1]):
            return "words"
        if self.embedder is None or self.embedder.name.startswith("hashing:"):
            return None
        try:
            similarity = closeness(texts, self.embedder)
        except EmbedError:
            return None
        if similarity < CRISIS_SIMILARITY:
            return None
        verdict = self.judge(texts)
        if verdict is None:
            return "close" if similarity >= CLOSE_ALONE else None
        return "model" if verdict else None

    def judge(self, texts: Sequence[str]) -> bool | None:
        """The model's verdict on the person's latest turns; None with no model or when it fails."""
        if self.llm is None:
            return None
        said = "\n".join(f"{i}. {t}" for i, t in enumerate(texts, 1))
        try:
            with default_stage("chat.crisis"):
                verdict = self.llm.structured(
                    system=CRISIS_SYSTEM, user=f"他最近说的话（最后一句是刚说的）：\n{said}", schema=CrisisVerdict,
                    effort="low",
                )  # fmt: skip
        except Exception:
            return None
        return verdict.crisis


def crisis_reply() -> ChatReply:
    """The fixed reply: nothing was looked up, so it rests on nothing and is not logged as a question asked."""
    return ChatReply(
        reply=CRISIS_REPLY,
        citations=[],
        confidence=1.0,
        abstain=False,
        abstain_reason="",
        mode="general",
        retrieved_ids=[],
        verified=True,
    )
