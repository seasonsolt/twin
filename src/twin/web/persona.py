"""Web routes of the general digital twin (``/api/persona/...``): import sources, build the profile, browse it,
read its completeness and chat."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import math
import time
from collections.abc import AsyncGenerator, AsyncIterator, Awaitable, Callable, Iterator, Sequence
from contextlib import aclosing, asynccontextmanager, contextmanager, suppress
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal, Protocol

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.types import ASGIApp, Receive, Scope, Send

from ..config import Settings
from ..delegations import Asked, Unclear
from ..embed import Embedder, EmbedError
from ..handoffs import HandoffDesk
from ..llm import LLM, Effort
from ..persona import gate
from ..persona.assistant import note_text
from ..persona.attachments import (
    MAX_CHAT_ATTACHMENT_BYTES,
    MAX_CHAT_ATTACHMENT_COUNT,
    MAX_CHAT_EXTRACTED_CHARS,
    AttachmentPassage,
    select_attachment_passages,
)
from ..persona.chat import (
    LEDGER_PREFIX,
    Asker,
    PersonaChat,
    Step,
    index_persona,
    index_stale,
    no_profile_reply,
    off_loop,
    open_store_off_loop,
    search_items,
)
from ..persona.coverage import CHECKED_LABEL, LEVEL_LABELS, coverage_report
from ..persona.crisis import crisis_reply, in_crisis
from ..persona.dimensions import DIMENSION_BY_ID, DIMENSIONS, FACET_BY_ID, FACETS, TAXONOMY_VERSION
from ..persona.items import PersonaItem, PReview
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
from ..persona.reflection import Reflection
from ..persona.schema import SOURCE_KIND_LABELS, ChatReply, ChatTurn, ReviewStatus, Source, SourceKind, evidence_class
from ..persona.sources import MEMORY_KIND_LABELS, expression_view, parse_note, parse_upload
from ..persona.store import PersonaStore, stored_identity
from ..persona.text import extract_text
from ..persona.tiers import COLLEAGUE, SELF, Audience, PrivateWords, Tier, for_audience, item_tier, private_words
from ..teamanswers import prompt_line, question_of
from ..usage import CallRow, collect_calls, model_tokens, rate_limited, transient_summary
from . import assistant as assistant_routes
from .assistant import keep_note, note_reply, person_only, trial_withheld
from .backends import Backends, BackendUnavailable
from .conversations import (
    ConversationIndex,
    append_reply,
    append_user,
    owner,
    request_asker_name,
    request_audience,
)
from .jobs import AdmittedStream, Job, JobConflict, JobManager, PersonaProcessing, Ticket

if TYPE_CHECKING:
    from .uploads import MediaIngestion

logger = logging.getLogger(__name__)

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
# Put before a dream in the source's own text: kept for the mirror, never read into memories or answered from.
DREAM_MARK = "【梦 · 不进记忆】"
# Sources the memory page lists apart from the paged list: work in progress and work waiting for the person.
NEEDS_ATTENTION = MEDIA_PENDING | {"failed", "needs_asr", "needs_speaker"}
MAX_ATTENTION = 50

Log = Callable[[str], None]


class AssistantDelegation(Protocol):
    """What the person's assistant needs to ask colleagues' twins for them (``web.delegation.Delegations``)."""

    def parse(self, message: str, identity: dict[str, Any]) -> Asked | Unclear | None: ...

    def refusal(self, store: PersonaStore, text: str) -> dict[str, Any]: ...

    def ask(
        self,
        *,
        persona_id: str,
        store: PersonaStore,
        identity: dict[str, Any],
        asker_name: str,
        conversation_id: str | None,
        asked: Asked,
        llm: LLM,
        embedder: Embedder,
        name: str,
        effort: Effort = "medium",
    ) -> dict[str, Any]: ...


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
    # 看同事会得到什么: answer the last message as a colleague would be answered, and keep nothing of it. Only the
    # person themself can ask for it.
    preview: bool = False
    # A way of talking with one's own assistant about oneself (``persona.reflection``); ignored anywhere else.
    reflection: Reflection = ""


class TierBody(BaseModel):
    tier: Tier | None


def visible_item(store: PersonaStore, item_id: str, audience: Audience) -> None:
    """404 unless the item exists and ``audience`` may see it: an item of the person's own tier does not show that it
    exists to anyone else."""
    item = store.get_item(item_id)
    if item is None or (audience != SELF and item_tier(item, store.item_tiers()) != COLLEAGUE):
        raise HTTPException(404, f"找不到档案条目 {item_id}（可能已在重新构建时合并）")


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
        try:
            index_persona(store, embedder, settings, log)
            index_pending = False
        except EmbedError:
            # The memory is built: retrieval ranks by keywords where vectors are missing, and ``IndexRetry`` fills
            # them in once the embedding service answers again.
            log("向量服务暂时连不上：先按关键词检索，服务恢复后自动补齐")
            index_pending = True
    if report.failures and report.chunks_extracted == 0 and report.facets_merged == 0:
        raise RuntimeError(f"模型调用全部失败：{report.failures[-1]}")
    return {
        "sources": report.sources,
        "chunks": report.chunks_total,
        "chunks_extracted": report.chunks_extracted,
        "chunks_superseded": report.chunks_superseded,
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
        "index_pending": index_pending,
    }


def chat_asker(desk: HandoffDesk, email: str | None, name: str) -> Asker | None:
    """Who the twin is talking with: the signed-in person by name, or the person it is made for, who has taken it;
    nobody without sign-in, where no one is known."""
    if not email or not name:
        return None
    return Asker(name, person=email == desk.owner())


def run_chat(
    settings: Settings,
    llm: LLM,
    embedder: Embedder,
    messages: list[ChatTurn],
    log: Log,
    conversation_id: str | None = None,
    email: str | None = None,
    audience: Audience = SELF,
    index: ConversationIndex | None = None,
    handoffs: tuple[HandoffDesk, str] | None = None,
    assistant: bool = False,
    reflection: Reflection = "",
) -> dict[str, Any]:
    """``handoffs``: the desk and what the asker is called, to hand on what the reply leaves to the person.
    ``assistant``: the conversation is the person's own with their assistant (``persona.assistant``), and
    ``reflection`` the way they are talking with it (``persona.reflection``)."""
    with PersonaStore(settings.db_path) as store:
        log("检索档案并作答")
        # The ledger is the person's own: only a conversation of the tier that may use everything has it.
        chat = PersonaChat(
            store,
            llm,
            embedder,
            settings,
            ledger=audience == SELF,
            audience=audience,
            reach=handoffs[0].reach(email) if handoffs else "none",
            assistant=assistant,
            asker=chat_asker(handoffs[0], email, handoffs[1]) if handoffs else None,
            reflection=reflection,
        )
        owner_said = store.owner_replies(conversation_id, email) if conversation_id else []
        # Team answers that match the question are shown as cards of their own; the twin is told so.
        cards = (
            handoffs[0].answers.cards_for(
                question_of([m.content for m in messages if m.role == "user"]), embedder, asker=email
            )
            if handoffs and handoffs[0].answers is not None
            else []
        )
        reply = chat.reply(messages, owner_said=owner_said, team_answers=[prompt_line(c) for c in cards])
        payload = chat_payload(store, reply, audience=audience)
        if cards:
            payload["team_answers"] = cards
        return append_reply(
            store,
            conversation_id,
            email,
            payload,
            index,
            (handoffs[0], handoffs[1], audience) if handoffs else None,
            assistant=assistant,
        )


def for_citation(store: PersonaStore, items: dict[str, PersonaItem], audience: Audience) -> dict[str, PersonaItem]:
    """The cited items a conversation of ``audience`` may be shown."""
    if audience == SELF or not items:
        return items
    allowed = {i.item_id for i in for_audience(items.values(), store.item_tiers(), audience)}
    return {item_id: item for item_id, item in items.items() if item_id in allowed}


def chat_payload(
    store: PersonaStore,
    reply: ChatReply,
    attachment_passages: Sequence[AttachmentPassage] = (),
    audience: Audience = SELF,
) -> dict[str, Any]:
    return {
        **reply.model_dump(mode="json"),
        "cited": cited_view(store, reply.citations, {p.citation_id: p for p in attachment_passages}, audience),
    }


def cited_view(
    store: PersonaStore,
    citations: Sequence[str],
    attachments: dict[str, AttachmentPassage] | None = None,
    audience: Audience = SELF,
) -> list[dict[str, Any]]:
    """What each cited id says, for the 依据 under an answer; ids gone since (or rejected items) are left out, and so
    are items of a tier the conversation's audience may not use, whatever the answer cited."""
    items = for_citation(store, store.get_items(list(citations)), audience)
    hidden: PrivateWords | None = PrivateWords() if audience == SELF else None
    cited: list[dict[str, Any]] = []
    for ref in citations:
        if (item := items.get(ref)) is not None and item.review is not ReviewStatus.REJECTED:
            facet = FACET_BY_ID[item.facet_id].name
            cited.append({"id": ref, "kind": "item", "facet": facet, "text": item.statement})
        elif (e := store.get_expression(ref)) is not None:
            if hidden is None:  # read once, and only when an answer cites someone's words
                hidden = private_words(
                    store.list_items(include_rejected=True), store.item_tiers(), store.private_note_sources()
                )
            if ref in hidden:
                continue
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
        elif (
            audience == SELF
            and ref.startswith(LEDGER_PREFIX)
            and (entry := store.get_ledger_entry(ref[len(LEDGER_PREFIX) :])) is not None
        ):
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


# Reading a twin's memory: refused while a twin made from a recording library is being rebuilt (``gate``).
GATED_PATHS = (
    "/api/persona/chat",
    "/api/persona/items",
    "/api/persona/followups",
    "/api/persona/handoffs",
    "/api/persona/answers",
    "/api/persona/fill",
    "/api/persona/life-",
    "/api/persona/observations",
    "/api/persona/self-ratings",
    "/api/persona/ledger",
)


class MemoryGateMiddleware:
    """Refuse every read of a twin's memory while ``gate`` says it is being rebuilt; asking it questions is refused
    again by ``PersonaChat`` itself, which also covers the service API, channels and the command line."""

    def __init__(self, app: ASGIApp, db_path: Path) -> None:
        self.app, self.db_path = app, db_path

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path, method = str(scope.get("path", "")), scope.get("method")
        if scope["type"] == "http" and (
            path.startswith(GATED_PATHS) or (method == "POST" and path == "/api/persona/work")
        ):
            try:
                await run_in_threadpool(gate.version_at, self.db_path)
            except gate.MemoryUpdating as e:
                await JSONResponse({"detail": str(e), "code": "memory_updating"}, status_code=409)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def sse_event(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def register(
    app: FastAPI,
    settings: Settings,
    backends: Backends,
    jobs: JobManager,
    read_uploads: Callable[[Request], Awaitable[list[tuple[str, bytes]]]],
    on_built: Callable[[int], None] | None = None,
    on_spent: Callable[[int], None] | None = None,
    on_unbuilt: Callable[[bool], None] | None = None,
    *,
    index: ConversationIndex,
    desk: HandoffDesk,
    after_build: Callable[[PersonaStore, LLM, Embedder], None] | None = None,
    delegations: AssistantDelegation | None = None,
) -> MediaIngestion:
    """``on_built(version)``: a build completed without any failure, from the library sources written at
    ``version`` (``gate.SYNCED``); a twin made from a recording library opens once that version is still wanted.
    ``on_spent(tokens)``: a build of such a twin ended (however it ended) after spending ``tokens`` model tokens,
    which count against the library's batch quota. ``on_unbuilt(rate_limited)``: a build of such a twin did not
    complete; ``rate_limited`` when only the model's rate limit stopped it. ``index``: this twin's conversations in the
    team database; ``desk``: its handoffs, what its answers leave to the person. ``after_build``: told, with the store,
    once a build has made the memories and their vectors. ``delegations``: how the person's assistant asks colleagues'
    twins for them (帮我问问…)."""

    @contextmanager
    def open_store() -> Iterator[PersonaStore]:
        with PersonaStore(settings.db_path) as store:
            yield store

    def built(llm: LLM, embedder: Embedder) -> None:
        """What the team does with a twin's memories once they are built (``after_build``). It never fails the build:
        what goes wrong in it is logged."""
        if after_build is None:
            return
        try:
            with open_store() as store:
                after_build(store, llm, embedder)
        except Exception:
            logger.warning("could not bring the team's view of the twin up to date after its build", exc_info=True)

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
            synced = store.get_meta(gate.SYNCED)
            store.clear_source_errors()
        error = None
        failed: list[str] = []
        rows: list[CallRow] = []
        complete = False
        try:
            with collect_calls() as rows:
                llm, embedder = backends.llm(), backends.embedder()
                result = run_persona_build(settings, llm, embedder, log)
                built(llm, embedder)
            failed = result["failed_sources"]
            complete = not result["merge_failed"] and not failed
            if result["merge_failed"]:
                error = "部分记忆处理失败，请重新处理"
            elif complete and synced is not None and on_built is not None:
                on_built(int(synced))
            return result
        except Exception:
            error = (
                "模型服务限流，记忆没有整理完，请稍后重试"
                if rate_limited(rows)
                else "记忆处理失败，请检查模型配置后重试"
            )
            # Backend exceptions can contain prompts. Do not pass them to job logs.
            raise RuntimeError(error) from None
        finally:
            with open_store() as store:
                store.processing_result(ids, version, error, failed)
            if synced is not None and on_spent is not None:
                on_spent(model_tokens(rows))
            if synced is not None and not complete and on_unbuilt is not None:
                on_unbuilt(rate_limited(rows))

    processing = PersonaProcessing(jobs, automatic_build, lambda snapshot: None)
    app.state.processing = processing

    def queue_build() -> None:
        with open_store() as store:
            store.clear_source_errors()
        processing.queue()

    from . import conversations, identity

    conversations.register(app, settings, index, desk)
    identity.register(app, settings, queue_build)

    from . import uploads

    ingestion = uploads.register(app, settings, jobs, queue_build, backends.llm)
    assistant_routes.register(app, settings, queue_build, ingestion.lock, open_store)
    from . import fill as fill_routes

    fill_routes.register(app, settings, backends, queue_build, ingestion.lock, open_store)
    from . import observations as observation_routes

    observation_routes.register(app, settings, backends, ingestion.lock, open_store)
    from . import self_ratings as self_rating_routes

    self_rating_routes.register(app, ingestion.lock, open_store)
    from . import will as will_routes

    will_routes.register(app, ingestion.lock, open_store)
    from . import claims

    claims.register(app, settings, ingestion)
    from . import transcripts

    transcripts.register(app, settings, queue_build)
    from . import ledger

    ledger.register(app, settings, backends, jobs, desk)
    from . import followups
    from . import handoffs as handoff_routes

    followups.register(app, settings, queue_build, desk)
    handoff_routes.register(app, settings, desk, queue_build, backends)
    from . import work

    work.register(app, settings, backends, jobs, lambda store, refs, audience: cited_view(store, refs, None, audience))

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

    # Called after an administrator chose another embedding model in the system settings.
    app.state.resume_index = resume_index

    def index_behind() -> bool:
        """Whether the twin's index waits for vectors (``IndexRetry``)."""
        if not settings.db_path.is_file():
            return False
        try:
            embedder = backends.embedder()
        except BackendUnavailable:
            return False
        with open_store() as store:
            return index_stale(store, embedder)

    app.state.index_behind = index_behind
    previous_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with previous_lifespan(app):
            await run_in_threadpool(ingestion.sweep)
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
            progress = build_progress(store) if view["state"] == "running" else None
        if progress:
            view["progress"] = progress
        return view

    def build_progress(store: PersonaStore) -> dict[str, Any] | None:
        """The running build's phase, its chunks read and to read, and once it merges, its batches merged."""
        progress = store.build_progress()
        if not progress:
            return None
        phase, chunks = progress
        view: dict[str, Any] = {
            "phase": phase,
            "done": sum(done for done, _ in chunks.values()),
            "total": sum(total for _, total in chunks.values()),
        }
        merging = store.merge_progress() if phase == "merge" else None
        if merging:
            view["merged"], view["to_merge"] = merging
        return view

    def build_status() -> dict[str, Any]:
        """How far the build has gone, in the shape of ``/api/persona/processing``, for the team's cards."""
        view = processing.view()
        status: dict[str, Any] = {"state": view["state"]}
        snapshot = jobs.snapshot(view["job_id"]) if view["job_id"] is not None else None
        if snapshot is not None:
            status["stage"], status["tally"] = snapshot["stage"], snapshot["tally"]
        if view["state"] == "running":
            with open_store() as store:
                progress = build_progress(store)
            if progress:
                status["progress"] = progress
        elif view["state"] == "idle":
            with open_store() as store:
                if error := store.get_meta("processing_last_error"):
                    status["last_error"] = error
        return status

    app.state.build_status = build_status

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
    def source_text(source_id: str, request: Request) -> str:
        with open_store() as store:
            source = store.get_source(source_id)
            # A note the person kept to themself is not for those who manage the twin either.
            if source is None or (request_audience(request) != SELF and source_id in store.private_note_sources()):
                raise HTTPException(404, "找不到这条记忆")
            # The person's own text as written, dreams included and marked: the twin does not read them.
            expressions = expression_view(store, settings, source_id=source_id, mirror=True)
            speaker_lines = source.kind in {SourceKind.CHAT, SourceKind.INTERVIEW, SourceKind.AUDIO, SourceKind.VIDEO}
            return "\n\n".join(
                (f"{e.context}\n" if e.context and not source.media_sha else "")
                + (DREAM_MARK if e.mirror == "dream" else "")
                + (f"{e.speaker}：{e.text}" if speaker_lines else e.text)
                for e in expressions
            )[:20000]

    @app.get("/api/persona/sources")
    def list_sources(
        request: Request,
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
            if request_audience(request) != SELF:
                private = store.private_note_sources()
                sources = [s for s in sources if s.source_id not in private]
            memories = source_memories(store, sources)
            statuses = store.source_statuses(sources, {sid: m.items_supported for sid, m in memories.items()})
            progress = store.build_progress() if running else None
        chunks = progress[1] if progress else {}

        def busy(source: Source) -> bool:
            state = statuses[source.source_id]
            return (
                state in MEDIA_PENDING
                or state == "processing"
                or (source.candidates_pending and state not in {"failed", "needs_asr", "needs_speaker", "needs_name"})
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
                "needs_name": sum(statuses[s.source_id] == "needs_name" for s in sources),
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

    def hidden_words(store: PersonaStore, request: Request) -> PrivateWords:
        """The words the viewer may not be shown in an item's evidence: the notes the person kept to themself, for a
        viewer of the colleague tier (an item opened to colleagues may still quote one), none for the person. An item
        a colleague can see is of their tier, so no other words of it are private."""
        if request_audience(request) == SELF:
            return PrivateWords()
        return PrivateWords(sources=frozenset(store.private_note_sources()))

    def item_view(i: PersonaItem, tiers: dict[str, Tier], hidden: PrivateWords) -> dict[str, Any]:
        facet = FACET_BY_ID[i.facet_id]
        if hidden and any(e.expression_id in hidden for e in i.evidence):
            i = i.model_copy(update={"evidence": [e for e in i.evidence if e.expression_id not in hidden]})
        return {
            **i.model_dump(mode="json"),
            "facet_name": facet.name,
            "dimension_id": facet.dimension_id,
            "dimension_name": DIMENSION_BY_ID[facet.dimension_id].name,
            "occasions": i.occasions(),
            "tier": item_tier(i, tiers),
            "tier_changed": i.item_id in tiers,
        }

    @app.get("/api/persona/items")
    def list_items(
        request: Request,
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
                audience=request_audience(request),
            )
            tiers = store.item_tiers()
            hidden = hidden_words(store, request)
            views = [item_view(i, tiers, hidden) for i in items]
            result: dict[str, Any] = {"items": views, "total": total}
            if with_sources:
                cited = sorted({e["source_id"] for v in views for e in v["evidence"] if e["source_id"]})
                result["sources"] = {
                    sid: {"title": source.title, "first_date": source.first_date, "kind": source.kind.value}
                    for sid in cited
                    if (source := store.get_source(sid)) is not None
                }
        return result

    @app.get("/api/persona/items/search")
    def search_profile_items(
        request: Request,
        q: Annotated[str, Query(min_length=1, max_length=200)],
        limit: Annotated[int, Query(ge=1, le=MAX_PAGE_SIZE)] = SEARCH_SIZE,
    ) -> dict[str, Any]:
        """The items closest to ``q`` by meaning and keywords, best first, as chat retrieval finds them: where the
        person looks for what the twin knows about something, to correct or remove it. Falls back to keywords alone
        when the embedding service is unavailable."""
        query = q.strip()
        if not query:
            raise HTTPException(400, "请输入要找的内容")
        audience = request_audience(request)
        with open_store() as store:
            try:
                found = search_items(store, backends.embedder(), query, limit, audience)
            except (BackendUnavailable, EmbedError, ValueError):
                found = search_items(store, None, query, limit, audience)
            tiers = store.item_tiers()
            hidden = hidden_words(store, request)
        return {"items": [item_view(i, tiers, hidden) for i in found], "total": len(found)}

    @app.get("/api/persona/items/summary")
    def items_summary(request: Request) -> dict[str, Any]:
        """Item counts per dimension in taxonomy order, rejected items left out, and how many have evidence that
        disagrees (worth a look, never a queue to work through)."""
        with open_store() as store:
            audience = request_audience(request)
            counts = store.item_counts(audience)
            _, conflicts = store.query_items(conflict=True, limit=0, audience=audience)
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
    def review_item(item_id: str, body: ReviewBody, request: Request) -> dict[str, Any]:
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
            visible_item(store, item_id, request_audience(request))
            try:
                store.set_review(item_id, review)
            except KeyError as e:
                raise HTTPException(404, f"找不到档案条目 {item_id}（可能已在重新构建时合并）") from e
            item = store.get_item(item_id)
            assert item is not None
            return item_view(item, store.item_tiers(), hidden_words(store, request))

    @app.put("/api/persona/items/{item_id}/tier")
    def set_item_tier(item_id: str, body: TierBody, request: Request) -> dict[str, Any]:
        """Say who may use an item: colleagues' conversations or only the person (``tier``), or with null go back to the
        default of its facet. Only the person themself decides, and only about items they can see."""
        if request_audience(request) != SELF:
            raise HTTPException(403, "只有本人可以改记忆的档位")
        with open_store() as store:
            visible_item(store, item_id, SELF)
            store.set_item_tier(item_id, body.tier)
            item = store.get_item(item_id)
            assert item is not None
            return item_view(item, store.item_tiers(), hidden_words(store, request))

    @app.get("/api/persona/coverage")
    def get_coverage(request: Request, as_of: str | None = None) -> dict[str, Any]:
        """What the twin knows per facet, of the memories the viewer may see: the person sees all of it, anyone else
        only the colleague tier, which can be less."""
        with open_store() as store:
            items = for_audience(store.list_items(), store.item_tiers(), request_audience(request))
            report = coverage_report(items, consented_facets(store), _date(as_of, "as_of"), demand=store.chat_demand())
        data = report.model_dump(mode="json")
        data["level_labels"] = LEVEL_LABELS
        data["checked_label"] = CHECKED_LABEL
        data["kind_labels"] = {k.value: v for k, v in SOURCE_KIND_LABELS.items()}
        data["taxonomy"] = TAXONOMY_VERSION
        return data

    # A chat is admitted (backends ready, a place in the chat queue) before its user turn is saved, so a rejected
    # message, which the page offers to send again, leaves nothing behind.

    @app.post("/api/persona/chat", status_code=202)
    def start_chat(body: ChatBody, request: Request) -> Any:
        if body.preview:
            raise HTTPException(400, "试问请用流式聊天")
        messages = validate_chat(body)
        email = owner(request)
        audience = index.audience(body.conversation_id, request_audience(request))
        asker = (desk, request_asker_name(request))
        with open_store() as store:
            if in_crisis(messages[-1].content):
                append_user(store, body.conversation_id, email, messages[-1].content, index)
                payload = {**chat_payload(store, crisis_reply(), audience=audience), "crisis": True}
                return JSONResponse(append_reply(store, body.conversation_id, email, payload, index), status_code=200)
            if not store.has_items():
                append_user(store, body.conversation_id, email, messages[-1].content, index)
                reply = no_profile_reply(store)
                return JSONResponse(
                    append_reply(store, body.conversation_id, email, chat_payload(store, reply), index),
                    status_code=200,
                )
        llm, embedder = backends.chat_llm(), backends.embedder()

        def accept(job: Job) -> None:
            with open_store() as store:
                append_user(store, body.conversation_id, email, messages[-1].content, index)

        job = jobs.submit(
            "chat",
            "和分身聊天",
            lambda log: run_chat(
                settings,
                llm,
                embedder,
                messages,
                log,
                body.conversation_id,
                email,
                audience,
                index,
                asker,
                audience == SELF and bool(request.scope.get("twin_person")),
                body.reflection,
            ),
            prepare=accept,
        )
        return {"job_id": job.job_id}

    def crisis_response(message: str, body: ChatBody, email: str | None, audience: Audience) -> StreamingResponse:
        """The message speaks of ending one's life or harming oneself (``persona.crisis``): the conversation stops
        with the fixed reply that says where help is. No model is asked, so nothing can delay or change it; a trial
        question keeps nothing, as always."""

        def keep() -> dict[str, Any]:
            with open_store() as store:
                payload = {**chat_payload(store, crisis_reply(), audience=audience), "crisis": True}
                payload["completed_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")
                if body.preview:
                    return payload
                append_user(store, body.conversation_id, email, message, index)
                return append_reply(store, body.conversation_id, email, payload, index)

        async def events() -> AsyncGenerator[str]:
            yield ": connected\n\n"
            try:
                final = await off_loop(keep)
            except HTTPException as e:
                yield sse_event("error", {"detail": str(e.detail)})
                return
            yield sse_event("delta", {"text": final["reply"]})
            yield sse_event("final", final)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def note_response(note: str, message: str, body: ChatBody, email: str | None) -> StreamingResponse:
        """The person asked the assistant to remember something (``记一下``): it is kept as a note, in the tier that is
        theirs alone until they choose, and answered at once; nothing is asked of the model, so nothing is lost to a
        reply that did not take it down."""

        def keep() -> dict[str, Any]:
            with open_store() as store:
                append_user(store, body.conversation_id, email, message, index)
                payload = chat_payload(store, note_reply(), audience=SELF)
                payload["note"] = keep_note(store, settings, note)
                payload["completed_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")
                return append_reply(store, body.conversation_id, email, payload, index)

        async def events() -> AsyncGenerator[str]:
            yield ": connected\n\n"
            try:
                final = await off_loop(keep)
            except HTTPException as e:
                yield sse_event("error", {"detail": str(e.detail)})
                return
            except Exception:
                yield sse_event("error", {"detail": "没能记下，请重试"})
                return
            await off_loop(queue_build)
            yield sse_event("delta", {"text": final["reply"]})
            yield sse_event("final", final)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def delegate_response(
        asked: Asked | Unclear,
        message: str,
        body: ChatBody,
        request: Request,
        email: str | None,
        asker_name: str,
    ) -> StreamingResponse:
        """The person told their assistant to ask colleagues' twins (帮我问问…): it puts the question to them in the
        person's name, each in a conversation of its own, and answers with who it asked. What cannot be carried out is
        said, and nobody is asked."""
        assert delegations is not None
        identity = request.scope["twin_identity"]
        llm = backends.chat_llm() if isinstance(asked, Asked) else None
        embedder = backends.embedder() if isinstance(asked, Asked) else None
        # Asking takes the models' time: a place in the chat queue is held while the colleagues' twins answer. Taken
        # after the models are reached, so one that is not available leaves no place held.
        ticket = jobs.admit_stream() if isinstance(asked, Asked) else None
        try:
            with open_store() as store:
                append_user(store, body.conversation_id, email, message, index)
            name = stored_identity(settings.db_path)[0] or settings.target_name
        except BaseException:
            if ticket is not None:
                ticket.close()
            raise

        def put() -> dict[str, Any]:
            with open_store() as store:
                if isinstance(asked, Asked) and llm is not None and embedder is not None:
                    payload = delegations.ask(
                        persona_id=desk.persona_id,
                        store=store,
                        identity=identity,
                        asker_name=asker_name,
                        conversation_id=body.conversation_id,
                        asked=asked,
                        llm=llm,
                        embedder=embedder,
                        name=name,
                        effort=settings.effective_chat_llm.effort_extract,
                    )
                else:
                    assert isinstance(asked, Unclear)
                    payload = delegations.refusal(store, asked.reply)
                payload["completed_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")
                return append_reply(store, body.conversation_id, email, payload, index, assistant=True)

        async def events() -> AsyncGenerator[str]:
            yield ": connected\n\n"
            work: asyncio.Future[dict[str, Any]] | None = None
            try:
                if ticket is not None:
                    async with ticket.running():
                        work = asyncio.ensure_future(off_loop(put))
                        while not (await asyncio.wait({work}, timeout=10))[0]:
                            yield ": heartbeat\n\n"
                else:
                    work = asyncio.ensure_future(off_loop(put))
                    await work
                final = work.result()
            except HTTPException as e:
                yield sse_event("error", {"detail": str(e.detail)})
                return
            except Exception:
                logger.warning("could not ask colleagues' twins", exc_info=True)
                yield sse_event("error", {"detail": "没能去问，请重试"})
                return
            finally:
                if work is not None and not work.done():
                    work.cancel()
            yield sse_event("delta", {"text": final["reply"]})
            yield sse_event("final", final)

        return AdmittedStream(
            events(),
            ticket,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    def stream_chat_response(
        body: ChatBody, request: Request, attachment_passages: Sequence[AttachmentPassage] = ()
    ) -> StreamingResponse:
        messages = validate_chat(body)
        email = owner(request)
        # The ledger is private: only a conversation of the tier that may use everything has it, never a visitor's or
        # a manager's.
        audience = index.audience(body.conversation_id, request_audience(request))
        asker_name = request_asker_name(request)
        ledger = audience == SELF and not request.scope.get("twin_visitor")
        preview = body.preview
        if preview:
            # 看同事会得到什么: the last message alone, answered from the colleague tier, with nothing saved.
            person_only(request)
            audience, ledger, messages = COLLEAGUE, False, messages[-1:]
        # Before anything else, whoever asks: a message of ending one's life or harming oneself stops here.
        if in_crisis(messages[-1].content):
            return crisis_response(messages[-1].content, body, email, audience)
        # The person's own conversation is answered by their assistant, which also takes down notes and promises.
        assistant = audience == SELF and bool(request.scope.get("twin_person")) and not preview
        if assistant and not attachment_passages and (note := note_text(messages[-1].content)) is not None:
            return note_response(note, messages[-1].content, body, email)
        if (
            assistant
            and not attachment_passages
            and delegations is not None
            and (asked := delegations.parse(messages[-1].content, request.scope["twin_identity"])) is not None
        ):
            return delegate_response(asked, messages[-1].content, body, request, email, asker_name)
        with open_store() as store:
            profiled = store.has_items() or bool(attachment_passages)
        ticket: Ticket | None = None
        if profiled:
            llm, embedder = backends.chat_llm(), backends.embedder()
            ticket = jobs.admit_stream()
        try:
            if not preview:
                with open_store() as store:
                    append_user(store, body.conversation_id, email, messages[-1].content, index)
        except BaseException:
            if ticket is not None:
                ticket.close()
            raise

        started_at = time.monotonic()
        # The team's answers that match the question, found before the twin answers and shown apart from its words.
        shown: list[dict[str, Any]] = []

        def save(store: PersonaStore, reply: ChatReply) -> dict[str, Any]:
            payload = chat_payload(store, reply, attachment_passages, audience)
            if shown:
                payload["team_answers"] = shown
            payload["elapsed_ms"] = max(0, round((time.monotonic() - started_at) * 1000))
            payload["completed_at"] = dt.datetime.now(dt.UTC).isoformat(timespec="milliseconds")
            # The way the person was talking with their assistant, for what they say of the answer (自评记录).
            if assistant and body.reflection:
                payload["reflection"] = body.reflection
            if preview:
                payload["preview"] = {"withheld": trial_withheld(store, llm, embedder, settings, messages[-1].content)}
                return payload
            return append_reply(
                store,
                body.conversation_id,
                email,
                payload,
                index,
                (desk, asker_name, audience),
                assistant=assistant,
            )

        def unbuilt() -> tuple[str, dict[str, Any]]:
            with open_store() as store:
                reply = no_profile_reply(store)
                if preview:
                    return reply.reply, chat_payload(store, reply, audience=COLLEAGUE)
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
                if desk.answers is not None:
                    asked = question_of([m.content for m in messages if m.role == "user"])
                    shown.extend(
                        await off_loop(
                            partial(desk.answers.cards_for, asked, embedder, asker=None if preview else email)
                        )
                    )
                with await open_store_off_loop(settings.db_path) as store:
                    # Off the loop: it checks the twin's memory gate, which reads the store.
                    chat = await off_loop(
                        partial(
                            PersonaChat,
                            store,
                            llm,
                            embedder,
                            settings,
                            ledger=ledger,
                            audience=audience,
                            reach=desk.reach(None if preview else email),
                            assistant=assistant,
                            # 看同事会得到什么 is asked by nobody in particular.
                            asker=None if preview else chat_asker(desk, email, asker_name),
                            reflection=body.reflection,
                        )
                    )
                    # What the person answered themself in this conversation settles it; read here, from what the
                    # server saved, never from what the page sends.
                    owner_said = await off_loop(partial(store.owner_replies, body.conversation_id or "", email))
                    async with aclosing(
                        chat.stream_reply(
                            messages,
                            attachments=attachment_passages,
                            persist=not attachment_passages and not preview,
                            owner_said=[] if preview else owner_said,
                            team_answers=[prompt_line(c) for c in shown],
                            steps=True,
                        )
                    ) as replies:
                        async for result in replies:
                            if isinstance(result, Step):
                                yield sse_event("step", {"step": result.name})
                            elif isinstance(result, str):
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
            except gate.MemoryUpdating as e:
                yield sse_event("error", {"detail": str(e), "code": "memory_updating"})
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

            def build(log: Log) -> dict[str, Any]:
                result = run_persona_build(settings, llm, embedder, log)
                built(llm, embedder)
                return result

            job = jobs.submit("persona_build", "构建人格档案", build)
        except Exception as e:
            # Model not configured or another build running: the answers are saved, the build can start later.
            return {"round": "initial", "job_id": None, "notice": f"{notice}；构建没有自动开始：{e}"}
        return {"round": "initial", "job_id": job.job_id, "notice": f"{notice}，正在构建人格档案"}

    return ingestion


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
