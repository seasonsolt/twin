"""Interrupted upload finalization recovers without filing or exposing another copy of a recording."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from twin.config import Settings
from twin.web.library import Libraries, Viewer
from twin.web.uploads import UploadBody, Uploads


def completed(libraries: Libraries, viewer: Viewer, data: bytes = b"synthetic recording bytes") -> str:
    uploads = libraries.uploads(viewer)
    created = uploads.create(UploadBody(filename="meeting.wav", size=len(data)))
    uploads.append(created["id"], data, 0)
    return str(created["id"])


def test_finish_recovers_after_recording_commit_but_metadata_save_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    libraries = Libraries(settings, MagicMock())
    monkeypatch.setattr(libraries, "kick", lambda _: None)
    viewer = Viewer("uploader", "uploader@example.com", False)
    upload_id = completed(libraries, viewer)
    save = Uploads.save
    failed = False

    def save_once(self: Uploads, key: str, info: dict[str, Any]) -> None:
        nonlocal failed
        if info.get("recording_id") and not failed:
            failed = True
            raise OSError("synthetic final metadata failure")
        save(self, key, info)

    monkeypatch.setattr(Uploads, "save", save_once)
    with pytest.raises(OSError, match="synthetic final"):
        libraries.finish(viewer, upload_id)
    [recording] = libraries.library("team").list()
    assert not libraries.uploads(viewer).paths(upload_id)[1].exists()
    # A fresh coordinator has no in-memory upload hash or job map to rely on.
    restarted = Libraries(settings, MagicMock())
    monkeypatch.setattr(restarted, "kick", lambda _: None)
    result = restarted.finish(viewer, upload_id)
    assert result["id"] == recording.id and result["mine"] is True and result["new"] is False
    assert len(restarted.library("team").list()) == 1
    assert restarted.uploads(viewer).load(upload_id)["offset"] == recording.size


def test_finish_recovers_original_moved_before_recording_insert_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    settings = Settings(db_path=tmp_path / "twin.db")
    libraries = Libraries(settings, MagicMock())
    monkeypatch.setattr(libraries, "kick", lambda _: None)
    viewer = Viewer("uploader", "uploader@example.com", False)
    upload_id = completed(libraries, viewer)
    uploads, library = libraries.uploads(viewer), libraries.library("team")
    _, part = uploads.paths(upload_id)
    connect = library._db
    failed = False

    @contextmanager
    def interrupted() -> Any:
        nonlocal failed
        if not part.exists() and not failed:
            failed = True
            raise OSError("synthetic stop before insert")
        with connect() as db:
            yield db

    with monkeypatch.context() as local:
        local.setattr(library, "_db", interrupted)
        with pytest.raises(OSError, match="synthetic stop"):
            libraries.finish(viewer, upload_id)
    assert library.list() == []
    assert not part.exists() and uploads.load(upload_id)["offset"] == uploads.load(upload_id)["size"]
    restarted = Libraries(settings, MagicMock())
    monkeypatch.setattr(restarted, "kick", lambda _: None)
    result = restarted.finish(viewer, upload_id)
    assert result["new"] is True and result["mine"] is True
    assert len(restarted.library("team").list()) == 1
    assert restarted.finish(viewer, upload_id)["id"] == result["id"]


def test_finished_upload_retries_do_not_submit_more_jobs_and_cancel_does_not_recover_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    libraries = Libraries(Settings(db_path=tmp_path / "twin.db"), MagicMock())
    kick = MagicMock()
    monkeypatch.setattr(libraries, "kick", kick)
    owner = Viewer("uploader", "uploader@example.com", False)
    stranger = Viewer("other", "other@example.com", False)
    upload_id = completed(libraries, owner)
    first = libraries.finish(owner, upload_id)
    assert libraries.finish(owner, upload_id)["id"] == first["id"]
    kick.assert_called_once()
    with pytest.raises(HTTPException) as denied:
        libraries.finish(stranger, upload_id)
    assert denied.value.status_code == 404
    libraries.uploads(owner).cancel(upload_id)
    with pytest.raises(HTTPException) as cancelled:
        libraries.finish(owner, upload_id)
    assert cancelled.value.status_code == 404
    assert len(libraries.library("team").list()) == 1


def test_duplicate_upload_recovery_preserves_the_existing_recordings_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    libraries = Libraries(Settings(db_path=tmp_path / "twin.db"), MagicMock())
    monkeypatch.setattr(libraries, "kick", lambda _: None)
    owner = Viewer("uploader", "uploader@example.com", False)
    other = Viewer("other", "other@example.com", False)
    first = libraries.finish(owner, completed(libraries, owner))
    duplicate = completed(libraries, other)
    save = Uploads.save
    failed = False

    def save_once(self: Uploads, key: str, info: dict[str, Any]) -> None:
        nonlocal failed
        if info.get("recording_id") and not failed:
            failed = True
            raise OSError("synthetic duplicate finish response lost")
        save(self, key, info)

    monkeypatch.setattr(Uploads, "save", save_once)
    with pytest.raises(OSError, match="synthetic duplicate"):
        libraries.finish(other, duplicate)
    result = libraries.finish(other, duplicate)
    assert result == {"id": first["id"], "filename": "meeting.wav", "new": False, "mine": False}
    [recording] = libraries.library("team").list()
    assert recording.uploader == owner.key


def test_failed_upload_metadata_write_keeps_the_previous_json_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    uploads = Uploads(tmp_path)
    created = uploads.create(UploadBody(filename="meeting.wav", size=10))
    upload_id = created["id"]
    metadata, _ = uploads.paths(upload_id)
    original = metadata.read_text()
    write = Path.write_text

    def partial(path: Path, text: str, *args: Any, **kwargs: Any) -> int:
        if path.name.endswith(".tmp"):
            write(path, "{", *args, **kwargs)
            raise OSError("synthetic interrupted metadata write")
        return write(path, text, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", partial)
    with pytest.raises(OSError, match="synthetic interrupted"):
        uploads.save(upload_id, {**json.loads(original), "recording_id": "synthetic-recording"})
    assert metadata.read_text() == original
    assert uploads.load(upload_id)["offset"] == 0
    assert metadata.stat().st_mode & 0o777 == 0o600
    assert not list(uploads.root.glob(".*.tmp"))


def test_an_old_upload_without_bytes_or_a_recovery_hash_requires_reselection(tmp_path: Path) -> None:
    from fastapi import HTTPException

    uploads = Uploads(tmp_path)
    created = uploads.create(UploadBody(filename="meeting.wav", size=10))
    _, part = uploads.paths(created["id"])
    part.unlink()
    with pytest.raises(HTTPException) as lost:
        uploads.load(created["id"])
    assert lost.value.status_code == 404


def test_recovery_hash_cannot_resurrect_a_deleted_recording(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    libraries = Libraries(Settings(db_path=tmp_path / "twin.db"), MagicMock())
    monkeypatch.setattr(libraries, "kick", lambda _: None)
    owner = Viewer("uploader", "uploader@example.com", False)
    upload_id = completed(libraries, owner)
    result = libraries.finish(owner, upload_id)
    uploads = libraries.uploads(owner)
    metadata = uploads.load(upload_id)
    metadata.pop("recording_id")  # The crash window retained only the preparation hash.
    uploads.save(upload_id, metadata)
    assert libraries.library("team").delete(result["id"])
    with pytest.raises(HTTPException) as deleted:
        libraries.finish(owner, upload_id)
    assert deleted.value.status_code == 404
    assert libraries.library("team").list() == []


def test_filing_rejects_empty_and_late_chunks_after_original_was_moved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from contextlib import contextmanager

    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from twin.web.uploads import finished, upload_routes

    libraries = Libraries(Settings(db_path=tmp_path / "twin.db"), MagicMock())
    monkeypatch.setattr(libraries, "kick", lambda _: None)
    owner = Viewer("uploader", "uploader@example.com", False)
    data = b"the original recording must survive"
    upload_id = completed(libraries, owner, data)
    uploads, library = libraries.uploads(owner), libraries.library("team")
    _, part = uploads.paths(upload_id)
    connect = library._db

    @contextmanager
    def stop_before_insert() -> Any:
        if not part.exists():
            raise OSError("synthetic stop after move")
        with connect() as db:
            yield db

    with monkeypatch.context() as local:
        local.setattr(library, "_db", stop_before_insert)
        with pytest.raises(OSError, match="synthetic stop"):
            libraries.finish(owner, upload_id)
    info = uploads.load(upload_id)
    assert info.get("filing_sha256") and not finished(info)
    original = library.original("rec_" + info["filing_sha256"][:20])
    assert original is not None and original.read_bytes() == data
    assert not part.exists() and library.list() == []
    app = FastAPI()
    upload_routes(
        app,
        "/uploads",
        lambda request: libraries.uploads(owner),
        lambda request, key: libraries.finish(owner, key),
    )
    with TestClient(app) as client:
        # The empty chunk at the end must not recreate .part in append mode. A late old chunk stays a normal
        # offset conflict, and neither one turns a pending finalization into a successful upload.
        for offset, chunk in ((len(data), b""), (0, data)):
            response = client.put(f"/uploads/{upload_id}?offset={offset}", content=chunk)
            assert response.status_code == 409 and response.json() == {"offset": len(data)}
            assert not part.exists() and original.read_bytes() == data
        result = client.post(f"/uploads/{upload_id}/finish")
        assert result.status_code == 200 and result.json()["size"] == len(data)
    assert library.list()[0].size == len(data)


def test_finish_refuses_a_damaged_part_instead_of_overwriting_the_moved_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    libraries = Libraries(Settings(db_path=tmp_path / "twin.db"), MagicMock())
    monkeypatch.setattr(libraries, "kick", lambda _: None)
    owner = Viewer("uploader", "uploader@example.com", False)
    data = b"complete original recording"
    upload_id = completed(libraries, owner, data)
    uploads, library = libraries.uploads(owner), libraries.library("team")
    info = uploads.load(upload_id)
    info["filing_sha256"] = uploads.digest(upload_id)
    uploads.save(upload_id, info)
    _, part = uploads.paths(upload_id)
    original = library.folder("rec_" + info["filing_sha256"][:20]) / "original.wav"
    original.parent.mkdir(parents=True)
    part.replace(original)
    part.touch(mode=0o600)  # A stray empty .part from the old append-at-complete bug.
    with pytest.raises(HTTPException) as damaged:
        libraries.finish(owner, upload_id)
    assert damaged.value.status_code == 409
    assert original.read_bytes() == data and library.list() == []
    part.unlink()
    result = libraries.finish(owner, upload_id)
    assert result["size"] == len(data) and library.list()[0].size == len(data)
