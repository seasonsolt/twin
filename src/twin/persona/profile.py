"""Build the persona profile from the stored expressions.

1. Chunk: the person's own expressions of each source, in order, numbered, with what each answered (context).
2. Extract: per chunk, one LLM call returns candidate conclusions, each tagged with a facet and backed by verbatim
   quotes of numbered entries; a quote that cannot be found in its entry is dropped, and so is a candidate left
   without evidence. Facets of consent-gated dimensions are offered only after the person answered such a
   questionnaire question.
3. Merge: per facet, one LLM call groups candidates that state the same underlying trait and flags a contradiction
   between incompatible conclusions.

Both steps are incremental: a chunk already extracted (same source, entries and prompt version) is not sent again,
and a facet whose candidates did not change is not merged again.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from functools import partial
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..config import Settings
from ..llm import LLM, LLMError, LLMTruncated, failure_summary, retry_truncated
from ..usage import call_totals, collect_calls
from ..util import Progress, run_parallel, verify_quote
from .dimensions import FACET_BY_ID, FACETS, facet_guide, requires_consent
from .items import FACET_SAMPLE_CHARS, ExtractStats, PersonaCandidate, PersonaItem, PEvidence
from .kernel import KERNEL, LEGACY_KERNEL, content_digest, kernel_json, rebuild_scope
from .kernel import PROMPT_VERSION as PROMPT_VERSION
from .schema import Expression, Source, SourceKind, evidence_class
from .sources import expression_view
from .store import PersonaStore

CHUNK_CHARS = 6000
ENTRY_CHARS = 1500
CONTEXT_CHARS = 300
MAX_MERGE_CANDIDATES = 80
MAX_QUOTES = 3
STYLE_DIMENSION = "D6"


STALE_PROFILE_NOTICE = "资料有变化，尚未重新构建；档案和聊天仍基于上次构建"
KERNEL_STALE_NOTICE = "记忆内核已升级，正在按新版本重新整理；整理完成前沿用旧档案"
KERNEL_AWAITING_NOTICE = "记忆内核已升级，需要管理员确认后重新整理；目前沿用旧档案"


def stale_reason(store: PersonaStore) -> Literal["sources", "kernel", None]:
    built_at = store.get_meta("built_at")
    if built_at is None:
        return "sources" if store.count_sources() else None
    changed_at = store.get_meta("sources_changed_at")
    if (
        changed_at
        and built_at
        and dt.datetime.fromisoformat(changed_at).astimezone(dt.UTC)
        > dt.datetime.fromisoformat(built_at).astimezone(dt.UTC)
    ):
        return "sources"
    return "kernel" if rebuild_scope(store.kernel_built(), KERNEL) != "none" else None


def profile_stale(store: PersonaStore) -> bool:
    return stale_reason(store) is not None


def pending_chunks(store: PersonaStore, settings: Settings) -> int:
    allowed = consented_facets(store)
    sources = [s for s in store.list_sources() if s.media_status in (None, "ready")]
    return sum(not store.has_chunk(chunk.chunk_id) for chunk in corpus_chunks(store, sources, allowed, settings))


@dataclass(frozen=True)
class SourceMemory:
    expressions_total: int
    expressions_target: int
    expressions_others: int
    items_supported: int
    facets: list[dict[str, str]]
    contributes_nothing: bool
    build_status: Literal["not_built", "remembered", "no_items"]
    chunks_extracted: int = 0
    # Summed over the chunks extracted since counts were kept; None when there is none.
    extraction: ExtractStats | None = None
    # Why a built source supports no memory, when the counts tell; empty otherwise.
    nothing_found_reason: str = ""


def nothing_found_reason(stats: ExtractStats | None) -> str:
    if stats is None:
        return ""
    if stats.returned == 0:
        return "模型没有从中提炼出结论"
    if stats.kept:
        return f"提炼出 {stats.kept} 条结论，但都没有留在当前档案里（可能已被否定）"
    causes = [
        f"{label} {n} 处"
        for label, n in (
            ("引文与原文对不上", stats.quotes_unmatched),
            ("引用了不存在的条目", stats.quotes_misnumbered),
            ("表达风格引用了他人记述", stats.quotes_narrated_style),
        )
        if n
    ]
    if stats.off_facet and stats.unknown_facets:
        common = sorted(stats.unknown_facets.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        written = "、".join(f"“{facet}”×{n}" for facet, n in common)
        causes.append(f"细项不在可用列表里 {stats.off_facet} 条（模型写的是 {written}）")
    elif stats.off_facet:  # counted before facets and empty statements were told apart
        causes.append(f"细项不可用或结论为空 {stats.off_facet} 条")
    if stats.empty_statement:
        causes.append(f"结论为空 {stats.empty_statement} 条")
    return f"模型提炼了 {stats.returned} 条结论，校验后全部丢弃：" + "，".join(causes)


def source_memories(store: PersonaStore, sources: Sequence[Source] | None = None) -> dict[str, SourceMemory]:
    """Query current, non-rejected profile support via expression IDs, once per source and item, for ``sources``
    (default: all of them). Read with SQL aggregates, so it stays cheap with tens of thousands of items."""
    counts = store.expression_counts()
    owners = store.expression_owners()
    supported: dict[str, set[str]] = {}
    facets: dict[str, set[str]] = {}
    for item_id, facet_id, expression_id in store.item_support():
        if (source_id := owners.get(expression_id)) is not None:
            supported.setdefault(source_id, set()).add(item_id)
            facets.setdefault(source_id, set()).add(facet_id)
    built_at = store.get_meta("built_at")
    pending = store.pending_source_ids()
    extracted = store.extraction_stats()
    result: dict[str, SourceMemory] = {}
    for source in store.list_sources() if sources is None else sources:
        sid = source.source_id
        total, target = counts.get(sid, (0, 0))
        count = len(supported.get(sid, set()))
        built = built_at is not None and sid not in pending
        chunks, stats = extracted.get(sid, (0, None))
        reason = "" if not built or count else nothing_found_reason(stats) if target else "资料里没有识别出本人说的话"
        result[sid] = SourceMemory(
            expressions_total=total,
            expressions_target=target,
            expressions_others=total - target,
            items_supported=count,
            facets=[{"facet_id": fid, "name": FACET_BY_ID[fid].name} for fid in sorted(facets.get(sid, set()))],
            contributes_nothing=count == 0,
            build_status="not_built" if not built else "remembered" if count else "no_items",
            chunks_extracted=chunks,
            extraction=stats,
            nothing_found_reason=reason,
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
    """Allow gated facets only when answered in a questionnaire and not declined."""
    answered: set[str] = set()
    declined: set[str] = set()
    for source in store.list_sources(SourceKind.QUESTIONNAIRE):
        declined.update(source.declined_facets)
        for e in store.list_expressions(source.source_id):
            answered.update(e.facets_hint)
    return frozenset(
        f.facet_id for f in FACETS if not requires_consent(f.facet_id) or f.facet_id in answered - declined
    )


def chunks_for(store: PersonaStore, source: Source, allowed: frozenset[str], settings: Settings) -> list[Chunk]:
    return _chunk(source, expression_view(store, settings, source_id=source.source_id, target_only=True), allowed)


def corpus_chunks(
    store: PersonaStore, sources: Sequence[Source], allowed: frozenset[str], settings: Settings
) -> list[Chunk]:
    """The chunks of every source in ``sources``, cut from one view of the whole corpus: ``chunks_for`` per source
    would read and pseudonymise every expression once per source."""
    by_source: dict[str, list[Expression]] = {}
    for e in expression_view(store, settings, target_only=True):
        by_source.setdefault(e.source_id, []).append(e)
    return [c for s in sources for c in _chunk(s, by_source.get(s.source_id, []), allowed)]


def _render(entries: Sequence[Expression]) -> str:
    return "\n\n".join(render_entry(n, e) for n, e in enumerate(entries, 1))


def _chunk(source: Source, entries: Sequence[Expression], allowed: frozenset[str]) -> list[Chunk]:
    chunks: list[Chunk] = []
    current: list[Expression] = []
    size = 0

    def close() -> None:
        if not current:
            return
        text = _render(current)
        key = "\x1f".join([KERNEL.prompt, source.source_id, ",".join(sorted(allowed)), text])
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
        default=False, description="“记述”条目里，这段引文是他本人说的话或写的文字（直接引语、书信）时为 true"
    )


class CandidateDraft(BaseModel):
    facet_id: str = Field(description="细项编号，如 3.1")
    statement: str = Field(description="一条具体结论，一句话，不加人称代词主语（我、他、她等）")
    applies_when: str = Field(default="", description="这条结论适用的情境；普遍适用时留空")
    quotes: list[QuoteRefDraft] = Field(description=f"支持这条结论的原话，1 到 {MAX_QUOTES} 条")


class ExtractDraft(BaseModel):
    items: list[CandidateDraft]


EXTRACT_SYSTEM = """\
你在为{name}建立人格档案。用户消息里是关于{name}的一组资料，每条有编号，"语境"是这句话在回应什么，\
"本人"后面是{name}自己的原话，"记述"后面是别人写的关于{name}的叙述。来源类型：{source_kind}（{evidence_note}）。

请从中提炼关于{name}这个人的结论，每条归入下面一个细项：
{facets}

规则：
1. 只写有原文支撑的结论，每条至少引用 1 条、最多 {max_quotes} 条。quote 必须从对应编号条目"本人："或"记述："之后\
逐字复制，不改写、不拼接、不加省略号；不能引用"语境"里别人说的话。
2. 结论要具体，不加人称代词主语（我、他、她等）。例如"在成都做产品经理"、"做决定前喜欢先睡一觉"，不写"他做事认真"。\
原话里的专有名称和数字原样写进结论，不要概括掉：人名、宠物名，书、剧、电影、节目、歌曲、歌单等作品名，品牌型号、\
地名，数量、金额、时长、次数、比例；专有名称可保留外文原文，其余照常用中文写。原话提到的时间（今天、上周、\
三周前）、东西的来源（谁送的、在哪买的）和同去的人也一并写上。例如写"上周在宜家买了 3 盆多肉"，不写"在养多肉"；\
写"读完了《百年孤独》"，不写"喜欢读小说"。
3. 一条结论只讲一件事，只归一个细项；同一件事有多处原话就合在一条里引用。做过、买过、去过、认识了谁这类具体经历，\
记成这件事本身，不要只概括成兴趣或习惯；能看出兴趣时另记一条。只见到一次的做法记成这一次的事，不要推成习惯、\
一贯的偏好或说话方式；本人明说的偏好和习惯照记。
4. {name}说起的身边人的情况（家人、朋友、同事等是谁，做了什么，近况和变化）照实记录：结论以这个人开头，\
原话说了和{name}的关系就写上，没说不要补，如"朋友小林上个月搬到了杭州"、"前同事老周现在带一个 8 人团队"；\
家人归 9.3，同事、上级归 1.4，朋友和其他人归 7.3。不写对具体他人的评价和褒贬（如"小林做事靠谱"）。
5. 寒暄、事务性的只言片语（"好的""收到"）不提炼。表达风格类细项（6.x）可以根据他的用词、句式、语气提炼，\
引用最能体现这种风格的原话。
6. 他常请别人帮忙（润色邮件、改文案、问问题）：草稿和问题里顺带透露的个人情况，如住在哪、做什么、身体状况、\
作息、喜好、去过的地方、正在做的事，同样要提炼，按事实记录。每个不同的具体情况单独一条，不要只挑几条代表。
7. 他反复问起或主动关心某个话题，说明他关注它，可以记一条“关注……”（如“关注地中海饮食为什么流行”）；\
措辞要写明是关注或好奇，不要写成喜欢或擅长。提问里透露的他自己的情况（如问“我母亲那边有糖尿病，我该怎么吃”\
透露了母系有糖尿病家族史），按规则 6 另记一条事实，不要只记成关注。健康状况、病史、治疗经历也照实记录。
8. 没有值得提炼的内容时，返回空列表。{coverage}"""

# Questionnaire answers are each a deliberate statement, and most are never retrieved verbatim later, so a stance
# left out of every conclusion is effectively lost to the twin.
QUESTIONNAIRE_COVERAGE = """
9. 这是问卷资料：凡是表明身份、立场、价值观、偏好、习惯或行为倾向的回答，都要被至少一条结论引用，\
不要只挑几条代表；只有空白、纯事务性或不涉及本人的回答可以不覆盖。同一主题的几个回答合成一条结论，\
引用最能代表的原话。"""

_EVIDENCE_NOTES = {
    "self_report": "本人自述：这是他对自己的描述，结论照实记录他怎么说",
    "behavior": "实际行为：这是他在真实场合的言行",
}


def _candidate_id(chunk_id: str, i: int) -> str:
    return "pc_" + hashlib.sha256(f"{chunk_id}\x1f{i}".encode()).hexdigest()[:16]


def prompt_fingerprint() -> str:
    """Everything that shapes extraction and merge output apart from the taxonomy; pinned per PROMPT_VERSION."""
    return content_digest(
        {
            "extract": EXTRACT_SYSTEM,
            "merge": MERGE_SYSTEM,
            "evidence": _EVIDENCE_NOTES,
            "questionnaire": QUESTIONNAIRE_COVERAGE,
            "max_quotes": MAX_QUOTES,
            "extract_schema": ExtractDraft.model_json_schema(),
            "merge_schema": MergeDraft.model_json_schema(),
        }
    )


_FACET_NUMBER = re.compile(r"(?<![\d.．])(\d{1,2})\s*[.．]\s*(\d{1,2})(?![\d.．])")


def facet_id(written: str) -> str:
    """The facet a model named, read from how models write it besides the bare id: "8.2 正在做的事", "8.2：…",
    "细项 8．2". Anything else is returned as written, and dropped as a facet that is not offered."""
    written = written.strip()
    if written in FACET_BY_ID:
        return written
    match = _FACET_NUMBER.search(written)
    return f"{int(match[1])}.{int(match[2])}" if match else written


@dataclass(frozen=True)
class Extraction:
    candidates: list[PersonaCandidate]
    stats: ExtractStats


def extract_chunk(llm: LLM, chunk: Chunk, allowed: frozenset[str], settings: Settings) -> Extraction:
    """Extract a chunk; one whose reply is cut off twice is extracted again as two halves, down to single entries,
    and a single entry that is still cut off fails the chunk. The halves' candidates keep the chunk's id, so the
    chunk is stored, and retried after a failure, as one."""
    try:
        return _extract(llm, chunk, allowed, settings)
    except LLMTruncated:
        if len(chunk.entries) < 2:
            raise
    middle = len(chunk.entries) // 2
    parts = [
        extract_chunk(llm, Chunk(f"{chunk.chunk_id}/{n}", chunk.source, entries, _render(entries)), allowed, settings)
        for n, entries in ((1, chunk.entries[:middle]), (2, chunk.entries[middle:]))
    ]
    stats = parts[0].stats + parts[1].stats
    stats.splits += 1
    return Extraction([c.model_copy(update={"chunk_id": chunk.chunk_id}) for p in parts for c in p.candidates], stats)


def _extract(llm: LLM, chunk: Chunk, allowed: frozenset[str], settings: Settings) -> Extraction:
    klass = evidence_class(chunk.source.kind)
    system = EXTRACT_SYSTEM.format(
        name=settings.target_name,
        source_kind=chunk.source.kind.value,
        evidence_note=_EVIDENCE_NOTES[klass.value],
        facets=facet_guide(allowed),
        max_quotes=MAX_QUOTES,
        coverage=QUESTIONNAIRE_COVERAGE if chunk.source.kind == SourceKind.QUESTIONNAIRE else "",
    )
    draft = retry_truncated(
        lambda: llm.structured(
            system=system,
            user=chunk.text,
            schema=ExtractDraft,
            effort=settings.llm.effort_extract,
            reasoning_effort=settings.llm.effective_reasoning_effort_extract,
        )
    )
    candidates: list[PersonaCandidate] = []
    stats = ExtractStats(returned=len(draft.items))
    for i, item in enumerate(draft.items):
        facet = facet_id(item.facet_id)
        if not item.statement.strip():
            stats.empty_statement += 1
            continue
        if facet not in allowed:
            stats.off_facet += 1
            sample = item.facet_id.strip()[:FACET_SAMPLE_CHARS]
            stats.unknown_facets[sample] = stats.unknown_facets.get(sample, 0) + 1
            continue
        evidence: list[PEvidence] = []
        for ref in item.quotes[:MAX_QUOTES]:
            if not 1 <= ref.n <= len(chunk.entries):
                stats.quotes_misnumbered += 1
                continue
            entry = chunk.entries[ref.n - 1]
            own_words = not entry.narrated or ref.own_words
            if not own_words and FACET_BY_ID[facet].dimension_id == STYLE_DIMENSION:
                stats.quotes_narrated_style += 1
                continue  # how he talks can only rest on his own words, never on a narrator's
            found = verify_quote(ref.quote, entry.text)
            if found is None:
                stats.quotes_unmatched += 1
                continue
            if any(e.expression_id == entry.expression_id and e.quote == found for e in evidence):
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
        else:
            stats.unsupported += 1
    stats.kept = len(candidates)
    return Extraction(candidates, stats)


# ---------------------------------------------------------------- merge


class MergedDraft(BaseModel):
    statement: str = Field(description="合并后的结论，一句话，不加人称代词主语（我、他、她等）")
    applies_when: str = Field(default="")
    candidate_ids: list[str] = Field(description="归入这一条的候选编号")
    conflict: str = Field(
        default="",
        description="成员内容有冲突时用一句话说明差别；没有冲突留空",
    )


class MergeDraft(BaseModel):
    items: list[MergedDraft]


MERGE_SYSTEM = """\
下面是从{name}的不同资料里提炼出的一组结论，都属于细项"{facet_id} {facet_name}"（{facet_desc}）。\
每条有编号、来源类别（本人自述 / 实际行为）和日期。

请把讲同一个底层特点的结论归为一组，每组写一条合并后的结论：
1. 每个候选编号必须归入且只归入一组；讲的不是同一件事就不要合并。
2. 合并后的结论要保留具体内容，不加人称代词主语，不要概括成空话；适用情境不同时写进 applies_when。
3. 内容冲突时，优先参考本人实际做过的事；在 conflict 里简短说明差别，不确定时不要替本人下定论。没有冲突时留空。"""


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


class MergeDegraded(Exception):
    """A facet merged only in part: ``items`` keep every candidate, some left unmerged after a model failure.
    Saving them keeps the profile usable; the facet is merged again on the next build."""

    def __init__(self, items: list[PersonaItem], cause: LLMError) -> None:
        super().__init__(failure_summary(cause))
        self.items = items
        self.cause = cause


def merge_facet(
    llm: LLM, facet_id: str, candidates: Sequence[PersonaCandidate], settings: Settings
) -> list[PersonaItem]:
    """Merge a facet's candidates in batches. A batch whose call fails (usually a timeout on a long reply) is
    merged again as two halves; a half that still fails keeps its candidates as separate items, and the facet
    raises ``MergeDegraded`` carrying every item instead of losing them all."""
    if len(candidates) == 1:
        c = candidates[0]
        return [_item_from(facet_id, c.statement, c.applies_when, [c], "")]
    facet = FACET_BY_ID[facet_id]
    system = MERGE_SYSTEM.format(
        name=settings.target_name, facet_id=facet_id, facet_name=facet.name, facet_desc=facet.description
    )

    def merge_batch(batch: Sequence[PersonaCandidate]) -> list[PersonaItem]:
        call = partial(
            llm.structured,
            system=system,
            user=_render_candidates(batch),
            schema=MergeDraft,
            effort=settings.llm.effort_extract,
            reasoning_effort=settings.llm.effective_reasoning_effort_extract,
        )
        draft = retry_truncated(call)
        by_id = {c.candidate_id: c for c in batch}
        used: set[str] = set()
        merged: list[PersonaItem] = []
        for group in draft.items:
            members = [by_id[i] for i in dict.fromkeys(group.candidate_ids) if i in by_id and i not in used]
            if not members or not group.statement.strip():
                continue
            used.update(c.candidate_id for c in members)
            merged.append(
                _item_from(facet_id, group.statement.strip(), group.applies_when.strip(), members, group.conflict)
            )
        merged.extend(
            _item_from(facet_id, c.statement, c.applies_when, [c], "") for c in batch if c.candidate_id not in used
        )
        return merged

    items: list[PersonaItem] = []
    failure: LLMError | None = None
    ordered = sorted(candidates, key=lambda c: (min(e.date or dt.date.min for e in c.evidence), c.candidate_id))
    for start in range(0, len(ordered), MAX_MERGE_CANDIDATES):
        batch = ordered[start : start + MAX_MERGE_CANDIDATES]
        try:
            items.extend(merge_batch(batch))
            continue
        except LLMError as error:
            failure = error
        middle = len(batch) // 2
        for half in (batch[:middle], batch[middle:]):
            if len(half) < 2:
                items.extend(_item_from(facet_id, c.statement, c.applies_when, [c], "") for c in half)
                continue
            try:
                items.extend(merge_batch(half))
            except LLMError:
                items.extend(_item_from(facet_id, c.statement, c.applies_when, [c], "") for c in half)
    if failure is not None:
        raise MergeDegraded(items, failure)
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
    # What this build's extraction calls returned and dropped; ``candidates`` counts every stored one.
    extraction: ExtractStats = field(default_factory=ExtractStats)
    candidates: int = 0
    facets_merged: int = 0
    items: int = 0
    failures: list[str] = field(default_factory=list)
    # Sources with a chunk that failed to extract; the others are remembered when the merge succeeds.
    failed_sources: set[str] = field(default_factory=set)
    merge_failed: bool = False
    # Facets saved after a partial merge (see ``MergeDegraded``); they are merged again on the next build.
    degraded: list[str] = field(default_factory=list)
    facet_diffs: dict[str, FacetItemDiff] = field(default_factory=dict)
    # The model calls this build made (``usage.call_totals``: attempts, retryable errors by cause, tokens, cost).
    calls: dict[str, Any] = field(default_factory=dict)

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
    parts = [KERNEL.prompt, *sorted(c.candidate_id for c in candidates)]
    if KERNEL.taxonomy != "v1":
        parts.insert(1, KERNEL.taxonomy)
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


def build_profile(
    store: PersonaStore,
    llm: LLM,
    settings: Settings,
    progress: Progress | None = None,
    *,
    grant_gated: bool = False,
) -> BuildReport:
    """``grant_gated`` treats every consent-gated facet as allowed; only evaluations use it, to measure what the
    profile could hold with the person's consent. Production builds derive consent from questionnaires."""
    report = BuildReport()
    built = store.kernel_built()
    # Snapshot once per kernel change, before stale extractions are dropped, so a bad kernel can be rolled back.
    if (
        rebuild_scope(built, KERNEL) != "none"
        and store.get_meta("kernel:snapshot") != kernel_json(KERNEL)
        and store.has_extractions()
    ):
        old = built or LEGACY_KERNEL
        store.snapshot(f"{old.prompt}-{old.taxonomy}")
        store.set_meta("kernel:snapshot", kernel_json(KERNEL))
    sources_changed_at = store.get_meta("sources_changed_at")
    built_at = dt.datetime.now(dt.UTC).isoformat()
    allowed = frozenset(f.facet_id for f in FACETS) if grant_gated else consented_facets(store)

    def safe_progress(message: str) -> None:
        if progress:
            progress(": ".join(message.split(": ")[:2]) if message.startswith("FAILED ") else message)

    sources = [s for s in store.list_sources() if s.media_status in (None, "ready")]
    report.sources = len(sources)
    chunks = corpus_chunks(store, sources, allowed, settings)
    report.chunks_total = len(chunks)
    report.chunks_dropped = store.drop_stale_chunks({c.chunk_id for c in chunks})
    todo = [c for c in chunks if not store.has_chunk(c.chunk_id)]
    pending = store.pending_versions([s.source_id for s in sources])
    totals: dict[str, int] = {}
    for chunk in chunks:
        totals[chunk.source.source_id] = totals.get(chunk.source.source_id, 0) + 1
    store.set_build_progress("extract", totals)
    try:
        with collect_calls() as rows:
            _extract_and_merge(store, llm, settings, report, todo, allowed, safe_progress, totals)
    finally:
        store.clear_build_progress()
        report.calls = {"started_at": built_at, "models": sorted({r.model for r in rows}), **call_totals(rows)}
        if rows:  # a build with nothing to do keeps the last real build's record
            store.set_meta("build:last_calls", json.dumps(report.calls, ensure_ascii=False))
    # A build that learned nothing (every chunk failed) is not recorded; one that lost only some sources is.
    if not report.merge_failed and (report.chunks_extracted or not report.failures):
        settled = {sid: value for sid, value in pending.items() if sid not in report.failed_sources}
        store.finish_build(built_at, sources_changed_at, settled, complete=not report.failures, kernel=KERNEL)
    return report


def _extract_and_merge(
    store: PersonaStore,
    llm: LLM,
    settings: Settings,
    report: BuildReport,
    todo: list[Chunk],
    allowed: frozenset[str],
    safe_progress: Progress,
    totals: dict[str, int],
) -> None:
    def persist(chunk: Chunk, outcome: Extraction | Exception) -> None:
        if isinstance(outcome, Exception):
            report.failures.append(f"extract {chunk.chunk_id}: {failure_summary(outcome)}")
            report.failed_sources.add(chunk.source.source_id)
        else:
            store.put_chunk(chunk.chunk_id, chunk.source.source_id, outcome.candidates, outcome.stats)
            report.chunks_extracted += 1
            report.extraction += outcome.stats

    run_parallel(
        lambda c: extract_chunk(llm, c, allowed, settings),
        todo,
        settings.max_workers,
        safe_progress,
        label=lambda c: f"persona extract {c.chunk_id}",
        on_result=persist,
    )
    store.set_build_progress("merge", totals)
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
        if isinstance(outcome, MergeDegraded):
            report.degraded.append(f"merge {facet_id}: {failure_summary(outcome.cause)}")
            items = outcome.items
        elif isinstance(outcome, Exception):
            report.failures.append(f"merge {facet_id}: {failure_summary(outcome)}")
            report.merge_failed = True
            return
        else:
            items = outcome
        before = {i.item_id: i.statement for i in store.list_items(facet_id, raw=True)}
        store.replace_facet_items(facet_id, items)
        after = {i.item_id: i.statement for i in store.list_items(facet_id, raw=True)}
        report.facet_diffs[facet_id] = FacetItemDiff(
            added=len(after.keys() - before.keys()),
            changed=sum(before[i] != after[i] for i in before.keys() & after.keys()),
            removed=len(before.keys() - after.keys()),
        )
        if isinstance(outcome, MergeDegraded):
            return
        store.set_meta(f"merge:{facet_id}", _merge_key(members))
        report.facets_merged += 1

    run_parallel(
        merge, jobs, settings.max_workers, safe_progress, label=lambda j: f"persona merge {j[0]}", on_result=save
    )
    report.items = len(store.list_items())
