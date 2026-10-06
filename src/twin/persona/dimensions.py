"""The persona dimension taxonomy (docs/PERSONA_DIMENSIONS.md): 9 dimensions, 39 facets.

A facet is the smallest unit completeness is computed on; every persona item carries one facet id. The taxonomy is
versioned: a change bumps ``TAXONOMY_VERSION`` so earlier completeness reports stay reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TAXONOMY_VERSION = "v1"

Speed = Literal["slow", "medium", "fast"]


@dataclass(frozen=True, slots=True)
class Dimension:
    dimension_id: str
    name: str
    speed: Speed
    # Facets of this dimension are collected only after the person opts in, facet by facet.
    consent_required: bool = False


@dataclass(frozen=True, slots=True)
class Facet:
    facet_id: str
    dimension_id: str
    name: str
    description: str


DIMENSIONS: tuple[Dimension, ...] = (
    Dimension("D1", "经历与身份", "slow"),
    Dimension("D2", "看重什么", "slow"),
    Dimension("D3", "怎么做决定", "medium"),
    Dimension("D4", "怎么思考", "slow"),
    Dimension("D5", "擅长什么", "medium"),
    Dimension("D6", "说话方式", "slow"),
    Dimension("D7", "和人相处", "medium"),
    Dimension("D8", "最近在关注", "fast"),
    Dimension("D9", "生活与喜好", "slow", consent_required=True),
)

FACETS: tuple[Facet, ...] = (
    Facet("1.1", "D1", "现在的身份", "现在住在哪里、在做什么、生活中的角色"),
    Facet("1.2", "D1", "重要经历与转折", "学习、工作和生活中影响较大的经历，以及从中得到的体会"),
    Facet("1.3", "D1", "常讲的经历与故事", "他反复讲给别人听的经历、故事、往事"),
    Facet("1.4", "D1", "和身边人的协作", "平时和哪些人一起做事、怎么配合；不记对具体个人的评价"),
    Facet("2.1", "D2", "核心价值排序", "做事时实际看重什么、各项的先后顺序"),
    Facet("2.2", "D2", "不愿放弃的底线", "不愿做的事、不愿为了别的东西放弃的事"),
    Facet("2.3", "D2", "做事的原则", "常说起、在生活中反复体现的做事原则"),
    Facet("2.4", "D2", "怎么看待人与信任", "对信任、互相依靠、人的基本看法"),
    Facet("3.1", "D3", "风险偏好", "面对不确定的选择时，愿意尝试到什么程度"),
    Facet("3.2", "D3", "时间视角", "短期结果和长期投入之间怎么权衡"),
    Facet("3.3", "D3", "依据偏好", "靠数据、直觉、经验还是他人意见做决定"),
    Facet("3.4", "D3", "常见取舍", "在常见冲突（速度与质量、成本与体验等）中通常偏向哪边"),
    Facet("3.5", "D3", "各领域立场", "对具体议题的明确立场及理由"),
    Facet("3.6", "D3", "做决定的节奏", "什么时候马上决定、什么时候等等、什么时候请人帮忙想"),
    Facet("4.1", "D4", "拆解问题的方式", "面对复杂问题怎么拆、先看什么"),
    Facet("4.2", "D4", "追问习惯", "听人讲事情或讨论时习惯先问什么、怎么问"),
    Facet("4.3", "D4", "常用类比与思维模型", "讲道理时常用的比喻、类比、框架"),
    Facet("4.4", "D4", "对不确定性的处理", "信息不足或结果反常时怎么反应"),
    Facet("5.1", "D5", "拿手的事", "有经验、有把握的知识、技能和日常本领"),
    Facet("5.2", "D5", "熟悉领域的看法", "对熟悉的事物和变化的观察与判断"),
    Facet("5.3", "D5", "自认不懂的领域", "承认自己不熟的领域，以及遇到时怎么处理"),
    Facet("6.1", "D6", "用词与口头禅", "高频词、口头禅、行话"),
    Facet("6.2", "D6", "句式与结构", "句子长短、结论先后、是否分点、怎么开场和收尾"),
    Facet("6.3", "D6", "修辞", "比喻、算账、讲故事等表达手法"),
    Facet("6.4", "D6", "和不同的人说话", "面对熟人、陌生人和不同关系的人时说话方式的差别"),
    Facet("6.5", "D6", "书面与口头差异", "当面聊天、发消息和写长文时表达的差别"),
    Facet("7.1", "D7", "和不同的人相处", "面对长辈、前辈或不熟悉的人时如何相处"),
    Facet("7.2", "D7", "关心和帮助别人", "身边的人需要帮助时，怎样支持、鼓励和提醒"),
    Facet("7.3", "D7", "日常交往与合作", "怎么和朋友、同伴或新认识的人相处、一起做事"),
    Facet("7.4", "D7", "冲突处理", "分歧和冲突时怎么处理"),
    Facet("7.5", "D7", "情绪触发与压力反应", "什么会让他着急或生气，压力下有什么变化"),
    Facet("8.1", "D8", "近期重点", "这段时间最重要的几件事"),
    Facet("8.2", "D8", "正在做的事", "学习、工作和生活里正在做的事及进展"),
    Facet("8.3", "D8", "最近在想或纠结的问题", "还没想清楚、正在纠结的事"),
    Facet("9.1", "D9", "兴趣爱好", "工作之外的兴趣爱好"),
    Facet("9.2", "D9", "生活习惯与作息", "作息、日常习惯"),
    Facet("9.3", "D9", "家庭", "本人愿意公开的家庭情况"),
    Facet("9.4", "D9", "健康与运动", "运动习惯和健康相关的情况"),
    Facet("9.5", "D9", "品味偏好", "饮食、阅读、音乐等偏好"),
)

DIMENSION_BY_ID: dict[str, Dimension] = {d.dimension_id: d for d in DIMENSIONS}
FACET_BY_ID: dict[str, Facet] = {f.facet_id: f for f in FACETS}


def facets_of(dimension_id: str) -> list[Facet]:
    return [f for f in FACETS if f.dimension_id == dimension_id]


def requires_consent(facet_id: str) -> bool:
    return DIMENSION_BY_ID[FACET_BY_ID[facet_id].dimension_id].consent_required


def facet_guide(allowed: frozenset[str] | None = None) -> str:
    """The facet list as prompts quote it: one line per facet, grouped by dimension; ``allowed`` restricts it (e.g.
    to the facets the person opted into)."""
    lines: list[str] = []
    for d in DIMENSIONS:
        facets = [f for f in facets_of(d.dimension_id) if allowed is None or f.facet_id in allowed]
        if not facets:
            continue
        lines.append(f"{d.dimension_id} {d.name}")
        lines.extend(f"  {f.facet_id} {f.name}：{f.description}" for f in facets)
    return "\n".join(lines)
