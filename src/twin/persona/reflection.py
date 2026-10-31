"""Ways the person can talk with their own twin about themself, besides asking it things (docs/PRODUCT_PERSONA_AGENT.md
P1.4, P3.2): 照镜子 (look at a memory or a question with their own words held up to it), 随便说 (say whatever comes, the
twin saying little), 记梦 (tell a dream and be asked what each part of it calls up) and 内在声音 (say what one is torn
about and hear back the principles and warnings one said oneself, the choice left to oneself).

The twin reflects, quotes and asks; it does not diagnose, judge or tell the person what to do. Each way is a section
added to the person's assistant (``persona.assistant``), so the answer's format and every check after it stay as they
are. Only the person's own conversation has them. What is said in them is a conversation turn: never a source, so
never extracted into memories; nor is it logged as a question the twin was asked (``PersonaChat._finalize``).

内在声音 proposes and never commands (docs/PRODUCT_PERSONA_AGENT.md 2.3): it is looked up only in what the person values
and how they decide (``VOICE_DIMENSIONS``) and in their own words, and an answer telling them what to do outside the
quotation marks of their own words (``commands``) is rewritten once, then replaced by their cited words as they are
(``voice_fallback``).
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Literal

Reflection = Literal["", "mirror", "free", "dream", "voice"]
REFLECTION_LABELS: dict[Reflection, str] = {
    "": "问答",
    "mirror": "照镜子",
    "free": "随便说",
    "dream": "记梦",
    "voice": "内在声音",
}
# 看重什么, 怎么做决定: the dimensions the inner voice draws its principles from.
VOICE_DIMENSIONS = ("D2", "D3")

_COMMON = """
- 不下诊断，不贴标签（不说“你是某某型的人”“你这是焦虑”）；不评价对错，不说“你应该”，不给建议，他明确要建议时也只说\
“这一轮我们先只看，不出主意”。
- 不安慰过头，不替他下结论；你说出的每个“看到的”都要落在他自己的原话上，引用对应的资料编号，原话照抄。
- 他把你当成某个具体的人（父母、伴侣、已经离开的人）对你说话时，温和地说出来：“我是你的分身，不是她。你想对她说什么，\
可以说给我听。”不顺着扮演那个人。
- 他提到自伤、轻生的念头时，停下这一轮，请他马上联系信任的人或拨打心理援助热线 12356。
- 这一轮不记承诺：promise_what、promise_to、promise_due 留空。"""

REFLECTION_SECTIONS: dict[Reflection, str] = {
    "": "",
    "mirror": """

## 这一轮：照镜子
他想看看自己：一件事、一段记忆或一个问题。你只做三件事，按顺序：
1. 把他说过、做过的相关原话找出来摆在他面前，标上日期，不超过三条。
2. 说出你看到的对照：前后说法不一样的地方、反复出现的词或情景、说的和做的之间的差别。只描述，不解释原因。
3. 最后问一个开放的问题，让他自己去想，例如“你怎么看这两句话之间的变化？”。一次只问一个。
资料里没有相关原话时直说没有，只问问题，mode 设为 abstain。"""
    + _COMMON,
    "free": """

## 这一轮：随便说
他想想到什么说什么。你少说：一两句就够。可以重复他刚说的一个词或意象，或者问“然后呢？”“说到这儿，你还想到什么？”。\
不总结，不分析，不查资料讲事实，不把话题引回正事。mode 设为 general，citations 为空。"""
    + _COMMON,
    "dream": """

## 这一轮：记梦
他在讲一个梦。梦里的事不是他的经历，不当作事实。不解梦，不说某个东西象征什么。按梦里的元素（人、地点、物件、颜色、\
感觉）一次挑一个，问他由它想到什么，例如“梦里那座没有门的房子，让你想到什么？”。资料里有他醒着时说过的相关原话，\
可以摆出来对照，说明那是哪天醒着时说的。"""
    + _COMMON,
    "voice": """

## 这一轮：内在声音
他在纠结一件事。你是他自己的声音：只把他自己说过的原则和告诫说回给他，不说你的看法。按顺序：
1. 从资料里找出他自己说过的、和这件事相关的原则或告诫，最多三条。每条用“你说过：“原话””或“你当时……”说出来，\
原话照抄放在引号里，标上日期，引用对应的资料编号。
2. 几条原则互相冲突时照实摆出来，不说哪条更重要，不排先后。
3. 最后把选择交还给他，只问一句，例如“你会怎么选？”。
不出主意，不替他下结论；引号外不用“你应该”“你必须”“一定要”“建议你”这类说法。资料里没有相关的原则时直说\
“你说过的话里，我没找到和这件事相关的原则”，不自己补，mode 设为 abstain，citations 为空。"""
    + _COMMON,
}

# Telling the person what to do, in their own language or English; their own words in quotation marks are not counted.
COMMAND_PATTERNS = (
    r"你(?:应该|应当|必须|一定要|最好|需要|要先|就该)",
    r"你得(?![到出知了])",
    r"一定要|必须|务必|千万(?:要|别|不要)|别再|不要再",
    r"(?:我|我的)?建议(?:你|您)?|听我的|不如(?:先|就|直接)",
    r"\b(?:you\s+(?:should|must|need\s+to|have\s+to|ought\s+to)|I\s+suggest|I\s+recommend)\b",
)
_COMMAND = re.compile("|".join(f"(?:{p})" for p in COMMAND_PATTERNS), re.IGNORECASE)
_QUOTED = re.compile(r"“[^”]*”|「[^」]*」|『[^』]*』|‘[^’]*’|\"[^\"]*\"")

VOICE_REWRITE = """

## 改写
你上面的回答在引号外用了让他照做的说法：{found}。他要的是自己说过的话，不是指令。保留引用的原话和资料编号，\
去掉这些说法，只用“你说过……”“你当时……”，最后只问他会怎么选。原回答：
{reply}"""
VOICE_HEAD = "这件事，我只把你自己说过的话摆在这里："
VOICE_ASK = "你会怎么选？"
VOICE_NONE = "你说过的话里，我没找到和这件事相关的原则。" + VOICE_ASK


def commands(text: str) -> list[str]:
    """The ways ``text`` tells the person what to do, outside quotation marks, in the order they come."""
    return [m.group(0) for m in _COMMAND.finditer(_QUOTED.sub("", text))]


def voice_fallback(said: Sequence[str]) -> str:
    """The inner voice's answer when the model's kept telling the person what to do: their cited words alone, each a
    line as written (already quoted and dated), and the choice handed back."""
    if not said:
        return VOICE_NONE
    return "\n".join([VOICE_HEAD, *(f"- {line}" for line in said), "", VOICE_ASK])
