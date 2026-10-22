"""The cached web queue must be identical to the original reading and follow every committed change."""

from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from test_review import VOICES, Voices, library_with_mixed_speaker
from test_team import decide, meeting, revision

from twin.media.library import Library
from twin.media.review import Reviews
from twin.media.team import Team
from twin.web.review_queue import PAGED, ReviewQueue, page


def original_queue(library: Library, recordings: set[str]) -> dict[str, Any]:
    """The response before caching and before restricting the old queue to disputed speakers."""
    team = Team(library)
    voices, fragments = team.voices(recordings)
    suspects = Reviews(library).suspects(recordings)
    settled, total = team.heard(recordings)
    return {
        "heard": {"settled": settled, "total": total},
        "items": [entry for entry in team.review(recordings) if entry["disputed"]],
        "voices": [voice.model_dump() for voice in voices],
        "fragments": [
            {
                **member.model_dump(),
                "like": {"person_id": voice.candidates[0].person_id, "name": voice.candidates[0].name}
                if voice.candidates
                else None,
            }
            for voice in fragments
            for member in voice.members
        ],
        "unsorted": [
            {"recording_id": r.id, "filename": r.filename, "speakers": n, "total": r.speakers}
            for r, n in team.unvoiced(recordings)
        ],
        "suspects": [review.model_dump() for review in suspects],
    }


def test_queue_stays_identical_after_samples_decisions_reviews_and_people_change(tmp_path: Path) -> None:
    library, team, earlier, mixed, zhang, li = library_with_mixed_speaker(tmp_path)
    scope = {earlier, mixed}
    queue = ReviewQueue(library)
    try:

        def same() -> None:
            expected = original_queue(library, scope)
            assert queue.get(scope) == expected
            assert queue.get(scope) == expected

        same()
        Reviews(library).run(mixed, Voices(VOICES))  # Reviewed units arrive without changing recording.revision.
        same()
        transcript, version = revision(library, mixed)
        Reviews(library).fix(mixed, transcript, version, "S1", [1], "keep")
        same()
        team.rename(li, "李老师")  # A name and a sample elsewhere affect this recording too.
        same()
        decide(team, mixed, "S2", "confirm", li, sample=True)
        same()
        team.dispute(mixed, "S1", {zhang})
        same()
        assert queue.get(scope)["items"]
        decide(team, mixed, "S1", "confirm", li)
        same()
        team.merge(zhang, li)
        same()
        library.delete(mixed)
        same()
    finally:
        queue.close()


def test_warm_reads_share_work_and_keep_permission_scopes_and_responses_separate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = Library(tmp_path / "library")
    rec = meeting(library)
    queue = ReviewQueue(library)
    calls: list[set[str]] = []
    build = queue._build

    def counted(scope: set[str]) -> dict[str, Any]:
        calls.append(scope)
        return build(scope)

    monkeypatch.setattr(queue, "_build", counted)
    try:
        expected = original_queue(library, {rec})
        response = queue.get({rec})
        response["heard"]["total"] = -1
        with ThreadPoolExecutor(max_workers=4) as pool:
            assert all(value == expected for value in pool.map(queue.get, [{rec}] * 8))
        assert calls == [{rec}]
        assert queue.get(set()) == original_queue(library, set())
        assert calls == [{rec}, set()]
        assert queue.get({rec}) == expected
        assert len(calls) == 2
    finally:
        queue.close()


def test_external_commits_invalidate_but_rolled_back_changes_do_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library, _, earlier, mixed, _, _ = library_with_mixed_speaker(tmp_path)
    Reviews(library).run(mixed, Voices(VOICES))
    scope = {earlier, mixed}
    queue = ReviewQueue(library)
    calls = 0
    build = queue._build

    def counted(scope: set[str]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return build(scope)

    monkeypatch.setattr(queue, "_build", counted)
    try:
        before = queue.get(scope)
        with sqlite3.connect(library.db_path) as external:
            external.execute("UPDATE reviewed SET error = 'retry'")
            external.rollback()
            assert queue.get(scope) == before
            assert calls == 1
            external.execute("UPDATE reviewed SET error = 'retry'")
        after = queue.get(scope)
        assert after == original_queue(library, scope) and after != before
        assert calls == 2
    finally:
        queue.close()


def test_a_commit_during_computation_is_not_cached(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library = Library(tmp_path / "library")
    rec = meeting(library)
    queue = ReviewQueue(library)
    started, resume = threading.Event(), threading.Event()
    calls = 0
    build = queue._build

    def paused(scope: set[str]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        result = build(scope)
        if calls == 1:
            started.set()
            assert resume.wait(5)
        return result

    monkeypatch.setattr(queue, "_build", paused)
    try:
        with ThreadPoolExecutor(max_workers=1) as pool:
            first = pool.submit(queue.get, {rec})
            assert started.wait(5)
            Team(library).add_person("新同事")
            resume.set()
            first.result(timeout=5)
        assert queue.get({rec}) == original_queue(library, {rec})
        assert calls == 2
        queue.get({rec})
        assert calls == 2
    finally:
        resume.set()
        queue.close()


def test_replacing_the_database_or_reopening_the_cache_cannot_reuse_an_old_reading(tmp_path: Path) -> None:
    library = Library(tmp_path / "library")
    rec = meeting(library)
    with sqlite3.connect(library.db_path) as db:
        db.execute("PRAGMA journal_mode=DELETE")
    queue = ReviewQueue(library)
    try:
        assert queue.get({rec})["fragments"]
        other = Library(tmp_path / "other")
        with sqlite3.connect(other.db_path) as db:
            db.execute("PRAGMA journal_mode=DELETE")
        other.db_path.replace(library.db_path)
        assert queue.get({rec}) == original_queue(library, {rec})
        assert queue.get({rec})["voices"] == []
        queue.close()
        assert queue.get({rec})["voices"] == []
    finally:
        queue.close()


def test_no_dispute_skips_candidate_matching(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library = Library(tmp_path / "library")
    meeting(library)

    def unnecessary(*args: Any) -> Any:
        pytest.fail("No disputed speaker needs matching")

    monkeypatch.setattr(Team, "speakers", unnecessary)
    assert Team(library).review(disputed_only=True) == []


def test_disputed_speakers_are_matched_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    earlier, rec = meeting(library, "一.m4a"), meeting(library, "二.m4a")
    zhang = team.add_person("张总")
    decide(team, earlier, "S1", "confirm", zhang.id, sample=True)
    decide(team, rec, "S1", "confirm", zhang.id)
    team.dispute(rec, "S1", {zhang.id})
    full = [entry for entry in team.review({rec}) if entry["disputed"]]
    matched: list[list[float]] = []
    suggest = Team._suggest

    def counted(embedding: list[float], *args: Any) -> Any:
        matched.append(list(embedding))
        return suggest(embedding, *args)

    monkeypatch.setattr(Team, "_suggest", staticmethod(counted))
    assert team.review({rec}, disputed_only=True) == full and len(full) == 1
    assert matched == [[1.0, 0.0, 0.0]]  # S1 alone, not the meeting's undecided S2 and S3.


def voice(key: str, seconds: float, **flags: bool) -> dict[str, Any]:
    return {"id": key, "seconds": seconds, "stranger": False, "enough": False, **flags}


def test_a_page_holds_the_first_of_each_list_and_how_many_each_holds() -> None:
    reading = {
        "heard": {"settled": 1.0, "total": 9.0},
        "items": [{"id": "S1"}, {"id": "S2"}],
        # As ``Team.voices`` sorts them: those asked first, then those surely of someone heard enough, then strangers.
        "voices": [
            voice("a", 30),
            voice("b", 20),
            voice("c", 10.25),
            voice("d", 50, enough=True),
            voice("e", 40, enough=True),
            voice("f", 5, stranger=True, enough=True),
        ],
        "fragments": [{"speaker_id": "S9"}],
        "unsorted": [{"recording_id": "r1"}, {"recording_id": "r2"}, {"recording_id": "r3"}],
        "suspects": [],
    }
    before = deepcopy(reading)
    paged = page(reading, {"voices": 2, "enough": 1, "strangers": 0, "items": 1, "unsorted": 5, "suspects": 3})
    assert [v["id"] for v in paged["voices"]] == ["a", "b", "d"]
    assert paged["items"] == [{"id": "S1"}] and len(paged["unsorted"]) == 3 and paged["suspects"] == []
    # Fragments are one task, settled together: always whole.
    assert paged["fragments"] == reading["fragments"] and paged["heard"] == reading["heard"]
    assert paged["totals"] == {
        "voices": {"count": 3, "seconds": 60.2},
        "enough": {"count": 2, "seconds": 90},
        "strangers": {"count": 1, "seconds": 5},
        "items": {"count": 2},
        "unsorted": {"count": 3},
        "suspects": {"count": 0},
    }
    whole = page(reading, dict.fromkeys(PAGED))
    assert whole == {**reading, "totals": paged["totals"]} and reading == before


def test_summary_matches_details_without_constructing_unit_views(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from twin.media import review as module

    library, _, earlier, mixed, _, _ = library_with_mixed_speaker(tmp_path)
    reviews = Reviews(library)
    reviews.run(mixed, Voices(VOICES))
    transcript, version = revision(library, mixed)
    reviews.fix(mixed, transcript, version, "S1", [1], "keep")
    expected = [view.model_copy(update={"units": []}) for view in reviews.suspects(units=True)]

    def unnecessary(*args: Any, **kwargs: Any) -> Any:
        pytest.fail("A queue summary must not construct detailed stretches")

    monkeypatch.setattr(module, "UnitView", unnecessary)
    assert reviews.suspects() == expected
    assert reviews.suspects({earlier}) == []


def test_batched_summary_scores_match_scalar_and_defer_boundaries() -> None:
    import numpy as np

    from twin.media.review import MARGIN, STRANGER, _summary_scores, _unit

    rng = np.random.default_rng(42)
    matrix = _unit(rng.normal(size=(7, 16)))
    owners = np.array([0, 0, 1, 1, 2, 2, 2])
    blobs = [row.astype(np.float32).tobytes() for row in rng.normal(size=(530, 16))]
    found = _summary_scores([*blobs, None, b"bad"], matrix, owners, 3, 0)
    assert len(found) == len(blobs)
    assert _summary_scores([b""], np.zeros((1, 0)), np.array([0]), 1, 0) == {}
    for index, best in found.items():
        vector = _unit(np.frombuffer(blobs[index], dtype=np.float32).astype(np.float64))
        expected = np.full(3, -1.0)
        np.maximum.at(expected, owners, matrix @ vector)
        np.testing.assert_allclose(best, expected, atol=1e-12)
    # A tie for the likely person or a verdict boundary must use the original scalar arithmetic.
    blob = np.array([1.0, 0.0], dtype=np.float32).tobytes()
    for scores in ([0.0, MARGIN], [STRANGER, 0.0], [0.0, 0.8, 0.8]):
        samples = np.array([[score * (1 + 1e-9), 0.0] for score in scores])
        assert _summary_scores([blob], samples, np.arange(len(scores)), len(scores), 0) == {}
