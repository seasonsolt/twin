"""``GET /api/personas/commitments``: the commitments of every twin the signed-in person looks after, in one list.

Each twin keeps its own ledger (``persona.ledger``), read from the meetings it was in, so a meeting that several
people spoke in is in several ledgers, each told from its own person's side: "本人" is whoever the ledger belongs to.
The team's list names that person instead and keeps one entry for what was said once. Two entries are the same
commitment when they rest on the same line of the same meeting, are of the same kind and have the same owner; of
the copies, the one the owner's own ledger holds is kept (then a reviewed one, then the surest). Nothing here is
stored: it is read from the twins' databases each time, and the ledgers stay the one place an entry is changed (the
row says which twin's it is). A twin whose memory is being rebuilt from changed recordings is left out until it is
done, as its own ledger is refused meanwhile.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request

from ..media.team import SOURCE_PREFIX
from ..persona import gate
from ..persona.ledger import (
    KIND_LABELS,
    LEDGER_VERSION,
    SELF,
    STATUS_LABELS,
    UNKNOWN_OWNER,
    is_meeting,
    people,
)
from ..persona.schema import LedgerEntry, ReviewStatus
from ..persona.store import PersonaStore, stored_identity
from .ledger import entry_view
from .personas import Personas


def meeting_of(entry: LedgerEntry) -> str:
    """The meeting an entry was read from, the same for every twin that was in it: a recording's id for what the
    library made (its source ids differ per twin, with the person's own lines), else the source itself."""
    if entry.source_id.startswith(SOURCE_PREFIX):
        return entry.source_id[len(SOURCE_PREFIX) :].rsplit("_", 1)[0]
    return entry.source_id


def line_of(entry: LedgerEntry) -> str:
    """Which line of the meeting the entry rests on; numbered the same in every twin's source of a recording."""
    return entry.expression_id.rsplit("#", 1)[-1]


def named(entry: LedgerEntry, who: str) -> LedgerEntry:
    """The entry with "本人" replaced by the name of the person whose ledger it is in, since the list is of several."""
    changes = {field: who for field in ("owner", "counterpart", "speaker") if getattr(entry, field) == SELF}
    return entry.model_copy(update=changes) if changes else entry


def same_commitment(entry: LedgerEntry) -> tuple[str, str, str, str]:
    return (meeting_of(entry), line_of(entry), entry.kind, " ".join(entry.owner.split()).lower())


def merge(ledgers: list[tuple[str, str, list[LedgerEntry]]]) -> list[tuple[str, str, LedgerEntry, list[LedgerEntry]]]:
    """One row for each commitment across the ledgers ``(twin id, person, entries)``: ``(twin id, person, entry,
    that twin's live ledger)``. Entries are named by their person first (``named``)."""
    best: dict[tuple[str, str, str, str], tuple[tuple[int, int, float, int], tuple[str, str, LedgerEntry, Any]]] = {}
    order: list[tuple[str, str, str, str]] = []
    for position, (persona_id, who, entries) in enumerate(ledgers):
        live = [e for e in entries if e.review is not ReviewStatus.REJECTED]
        for entry in entries:
            shown = named(entry, who)
            key = same_commitment(shown)
            # Their own ledger first, then one the person has looked at, then the surest, then the earlier twin.
            rank = (
                int(entry.owner != SELF),
                int(entry.review is ReviewStatus.UNREVIEWED),
                -entry.confidence,
                position,
            )
            if key not in best:
                order.append(key)
            if key not in best or rank < best[key][0]:
                best[key] = (rank, (persona_id, who, shown, live))
    return [best[key][1] for key in order]


def register_all(app: FastAPI, registry: Personas) -> None:
    @app.get("/api/personas/commitments")
    def everyone(request: Request, include_rejected: bool = False) -> dict[str, Any]:
        """The ledgers of the twins the signed-in person looks after (an administrator: every twin) as one list, in
        the shape of ``/api/persona/ledger``, each row with the twin it is kept in."""
        identity = request.scope["twin_identity"]
        with registry.lock:
            looked_after = [
                dict(entry)
                for entry in registry.data["personas"]
                if registry.visible(entry, identity) and registry.accessible(entry, identity)
            ]
        if not looked_after:
            raise HTTPException(403, "只有管理分身的人可以看全部承诺")
        ledgers: list[tuple[str, str, list[LedgerEntry]]] = []
        names: dict[str, str] = {}
        meetings: set[str] = set()
        waiting = 0
        updating: list[dict[str, str]] = []
        for twin in looked_after:
            path = registry.db_path_of(twin["id"])
            if not path.is_file():
                continue
            settings = registry.settings_for(twin["id"])
            who = stored_identity(path)[0] or settings.target_name
            try:
                gate.version_at(path)
            except gate.MemoryUpdating:
                # Its memory is being brought in line with changed recordings: nothing of it is used until then,
                # as in its own ledger (``MemoryGateMiddleware``); the list says whose is missing for now.
                updating.append({"id": twin["id"], "name": who})
                continue
            names[twin["id"]] = who
            with PersonaStore(path) as store:
                entries = store.list_ledger()
                sources = [s for s in store.list_sources() if is_meeting(s)]
                waiting += sum(1 for s in sources if store.ledger_done(s.source_id) != LEDGER_VERSION)
            meetings.update(s.source_id for s in sources if not s.source_id.startswith(SOURCE_PREFIX))
            meetings.update(
                s.source_id[len(SOURCE_PREFIX) :].rsplit("_", 1)[0]
                for s in sources
                if s.source_id.startswith(SOURCE_PREFIX)
            )
            ledgers.append((twin["id"], who, entries))
        merged = merge(ledgers)
        shown = [
            (persona_id, who, entry, live)
            for persona_id, who, entry, live in merged
            if include_rejected or entry.review is not ReviewStatus.REJECTED
        ]
        rows = []
        for persona_id, who, entry, live in shown:
            by_id = {e.entry_id: e for e in live}
            # The status is read from the entry's own ledger, where the entries it relates to are.
            view = entry_view(entry, live, by_id)
            rows.append({**view, "persona_id": persona_id, "persona_name": who, "meeting": meeting_of(entry)})
        listed = [entry for _, _, entry, _ in merged if entry.review is not ReviewStatus.REJECTED]
        return {
            "entries": rows,
            "people": [name for name in people(listed) if name != UNKNOWN_OWNER],
            "kind_labels": KIND_LABELS,
            "status_labels": STATUS_LABELS,
            "meetings": {"total": len(meetings), "pending": waiting},
            "twins": [{"id": persona_id, "name": who} for persona_id, who in names.items()],
            "updating": updating,
            "job_id": None,
        }
