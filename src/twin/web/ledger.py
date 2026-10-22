"""Web routes of the commitment ledger (``/api/persona/ledger...``): browse entries with their current status,
review them, read them from meetings in the background, and the pre-meeting brief for one person."""

from __future__ import annotations

import datetime as dt
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from ..config import Settings
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
from .backends import Backends
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


def register(app: FastAPI, settings: Settings, backends: Backends, jobs: JobManager) -> None:
    admission = threading.Lock()

    @contextmanager
    def open_store() -> Iterator[PersonaStore]:
        with PersonaStore(settings.db_path) as store:
            yield store

    def meetings(store: PersonaStore) -> tuple[int, int]:
        """(meeting sources, those the current extractor has not read yet)."""
        ids = [s.source_id for s in store.list_sources() if is_meeting(s)]
        return len(ids), sum(1 for i in ids if store.ledger_done(i) != LEDGER_VERSION)

    @app.get("/api/persona/ledger")
    def list_ledger(
        kind: LedgerKind | None = None,
        owner: str | None = Query(default=None, max_length=80),
        status: LedgerStatus | None = None,
        include_rejected: bool = False,
    ) -> dict[str, Any]:
        """Entries in meeting order with their current status. ``status`` filters on the current status."""
        with open_store() as store:
            ledger = store.list_ledger()
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
    def review(entry_id: str, body: LedgerReviewBody) -> dict[str, Any]:
        """Confirm, correct (``changes`` holds only the corrected fields), reject, or reset an entry to unreviewed."""
        changes = body.changes.model_dump(exclude_unset=True) if body.changes else {}
        if body.action == "edit" and not changes:
            raise HTTPException(400, "修改时请给出要改的内容")
        if body.action != "edit" and changes:
            raise HTTPException(400, "只有修改时才能附带要改的内容")
        if any(key in changes and changes[key] is None for key in ("owner", "what")):
            raise HTTPException(400, "负责人和内容不能清空")
        changes.update({key: "" for key in ("counterpart", "condition") if key in changes and changes[key] is None})
        with open_store() as store:
            try:
                revised = review_entry(store, entry_id, body.action, changes)
            except KeyError as e:
                raise HTTPException(404, f"找不到账本条目 {entry_id}（可能已在重新整理时替换）") from e
            ledger = [e for e in store.list_ledger() if e.review is not ReviewStatus.REJECTED]
        return entry_view(revised, ledger)

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
                )
            log(f"读了 {report.sources} 场会议，记下 {report.entries} 条")
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

    # For the system settings, which list and start every twin's ledger upgrade.
    app.state.ledger_status = ledger_status
    app.state.ledger_build = start_build

    @app.get("/api/persona/ledger/brief")
    def get_brief(person: str = Query(min_length=1, max_length=80), as_of: dt.date | None = None) -> dict[str, Any]:
        """What to bring up with ``person``: their open commitments, what was promised to them, recent progress,
        their objections and the questions to ask, as of ``as_of`` (today when omitted)."""
        with open_store() as store:
            ledger = [e for e in store.list_ledger() if e.review is not ReviewStatus.REJECTED]
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
