"""Merging the recording libraries earlier versions kept per account into the team's library, once.

Each old library (``data/library/<owner_key>/``) is folded in, the one with the earliest recording first, then set
aside under ``data/library/.legacy/`` untouched, so going back to an earlier version only needs it moved back. What
merges:

- recordings, by content: a meeting two colleagues both uploaded stays the first upload's, with that library's
  decisions about its speakers; each recording remembers whose library it came from as its ``uploader``, so its
  uploader still decides about it. Their files are hard-linked (copied across file systems).
- people, never by name alone: two people with one name are one only when ``same`` says so (their twins were made
  for the same work e-mail); otherwise the newcomer is called "张三（2）" and the pair is left for an administrator
  to merge or keep apart (``Team.similar``). Unnamed voices are numbered afresh.
- decisions, voice samples, model spending, and the twins made from each library, whose wanted version is raised so
  they stay closed until rebuilt from the team's library (relinking them is ``web.library``'s, which knows them).
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

from ..util import prepare_private_file, private_directory
from . import attribution
from .library import TEAM, Library
from .team import UNNAMED, Team

logger = logging.getLogger(__name__)

LEGACY = ".legacy"
# Whether two people of these rows are one: given the old row and the team's row of the same name.
Same = Callable[[sqlite3.Row, sqlite3.Row], bool]


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


def legacy(root: Path) -> list[Path]:
    """The old libraries under ``root`` still to merge, the one with the earliest recording first."""
    found = []
    for folder in root.iterdir() if root.is_dir() else ():
        if folder.name == TEAM or folder.name.startswith(".") or not (folder / "library.db").is_file():
            continue
        with closing(sqlite3.connect(f"{(folder / 'library.db').resolve().as_uri()}?mode=ro", uri=True)) as db:
            try:
                first = db.execute("SELECT MIN(created_at) FROM recordings").fetchone()[0]
            except sqlite3.Error:
                first = None
        found.append((first or "~", folder.name, folder))
    return [folder for _, _, folder in sorted(found)]


def merge_all(root: Path, same: Same) -> list[str]:
    """Merge every old library under ``root`` into the team's; returns the twins whose library changed."""
    twins: list[str] = []
    for folder in legacy(root):
        team = Library(root / TEAM)
        twins += merge(team, folder, same)
        aside = root / LEGACY / folder.name
        private_directory(aside.parent)
        if aside.exists():
            aside = aside.with_name(f"{folder.name}-{dt.datetime.now(dt.UTC):%Y%m%dT%H%M%S%f}")
        folder.rename(aside)
        logger.info("merged recording library %s into the team's library (kept in %s)", folder.name, aside)
    return twins


def merge(team: Library, folder: Path, same: Same) -> list[str]:
    """Fold the old library at ``folder`` into ``team`` in one transaction; returns its twins."""
    old = Library(folder)  # Brings an old schema up to date, so every column below exists.
    with old.read() as source, team.transaction() as db:
        if db.execute("SELECT 1 FROM merged_libraries WHERE key = ?", (folder.name,)).fetchone():
            return []
        taken = {row["sha256"] for row in db.execute("SELECT sha256 FROM recordings")}
        moved = []
        for row in source.execute("SELECT * FROM recordings ORDER BY created_at"):
            if row["sha256"] in taken:
                continue
            values = {**dict(row), "uploader": row["uploader"] or folder.name}
            db.execute(
                f"INSERT INTO recordings ({', '.join(values)}) VALUES ({', '.join('?' * len(values))})",
                tuple(values.values()),
            )
            moved.append(row["id"])
            _link_tree(old.folder(row["id"]), team.folder(row["id"]))
        people = _people(source, db, same)
        for recording_id in moved:
            for row in source.execute("SELECT * FROM attributions WHERE recording_id = ?", (recording_id,)):
                rejected = [people[p] for p in json.loads(row["rejected"]) if p in people]
                db.execute(
                    "INSERT OR REPLACE INTO attributions (recording_id, transcript_id, speaker_id, decision, "
                    "person_id, rejected, updated_at, auto, disputed) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        row["recording_id"],
                        row["transcript_id"],
                        row["speaker_id"],
                        row["decision"],
                        people.get(row["person_id"]) if row["person_id"] else None,
                        json.dumps(sorted(set(rejected))),
                        row["updated_at"],
                        row["auto"],
                        row["disputed"],
                    ),
                )
            for row in source.execute("SELECT * FROM voiceprints WHERE recording_id = ?", (recording_id,)):
                if row["person_id"] in people:
                    db.execute(
                        "INSERT INTO voiceprints (person_id, recording_id, transcript_id, speaker_id, embedding, "
                        "active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            people[row["person_id"]],
                            row["recording_id"],
                            row["transcript_id"],
                            row["speaker_id"],
                            row["embedding"],
                            row["active"],
                            row["created_at"],
                        ),
                    )
        twins = []
        for row in source.execute("SELECT * FROM personas_sync"):
            if row["person_id"] not in people:
                continue
            person_id = people[row["person_id"]]
            # Raised past what was built: the twin stays closed until rebuilt from the team's library.
            db.execute(
                "INSERT OR REPLACE INTO personas_sync (persona_id, person_id, wanted, done) VALUES (?, ?, ?, ?)",
                (row["persona_id"], person_id, max(row["wanted"], row["done"]) + 1, row["done"]),
            )
            db.execute(
                "UPDATE people SET persona_id = ? WHERE id = ? AND persona_id IS NULL", (row["persona_id"], person_id)
            )
            twins.append(str(row["persona_id"]))
        # Everyone who speaks with someone whose recordings just arrived is rebuilt too.
        attribution.bump_twins(db, set(people.values()))
        for row in source.execute("SELECT at, kind, tokens FROM spending"):
            db.execute("INSERT INTO spending (at, kind, tokens) VALUES (?, ?, ?)", tuple(row))
        db.execute("INSERT INTO merged_libraries (key, merged_at) VALUES (?, ?)", (folder.name, _now()))
    return twins


def _people(source: sqlite3.Connection, db: sqlite3.Connection, same: Same) -> dict[str, str]:
    """Bring the old library's people over; returns old id → team id."""
    found: dict[str, str] = {}
    for row in source.execute("SELECT * FROM people ORDER BY created_at"):
        if db.execute("SELECT 1 FROM people WHERE id = ?", (row["id"],)).fetchone():
            # Person ids are random: the same id is the same person merged before (a merge cut off midway).
            found[row["id"]] = row["id"]
            continue
        namesake = db.execute("SELECT * FROM people WHERE name = ?", (row["name"],)).fetchone()
        name = row["name"]
        if namesake is not None and not row["auto"] and not namesake["auto"] and same(row, namesake):
            found[row["id"]] = namesake["id"]
            for column in ("gender", "account"):
                if row[column] and not namesake[column]:
                    db.execute(f"UPDATE people SET {column} = ? WHERE id = ?", (row[column], namesake["id"]))
            continue
        if row["auto"]:
            name = Team._unnamed(db) if namesake is not None or name.startswith(UNNAMED) else name
        elif namesake is not None:
            n = 2
            while db.execute("SELECT 1 FROM people WHERE name = ?", (f"{row['name']}（{n}）",)).fetchone():
                n += 1
            name = f"{row['name']}（{n}）"
        db.execute(
            "INSERT INTO people (id, name, persona_id, created_at, auto, gender, account) "
            "VALUES (?, ?, NULL, ?, ?, ?, ?)",
            (row["id"], name, row["created_at"], row["auto"], row["gender"], row["account"]),
        )
        found[row["id"]] = row["id"]
        if namesake is not None and not row["auto"] and not namesake["auto"]:
            db.execute(
                "INSERT OR IGNORE INTO similar_people (person_id, other_id, created_at) VALUES (?, ?, ?)",
                (namesake["id"], row["id"], _now()),
            )
    return found


def _link_tree(source: Path, target: Path) -> None:
    """Hard-link a recording's files (they never change once written); copy across file systems."""
    if not source.is_dir():
        return
    private_directory(target)
    target.chmod(0o700)
    for path in source.iterdir():
        destination = target / path.name
        if path.is_symlink() or path.name == "media-cache" or destination.exists():
            continue
        if path.is_dir():
            _link_tree(path, destination)
        elif path.is_file():
            try:
                os.link(path, destination)
            except OSError:
                prepare_private_file(destination)
                shutil.copyfile(path, destination)
                destination.chmod(0o600)
