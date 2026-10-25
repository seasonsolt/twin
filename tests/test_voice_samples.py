"""Voice samples as the attribution layer keeps them (docs/PLAN_VOICE_COLLECTOR.md 3b): voices the owner could not
name as rivals, what each automatic decision records, how a sample is taken and how it fares, what happens to the
speakers it gave once it no longer stands, and the hint when tagging a voice that sounds like someone else."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_team import decide, voices, wanted_done

from twin.media import team as team_module
from twin.media.library import Library
from twin.media.team import Team

ZHANG = [1.0, 0.0, 0.0]
LI = [0.0, 1.0, 0.0]
STRANGER = [0.0, 0.0, 1.0]
# 0.729 like 张总, 0.104 like 李总, 0.677 like the stranger.
BETWEEN = [0.7, 0.1, 0.65]


def two_people(tmp_path: Path) -> tuple[Library, Team, str, str, str]:
    """张总 and 李总, a sample each from the first recording, whose third voice the owner has not decided."""
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    first = voices(library, "一.m4a", (ZHANG, 120), (LI, 90), (STRANGER, 60))
    zhang, li = team.add_person("张总"), team.add_person("李总")
    decide(team, first, "S1", "confirm", zhang.id, sample=True)
    decide(team, first, "S2", "confirm", li.id, sample=True)
    return library, team, first, zhang.id, li.id


def attribution(library: Library, recording_id: str, speaker_id: str) -> dict[str, object]:
    with library.read() as db:
        row = db.execute(
            "SELECT decision, person_id, auto, version, tier, score, lead, sample, suggest FROM attributions "
            "WHERE recording_id = ? AND speaker_id = ?",
            (recording_id, speaker_id),
        ).fetchone()
    return dict(row)


def sample_of(library: Library, recording_id: str, speaker_id: str) -> tuple[int, str | None, int, int]:
    with library.read() as db:
        row = db.execute(
            "SELECT id, source, corrected, active FROM voiceprints WHERE recording_id = ? AND speaker_id = ?",
            (recording_id, speaker_id),
        ).fetchone()
    return int(row[0]), row[1], int(row[2]), int(row[3])


def test_a_voice_the_owner_could_not_name_is_a_rival(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library, team, first, zhang, _ = two_people(tmp_path)
    # The stranger in the same recording does not count: diarization already told the voices apart there.
    third = voices(library, "三.m4a", (BETWEEN, 100), (STRANGER, 60))
    decide(team, third, "S2", "unknown")
    assert team.classify(third) == 1
    sample, source, _, _ = sample_of(library, first, "S1")
    assert source == "speaker"
    # The decision says how sure the voice was, by how much, and which sample recognised it.
    assert attribution(library, third, "S1") == {
        "decision": "confirmed",
        "person_id": zhang,
        "auto": 1,
        "version": "attribution-v3",
        "tier": "high",
        "score": 0.729,
        "lead": 0.625,
        "sample": sample,
        "suggest": None,
    }
    # In another recording it does: 张总 leads the stranger by 0.052 only, so the owner is offered 张总 to confirm.
    decide(team, first, "S3", "unknown")
    second = voices(library, "二.m4a", (BETWEEN, 100))
    assert team.classify(second) == 0
    recording = library.get(second)
    assert recording is not None
    [(level, best, lead)] = team.voice_tiers(recording).values()
    assert (level, best.person_id if best else None, lead) == ("mid", zhang, 0.052)
    monkeypatch.setattr(team_module, "STRANGER_RIVALS", 0.0)
    assert team.classify(second) == 1


def test_speakers_given_by_a_sample_that_no_longer_stands_go_back_to_the_owner(tmp_path: Path) -> None:
    library, team, first, zhang, _ = two_people(tmp_path)
    # A second sample of 张总, from another room.
    other = voices(library, "其他.m4a", ([0.9, 0.0, 0.436], 80))
    decide(team, other, "S1", "confirm", zhang, sample=True)
    second = voices(library, "二.m4a", ([0.97, 0.05, 0.0], 100))
    assert team.classify(second) == 1
    taken = sample_of(library, first, "S1")[0]
    assert attribution(library, second, "S1")["sample"] == taken
    team.link(zhang, "p-zhang")
    team.built("p-zhang", 1)
    wanted = wanted_done(library, "p-zhang")[0]

    # The owner hears that the first recording's speaker was nobody they know: that sample stands no more, and what
    # it gave 张总 waits for the owner, offered to 张总, rather than staying 张总's or being dropped.
    decide(team, first, "S1", "unknown")
    row = attribution(library, second, "S1")
    assert (row["decision"], row["person_id"], row["suggest"], row["tier"]) == ("none", None, zhang, "mid")
    assert wanted_done(library, "p-zhang")[0] > wanted
    recording = library.get(second)
    assert recording is not None
    # Still most like 张总's other sample, but never taken again by voice alone.
    [(level, best, _)] = team.voice_tiers(recording).values()
    assert (level, best.person_id if best else None) == ("mid", zhang)
    assert team.classify(second) == 0
    [voice], _ = team.voices({second})
    assert voice.candidates[0].person_id == zhang
    # The owner confirms it.
    decide(team, second, "S1", "confirm", zhang)
    assert attribution(library, second, "S1")["decision"] == "confirmed"


def test_a_sample_the_owner_keeps_correcting_stops_standing(tmp_path: Path) -> None:
    library, team, first, zhang, li = two_people(tmp_path)
    decide(team, first, "S3", "unknown")
    claimed = [voices(library, f"{n}.m4a", ([0.97, 0.05, 0.0], 100)) for n in "二三四五"]
    assert team.classify_all() == 4
    sample = sample_of(library, first, "S1")[0]
    assert all(attribution(library, r, "S1")["sample"] == sample for r in claimed)
    # The owner gives three of the four to 李总: each counts against the sample.
    for count, recording_id in enumerate(claimed[:2], start=1):
        decide(team, recording_id, "S1", "confirm", li)
        assert sample_of(library, first, "S1")[2:] == (count, 1)
    decide(team, claimed[2], "S1", "confirm", li)
    # Corrected three times, more than it still gives: it stops standing, and its last claim goes back to the owner.
    assert sample_of(library, first, "S1")[2:] == (3, 0)
    row = attribution(library, claimed[3], "S1")
    assert (row["decision"], row["suggest"]) == ("none", zhang)
    # The owner's own decision about the sample's speaker is unchanged.
    assert attribution(library, first, "S1")["person_id"] == zhang


def test_how_each_sample_was_taken_is_recorded(tmp_path: Path) -> None:
    library, team, first, _, _ = two_people(tmp_path)
    assert sample_of(library, first, "S2")[1] == "speaker"
    a = voices(library, "二.m4a", ([0.0, 0.6, 0.8], 90))
    b = voices(library, "三.m4a", ([0.0, 0.6, 0.8], 70))
    [voice], _ = team.voices({a, b})
    members = [(m.recording_id, m.transcript_id, m.speaker_id) for m in voice.members]
    wang = team.add_person("王总")
    team.decide_voice(members, "confirm", wang.id)
    assert {sample_of(library, r, "S1")[1] for r in (a, b)} == {"voice"}
    # A long voice matching nobody becomes an unnamed person, kept by that voice.
    new = voices(library, "四.m4a", ([-1.0, 0.0, 0.0], 120))
    assert team.classify(new) == 1
    assert sample_of(library, new, "S1")[1] == "new"
    assert attribution(library, new, "S1")["tier"] == "new"


def test_tagging_a_voice_that_sounds_like_someone_else_says_so(tmp_path: Path) -> None:
    library, team, _, zhang, li = two_people(tmp_path)
    second = voices(library, "二.m4a", ([0.2, 0.98, 0.0], 100), ([0.98, 0.2, 0.0], 100), ([0.6, 0.0, 0.8], 100))
    hint = team.unlike([(second, "S1")], zhang)
    assert hint is not None and (hint.person_id, hint.score) == (li, 0.98)
    assert team.unlike([(second, "S1")], li) is None
    assert team.unlike([(second, "S2")], zhang) is None
    # Someone with no samples yet: only a voice surely someone else's is said.
    wang = team.add_person("王总").id
    assert team.unlike([(second, "S1")], wang) is not None
    assert team.unlike([(second, "S3")], wang) is None


def test_voices_heard_in_more_recordings_are_asked_first(tmp_path: Path) -> None:
    library = Library(tmp_path / "library" / "team")
    team = Team(library)
    long = voices(library, "一.m4a", (ZHANG, 100))
    often = [voices(library, f"{n}.m4a", (STRANGER, 30)) for n in "二三"]
    listed, _ = team.voices()
    assert [{m.recording_id for m in v.members} for v in listed] == [set(often), {long}]


def test_a_person_s_samples_and_what_voice_alone_gave_them_least_sure_first(tmp_path: Path) -> None:
    library, team, first, zhang, _ = two_people(tmp_path)
    decide(team, first, "S3", "unknown")
    sure = voices(library, "二.m4a", ([0.97, 0.05, 0.0], 100))
    unsure = voices(library, "三.m4a", ([0.75, 0.55, 0.37], 60))
    assert team.classify_all() == 2
    checks = team.checks(zhang)
    assert [c.recording_id for c in checks] == [unsure, sure]
    assert checks[0].tier == "high" and checks[0].lead is not None and checks[0].lead < checks[1].lead  # type: ignore[operator]
    assert team.checks(zhang, {sure}) == checks[1:]
    assert [p.checks for p in team.people() if p.id == zhang] == [2]
    assert team.check_counts({sure}) == {zhang: 1}
    [sample] = team.samples(zhang)
    assert (sample.recording_id, sample.speaker_id, sample.source, sample.claims) == (first, "S1", "speaker", 2)

    # Removed, it recognises nobody; what it gave 张总 goes back to the owner with 张总 offered.
    assert team.remove_sample(zhang, sample.id) == 2
    assert team.remove_sample(zhang, sample.id) is None
    assert team.samples(zhang) == [] and team.checks(zhang) == []
    assert attribution(library, first, "S1")["person_id"] == zhang  # The speaker it was taken from stays theirs.
    listed, _ = team.voices({sure, unsure})
    assert all(v.candidates == [] or v.candidates[0].person_id == zhang for v in listed)


def test_a_voice_offered_to_confirm_with_one_key_is_mid(tmp_path: Path) -> None:
    library, team, first, zhang, _ = two_people(tmp_path)
    decide(team, first, "S3", "unknown")
    # 0.65 like 张总, 0.58 like 李总: not enough of a lead to take alone, enough to offer 张总.
    second = voices(library, "二.m4a", ([0.65, 0.58, -0.49], 40))
    assert team.classify(second) == 0
    [voice], _ = team.voices({second})
    assert ([c.person_id for c in voice.candidates], voice.tier) == ([zhang], "mid")
    # 0.65 and 0.62: too close to tell, whoever is offered.
    close = voices(library, "近.m4a", ([0.65, 0.62, -0.44], 40))
    [voice], _ = team.voices({close})
    assert voice.tier == "low"
    # 0.65 like 张总 but 0.76 like the voice the owner could not name in the first recording: asked.
    third = voices(library, "三.m4a", ([0.65, 0.0, 0.76], 40))
    [voice], _ = team.voices({third})
    assert (voice.candidates[0].person_id, voice.tier) == (zhang, "low")
