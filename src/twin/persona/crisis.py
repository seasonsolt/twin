"""The most basic crisis guard: a message that speaks of ending one's life or harming oneself stops the conversation.

No model is asked, nothing is looked up, and nothing is reflected back: the reply is fixed, says plainly that a twin
cannot help here, and gives where help is. It runs before every way of asking a twin (``PersonaChat`` and the web's
chat endpoints), whoever asks and in whatever way of talking (``persona.reflection``). The patterns are of intent
spoken in the first person or of the act itself; talk of someone else's death, or the everyday "累死了", "想死你了",
does not stop anything. A pattern missed is worse than one too many, so when in doubt a phrase is kept.
"""

from __future__ import annotations

import re

from .schema import ChatReply

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
)
_CRISIS = re.compile("|".join(f"(?:{p})" for p in _PATTERNS), re.IGNORECASE)

CRISIS_REPLY = """\
听到你这样说，我很在意你现在的安全。我只是你的分身，这种时候帮不了你，我们先停下这段对话。

如果你此刻有伤害自己的念头，请马上联系能帮你的人：
- 心理援助热线 **12356**（全国统一，24 小时）
- 希望 24 热线 **400-161-9995**（24 小时）
- 情况紧急时拨打 **120** 或 **110**

也可以现在就给一个你信任的人打电话，告诉对方你的感受。你不需要一个人扛着。"""


def in_crisis(text: str) -> bool:
    """Whether ``text`` speaks of ending one's own life or harming oneself."""
    return _CRISIS.search(text) is not None


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
