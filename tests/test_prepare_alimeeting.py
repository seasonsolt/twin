"""AliMeeting conversion: TextGrid parsing, mark removal, far channel 0, isolated clips and cross-session voices."""

import importlib.util
import json
import sys
import wave
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "asr-eval" / "prepare_alimeeting.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_alimeeting", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses look their module up while the class is created
    spec.loader.exec_module(module)
    return module


prep = _load()


def _textgrid(tiers: dict[str, list[tuple[float, float, str]]], end: float) -> str:
    lines = [
        'File type = "ooTextFile"',
        'Object class = "TextGrid"',
        "",
        "xmin = 0",
        f"xmax = {end}",
        "tiers? <exists>",
    ]
    lines.append(f"size = {len(tiers)}")
    lines.append("item []:")
    for i, (name, intervals) in enumerate(tiers.items(), 1):
        lines += [f"    item [{i}]:", '        class = "IntervalTier"', f'        name = "{name}"', "        xmin = 0"]
        lines += [f"        xmax = {end}", f"        intervals: size = {len(intervals)}"]
        for j, (start, stop, text) in enumerate(intervals, 1):
            lines += [f"        intervals [{j}]:", f"            xmin = {start}", f"            xmax = {stop}"]
            lines.append(f'            text = "{text}"')
    return "\n".join(lines) + "\n"


def _wav(path: Path, channels: list[np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(len(channels))
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(np.stack(channels, axis=1).astype("<i2").tobytes())


def _tone(seconds: float, value: int) -> np.ndarray:
    return np.full(round(seconds * 16000), value, dtype=np.int16)


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "Eval_Ali"
    far, near = root / "Eval_Ali_far", root / "Eval_Ali_near"
    sessions = {
        # SPK1 attends both sessions; SPK2 only R1; SPK3 only R2.
        "R1_M1": {
            "SPK1": [(0.0, 6.0, "今天(SIL)我们开会"), (8.0, 14.0, "<sil>预算的事")],
            "SPK2": [(5.0, 7.0, "好的(/OVERLAP)"), (15.0, 16.0, "")],
        },
        "R2_M2": {"SPK1": [(0.0, 12.0, "第二场我先讲")], "SPK3": [(12.5, 14.0, "嗯(~)对")]},
    }
    for session, tiers in sessions.items():
        (far / "textgrid_dir").mkdir(parents=True, exist_ok=True)
        (far / "textgrid_dir" / f"{session}.TextGrid").write_text(_textgrid(tiers, 16.0), encoding="utf-8")
        # Channel 0 carries 100, channel 1 carries 200: only channel 0 must reach the outputs.
        _wav(far / "audio_dir" / f"{session}_MS1.wav", [_tone(16, 100), _tone(16, 200)])
        for speaker in tiers:
            _wav(near / "audio_dir" / f"{session}_N_{speaker}.wav", [_tone(16, 300)])
    return root


def _rows(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _samples(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        assert source.getnchannels() == 1 and source.getframerate() == 16000
        return np.frombuffer(source.readframes(source.getnframes()), dtype="<i2")


def test_clean_text_removes_marks() -> None:
    assert prep.clean_text("今天(SIL)我们<sil>开会(/OVERLAP)(~)`&") == "今天 我们 开会"
    assert prep.clean_text("Hello world") == "Hello world"


def test_read_textgrid_parses_tiers_and_drops_blanks(corpus: Path) -> None:
    turns = prep.read_textgrid(corpus / "Eval_Ali_far" / "textgrid_dir" / "R1_M1.TextGrid")
    assert [(t.start, t.end, t.speaker, t.text) for t in turns] == [
        (0.0, 6.0, "SPK1", "今天 我们开会"),
        (5.0, 7.0, "SPK2", "好的"),
        (8.0, 14.0, "SPK1", "预算的事"),
    ]


def test_read_textgrid_handles_utf16(tmp_path: Path) -> None:
    path = tmp_path / "x.TextGrid"
    path.write_bytes(_textgrid({"SPK9": [(0.0, 1.0, "你好")]}, 1.0).encode("utf-16"))
    assert [t.text for t in prep.read_textgrid(path)] == ["你好"]


def test_isolated_drops_overlapping_turns() -> None:
    turns = [prep.Turn(0, 6, "A", "x"), prep.Turn(5, 7, "B", "y"), prep.Turn(8, 9, "A", "z")]
    assert [t.text for t in prep.isolated(turns)] == ["z"]


def test_prepare_writes_sessions_clips_and_voices(corpus: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    counts = prep.prepare(corpus, out)
    assert counts == {"sessions": 2, "far_clips": 3, "near_clips": 3, "voices": 1}

    sessions = {row["id"]: row for row in _rows(out / "sessions.jsonl")}
    assert sessions["R1_M1"]["duration"] == 16.0
    # SPK1's voice comes from R2_M2 (the last session they attend), so only R1_M1 tests SPK1 as the person.
    assert sessions["R1_M1"]["references"] == {"SPK1": "voices/SPK1.wav"}
    assert sessions["R2_M2"]["references"] == {}
    reference = json.loads((out / "sessions" / "R1_M1.json").read_text(encoding="utf-8"))
    assert [s["speaker"] for s in reference["segments"]] == ["SPK1", "SPK2", "SPK1"]
    assert set(_samples(out / "sessions" / "R1_M1.wav").tolist()) == {100}

    far = _rows(out / "manifest-far.jsonl")
    assert [(r["text"], r["group"]) for r in far] == [
        ("预算的事", "R1_M1"),
        ("第二场我先讲", "R2_M2"),
        ("嗯 对", "R2_M2"),
    ]
    assert set(_samples(out / far[0]["audio"]).tolist()) == {100}
    assert len(_samples(out / far[0]["audio"])) == 6 * 16000
    near = _rows(out / "manifest-near.jsonl")
    assert [r["id"] for r in near] == [r["id"] for r in far]
    assert set(_samples(out / near[0]["audio"]).tolist()) == {300}

    voice = _samples(out / "voices" / "SPK1.wav")
    assert len(voice) == 12 * 16000  # one 12 s turn already covers the 10 s target
    assert not (out / "voices" / "SPK2.wav").exists()


def test_read_channel_rejects_wrong_rate(tmp_path: Path) -> None:
    path = tmp_path / "x.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(8000)
        out.writeframes(b"\x00\x00" * 10)
    with pytest.raises(ValueError, match="8000 Hz"):
        prep.read_channel(path)
