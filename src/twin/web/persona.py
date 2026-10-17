"""Web routes of the general digital twin (``/api/persona/...``): import sources, build the profile, browse it,
read its completeness and chat."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import math
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import aclosing, asynccontextmanager, contextmanager, suppress
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Annotated, Any, Literal

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from ..config import Settings
from ..embed import Embedder, EmbedError
from ..llm import LLM
from ..persona.attachments import (
    MAX_CHAT_ATTACHMENT_BYTES,
    MAX_CHAT_ATTACHMENT_COUNT,
    MAX_CHAT_EXTRACTED_CHARS,
    AttachmentPassage,
    select_attachment_passages,
)
from ..persona.chat import (
    LEDGER_PREFIX,
    PersonaChat,
    index_persona,
    index_stale,
    no_profile_reply,
    off_loop,
    open_store_off_loop,
    search_items,
)
from ..persona.coverage import LEVEL_LABELS, coverage_report
from ..persona.dimensions import DIMENSION_BY_ID, DIMENSIONS, FACET_BY_ID, FACETS, TAXONOMY_VERSION
from ..persona.items import PReview
from ..persona.kernel import KERNEL, rebuild_scope
from ..persona.ledger import KIND_LABELS as LEDGER_KIND_LABELS
from ..persona.profile import (
    KERNEL_AWAITING_NOTICE,
    KERNEL_STALE_NOTICE,
    build_profile,
    consented_facets,
    pending_chunks,
    profile_stale,
    source_memories,
    stale_reason,
)
from ..persona.questionnaire import Round, round_view, save_draft, submit_initial
from ..persona.schema import SOURCE_KIND_LABELS, ChatReply, ChatTurn, ReviewStatus, Source, SourceKind, evidence_class
from ..persona.sources import MEMORY_KIND_LABELS, expression_view, parse_note, parse_upload
from ..persona.store import PersonaStore, stored_identity
from ..persona.text import extract_text
from ..usage import transient_summary
from .backends import Backends, BackendUnavailable
from .conversations import append_reply, append_user, owner
from .jobs import AdmittedStream, Job, JobConflict, JobManager, PersonaProcessing, Ticket

MAX_UPLOAD_BYTES = 1024**3
MAX_UPLOAD_FILES = 500
MAX_CHAT_TURNS = 40
MAX_MESSAGE_CHARS = 4000
CHAT_ATTACHMENT_PATH = "/api/persona/chat/stream-with-files"
MAX_CHAT_ATTACHMENT_REQUEST_BYTES = MAX_CHAT_ATTACHMENT_BYTES + 2 * 1024 * 1024
PAGE_SIZE = 50
MAX_PAGE_SIZE = 500
# Search shows the closest items, best first: enough to find the wrong one, short enough to read.
SEARCH_SIZE = 20
MEDIA_PENDING = frozenset({"queued", "extracting", "transcribing"})
# Sources the memory page lists apart from the paged list: work in progress and work waiting for the person.
NEEDS_ATTENTION = MEDIA_PENDING | {"failed", "needs_asr", "needs_speaker"}
MAX_ATTENTION = 50

Log = Callable[[str], None]


class NoteBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)
    title: str | None = Field(default=None, max_length=200)


class QuestionnaireBody(BaseModel):
    round: Round = "initial"
    answers: dict[str, str] = Field(default_factory=dict)


class ReviewBody(BaseModel):
    status: ReviewStatus
    statement: str | None = Field(default=None, max_length=1000)
    note: str = Field(default="", max_length=1000)


class ChatBody(BaseModel):
    messages: list[ChatTurn] = Field(min_length=1, max_length=MAX_CHAT_TURNS)
    conversation_id: str | None = Field(default=None, max_length=100)


def _date(value: str | None, field: str) -> dt.date | None:
    if value is None or not value.strip():
        return None
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError as e:
        raise HTTPException(400, f"{field} 的日期格式应为 YYYY-MM-DD") from e


def source_view(s: Any) -> dict[str, Any]:
    return {
        **s.model_dump(mode="json"),
        "kind_label": SOURCE_KIND_LABELS[s.kind],
        "detected_kind": s.kind.value,
        "detected_kind_label": "笔记" if s.origin.startswith("note:") else MEMORY_KIND_LABELS[s.kind],
        "evidence_class": evidence_class(s.kind).value,
    }


def run_persona_build(settings: Settings, llm: LLM, embedder: Embedder, log: Log) -> dict[str, Any]:
    settings = settings.model_copy(update={"target_name": stored_identity(settings.db_path)[0] or settings.target_name})
    with PersonaStore(settings.db_path) as store:
        log("[1/2] 抽取并合并人格档案")
        report = build_profile(store, llm, settings, log)
        for failure in report.failures:
            log(f"FAILED {failure}")
        for degraded in report.degraded:
            log(f"未完全合并，下次构建会重试：{degraded}")
        if note := transient_summary(report.calls.get("transient", {})):
            log(note)
        log("[2/2] 更新检索向量")
        index_persona(store, embedder, settings, log)
    if report.failures and report.chunks_extracted == 0 and report.facets_merged == 0:
        raise RuntimeError(f"模型调用全部失败：{report.failures[-1]}")
    return {
        "sources": report.sources,
        "chunks": report.chunks_total,
        "chunks_extracted": report.chunks_extracted,
        "candidates": report.candidates,
        "facets_merged": report.facets_merged,
        "items": report.items,
        "failures": report.failures,
        "failed_sources": sorted(report.failed_sources),
        "merge_failed": report.merge_failed,
        "facet_diffs": {fid: asdict(diff) for fid, diff in report.facet_diffs.items()},
        "items_added": report.items_added,
        "items_changed": report.items_changed,
        "items_removed": report.items_removed,
        "facets_changed": report.facets_changed,
        "calls": report.calls,
    }


def run_chat(
    settings: Settings,
    llm: LLM,
    embedder: Embedder,
    messages: list[ChatTurn],
    log: Log,
    conversation_id: str | None = None,
    email: str | None = None,
) -> dict[str, Any]:
    with PersonaStore(settings.db_path) as store:
        log("检索档案并作答")
        # This route is the person's own (visitors only reach the stream), so the ledger is material.
        reply = PersonaChat(store, llm, embedder, settings, ledger=True).reply(messages)
        return append_reply(store, conversation_id, email, chat_payload(store, reply))


def chat_payload(
    store: PersonaStore, reply: ChatReply, attachment_passages: Sequence[AttachmentPassage] = ()
) -> dict[str, Any]:
    return {
        **reply.model_dump(mode="json"),
        "cited": cited_view(store, reply.citations, {p.citation_id: p for p in attachment_passages}),
    }


def cited_view(
    store: PersonaStore, citations: Sequence[str], attachments: dict[str, AttachmentPassage] | None = None
) -> list[dict[str, Any]]:
    """What each cited id says, for the 依据 under an answer; ids gone since (or rejected items) are left out."""
    items = store.get_items(list(citations))
    cited: list[dict[str, Any]] = []
    for ref in citations:
        if (item := items.get(ref)) is not None and item.review is not ReviewStatus.REJECTED:
            facet = FACET_BY_ID[item.facet_id].name
            cited.append({"id": ref, "kind": "item", "facet": facet, "text": item.statement})
        elif (e := store.get_expression(ref)) is not None:
            day = e.date.isoformat() if e.date else None
            cited.append({"id": ref, "kind": "expression", "date": day, "channel": e.channel, "text": e.text})
        elif (passage := (attachments or {}).get(ref)) is not None:
            cited.append(
                {
                    "id": ref,
                    "kind": "file",
                    "file_name": passage.file_name,
                    "locator": passage.locator,
                    "text": passage.text,
                }
            )
        elif ref.startswith(LEDGER_PREFIX) and (entry := store.get_ledger_entry(ref[len(LEDGER_PREFIX) :])) is not None:
            cited.append(
                {
                    "id": ref,
                    "kind": "ledger",
                    "ledger_kind": LEDGER_KIND_LABELS[entry.kind],
                    "date": entry.meeting_date.isoformat() if entry.meeting_date else None,
                    "channel": entry.meeting_title,
                    "text": entry.quote,
                }
            )
    return cited


async def read_chat_attachment_request(request: Request) -> tuple[ChatBody, list[AttachmentPassage]]:
    """Parse bounded multipart attachments as transient text; never create persona sources from chat files."""
    try:
        form = await request.form(max_files=MAX_CHAT_ATTACHMENT_COUNT, max_fields=1)
    except Exception:
        raise HTTPException(400, "上传格式无效，请重新选择文件") from None
    try:
        raw_payload = form.get("payload")
        if not isinstance(raw_payload, str):
            raise HTTPException(400, "缺少聊天内容")
        try:
            body = ChatBody.model_validate_json(raw_payload)
        except ValidationError:
            raise HTTPException(400, "聊天内容格式无效") from None
        validate_chat(body)
        uploads = form.getlist("files")
        if not 1 <= len(uploads) <= MAX_CHAT_ATTACHMENT_COUNT:
            raise HTTPException(400, f"一次最多附加 {MAX_CHAT_ATTACHMENT_COUNT} 个文件")

        total_bytes = 0
        total_chars = 0
        documents: list[tuple[str, str]] = []
        for upload in uploads:
            if not isinstance(upload, UploadFile):
                raise HTTPException(400, "附件格式无效，请重新选择文件")
            file_name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
            if not file_name or file_name.startswith("."):
                raise HTTPException(400, "附件文件名无效")
            data = await upload.read(MAX_CHAT_ATTACHMENT_BYTES + 1)
            if len(data) > MAX_CHAT_ATTACHMENT_BYTES:
                raise HTTPException(413, "单次附件总量不能超过 50 MB")
            total_bytes += len(data)
            if total_bytes > MAX_CHAT_ATTACHMENT_BYTES:
                raise HTTPException(413, "单次附件总量不能超过 50 MB")
            try:
                extracted = await run_in_threadpool(extract_text, file_name, data)
            except ValueError as error:
                raise HTTPException(400, str(error)) from None
            if not extracted.strip():
                raise HTTPException(400, f"{file_name} 中没有可提取的文字")
            total_chars += len(extracted)
            if total_chars > MAX_CHAT_EXTRACTED_CHARS:
                raise HTTPException(413, f"附件提取文字超过 {MAX_CHAT_EXTRACTED_CHARS // 10_000} 万字，请拆分后上传")
            documents.append((file_name, extracted))
        try:
            passages = await run_in_threadpool(select_attachment_passages, documents, body.messages[-1].content)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        return body, passages
    finally:
        await form.close()


def validate_chat(body: ChatBody) -> list[ChatTurn]:
    messages = body.messages
    if messages[-1].role != "user" or not messages[-1].content.strip():
        raise HTTPException(400, "最后一条消息必须是你说的话，且不能为空")
    if any(len(m.content) > MAX_MESSAGE_CHARS for m in messages):
        raise HTTPException(400, f"单条消息不能超过 {MAX_MESSAGE_CHARS} 字")
    return messages


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def register(
    app: FastAPI,
    settings: Settings,
    backends: Backends,
    jobs: JobManager,
    read_uploads: Callable[[Request], Awaitable[list[tuple[str, bytes]]]],
) -> None:
    @contextmanager
    def open_store() -> Iterator[PersonaStore]:
        with PersonaStore(settings.db_path) as store:
            yield store

    def automatic_build(log: Log) -> dict[str, Any]:
        with open_store() as store:
            ids = [
                s.source_id
                for s in store.list_sources()
                if s.media_status in (None, "ready")
                and (
                    store.get_meta("built_at") is None
                    or store.get_meta(f"source_pending:{s.source_id}") is not None
                    or store.get_meta(f"source_error:{s.source_id}")
                )
            ]
            version = store.get_meta("sources_changed_at")
            store.clear_source_errors()
        error = None
        failed: list[str] = []
        try:
            result = run_persona_build(settings, backends.llm(), backends.embedder(), log)
            failed = result["failed_sources"]
            if result["merge_failed"]:
                error = "部分记忆处理失败，请重新处理"
            return result
        except Exception:
            error = "记忆处理失败，请检查模型配置后重试"
            # Backend exceptions can contain prompts. Do not pass them to job logs.
            raise RuntimeError(error) from None
        finally:
            with open_store() as store:
                store.processing_result(ids, version, error, failed)

    processing = PersonaProcessing(jobs, automatic_build, lambda snapshot: None)
    app.state.processing = processing

    def queue_build() -> None:
        with open_store() as store:
            store.clear_source_errors()
        processing.queue()

    from . import conversations, identity

    conversations.register(app, settings)
    identity.register(app, settings, queue_build)

    from . import uploads

    ingestion = uploads.register(app, settings, jobs, queue_build, backends.llm)
    from . import claims

    claims.register(app, settings, ingestion)
    from . import ledger

    ledger.register(app, settings, backends, jobs)
    from . import followups

    followups.register(app, settings, queue_build)
    from . import work

    work.register(app, settings, backends, jobs, cited_view)

    def resume_processing() -> None:
        if not settings.db_path.is_file():
            return
        with open_store() as store:
            stale = profile_stale(store)
            interrupted = [
                s.source_id for s in store.list_sources() if s.media_status in {"queued", "extracting", "transcribing"}
            ]
            pending_candidates = [s for s in store.list_sources() if s.candidates_pending and s.media_status == "ready"]
            kernel_scope = rebuild_scope(store.kernel_built(), KERNEL)
            kernel_pending = pending_chunks(store, settings) if kernel_scope != "none" else 0
            kernel_blocked = kernel_scope != "none" and (
                not settings.kernel.auto_rebuild or kernel_pending > settings.kernel.max_auto_rebuild_chunks
            )
        for source_id in interrupted:
            ingestion.queue(source_id)
        from ..media.claim import Analysis

        for source in pending_candidates:
            folder = settings.db_path.parent / "media-sources" / str(source.media_sha)
            revision = Analysis.load(folder).revision
            jobs.submit(
                "media_ingest",
                source.title,
                partial(ingestion.candidates, source.source_id, revision),
            )
        if stale:
            if kernel_blocked:
                with open_store() as store:
                    store.set_meta("kernel_rebuild", "awaiting_confirmation")
            else:
                processing.queue()
                return
        resume_index()

    def reindex(log: Log) -> dict[str, Any]:
        log("[1/1] 更新检索向量")
        log("检索向量来自之前的向量模型或上次没有完成，按当前模型补齐（只调用向量模型）")
        with open_store() as store:
            return {"embedded": index_persona(store, backends.embedder(), settings, log)}

    def resume_index() -> None:
        """A changed [embed] model re-embeds the index at startup, without waiting for the next build; until it
        finishes, retrieval leaves the old model's vectors out and ranks by keywords."""
        try:
            embedder = backends.embedder()
        except BackendUnavailable:
            return
        with open_store() as store:
            behind = index_stale(store, embedder)
        if behind:
            with suppress(JobConflict):
                jobs.submit("persona_build", "更新检索向量", reindex)

    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with previous_lifespan(app):
            resume_processing()
            try:
                yield
            finally:
                processing.close()

    app.router.lifespan_context = lifespan

    @app.get("/api/persona/processing")
    def get_processing() -> dict[str, Any]:
        view = processing.view()
        if view["job_id"] is not None:
            snapshot = jobs.snapshot(view["job_id"])
            if snapshot is not None:
                view["stage"] = snapshot["stage"]
                view["tally"] = snapshot["tally"]
                view["started"] = snapshot["started"]
                view["activity"] = snapshot["activity"]
        # The page counts elapsed and idle time from the server's clock, not the viewer's.
        view["now"] = dt.datetime.now(dt.UTC).isoformat()
        with open_store() as store:
            view["kernel_rebuild"] = store.get_meta("kernel_rebuild")
            awaiting = view["kernel_rebuild"] == "awaiting_confirmation" and stale_reason(store) == "kernel"
            view["kernel_pending"] = pending_chunks(store, settings) if awaiting else 0
            view["notice"] = (
                (KERNEL_AWAITING_NOTICE if view["kernel_rebuild"] == "awaiting_confirmation" else KERNEL_STALE_NOTICE)
                if stale_reason(store) == "kernel"
                else None
            )
            view["last_finished_at"] = store.get_meta("processing_last_finished_at") or view["last_finished_at"]
            view["last_calls"] = json.loads(store.get_meta("build:last_calls") or "null")
            view["last_error"] = store.get_meta("processing_last_error") or view["last_error"]
            progress = store.build_progress() if view["state"] == "running" else None
            merging = store.merge_progress() if progress and progress[0] == "merge" else None
        if progress:
            phase, chunks = progress
            view["progress"] = {
                "phase": phase,
                "done": sum(done for done, _ in chunks.values()),
                "total": sum(total for _, total in chunks.values()),
            }
            if merging:
                view["progress"]["merged"], view["progress"]["to_merge"] = merging
        return view

    @app.post("/api/persona/notes")
    def add_note(body: NoteBody) -> dict[str, Any]:
        try:
            parsed = parse_note(body.text, settings, body.title)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        with open_store() as store:
            new = store.put_source(parsed)
        queue_build()
        return {**source_view(parsed.source), "new": new}

    @app.get("/api/persona/sources/{source_id}/text", response_class=PlainTextResponse)
    def source_text(source_id: str) -> str:
        with open_store() as store:
            source = store.get_source(source_id)
            if source is None:
                raise HTTPException(404, "找不到这条记忆")
            expressions = expression_view(store, settings, source_id=source_id)
            speaker_lines = source.kind in {SourceKind.CHAT, SourceKind.INTERVIEW, SourceKind.AUDIO, SourceKind.VIDEO}
            return "\n\n".join(
                (f"{e.context}\n" if e.context and not source.media_sha else "")
                + (f"{e.speaker}：{e.text}" if speaker_lines else e.text)
                for e in expressions
            )[:20000]

    @app.get("/api/persona/sources")
    def list_sources(
        limit: Annotated[int, Query(ge=0, le=MAX_PAGE_SIZE)] = PAGE_SIZE,
        offset: Annotated[int, Query(ge=0)] = 0,
        status: Annotated[list[str] | None, Query()] = None,
        candidates: bool = False,
        attention: bool = False,
    ) -> dict[str, Any]:
        """One page of memories (oldest first) and how many match: only those with a ``status`` (repeatable) or,
        with ``candidates``, with voice or portrait candidates. ``summary`` counts every memory; ``attention`` adds
        up to 50 memories being transcribed or waiting for the person, wherever they are in the list."""
        running = processing.view()["state"] == "running"
        with open_store() as store:
            sources = store.list_sources()
            memories = source_memories(store, sources)
            statuses = store.source_statuses(sources, {sid: m.items_supported for sid, m in memories.items()})
            progress = store.build_progress() if running else None
        chunks = progress[1] if progress else {}

        def busy(source: Source) -> bool:
            state = statuses[source.source_id]
            return (
                state in MEDIA_PENDING
                or state == "processing"
                or (source.candidates_pending and state not in {"failed", "needs_asr", "needs_speaker"})
            )

        def row(source: Source) -> dict[str, Any]:
            memory = memories[source.source_id]
            state = statuses[source.source_id]
            view = {**source_view(source), **asdict(memory), "status": state, "remembered": memory.items_supported}
            if state == "processing" and source.source_id in chunks:
                view["chunks_done"], view["chunks_total"] = chunks[source.source_id]
            return view

        wanted = set(status or ())
        matching = [
            s
            for s in sources
            if (not wanted or statuses[s.source_id] in wanted)
            and (not candidates or s.voice_candidates or s.portrait_candidates)
        ]
        result: dict[str, Any] = {
            "items": [row(s) for s in matching[offset : offset + limit]],
            "total": len(matching),
            "summary": {
                "total": len(sources),
                "duration_s": sum(s.duration_s or 0 for s in sources),
                "needs_speaker": sum(statuses[s.source_id] == "needs_speaker" for s in sources),
                "remembered": sum(statuses[s.source_id] == "remembered" for s in sources),
                "nothing_found": sum(statuses[s.source_id] == "nothing_found" for s in sources),
                "failed": sum(statuses[s.source_id] == "failed" for s in sources),
                "busy": sum(busy(s) for s in sources),
            },
        }
        if attention:
            waiting = [s for s in sources if statuses[s.source_id] in NEEDS_ATTENTION]
            result["attention"] = [row(s) for s in waiting[:MAX_ATTENTION]]
        return result

    @app.get("/api/persona/state")
    def get_state() -> dict[str, Any]:
        with open_store() as store:
            return {
                "stale": profile_stale(store),
                "built_at": store.get_meta("built_at"),
                "sources_changed_at": store.get_meta("sources_changed_at"),
            }

    @app.post("/api/persona/import")
    async def import_sources(
        request: Request,
        kind: Annotated[SourceKind | None, Query()] = None,
        date: Annotated[str | None, Query()] = None,
    ) -> dict[str, Any]:
        when = _date(date, "date")
        received = await read_uploads(request)

        # Parsing documents and writing them to SQLite would stall every other request on the event loop.
        def store_all() -> dict[str, Any]:
            imported: list[dict[str, Any]] = []
            skipped: list[dict[str, str]] = []
            with open_store() as store:
                for raw_name, data in received:
                    relative = Path(raw_name.replace("\\", "/"))
                    name = relative.name
                    if any(part.startswith(".") for part in relative.parts):
                        skipped.append({"file": raw_name, "reason": "已跳过隐藏文件"})
                        continue
                    try:
                        parsed = parse_upload(name, data, settings, kind, when)
                    except ValueError as e:
                        skipped.append({"file": raw_name, "reason": str(e)})
                        continue
                    new = store.put_source(parsed)
                    imported.append(
                        {**source_view(parsed.source), "new": new, "skipped_lines": len(parsed.skipped_lines)}
                    )
            if imported:
                queue_build()
            return {"imported": imported, "skipped": skipped}

        return await run_in_threadpool(store_all)

    @app.delete("/api/persona/sources/{source_id}")
    def delete_source(source_id: str) -> dict[str, bool]:
        with ingestion.lock, open_store() as store:
            if not store.delete_source(source_id):
                raise HTTPException(404, f"找不到资料 {source_id}")
        queue_build()
        return {"deleted": True}

    @app.post("/api/persona/sources/{source_id}/reextract", status_code=202)
    def reextract_source(source_id: str) -> dict[str, int]:
        with ingestion.lock, open_store() as store:
            forgotten = store.reextract_source(source_id)
        if forgotten is None:
            raise HTTPException(404, f"找不到资料 {source_id}")
        queue_build()
        return {"chunks": forgotten}

    @app.post("/api/persona/build", status_code=202)
    def start_build() -> dict[str, str]:
        with open_store() as store:
            if not store.count_sources() and not profile_stale(store):
                raise HTTPException(400, "还没有导入资料，请先添加记忆")
        job = processing.start()
        return {"job_id": job.job_id}

    @app.post("/api/kernel/rebuild", status_code=202)
    def rebuild_kernel(request: Request) -> dict[str, str]:
        if not request.scope["twin_identity"]["admin"]:
            raise HTTPException(403, "仅管理员可以重建记忆内核")
        job = processing.start()
        return {"job_id": job.job_id}

    def item_view(i: Any) -> dict[str, Any]:
        facet = FACET_BY_ID[i.facet_id]
        return {
            **i.model_dump(mode="json"),
            "facet_name": facet.name,
            "dimension_id": facet.dimension_id,
            "dimension_name": DIMENSION_BY_ID[facet.dimension_id].name,
            "occasions": i.occasions(),
        }

    @app.get("/api/persona/items")
    def list_items(
        include_rejected: bool = False,
        dimension: Annotated[list[str] | None, Query()] = None,
        review: ReviewStatus | None = None,
        q: Annotated[str, Query(max_length=200)] = "",
        source_id: str | None = None,
        conflict: bool = False,
        sort: Literal["facet", "evidence"] = "facet",
        limit: Annotated[int, Query(ge=0, le=MAX_PAGE_SIZE)] = PAGE_SIZE,
        offset: Annotated[int, Query(ge=0)] = 0,
        with_sources: bool = False,
    ) -> dict[str, Any]:
        """One page of profile items and how many match. Filters: ``dimension`` (repeatable), ``review``, ``q``
        (statement or quote), ``source_id`` (evidence from that source), ``conflict`` (evidence that disagrees).
        ``sort=evidence`` lists the best-supported items first; ``with_sources`` adds the title and date of every
        source the page cites."""
        if unknown := [d for d in dimension or () if d not in DIMENSION_BY_ID]:
            raise HTTPException(400, f"未知的维度 {unknown[0]}")
        facet_ids = [f.facet_id for f in FACETS if f.dimension_id in set(dimension)] if dimension else None
        with open_store() as store:
            items, total = store.query_items(
                facet_ids=facet_ids,
                review=review,
                text=q,
                source_id=source_id,
                conflict=conflict,
                by_evidence=sort == "evidence",
                include_rejected=include_rejected,
                limit=limit,
                offset=offset,
            )
            result: dict[str, Any] = {"items": [item_view(i) for i in items], "total": total}
            if with_sources:
                cited = sorted({e.source_id for i in items for e in i.evidence if e.source_id})
                result["sources"] = {
                    sid: {"title": source.title, "first_date": source.first_date, "kind": source.kind.value}
                    for sid in cited
                    if (source := store.get_source(sid)) is not None
                }
        return result

    @app.get("/api/persona/items/search")
    def search_profile_items(
        q: Annotated[str, Query(min_length=1, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = SEARCH_SIZE,
    ) -> dict[str, Any]:
        """The items closest to ``q`` by meaning and keywords, best first, as chat retrieval finds them: where the
        person looks for what the twin knows about something, to correct or remove it. Falls back to keywords alone
        when the embedding service is unavailable."""
        query = q.strip()
        if not query:
            raise HTTPException(400, "请输入要找的内容")
        with open_store() as store:
            try:
                found = search_items(store, backends.embedder(), query, limit)
            except (BackendUnavailable, EmbedError, ValueError):
                found = search_items(store, None, query, limit)
        return {"items": [item_view(i) for i in found], "total": len(found)}

    @app.get("/api/persona/items/summary")
    def items_summary() -> dict[str, Any]:
        """Item counts per dimension in taxonomy order, rejected items left out, and how many have evidence that
        disagrees (worth a look, never a queue to work through)."""
        with open_store() as store:
            counts = store.item_counts()
            _, conflicts = store.query_items(conflict=True, limit=0)
        totals: dict[str, int] = {}
        for (facet_id, status), n in counts.items():
            if status is ReviewStatus.REJECTED or facet_id not in FACET_BY_ID:
                continue
            dimension_id = FACET_BY_ID[facet_id].dimension_id
            totals[dimension_id] = totals.get(dimension_id, 0) + n
        dimensions = [
            {"dimension_id": d.dimension_id, "name": d.name, "total": totals[d.dimension_id]}
            for d in DIMENSIONS
            if d.dimension_id in totals
        ]
        return {"total": sum(totals.values()), "conflicts": conflicts, "dimensions": dimensions}

    @app.post("/api/persona/items/{item_id}/review")
    def review_item(item_id: str, body: ReviewBody) -> dict[str, Any]:
        """Confirm, edit (with a new statement), reject, or with ``unreviewed`` clear the review of an item."""
        statement = (body.statement or "").strip()
        if body.status is ReviewStatus.EDITED and not statement:
            raise HTTPException(400, "修改时必须给出新的表述")
        review = None
        if body.status is not ReviewStatus.UNREVIEWED:
            review = PReview(
                status=body.status,
                statement=statement if body.status is ReviewStatus.EDITED else None,
                note=body.note.strip(),
                reviewed_at=dt.datetime.now().isoformat(timespec="seconds"),
            )
        with open_store() as store:
            try:
                store.set_review(item_id, review)
            except KeyError as e:
                raise HTTPException(404, f"找不到档案条目 {item_id}（可能已在重新构建时合并）") from e
            item = store.get_item(item_id)
        assert item is not None
        return item_view(item)

    @app.get("/api/persona/coverage")
    def get_coverage(as_of: str | None = None) -> dict[str, Any]:
        with open_store() as store:
            report = coverage_report(
                store.list_items(), consented_facets(store), _date(as_of, "as_of"), demand=store.chat_demand()
            )
        data = report.model_dump(mode="json")
        data["level_labels"] = LEVEL_LABELS
        data["kind_labels"] = {k.value: v for k, v in SOURCE_KIND_LABELS.items()}
        data["taxonomy"] = TAXONOMY_VERSION
        return data

    # A chat is admitted (backends ready, a place in the chat queue) before its user turn is saved, so a rejected
    # message, which the page offers to send again, leaves nothing behind.

    @app.post("/api/persona/chat", status_code=202)
    def start_chat(body: ChatBody, request: Request) -> Any:
        messages = validate_chat(body)
        email = owner(request)
        with open_store() as store:
            if not store.has_items():
                append_user(store, body.conversation_id, email, messages[-1].content)
                reply = no_profile_reply(store)
                return JSONResponse(
                    append_reply(store, body.conversation_id, email, chat_payload(store, reply)), status_code=200
                )
        llm, embedder = backends.chat_llm(), backends.embedder()

        def accept(job: Job) -> None:
            with open_store() as store:
                append_user(store, body.conversation_id, email, messages[-1].content)

        job = jobs.submit(
            "chat",
            "和分身聊天",
            lambda log: run_chat(settings, llm, embedder, messages, log, body.conversation_id, email),
            prepare=accept,
        )
        return {"job_id": job.job_id}

    def stream_chat_response(
        body: ChatBody, request: Request, attachment_passages: Sequence[AttachmentPassage] = ()
    ) -> StreamingResponse:
        messages = validate_chat(body)
        email = owner(request)
        # The ledger is private: only the person themselves, never a visitor of a public twin, chats with it.
        ledger = not request.scope.get("twin_visitor")
        with open_store() as store:
            profiled = store.has_items() or bool(attachment_passages)
        ticket: Ticket | None = None
        if profiled:
            llm, embedder = backends.chat_llm(), backends.embedder()
            ticket = jobs.admit_stream()
        try:
            with open_store() as store:
                append_user(store, body.conversation_id, email, messages[-1].content)
        except BaseException:
            if ticket is not None:
                ticket.close()
            raise

        started_at = time.monotonic()

        def save(store: PersonaStore, reply: ChatReply) -> dict[str, Any]:
            payload = chat_payload(store, reply, attachment_passages)
            payload["elapsed_ms"] = max(0, round((time.monotonic() - started_at) * 1000))
            payload["completed_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")
            return append_reply(store, body.conversation_id, email, payload)

        def unbuilt() -> tuple[str, dict[str, Any]]:
            with open_store() as store:
                reply = no_profile_reply(store)
                return reply.reply, save(store, reply)

        # The store is opened, read and written off the event loop, which other requests share.
        async def produce() -> AsyncGenerator[str]:
            if ticket is None:
                text, final = await off_loop(unbuilt)
                yield sse_event("delta", {"text": text})
                yield sse_event("final", final)
                return
            # Waits, with heartbeats, for one of the chat worker slots that chat jobs use too.
            async with ticket.running():
                with await open_store_off_loop(settings.db_path) as store:
                    chat = PersonaChat(store, llm, embedder, settings, ledger=ledger)
                    async with aclosing(
                        chat.stream_reply(messages, attachments=attachment_passages, persist=not attachment_passages)
                    ) as replies:
                        async for result in replies:
                            if isinstance(result, str):
                                yield sse_event("delta", {"text": result})
                            else:
                                yield sse_event("final", await off_loop(partial(save, store, result)))

        async def events() -> AsyncGenerator[str]:
            yield ": connected\n\n"
            stream = produce()
            pending: asyncio.Task[str] | None = None
            try:
                while True:
                    pending = asyncio.create_task(anext(stream))
                    while not (await asyncio.wait({pending}, timeout=10))[0]:
                        yield ": heartbeat\n\n"
                    try:
                        yield pending.result()
                    except StopAsyncIteration:
                        break
            except Exception:
                # Backend errors can contain prompts, URLs or credentials; never reflect them to the browser.
                yield sse_event("error", {"detail": "分身暂时无法回复，请重试"})
            finally:
                # Cancel the pending operation once, then let its worker finish before closing the store and
                # releasing the ticket. Starlette's cancelled scope would otherwise cancel this gather again.
                with anyio.CancelScope(shield=True):
                    if pending is not None:
                        pending.cancel()
                        await asyncio.gather(pending, return_exceptions=True)
                    await stream.aclose()

        return AdmittedStream(
            events(),
            ticket,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/persona/chat/stream")
    def stream_chat(body: ChatBody, request: Request) -> StreamingResponse:
        return stream_chat_response(body, request)

    @app.post(CHAT_ATTACHMENT_PATH)
    async def stream_chat_with_files(request: Request) -> StreamingResponse:
        body, passages = await read_chat_attachment_request(request)
        return stream_chat_response(body, request, passages)

    @app.get("/api/persona/questionnaire")
    def get_questionnaire(round: Round = "initial") -> dict[str, Any]:
        with open_store() as store:
            return round_view(store, round)

    @app.put("/api/persona/questionnaire/draft")
    def put_draft(body: QuestionnaireBody) -> dict[str, Any]:
        with open_store() as store:
            try:
                state = save_draft(store, body.round, body.answers)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        return {"status": state.status, "updated_at": state.updated_at, "answered": len(state.answers)}

    @app.post("/api/persona/questionnaire/submit")
    def submit_questionnaire(body: QuestionnaireBody) -> dict[str, Any]:
        """Import optional answers and start a build when a model is configured and no build is running."""
        with open_store() as store:
            try:
                parsed = submit_initial(store, settings, body.answers)
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
        notice = f"已导入 {parsed.source.n_expressions} 条回答"
        try:
            llm, embedder = backends.llm(), backends.embedder()
            job = jobs.submit(
                "persona_build", "构建人格档案", lambda log: run_persona_build(settings, llm, embedder, log)
            )
        except Exception as e:
            # Model not configured or another build running: the answers are saved, the build can start later.
            return {"round": "initial", "job_id": None, "notice": f"{notice}；构建没有自动开始：{e}"}
        return {"round": "initial", "job_id": job.job_id, "notice": f"{notice}，正在构建人格档案"}


async def read_uploads(request: Request) -> list[tuple[str, bytes]]:
    """``(file name as sent, content)`` of every file part named ``files`` of a multipart/form-data request, within
    the size and count limits. File parts are spooled to temporary files while the body streams in, so only the
    contents returned are held in memory."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(400, "请用 multipart/form-data 上传文件，字段名为 files")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise _too_large()

    async def limited() -> AsyncGenerator[bytes, None]:
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise _too_large()
            yield chunk

    # File and field counts are checked below with a Chinese message; the byte limit already bounds both.
    parser = MultiPartParser(request.headers, limited(), max_files=math.inf, max_fields=math.inf)
    try:
        form = await parser.parse()
    except MultiPartException as e:
        raise HTTPException(400, f"无法解析上传内容：{e.message}") from e
    try:
        parts = [part for key, part in form.multi_items() if key == "files" and isinstance(part, UploadFile)]
        if not parts:
            raise HTTPException(400, "没有收到文件：请用字段名 files 上传一个或多个文件")
        if len(parts) > MAX_UPLOAD_FILES:
            raise HTTPException(400, f"一次最多上传 {MAX_UPLOAD_FILES} 个文件")
        return [(part.filename or "", await part.read()) for part in parts]
    finally:
        await form.close()


def _too_large() -> HTTPException:
    return HTTPException(status_code=413, detail=f"上传内容太大（上限 {MAX_UPLOAD_BYTES // 1024**3} GB），请分批上传")
