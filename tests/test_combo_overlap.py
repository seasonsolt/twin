"""Overlap recovery gates use only mixture-derived enrollment, never reference audio."""

import importlib.util
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "asr-eval" / "combo_overlap.py"
spec = importlib.util.spec_from_file_location("combo_overlap", SCRIPT)
combo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(combo)


@pytest.mark.parametrize(
    ("text", "original", "expected"),
    [("", "讨论", False), ("讨论。", "继续讨论。", False), ("预算", "继续讨论。", True)],
)
def test_duplicate_text(text, original, expected):
    assert combo.distinct_text(text, original) == expected


def test_assignment_requires_known_distinct_speaker():
    centroids = {"a": np.array([1.0, 0.0]), "b": np.array([0.0, 1.0])}
    assert combo.assign(np.array([1.0, 0.0]), centroids) == "a"
    assert combo.assign(np.array([0.7, 0.7]), centroids) is None
    assert combo.assign(np.array([0.2, 0.0]), centroids) is None
    assert combo.assign(np.array([1.0, 0.0]), {"a": centroids["a"]}) is None


def fake_engine(secondary=2.0):
    def embed(clip):
        return np.array([1.0, 0.0]) if float(clip.mean()) < 1.5 else np.array([0.0, 1.0])

    return SimpleNamespace(
        np=np,
        embed=embed,
        separate=lambda clip: [np.ones_like(clip), np.full_like(clip, secondary)],
        vad=SimpleNamespace(generate=lambda **kw: [{"value": [[0, len(kw["input"]) / 16]]}]),
        recognize=lambda clips, hotwords: ["补充预算" if c.mean() > 1.5 else "主要内容" for c in clips],
    )


def fixture_result():
    return {
        "ok": True,
        "segments": [
            {"start": 0, "end": 2, "text": "原有内容", "speaker": "a"},
            {"start": 2, "end": 4, "text": "补充预算", "speaker": "b"},
        ],
        "speakers": [{"id": "a", "seconds": 2, "similarity": 0.7}, {"id": "b", "seconds": 2}],
    }


@pytest.mark.parametrize("mode", ["add", "replace"])
def test_recovery_preserves_claims_and_emits_overlapping_streams(mode):
    result = fixture_result()
    wav = np.concatenate([np.ones(32000), np.full(32000, 2)])
    progress = []
    output = combo.recover(fake_engine(), wav, result, mode, progress.append)
    assert output["ok"]
    assert output["speakers"][0]["similarity"] == 0.7
    first = [s for s in output["segments"] if s["start"] == 0]
    assert {s["speaker"] for s in first} == {"a", "b"}
    assert first[0]["text"] == ("原有内容" if mode == "add" else "主要内容")
    assert progress[-1] == 1


@pytest.mark.parametrize("secondary", [0.0, 1.0, float("nan")])
def test_silence_same_speaker_and_invalid_stream_do_not_add_words(secondary):
    result = fixture_result()
    expected = deepcopy(result)
    wav = np.concatenate([np.ones(32000), np.full(32000, 2)])
    assert combo.recover(fake_engine(secondary), wav, result, "add", lambda _: None) == expected


def test_one_speaker_is_unchanged():
    result = fixture_result()
    result["segments"] = result["segments"][:1]
    expected = deepcopy(result)
    assert combo.recover(fake_engine(), np.ones(32000), result, "add", lambda _: None) == expected
