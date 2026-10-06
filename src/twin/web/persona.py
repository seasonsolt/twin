"""Web routes of the general digital twin (``/api/persona/...``): import sources, build the profile, browse it,
read its completeness and chat."""

from __future__ import annotations

import datetime as dt
import email.parser
import email.policy
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..config import Settings
from ..embed import Embedder
from ..llm import LLM
from ..persona.chat import PersonaChat, index_persona, no_profile_reply
from ..persona.coverage import LEVEL_LABELS, coverage_report
from ..persona.dimensions import DIMENSION_BY_ID, FACET_BY_ID, TAXONOMY_VERSION
from ..persona.items import PReview
from ..persona.profile import build_profile, consented_facets, profile_stale, source_memories
from ..persona.questionnaire import Round, round_view, save_draft, submit_initial, submit_retest
from ..persona.schema import SOURCE_KIND_LABELS, ChatTurn, ReviewStatus, SourceKind, evidence_class
from ..persona.sources import MEMORY_KIND_LABELS, expression_view, parse_note, parse_upload
from ..persona.store import PersonaStore, stored_identity
from .backends import Backends
from .jobs import JobManager, PersonaProcessing

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
MAX_UPLOAD_FILES = 500
MAX_CHAT_TURNS = 40
MAX_MESSAGE_CHARS = 4000

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
    as_of: str | None = None


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
        "facet_diffs": {fid: asdict(diff) for fid, diff in report.facet_diffs.items()},
        "items_added": report.items_added,
        "items_changed": report.items_changed,
        "items_removed": report.items_removed,
        "facets_changed": report.facets_changed,
    }


def run_chat(
    settings: Settings, llm: LLM, embedder: Embedder, messages: list[ChatTurn], as_of: dt.date | None, log: Log
) -> dict[str, Any]:
    with PersonaStore(settings.db_path) as store:
        log("检索档案并作答")
        reply = PersonaChat(store, llm, embedder, settings).reply(messages, as_of)
        items = {i.item_id: i for i in store.list_items()}
        cited: list[dict[str, Any]] = []
        for ref in reply.citations:
            if (item := items.get(ref)) is not None:
                facet = FACET_BY_ID[item.facet_id].name
                cited.append({"id": ref, "kind": "item", "facet": facet, "text": item.statement})
            elif (e := store.get_expression(ref)) is not None:
                day = e.date.isoformat() if e.date else None
                cited.append({"id": ref, "kind": "expression", "date": day, "channel": e.channel, "text": e.text})
    return {**reply.model_dump(mode="json"), "cited": cited}


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
                if store.get_meta("built_at") is None
                or store.get_meta(f"source_pending:{s.source_id}") is not None
                or store.get_meta(f"source_error:{s.source_id}")
            ]
            version = store.get_meta("sources_changed_at")
            store.clear_source_errors()
        error = None
        try:
            result = run_persona_build(settings, backends.llm(), backends.embedder(), log)
            if result.get("failures"):
                error = "部分记忆处理失败，请重新处理"
            return result
        except Exception:
            error = "记忆处理失败，请检查模型配置后重试"
            # Backend exceptions can contain prompts. Do not pass them to job logs.
            raise RuntimeError(error) from None
        finally:
            with open_store() as store:
                store.processing_result(ids, version, error)

    processing = PersonaProcessing(jobs, automatic_build, lambda snapshot: None)

    def queue_build() -> None:
        with open_store() as store:
            store.clear_source_errors()
        processing.queue()

    from . import identity

    identity.register(app, settings, queue_build)

    def resume_processing() -> None:
        if not settings.db_path.is_file():
            return
        with open_store() as store:
            stale = profile_stale(store)
        if stale:
            processing.queue()

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
        with open_store() as store:
            view["last_finished_at"] = store.get_meta("processing_last_finished_at") or view["last_finished_at"]
            view["last_error"] = store.get_meta("processing_last_error") or view["last_error"]
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
            speaker_lines = source.kind in {SourceKind.CHAT, SourceKind.INTERVIEW, SourceKind.MEETING}
            return "\n\n".join(
                (f"{e.context}\n" if e.context else "") + (f"{e.speaker}：{e.text}" if speaker_lines else e.text)
                for e in expressions
            )[:20000]

    @app.get("/api/persona/sources")
    def list_sources() -> list[dict[str, Any]]:
        with open_store() as store:
            memories = source_memories(store)
            return [
                {
                    **source_view(s),
                    **asdict(memories[s.source_id]),
                    "status": store.source_status(s.source_id, memories[s.source_id].items_supported),
                    "remembered": memories[s.source_id].items_supported,
                }
                for s in store.list_sources()
            ]

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
                imported.append({**source_view(parsed.source), "new": new, "skipped_lines": len(parsed.skipped_lines)})
        if imported:
            queue_build()
        return {"imported": imported, "skipped": skipped}

    @app.delete("/api/persona/sources/{source_id}")
    def delete_source(source_id: str) -> dict[str, bool]:
        with open_store() as store:
            if not store.delete_source(source_id):
                raise HTTPException(404, f"找不到资料 {source_id}")
        queue_build()
        return {"deleted": True}

    @app.post("/api/persona/build", status_code=202)
    def start_build() -> dict[str, str]:
        with open_store() as store:
            if not store.list_sources() and not profile_stale(store):
                raise HTTPException(400, "还没有导入资料，请先添加记忆")
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
    def list_items(include_rejected: bool = False) -> list[dict[str, Any]]:
        with open_store() as store:
            return [item_view(i) for i in store.list_items(include_rejected=include_rejected)]

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

    @app.post("/api/persona/chat", status_code=202)
    def start_chat(body: ChatBody) -> Any:
        messages = body.messages
        if messages[-1].role != "user" or not messages[-1].content.strip():
            raise HTTPException(400, "最后一条消息必须是你说的话，且不能为空")
        if any(len(m.content) > MAX_MESSAGE_CHARS for m in messages):
            raise HTTPException(400, f"单条消息不能超过 {MAX_MESSAGE_CHARS} 字")
        as_of = _date(body.as_of, "as_of")
        with open_store() as store:
            if not store.list_items():
                reply = no_profile_reply(store, as_of)
                return JSONResponse({**reply.model_dump(mode="json"), "cited": []}, status_code=200)
        llm, embedder = backends.llm(), backends.embedder()
        job = jobs.submit("chat", "和分身聊天", lambda log: run_chat(settings, llm, embedder, messages, as_of, log))
        return {"job_id": job.job_id}

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
        """The initial round is imported as a questionnaire source and a profile build starts when the model is
        configured and no other build is running; the retest round is only recorded."""
        with open_store() as store:
            try:
                if body.round == "retest":
                    submit_retest(store, body.answers)
                    return {"round": "retest", "job_id": None, "notice": "重测已提交"}
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


def parse_multipart(content_type: str, body: bytes) -> list[tuple[str, bytes]]:
    """``(file name as sent, content)`` of every file part named ``files`` of a multipart/form-data body. Raises
    ``ValueError`` when the body is not multipart."""
    head = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("latin-1", "replace")
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(head + body)
    if not message.is_multipart():
        raise ValueError("请求体不是 multipart/form-data")
    files: list[tuple[str, bytes]] = []
    for part in message.iter_parts():
        filename = part.get_filename()
        if part.get_param("name", header="content-disposition") != "files" or filename is None:
            continue
        payload = part.get_payload(decode=True)
        files.append((str(filename), payload if isinstance(payload, bytes) else b""))
    return files


async def read_uploads(request: Request) -> list[tuple[str, bytes]]:
    """The ``files`` parts of a multipart/form-data request, within the size and count limits."""
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise HTTPException(400, "请用 multipart/form-data 上传文件，字段名为 files")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
        raise _too_large()
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_UPLOAD_BYTES:
            raise _too_large()
        chunks.append(chunk)
    try:
        received = await run_in_threadpool(parse_multipart, content_type, b"".join(chunks))
    except ValueError as e:
        raise HTTPException(400, f"无法解析上传内容：{e}") from e
    if not received:
        raise HTTPException(400, "没有收到文件：请用字段名 files 上传一个或多个文件")
    if len(received) > MAX_UPLOAD_FILES:
        raise HTTPException(400, f"一次最多上传 {MAX_UPLOAD_FILES} 个文件")
    return received


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=413, detail=f"上传内容太大（上限 {MAX_UPLOAD_BYTES // (1024 * 1024)} MB），请分批上传"
    )
