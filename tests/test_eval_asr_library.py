"""Library-path ASR benchmark: the production library, team and review code run over a scored meeting."""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from twin.evals.asr_library import (
    Tally,
    evaluate_engine,
    overridden,
    parse_overrides,
    render,
    run_library_benchmark,
    summarize,
)
from twin.evals.asr_session import SessionEngine, load_sessions
from twin.evals.diarization import Utterance, spoken_by
from twin.media.ingest import CommandTranscriber, Progress, Segment, Speaker

DURATION = 80


class Service(CommandTranscriber):
    """A transcription service that hears A's voice as [1, 0] and B's as [0, 1] (stretches by their start time)."""

    def __init__(self) -> None:
        super().__init__("unused")
        self.requests: list[dict[str, object]] = []

    def transcribe(self, audio: Path, duration: float, progress: Progress) -> list[Segment]:
        # The library's request: diarize, and no reference voice (it is not the upload path).
        self.requests.append({"diarize": self.diarize, "reference": self.reference, "references": self.references})
        self.speakers = [
            Speaker(id="S1", seconds=40, embedding=[1.0, 0.0]),
            Speaker(id="S2", seconds=40, embedding=[0.0, 1.0]),
        ]
        # S1 holds A's first 32 s and, by mistake, B's next 8 s; S2 is B.
        first = [Segment(start=t, end=t + 4, text="甲乙丙丁", speaker="S1") for t in range(0, 40, 4)]
        second = [Segment(start=t, end=t + 4, text="戊己庚辛", speaker="S2") for t in range(40, 80, 4)]
        return first + second

    def embed(self, voice: Path) -> list[float] | None:
        return [1.0, 0.0]

    def embed_spans(self, audio: Path, spans: list[list[tuple[float, float]]]) -> list[list[float] | None] | None:
        return [[0.0, 1.0] if parts[0][0] >= 32 else [1.0, 0.0] for parts in spans]


def write_session(tmp_path: Path) -> Path:
    audio = tmp_path / "s1.wav"
    with wave.open(str(audio), "wb") as wav:
        wav.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        wav.writeframes(bytes(2) * 16000 * DURATION)
    (tmp_path / "A.wav").write_bytes(audio.read_bytes()[:1000])
    reference = [
        {"start": 0, "end": 32, "speaker": "A", "text": "甲" * 32},
        {"start": 32, "end": 80, "speaker": "B", "text": "乙" * 48},
    ]
    (tmp_path / "s1.json").write_text(json.dumps({"segments": reference}))
    manifest = tmp_path / "sessions.jsonl"
    row = {
        "id": "s1",
        "audio": "s1.wav",
        "duration": DURATION,
        "reference": "s1.json",
        "references": {"A": "A.wav"},
    }
    manifest.write_text(json.dumps(row) + "\n")
    return manifest


def test_spoken_by_counts_the_target_and_only_the_others() -> None:
    reference = [Utterance(0, 10, "A"), Utterance(5, 15, "B")]
    assert spoken_by(reference, [(0, 20)], "A") == (10.0, 5.0)
    assert spoken_by(reference, [(12, 14)], "A") == (0.0, 2.0)
    assert spoken_by(reference, [(16, 18)], "A") == (0.0, 0.0)


def test_the_library_flow_is_scored_stage_by_stage(tmp_path: Path) -> None:
    sessions = load_sessions(write_session(tmp_path))
    service = Service()
    result = evaluate_engine(
        SessionEngine("fake", "unused"), sessions, tmp_path / "base", tmp_path / "work", lambda *_: None, service
    )
    assert service.requests == [{"diarize": True, "reference": None, "references": {}}]
    tally: Tally = result["tally"]
    # S1 is A's voice and is taken by voice alone; S2 is B, who has no sample and has spoken for under a minute.
    assert tally.total("classify_known_right") == 40
    assert tally.total("classify_unknown_undecided") == 40
    card = summarize(result)
    review = card["review"]
    # The owner confirmed S2 as B, who has no samples, so only S1 was heard: 8 of its 40 seconds are B's.
    assert review["foreign_found"] == 1.0 and review["own_flagged"] == 0.0
    assert review["put_to_owner"] == 1 and review["put_impure"] == 1 and review["unready"] == 1
    twin = card["twin"]
    # A's twin holds 8 foreign characters of its 40; with B's 40 own characters that is 8 of 80.
    assert twin["owner"]["strict"]["foreign"]["rate"] == 0.1
    assert twin["review"]["strict"]["foreign"]["rate"] == 0.0
    assert twin["follow"]["strict"]["foreign"]["rate"] == 0.0
    # The owner decides S2 (40 s, undecided) and hears S1 (40 s, put to them): all 80 s of speech went through them.
    assert card["manual"]["rate"] == 1.0 and card["manual"]["review_seconds"] == 40
    assert card["gate"]["auto_wrong_seconds"] == 0 and card["gate"]["foreign"] == 0.0
    assert not card["gate"]["passed"]


def test_benchmark_writes_a_private_scorecard(tmp_path: Path, monkeypatch: object) -> None:
    manifest = write_session(tmp_path)
    out = tmp_path / "out"
    engine = SessionEngine("fake", "unused")
    import twin.evals.asr_library as module

    monkeypatch.setattr(module, "CachedService", lambda command, language, cache: Service())  # type: ignore[attr-defined]
    card = run_library_benchmark(manifest, [engine], out)
    assert card["sessions"] == 1
    text = (out / "scorecard.md").read_text()
    assert "团队录音库流程评测" in text and "自动归属" in text and "听并判断" in text and "未通过" in text
    assert (out / "scorecard.md").stat().st_mode & 0o077 == 0
    assert render(card["engines"], 1) == text


def test_overrides_name_known_thresholds_and_are_put_back() -> None:
    from twin.media import team

    assert parse_overrides(["team.AUTO=0.6"]) == {"team.AUTO": 0.6}
    with pytest.raises(ValueError):
        parse_overrides(["team.SOURCE_PREFIX=1"])
    with pytest.raises(ValueError):
        parse_overrides(["team.AUTO=high"])
    before = team.AUTO
    with overridden({"team.AUTO": 0.5}):
        assert team.AUTO == 0.5
    assert before == team.AUTO
