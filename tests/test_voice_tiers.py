"""How sure voice alone is of a speaker (``team.tier``), and the knobs being calibrated for the three tiers
(docs/PLAN_VOICE_COLLECTOR.md): one speaker per person and recording, and which samples are matched."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_team import decide, voices

from twin.media import team as team_module
from twin.media.library import Library
from twin.media.team import Candidate, Team, tier


def candidates(*scores: float) -> list[Candidate]:
    return [Candidate(person_id=f"p{i}", name=f"p{i}", score=score) for i, score in enumerate(scores)]


def test_tiers_follow_the_lead_over_the_runner_up(monkeypatch: pytest.MonkeyPatch) -> None:
    # The rule before tiers: very close, far ahead of the runner-up, and long enough.
    assert tier(candidates(0.8, 0.5), 0.5, 30) == "high"
    assert tier(candidates(0.8, 0.7), 0.7, 30) == "low"
    assert tier(candidates(0.8), 0.0, 10) == "low"
    assert tier([], 0.0, 300) == "low"
    # The runner-up counts however low it is, so a lead is measured against whoever comes second.
    assert tier(candidates(0.76), 0.62, 30) == "low"
    monkeypatch.setattr(team_module, "MID_MARGIN", 0.1)
    assert tier(candidates(0.7, 0.55), 0.55, 30) == "mid"
    assert tier(candidates(0.7, 0.65), 0.65, 30) == "low"
    assert tier(candidates(0.55), 0.3, 30) == "low"  # Below MID_FLOOR.
    assert tier(candidates(0.8), 0.0, 10) == "mid"  # Sure, but too short to take alone.


def two_people(tmp_path: Path) -> tuple[Library, Team, str, str]:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = voices(library, "一.m4a", ([1.0, 0.0, 0.0], 120), ([0.0, 1.0, 0.0], 90))
    zhang, li = team.add_person("张总"), team.add_person("李总")
    decide(team, first, "S1", "confirm", zhang.id, sample=True)
    decide(team, first, "S2", "confirm", li.id, sample=True)
    return library, team, zhang.id, li.id


def test_undecided_speakers_get_a_tier_and_whom_it_is_of(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library, team, zhang, li = two_people(tmp_path)
    monkeypatch.setattr(team_module, "MID_MARGIN", 0.1)
    second = voices(library, "二.m4a", ([0.97, 0.05, 0.0], 100), ([0.6, 0.0, 0.8], 40), ([0.5, 0.5, 0.7], 40))
    recording = library.get(second)
    assert recording is not None
    found = {
        sid: (level, c.person_id if c else None, lead) for sid, (level, c, lead) in team.voice_tiers(recording).items()
    }
    assert found == {"S1": ("high", zhang, 0.948), "S2": ("mid", zhang, 0.6), "S3": ("low", zhang, 0.0)}
    # A speaker denied to be 张总 is not offered 张总 again; a decided one has no tier.
    decide(team, second, "S2", "reject", zhang)
    decide(team, second, "S3", "confirm", li)
    recording = library.get(second)
    assert recording is not None
    assert {sid: level for sid, (level, _, _) in team.voice_tiers(recording).items()} == {"S1": "high", "S2": "low"}


def test_one_speaker_per_person_and_recording_by_voice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library, team, zhang, _ = two_people(tmp_path)
    # Two speakers both sound like 张总: diarization split them, or one of them is someone else in the same room.
    second = voices(library, "二.m4a", ([0.97, 0.05, 0.0], 100), ([0.95, 0.0, 0.2], 60))
    monkeypatch.setattr(team_module, "ONE_PER_RECORDING", 1.0)
    assert team.classify(second) == 1
    recording = library.get(second)
    assert recording is not None
    view = {s.id: (s.decision, s.person_id, s.auto) for s in team.speakers(recording)}
    assert view["S1"] == ("confirmed", zhang, True) and view["S2"][0] == "none"
    assert {sid: level for sid, (level, _, _) in team.voice_tiers(recording).items()} == {"S2": "mid"}
    # Without the rule, both are taken.
    third = voices(library, "三.m4a", ([0.97, 0.05, 0.0], 100), ([0.95, 0.0, 0.2], 60))
    monkeypatch.setattr(team_module, "ONE_PER_RECORDING", 0.0)
    assert team.classify(third) == 2


def test_samples_matched_can_be_capped_chosen_and_averaged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    zhang = team.add_person("张总")
    # Four samples of 张总 from four rooms: the first short, two long and alike, two unlike the others.
    for name, vector, seconds in (
        ("一.m4a", [1.0, 0.0, 0.0], 30),
        ("二.m4a", [0.0, 1.0, 0.0], 300),
        ("三.m4a", [0.0, 0.99, 0.14], 200),
        ("四.m4a", [0.0, 0.0, 1.0], 100),
    ):
        recording = voices(library, name, (vector, seconds))
        decide(team, recording, "S1", "confirm", zhang.id, sample=True)

    def kept() -> list[list[float]]:
        with library.read() as db:
            return [vector for _, _, vector in team._prints(db)]

    assert len(kept()) == 4
    monkeypatch.setattr(team_module, "SAMPLE_CAP", 2.0)
    assert kept() == [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]]  # The earliest.
    monkeypatch.setattr(team_module, "SAMPLE_PICK", 1.0)
    assert kept() == [[0.0, 1.0, 0.0], [0.0, 0.99, 0.14]]  # The longest.
    monkeypatch.setattr(team_module, "SAMPLE_PICK", 2.0)
    assert kept() == [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]  # The longest, then the longest of the most unlike it.

    monkeypatch.setattr(team_module, "SAMPLE_CAP", 0.0)
    with library.read() as db:
        prints = team._prints(db)
    assert [c.score for c in Team._match([0.0, 1.0, 0.0], prints, set(), floor=-1.0)] == [1.0]
    monkeypatch.setattr(team_module, "SCORE_TOP", 2.0)
    assert [c.score for c in Team._match([0.0, 1.0, 0.0], prints, set(), floor=-1.0)] == [0.995]
