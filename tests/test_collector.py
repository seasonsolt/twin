"""Collector versions (``media.collector``): which layer a recording must be collected again by, and what an
attribution or review rule change does to what the voice decided under older rules."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest
from test_library import needs_ffmpeg, wav_bytes
from test_review import VOICES, Voices, library_with_mixed_speaker
from test_team import decide, voices, wanted_done

from twin.media import review as review_module
from twin.media import team as team_module
from twin.media.collector import CollectorVersion, asr_version, recollect_scope
from twin.media.ingest import CommandTranscriber
from twin.media.library import Library
from twin.media.review import Reviews
from twin.media.team import Team


def test_the_deepest_changed_layer_is_collected_again() -> None:
    now = CollectorVersion(asr="1.4.1/overlap", attribution="attribution-v2", cleanup="cleanup-v1")
    assert recollect_scope(now, now) == "none"
    assert recollect_scope(CollectorVersion("1.4.1/overlap", "attribution-v2", "cleanup-v0"), now) == "cleanup"
    assert recollect_scope(CollectorVersion("1.4.1/overlap", "attribution-v1", "cleanup-v0"), now) == "attribution"
    # Another service, or one that did not say which it was, transcribes again.
    assert recollect_scope(CollectorVersion("1.4.1/classic", "attribution-v2", "cleanup-v1"), now) == "asr"
    assert recollect_scope(CollectorVersion(None, "attribution-v2", "cleanup-v1"), now) == "asr"
    # With the current service unknown, nothing says a transcript is stale.
    assert recollect_scope(now, CollectorVersion(None, "attribution-v2", "cleanup-v1")) == "none"
    assert asr_version("1.4.1", "overlap") == "1.4.1/overlap" and asr_version("1.4.1", None) == "1.4.1"
    assert asr_version(None, "overlap") is None and asr_version(" ", "classic") is None


def service(tmp_path: Path, reply: dict[str, object]) -> CommandTranscriber:
    """A transcription command answering ``reply`` to any request."""
    script = tmp_path / "service.py"
    script.write_text(f"import sys\nsys.stdin.read()\nprint({json.dumps(json.dumps(reply))})\n")
    return CommandTranscriber(f"python3 {script}")


SEGMENTS = [{"start": 0, "end": 1, "text": "先看预算。", "speaker": "S1"}]
SPEAKERS = [{"id": "S1", "seconds": 1, "embedding": [1.0, 0.0]}]


@needs_ffmpeg
def test_each_transcript_records_the_service_that_made_it(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    recordings = []
    for k, reply in enumerate(
        [
            {"ok": True, "segments": SEGMENTS, "speakers": SPEAKERS},  # Before services said which they are.
            {"ok": True, "segments": SEGMENTS, "speakers": SPEAKERS, "version": "1.4.1", "pipeline": "classic"},
        ]
    ):
        part = tmp_path / f"upload-{k}.part"
        part.write_bytes(wav_bytes(tone=k))
        recording, _ = library.add(part, f"会议{k}.wav")
        library.transcribe(recording.id, service(tmp_path, reply), lambda done, total: None)
        recordings.append(library.get(recording.id))
    old, new = recordings
    assert old is not None and new is not None and (old.asr, new.asr) == (None, "1.4.1/classic")
    assert library.transcript(new).asr == "1.4.1/classic"  # type: ignore[union-attr]
    assert library.collector().asr == "1.4.1/classic"
    # Only the transcript of an unknown service is one the current service would make anew.
    assert [r.id for r in library.recollectable()] == [old.id]

    # A service moved to the GPU pipeline: both could be transcribed again, oldest first.
    part = tmp_path / "upload-2.part"
    part.write_bytes(wav_bytes(tone=2))
    third, _ = library.add(part, "会议2.wav")
    reply = {"ok": True, "segments": SEGMENTS, "speakers": SPEAKERS, "version": "1.4.1", "pipeline": "overlap"}
    library.transcribe(third.id, service(tmp_path, reply), lambda done, total: None)
    assert [r.id for r in library.recollectable()] == [old.id, new.id]


def test_a_library_from_before_versions_opens_with_its_decisions_as_they_were(tmp_path: Path) -> None:
    root = tmp_path / "library" / "team"
    library = Library(root)
    first = voices(library, "一.m4a", ([1.0, 0.0], 120), ([0.0, 1.0], 90))
    assert Team(library).classify(first) == 2
    # As an older twin left it: no version columns, nor the collector table.
    with sqlite3.connect(library.db_path) as db:
        for table, column in (("recordings", "asr"), ("attributions", "version"), ("segment_fixes", "version")):
            db.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        db.execute("DROP TABLE collector")
    reopened = Library(root)
    with reopened.read() as db:
        rows = db.execute("SELECT auto, version FROM attributions ORDER BY speaker_id").fetchall()
    assert [tuple(row) for row in rows] == [(1, None), (1, None)]
    # Decided by the first rules, the rules still in force: nothing is decided again, and nothing to transcribe.
    assert Team(reopened).classify_all() == 0
    assert reopened.collector().asr is None and reopened.recollectable() == ()


def test_new_attribution_rules_decide_again_only_what_the_voice_decided(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = voices(library, "一.m4a", ([1.0, 0.0, 0.0], 120), ([0.0, 1.0, 0.0], 90))
    zhang, li = team.add_person("张总"), team.add_person("李总")
    decide(team, first, "S1", "confirm", zhang.id, sample=True)
    decide(team, first, "S2", "confirm", li.id, sample=True)
    second = voices(library, "二.m4a", ([0.9, 0.3, 0.0], 100), ([0.0, 1.0, 0.0], 70), ([0.6, 0.2, 0.7], 30))
    decide(team, second, "S3", "confirm", li.id)  # The owner's, against the voice.
    assert team.classify(second) == 2
    team.link(zhang.id, "p-zhang")
    team.link(li.id, "p-li")
    zhang_wanted, li_wanted = wanted_done(library, "p-zhang")[0], wanted_done(library, "p-li")[0]

    def rows() -> dict[str, tuple[str | None, int, str | None]]:
        with library.read() as db:
            found = db.execute(
                "SELECT speaker_id, person_id, auto, version FROM attributions WHERE recording_id = ?", (second,)
            ).fetchall()
        return {row[0]: (row[1], row[2], row[3]) for row in found}

    assert rows() == {"S1": (zhang.id, 1, "attribution-v2"), "S2": (li.id, 1, "attribution-v2"), "S3": (li.id, 0, None)}

    # New rules that decide these speakers the same way: only the versions change, and no twin closes.
    monkeypatch.setattr(team_module, "ATTRIBUTION_VERSION", "attribution-v3")
    assert team.classify_all() == 0
    assert rows() == {"S1": (zhang.id, 1, "attribution-v3"), "S2": (li.id, 1, "attribution-v3"), "S3": (li.id, 0, None)}
    assert (wanted_done(library, "p-zhang")[0], wanted_done(library, "p-li")[0]) == (zhang_wanted, li_wanted)

    # Stricter rules: 张总's speaker is no longer sure enough, and goes back to the owner; 李总's stays.
    monkeypatch.setattr(team_module, "ATTRIBUTION_VERSION", "attribution-v4")
    monkeypatch.setattr(team_module, "AUTO", 0.99)
    assert team.classify(second) == 1
    assert rows() == {"S2": (li.id, 1, "attribution-v4"), "S3": (li.id, 0, None)}
    assert wanted_done(library, "p-zhang")[0] == zhang_wanted + 1
    assert wanted_done(library, "p-li")[0] == li_wanted + 1  # They speak in the recording, whose sources changed.
    assert team.classify(second) == 0


def test_new_review_rules_judge_again_only_the_stretches_the_review_left_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, team, _, mixed, zhang, _ = library_with_mixed_speaker(tmp_path)
    team.link(zhang, "p-zhang")
    reviews = Reviews(library)
    reviews.run(mixed, Voices(VOICES))

    def fixes() -> dict[int, tuple[int, str | None]]:
        with library.read() as db:
            found = db.execute("SELECT segment, auto, version FROM segment_fixes WHERE recording_id = ?", (mixed,))
            return {row[0]: (row[1], row[2]) for row in found.fetchall()}

    assert fixes() == {2: (1, "cleanup-v1"), 3: (1, "cleanup-v1")}
    before = wanted_done(library, "p-zhang")[0]
    monkeypatch.setattr(review_module, "CLEANUP_VERSION", "cleanup-v2")
    assert reviews.refresh() == 0 and reviews.settle() == 0
    assert fixes() == {2: (1, "cleanup-v2"), 3: (1, "cleanup-v2")}
    assert wanted_done(library, "p-zhang")[0] == before

    # Rules that no longer take a stranger's stretch out: it goes back to 张总, and the other one stays out.
    monkeypatch.setattr(review_module, "CLEANUP_VERSION", "cleanup-v3")
    monkeypatch.setattr(review_module, "STRANGER", 0.0)
    assert reviews.refresh() == 1 and reviews.settle() == 0
    assert fixes() == {2: (1, "cleanup-v3")}
    assert wanted_done(library, "p-zhang")[0] == before + 1
    (source,) = [s for s in team.sources(zhang, "张总") if s.title == "2026-03-02 周会"]
    assert [i for i, line in enumerate(source.lines) if line[2]] == [0, 3]
