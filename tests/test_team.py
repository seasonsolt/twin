"""Team twins from the recording library: decisions, matching, sources and the memory gate (P0b acceptance)."""

from __future__ import annotations

import json
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
from twin.media.ingest import Segment, Speaker
from twin.media.library import Library, Transcript
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
    """A transcribed recording, as the transcription job leaves it."""
    part = library.root / f"{uuid.uuid4().hex}.part"
    part.write_bytes(uuid.uuid4().bytes)
    added, _ = library.add(part, name)
    transcript = Transcript(
        id=uuid.uuid4().hex[:12],
        recording_id=added.id,
        created_at="2026-10-17T00:00:00+00:00",
        duration_s=segments[-1].end,
        segments=segments,
        speakers=speakers,
    )
    folder = library.folder(added.id)
    for original in folder.glob("original.*"):
        original.unlink()
    Library._write_transcript(folder, transcript)
    library.update(
        added.id, status="ready", transcript_id=transcript.id, segments=len(segments), speakers=len(speakers)
    )
    return added.id


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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    assert view["S3"].decision == view["S4"].decision == "none" and view["S3"].candidates
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
    library = Library(tmp_path / "library" / "local")
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
