"""Cache-only attribution evaluation: scoring, meeting isolation and explicit evidence boundaries."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from twin.evals.asr import _sha256
from twin.evals.asr_attribution import evaluate_attribution, run_attribution_benchmark, select_meetings
from twin.evals.asr_session import Run, Session
from twin.evals.diarization import Utterance
from twin.media.ingest import Speaker


def example(tmp_path: Path) -> tuple[Session, Run]:
    session = Session(
        "s1",
        tmp_path / "audio.wav",
        80,
        [Utterance(0, 32, "A"), Utterance(32, 80, "B")],
        {"A": tmp_path / "A.wav"},
    )
    run = Run(
        [Utterance(0, 40, "S1"), Utterance(40, 80, "S2")],
        [Speaker(id="S1", seconds=40, embedding=[1, 0]), Speaker(id="S2", seconds=40, embedding=[0, 1])],
        1,
    )
    return session, run


def test_majority_correct_cluster_still_has_other_peoples_time(tmp_path: Path) -> None:
    session, run = example(tmp_path)
    result = evaluate_attribution([session], {session.id: run}, {"A": [1, 0]})
    assert result["automatic_named_coverage"]["rate"] == 0.5
    # The majority label is A, but eight of the forty seconds are exclusively B's.
    assert result["automatic_wrong_cluster_seconds_proxy"] == 0
    assert result["automatic_other_only_fraction"]["rate"] == 0.2
    workload = result["workload_proxy"]
    assert workload["unresolved_speech"]["rate"] == 0.5
    assert workload["confirmation_questions"]["total"] == 1
    assert workload["actual_human_seconds"] is None


def test_meeting_order_cannot_teach_the_next_meeting_an_oracle_identity(tmp_path: Path) -> None:
    session, _ = example(tmp_path)
    first = replace(session, id="first", reference=[Utterance(0, 80, "B")])
    second = replace(session, id="second", reference=[Utterance(0, 80, "C")])
    run = Run([Utterance(0, 80, "S1")], [Speaker(id="S1", seconds=80, embedding=[0, 1])], 1)
    runs = {"first": run, "second": run}
    a = evaluate_attribution([first, second], runs, {"A": [1, 0]})
    b = evaluate_attribution([second, first], runs, {"A": [1, 0]})
    assert a["classify"] == b["classify"]
    assert a["classify"]["unknown"]["newperson"]["rate"] == 1
    # Automatically inventing an unnamed person is not identifying a known one.
    assert a["automatic_named_coverage"]["rate"] == 0
    assert a["automatic_other_only_fraction"]["rate"] is None
    assert a["new_unnamed_speech_fraction"]["rate"] == 1


def test_bootstrap_grouping_does_not_turn_questions_per_meeting_into_per_group(tmp_path: Path) -> None:
    session, run = example(tmp_path)
    first = replace(session, id="first", group="shared-room")
    second = replace(session, id="second", group="shared-room")
    result = evaluate_attribution([first, second], {"first": run, "second": run}, {"A": [1, 0]})
    questions = result["workload_proxy"]["confirmation_questions"]
    assert questions["total"] == 2
    assert questions["mean"] == 1 and questions["max"] == 1


def test_anonymous_person_is_not_recognition_even_when_gold_is_an_enrolled_person(tmp_path: Path) -> None:
    session, _ = example(tmp_path)
    session = replace(session, reference=[Utterance(0, 80, "A")])
    # The recognizer does not match A's enrolled voice, although gold says it is A.
    # It creates an anonymous identity instead. Gold must not repair recognition.
    run = Run([Utterance(0, 80, "S1")], [Speaker(id="S1", seconds=80, embedding=[0, 1])], 1)
    result = evaluate_attribution([session], {session.id: run}, {"A": [1, 0]})
    assert result["classify"]["known"]["newperson"]["rate"] == 1
    assert result["automatic_named_coverage"]["rate"] == 0
    assert result["new_unnamed_speech_fraction"]["rate"] == 1
    assert result["automatic_other_only_fraction"]["rate"] is None


def test_correlated_meetings_are_not_split_between_folds(tmp_path: Path) -> None:
    session, _ = example(tmp_path)
    sessions = [replace(session, id=f"s{i}", group=f"meeting-{i // 2}") for i in range(40)]
    dev = select_meetings(sessions, "dev", "frozen")
    formal = select_meetings(sessions, "formal", "frozen")
    assert dev and formal
    assert {s.group for s in dev}.isdisjoint({s.group for s in formal})
    assert {s.id for s in dev + formal} == {s.id for s in sessions}
    assert select_meetings(list(reversed(sessions)), "dev", "frozen") == list(reversed(dev))
    with pytest.raises(ValueError, match="split"):
        select_meetings(sessions, "random", "frozen")


def cached_inputs(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    session, run = example(tmp_path)
    session.audio.write_bytes(b"not decoded")
    session.voices["A"].write_bytes(b"reference not decoded")
    annotations = tmp_path / "reference.json"
    annotations.write_text(json.dumps({"segments": [u.__dict__ for u in session.reference]}))
    manifest = tmp_path / "sessions.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "id": session.id,
                "audio": session.audio.name,
                "reference": annotations.name,
                "duration": 80,
                "references": {"A": "A.wav"},
                "voice_from": {"A": session.id},
            }
        )
        + "\n"
    )
    cache = tmp_path / "session-cache.jsonl"
    cache.write_text(
        json.dumps(
            {
                "session": session.id,
                "target": "A",
                "segments": [u.__dict__ for u in run.segments],
                "speakers": [s.model_dump() for s in run.speakers],
                "seconds": 1,
            }
        )
        + "\n"
    )
    enrollment = tmp_path / "voiceprints.jsonl"
    enrollment.write_text(json.dumps({"key": "voice:" + _sha256(session.voices["A"]), "embedding": [1, 0]}) + "\n")
    provenance = tmp_path / "provenance.json"
    provenance.write_text(json.dumps({"data": "synthetic test; not a quality evaluation"}))
    return manifest, cache, enrollment, provenance


def test_cache_replay_keeps_provenance_and_unknown_human_time(tmp_path: Path) -> None:
    manifest, cache, enrollment, provenance = cached_inputs(tmp_path)
    before = [_sha256(p) for p in (manifest, cache, enrollment, provenance)]
    out = tmp_path / "out"
    card = run_attribution_benchmark(manifest, cache, enrollment, out, provenance_path=provenance)
    assert card["protocol"]["reference_origins"] == {"same_meeting": 1}
    assert not card["protocol"]["cross_meeting_enrollment_verified"]
    assert card["protocol"]["transcription_cache_sha256"] == _sha256(cache)
    assert card["workload_proxy"]["actual_human_seconds"] is None
    assert "实际人工工时未测" in (out / "scorecard.md").read_text()
    assert (out / "scorecard.json").stat().st_mode & 0o077 == 0
    assert before == [_sha256(p) for p in (manifest, cache, enrollment, provenance)]


def test_missing_or_incompatible_cache_fails_without_a_model_fallback(tmp_path: Path) -> None:
    manifest, cache, enrollment, provenance = cached_inputs(tmp_path)
    original = enrollment.read_text()
    enrollment.write_text("")
    with pytest.raises(ValueError, match="参考声纹"):
        run_attribution_benchmark(manifest, cache, enrollment, tmp_path / "out", provenance_path=provenance)
    enrollment.write_text(original.replace("[1, 0]", "[1, 0, 0]"))
    with pytest.raises(ValueError, match="兼容"):
        run_attribution_benchmark(manifest, cache, enrollment, tmp_path / "out", provenance_path=provenance)
    enrollment.write_text(original)
    cache.write_text("")
    with pytest.raises(ValueError, match="转写缓存"):
        run_attribution_benchmark(manifest, cache, enrollment, tmp_path / "out", provenance_path=provenance)
