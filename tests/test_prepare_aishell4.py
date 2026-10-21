"""AISHELL-4 conversion: per-session speaker names, mark removal, channel choice and the R### group."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "asr-eval" / "prepare_aishell4.py"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("prepare_aishell4", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


prep = _load()


def _textgrid(tiers: dict[str, list[tuple[float, float, str]]], end: float) -> str:
    lines = ['File type = "ooTextFile"', 'Object class = "TextGrid"', "", "xmin = 0", f"xmax = {end}"]
    lines += ["tiers? <exists>", f"size = {len(tiers)}", "item []:"]
    for i, (name, intervals) in enumerate(tiers.items(), 1):
        lines += [f"    item [{i}]:", '        class = "IntervalTier"', f'        name = "{name}"', "        xmin = 0"]
        lines += [f"        xmax = {end}", f"        intervals: size = {len(intervals)}"]
        for j, (start, stop, text) in enumerate(intervals, 1):
            lines += [f"        intervals [{j}]:", f"            xmin = {start}", f"            xmax = {stop}"]
            lines.append(f'            text = "{text}"')
    return "\n".join(lines) + "\n"


def test_group_is_the_room_number_across_sizes() -> None:
    assert prep.group_of("L_R003S01C02") == "R003"
    assert prep.group_of("S_R003S04C01") == prep.group_of("M_R003S02C01")
    assert prep.group_of("L_R004S06C01") == "R004"
    with pytest.raises(ValueError):
        prep.group_of("R003")


def test_prepare_names_speakers_per_session_and_writes_group(tmp_path: Path, monkeypatch) -> None:
    root, out = tmp_path / "test", tmp_path / "out"
    (root / "TextGrid").mkdir(parents=True)
    (root / "wav").mkdir()
    tiers = {
        # 001 talks alone for 12 s, then 002 overlaps it; 002 is never alone long enough for a voice.
        "001-M": [(0.0, 12.0, "今天<sil>我们开会"), (12.0, 14.0, "<%>")],
        "002-F": [(13.0, 14.0, "好的<$>")],
    }
    for session in ("L_R003S01C02", "S_R004S01C01"):
        (root / "TextGrid" / f"{session}.TextGrid").write_text(_textgrid(tiers, 14.0), encoding="utf-8")
        (root / "wav" / f"{session}.flac").touch()

    def channels(path: Path, wanted: tuple[int, ...]) -> list[np.ndarray]:
        assert wanted == (prep.CHANNEL, prep.VOICE_CHANNEL)
        return [np.full(14 * prep.RATE, 100 + c, np.int16) for c in wanted]

    monkeypatch.setattr(prep, "read_channels", channels)
    assert prep.prepare(root, out) == {"sessions": 2, "people": 2}
    rows = [json.loads(line) for line in (out / "sessions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(r["id"], r["group"]) for r in rows] == [("L_R003S01C02", "R003"), ("S_R004S01C01", "R004")]
    first = rows[0]
    assert first["references"] == {"L_R003S01C02-001-M": "voices/L_R003S01C02-001-M.wav"}
    assert first["voice_from"] == {"L_R003S01C02-001-M": "L_R003S01C02"}
    segments = json.loads((out / first["reference"]).read_text(encoding="utf-8"))["segments"]
    # Marks are gone and the mark-only interval is dropped.
    assert [(s["speaker"], s["text"]) for s in segments] == [
        ("L_R003S01C02-001-M", "今天 我们开会"),
        ("L_R003S01C02-002-F", "好的"),
    ]
