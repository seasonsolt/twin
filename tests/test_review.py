"""Confirmed speakers heard again stretch by stretch (``media.review``), and the owner's decisions about them."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_team import HEADERS, decide, recording, revision, wanted_done

from twin.config import Settings
from twin.embed import HashingEmbedder
from twin.llm import FakeLLM
from twin.media import review as review_module
from twin.media.ingest import CommandTranscriber, Segment, Speaker
from twin.media.library import Library
from twin.media.review import Reviews, judge, units
from twin.media.team import Stale, Team
from twin.web import create_app


class Voices(CommandTranscriber):
    """A transcription service whose voiceprint of a stretch is chosen by the stretch's start."""

    def __init__(self, by_start: dict[float, list[float]], spans: bool = True) -> None:
        super().__init__("false")
        self.by_start, self.spans = by_start, spans
        self.requests: list[list[list[tuple[float, float]]]] = []

    def embed_spans(self, audio: Path, spans: list[list[tuple[float, float]]]) -> list[list[float] | None] | None:
        self.requests.append(spans)
        return [self.by_start.get(parts[0][0]) for parts in spans] if self.spans else None


def segment(start: float, end: float, speaker: str, text: str = "说了一句话。") -> Segment:
    return Segment(start=start, end=end, text=text, speaker=speaker)


def test_stretches_join_a_speakers_neighbouring_segments_up_to_a_few_seconds() -> None:
    segments = [
        segment(0, 1, "S1"),
        segment(1, 2, "S2"),
        segment(2, 3, "S1"),
        segment(3, 4.5, "S1"),
        segment(5, 6, "S1"),
        # A pause longer than MAX_GAP starts another stretch; one left short joins the one before it if near.
        segment(50, 54, "S1"),
        segment(60, 61, "S1"),
        segment(200, 201, "S1"),
        segment(201, 201, "S1"),
    ]
    found = units(segments, "S1")
    assert [u.segments for u in found] == [(0, 2, 3, 4), (5, 6), (7,)]
    assert found[0].parts == ((0, 1), (2, 3), (3, 4.5), (5, 6)) and found[0].seconds == 4.5
    assert units(segments, "S9") == []


def test_a_stretch_is_someone_elses_or_a_strangers_only_when_the_voices_say_so() -> None:
    assert judge(0.5, 0.62, 4) == "other"
    assert judge(0.5, 0.58, 4) == ""
    assert judge(0.2, 0.1, 4) == "stranger"
    # A stranger needs a few seconds; nothing is judged from a second or so.
    assert judge(0.2, 0.1, 2) == "" and judge(0.1, 0.9, 1) == ""


def library_with_mixed_speaker(tmp_path: Path) -> tuple[Library, Team, str, str, str, str]:
    """张总 and 李总 have voice samples from another meeting; in this one, 张总's speaker also holds a stretch of
    李总 and one of a stranger."""
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    earlier = recording(
        library,
        "2026-03-01 例会.m4a",
        [segment(0, 30, "S1"), segment(30, 60, "S2")],
        [Speaker(id="S1", seconds=30, embedding=[1.0, 0.0, 0.0]), Speaker(id="S2", seconds=30, embedding=[0, 1.0, 0])],
    )
    zhang, li = team.add_person("张总"), team.add_person("李总")
    decide(team, earlier, "S1", "confirm", zhang.id, sample=True)
    decide(team, earlier, "S2", "confirm", li.id, sample=True)
    mixed = recording(
        library,
        "2026-03-02 周会.m4a",
        [
            segment(0, 4, "S1", "先看预算。"),
            segment(4, 8, "S2", "好的。"),
            segment(40, 44, "S1", "研发不能砍。"),
            segment(80, 84, "S1", "我是来送快递的。"),
        ],
        [Speaker(id="S1", seconds=12, embedding=[0.9, 0.3, 0.1]), Speaker(id="S2", seconds=4, embedding=[0, 1, 0])],
    )
    decide(team, mixed, "S1", "confirm", zhang.id)
    return library, team, earlier, mixed, zhang.id, li.id


VOICES = {0.0: [1.0, 0.0, 0.0], 40.0: [0.1, 1.0, 0.0], 80.0: [0.0, 0.0, 1.0]}


def test_a_confirmed_speaker_is_heard_again_and_suspect_stretches_are_put_to_the_owner(tmp_path: Path) -> None:
    library, _, earlier, mixed, _, li = library_with_mixed_speaker(tmp_path)
    reviews = Reviews(library)
    assert [r.id for r in reviews.waiting()] == [earlier, mixed]
    service = Voices(VOICES)
    assert reviews.run(mixed, service) == 1
    # Each recording is asked once, for all its confirmed speakers' stretches.
    assert service.requests == [[[(0, 4)], [(40, 44)], [(80, 84)]]]
    assert [r.id for r in reviews.waiting()] == [earlier]

    found = library.get(mixed)
    assert found is not None
    view = reviews.speaker(found, "S1")
    assert view is not None and view.status == "ready" and view.name == "张总"
    assert [(u.verdict, u.like_name) for u in view.units] == [("", "李总"), ("other", "李总"), ("stranger", "李总")]
    assert view.units[1].text == "研发不能砍。" and view.units[0].own == 1.0
    assert (view.seconds, view.suspect_seconds, view.open, view.likely) == (12, 8, 2, li)
    (suspect,) = reviews.suspects()
    assert (suspect.speaker_id, suspect.share, suspect.units) == ("S1", 0.667, [])
    assert reviews.suspects({earlier}) == []

    # In the meeting the samples were taken from, a speaker would only be compared with itself.
    assert reviews.run(earlier, Voices({0.0: [1.0, 0, 0], 30.0: [0, 1.0, 0]})) == 2
    earlier_view = reviews.speaker(library.get(earlier), "S1")  # type: ignore[arg-type]
    assert earlier_view is not None and earlier_view.status == "no_samples" and earlier_view.units[0].own is None


def test_leaving_out_or_moving_stretches_rewrites_only_the_twins_they_change(tmp_path: Path) -> None:
    library, team, _, mixed, zhang, li = library_with_mixed_speaker(tmp_path)
    reviews = Reviews(library)
    zhang_before = {s.source_id for s in team.sources(zhang, "张总")}
    reviews.run(mixed, Voices(VOICES))
    team.link(zhang, "p-zhang")
    team.link(li, "p-li")
    assert [s.title for s in team.sources(li, "李总")] == ["2026-03-01 例会"]

    transcript_id, current = revision(library, mixed)
    current = reviews.fix(mixed, transcript_id, current, "S1", [2], "exclude")
    current = reviews.fix(mixed, transcript_id, current, "S1", [1], "move", li)
    sources = {s.title: s for s in team.sources(zhang, "张总")}
    lines = sources["2026-03-02 周会"].lines
    assert [(who, mine) for who, _, mine in lines] == [
        ("张总", True),
        ("其他人1", False),
        ("李总", False),
        ("其他人", False),
    ]
    assert {s.source_id for s in team.sources(zhang, "张总")} != zhang_before
    # The moved stretch is 李总's now, in a meeting where no speaker is theirs.
    given = {s.title: s for s in team.sources(li, "李总")}["2026-03-02 周会"]
    assert [i for i, line in enumerate(given.lines) if line[2]] == [2] and given.lines[0][0] == "张总"
    assert wanted_done(library, "p-zhang")[0] == 3 and wanted_done(library, "p-li")[0] == 2
    suspect = reviews.speaker(library.get(mixed), "S1")  # type: ignore[arg-type]
    assert suspect is not None and suspect.open == 0 and [u.fix for u in suspect.units] == [None, "move", "exclude"]
    assert suspect.units[1].to_name == "李总" and reviews.suspects() == []

    # Keeping a stretch that was the person's anyway closes no twin; undoing a decision does.
    current = reviews.fix(mixed, transcript_id, current, "S1", [0], "keep")
    assert wanted_done(library, "p-zhang")[0] == 3
    current = reviews.fix(mixed, transcript_id, current, "S1", [1, 2], "clear")
    assert wanted_done(library, "p-zhang")[0] == 4 and wanted_done(library, "p-li")[0] == 3
    assert {s.title for s in team.sources(li, "李总")} == {"2026-03-01 例会"}

    with pytest.raises(Stale):
        reviews.fix(mixed, transcript_id, current - 1, "S1", [1], "exclude")
    for bad in ({"indices": [9], "action": "exclude"}, {"indices": [1], "action": "move", "to_person": zhang}):
        with pytest.raises(ValueError):
            reviews.fix(mixed, transcript_id, current, "S1", **bad)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="还没有确认"):
        reviews.fix(mixed, transcript_id, current, "S2", [0], "exclude")


def test_decisions_about_stretches_follow_the_people_they_name(tmp_path: Path) -> None:
    library, team, _, mixed, zhang, li = library_with_mixed_speaker(tmp_path)
    reviews = Reviews(library)
    reviews.run(mixed, Voices(VOICES))
    transcript_id, current = revision(library, mixed)
    current = reviews.fix(mixed, transcript_id, current, "S1", [1], "move", li)
    reviews.fix(mixed, transcript_id, current + 0, "S1", [2], "exclude")
    # Taking 李总 for 张总 after all: the stretch given from one to the other was theirs all along.
    team.merge(li, zhang)
    view = reviews.speaker(library.get(mixed), "S1")  # type: ignore[arg-type]
    assert view is not None and [u.fix for u in view.units] == [None, None, "exclude"]
    # A speaker given to someone else leaves the decisions about its stretches behind.
    decide(team, mixed, "S1", "clear")
    assert [s.title for s in team.sources(zhang, "张总")] == ["2026-03-01 例会"]
    # Deleting the recording takes its stretches with it.
    assert library.delete(mixed)
    with library.read() as db:
        assert db.execute("SELECT COUNT(*) FROM review_units WHERE recording_id = ?", (mixed,)).fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM segment_fixes").fetchone()[0] == 0


def test_an_older_service_is_asked_stretch_by_stretch_and_a_failure_waits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, _, _, mixed, _, _ = library_with_mixed_speaker(tmp_path)
    cut: list[tuple[tuple[float, float], ...]] = []

    def fake_cut(audio: Path, output: Path, parts: Any, rate: int = 24000) -> None:
        assert rate == 16000
        cut.append(tuple(parts))
        output.write_bytes(str(parts[0][0]).encode())

    class Old(Voices):
        def embed(self, voice: Path) -> list[float] | None:
            return VOICES.get(float(voice.read_text()))

    monkeypatch.setattr(review_module, "cut_parts", fake_cut)
    reviews = Reviews(library)
    assert reviews.run(mixed, Old({}, spans=False)) == 1
    assert cut == [((0, 4),), ((40, 44),), ((80, 84),)]
    assert not list(library.folder(mixed).glob(".review-*"))
    view = reviews.speaker(library.get(mixed), "S1")  # type: ignore[arg-type]
    assert view is not None and [u.verdict for u in view.units] == ["", "other", "stranger"]

    class Down(Voices):
        def embed_spans(self, audio: Path, spans: list[list[tuple[float, float]]]) -> list[list[float] | None] | None:
            raise RuntimeError("转写服务没能计算声纹")

    library_two, _, _, again, _, _ = library_with_mixed_speaker(tmp_path / "two")
    reviews = Reviews(library_two)
    with pytest.raises(RuntimeError):
        reviews.run(again, Down({}))
    failed = reviews.speaker(library_two.get(again), "S1")  # type: ignore[arg-type]
    assert failed is not None and failed.status == "failed" and "声纹" in failed.error
    assert again not in {r.id for r in reviews.waiting()}


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_the_team_page_hears_settles_and_plays_suspect_stretches(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "data" / "twin.db")
    app = create_app(settings, llm_factory=lambda: FakeLLM(lambda *_: {"items": []}), embedder_factory=HashingEmbedder)
    library, _, _, mixed, _, _ = library_with_mixed_speaker(tmp_path / "data")
    assert library.root == settings.db_path.parent / "library" / "team"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=90",
            "-ar",
            "16000",
            str(library.folder(mixed) / "playback.flac"),
        ],
        check=True,
    )
    Reviews(library).run(mixed, Voices(VOICES))
    with TestClient(app, base_url="http://localhost") as web:
        review = web.get("/api/library/review").json()
        (suspect,) = review["suspects"]
        assert (suspect["speaker_id"], suspect["name"], suspect["open"]) == ("S1", "张总", 2)
        base = f"/api/library/recordings/{mixed}/speakers/S1/units"
        detail = web.get(base).json()
        assert [u["verdict"] for u in detail["units"]] == ["", "other", "stranger"]
        clip = web.get(f"{base}/1/clip")
        assert clip.status_code == 200 and clip.headers["content-type"] == "audio/wav" and len(clip.content) > 1000
        assert web.get(f"{base}/7/clip").status_code == 404
        body = {"transcript_id": detail["transcript_id"], "revision": detail["revision"], "units": [1, 2]}
        moved = web.put(base, json={**body, "action": "move", "new_person": "王工"}, headers=HEADERS)
        assert moved.status_code == 200, moved.text
        assert web.put(base, json={**body, "action": "exclude"}, headers=HEADERS).status_code == 409
        names = {p["name"] for p in web.get("/api/library/people").json()["items"]}
        assert "王工" in names and web.get("/api/library/review").json()["suspects"] == []
        assert web.get(f"/api/library/recordings/{mixed}/speakers/S2/units").status_code == 404


def test_a_speaker_decided_again_reopens_whoever_was_given_its_stretches(tmp_path: Path) -> None:
    library, team, _, mixed, _zhang, li = library_with_mixed_speaker(tmp_path)
    reviews = Reviews(library)
    reviews.run(mixed, Voices(VOICES))
    team.link(li, "p-li")
    transcript_id, current = revision(library, mixed)
    reviews.fix(mixed, transcript_id, current, "S1", [1], "move", li)
    before = wanted_done(library, "p-li")[0]
    # 李总 speaks nowhere in this meeting, yet the stretch given to them leaves their twin once S1 is nobody's.
    decide(team, mixed, "S1", "clear")
    assert wanted_done(library, "p-li")[0] == before + 1
    assert [s.title for s in team.sources(li, "李总")] == ["2026-03-01 例会"]


def test_suspect_stretches_leave_the_twin_without_asking_and_the_owner_can_take_them_back(tmp_path: Path) -> None:
    library, team, _, mixed, zhang, li = library_with_mixed_speaker(tmp_path)
    team.link(zhang, "p-zhang")
    reviews = Reviews(library)
    before = wanted_done(library, "p-zhang")[0]
    reviews.run(mixed, Voices(VOICES))
    # 李总's stretch and the stranger's are out of 张总's twin at once, and the twin is rebuilt once.
    (source,) = [s for s in team.sources(zhang, "张总") if s.title == "2026-03-02 周会"]
    assert [i for i, line in enumerate(source.lines) if line[2]] == [0]
    assert wanted_done(library, "p-zhang")[0] == before + 1
    view = reviews.speaker(library.get(mixed), "S1")  # type: ignore[arg-type]
    assert view is not None and [(u.fix, u.auto) for u in view.units] == [
        (None, False),
        ("exclude", True),
        ("exclude", True),
    ]
    # Left out by the review alone, the speaker still waits for the owner when most of it is suspect.
    assert view.open == 2 and [s.speaker_id for s in reviews.suspects()] == ["S1"]
    # Settling again changes nothing and closes no twin.
    assert reviews.settle() == 0 and wanted_done(library, "p-zhang")[0] == before + 1

    # The owner hears the stranger's stretch and keeps it: it is 张总's again, and stays so.
    transcript_id, current = revision(library, mixed)
    current = reviews.fix(mixed, transcript_id, current, "S1", [2], "keep")
    assert reviews.settle() == 0
    (source,) = [s for s in team.sources(zhang, "张总") if s.title == "2026-03-02 周会"]
    assert [i for i, line in enumerate(source.lines) if line[2]] == [0, 3]
    view = reviews.speaker(library.get(mixed), "S1")  # type: ignore[arg-type]
    assert [(u.fix, u.auto) for u in view.units] == [(None, False), ("exclude", True), ("keep", False)]  # type: ignore[union-attr]

    # Confirmed as 李总 instead, S1's stretches are judged against 李总: the one sounding like 张总 leaves them,
    # and so does the stranger's, since keeping it was a word about 张总 and no longer holds.
    decide(team, mixed, "S1", "confirm", li)
    assert reviews.settle({mixed}) == 2
    view = reviews.speaker(library.get(mixed), "S1")  # type: ignore[arg-type]
    assert view is not None and view.person_id == li
    assert [(u.verdict, u.fix) for u in view.units] == [("other", "exclude"), ("", None), ("stranger", "exclude")]


def wrongly_confirmed(tmp_path: Path) -> tuple[Library, Team, str, str, str]:
    """张总 and 李总 have samples from another meeting; in this one 李总's speaker was taken as 张总's sample."""
    library, team, _, _, zhang, li = library_with_mixed_speaker(tmp_path)
    wrong = recording(
        library,
        "2026-03-03 周会.m4a",
        [segment(0, 4, "S1", "预算要砍。"), segment(40, 44, "S1", "研发先停。"), segment(80, 84, "S1", "下周再议。")],
        [Speaker(id="S1", seconds=12, embedding=[0.1, 1.0, 0.0])],
    )
    decide(team, wrong, "S1", "confirm", zhang, sample=True)
    return library, team, wrong, zhang, li


LIKE_LI = {0.0: [0.1, 1.0, 0.0], 40.0: [0.0, 1.0, 0.0], 80.0: [0.05, 1.0, 0.0]}


def attribution(library: Library, recording_id: str) -> tuple[str, int, list[str]]:
    with library.read() as db:
        row = db.execute(
            "SELECT person_id, auto, rejected FROM attributions WHERE recording_id = ? AND speaker_id = 'S1'",
            (recording_id,),
        ).fetchone()
    return str(row[0]), int(row[1]), json.loads(row[2])


def test_a_speaker_confirmed_as_the_wrong_person_is_given_to_whom_it_sounds_like(tmp_path: Path) -> None:
    library, team, wrong, zhang, li = wrongly_confirmed(tmp_path)
    team.link(zhang, "p-zhang")
    team.link(li, "p-li")
    reviews = Reviews(library)
    reviews.run(wrong, Voices(LIKE_LI))
    # Every stretch sounds like 李总: the speaker is theirs now, as an automatic decision, and not 张总's.
    assert attribution(library, wrong) == (li, 1, [zhang])
    assert "2026-03-03 周会" not in {s.title for s in team.sources(zhang, "张总")}
    (given,) = [s for s in team.sources(li, "李总") if s.title == "2026-03-03 周会"]
    assert [i for i, line in enumerate(given.lines) if line[2]] == [0, 1, 2]
    # The sample taken from it as 张总 no longer stands for them, and nothing is left for the owner.
    with library.read() as db:
        assert not db.execute(
            "SELECT 1 FROM voiceprints WHERE recording_id = ? AND person_id = ? AND active = 1", (wrong, zhang)
        ).fetchone()
    assert wrong not in {s.recording_id for s in reviews.suspects()}
    assert reviews.settle() == 0

    # The owner hears it and says it is 张总 after all: their word stands, the review does not take it away again.
    decide(team, wrong, "S1", "confirm", zhang)
    # Only its stretches leave 张总's twin again (three segments), and the speaker is put to the owner.
    assert reviews.settle({wrong}) == 3 and attribution(library, wrong) == (zhang, 0, [])
    assert [s.speaker_id for s in reviews.suspects({wrong})] == ["S1"]


def test_a_speaker_the_wrong_sample_held_up_is_given_away_with_it(tmp_path: Path) -> None:
    library, team, wrong, zhang, li = wrongly_confirmed(tmp_path)
    held = recording(
        library,
        "2026-03-04 周会.m4a",
        [segment(0, 4, "S1", "预算砍一半。"), segment(40, 44, "S1", "研发也停。"), segment(80, 84, "S1", "就这样。")],
        [Speaker(id="S1", seconds=12, embedding=[0.0, 1.0, 0.0])],
    )
    decide(team, held, "S1", "confirm", zhang)
    reviews = Reviews(library)
    # Heard first, it sounds like the sample wrongly taken as 张总's: nothing to doubt yet.
    reviews.run(held, Voices(LIKE_LI))
    assert attribution(library, held) == (zhang, 0, [])
    assert held not in {s.recording_id for s in reviews.suspects()}
    # Once that speaker is given to 李总, this one sounds like 李总 alone and follows in the same settling.
    reviews.run(wrong, Voices(LIKE_LI))
    assert attribution(library, wrong) == (li, 1, [zhang])
    assert attribution(library, held) == (li, 1, [zhang])


def test_a_speaker_is_never_given_to_someone_the_owner_said_it_is_not(tmp_path: Path) -> None:
    library, _, wrong, zhang, li = wrongly_confirmed(tmp_path)
    with library.transaction() as db:
        db.execute("UPDATE attributions SET rejected = ? WHERE recording_id = ?", (json.dumps([li]), wrong))
    Reviews(library).run(wrong, Voices(LIKE_LI))
    assert attribution(library, wrong)[0] == zhang
    # Left with 张总, every stretch is out of their twin and the speaker waits for the owner.
    assert [s.speaker_id for s in Reviews(library).suspects({wrong})] == ["S1"]
