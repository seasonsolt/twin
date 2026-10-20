"""Team twins from the recording library: decisions, matching, sources and the memory gate (P0b acceptance)."""

from __future__ import annotations

import datetime as dt
import json
import math
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_chat_streaming import StreamingLLM, parse_events

from twin.api import create_api
from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media.cues import Cue, Named
from twin.media.ingest import Segment, Speaker
from twin.media.library import Library, Recording, Transcript
from twin.media.schema import AVATAR_GENDERS
from twin.media.team import Stale, Team
from twin.persona import gate
from twin.persona.chat import PersonaChat
from twin.persona.items import PersonaItem
from twin.persona.schema import ChatTurn
from twin.persona.store import PersonaStore
from twin.web import create_app
from twin.web import library as web_library
from twin.web.jobs import PersonaProcessing

HEADERS = {"X-Twin": "1"}


def recording(library: Library, name: str, segments: list[Segment], speakers: list[Speaker]) -> str:
    """A transcribed recording, as the transcription job leaves it. Filed ready in one insert, after its transcript:
    a running app wakes every queued recording to transcribe it, and one queued here for a moment without an upload
    failed under it, sometimes after this had marked it ready, so it was never proofread."""
    recording_id = f"rec_{uuid.uuid4().hex[:20]}"
    transcript = Transcript(
        id=uuid.uuid4().hex[:12],
        recording_id=recording_id,
        created_at="2026-10-17T00:00:00+00:00",
        duration_s=segments[-1].end,
        segments=segments,
        speakers=speakers,
    )
    folder = library.folder(recording_id)
    folder.mkdir(parents=True, mode=0o700)
    Library._write_transcript(folder, transcript)
    row = Recording(
        id=recording_id,
        sha256=uuid.uuid4().hex,
        filename=name,
        size=16,
        kind="audio",
        status="ready",
        transcript_id=transcript.id,
        segments=len(segments),
        speakers=len(speakers),
        created_at=(now := dt.datetime.now(dt.UTC).isoformat()),
        updated_at=now,
    ).model_dump()
    with library.transaction() as db:
        db.execute(
            f"INSERT INTO recordings ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", tuple(row.values())
        )
    return recording_id


def meeting(library: Library, name: str = "2026-03-02 周会.m4a", lead: list[float] | None = None) -> str:
    return recording(
        library,
        name,
        [
            Segment(start=0, end=4, text="先看预算。", speaker="S1"),
            Segment(start=4, end=6, text="", speaker="S2"),
            Segment(start=6, end=9, text="我反对压缩研发。", speaker="S2"),
            Segment(start=9, end=12, text="那就按季度复盘。", speaker="S1"),
            Segment(start=12, end=14, text="嗯，都同意。", speaker="S3"),
        ],
        [
            Speaker(id="S1", seconds=7, embedding=lead or [1.0, 0.0, 0.0]),
            Speaker(id="S2", seconds=5, embedding=[0.0, 1.0, 0.0]),
            Speaker(id="S3", seconds=2, embedding=[0.0, 0.0, 1.0]),
        ],
    )


def revision(library: Library, recording_id: str) -> tuple[str, int]:
    found = library.get(recording_id)
    assert found and found.transcript_id
    return found.transcript_id, found.revision


def decide(team: Team, recording_id: str, speaker: str, action: Any, person: str | None = None, **kw: Any) -> int:
    transcript_id, current = revision(team.library, recording_id)
    return team.decide(recording_id, transcript_id, current, speaker, action, person, **kw)


def wanted_done(library: Library, persona_id: str) -> tuple[int, int]:
    with library.read() as db:
        row = db.execute("SELECT wanted, done FROM personas_sync WHERE persona_id = ?", (persona_id,)).fetchone()
    return int(row[0]), int(row[1])


# ------------------------------------------------------------------ decisions and matching


def test_samples_match_later_recordings_and_a_denial_or_change_takes_them_away(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first, second = meeting(library), meeting(library, "第二次.m4a", lead=[0.95, 0.05, 0.0])
    zhang, li = team.add_person("张总"), team.add_person("李总")
    with pytest.raises(ValueError, match="已经有"):
        team.add_person(" 张总 ")
    decide(team, first, "S1", "confirm", zhang.id, sample=True)
    decide(team, first, "S2", "confirm", li.id, sample=True)

    lead = next(s for s in team.speakers(library.get(second)) if s.id == "S1")  # type: ignore[arg-type]
    assert [c.name for c in lead.candidates] == ["张总"] and lead.candidates[0].score > 0.9
    assert [entry["id"] for entry in team.review()] == ["S2", "S1"]  # best match first

    # Denying 张总 for that speaker leaves only people it was not denied to be.
    decide(team, second, "S1", "reject", zhang.id)
    lead = next(s for s in team.speakers(library.get(second)) if s.id == "S1")  # type: ignore[arg-type]
    assert lead.rejected == [zhang.id] and all(c.person_id != zhang.id for c in lead.candidates)

    # The sample's basis is re-decided: the sample stops counting and the candidates follow.
    decide(team, first, "S1", "unknown")
    assert next(p for p in team.people() if p.id == zhang.id).samples == 0
    assert all(c.person_id != zhang.id for s in team.speakers(library.get(second)) for c in s.candidates)  # type: ignore[arg-type]

    transcript_id, current = revision(library, first)
    with pytest.raises(Stale):
        team.decide(first, transcript_id, current - 1, "S1", "mixed")
    with pytest.raises(Stale):
        team.decide(first, "another", current, "S1", "mixed")


def test_a_twin_reads_only_its_own_segments_and_mixed_speakers_are_nobody(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = meeting(library)
    zhang, li = team.add_person("张总"), team.add_person("李总")
    decide(team, first, "S1", "confirm", zhang.id)
    decide(team, first, "S2", "confirm", li.id)
    decide(team, first, "S3", "mixed")
    (source,) = team.sources(zhang.id, "张总")
    assert [line[2] for line in source.lines] == [True, False, False, True, False]
    # Every segment keeps its number, the empty one too; others are named once decided, otherwise numbered.
    assert [line[0] for line in source.lines] == ["张总", "李总", "李总", "张总", "其他人1"]
    assert source.lines[1][1] == "" and source.date == "2026-03-02"
    assert not any(line[2] for line in team.sources(li.id, "李总")[0].lines if line[0] == "其他人1")


def test_the_same_words_moving_to_another_person_change_the_source(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    same = "我支持这个方案。"
    rec = recording(
        library,
        "评审.m4a",
        [Segment(start=i, end=i + 1, text=same if i in (7, 19) else f"第{i}句。", speaker="S1") for i in range(20)],
        [Speaker(id="S1", seconds=20, embedding=[1.0, 0.0])],
    )
    # Segments 7 and 19 swap owners: the transcript is re-split so 7 belongs to S2, 19 to S1.
    zhang = team.add_person("张总")
    decide(team, rec, "S1", "confirm", zhang.id)
    before = team.sources(zhang.id, "张总")[0]
    found = library.get(rec)
    assert found is not None
    transcript = library.transcript(found)
    assert transcript is not None
    transcript.segments[7].speaker = "S2"
    swapped = transcript.model_copy(update={"id": transcript.id})
    folder = library.folder(rec)
    (folder / f"transcript-{transcript.id}.json").unlink()
    Library._write_transcript(folder, swapped)
    after = team.sources(zhang.id, "张总")[0]
    assert before.source_id != after.source_id
    assert [i for i, line in enumerate(after.lines) if line[2] and line[1].endswith(same)] == [19]


def test_deleting_a_recording_closes_the_twins_it_fed(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first, other = meeting(library), meeting(library, "无关.m4a")
    zhang = team.add_person("张总")
    decide(team, first, "S1", "confirm", zhang.id)
    team.link(zhang.id, "p-zhang")
    assert team.built("p-zhang", 1) and wanted_done(library, "p-zhang") == (1, 1)
    assert library.delete(other) and wanted_done(library, "p-zhang") == (1, 1)
    assert library.delete(first) and wanted_done(library, "p-zhang") == (2, 1)
    # A build of the old version cannot open it.
    assert not team.built("p-zhang", 1) and wanted_done(library, "p-zhang") == (2, 1)
    assert team.sources(zhang.id, "张总") == []


def test_listing_people_and_candidates_reads_each_transcript_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = meeting(library)
    meeting(library, "第二次.m4a")
    zhang = team.add_person("张总")
    decide(team, first, "S1", "confirm", zhang.id, sample=True)
    reads: list[str] = []
    original = Library.transcript
    monkeypatch.setattr(Library, "transcript", lambda self, r: reads.append(r.id) or original(self, r))
    for _ in range(3):
        fresh = Team(Library(library.root))  # Every request makes its own.
        assert fresh.people()[0].speakers == 1 and fresh.review()
    assert len(reads) == len(set(reads)) <= 2  # Never the same transcript twice.


def voices(library: Library, name: str, *speakers: tuple[list[float], float]) -> str:
    """A recording whose speakers S1, S2, ... have these voiceprints and speaking times."""
    return recording(
        library,
        name,
        [Segment(start=i, end=i + 1, text=f"第{i}位说话。", speaker=f"S{i + 1}") for i in range(len(speakers))],
        [Speaker(id=f"S{i + 1}", seconds=seconds, embedding=vector) for i, (vector, seconds) in enumerate(speakers)],
    )


def test_known_voices_are_taken_without_asking_and_new_long_voices_become_unnamed_people(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = voices(library, "一.m4a", ([1.0, 0.0, 0.0], 120), ([0.0, 1.0, 0.0], 90), ([0.0, 0.0, 1.0], 10))
    assert team.classify(first)
    view = {s.id: s for s in team.speakers(library.get(first))}  # type: ignore[arg-type]
    assert [p.name for p in team.people()] == ["未命名 1", "未命名 2"]
    assert view["S1"].auto and view["S2"].auto and view["S1"].decision == "confirmed"
    assert view["S3"].decision == "none"  # Too short to make anyone of.
    assert not team.classify(first)  # Nothing left that the voice settles.
    assert team.identities()[first] == (["未命名 1", "未命名 2"], 2)  # S3 still waits for the owner.

    lead = view["S1"].person_id
    assert lead is not None
    team.rename(lead, "张总")
    with pytest.raises(ValueError, match="已经有"):
        team.rename(lead, "未命名 2")
    team.link(lead, "p-zhang")
    team.built("p-zhang", 1)

    second = voices(
        library,
        "二.m4a",
        ([0.97, 0.03, 0.0], 100),  # 张总
        ([0.02, 1.0, 0.0], 70),  # 未命名 2
        ([0.6, 0.6, 0.2], 80),  # Like both: left for the owner.
        ([0.99, 0.01, 0.0], 5),  # Like 张总 but too short to be sure.
    )
    assert team.classify(second)
    view = {s.id: s for s in team.speakers(library.get(second))}  # type: ignore[arg-type]
    people = {p.name: p for p in team.people()}
    assert (view["S1"].person_id, view["S2"].person_id) == (lead, people["未命名 2"].id)
    assert view["S3"].decision == view["S4"].decision == "none"
    # Both people S3 sounds like already speak here as S1 and S2, so it is someone else: nobody is suggested.
    assert not view["S3"].candidates
    # S4 is as alike to S1 as a split half: 张总 again, the answer by default.
    assert [(c.person_id, c.split, c.sure) for c in view["S4"].candidates] == [(lead, True, True)]
    assert people["张总"].samples == 1 and not people["张总"].auto  # A match adds no sample.
    assert people["未命名 2"].auto and people["未命名 2"].speakers == 2 and people["未命名 2"].recording_id
    assert wanted_done(library, "p-zhang") == (2, 1)  # 张总's twin follows the new recording.

    # Naming someone rebuilds everyone who speaks with them, since their sources call them by name.
    team.built("p-zhang", 2)
    team.rename(people["未命名 2"].id, "李总")
    assert wanted_done(library, "p-zhang") == (3, 2)

    # The owner says it is not 张总: that speaker is never classified again.
    decide(team, second, "S1", "reject", lead)
    assert not team.classify(second)
    assert next(s for s in team.speakers(library.get(second)) if s.id == "S1").decision == "none"  # type: ignore[arg-type]


def test_an_unnamed_person_whose_voice_is_given_away_is_forgotten(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = voices(library, "一.m4a", ([1.0, 0.0], 120), ([0.0, 1.0], 90))
    assert team.classify(first)
    unnamed = {p.name: p.id for p in team.people()}
    zhang = team.add_person("张总")
    decide(team, first, "S1", "reject", unnamed["未命名 2"])  # A denial names them too, and must not dangle.
    # The owner hears 未命名 1 and says it is 张总: nobody is left for "who is this".
    decide(team, first, "S1", "confirm", zhang.id)
    assert {p.name for p in team.people()} == {"张总", "未命名 2"}
    # Undoing the automatic decision forgets them as well, and the voice is not made into someone again.
    decide(team, first, "S2", "clear")
    assert [p.name for p in team.people()] == ["张总"]
    assert not team.classify(first)
    assert all(not s.rejected for s in team.speakers(library.get(first)))  # type: ignore[arg-type]
    assert not team.prune()  # A named person stays even with nothing heard.


def test_an_unnamed_voice_is_settled_as_someone_known_or_nobody(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = voices(library, "一.m4a", ([1.0, 0.0, 0.0], 120), ([0.0, 1.0, 0.0], 90))
    assert team.classify(first)
    unnamed = {p.name: p for p in team.people()}
    assert (unnamed["未命名 1"].recording_id, unnamed["未命名 1"].speaker_id) == (first, "S1")
    zhang = team.add_person("张总")
    team.link(zhang.id, "p-zhang")
    _, before = revision(library, first)
    with pytest.raises(ValueError, match="还没起名"):
        team.resolve(zhang.id, None)
    with pytest.raises(ValueError, match="找不到"):
        team.resolve(unnamed["未命名 1"].id, "per_nobody")

    # Heard as 张总: the speaker is the owner's decision, and the voice becomes 张总's sample.
    team.resolve(unnamed["未命名 1"].id, zhang.id)
    view = {s.id: s for s in team.speakers(library.get(first))}  # type: ignore[arg-type]
    assert (view["S1"].decision, view["S1"].person_id, view["S1"].auto) == ("confirmed", zhang.id, False)
    assert revision(library, first)[1] == before + 1
    assert wanted_done(library, "p-zhang")[0] == 2  # Linked at 1; 张总 now speaks there.
    later = voices(library, "二.m4a", ([0.98, 0.02, 0.0], 100))
    assert team.classify(later)
    assert team.speakers(library.get(later))[0].person_id == zhang.id  # type: ignore[arg-type]

    # Nobody known: the speaker is settled as such, and nobody is left to name.
    team.resolve(unnamed["未命名 2"].id, None)
    view = {s.id: s for s in team.speakers(library.get(first))}  # type: ignore[arg-type]
    assert (view["S2"].decision, view["S2"].person_id) == ("unknown", None)
    assert [p.name for p in team.people()] == ["张总"]
    assert team.identities()[first] == (["张总"], 2)
    assert not team.classify(first)


def test_a_new_sample_and_a_restart_classify_the_whole_library(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    first = voices(library, "一.m4a", ([1.0, 0.0], 15), ([0.0, 1.0], 15))
    second = voices(library, "二.m4a", ([0.98, 0.02], 40), ([0.0, 1.0], 61))
    settings = Settings(db_path=tmp_path / "twin.db")
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as web:
        # Started with recordings never classified: the long new voice of the second becomes someone, in the
        # background so that start-up does not wait for every transcript to be read.
        until(lambda: [p["name"] for p in web.get("/api/library/people").json()["items"]] == ["未命名 1"])
        detail = web.get(f"/api/library/recordings/{first}").json()
        confirm = {"transcript_id": detail["transcript_id"], "revision": detail["revision"], "action": "confirm"}
        put = web.put(
            f"/api/library/recordings/{first}/speakers/S1",
            json={**confirm, "new_person": "张总", "sample": True},
            headers=HEADERS,
        )
        zhang = put.json()["person_id"]
        speakers = {s["id"]: s for s in web.get(f"/api/library/recordings/{second}").json()["speakers"]}
        assert speakers["S1"]["person_id"] == zhang and speakers["S1"]["auto"] is True
        unnamed = next(p for p in web.get("/api/library/people").json()["items"] if p["auto"])
        renamed = web.patch(f"/api/library/people/{unnamed['id']}", json={"name": "李总"}, headers=HEADERS)
        assert renamed.status_code == 200
        taken = web.patch(f"/api/library/people/{unnamed['id']}", json={"name": "张总"}, headers=HEADERS)
        assert taken.status_code == 409
        other = web.post(f"/api/library/people/{unnamed['id']}/resolve", json={"into": zhang}, headers=HEADERS)
        assert other.status_code == 409  # Named by now.
        names = {p["name"]: p["auto"] for p in web.get("/api/library/people").json()["items"]}
        assert names == {"张总": False, "李总": False}
        rows = {r["id"]: r for r in web.get("/api/library").json()["recordings"]}
        assert (rows[first]["people"], rows[first]["unsettled"]) == (["张总"], 1)
        assert (rows[second]["people"], rows[second]["unsettled"]) == (["张总", "李总"], 0)


# ------------------------------------------------------------------ the gate


def linked_store(tmp_path: Path) -> tuple[Library, Path]:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    zhang = team.add_person("张总")
    team.link(zhang.id, "p-zhang")
    db = tmp_path / "personas" / "p-zhang" / "twin.db"
    db.parent.mkdir(parents=True)
    with PersonaStore(db) as store:
        gate.link(store, library.db_path, "p-zhang")
        store.set_meta("built_at", "2026-01-01")
        store.replace_facet_items(
            "2.1", [PersonaItem(item_id="pi_test", facet_id="2.1", statement="回款优先", evidence=[])]
        )
    return library, db


def test_a_voice_heard_in_many_recordings_is_settled_once(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    one = voices(library, "一.m4a", ([1.0, 0.0, 0.0], 40), ([0.0, 1.0, 0.0], 30), ([0.0, 0.0, 1.0], 4))
    two = voices(
        library,
        "二.m4a",
        ([0.95, 0.05, 0.0], 25),
        ([0.05, 0.95, 0.0], 20),
        ([0.9, 0.1, 0.0], 10),  # As alike to S1 as a split half: one person diarization split in two.
        ([0.5, 0.5, 0.707], 4),  # Somewhat like S1 and S2, but told apart from both here.
    )
    three = voices(library, "三.m4a", ([1.0, 0.1, 0.0], 12))

    found, fragments = team.voices()
    assert [[(m.recording_id, m.speaker_id) for m in v.members] for v in found] == [
        [(one, "S1"), (two, "S1"), (three, "S1"), (two, "S3")],
        [(one, "S2"), (two, "S2")],
    ]
    assert [v.seconds for v in found] == [87, 50] and not found[0].candidates
    assert sorted((m.recording_id, m.speaker_id) for v in fragments for m in v.members) == sorted(
        [(one, "S3"), (two, "S4")]
    )
    assert [[m.speaker_id for m in v.members] for v in team.voices({two})[0]] == [["S1", "S3"], ["S2"]]

    # Settled as a whole: every meeting is 张总's now, and the longest speaker is his voice sample.
    zhang = team.add_person("张总")
    members = [(m.recording_id, m.transcript_id, m.speaker_id) for m in found[0].members]
    before = {rid: revision(library, rid)[1] for rid in (one, two, three)}
    team.decide_voice(members, "confirm", zhang.id)
    person = team.person(zhang.id)
    assert person and (person.speakers, person.samples, person.seconds) == (4, 1, 87)
    assert all(revision(library, rid)[1] == before[rid] + 1 for rid in (one, two, three))
    after, _ = team.voices()
    assert [[m.speaker_id for m in v.members] for v in after] == [["S2", "S2"]]

    # A page showing an old grouping is refused as a whole.
    with pytest.raises(Stale):
        team.decide_voice([*members[:1], (two, revision(library, two)[0], "S2")], "unknown")
    assert next(s for s in team.speakers(library.get(two)) if s.id == "S2").decision == "none"  # type: ignore[arg-type]

    # Fragments are set aside together, and a voice like nobody's stays out of the samples.
    team.decide_voice(
        [(m.recording_id, m.transcript_id, m.speaker_id) for v in team.voices()[1] for m in v.members], "unknown"
    )
    assert team.identities()[one] == (["张总"], 2) and team.voices()[1] == []
    with pytest.raises(ValueError, match="需要指定"):
        team.decide_voice([(two, revision(library, two)[0], "S2")], "confirm")


def test_only_a_close_voice_is_suggested_and_only_a_very_close_one_is_the_default(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    wang = team.add_person("王宁")
    sample = voices(library, "样本.m4a", ([1.0, 0.0, 0.0], 60))
    decide(team, sample, "S1", "confirm", wang.id, sample=True)

    # Speakers too short to decide automatically, long enough to be asked about alone: 0.5, 0.7, 0.8 to 王宁's sample.
    far = voices(library, "一.m4a", ([0.5, 0.866, 0.0], 18))
    close = voices(library, "二.m4a", ([0.7, 0.714, 0.0], 18))
    closer = voices(library, "三.m4a", ([0.8, 0.6, 0.0], 18))

    def suggested(recording_id: str) -> list[tuple[str, bool]]:
        speaker = team.speakers(library.get(recording_id))[0]  # type: ignore[arg-type]
        return [(c.name, c.sure) for c in speaker.candidates]

    # The nearest known voice is merely the nearest: not offered. Like enough to offer, but not to answer by
    # Enter. Close enough to be the answer.
    assert (suggested(far), suggested(close), suggested(closer)) == ([], [("王宁", False)], [("王宁", True)])
    assert [(v.candidates[0].name, v.candidates[0].sure) for v in team.voices({close})[0]] == [("王宁", False)]


def test_one_meeting_gives_a_person_one_voice_sample_so_its_room_does_not_lean_towards_them(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    # Voices of 张总, 李明 and a third colleague, and the room of a weekly meeting heard on all of them there.
    zhang, li = team.add_person("张总"), team.add_person("李明")
    samples = voices(library, "样本.m4a", ([1.0, 0.0, 0.0, 0.0], 60), ([0.0, 1.0, 0.0, 0.0], 60))
    decide(team, samples, "S1", "confirm", zhang.id, sample=True)
    decide(team, samples, "S2", "confirm", li.id, sample=True)
    first = voices(library, "周会一.m4a", ([1.0, 0.0, 0.0, 0.8], 300), ([0.0, 0.0, 1.0, 0.8], 200))

    # Once 张总 is settled in the meeting, its other voices are not offered as him: they are someone else there.
    lead = next(v for v in team.voices({first})[0] if v.members[0].speaker_id == "S1")
    team.decide_voice([(first, lead.members[0].transcript_id, "S1")], "confirm", zhang.id)
    [other] = team.voices({first})[0]
    assert not other.candidates
    # The owner takes the other voice for 张总 too: the meeting is still one sample of his, its longest voice.
    team.decide_voice([(first, other.members[0].transcript_id, "S2")], "confirm", zhang.id)
    person = team.person(zhang.id)
    assert person and (person.speakers, person.samples) == (3, 2)

    # In the next meeting of that room, 李明 (0.62 to his sample) sounds 0.75 like the second voice of the first
    # meeting, 0.40 like 张总 there: still suggested as 李明, not taken for whoever was settled most in the room.
    second = voices(library, "周会二.m4a", ([0.0, 0.62, 0.45, 0.65], 18))
    [voice] = team.voices({second})[0]
    assert [(c.name, c.score) for c in voice.candidates] == [("李明", 0.617)]

    # Two people sampled in one meeting and then merged keep its earlier sample alone.
    double = team.add_person("张总（重复）")
    decide(team, first, "S2", "confirm", double.id, sample=True)
    team.merge(double.id, zhang.id)
    person = team.person(zhang.id)
    assert person and (person.speakers, person.samples) == (3, 2)
    [voice] = team.voices({second})[0]
    assert [(c.name, c.score) for c in voice.candidates] == [("李明", 0.617)]


def test_a_settled_voice_gives_its_person_samples_from_several_recordings(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)

    def angle(degrees: float) -> list[float]:
        return [math.cos(math.radians(degrees)), math.sin(math.radians(degrees)), 0.0]

    # One colleague through four rooms and microphones, and later in a fifth sounding like the second room only.
    heard = [
        voices(library, f"{n}.m4a", (angle(a), seconds))
        for n, a, seconds in ((1, 0, 300), (2, 30, 200), (3, 35, 100), (4, 10, 30))
    ]
    later = voices(library, "5.m4a", (angle(60), 40))
    [voice] = [v for v in team.voices()[0] if len(v.members) > 1]
    assert [m.recording_id for m in voice.members] == heard
    wang = team.add_person("王宁")
    team.decide_voice([(m.recording_id, m.transcript_id, m.speaker_id) for m in voice.members], "confirm", wang.id)
    # The three longest from different recordings, not the short fourth.
    person = team.person(wang.id)
    assert person and (person.speakers, person.samples) == (4, 3)
    # 0.5 alike to the longest, 0.87 to the second: recognised by the second sample alone.
    assert team.classify_all() == 1
    assert next(s for s in team.speakers(library.get(later)) if s.id == "S1").person_id == wang.id  # type: ignore[arg-type]


def test_a_voice_the_owner_could_not_name_comes_back_as_such(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = voices(library, "一.m4a", ([0.0, 1.0, 0.0], 40))
    [voice] = team.voices()[0]
    assert not voice.stranger
    team.decide_voice([(m.recording_id, m.transcript_id, m.speaker_id) for m in voice.members], "unknown")

    # The same colleague in the next meeting, long enough to become "未命名 2" otherwise, and someone new.
    second = voices(library, "二.m4a", ([0.05, 1.0, 0.0], 90), ([1.0, 0.0, 0.0], 90))
    assert team.classify(second) == 1
    view = {s.id: s for s in team.speakers(library.get(second))}  # type: ignore[arg-type]
    assert view["S1"].decision == "none" and view["S2"].decision == "confirmed"
    assert [p.name for p in team.people()] == ["未命名 1"]
    # Not decided behind the owner's back: asked about as the voice they already could not name.
    [again] = team.voices()[0]
    assert [(m.recording_id, m.speaker_id) for m in again.members] == [(second, "S1")] and again.stranger
    # The colleague may still recognise their own voice in either meeting.
    assert {(v.recording.id, v.speaker_id) for v in team.open_voices()} >= {(first, "S1"), (second, "S1")}


def test_confirming_a_voice_never_leaves_more_questions_than_before(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    voices(library, "一.m4a", ([1.0, 0.0, 0.0, 0.0], 40))
    voices(library, "二.m4a", ([0.8, 0.6, 0.0, 0.0], 30))
    # Short voices of three other meetings: somewhat like the first speaker, unlike the second and each other.
    short = [
        voices(library, f"{n}.m4a", (vector, 5))
        for n, vector in (
            ("三", [0.65, -0.76, 0.0, 0.0]),
            ("四", [0.65, 0.0, -0.76, 0.0]),
            ("五", [0.65, 0.0, 0.0, -0.76]),
        )
    ]

    def asked() -> int:
        found, fragments = team.voices()
        return len(found) + (1 if fragments else 0)

    assert asked() == 2
    [voice] = team.voices()[0]
    zhang = team.add_person("张总")
    team.decide_voice([(m.recording_id, m.transcript_id, m.speaker_id) for m in voice.members], "confirm", zhang.id)
    # The short voices now sound like 张总, and still wait together, to be given to him in one click.
    found, fragments = team.voices()
    assert asked() == 1 and found == []
    assert sorted(m.recording_id for f in fragments for m in f.members) == sorted(short)
    assert all(f.candidates[0].person_id == zhang.id for f in fragments)
    members = [(m.recording_id, m.transcript_id, m.speaker_id) for f in fragments for m in f.members]
    team.decide_voice(members, "confirm", zhang.id, sample=False)
    person = team.person(zhang.id)
    assert asked() == 0 and person and (person.speakers, person.samples) == (5, 1)


def test_a_voice_can_be_several_people_mixed_together(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    one = voices(library, "一.m4a", ([1.0, 0.0, 0.0], 40))
    [voice] = team.voices()[0]
    team.decide_voice([(m.recording_id, m.transcript_id, m.speaker_id) for m in voice.members], "mixed")
    assert team.voices() == ([], [])
    [speaker] = team.speakers(library.get(one))  # type: ignore[arg-type]
    assert speaker.decision == "mixed" and team.people() == []
    # Not a voice the owner could not name: nothing like it is asked about as such.
    voices(library, "二.m4a", ([1.0, 0.05, 0.0], 40))
    [again] = team.voices()[0]
    assert not again.stranger


def test_voices_like_one_the_owner_could_not_name_wait_last(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    voices(library, "一.m4a", ([0.0, 1.0, 0.0], 40))
    [voice] = team.voices()[0]
    team.decide_voice([(m.recording_id, m.transcript_id, m.speaker_id) for m in voice.members], "unknown")
    voices(library, "二.m4a", ([0.05, 1.0, 0.0], 50), ([1.0, 0.0, 0.0], 30))
    assert [(v.seconds, v.stranger) for v in team.voices()[0]] == [(30, False), (50, True)]


def name(library: Library, recording_id: str, *cues: tuple[str, str, bool]) -> None:
    """File what the meeting calls speakers: (speaker, name, whether the name was said plainly)."""
    found = library.get(recording_id)
    assert found and found.transcript_id
    library.write_names(
        found,
        Named(
            transcript_id=found.transcript_id,
            created_at="2026-10-20T00:00:00+00:00",
            speakers=[Cue(speaker=s, name=n, evidence=[0], sure=sure, quote=f"请{n}讲一下。") for s, n, sure in cues],
        ),
    )


def test_what_a_meeting_calls_a_speaker_is_offered_beside_their_voice(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    wang, ai = team.add_person("王宁"), team.add_person("艾总")
    sample = voices(library, "样本.m4a", ([1.0, 0.0, 0.0], 60))
    decide(team, sample, "S1", "confirm", wang.id, sample=True)
    week = voices(
        library,
        "周会.m4a",
        ([0.0, 0.0, 1.0], 90),  # The chair: nobody calls them by name.
        ([0.8, 0.6, 0.0], 50),  # Called 王宁, and sounds like her.
        ([0.0, 1.0, 0.0], 40),  # Called 宋明, whom the team does not know yet.
        ([0.7, 0.714, 0.0], 30),  # Called 艾总 (no voice sample), though sounding somewhat like 王宁.
    )
    name(library, week, ("S2", "王宁", True), ("S3", "宋明", True), ("S4", "艾总", True))

    found = {v.members[0].speaker_id: v for v in team.voices()[0]}
    # One meeting's 王宁 and 艾总 are told apart by their names, though their voices are split-half alike.
    assert sorted(found) == ["S1", "S2", "S3", "S4"]
    s2, s3, s4 = found["S2"], found["S3"], found["S4"]
    assert [(c.name, c.called, c.sure) for c in s2.candidates] == [("王宁", True, True)]
    assert (s2.called, s2.quote) == ("王宁", "请王宁讲一下。")
    assert (s3.candidates, s3.called) == ([], "宋明")
    # The name leads, but a voice sounding like someone else is no default for either.
    assert [(c.name, c.called, c.sure) for c in s4.candidates] == [("艾总", True, False), ("王宁", False, False)]
    assert found["S1"].called is None and found["S1"].quote == ""

    # The recording page offers the same.
    view = {s.id: s for s in team.speakers(library.get(week))}  # type: ignore[arg-type]
    assert [(c.name, c.called) for c in view["S4"].candidates] == [("艾总", True), ("王宁", False)]
    assert (view["S3"].called, view["S3"].quote) == ("宋明", "请宋明讲一下。")

    # Once 王宁 is settled here, the meeting calling another speaker by her name is not offered.
    decide(team, week, "S2", "confirm", wang.id)
    name_again = voices(library, "周会二.m4a", ([0.0, 0.0, 1.0], 20), ([0.0, 1.0, 0.0], 20))
    decide(team, name_again, "S1", "confirm", ai.id)
    name(library, name_again, ("S2", "艾总", True))
    [other] = [v for v in team.voices({name_again})[0] if v.members[0].speaker_id == "S2"]
    assert (other.candidates, other.called) == ([], None)


def test_voices_of_someone_heard_enough_wait_behind_the_rest(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    wang, ai = team.add_person("王宁"), team.add_person("艾总")
    sample = voices(library, "样本.m4a", ([1.0, 0.0, 0.0], 1800), ([0.0, 1.0, 0.0], 600))
    decide(team, sample, "S1", "confirm", wang.id, sample=True)
    decide(team, sample, "S2", "confirm", ai.id, sample=True)
    later = voices(
        library,
        "周会.m4a",
        ([0.95, 0.05, 0.0], 100),  # Surely 王宁, already heard half an hour.
        ([0.05, 0.95, 0.0], 60),  # Surely 艾总, heard ten minutes.
        ([0.0, 0.0, 1.0], 30),  # Nobody known.
    )
    order = [(v.members[0].speaker_id, v.enough, v.had) for v in team.voices({later})[0]]
    assert order == [("S2", False, 600), ("S3", False, 0), ("S1", True, 1800)]
    lacking = {p.name: p.lacking for p in team.people()}
    assert lacking == {"王宁": 0, "艾总": 1200}


def test_a_voice_never_chains_colleagues_who_sound_alike(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)

    def angle(degrees: float) -> list[float]:
        return [math.cos(math.radians(degrees)), math.sin(math.radians(degrees)), 0.0]

    # Each one like the next, the first and last not alike: their centroid would take all three for one voice.
    first = voices(library, "一.m4a", (angle(0), 300))
    second = voices(library, "二.m4a", (angle(35), 200))
    third = voices(library, "三.m4a", (angle(70), 100))
    found, _ = team.voices()
    assert [[m.recording_id for m in v.members] for v in found] == [[first, second], [third]]

    # Alike, but one sounds most like 王宁 and the other like 艾总: asked about apart, each led by its own.
    wang, ai = team.add_person("王宁"), team.add_person("艾总")
    sample = voices(library, "样本.m4a", ([1.0, 0.6, 0.0], 60), ([1.0, -0.6, 0.0], 60))
    decide(team, sample, "S1", "confirm", wang.id, sample=True)
    decide(team, sample, "S2", "confirm", ai.id, sample=True)
    one = voices(library, "四.m4a", ([1.0, 0.1, 0.0], 50))
    other = voices(library, "五.m4a", ([1.0, -0.1, 0.0], 40))
    led = {v.members[0].recording_id: v.candidates[0].name for v in team.voices({one, other})[0]}
    assert led == {one: "王宁", other: "艾总"}


def test_a_person_is_heard_by_their_voice_sample(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first, second = meeting(library), meeting(library, "第二次.m4a")
    zhang = team.add_person("张总")
    decide(team, first, "S1", "confirm", zhang.id)
    person = team.person(zhang.id)
    assert person and (person.recording_id, person.speaker_id) == (first, "S1")  # Only a meeting so far.
    decide(team, second, "S2", "confirm", zhang.id, sample=True)
    person = team.person(zhang.id)
    assert person and (person.recording_id, person.speaker_id) == (second, "S2")  # The voice others match.


def test_speakers_without_a_voiceprint_are_settled_in_their_recording(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    rec = recording(
        library,
        "无声纹.m4a",
        [Segment(start=0, end=4, text="先看预算。", speaker="S1"), Segment(start=4, end=8, text="好。", speaker="S2")],
        [Speaker(id="S1", seconds=4, embedding=[1.0, 0.0, 0.0]), Speaker(id="S2", seconds=4)],
    )
    meeting(library)  # Every speaker has a voiceprint: in voices, not here.
    assert [(r.id, n) for r, n in team.unvoiced()] == [(rec, 1)]
    assert team.unvoiced({"rec_other"}) == []
    decide(team, rec, "S2", "unknown")
    assert team.unvoiced() == []


def test_every_way_of_asking_is_refused_until_the_build_is_complete(tmp_path: Path) -> None:
    library, db = linked_store(tmp_path)
    settings = Settings(db_path=db)
    llm = FakeLLM(lambda *_: {"reply": "回款优先", "citations": [], "confidence": 0.5, "mode": "general"})
    with PersonaStore(db) as store, pytest.raises(gate.MemoryUpdating):
        PersonaChat(store, llm, HashingEmbedder(), settings)
    api = create_api(settings, lambda: PersonaChat(PersonaStore(db), llm, HashingEmbedder(), settings), token="t" * 32)
    with TestClient(api, base_url="http://localhost") as client:
        refused = client.post("/v1/ask", json={"question": "怎么看？"}, headers={"Authorization": "Bearer " + "t" * 32})
    assert refused.status_code == 409 and refused.json()["code"] == "memory_updating"

    Team(library).built("p-zhang", 1)
    with PersonaStore(db) as store:
        chat = PersonaChat(store, llm, HashingEmbedder(), settings)
        # The twin's memory changes while it answers: the answer is void and not logged.
        with library.transaction() as connection:
            connection.execute("UPDATE personas_sync SET wanted = wanted + 1")
        with pytest.raises(gate.MemoryUpdating):
            chat.reply([ChatTurn(role="user", content="怎么看？")])
        assert chat.stale
    with sqlite3.connect(db) as connection:
        assert connection.execute("SELECT COUNT(*) FROM p_chat_log").fetchone()[0] == 0


def test_a_meeting_record_answers_without_the_portrait(tmp_path: Path) -> None:
    library, db = linked_store(tmp_path)
    Team(library).built("p-zhang", 1)
    settings = Settings(db_path=db)
    answer = {"reply": "会上没聊到这个。", "citations": [], "confidence": 0.2, "mode": "abstain", "abstain": True}
    prompts: dict[bool, str] = {}
    for meeting_record in (True, False):
        llm = FakeLLM(lambda *_: answer)
        with PersonaStore(db) as store:
            if not meeting_record:
                store.set_meta(gate.MODE, "")
            PersonaChat(store, llm, HashingEmbedder(), settings).reply([ChatTurn(role="user", content="回款怎么看？")])
        prompts[meeting_record] = "".join(system + user for name, system, user in llm.calls if name == "ChatDraft")
    assert "回款优先" not in prompts[True] and "只凭会上的记录" in prompts[True]
    assert "回款优先" in prompts[False] and "只凭会上的记录" not in prompts[False]


@pytest.fixture
def web(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    def soon(delay: float, fn: Any) -> threading.Timer:
        timer = threading.Timer(0.01, fn)
        timer.daemon = True
        timer.start()
        return timer

    monkeypatch.setattr(PersonaProcessing, "_timer", staticmethod(soon))
    settings = Settings(db_path=tmp_path / "twin.db")
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    with TestClient(app, base_url="http://localhost") as client:
        yield client


def until(check: Any, seconds: float = 60) -> None:
    """Wait for ``check`` to hold. ``seconds`` is only a liveness bound: a build on a loaded machine can take many
    seconds, and the wait ends as soon as the check holds."""
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() > deadline:
            raise AssertionError("timed out")
        time.sleep(0.05)


def open_twin(web: TestClient, persona_id: str) -> bool:
    return web.get("/api/status", headers={"X-Twin-Persona": persona_id}).json()["memory_updating"] is False


def test_a_misattributed_fact_leaves_the_twin_and_reaches_the_right_one(web: TestClient, tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    rec = meeting(library)
    detail = web.get(f"/api/library/recordings/{rec}").json()
    assert [s["id"] for s in detail["speakers"]] == ["S1", "S2", "S3"] and len(detail["segments"]) == 5
    body = {"transcript_id": detail["transcript_id"], "revision": detail["revision"]}
    # S2's objection is wrongly given to 张总 (a new person), with S2 as a voice sample.
    put = web.put(
        f"/api/library/recordings/{rec}/speakers/S2",
        json={**body, "action": "confirm", "new_person": "张总", "sample": True},
        headers=HEADERS,
    )
    assert put.status_code == 200
    zhang = put.json()["person_id"]
    stale = web.put(f"/api/library/recordings/{rec}/speakers/S1", json={**body, "action": "mixed"}, headers=HEADERS)
    assert stale.status_code == 409 and "刷新" in stale.json()["detail"]
    orphan = {**body, "action": "confirm", "new_person": "王总"}
    assert web.put(f"/api/library/recordings/{rec}/speakers/S3", json=orphan, headers=HEADERS).status_code == 409
    assert [p["name"] for p in web.get("/api/library/people").json()["items"]] == ["张总"]
    assert all(s["samples"] >= 1 for s in web.get(f"/api/library/recordings/{rec}").json()["speakers"])

    twin = web.post(f"/api/library/people/{zhang}/persona", headers=HEADERS).json()
    assert twin["new"] is True
    again = web.post(f"/api/library/people/{zhang}/persona", headers=HEADERS).json()
    assert again == {"persona_id": twin["persona_id"], "new": False}
    pid = twin["persona_id"]
    until(lambda: open_twin(web, pid))
    persona = {"X-Twin-Persona": pid}
    sources = web.get("/api/persona/sources", headers=persona).json()["items"]
    assert len(sources) == 1 and sources[0]["n_target"] == 1

    # Corrected to 李总: from this moment until the rebuild, nothing of 张总's memory is read.
    revision_now = web.get(f"/api/library/recordings/{rec}").json()["revision"]
    li = web.post("/api/library/people", json={"name": "李总"}, headers=HEADERS).json()["id"]
    # Hold the rebuild so the closed state can be observed: no build timer fires while held.
    held: list[Any] = []
    web.app.state.personas.application(pid).state.processing._schedule = lambda delay, fn: held.append(fn)  # type: ignore[union-attr]
    moved = web.put(
        f"/api/library/recordings/{rec}/speakers/S2",
        json={"transcript_id": body["transcript_id"], "revision": revision_now, "action": "confirm", "person_id": li},
        headers=HEADERS,
    )
    assert moved.status_code == 200
    assert web.get("/api/status", headers=persona).json()["memory_updating"] is True
    chat = {"messages": [{"role": "user", "content": "研发预算怎么看？"}]}
    for method, path, payload in [
        ("post", "/api/persona/chat/stream", chat),
        ("post", "/api/persona/chat", chat),
        ("get", "/api/persona/items", None),
        ("get", "/api/persona/items/summary", None),
        ("get", "/api/persona/followups", None),
        ("get", "/api/persona/ledger", None),
        ("post", "/api/persona/work", {"text": "写一份周报"}),
    ]:
        response = getattr(web, method)(path, headers={**HEADERS, **persona}, **({"json": payload} if payload else {}))
        assert response.status_code == 409 and response.json()["code"] == "memory_updating", path
    until(lambda: bool(held))
    for fn in held:
        fn()
    until(lambda: open_twin(web, pid))
    sources = web.get("/api/persona/sources", headers=persona).json()["items"]
    assert sources == []  # 张总 has no speaker left in that meeting.

    li_twin = web.post(f"/api/library/people/{li}/persona", headers=HEADERS).json()["persona_id"]
    until(lambda: open_twin(web, li_twin))
    with PersonaStore(tmp_path / "personas" / li_twin / "twin.db") as store:
        own = [e.text for e in store.list_expressions() if e.is_target]
    assert own == ["[00:06] 我反对压缩研发。"]
    people = {p["name"]: p for p in web.get("/api/library/people").json()["items"]}
    assert people["李总"]["persona_id"] == li_twin and people["张总"]["samples"] == 0


def test_a_twin_from_the_library_stays_private(web: TestClient) -> None:
    li = web.post("/api/library/people", json={"name": "李总"}, headers=HEADERS).json()["id"]
    pid = web.post(f"/api/library/people/{li}/persona", headers=HEADERS).json()["persona_id"]
    public = web.patch(f"/api/personas/{pid}", json={"public": True}, headers=HEADERS)
    assert public.status_code == 409 and "私有" in public.json()["detail"]
    assert web.patch(f"/api/personas/{pid}", json={"public": False}, headers=HEADERS).status_code == 200
    own = web.post("/api/personas", json={"name": "自己"}, headers=HEADERS).json()["id"]
    assert web.patch(f"/api/personas/{own}", json={"public": True}, headers=HEADERS).json()["public"] is True


def test_a_failed_sync_is_tried_again(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_library, "SYNC_RETRY_SECONDS", (0.01, 0.01))
    libraries = web.app.state.libraries  # type: ignore[attr-defined]
    write = libraries.write_sources
    calls: list[str] = []

    def flaky(owner: str, persona_id: str) -> bool:
        calls.append(persona_id)
        if len(calls) == 1:
            raise OSError("disk briefly unavailable")
        return bool(write(owner, persona_id))

    monkeypatch.setattr(libraries, "write_sources", flaky)
    li = web.post("/api/library/people", json={"name": "李总"}, headers=HEADERS).json()["id"]
    pid = web.post(f"/api/library/people/{li}/persona", headers=HEADERS).json()["persona_id"]
    until(lambda: open_twin(web, pid))
    assert calls == [pid, pid]


def test_a_deleted_twin_is_not_synced(web: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    libraries = web.app.state.libraries  # type: ignore[attr-defined]
    li = web.post("/api/library/people", json={"name": "李总"}, headers=HEADERS).json()["id"]
    pid = web.post(f"/api/library/people/{li}/persona", headers=HEADERS).json()["persona_id"]
    # Deleting answers 409 while any background job of the twin is still running, which can outlast memory_updating.
    until(lambda: web.delete(f"/api/personas/{pid}", headers=HEADERS).status_code == 200)
    synced: list[str] = []
    monkeypatch.setattr(libraries, "sync", lambda owner, persona_id: synced.append(persona_id))
    with libraries.library("local").transaction() as db:
        db.execute("UPDATE personas_sync SET wanted = wanted + 1")
    libraries.changed("local")
    assert synced == []


def test_a_person_s_gender_dresses_their_twin(web: TestClient) -> None:
    def preset(persona_id: str) -> str:
        return str(web.get("/api/identity", headers={"X-Twin-Persona": persona_id}).json()["avatar_preset"])

    li = web.post("/api/library/people", json={"name": "李总"}, headers=HEADERS).json()["id"]
    assert web.patch(f"/api/library/people/{li}", json={"gender": "female"}, headers=HEADERS).status_code == 200
    assert web.patch(f"/api/library/people/{li}", json={"gender": "other"}, headers=HEADERS).status_code == 400
    assert web.get("/api/library/people").json()["items"][0]["gender"] == "female"
    pid = web.post(f"/api/library/people/{li}/persona", headers=HEADERS).json()["persona_id"]
    assert AVATAR_GENDERS[preset(pid)] == "female"
    web.patch(f"/api/library/people/{li}", json={"gender": "male"}, headers=HEADERS)
    chosen = preset(pid)
    assert AVATAR_GENDERS[chosen] == "male"
    # Name and gender in one change; a matching illustration (perhaps chosen by hand) is kept.
    web.patch(f"/api/library/people/{li}", json={"name": "李总监", "gender": "male"}, headers=HEADERS)
    assert preset(pid) == chosen
    assert web.get("/api/library/people").json()["items"][0]["name"] == "李总监"
    web.patch(f"/api/library/people/{li}", json={"gender": ""}, headers=HEADERS)
    assert preset(pid) == chosen  # Unsaid changes nothing.


def test_a_change_waiting_at_shutdown_is_carried_out_after_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(PersonaProcessing, "_timer", staticmethod(lambda delay, fn: threading.Timer(3600, fn)))
    settings = Settings(db_path=tmp_path / "twin.db")
    library = Library(tmp_path / "library" / "team")
    rec = meeting(library)
    factory = {"llm_factory": lambda: FakeLLM(lambda *_: {"items": []}), "embedder_factory": HashingEmbedder}
    with TestClient(create_app(settings, **factory), base_url="http://localhost") as web:
        person = web.post("/api/library/people", json={"name": "张总"}, headers=HEADERS).json()["id"]
        detail = web.get(f"/api/library/recordings/{rec}").json()
        web.put(
            f"/api/library/recordings/{rec}/speakers/S1",
            json={
                "transcript_id": detail["transcript_id"],
                "revision": detail["revision"],
                "action": "confirm",
                "person_id": person,
            },
            headers=HEADERS,
        )
        pid = web.post(f"/api/library/people/{person}/persona", headers=HEADERS).json()["persona_id"]
        # The process stops before any build: the twin stays closed.
        assert web.get("/api/status", headers={"X-Twin-Persona": pid}).json()["memory_updating"] is True
    with library.transaction() as db:
        db.execute("UPDATE personas_sync SET wanted = wanted + 1")

    def soon(delay: float, fn: Any) -> threading.Timer:
        timer = threading.Timer(0.01, fn)
        timer.start()
        return timer

    monkeypatch.setattr(PersonaProcessing, "_timer", staticmethod(soon))
    with TestClient(create_app(settings, **factory), base_url="http://localhost") as web:
        until(lambda: open_twin(web, pid))
        assert wanted_done(library, pid)[0] == wanted_done(library, pid)[1] == 2


def test_an_answer_streamed_while_the_memory_changes_is_marked_and_not_saved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, _ = linked_store(tmp_path)
    Team(library).built("p-zhang", 1)
    registry = tmp_path / "personas.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "default": "default",
                "personas": [
                    {"id": "default", "owner": None, "created_at": "2026-01-01T00:00:00+00:00"},
                    {"id": "p-zhang", "owner": None, "created_at": "2026-01-01T00:00:00+00:00"},
                ],
            }
        )
    )

    class Changing(StreamingLLM):
        """Writes its answer while a decision changes the twin's recordings."""

        async def stream(self, **kwargs: Any) -> AsyncIterator[str]:
            first = True
            async for chunk in super().stream(**kwargs):
                if first:
                    with library.transaction() as connection:
                        connection.execute("UPDATE personas_sync SET wanted = wanted + 1")
                    first = False
                yield chunk

    settings = Settings(db_path=tmp_path / "twin.db")
    app = create_app(settings, llm_factory=lambda: Changing(lambda *_: {}), embedder_factory=HashingEmbedder)
    persona = {**HEADERS, "X-Twin-Persona": "p-zhang"}
    with TestClient(app, base_url="http://localhost") as web:
        cid = web.post("/api/conversations", headers=persona).json()["id"]
        body = {"conversation_id": cid, "messages": [{"role": "user", "content": "怎么看？"}]}
        events = parse_events(web.post("/api/persona/chat/stream", json=body, headers=persona))
        assert events[-1][0] == "stale" and "过时" in events[-1][1]["detail"]
        turns = web.get(f"/api/conversations/{cid}", headers=persona).json()["turns"]
        assert [t["role"] for t in turns] == ["user"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")
def test_speakers_can_be_heard_at_several_moments(web: TestClient, tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    rec = meeting(library)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=f=220:d=14",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(library.folder(rec) / "playback.flac"),
        ],
        check=True,
    )
    sample = web.get(f"/api/library/recordings/{rec}/speakers/S1/samples/0")
    assert sample.status_code == 200 and sample.headers["content-type"] == "audio/wav"
    assert web.get(f"/api/library/recordings/{rec}/speakers/S9/samples/0").status_code == 404
    assert not list(library.folder(rec).glob("*.wav"))


def test_a_twin_from_meetings_is_made_for_a_work_address_and_stays_private(web: TestClient, tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    rec = meeting(library)
    detail = web.get(f"/api/library/recordings/{rec}").json()
    body = {"transcript_id": detail["transcript_id"], "revision": detail["revision"], "action": "confirm"}
    put = web.put(f"/api/library/recordings/{rec}/speakers/S2", json={**body, "new_person": "张总"}, headers=HEADERS)
    zhang = put.json()["person_id"]
    bad = web.post(f"/api/library/people/{zhang}/persona", json={"claim": "张总"}, headers=HEADERS)
    assert bad.status_code == 400
    twin = web.post(f"/api/library/people/{zhang}/persona", json={"claim": "Zhang@Acme.cn"}, headers=HEADERS).json()
    [entry] = [p for p in web.get("/api/personas").json() if p["id"] == twin["persona_id"]]
    assert entry["claim"] == "zhang@acme.cn" and entry["claimed"] is False
    # Nobody but 张总, once signed in and having looked at it, lets colleagues ask it.
    public = web.patch(f"/api/personas/{twin['persona_id']}", json={"public": True}, headers=HEADERS)
    assert public.status_code == 409


def test_a_voice_is_settled_once_through_the_page(web: TestClient, tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    first = voices(library, "一.m4a", ([1.0, 0.0, 0.0], 30), ([0.0, 1.0, 0.0], 3))
    second = voices(library, "二.m4a", ([0.95, 0.05, 0.0], 20))
    listed = web.get("/api/library/review").json()
    assert listed["unsorted"] == []  # Every speaker has a voiceprint.
    assert listed["heard"] == {"settled": 0, "total": 53}  # Progress is how much speech is settled.
    assert listed["items"] == [] and [(m["recording_id"], m["speaker_id"]) for m in listed["fragments"]] == [
        (first, "S2")
    ]
    lead = listed["voices"][0]
    assert [(m["recording_id"], m["speaker_id"]) for m in lead["members"]] == [(first, "S1"), (second, "S1")]
    members = [{k: m[k] for k in ("recording_id", "transcript_id", "speaker_id")} for m in lead["members"]]
    post = web.post(
        "/api/library/voices", json={"members": members, "action": "confirm", "new_person": "张总"}, headers=HEADERS
    )
    assert post.status_code == 200
    [zhang] = [p for p in web.get("/api/library/people").json()["items"] if p["name"] == "张总"]
    assert (zhang["id"], zhang["speakers"], zhang["samples"]) == (post.json()["person_id"], 2, 1)
    assert post.json()["recognised"] == 0  # Nobody else to recognise by the new sample.
    # The same grouping again is out of date, and the person made for it is not left behind.
    again = web.post(
        "/api/library/voices", json={"members": members, "action": "confirm", "new_person": "李总"}, headers=HEADERS
    )
    assert again.status_code == 409
    assert [p["name"] for p in web.get("/api/library/people").json()["items"]] == ["张总"]
    listed = web.get("/api/library/review").json()
    assert listed["voices"] == [] and listed["heard"] == {"settled": 50, "total": 53}
