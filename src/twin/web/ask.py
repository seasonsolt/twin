"""``GET /api/personas/ask?q=``: 问一句、找人, from ⌘K anywhere in the app.

One question, three answers, from the one that can be used as it stands to the one that has to be asked again: the
team answers that mean the same (``teamanswers``), the people who know about the matter and so whom to ask
(``finder``), and the meetings the matter came up in. Nothing is stored and nobody is scored: it is this one
recommendation for this one question. The meetings are those the asker may read (``Libraries.access``), found by
words, the people only among twins open to colleagues, by what colleagues may use of them.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

import anyio
from fastapi import FastAPI, Query, Request

from ..embed import Embedder, EmbedError
from ..finder import Finder, TwinRef, asks_for_decision
from ..media.library import TEAM, Library, Recording
from ..persona.lexical import BM25, tokenize
from ..persona.store import stored_identity
from ..teamanswers import TeamAnswers
from .backends import Backends, BackendUnavailable
from .library import Libraries
from .personas import Personas

logger = logging.getLogger(__name__)

# What one question shows of each answer.
MEETINGS_SHOWN = 3
QUOTE_CHARS = 70
# Meeting lines this share of the question's words must be found in to be taken for about it; at least two.
MEETING_OVERLAP = 0.34
MEETING_CANDIDATES = 40
MIN_QUESTION_CHARS = 2
MAX_QUESTION_CHARS = 300


class MeetingSearch:
    """The lines of the team's recordings by words, for the recordings a viewer may read. The lines of every ready
    recording are kept in memory and the index over them made again only when a recording is added, changed or
    removed; who may read what is applied to the result."""

    def __init__(self, libraries: Libraries) -> None:
        self.libraries = libraries
        self._lock = threading.RLock()
        self._lines: dict[tuple[str, str], list[tuple[float, str, str]]] = {}
        self._mark: tuple[tuple[str, str], ...] = ()
        self._index: BM25 | None = None

    def _library(self) -> Library:
        return self.libraries.library(TEAM)

    def _read(self, library: Library, recording: Recording) -> list[tuple[float, str, str]]:
        key = (recording.id, recording.transcript_id or "")
        found = self._lines.get(key)
        if found is None:
            try:
                transcript = library.cleaned(recording)
            except (OSError, ValueError):
                logger.warning("could not read the transcript of %s", recording.id, exc_info=True)
                transcript = None
            found = [(s.start, s.speaker, s.text) for s in transcript.segments] if transcript else []
            self._lines[key] = found
        return found

    def _bm25(self, library: Library) -> BM25:
        recordings = [r for r in library.list() if r.status == "ready" and r.transcript_id]
        mark = tuple(sorted((r.id, r.transcript_id or "") for r in recordings))
        with self._lock:
            if self._index is not None and mark == self._mark:
                return self._index
            live = set(mark)
            for key in [k for k in self._lines if k not in live]:
                del self._lines[key]
            docs = {
                f"{r.id}\t{i}": text
                for r in recordings
                for i, (_, _, text) in enumerate(self._read(library, r))
                if text.strip()
            }
            self._index, self._mark = BM25(docs), mark
            return self._index

    def search(self, request: Request, question: str, limit: int = MEETINGS_SHOWN) -> list[dict[str, Any]]:
        libraries = self.libraries
        library = self._library()
        access = libraries.access(libraries.viewer(request))
        if not access:
            return []
        index = self._bm25(library)
        wanted = set(tokenize(question))
        if len(wanted) < 2:
            return []
        scores = index.scores(question)
        best: dict[str, tuple[float, int]] = {}
        for ref, score in sorted(scores.items(), key=lambda pair: -pair[1])[: MEETING_CANDIDATES * 10]:
            recording_id, at = ref.split("\t")
            if recording_id not in access or recording_id in best:
                continue
            with self._lock:
                recording = library.get(recording_id)
                lines = self._read(library, recording) if recording else []
            if not recording or int(at) >= len(lines):
                continue
            shared = len(wanted & set(tokenize(lines[int(at)][2])))
            if shared >= 2 and shared / len(wanted) >= MEETING_OVERLAP:
                best[recording_id] = (score, int(at))
            if len(best) >= limit:
                break
        if not best:
            return []
        people = {p.id: p.name for p in libraries.team(TEAM).people()}
        out: list[dict[str, Any]] = []
        for recording_id, (_, number) in best.items():
            recording = library.get(recording_id)
            if recording is None:
                continue
            with self._lock:
                start, speaker, text = self._read(library, recording)[number]
            named = next(
                (
                    people.get(view.person_id or "")
                    for view in libraries.team(TEAM).speakers(recording)
                    if view.id == speaker and view.decision == "confirmed"
                ),
                None,
            )
            out.append(
                {
                    "recording_id": recording.id,
                    "title": recording.filename.rsplit(".", 1)[0],
                    "date": (recording.creation_time or recording.created_at)[:10],
                    "speaker": named or "",
                    "quote": " ".join(text.split())[:QUOTE_CHARS],
                    "start": round(start, 1),
                    # Which line of the transcript, as the recording's page lists them, to open it on.
                    "line": number,
                }
            )
        return out


def register(
    app: FastAPI,
    registry: Personas,
    finder: Finder,
    answers: TeamAnswers,
    backends: Backends,
    libraries: Libraries,
) -> MeetingSearch:
    meetings = MeetingSearch(libraries)

    def open_twins() -> list[TwinRef]:
        """The twins that exist and are open to colleagues' questions, as the finder is given them."""
        found: list[TwinRef] = []
        with registry.lock:
            entries = [dict(e) for e in registry.data["personas"] if not e.get("deleted_at")]
            gone = set(registry.removing)
        for entry in entries:
            if entry["id"] in gone or not entry.get("public") or not entry.get("member"):
                continue
            path = registry.db_path_of(entry["id"])
            if path.is_file():
                found.append(
                    TwinRef(
                        entry["id"],
                        stored_identity(path)[0] or "本人",
                        path,
                        entry.get("member"),
                        bool(entry.get("public")),
                    )
                )
        return found

    def ask(request: Request, question: str) -> dict[str, Any]:
        identity = request.scope["twin_identity"]
        asker = identity["email"]
        result: dict[str, Any] = {
            "team_answers": [],
            "people": [],
            "meetings": meetings.search(request, question),
            "decision": asks_for_decision(question),
            "degraded": False,
        }
        try:
            embedder: Embedder = backends.embedder()
            result["team_answers"] = answers.cards_for(question, embedder, asker=asker)
            result["people"] = finder.recommend(question, embedder, open_twins(), asker)
        except (BackendUnavailable, EmbedError):
            # Meetings are found by words; the rest needs the embedding model.
            result["degraded"] = True
        return result

    @app.get("/api/personas/ask")
    async def ask_route(
        request: Request, q: str = Query(min_length=MIN_QUESTION_CHARS, max_length=MAX_QUESTION_CHARS)
    ) -> dict[str, Any]:
        # Reads other twins' databases and the recordings' transcripts: off the event loop.
        return await anyio.to_thread.run_sync(ask, request, q.strip())

    return meetings
