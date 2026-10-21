"""Transcribing a recording again with a newer service (``media.recollect``): people's decisions follow the speech
they were about, what cannot follow is reported, and the recording can go back to its old transcript."""

from __future__ import annotations

import wave
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from test_team import HEADERS, decide, recording, revision, until, wanted_done

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media import recollect
from twin.media.ingest import CommandTranscriber, Interrupted, Progress, Segment, Speaker
from twin.media.library import Library, TranscriptionError, TranscriptionInterrupted
from twin.media.team import Team
from twin.web import create_app


def segment(start: float, end: float, speaker: str) -> Segment:
    return Segment(start=start, end=end, text=f"{speaker} 在 {start:g} 秒说话。", speaker=speaker)


OLD = [
    segment(0, 10, "S1"),  # 张总
    segment(10, 20, "S2"),  # 李总
    segment(20, 30, "S1"),  # 张总, left out of 张总's twin by the owner
    segment(30, 40, "S3"),  # Nobody the owner knows
    segment(40, 50, "S4"),  # Undecided
    segment(50, 55, "S1"),  # 张总, left out by the owner
]
NEW = [
    segment(0, 5, "N1"),
    segment(5, 10, "N2"),  # N2 now holds some of 张总 and some of 李总, and the end of the meeting.
    segment(10, 15, "N2"),
    segment(15, 20, "N3"),  # Half of 李总's old speaker.
    segment(20, 25, "N1"),
    segment(25, 30, "N1"),
    segment(30, 40, "N4"),
    segment(40, 50, "N5"),
    segment(50, 55, "N2"),
]


class Newer(CommandTranscriber):
    """A newer service: other speaker numbers, another split of the same speech."""

    def __init__(self, fail: BaseException | None = None) -> None:
        super().__init__("unused")
        self.fail = fail
        self.heard: list[Path] = []

    def transcribe(self, audio: Path, duration: float, progress: Progress) -> list[Segment]:
        assert self.diarize and self.reference is None and not self.references
        self.heard.append(audio)
        if self.fail is not None:
            raise self.fail
        self.asr = "1.4.1/overlap"
        self.speakers = [
            Speaker(id="N1", seconds=15, embedding=[0.98, 0.0, 0.2]),
            Speaker(id="N2", seconds=15, embedding=[0.5, 0.5, 0.7]),
            Speaker(id="N3", seconds=5, embedding=[0.0, 1.0, 0.0]),
            Speaker(id="N4", seconds=10, embedding=[0.0, 0.0, 1.0]),
            Speaker(id="N5", seconds=10, embedding=[0.3, 0.3, 0.9]),
        ]
        return NEW


def playback(library: Library, recording_id: str) -> None:
    """A playback copy, as transcription leaves it (16 kHz mono)."""
    with wave.open(str(library.folder(recording_id) / "playback.flac"), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(2) * 16000)


@pytest.fixture(autouse=True)
def no_ffmpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    """The playback copy is decoded by ffmpeg in production; here it already is the wav the service hears."""
    monkeypatch.setattr(recollect, "decode", lambda source, target: target.write_bytes(source.read_bytes()))


def decided_library(tmp_path: Path) -> tuple[Library, Team, str, str, str]:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    meeting = recording(
        library,
        "2026-03-02 周会.m4a",
        OLD,
        [
            Speaker(id="S1", seconds=25, embedding=[1.0, 0.0, 0.0]),
            Speaker(id="S2", seconds=10, embedding=[0.0, 1.0, 0.0]),
            Speaker(id="S3", seconds=10, embedding=[0.0, 0.0, 1.0]),
            Speaker(id="S4", seconds=10, embedding=[0.3, 0.3, 0.9]),
        ],
    )
    playback(library, meeting)
    zhang, li = team.add_person("张总"), team.add_person("李总")
    decide(team, meeting, "S1", "confirm", zhang.id, sample=True)
    decide(team, meeting, "S2", "confirm", li.id)
    decide(team, meeting, "S3", "unknown")
    # The owner left two of 张总's segments out of 张总's twin.
    transcript_id, _ = revision(library, meeting)
    for index in (2, 5):
        with library.transaction() as db:
            db.execute(
                "INSERT INTO segment_fixes (recording_id, transcript_id, segment, from_person, action, to_person, "
                "updated_at, auto) VALUES (?, ?, ?, ?, 'exclude', NULL, '2026-03-02', 0)",
                (meeting, transcript_id, index, zhang.id),
            )
    team.link(zhang.id, "p-zhang")
    team.link(li.id, "p-li")
    team.built("p-zhang", 1)
    team.built("p-li", 1)
    with library.transaction() as db:
        db.execute("INSERT INTO collector (key, value) VALUES ('asr', '1.4.1/overlap')")
    return library, team, meeting, zhang.id, li.id


def test_decisions_follow_the_speech_they_were_about(tmp_path: Path) -> None:
    library, team, meeting, zhang, li = decided_library(tmp_path)
    old = library.get(meeting)
    assert old is not None and old.transcript_id is not None
    assert recollect.ask(library, [meeting, "rec_missing"]) == 1
    assert [r.id for r in recollect.waiting(library)] == [meeting]
    assert recollect.ask(library, [meeting]) == 0  # Asked already.

    report = recollect.run(library, meeting, Newer(), lambda done, total: None)
    now = library.get(meeting)
    assert now is not None and now.transcript_id == report.new_transcript and now.previous == old.transcript_id
    assert (now.asr, now.recollect, now.speakers, now.segments) == ("1.4.1/overlap", None, 5, 9)
    assert now.revision > old.revision and recollect.waiting(library) == []
    assert library.recollectable() == ()

    view = {s.id: (s.decision, s.person_id, s.auto) for s in team.speakers(now)}
    # N1 is all of 张总's old speaker, N3 half of 李总's, N4 the voice nobody knows: each takes its decision.
    assert view["N1"] == ("confirmed", zhang, False) and view["N3"] == ("confirmed", li, False)
    assert view["N4"] == ("unknown", None, False)
    # N2 mixes 张总's and 李总's speech: nobody's decision, so the owner is told about it; N5 was undecided anyway.
    assert view["N2"][0] == "none" and view["N5"][0] == "none"
    assert (report.decided, report.carried) == (3, 3)
    assert [(u.speaker_id, sorted(u.people)) for u in report.unsettled] == [("N2", sorted([zhang, li]))]
    # Leaving 20-30 s out of 张总 follows to both new segments there; 50-55 s now belongs to N2, nobody's yet.
    with library.read() as db:
        fixes = db.execute(
            "SELECT segment, from_person, action FROM segment_fixes WHERE recording_id = ? AND transcript_id = ?",
            (meeting, now.transcript_id),
        ).fetchall()
    assert [tuple(f) for f in fixes] == [(4, zhang, "exclude"), (5, zhang, "exclude")]
    assert (report.fixes_carried, report.fixes_lost) == (1, [5])
    # 张总's voice sample now stands on N1, with N1's voiceprint.
    with library.read() as db:
        samples = db.execute(
            "SELECT transcript_id, speaker_id, active FROM voiceprints WHERE person_id = ? ORDER BY id", (zhang,)
        ).fetchall()
    assert [tuple(s) for s in samples] == [(old.transcript_id, "S1", 0), (now.transcript_id, "N1", 1)]
    assert len(report.samples_moved) == 1
    # Each twin is told its speech here changed: 10 s of 张总's (0-10) is now 5 s, 李总's 10 s is 5 s.
    assert report.seconds == {zhang: (10.0, 5.0), li: (10.0, 5.0)}
    assert wanted_done(library, "p-zhang")[0] > 1 and wanted_done(library, "p-li")[0] > 1
    (_, stored, rolled_back), *_ = recollect.reports(library)
    assert stored == report and not rolled_back

    # Back to the old transcript: every decision about it is as it was, and the sample stands on S1 again.
    assert recollect.rollback(library, meeting)
    back = library.get(meeting)
    assert back is not None and back.transcript_id == old.transcript_id and back.previous is None
    assert back.asr is None and back.speakers == 4
    view = {s.id: (s.decision, s.person_id) for s in team.speakers(back)}
    assert view["S1"] == ("confirmed", zhang) and view["S2"] == ("confirmed", li) and view["S3"][0] == "unknown"
    with library.read() as db:
        active = db.execute(
            "SELECT speaker_id FROM voiceprints WHERE person_id = ? AND active = 1", (zhang,)
        ).fetchall()
    assert [a[0] for a in active] == ["S1"]
    assert recollect.reports(library)[0][2] is True
    assert not recollect.rollback(library, meeting)  # Nothing further back.
    assert [r.id for r in library.recollectable()] == [meeting]  # It can be asked again.


def test_speakers_a_moved_sample_recognised_follow_it(tmp_path: Path) -> None:
    library, team, meeting, _, _ = decided_library(tmp_path)
    other = recording(
        library,
        "2026-03-09 周会.m4a",
        [segment(0, 30, "S1")],
        [Speaker(id="S1", seconds=30, embedding=[0.97, 0.05, 0.0])],
    )
    assert team.classify(other) == 1

    def given() -> int:
        with library.read() as db:
            row = db.execute("SELECT sample FROM attributions WHERE recording_id = ?", (other,)).fetchone()
        return int(row[0])

    old = given()
    recollect.ask(library, [meeting])
    report = recollect.run(library, meeting, Newer(), lambda done, total: None)
    assert report.samples_moved == [(old, given())] and given() != old
    with library.read() as db:
        source = db.execute("SELECT source FROM voiceprints WHERE id = ?", (given(),)).fetchone()[0]
    assert source == "speaker"
    assert recollect.rollback(library, meeting)
    assert given() == old


def test_a_failed_transcription_keeps_the_old_transcript(tmp_path: Path) -> None:
    library, team, meeting, zhang, _ = decided_library(tmp_path)
    old = library.get(meeting)
    assert old is not None
    recollect.ask(library, [meeting])
    with pytest.raises(TranscriptionError, match="原来的转写保持不变"):
        recollect.run(library, meeting, Newer(RuntimeError("down")), lambda done, total: None)
    after = library.get(meeting)
    assert after is not None and after.transcript_id == old.transcript_id and after.revision == old.revision
    # Not asked again by itself: a failing service would otherwise take every turn.
    assert after.recollect is None and recollect.waiting(library) == []
    assert [s.person_id for s in team.speakers(after) if s.id == "S1"] == [zhang]
    # Cut off by the service stopping, it waits for its turn again.
    recollect.ask(library, [meeting])
    with pytest.raises(TranscriptionInterrupted):
        recollect.run(library, meeting, Newer(Interrupted()), lambda done, total: None)
    assert [r.id for r in recollect.waiting(library)] == [meeting]
    # No audio is left behind.
    assert sorted(p.name for p in library.folder(meeting).iterdir() if p.suffix == ".wav") == []


def test_the_owner_asks_and_goes_back_through_the_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "library" / "team"
    _, _, meeting, _, _ = decided_library(tmp_path)
    service = Newer()
    monkeypatch.setattr("twin.web.library.make_transcriber", lambda _: service)
    settings = Settings(db_path=tmp_path / "twin.db")
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        listed = web.get("/api/library/recollect").json()
        assert listed["service"] == "1.4.1/overlap"
        assert [(r["id"], r["asr"], r["asked"]) for r in listed["recordings"]] == [(meeting, None, None)]
        assert web.post("/api/library/recollect", json={}, headers=HEADERS).json() == {"asked": 1}
        until(lambda: getattr(Library(root).get(meeting), "previous", None) is not None)
        done = web.get("/api/library/recollect").json()
        assert done["recordings"] == [] and done["done"][0]["recording_id"] == meeting
        assert done["done"][0]["carried"] == 3 and not done["done"][0]["rolled_back"]
        back = web.post(f"/api/library/recordings/{meeting}/rollback", headers=HEADERS)
        assert back.status_code == 200 and back.json()["previous"] is None
        assert web.post(f"/api/library/recordings/{meeting}/rollback", headers=HEADERS).status_code == 409
