"""Minutes someone wrote, brought into the team's library (``media.minutes``, docs/PLAN_MEETING_MINUTES.md).

One file is put on one recording from that recording's menu. Many files dropped on the library are read for their
days, a file holding several meetings is cut at the headings of their days, and each meeting is matched to a recording
(``minutes.match_recording``). Nothing is put on a recording until whoever brought the files in says so: until then
each waits (``minutes_pending``) with the recording it seems to be of, and the library shows how many wait. Minutes put
on a recording are cut into points in the background, like the model's own (``Libraries.run_written``).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Annotated, Any

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..media.library import TEAM, PendingMinutes, Recording, WrittenDocument
from ..media.minutes import Candidate, match_recording, meeting_day, recording_clock, written_parts
from ..persona.sources import parse_turns
from ..persona.text import extract_text
from .library import MAX_TRANSCRIPT_BYTES, Libraries, Viewer

# How a recording was found for minutes without anyone choosing it.
MATCHED = frozenset({"当天唯一", "时刻相近", "内容最像"})
# A file chosen as minutes for one recording, and how that recording was found.
CHOSEN = "人选"
ADDED = "单场添加"
# Recordings offered for minutes waiting to be put on one: those of the nearest days.
CHOICES = 8


class AttachItem(BaseModel):
    id: str
    recording_id: str


class AttachBody(BaseModel):
    items: list[AttachItem] = Field(default_factory=list, max_length=1000)


def _file_name(file: UploadFile) -> str:
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not name or name.startswith("."):
        raise HTTPException(400, "文件名无效")
    return name


async def _read(file: UploadFile) -> tuple[str, bytes]:
    name = _file_name(file)
    data = await file.read(MAX_TRANSCRIPT_BYTES + 1)
    if len(data) > MAX_TRANSCRIPT_BYTES:
        raise HTTPException(413, f"「{name}」太大，请选择 20 MB 以内的文件")
    return name, data


def _text(name: str, data: bytes) -> str:
    try:
        text = extract_text(name, data).strip()
    except ValueError as e:
        raise HTTPException(400, f"「{name}」读不出文字：{e}") from None
    if not text:
        raise HTTPException(400, f"「{name}」是空的")
    return text


def _editable(libraries: Libraries, viewer: Viewer) -> list[Recording]:
    """The transcribed recordings the viewer decides about, which minutes can be put on."""
    library = libraries.library(TEAM)
    access = libraries.access(viewer)
    return [
        r
        for r in library.list()
        if r.status == "ready" and r.transcript_id is not None and r.id in access and access[r.id].edit
    ]


def _day(recording: Recording) -> dt.date | None:
    return meeting_day(recording.creation_time, recording.filename)


def _brief(recording: Recording) -> dict[str, Any]:
    day = _day(recording)
    return {"id": recording.id, "filename": recording.filename, "day": day.isoformat() if day else None}


def pending_view(libraries: Libraries, viewer: Viewer) -> list[dict[str, Any]]:
    """The viewer's minutes waiting for a recording (everyone's, for an administrator), each with the recording it
    seems to be of and the recordings of the nearest days to choose from."""
    library = libraries.library(TEAM)
    waiting = library.pending_minutes(None if viewer.admin else viewer.key)
    if not waiting:
        return []
    recordings = _editable(libraries, viewer)
    by_id = {r.id: r for r in recordings}
    newest = sorted(recordings, key=lambda r: (_day(r) or dt.date.min, r.created_at), reverse=True)

    def choices(item: PendingMinutes) -> list[dict[str, Any]]:
        if item.day is None:
            near = newest
        else:
            day = dt.date.fromisoformat(item.day)
            near = sorted(newest, key=lambda r: abs(((_day(r) or dt.date.min) - day).days))
        picked = near[:CHOICES]
        if item.proposal in by_id and by_id[item.proposal] not in picked:
            picked = [by_id[item.proposal], *picked[: CHOICES - 1]]
        return [_brief(r) for r in picked]

    return [
        {
            "id": item.id,
            "filename": item.filename,
            "title": item.title,
            "part": item.part,
            "parts": item.parts,
            "day": item.day,
            "how": item.how,
            "matched": item.how in MATCHED and item.proposal in by_id,
            "proposal": _brief(by_id[item.proposal]) if item.proposal in by_id else None,
            "choices": choices(item),
        }
        for item in waiting
    ]


def read_files(libraries: Libraries, viewer: Viewer, files: list[tuple[str, bytes]]) -> dict[str, Any]:
    """Read written minutes for the meetings they hold and the recordings those seem to be of, each kept waiting for
    the viewer to say. A file that is a transcript (speakers taking turns) is named back, to be brought in as one;
    minutes brought in before are skipped."""
    library = libraries.library(TEAM)
    known = library.written_documents()
    kinds = library.minutes_kinds()
    recordings = _editable(libraries, viewer)
    transcripts: list[str] = []
    unreadable: list[str] = []
    found: list[tuple[WrittenDocument, Any]] = []
    skipped = 0
    for name, data in files:
        try:
            parse_turns(name, data)
        except ValueError:
            pass
        else:
            transcripts.append(name)
            continue
        try:
            text = _text(name, data)
        except HTTPException as e:
            unreadable.append(str(e.detail))
            continue
        sha = hashlib.sha256(data).hexdigest()
        parts = written_parts(name, text)
        for part in parts:
            document = WrittenDocument(filename=name, sha256=sha, part=part.part, parts=part.parts)
            if (sha, part.part) in known:
                skipped += 1
                continue
            known.add((sha, part.part))
            found.append((document, part))
    # What a recording says is read only where its day has other recordings that minutes of that day could be of.
    days: dict[dt.date | None, list[Recording]] = {}
    for recording in recordings:
        days.setdefault(_day(recording), []).append(recording)
    wanted = {part.day for _, part in found}
    candidates = []
    for day, same in days.items():
        for recording in same:
            text = ""
            if day in wanted and len(same) > 1:
                transcript = library.cleaned(recording)
                text = " ".join(s.text for s in transcript.segments) if transcript else ""
            candidates.append(
                Candidate(
                    recording.id,
                    day,
                    recording_clock(recording.creation_time, recording.filename),
                    text,
                    kinds.get(recording.id) == "human",
                )
            )
    for document, part in found:
        library.add_pending(viewer.key, document, part, match_recording(part, candidates))
    return {
        "transcripts": transcripts,
        "unreadable": unreadable,
        "skipped": skipped,
        "added": len(found),
        "pending": pending_view(libraries, viewer),
    }


def attach(libraries: Libraries, viewer: Viewer, body: AttachBody) -> dict[str, Any]:
    """Put the waiting minutes on the recordings chosen for them; the rest keep waiting."""
    library = libraries.library(TEAM)
    waiting = {item.id: item for item in library.pending_minutes(None if viewer.admin else viewer.key)}
    visible = libraries.access(viewer)
    for choice in body.items:
        if choice.id not in waiting:
            raise HTTPException(404, "这份纪要已经处理过了，请刷新")
        libraries.allowed(viewer, choice.recording_id, edit=True, visible=visible)
    attached = 0
    for choice in body.items:
        item = waiting[choice.id]
        how = item.how if choice.recording_id == item.proposal and item.how in MATCHED else CHOSEN
        library.put_written(choice.recording_id, item.document, item.body, how)
        library.drop_pending(item.id)
        attached += 1
    libraries.proofread(TEAM)
    return {"attached": attached, "pending": pending_view(libraries, viewer)}


def register(app: FastAPI, libraries: Libraries) -> None:
    @app.get("/api/library/minutes/pending")
    def get_pending(request: Request) -> dict[str, Any]:
        return {"items": pending_view(libraries, libraries.viewer(request))}

    @app.post("/api/library/minutes/read")
    async def read_minutes(request: Request, files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
        """Read written minutes for the recordings they are of; nothing is put on a recording yet."""
        read = [await _read(file) for file in files]
        return await run_in_threadpool(read_files, libraries, libraries.viewer(request), read)

    @app.post("/api/library/minutes/attach")
    def attach_minutes(request: Request, body: AttachBody) -> dict[str, Any]:
        return attach(libraries, libraries.viewer(request), body)

    @app.delete("/api/library/minutes/pending/{pending_id}")
    def drop_pending(pending_id: str, request: Request) -> dict[str, Any]:
        viewer = libraries.viewer(request)
        library = libraries.library(TEAM)
        if pending_id not in {item.id for item in library.pending_minutes(None if viewer.admin else viewer.key)}:
            raise HTTPException(404, "这份纪要已经处理过了，请刷新")
        library.drop_pending(pending_id)
        return {"items": pending_view(libraries, viewer)}

    @app.post("/api/library/recordings/{recording_id}/minutes")
    async def add_minutes(recording_id: str, request: Request, file: Annotated[UploadFile, File()]) -> dict[str, Any]:
        """Put one file of written minutes on the recording, in place of any it had."""
        viewer = libraries.viewer(request)
        libraries.allowed(viewer, recording_id, edit=True)
        name, data = await _read(file)
        text = await run_in_threadpool(_text, name, data)
        library = libraries.library(TEAM)
        document = WrittenDocument(filename=name, sha256=hashlib.sha256(data).hexdigest())
        library.put_written(recording_id, document, text, ADDED)
        libraries.proofread(TEAM)
        return {"recording_id": recording_id, "minutes": "human"}

    @app.delete("/api/library/recordings/{recording_id}/minutes")
    def remove_minutes(recording_id: str, request: Request) -> dict[str, Any]:
        """Take the written minutes off the recording; the model's own stay."""
        viewer = libraries.viewer(request)
        libraries.allowed(viewer, recording_id, edit=True)
        libraries.library(TEAM).remove_written(recording_id)
        return {"recording_id": recording_id}
