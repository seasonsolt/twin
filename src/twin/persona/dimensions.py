"""The persona dimension taxonomy (docs/PERSONA_DIMENSIONS.md): 9 dimensions, 39 facets.

A facet is the smallest unit completeness is computed on; every persona item carries one facet id. The taxonomy is
versioned: a change bumps ``TAXONOMY_VERSION`` so earlier completeness reports stay reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

TAXONOMY_VERSION = "v0"

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
    Dimension("D1", "身份与经历", "slow"),
    Dimension("D2", "价值观与原则", "slow"),
    Dimension("D3", "决策与判断", "medium"),
    Dimension("D4", "思维方式", "slow"),
    Dimension("D5", "知识与专长", "medium"),
    Dimension("D6", "表达风格", "slow"),
    Dimension("D7", "人际与情绪", "medium"),
    Dimension("D8", "当前状态与关注", "fast"),
    Dimension("D9", "个人生活与偏好", "slow", consent_required=True),
)

FACETS: tuple[Facet, ...] = (
    Facet("1.1", "D1", "角色与职责", "现在的角色、负责的范围、向谁汇报、谁向他汇报"),
    Facet("1.2", "D1", "履历与关键转折", "职业经历和对他影响最大的转折，以及他从中得出的结论"),
    Facet("1.3", "D1", "常讲的经历与故事", "他反复讲给别人听的经历、故事、往事"),
    Facet("1.4", "D1", "组织与协作关系", "所在组织结构和主要协作方；只记结构，不记对具体个人的评价"),
    Facet("2.1", "D2", "核心价值排序", "做事时实际看重什么、各项的先后顺序"),
    Facet("2.2", "D2", "底线与红线", "一定不做、一定不允许团队做的事"),
    Facet("2.3", "D2", "做事与经营原则", "常挂在嘴边、反复体现的做事原则"),
    Facet("2.4", "D2", "对人的基本假设", "对信任、授权、人性的基本看法"),
    Facet("3.1", "D3", "风险偏好", "面对不确定收益和损失时敢不敢押、押多少"),
    Facet("3.2", "D3", "时间视角", "短期结果和长期投入之间怎么权衡"),
    Facet("3.3", "D3", "依据偏好", "靠数据、直觉、经验还是他人意见做决定"),
    Facet("3.4", "D3", "常见取舍", "在常见冲突（速度与质量、成本与体验等）中通常偏向哪边"),
    Facet("3.5", "D3", "各领域立场", "对具体议题的明确立场及理由"),
    Facet("3.6", "D3", "决策节奏与授权", "什么时候当场拍板、什么时候延后、交给谁定"),
    Facet("4.1", "D4", "拆解问题的方式", "面对复杂问题怎么拆、先看什么"),
    Facet("4.2", "D4", "追问习惯", "听汇报或讨论时习惯先问什么、怎么问"),
    Facet("4.3", "D4", "常用类比与思维模型", "讲道理时常用的比喻、类比、框架"),
    Facet("4.4", "D4", "对不确定性的处理", "信息不足或结果反常时怎么反应"),
    Facet("5.1", "D5", "专业领域", "最有把握的专业领域"),
    Facet("5.2", "D5", "行业判断", "对行业、市场、技术趋势的判断"),
    Facet("5.3", "D5", "自认不懂的领域", "承认自己不熟的领域，以及遇到时怎么处理"),
    Facet("6.1", "D6", "用词与口头禅", "高频词、口头禅、行话"),
    Facet("6.2", "D6", "句式与结构", "句子长短、结论先后、是否分点、怎么开场和收尾"),
    Facet("6.3", "D6", "修辞", "比喻、算账、讲故事等表达手法"),
    Facet("6.4", "D6", "对象差异", "对上级、下属、外部说话方式的差别"),
    Facet("6.5", "D6", "书面与口头差异", "开会、聊天、写邮件和文档时表达的差别"),
    Facet("7.1", "D7", "对上", "怎么向上汇报、怎么应对上级的否定"),
    Facet("7.2", "D7", "对下", "怎么分配、辅导、授权、表扬、批评下属"),
    Facet("7.3", "D7", "对平级与外部", "怎么和平级、合作方、客户打交道"),
    Facet("7.4", "D7", "冲突处理", "分歧和冲突时怎么处理"),
    Facet("7.5", "D7", "情绪触发与压力反应", "什么会让他着急或生气，压力下有什么变化"),
    Facet("8.1", "D8", "近期重点", "这段时间最重要的几件事"),
    Facet("8.2", "D8", "手头项目与进展", "正在推进的项目和进展"),
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
