"""Completeness of the persona profile per facet and dimension (docs/PERSONA_DIMENSIONS.md, section 4).

Per facet: covered (an item exists), sufficiency S in [0, 1] from distinct occasions and source variety, accuracy A
from test probes (None until at least ``MIN_PROBES`` were scored), and a level 0-3. Per dimension: the share of
consented facets at level >= 1, >= 2 and 3. Also a facet x source-kind matrix of occasions and the next facets to
collect for, with the source kinds most likely to fill them.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, Field

from .dimensions import DIMENSIONS, FACET_BY_ID, FACETS, TAXONOMY_VERSION, facets_of
from .items import PersonaItem
from .schema import SOURCE_KIND_LABELS, EvidenceClass, SourceKind

OCCASION_TARGET = 3
RECENT_DAYS = 90
SUFFICIENT = 0.7
VERIFIED = 0.7
MIN_PROBES = 3
CONFLICT_CAP = 0.5
FAST_DIMENSIONS = frozenset({"D8"})

# Where each dimension's evidence most likely comes from, best first.
LIKELY_SOURCES: dict[str, tuple[SourceKind, ...]] = {
    "D1": (SourceKind.QUESTIONNAIRE, SourceKind.INTERVIEW, SourceKind.DOCUMENT),
    "D2": (SourceKind.CHAT, SourceKind.INTERVIEW, SourceKind.QUESTIONNAIRE),
    "D3": (SourceKind.CHAT, SourceKind.DOCUMENT, SourceKind.INTERVIEW),
    "D4": (SourceKind.CHAT, SourceKind.DOCUMENT),
    "D5": (SourceKind.DOCUMENT, SourceKind.CHAT),
    "D6": (SourceKind.CHAT, SourceKind.DOCUMENT),
    "D7": (SourceKind.CHAT, SourceKind.INTERVIEW),
    "D8": (SourceKind.CHAT, SourceKind.DOCUMENT),
    "D9": (SourceKind.QUESTIONNAIRE, SourceKind.INTERVIEW),
}

LEVEL_LABELS = {0: "未覆盖", 1: "已覆盖", 2: "充分", 3: "已验证"}


class FacetCoverage(BaseModel):
    facet_id: str
    name: str
    dimension_id: str
    consented: bool
    items: int
    occasions: int
    behavior: bool
    source_kinds: list[SourceKind]
    conflicts: int
    # Items the person confirmed or edited.
    confirmed: int = 0
    # Logged chat questions touching the facet, and how many of them the twin abstained on.
    asked: int = 0
    abstained: int = 0
    sufficiency: float
    accuracy: float | None
    probes: int
    level: int
    # Occasions per source kind, for the facet x source matrix.
    by_kind: dict[SourceKind, int] = Field(default_factory=dict)


class DimensionCoverage(BaseModel):
    dimension_id: str
    name: str
    facets: int
    consented: int
    covered: float | None
    sufficient: float | None
    verified: float | None
    conflicts: int


class Suggestion(BaseModel):
    facet_id: str
    name: str
    reason: str
    sources: list[SourceKind]


class CoverageReport(BaseModel):
    taxonomy: str = TAXONOMY_VERSION
    as_of: dt.date
    facets: list[FacetCoverage]
    dimensions: list[DimensionCoverage]
    suggestions: list[Suggestion]


def _occasions(items: Sequence[PersonaItem], kinds: set[SourceKind] | None = None) -> int:
    return len({(e.source_id, e.date) for i in items for e in i.evidence if kinds is None or e.source_kind in kinds})


def facet_coverage(
    facet_id: str,
    items: Sequence[PersonaItem],
    as_of: dt.date,
    consented: bool,
    probe_scores: Sequence[float] = (),
    demand: tuple[int, int] = (0, 0),
) -> FacetCoverage:
    facet = FACET_BY_ID[facet_id]
    if facet.dimension_id in FAST_DIMENSIONS:
        since = as_of - dt.timedelta(days=RECENT_DAYS)
        items = [
            i.model_copy(update={"evidence": recent})
            for i in items
            if (recent := [e for e in i.evidence if e.date is not None and since <= e.date <= as_of])
        ]
    occasions = _occasions(items)
    kinds = sorted({e.source_kind for i in items for e in i.evidence})
    behavior = any(e.evidence_class is EvidenceClass.BEHAVIOR for i in items for e in i.evidence)
    conflicts = sum(1 for i in items if i.conflict)
    s = 0.0
    if items:
        s = 0.5 * min(1.0, occasions / OCCASION_TARGET) + 0.25 * behavior + 0.25 * (len(kinds) >= 2)
        if conflicts:
            s = min(s, CONFLICT_CAP)
    accuracy = sum(probe_scores) / len(probe_scores) if len(probe_scores) >= MIN_PROBES else None
    level = 0
    if items:
        level = 1
        if s >= SUFFICIENT:
            level = 2
            if accuracy is not None and accuracy >= VERIFIED:
                level = 3
    return FacetCoverage(
        facet_id=facet_id,
        name=facet.name,
        dimension_id=facet.dimension_id,
        consented=consented,
        items=len(items),
        occasions=occasions,
        behavior=behavior,
        source_kinds=kinds,
        conflicts=conflicts,
        confirmed=sum(1 for i in items if i.verified),
        asked=demand[0],
        abstained=demand[1],
        sufficiency=round(s, 3),
        accuracy=None if accuracy is None else round(accuracy, 3),
        probes=len(probe_scores),
        level=level,
        by_kind={k: _occasions(items, {k}) for k in kinds},
    )


def _share(values: Sequence[bool]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def _suggest(f: FacetCoverage) -> Suggestion | None:
    likely = list(LIKELY_SOURCES[f.dimension_id])
    if f.conflicts:
        reason = f"有 {f.conflicts} 处自述与行为矛盾，需要访谈澄清"
        likely = [SourceKind.INTERVIEW]
    elif f.abstained:
        reason = f"聊天里被问到 {f.asked} 次，答不上 {f.abstained} 次"
    elif f.level == 0:
        reason = "还没有任何证据"
    elif f.level == 1:
        missing: list[str] = []
        if f.occasions < OCCASION_TARGET:
            missing.append(f"场合不足（{f.occasions}/{OCCASION_TARGET}）")
        if not f.behavior:
            missing.append("缺少实际行为证据")
        if len(f.source_kinds) < 2:
            missing.append("只有一类来源")
        reason = "；".join(missing) or "证据不够充分"
        if not f.behavior:
            likely = [k for k in likely if k not in (SourceKind.QUESTIONNAIRE, SourceKind.INTERVIEW)] or likely
    elif f.level == 2 and f.accuracy is None:
        reason = f"证据充分，测试题不足（{f.probes}/{MIN_PROBES}），还未验证"
        likely = []
    else:
        return None
    return Suggestion(facet_id=f.facet_id, name=f.name, reason=reason, sources=likely)


def coverage_report(
    items: Sequence[PersonaItem],
    consented: frozenset[str],
    as_of: dt.date | None = None,
    probe_scores: Mapping[str, Sequence[float]] | None = None,
    demand: Mapping[str, tuple[int, int]] | None = None,
) -> CoverageReport:
    as_of = as_of or dt.date.today()
    scores = probe_scores or {}
    by_facet: dict[str, list[PersonaItem]] = {}
    for i in items:
        by_facet.setdefault(i.facet_id, []).append(i)
    facets = [
        facet_coverage(
            f.facet_id,
            by_facet.get(f.facet_id, []),
            as_of,
            f.facet_id in consented,
            scores.get(f.facet_id, ()),
            (demand or {}).get(f.facet_id, (0, 0)),
        )
        for f in FACETS
    ]
    dims: list[DimensionCoverage] = []
    for d in DIMENSIONS:
        own = [f for f in facets if f.dimension_id == d.dimension_id and f.consented]
        dims.append(
            DimensionCoverage(
                dimension_id=d.dimension_id,
                name=d.name,
                facets=len(facets_of(d.dimension_id)),
                consented=len(own),
                covered=_share([f.level >= 1 for f in own]),
                sufficient=_share([f.level >= 2 for f in own]),
                verified=_share([f.level == 3 for f in own]),
                conflicts=sum(f.conflicts for f in own),
            )
        )
    order = {0: 1, 1: 2, 2: 3}
    pending = [s for f in facets if f.consented and (s := _suggest(f)) is not None]
    rank = {f.facet_id: (0 if f.conflicts else 0.5 if f.abstained else order.get(f.level, 4)) for f in facets}
    by_id = {f.facet_id: f for f in facets}
    pending.sort(key=lambda s: (rank[s.facet_id], -by_id[s.facet_id].abstained, s.facet_id))
    return CoverageReport(as_of=as_of, facets=facets, dimensions=dims, suggestions=pending)


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def report_markdown(report: CoverageReport, max_suggestions: int = 12) -> str:
    kinds = list(SourceKind)
    lines = [
        f"# 人格复刻完成度（维度体系 {report.taxonomy}，截至 {report.as_of.isoformat()}）",
        "",
        "## 维度汇总",
        "",
        "| 维度 | 细项（已授权） | 覆盖率 | 充分率 | 验证率 | 矛盾 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for d in report.dimensions:
        lines.append(
            f"| {d.dimension_id} {d.name} | {d.consented}/{d.facets} | {_pct(d.covered)} | {_pct(d.sufficient)} "
            f"| {_pct(d.verified)} | {d.conflicts} |"
        )
    lines += [
        "",
        "## 细项 × 来源（证据场合数）",
        "",
        "| 细项 | 等级 | 充分度 | 已确认 | 被问 / 答不上 | " + " | ".join(SOURCE_KIND_LABELS[k] for k in kinds) + " |",
        "| --- | --- | ---: | ---: | ---: | " + " | ".join("---:" for _ in kinds) + " |",
    ]
    for f in report.facets:
        level = LEVEL_LABELS[f.level] if f.consented else "未授权"
        cells = [str(f.by_kind.get(k, 0) or "") for k in kinds]
        flag = "（矛盾）" if f.conflicts else ""
        demand = f"{f.asked} / {f.abstained}" if f.asked else ""
        lines.append(
            f"| {f.facet_id} {f.name}{flag} | {level} | {f.sufficiency:.2f} | {f.confirmed or ''} | {demand} | "
            + " | ".join(cells)
            + " |"
        )
    lines += ["", "## 下一步采集建议", ""]
    if not report.suggestions:
        lines.append("所有已授权细项都已验证。")
    for s in report.suggestions[:max_suggestions]:
        where = "、".join(SOURCE_KIND_LABELS[k] for k in s.sources) or "补测试题"
        lines.append(f"- {s.facet_id} {s.name}：{s.reason}；建议来源：{where}")
    if len(report.suggestions) > max_suggestions:
        lines.append(f"- 另有 {len(report.suggestions) - max_suggestions} 个细项待补")
    return "\n".join(lines) + "\n"
