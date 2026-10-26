"""Web routes of the commitment ledger (``/api/persona/ledger...``): browse entries with their current status,
review them, read them from meetings in the background, and the pre-meeting brief for one person."""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
from ..handoffs import PENDING_ACCEPT, HandoffDesk, HandoffRefused
from ..persona.ledger import (
    KIND_LABELS,
    LEDGER_VERSION,
    STATUS_LABELS,
    brief,
    build_ledger,
    confirmation_message,
    current_status,
    is_meeting,
    people,
    review_entry,
    thread_root,
)
from ..persona.schema import LedgerEntry, LedgerKind, LedgerStatus, ReviewStatus
from ..persona.store import PersonaStore, stored_identity
from ..persona.tiers import SELF
from .backends import Backends
from .conversations import request_audience
from .handoffs import person
from .jobs import JobConflict, JobManager, Log


class LedgerChanges(BaseModel):
    """The fields a correction may change; any other field is refused."""

    model_config = ConfigDict(extra="forbid")

    owner: str | None = Field(default=None, min_length=1, max_length=80)
    counterpart: str | None = Field(default=None, max_length=80)
    what: str | None = Field(default=None, min_length=1, max_length=500)
    due: dt.date | None = None
    condition: str | None = Field(default=None, max_length=500)
    status: LedgerStatus | None = None


class LedgerReviewBody(BaseModel):
    action: Literal["confirm", "edit", "reject", "reset"]
    changes: LedgerChanges | None = None


class LedgerBuildBody(BaseModel):
    force: bool = False


def asked_in_conversation(entry: LedgerEntry) -> bool:
    """A promise someone asked the person for in a conversation with their twin (from a handoff): it holds the
    asker's question and name, which are the person's alone to see, as the handoff is."""
    return entry.origin == "conversation"


def is_person(request: Request) -> bool:
    """Whether the signed-in person is the one the twin is made for (``handoffs.person``, without refusing)."""
    return request_audience(request) == SELF and not request.scope.get("twin_visitor")


def entry_view(
    entry: LedgerEntry, ledger: list[LedgerEntry], by_id: dict[str, LedgerEntry] | None = None
) -> dict[str, Any]:
    """``ledger`` is the live ledger the status is derived from; ``by_id`` its entries by id, when already built."""
    status = current_status(entry, ledger)
    by_id = by_id if by_id is not None else {e.entry_id: e for e in ledger}
    return {
        **entry.model_dump(mode="json"),
        "kind_label": KIND_LABELS[entry.kind],
        "status_label": STATUS_LABELS[entry.status] if entry.status else None,
        "current_status": status,
        "current_status_label": STATUS_LABELS[status],
        "thread": thread_root(entry, by_id) if entry.entry_id in by_id else entry.entry_id,
        "confirmation_message": confirmation_message(entry),
    }


def register(app: FastAPI, settings: Settings, backends: Backends, jobs: JobManager, desk: HandoffDesk) -> None:
    admission = threading.Lock()
    # Set while an administrator has the ledger switched off.
    switched_off = threading.Event()

    @contextmanager
    def open_store() -> Iterator[PersonaStore]:
        with PersonaStore(settings.db_path) as store:
            yield store

    def meetings(store: PersonaStore) -> tuple[int, int]:
        """(meeting sources, those the current extractor has not read yet)."""
        ids = [s.source_id for s in store.list_sources() if is_meeting(s)]
        return len(ids), sum(1 for i in ids if store.ledger_done(i) != LEDGER_VERSION)

    def shown(ledger: list[LedgerEntry], request: Request) -> list[LedgerEntry]:
        """The entries this signed-in person may see: anyone but the person (a manager, an administrator) not the
        ones asked for in conversations."""
        return ledger if is_person(request) else [e for e in ledger if not asked_in_conversation(e)]

    @app.get("/api/persona/ledger")
    def list_ledger(
        request: Request,
        kind: LedgerKind | None = None,
        owner: str | None = Query(default=None, max_length=80),
        status: LedgerStatus | None = None,
        include_rejected: bool = False,
    ) -> dict[str, Any]:
        """Entries in meeting order with their current status. ``status`` filters on the current status."""
        with open_store() as store:
            ledger = shown(store.list_ledger(), request)
            total, pending = meetings(store)
        live = [e for e in ledger if e.review is not ReviewStatus.REJECTED]
        by_id = {e.entry_id: e for e in live}
        rows = [entry_view(e, live, by_id) for e in (ledger if include_rejected else live)]
        rows = [
            r
            for r in rows
            if (kind is None or r["kind"] == kind)
            and (owner is None or r["owner"] == owner)
            and (status is None or r["current_status"] == status)
        ]
        job = jobs.active_of("ledger_build")
        return {
            "entries": rows,
            "people": people(live),
            "kind_labels": KIND_LABELS,
            "status_labels": STATUS_LABELS,
            "meetings": {"total": total, "pending": pending},
            "job_id": job.job_id if job else None,
        }

    @app.post("/api/persona/ledger/{entry_id}/review")
    def review(entry_id: str, body: LedgerReviewBody, request: Request) -> dict[str, Any]:
        """Confirm, correct (``changes`` holds only the corrected fields), reject, or reset an entry to unreviewed. One
        asked for in a conversation only the person can."""
        changes = body.changes.model_dump(exclude_unset=True) if body.changes else {}
        if body.action == "edit" and not changes:
            raise HTTPException(400, "修改时请给出要改的内容")
        if body.action != "edit" and changes:
            raise HTTPException(400, "只有修改时才能附带要改的内容")
        if any(key in changes and changes[key] is None for key in ("owner", "what")):
            raise HTTPException(400, "负责人和内容不能清空")
        if changes.get("status") == PENDING_ACCEPT:
            raise HTTPException(400, "待你接受只在别人请你答应一件事时出现，不能手动设置")
        changes.update({key: "" for key in ("counterpart", "condition") if key in changes and changes[key] is None})
        with open_store() as store:
            found = store.get_ledger_entry(entry_id)
            if found is not None and asked_in_conversation(found):
                person(request)
            if found is not None and found.status == PENDING_ACCEPT:
                # Taken or turned down on the handoff it came from (接下 / 不接), which answers the asker: here it
                # would leave the asker without an answer, or a turned-down promise waiting to be taken again.
                raise HTTPException(409, "这件事要用“接下”或“不接”回复，不能在这里改")
            try:
                revised = review_entry(store, entry_id, body.action, changes)
            except KeyError as e:
                raise HTTPException(404, f"找不到账本条目 {entry_id}（可能已在重新整理时替换）") from e
            ledger = [e for e in shown(store.list_ledger(), request) if e.review is not ReviewStatus.REJECTED]
        return entry_view(revised, ledger)

    class AcceptBody(BaseModel):
        model_config = ConfigDict(extra="forbid")
        due: dt.date | None = None

    def taken(entry_id: str, request: Request, act: Callable[[str | None], Any]) -> dict[str, Any]:
        """A promise someone asked the person for in a conversation, taken or turned down: the handoff it came from
        writes the answer back to the asker. Only the person themself can."""
        me = person(request)
        if desk.team is None:
            raise HTTPException(503, "团队库没有打开")
        try:
            handoff = act(me)
        except HandoffRefused as e:
            raise HTTPException(409, str(e)) from e
        if handoff is None:
            raise HTTPException(404, "这条不是别人在对话里请你答应的事")
        with open_store() as store:
            entry = store.get_ledger_entry(entry_id)
            ledger = [e for e in store.list_ledger() if e.review is not ReviewStatus.REJECTED]
        return entry_view(entry, ledger) if entry is not None else {"entry_id": entry_id}

    @app.post("/api/persona/ledger/{entry_id}/accept")
    def accept(entry_id: str, request: Request, body: AcceptBody | None = None) -> dict[str, Any]:
        """接下: take on a promise someone asked for in a conversation (on a new date if ``due``)."""
        due = body.due if body else None
        return taken(entry_id, request, lambda me: desk.accept_ledger_entry(entry_id, me, due))

    @app.post("/api/persona/ledger/{entry_id}/decline")
    def decline(entry_id: str, request: Request) -> dict[str, Any]:
        """不接: turn down a promise someone asked for in a conversation."""
        return taken(entry_id, request, lambda me: desk.decline_ledger_entry(entry_id, me))

    @app.post("/api/persona/ledger/build", status_code=202)
    def start_build(body: LedgerBuildBody | None = None) -> dict[str, Any]:
        """Read the meetings not read yet (all of them with ``force``) in the background."""
        force = body.force if body else False
        with open_store() as store:
            total, pending = meetings(store)
        if total == 0:
            raise HTTPException(400, "还没有会议：请先添加有本人和其他人发言的录音或转写，并确认哪位是本人")
        if pending == 0 and not force:
            return {"job_id": None, "notice": "所有会议都已整理过"}
        llm = backends.llm()
        name = stored_identity(settings.db_path)[0] or settings.target_name

        def run(log: Log) -> dict[str, Any]:
            with open_store() as store:
                report = build_ledger(
                    store,
                    llm,
                    name,
                    effort=settings.llm.effort_extract,
                    reasoning_effort=settings.llm.effective_reasoning_effort_extract,
                    force=force,
                    log=log,
                    stopped=switched_off.is_set,
                )
            stop = "，承诺账本已关闭，其余会议没有读" if report.stopped else ""
            log(f"读了 {report.sources} 场会议，记下 {report.entries} 条{stop}")
            return asdict(report)

        with admission:
            active = jobs.active_of("ledger_build")
            if active is not None:
                raise JobConflict(active)
            job = jobs.submit("ledger_build", "整理承诺账本", run)
        return {"job_id": job.job_id, "notice": None}

    def ledger_status() -> dict[str, Any]:
        with open_store() as store:
            total, pending = meetings(store)
        return {"meetings": total, "pending": pending, "running": jobs.active_of("ledger_build") is not None}

    def ledger_switched(enabled: bool) -> None:
        """An administrator switched the ledger on or off: a build that is running stops before its next meeting."""
        if enabled:
            switched_off.clear()
        else:
            switched_off.set()

    # For the system settings, which list and start every twin's ledger upgrade and switch the ledger off.
    app.state.ledger_status = ledger_status
    app.state.ledger_build = start_build
    app.state.ledger_switched = ledger_switched

    @app.get("/api/persona/ledger/brief")
    def get_brief(
        request: Request, person: str = Query(min_length=1, max_length=80), as_of: dt.date | None = None
    ) -> dict[str, Any]:
        """What to bring up with ``person``: their open commitments, what was promised to them, recent progress,
        their objections and the questions to ask, as of ``as_of`` (today when omitted)."""
        with open_store() as store:
            ledger = [e for e in shown(store.list_ledger(), request) if e.review is not ReviewStatus.REJECTED]
        result = brief(ledger, person, as_of or dt.date.today())

        by_id = {e.entry_id: e for e in ledger}

        def views(entries: list[LedgerEntry]) -> list[dict[str, Any]]:
            return [entry_view(e, ledger, by_id) for e in entries]

        return {
            "person": result.person,
            "as_of": result.as_of.isoformat(),
            "theirs": views(result.theirs),
            "mine": views(result.mine),
            "progress": views(result.progress),
            "objections": views(result.objections),
            "questions": [asdict(q) for q in result.questions],
        }
