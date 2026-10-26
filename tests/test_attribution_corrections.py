"""A withdrawn voice sample must not leave its automatic decisions in a rebuilt twin."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from test_team import decide, recording

from twin.config import Settings
from twin.media import attribution, recollect
from twin.media.ingest import Segment, Speaker
from twin.media.library import TEAM, Library
from twin.media.team import Team
from twin.persona import gate
from twin.persona.store import PersonaStore
from twin.web.library import Libraries


def spoken(library: Library, name: str, text: str, vector: list[float] | None = None) -> str:
    return recording(
        library,
        name,
        [Segment(start=0, end=60, text=text, speaker="S1")],
        [Speaker(id="S1", seconds=60, embedding=vector or [1.0, 0.0, 0.0])],
    )


def test_deleting_a_sample_recording_removes_dependent_speech_from_the_next_build(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "twin.db")
    registry = MagicMock()
    libraries = Libraries(settings, MagicMock(), registry)
    library, pid = libraries.library(TEAM), "synthetic-twin"
    team = Team(library)
    person = team.add_person("合成同事")
    basis = spoken(library, "sample.wav", "提供原始声纹。")
    dependent = spoken(library, "dependent.wav", "错误归属不应在重建后回来。")
    manual = spoken(library, "manual.wav", "人工确认仍然保留。")
    other_basis = spoken(library, "another-sample.wav", "另一份有效声纹。")
    decide(team, basis, "S1", "confirm", person.id, sample=True)
    assert team.classify(dependent) == 1
    decide(team, manual, "S1", "confirm", person.id)
    decide(team, other_basis, "S1", "confirm", person.id, sample=True)
    team.link(person.id, pid)
    target = settings.model_copy(update={"db_path": tmp_path / "personas" / pid / "twin.db"})
    registry.settings_for.return_value = target
    registry.entry.return_value = {"id": pid}
    with PersonaStore(target.db_path) as store:
        store.set_meta("identity:name", person.name)
        gate.link(store, library.db_path, pid)
    assert libraries.write_sources(TEAM, pid)
    assert team.built(pid, 1)
    assert gate.version_at(target.db_path) == 1

    assert library.delete(basis)
    current = library.get(dependent)
    assert current is not None
    [withdrawn] = team.speakers(current)
    assert withdrawn.decision == "none" and withdrawn.person_id is None
    assert team.classify_all() == 0  # Another valid sample cannot silently restore the withdrawn decision.
    assert {s.title for s in team.sources(person.id, person.name)} == {"manual", "another-sample"}
    with pytest.raises(gate.MemoryUpdating):
        gate.version_at(target.db_path)
    # A held rebuild cannot keep answering from the removed recordings by treating the correction as additions.
    settings.library.auto_build = False
    assert libraries.write_sources(TEAM, pid) is False
    with pytest.raises(gate.MemoryUpdating):
        gate.version_at(target.db_path)
    settings.library.auto_build = True
    assert libraries.write_sources(TEAM, pid)
    wanted = team.wanted(pid)
    assert wanted is not None and team.built(pid, wanted)
    with PersonaStore(target.db_path) as store:
        assert gate.version(store) == wanted
        own = [e.text for e in store.list_expressions() if e.is_target]
    assert not any("错误归属" in text for text in own)
    assert any("人工确认仍然保留" in text for text in own)
    assert library.delete(basis)  # Repeating deletion is still harmless.


def test_sample_withdrawal_and_recording_deletion_rollback_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    person = team.add_person("合成同事")
    basis = spoken(library, "sample.wav", "原始样本。")
    dependent = spoken(library, "dependent.wav", "自动归属。")
    decide(team, basis, "S1", "confirm", person.id, sample=True)
    assert team.classify(dependent) == 1
    team.link(person.id, "synthetic-twin")
    assert team.built("synthetic-twin", 1)
    before = team.synced()
    withdraw = attribution.withdraw_samples

    def fail_after_withdraw(db: Any, samples: set[int]) -> int:
        assert withdraw(db, samples) == 1
        raise OSError("synthetic failure after withdrawal")

    monkeypatch.setattr(attribution, "withdraw_samples", fail_after_withdraw)
    with pytest.raises(OSError, match="synthetic failure"):
        library.delete(basis)
    assert library.get(basis) is not None and library.folder(basis).is_dir()
    current = library.get(dependent)
    assert current is not None
    assert team.speakers(current)[0].decision == "confirmed"
    assert team.synced() == before and len(team.samples(person.id)) == 1


def test_deleting_a_recording_without_samples_keeps_manual_decisions_elsewhere(tmp_path: Path) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    person = team.add_person("合成同事")
    removed = spoken(library, "removed.wav", "只删除这场。")
    kept = spoken(library, "kept.wav", "这场仍然保留。")
    decide(team, removed, "S1", "confirm", person.id)
    decide(team, kept, "S1", "confirm", person.id)
    assert library.delete(removed) and library.delete(removed)
    current = library.get(kept)
    assert current is not None
    assert team.speakers(current)[0].decision == "confirmed"
    assert len(team.sources(person.id, person.name)) == 1


@pytest.mark.parametrize("change", ["remove", "delete", "merge"])
def test_sample_settlement_cannot_overwrite_concurrent_corrections(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    person = team.add_person("合成同事")
    corrected = team.add_person("另一位同事")
    basis = spoken(library, "sample.wav", "旧版本留下的样本。")
    dependent = spoken(library, "dependent.wav", "自动归属。")
    decide(team, basis, "S1", "confirm", person.id, sample=True)
    assert team.classify(dependent) == 1
    [sample] = team.samples(person.id)
    # Earlier versions could leave an active sample attached to the preceding transcript after retranscription.
    with library.transaction() as db:
        db.execute("UPDATE voiceprints SET transcript_id = 'older' WHERE id = ?", (sample.id,))
    original_speakers = library.speakers
    # A separately opened library has a different Python lock and always uses independent SQLite connections.
    other_library = Library(library.root)
    other_team = Team(other_library)
    removed = False
    with ThreadPoolExecutor(max_workers=1) as pool:

        def speakers(recording: Any) -> Any:
            nonlocal removed
            result = original_speakers(recording)
            if not removed:
                # Settlement has read the sample list, but has not taken its write transaction yet.
                if change == "remove":
                    assert pool.submit(other_team.remove_sample, person.id, sample.id).result(timeout=5) == 1
                elif change == "delete":
                    assert pool.submit(other_library.delete, basis).result(timeout=5)
                else:
                    pool.submit(other_team.merge, person.id, corrected.id).result(timeout=5)
                removed = True
            return result

        monkeypatch.setattr(library, "speakers", speakers)
        assert recollect.settle_samples(library) == (0, 0)
    assert removed and team.samples(person.id) == []
    if change == "merge":
        assert [s.id for s in other_team.samples(corrected.id)] == [sample.id]
    later = spoken(library, "later.wav", "这段不能再凭已移除的样本认领。")
    team.classify(later)
    current = library.get(later)
    assert current is not None and team.speakers(current)[0].person_id != person.id


def test_retiring_a_sample_left_on_an_old_transcript_withdraws_its_dependents(tmp_path: Path) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    person = team.add_person("合成同事")
    basis = spoken(library, "sample.wav", "旧样本。")
    dependent = spoken(library, "dependent.wav", "不再有可靠样本支持的自动归属。")
    decide(team, basis, "S1", "confirm", person.id, sample=True)
    assert team.classify(dependent) == 1
    [sample] = team.samples(person.id)
    # The current speaker now sounds unlike the sample an older service measured. No safe successor exists.
    with library.transaction() as db:
        db.execute(
            "UPDATE voiceprints SET transcript_id = 'older', embedding = '[0.0, 1.0, 0.0]' WHERE id = ?", (sample.id,)
        )
    team.link(person.id, "synthetic-twin")
    assert team.built("synthetic-twin", 1)
    before = library.get(dependent)
    assert before is not None
    assert recollect.settle_samples(library) == (0, 1)
    current = library.get(dependent)
    assert current is not None
    assert team.speakers(current)[0].decision == "none"
    assert current.revision > before.revision
    assert team.wanted("synthetic-twin") != 1
    assert not any(source.title == "dependent" for source in team.sources(person.id, person.name))


@pytest.mark.parametrize("removal", ["remove", "delete"])
@pytest.mark.parametrize("moved_sample", [False, True])
def test_rollback_cannot_restore_dependencies_of_a_withdrawn_sample(
    tmp_path: Path, removal: str, moved_sample: bool
) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    person = team.add_person("合成同事")
    basis = spoken(library, "sample.wav", "原始样本。")
    dependent = spoken(library, "dependent.wav", "旧错误归属不能随转写回退复活。")
    decide(team, basis, "S1", "confirm", person.id, sample=True)
    assert team.classify(dependent) == 1
    [original_sample] = team.samples(person.id)

    # Exercise the real atomic transcript switch and sample-id remapping without invoking a codec or model.
    for rec in [basis, dependent] if moved_sample else [dependent]:
        before = library.get(rec)
        assert before is not None
        old = library.transcript(before)
        assert old is not None
        new = old.model_copy(update={"id": f"new-{rec}"})
        Library.write_transcript(library.folder(rec), new)
        recollect._switch(library, before, old, new)
        team.classify(rec)
    [current_sample] = team.samples(person.id)
    assert (current_sample.id != original_sample.id) is moved_sample
    with library.read() as db:
        rows = db.execute(
            "SELECT sample FROM attributions WHERE recording_id = ? AND decision = 'confirmed'", (dependent,)
        ).fetchall()
    assert len(rows) == 2 and all(row[0] == current_sample.id for row in rows)
    team.link(person.id, "synthetic-twin")
    assert team.built("synthetic-twin", 1)
    if removal == "remove":
        # Historical automatic rows are also cleared, but the user still sees one current speaker returned.
        assert team.remove_sample(person.id, current_sample.id) == 1
    else:
        assert library.delete(basis)
    current = library.get(dependent)
    assert current is not None and team.speakers(current)[0].decision == "none"
    assert recollect.rollback(library, dependent)
    previous = library.get(dependent)
    assert previous is not None and team.speakers(previous)[0].decision == "none"
    assert not any(source.title == "dependent" for source in team.sources(person.id, person.name))
    with library.read() as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM attributions WHERE recording_id = ? AND decision = 'confirmed'", (dependent,)
            ).fetchone()[0]
            == 0
        )
    if moved_sample and removal == "remove":
        assert recollect.rollback(library, basis)
        assert team.samples(person.id) == []  # The predecessor cannot resurrect a manually removed sample.


def test_rollback_withdraws_decisions_from_samples_first_taken_on_the_new_transcript(tmp_path: Path) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    person = team.add_person("合成同事")
    basis = spoken(library, "sample.wav", "之前没有取声纹。")
    dependent = spoken(library, "dependent.wav", "新样本造成的自动归属。")
    decide(team, basis, "S1", "confirm", person.id)
    before = library.get(basis)
    assert before is not None
    old = library.transcript(before)
    assert old is not None
    new = old.model_copy(update={"id": "new-transcript"})
    Library.write_transcript(library.folder(basis), new)
    recollect._switch(library, before, old, new)
    decide(team, basis, "S1", "confirm", person.id, sample=True)
    assert team.classify(dependent) == 1
    assert recollect.rollback(library, basis)
    assert team.samples(person.id) == []
    current = library.get(dependent)
    assert current is not None and team.speakers(current)[0].decision == "none"
    assert not any(source.title == "dependent" for source in team.sources(person.id, person.name))


def legacy_sample_dependency(tmp_path: Path, state: str) -> tuple[Library, Team, str, str, str, int]:
    """A previous transcript already holding an unsupported claim from an older release, without new withdrawal."""
    library = Library(tmp_path / "library")
    team = Team(library)
    person = team.add_person("合成同事")
    basis = spoken(library, "sample.wav", "原始样本。")
    dependent = spoken(library, "dependent.wav", "旧错误归属不能在回退后进入本人资料。")
    manual = spoken(library, "manual.wav", "人工确认保留。")
    decide(team, basis, "S1", "confirm", person.id, sample=True)
    assert team.classify(dependent) == 1
    decide(team, manual, "S1", "confirm", person.id)
    [sample] = team.samples(person.id)
    if state == "manual":
        decide(team, dependent, "S1", "confirm", person.id)
    before = library.get(dependent)
    assert before is not None
    old = library.transcript(before)
    assert old is not None
    new = old.model_copy(update={"id": "legacy-new-transcript"})
    Library.write_transcript(library.folder(dependent), new)
    recollect._switch(library, before, old, new)
    # Simulate the old database as found on the read-only audit: no call to new remove/withdraw code has run.
    with library.transaction() as db:
        if state == "missing":
            db.execute("DELETE FROM voiceprints WHERE id = ?", (sample.id,))
        elif state in {"inactive", "manual"}:
            db.execute("UPDATE voiceprints SET active = 0 WHERE id = ?", (sample.id,))
        elif state == "without_sample":
            db.execute(
                "UPDATE attributions SET sample = NULL, tier = 'new' WHERE recording_id = ? AND transcript_id = ?",
                (dependent, old.id),
            )
    team.link(person.id, "synthetic-twin")
    assert team.built("synthetic-twin", 1)
    return library, team, basis, dependent, person.id, sample.id


@pytest.mark.parametrize("state", ["missing", "inactive", "active", "without_sample", "manual"])
def test_rollback_validates_legacy_archived_samples_without_overriding_valid_or_manual_decisions(
    tmp_path: Path, state: str
) -> None:
    library, team, _, dependent, person, _ = legacy_sample_dependency(tmp_path, state)
    assert recollect.rollback(library, dependent)
    current = library.get(dependent)
    assert current is not None
    [speaker] = team.speakers(current)
    if state in {"missing", "inactive"}:
        assert speaker.decision == "none" and speaker.person_id is None
        assert "dependent" not in {s.title for s in team.sources(person, "合成同事")}
    else:
        assert speaker.decision == "confirmed" and speaker.person_id == person
        assert "dependent" in {s.title for s in team.sources(person, "合成同事")}
    assert "manual" in {s.title for s in team.sources(person, "合成同事")}
    assert team.wanted("synthetic-twin") != 1


@pytest.mark.parametrize("state", ["missing", "inactive"])
def test_rollback_and_legacy_dependency_cleanup_fail_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, state: str
) -> None:
    library, team, _, dependent, _, sample = legacy_sample_dependency(tmp_path, state)
    before, synced = library.get(dependent), team.synced()
    assert before is not None and before.previous is not None
    withdraw = attribution.withdraw_samples

    def fail_after_cleanup(db: Any, samples: set[int]) -> int:
        count = withdraw(db, samples)
        if sample in samples:
            raise OSError("synthetic failure after archived cleanup")
        return count

    monkeypatch.setattr(attribution, "withdraw_samples", fail_after_cleanup)
    with pytest.raises(OSError, match="synthetic failure"):
        recollect.rollback(library, dependent)
    assert library.get(dependent) == before
    assert team.synced() == synced
    with library.read() as db:
        assert (
            db.execute(
                "SELECT decision FROM attributions WHERE recording_id = ? AND transcript_id = ?",
                (dependent, before.previous),
            ).fetchone()[0]
            == "confirmed"
        )
        assert (
            db.execute("SELECT rolled_back FROM recollections WHERE recording_id = ?", (dependent,)).fetchone()[0] == 0
        )


def test_rollback_prunes_only_after_the_previous_transcript_is_current(tmp_path: Path) -> None:
    library = Library(tmp_path / "library")
    team = Team(library)
    origin = spoken(library, "original.wav", "应恢复的原始说话人。")
    assert team.classify(origin) == 1  # The old transcript's person is unnamed and eligible for pruning.
    before = library.get(origin)
    assert before is not None
    old = library.transcript(before)
    assert old is not None
    original_person = team.speakers(before)[0].person_id
    assert original_person is not None
    new = old.model_copy(
        update={
            "id": "new-transcript",
            "speakers": [s.model_copy(update={"embedding": [0.0, 1.0, 0.0]}) for s in old.speakers],
        }
    )
    Library.write_transcript(library.folder(origin), new)
    recollect._switch(library, before, old, new)
    assert team.classify(origin) == 1  # The new transcript gives a different unnamed person its own new sample.
    dependent = spoken(library, "dependent.wav", "新样本的自动归属应撤回。", [0.0, 1.0, 0.0])
    assert team.classify(dependent) == 1
    assert team.person(original_person) is not None

    # Rollback can interleave before the retranscription worker settles old samples. Pruning while the new
    # transcript is still current would mistake the original person, present only in previous, for an orphan.
    assert recollect.rollback(library, origin)
    current = library.get(origin)
    assert current is not None and current.transcript_id == old.id
    assert team.person(original_person) is not None
    assert team.speakers(current)[0].person_id == original_person
    assert [s.title for s in team.sources(original_person, "合成同事")] == ["original"]
    other = library.get(dependent)
    assert other is not None and team.speakers(other)[0].decision == "none"
