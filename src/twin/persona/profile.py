"""Build the persona profile from the stored expressions.

1. Chunk: the person's own expressions of each source, in order, numbered, with what each answered (context).
2. Extract: per chunk, one LLM call returns candidate conclusions, each tagged with a facet and backed by verbatim
   quotes of numbered entries; a quote that cannot be found in its entry is dropped, and so is a candidate left
   without evidence. Facets of consent-gated dimensions are offered only after the person answered such a
   questionnaire question.
3. Merge: per facet, one LLM call groups candidates that state the same underlying trait and flags a contradiction
   between what the person says about themself and what they do.

Both steps are incremental: a chunk already extracted (same source, entries and prompt version) is not sent again,
and a facet whose candidates did not change is not merged again.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Literal

from pydantic import BaseModel, Field

from ..config import Settings
from ..identity import Decision
from ..llm import LLM, retry_truncated
from ..util import Progress, run_parallel, verify_quote
from .dimensions import FACET_BY_ID, FACETS, facet_guide, requires_consent
from .items import PersonaCandidate, PersonaItem, PEvidence
from .schema import Expression, Source, SourceKind, evidence_class
from .sources import expression_view
from .store import PersonaStore

PROMPT_VERSION = "persona-v2"
CHUNK_CHARS = 6000
ENTRY_CHARS = 1500
CONTEXT_CHARS = 300
MAX_MERGE_CANDIDATES = 80
MAX_QUOTES = 3
STYLE_DIMENSION = "D6"


STALE_PROFILE_NOTICE = "资料或授权有变化，尚未重新构建；档案和聊天仍基于上次构建"


def profile_stale(store: PersonaStore) -> bool:
    built_at = store.get_meta("built_at")
    if built_at is None:
        return bool(store.list_sources())
    changed_at = store.get_meta("sources_changed_at")
    if changed_at is None:
        return False
    # Legacy built_at values are local naive timestamps; new timestamps carry UTC offsets.
    return dt.datetime.fromisoformat(changed_at).astimezone(dt.UTC) > dt.datetime.fromisoformat(built_at).astimezone(
        dt.UTC
    )


@dataclass(frozen=True)
class SourceMemory:
    expressions_total: int
    expressions_target: int
    expressions_others: int
    items_supported: int
    facets: list[dict[str, str]]
    contributes_nothing: bool
    build_status: Literal["not_built", "remembered", "no_items"]


def source_memories(store: PersonaStore) -> dict[str, SourceMemory]:
    """Query current, non-rejected profile support via expression IDs, once per source and item."""
    expressions = store.list_expressions(include_held_out=True)
    owners = {e.expression_id: e.source_id for e in expressions}
    totals: dict[str, int] = {}
    targets: dict[str, int] = {}
    supported: dict[str, set[str]] = {}
    facets: dict[str, set[str]] = {}
    for e in expressions:
        totals[e.source_id] = totals.get(e.source_id, 0) + 1
        targets[e.source_id] = targets.get(e.source_id, 0) + int(e.is_target)
    for item in store.list_items():
        for source_id in {owners[e.expression_id] for e in item.evidence if e.expression_id in owners}:
            supported.setdefault(source_id, set()).add(item.item_id)
            facets.setdefault(source_id, set()).add(item.facet_id)
    built_at = store.get_meta("built_at")
    result: dict[str, SourceMemory] = {}
    for source in store.list_sources():
        sid = source.source_id
        count = len(supported.get(sid, set()))
        built = built_at is not None and store.get_meta(f"source_pending:{sid}") is None
        result[sid] = SourceMemory(
            expressions_total=totals.get(sid, 0),
            expressions_target=targets.get(sid, 0),
            expressions_others=totals.get(sid, 0) - targets.get(sid, 0),
            items_supported=count,
            facets=[{"facet_id": fid, "name": FACET_BY_ID[fid].name} for fid in sorted(facets.get(sid, set()))],
            contributes_nothing=count == 0,
            build_status="not_built" if not built else "remembered" if count else "no_items",
        )
    return result


# ---------------------------------------------------------------- chunks


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    source: Source
    entries: tuple[Expression, ...]
    text: str


def _clip(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_entry(n: int, e: Expression) -> str:
    head = " · ".join(x for x in (e.date.isoformat() if e.date else "", e.channel) if x)
    lines = [f"[{n}] {head}".rstrip()]
    if e.context:
        lines.append(f"语境：{_clip(e.context, CONTEXT_CHARS)}")
    lines.append(f"{'记述' if e.narrated else '本人'}：{_clip(e.text, ENTRY_CHARS)}")
    return "\n".join(lines)


def consented_facets(store: PersonaStore) -> frozenset[str]:
    """Latest ledger decision per gated facet; without an event, retain legacy questionnaire derivation."""
    latest = {event.scope: event.decision for event in store.consent_events()}
    answered: set[str] = set()
    declined: set[str] = set()
    for source in store.list_sources(SourceKind.QUESTIONNAIRE):
        declined.update(source.declined_facets)
        for e in store.list_expressions(source.source_id):
            answered.update(e.facets_hint)
    return frozenset(
        f.facet_id
        for f in FACETS
        if not requires_consent(f.facet_id)
        or (
            latest[f"facet:{f.facet_id}"] is Decision.GRANT
            if f"facet:{f.facet_id}" in latest
            else f.facet_id in answered - declined
        )
    )


def chunks_for(store: PersonaStore, source: Source, allowed: frozenset[str], settings: Settings) -> list[Chunk]:
    entries = expression_view(store, settings, source_id=source.source_id, target_only=True)
    chunks: list[Chunk] = []
    current: list[Expression] = []
    size = 0

    def close() -> None:
        if not current:
            return
        text = "\n\n".join(render_entry(n, e) for n, e in enumerate(current, 1))
        key = "\x1f".join([PROMPT_VERSION, source.source_id, ",".join(sorted(allowed)), text])
        chunk_id = "ch_" + hashlib.sha256(key.encode()).hexdigest()[:16]
        chunks.append(Chunk(chunk_id, source, tuple(current), text))

    for e in entries:
        length = len(render_entry(0, e))
        if current and size + length > CHUNK_CHARS:
            close()
            current, size = [], 0
        current.append(e)
        size += length
    close()
    return chunks


# ---------------------------------------------------------------- extract


class QuoteRefDraft(BaseModel):
    n: int = Field(description="引用的条目编号，即方括号里的数字")
    quote: str = Field(description="从该条目“本人：”或“记述：”之后逐字复制的片段，不改写、不拼接")
    own_words: bool = Field(
        default=False, description="“记述”条目里，这段引文是他本人说的话或写的文字（直接引语、书信、奏折）时为 true"
    )


class CandidateDraft(BaseModel):
    facet_id: str = Field(description="细项编号，如 3.1")
    statement: str = Field(description="用第三人称写的一条具体结论，以“他”开头，一句话")
    applies_when: str = Field(default="", description="这条结论适用的情境；普遍适用时留空")
    quotes: list[QuoteRefDraft] = Field(description=f"支持这条结论的原话，1 到 {MAX_QUOTES} 条")


class ExtractDraft(BaseModel):
    items: list[CandidateDraft]


EXTRACT_SYSTEM = """\
你在为{name}建立人格档案。用户消息里是关于{name}的一组资料，每条有编号，"语境"是这句话在回应什么，\
"本人"后面是{name}自己的原话，"记述"后面是别人写的关于{name}的叙述。来源类型：{source_kind}（{evidence_note}）。
{source_rules}

请从中提炼关于{name}这个人的结论，每条归入下面一个细项：
{facets}

规则：
1. 只写有原文支撑的结论，每条至少引用 1 条、最多 {max_quotes} 条。quote 必须从对应编号条目"本人："或"记述："之后\
逐字复制，不改写、不拼接、不加省略号；不能引用"语境"里别人说的话。
2. 结论要具体，能指导别人预测他会怎么想、怎么说、怎么做。写"他看重回款，首付不到账不开工"，不写"他做事认真"。
3. 一条结论只讲一件事，只归一个细项；同一件事有多处原话就合在一条里引用。
4. 不写对任何具体他人的评价，不记录别人的隐私；涉及他人时只记录{name}自己的做法和观点。
5. 寒暄、事务性的只言片语（"好的""收到"）不提炼。表达风格类细项（6.x）可以根据他的用词、句式、语气提炼，\
引用最能体现这种风格的原话。
6. 没有值得提炼的内容时，返回空列表。"""

_SOURCE_RULES = {
    SourceKind.BIOGRAPHY: """
这是第三人称的传记类资料，读的时候注意：
- 叙述里的"公""他""其"等指的就是{name}；作者的评论、赞誉和事后总结不是{name}的想法，不要据此下结论。
- 重点提炼他做选择时的取舍和理由、坚持的原则、看问题的方式、待人处事的做法：从他做了什么、在两难时选了什么、\
他自己怎么说的来推断。任职、升迁、年龄、荣誉、行程等履历事实，只有体现了他的选择或态度时才写。
- 引文是他本人说的话或写的文字（"公曰""奏称""谕""致书"后面的内容、书信、奏折、日记）时，own_words 设为 true；\
作者的叙述设为 false。表达风格类细项（6.x）只能引用 own_words 为 true 的引文。
""",
}

_EVIDENCE_NOTES = {
    "self_report": "本人自述：这是他对自己的描述，结论照实记录他怎么说",
    "behavior": "实际行为：这是他在真实场合的言行",
}


def _candidate_id(chunk_id: str, i: int) -> str:
    return "pc_" + hashlib.sha256(f"{chunk_id}\x1f{i}".encode()).hexdigest()[:16]


def extract_chunk(llm: LLM, chunk: Chunk, allowed: frozenset[str], settings: Settings) -> list[PersonaCandidate]:
    klass = evidence_class(chunk.source.kind)
    system = EXTRACT_SYSTEM.format(
        name=settings.target_name,
        source_kind=chunk.source.kind.value,
        evidence_note=_EVIDENCE_NOTES[klass.value],
        source_rules=_SOURCE_RULES.get(chunk.source.kind, "").format(name=settings.target_name),
        facets=facet_guide(allowed),
        max_quotes=MAX_QUOTES,
    )
    draft = retry_truncated(
        lambda: llm.structured(system=system, user=chunk.text, schema=ExtractDraft, effort=settings.llm.effort_extract)
    )
    candidates: list[PersonaCandidate] = []
    for i, item in enumerate(draft.items):
        facet = item.facet_id.strip()
        if facet not in allowed or not item.statement.strip():
            continue
        evidence: list[PEvidence] = []
        for ref in item.quotes[:MAX_QUOTES]:
            if not 1 <= ref.n <= len(chunk.entries):
                continue
            entry = chunk.entries[ref.n - 1]
            own_words = not entry.narrated or ref.own_words
            if not own_words and FACET_BY_ID[facet].dimension_id == STYLE_DIMENSION:
                continue  # how he talks can only rest on his own words, never on a narrator's
            found = verify_quote(ref.quote, entry.text)
            if found is None or any(e.expression_id == entry.expression_id and e.quote == found for e in evidence):
                continue
            evidence.append(
                PEvidence(
                    expression_id=entry.expression_id,
                    source_id=entry.source_id,
                    source_kind=chunk.source.kind,
                    evidence_class=klass,
                    date=entry.date,
                    quote=found,
                    own_words=own_words,
                )
            )
        if evidence:
            candidates.append(
                PersonaCandidate(
                    candidate_id=_candidate_id(chunk.chunk_id, i),
                    chunk_id=chunk.chunk_id,
                    facet_id=facet,
                    statement=item.statement.strip(),
                    applies_when=item.applies_when.strip(),
                    evidence=evidence,
                )
            )
    return candidates


# ---------------------------------------------------------------- merge


class MergedDraft(BaseModel):
    statement: str = Field(description="合并后的结论，第三人称，以“他”开头，一句话")
    applies_when: str = Field(default="")
    candidate_ids: list[str] = Field(description="归入这一条的候选编号")
    conflict: str = Field(
        default="",
        description="成员之间互相矛盾时（尤其是本人自述与实际行为不一致）用一句话说明矛盾；没有矛盾留空",
    )


class MergeDraft(BaseModel):
    items: list[MergedDraft]


MERGE_SYSTEM = """\
下面是从{name}的不同资料里提炼出的一组结论，都属于细项"{facet_id} {facet_name}"（{facet_desc}）。\
每条有编号、来源类别（本人自述 / 实际行为）和日期。

请把讲同一个底层特点的结论归为一组，每组写一条合并后的结论：
1. 每个候选编号必须归入且只归入一组；讲的不是同一件事就不要合并。
2. 合并后的结论要保留各成员的具体内容，不要概括成空话；适用情境不同时写进 applies_when。
3. 同一组里本人自述和实际行为方向相反（例如自述"看重数据"，行为上总是凭直觉拍板），或者两次行为互相矛盾，\
在 conflict 里用一句话写明矛盾，结论按实际行为写；没有矛盾时 conflict 留空。"""


def _render_candidates(candidates: Sequence[PersonaCandidate]) -> str:
    lines: list[str] = []
    for c in candidates:
        classes = "、".join(
            sorted({"本人自述" if e.evidence_class == "self_report" else "实际行为" for e in c.evidence})
        )
        dates = sorted({e.date.isoformat() for e in c.evidence if e.date})
        when = f"（适用：{c.applies_when}）" if c.applies_when else ""
        lines.append(f"[{c.candidate_id}] {classes}，{'、'.join(dates) or '无日期'}：{c.statement}{when}")
    return "\n".join(lines)


def _item_from(
    facet_id: str, statement: str, applies_when: str, members: Sequence[PersonaCandidate], conflict: str
) -> PersonaItem:
    ids = sorted(c.candidate_id for c in members)
    evidence: list[PEvidence] = []
    for c in members:
        for e in c.evidence:
            if not any(x.expression_id == e.expression_id and x.quote == e.quote for x in evidence):
                evidence.append(e)
    evidence.sort(key=lambda e: (e.date or dt.date.min, e.expression_id))
    return PersonaItem(
        item_id="pi_" + hashlib.sha256("\x1f".join([facet_id, *ids]).encode()).hexdigest()[:12],
        facet_id=facet_id,
        statement=statement,
        applies_when=applies_when,
        evidence=evidence,
        member_candidate_ids=ids,
        conflict=conflict.strip(),
    )


def merge_facet(
    llm: LLM, facet_id: str, candidates: Sequence[PersonaCandidate], settings: Settings
) -> list[PersonaItem]:
    if len(candidates) == 1:
        c = candidates[0]
        return [_item_from(facet_id, c.statement, c.applies_when, [c], "")]
    items: list[PersonaItem] = []
    ordered = sorted(candidates, key=lambda c: (min(e.date or dt.date.min for e in c.evidence), c.candidate_id))
    for start in range(0, len(ordered), MAX_MERGE_CANDIDATES):
        batch = ordered[start : start + MAX_MERGE_CANDIDATES]
        facet = FACET_BY_ID[facet_id]
        system = MERGE_SYSTEM.format(
            name=settings.target_name, facet_id=facet_id, facet_name=facet.name, facet_desc=facet.description
        )
        call = partial(
            llm.structured,
            system=system,
            user=_render_candidates(batch),
            schema=MergeDraft,
            effort=settings.llm.effort_extract,
        )
        draft = retry_truncated(call)
        by_id = {c.candidate_id: c for c in batch}
        used: set[str] = set()
        for group in draft.items:
            members = [by_id[i] for i in dict.fromkeys(group.candidate_ids) if i in by_id and i not in used]
            if not members or not group.statement.strip():
                continue
            used.update(c.candidate_id for c in members)
            items.append(
                _item_from(facet_id, group.statement.strip(), group.applies_when.strip(), members, group.conflict)
            )
        items.extend(
            _item_from(facet_id, c.statement, c.applies_when, [c], "") for c in batch if c.candidate_id not in used
        )
    return items


# ---------------------------------------------------------------- build


@dataclass(frozen=True)
class FacetItemDiff:
    added: int = 0
    changed: int = 0
    removed: int = 0


@dataclass
class BuildReport:
    sources: int = 0
    chunks_total: int = 0
    chunks_extracted: int = 0
    chunks_dropped: int = 0
    candidates: int = 0
    facets_merged: int = 0
    items: int = 0
    failures: list[str] = field(default_factory=list)
    facet_diffs: dict[str, FacetItemDiff] = field(default_factory=dict)

    @property
    def items_added(self) -> int:
        return sum(d.added for d in self.facet_diffs.values())

    @property
    def items_changed(self) -> int:
        return sum(d.changed for d in self.facet_diffs.values())

    @property
    def items_removed(self) -> int:
        return sum(d.removed for d in self.facet_diffs.values())

    @property
    def facets_changed(self) -> int:
        return sum(bool(d.added or d.changed or d.removed) for d in self.facet_diffs.values())

    def change_summary(self) -> str:
        return (
            f"新增 {self.items_added} 条、修改 {self.items_changed} 条、删除 {self.items_removed} 条，"
            f"涉及 {self.facets_changed} 个细项"
        )


def _merge_key(candidates: Sequence[PersonaCandidate]) -> str:
    return hashlib.sha256(
        "\x1f".join([PROMPT_VERSION, *sorted(c.candidate_id for c in candidates)]).encode()
    ).hexdigest()


def build_profile(store: PersonaStore, llm: LLM, settings: Settings, progress: Progress | None = None) -> BuildReport:
    report = BuildReport()
    sources_changed_at = store.get_meta("sources_changed_at")
    built_at = dt.datetime.now(dt.UTC).isoformat()
    allowed = consented_facets(store)

    def safe_progress(message: str) -> None:
        if progress:
            progress(": ".join(message.split(": ")[:2]) if message.startswith("FAILED ") else message)

    sources = store.list_sources()
    report.sources = len(sources)
    chunks = [c for s in sources for c in chunks_for(store, s, allowed, settings)]
    report.chunks_total = len(chunks)
    report.chunks_dropped = store.drop_stale_chunks({c.chunk_id for c in chunks})
    todo = [c for c in chunks if not store.has_chunk(c.chunk_id)]

    def persist(chunk: Chunk, outcome: list[PersonaCandidate] | Exception) -> None:
        if isinstance(outcome, Exception):
            report.failures.append(f"extract {chunk.chunk_id}: {type(outcome).__name__}")
        else:
            store.put_chunk(chunk.chunk_id, chunk.source.source_id, outcome)
            report.chunks_extracted += 1

    run_parallel(
        lambda c: extract_chunk(llm, c, allowed, settings),
        todo,
        settings.max_workers,
        safe_progress,
        label=lambda c: f"persona extract {c.chunk_id}",
        on_result=persist,
    )
    candidates = [c for c in store.list_candidates() if c.facet_id in allowed]
    report.candidates = len(candidates)
    by_facet: dict[str, list[PersonaCandidate]] = {}
    for c in candidates:
        by_facet.setdefault(c.facet_id, []).append(c)
    jobs = [
        (facet.facet_id, by_facet.get(facet.facet_id, []))
        for facet in FACETS
        if store.get_meta(f"merge:{facet.facet_id}") != _merge_key(by_facet.get(facet.facet_id, []))
    ]

    def merge(job: tuple[str, list[PersonaCandidate]]) -> list[PersonaItem]:
        facet_id, members = job
        return merge_facet(llm, facet_id, members, settings) if members else []

    def save(job: tuple[str, list[PersonaCandidate]], outcome: list[PersonaItem] | Exception) -> None:
        facet_id, members = job
        if isinstance(outcome, Exception):
            report.failures.append(f"merge {facet_id}: {type(outcome).__name__}")
            return
        before = {i.item_id: i.statement for i in store.list_items(facet_id, raw=True)}
        store.replace_facet_items(facet_id, outcome)
        after = {i.item_id: i.statement for i in store.list_items(facet_id, raw=True)}
        report.facet_diffs[facet_id] = FacetItemDiff(
            added=len(after.keys() - before.keys()),
            changed=sum(before[i] != after[i] for i in before.keys() & after.keys()),
            removed=len(before.keys() - after.keys()),
        )
        store.set_meta(f"merge:{facet_id}", _merge_key(members))
        report.facets_merged += 1

    run_parallel(
        merge, jobs, settings.max_workers, safe_progress, label=lambda j: f"persona merge {j[0]}", on_result=save
    )
    report.items = len(store.list_items())
    if not report.failures:
        store.mark_profile_built(built_at, sources_changed_at)
    return report
