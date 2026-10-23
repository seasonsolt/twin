"""Who knows about a matter: asking the team a question and being told whom to ask.

Every twin keeps its own database, so a question to the whole team cannot be answered by one query. Two things make it
cheap enough to ask from anywhere (⌘K):

- how well each twin knows each facet, as colleagues may use its memories, is cached in the team database
  (``facet_coverage``), made again whenever a twin's memories, reviews or tiers change (``refresh_coverage``) and
  noticed to be out of date by a mark of the twin's items (``PersonaStore.items_signature``) when it was not;
- the vectors of every twin's items, with their facets, are kept in memory (``Finder``) and read again from a twin's
  database only when that mark changes.

A question is put to the items of colleagues' twins by meaning; the facets the closest items stand in are the facets
the question is about; the people are ordered by how well they know those facets (level, then on how many occasions,
then how recently), and no score is shown or kept. Only what colleagues may use counts, at every step: an item of the
person's own tier is neither found nor counted, so a person cannot be recommended for what they keep to themself.
Never recommended: the one who asks, a twin nobody has taken, a twin not open to colleagues, and anyone whose twin
holds nothing about the matter.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from .embed import Embedder, Matrix, embedder_fingerprint
from .persona import gate
from .persona.chat import ITEMS_NS, OWNER_CUE
from .persona.coverage import LEVEL_LABELS, coverage_report
from .persona.dimensions import FACET_BY_ID
from .persona.kernel import KERNEL
from .persona.profile import consented_facets
from .persona.store import PersonaStore
from .persona.tiers import COLLEAGUE, TIERS, default_tier, for_audience
from .teamdb import COVERAGE_SIGNATURE as SIGNATURE
from .teamdb import CoverageRow, TeamDB

logger = logging.getLogger(__name__)

# How many people one question recommends, and how many items of each twin are looked at.
RECOMMEND_LIMIT = 3
ITEMS_LOOKED_AT = 6
# Items count as about the question when they are this near the closest one found anywhere (cosine); and never when
# less alike than the floor, which is the embedder's own idea of "a repeat" less a margin.
BAND = 0.12
FLOOR_MARGIN = 0.3
FLOOR_MIN = 0.3


def kernel_label() -> str:
    """The kernel the cached coverage was made on; another kernel's levels are made again."""
    return f"{KERNEL.prompt}/{KERNEL.taxonomy}"


@dataclass(frozen=True)
class TwinRef:
    """A twin as the finder sees it: where its database is, and who it is made for and whether it is open."""

    persona_id: str
    name: str
    path: Path
    # The account that took the twin; None until someone does.
    member: str | None
    # Open to colleagues' questions.
    public: bool


def eligible(twin: TwinRef, asker: str | None) -> bool:
    """Whether a twin may be recommended to ``asker``: taken by someone else, and open to colleagues."""
    return twin.member is not None and twin.public and twin.member != asker


# ---------------------------------------------------------------- coverage cache


def coverage_rows(persona_id: str, store: PersonaStore, now: dt.datetime | None = None) -> list[CoverageRow]:
    """How well the twin knows each facet it knows at all, from the memories colleagues may use (the reviews applied,
    the person's own tier left out): level 1 to 3, the occasions it stands on and the day it was last said."""
    items = for_audience(store.list_items(), store.item_tiers(), COLLEAGUE)
    report = coverage_report(items, consented_facets(store))
    last: dict[str, dt.date] = {}
    for item in items:
        seen = item.last_seen()
        if seen is not None and (item.facet_id not in last or seen > last[item.facet_id]):
            last[item.facet_id] = seen
    stamp = (now or dt.datetime.now(dt.UTC)).isoformat()
    return [
        CoverageRow(
            persona_id,
            f.facet_id,
            f.level,
            f.occasions,
            last[f.facet_id].isoformat() if f.facet_id in last else None,
            kernel_label(),
            stamp,
        )
        for f in report.facets
        if f.level >= 1
    ]


def refresh_coverage(team: TeamDB, persona_id: str, store: PersonaStore) -> int:
    """Make the cached coverage of a twin again from its memories (after it was built, or its tiers or reviews
    changed); how many facets it knows."""
    rows = coverage_rows(persona_id, store)
    team.replace_coverage(persona_id, rows)
    team.set_meta(f"{SIGNATURE}{persona_id}", f"{kernel_label()}|{store.items_signature()}")
    return len(rows)


@dataclass
class _Vectors:
    signature: str
    model: str
    ids: list[str]
    matrix: Matrix
    # The facet of each row.
    facets: list[str]


EMPTY = np.zeros((0, 0), dtype=np.float32)


class Finder:
    """Recommends whom to ask. Holds the vectors of the colleague-tier items of the twins it has looked at, until a
    twin's items change."""

    def __init__(self, team: TeamDB) -> None:
        self.team = team
        self._lock = threading.RLock()
        self._vectors: dict[str, _Vectors] = {}

    def forget(self, persona_id: str | None = None) -> None:
        with self._lock:
            if persona_id is None:
                self._vectors.clear()
            else:
                self._vectors.pop(persona_id, None)

    def _load(self, twin: TwinRef, model: str) -> _Vectors:
        """The twin's colleague-tier item vectors in ``model``'s space, from memory while its items are as they were;
        its cached coverage is made again here if the items changed behind its back."""
        with PersonaStore(twin.path) as store:
            signature = store.items_signature()
            stamp = f"{kernel_label()}|{signature}"
            if self.team.get_meta(f"{SIGNATURE}{twin.persona_id}") != stamp:
                refresh_coverage(self.team, twin.persona_id, store)
            with self._lock:
                held = self._vectors.get(twin.persona_id)
            if held is not None and held.signature == signature and held.model == model:
                return held
            ids, matrix = (
                store.get_vectors(ITEMS_NS) if store.get_meta(f"embedder:{ITEMS_NS}") == model else ([], EMPTY)
            )
            facet_of: dict[str, str] = {}
            for item_id, facet_id, _ in store.item_support():
                facet_of.setdefault(item_id, facet_id)
            tiers = store.item_tiers()
            keep = [
                i
                for i, item_id in enumerate(ids)
                if item_id in facet_of
                and (tiers.get(item_id) if tiers.get(item_id) in TIERS else default_tier(facet_of[item_id]))
                == COLLEAGUE
            ]
            fresh = _Vectors(
                signature,
                model,
                [ids[i] for i in keep],
                matrix[keep] if keep else EMPTY,
                [facet_of[ids[i]] for i in keep],
            )
        with self._lock:
            self._vectors[twin.persona_id] = fresh
        return fresh

    def recommend(
        self,
        question: str,
        embedder: Embedder,
        twins: Sequence[TwinRef],
        asker: str | None,
        *,
        limit: int = RECOMMEND_LIMIT,
    ) -> list[dict[str, Any]]:
        """Whom to ask about ``question``, best first, at most ``limit``. Each: the twin, how well they know it (level
        and label), the facets it falls in (at most two), on how many occasions and when last. Empty when nobody is
        known to have said anything about it."""
        if not question.strip():
            return []
        model = embedder_fingerprint(embedder)
        query = np.asarray(embedder.embed([question[:2000]])[0], dtype=np.float32)
        floor = max(FLOOR_MIN, float(embedder.cluster_threshold) - FLOOR_MARGIN)
        found: list[tuple[TwinRef, list[tuple[float, str]]]] = []
        for twin in twins:
            if not eligible(twin, asker):
                continue
            try:
                gate.version_at(twin.path)
                vectors = self._load(twin, model)
            except gate.MemoryUpdating:
                # Its memory is being brought in line with changed recordings; nothing of it is used until then.
                continue
            except (OSError, ValueError):
                logger.warning("could not look into twin %s", twin.persona_id, exc_info=True)
                continue
            if not vectors.ids:
                continue
            sims = vectors.matrix @ query
            order = np.argsort(-sims)[:ITEMS_LOOKED_AT]
            hits = [(float(sims[i]), vectors.facets[i]) for i in order if sims[i] >= floor]
            if hits:
                found.append((twin, hits))
        if not found:
            return []
        closest = max(hits[0][0] for _, hits in found)
        rows = {
            (r.persona_id, r.facet_id): r
            for r in self.team.coverage([twin.persona_id for twin, _ in found])
            if r.level >= 1
        }
        ranked: list[tuple[tuple[int, int, int, float, str], dict[str, Any]]] = []
        for twin, hits in found:
            if hits[0][0] < closest - BAND:
                continue
            about = list(dict.fromkeys(f for sim, f in hits if sim >= hits[0][0] - BAND))
            known = [rows[(twin.persona_id, f)] for f in about if (twin.persona_id, f) in rows]
            if not known:
                continue
            level = max(r.level for r in known)
            top = [r for r in known if r.level == level]
            occasions = sum(r.occasions for r in top)
            seen = max((r.last_seen for r in known if r.last_seen), default=None)
            key = (
                -level,
                -occasions,
                -(dt.date.fromisoformat(seen).toordinal() if seen else 0),
                -hits[0][0],
                twin.persona_id,
            )
            ranked.append(
                (
                    (key[0], key[1], key[2], key[3], key[4]),
                    {
                        "persona_id": twin.persona_id,
                        "name": twin.name,
                        "level": level,
                        "label": LEVEL_LABELS[level],
                        "occasions": occasions,
                        "last_seen": seen,
                        "facets": [FACET_BY_ID[r.facet_id].name for r in top][:2],
                    },
                )
            )
        ranked.sort(key=lambda pair: pair[0])
        return [view for _, view in ranked[:limit]]


def asks_for_decision(question: str) -> bool:
    """Whether the question asks someone to decide, promise or judge: the answer will be theirs to give, and their
    twin hands it to them."""
    return bool(OWNER_CUE.search(question))
