"""Overlap-aware transcription helpers: which turns are kept, how they are chunked, and whose audio each chunk holds."""

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1] / "deploy" / "asr-eval"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


overlap = load("overlap_pipeline")
climb = load("climb")


def test_short_turn_inside_another_is_dropped_but_long_or_boundary_turns_stay():
    turns = [(0.0, 10.0, "A"), (2.0, 2.4, "B"), (4.0, 5.0, "B"), (9.8, 12.0, "C")]
    kept = overlap.drop_enclosed(turns, 0.5)
    assert (2.0, 2.4, "B") not in kept
    assert {(4.0, 5.0, "B"), (9.8, 12.0, "C"), (0.0, 10.0, "A")} <= set(kept)
    assert overlap.drop_enclosed(turns, 0) == turns


def test_chunks_join_close_turns_of_one_speaker_and_split_long_ones():
    found = overlap.chunks([(0.0, 3.0, "A"), (3.5, 6.0, "A"), (8.0, 9.0, "A"), (20.0, 50.0, "B")])
    assert (0.0, 6.0, "A") in found and (8.0, 9.0, "A") in found
    assert [c for c in found if c[2] == "B"] == [(20.0, 35.0, "B"), (35.0, 50.0, "B")]
    # A turn of someone else starting in between ends the chunk, as in run.organize.
    found = overlap.chunks([(0.0, 3.0, "A"), (1.0, 2.0, "B"), (3.5, 6.0, "A")])
    assert found == [(0.0, 3.0, "A"), (1.0, 2.0, "B"), (3.5, 6.0, "A")]


def test_overlap_regions_pick_the_two_speakers_talking_longest():
    speakers = ["A", "B", "C"]
    act = overlap.activity([(0.0, 3.0, "A"), (1.0, 2.0, "B"), (1.5, 1.8, "C"), (5.0, 6.0, "B")], speakers, 700)
    regions = overlap.overlap_regions(act, speakers)
    assert len(regions) == 1
    assert regions[0]["start"] == pytest.approx(1.0) and regions[0]["end"] == pytest.approx(2.0)
    assert set(regions[0]["pair"]) == {"A", "B"}


def test_speaker_audio_uses_own_stream_in_overlap_and_silence_where_others_talk():
    sr = overlap.SAMPLE_RATE
    wav = np.ones(4 * sr, np.float32)  # the mixture
    speakers = ["A", "B"]
    act = overlap.activity([(0.0, 1.0, "A"), (2.0, 4.0, "A"), (1.0, 3.0, "B")], speakers, 401)
    region = {"start": 2.0, "end": 3.0, "pair": ["A", "B"]}
    region["audio"] = {"A": np.full(sr, 5.0, np.float32), "B": np.full(sr, 7.0, np.float32)}
    audio = overlap.speaker_audio(wav, 0.0, 4.0, "A", act[0], [region], fade=0.0, pad=0.0)
    assert audio[int(0.5 * sr)] == pytest.approx(1.0)  # A alone: mixture
    assert audio[int(1.5 * sr)] == pytest.approx(0.0)  # only B talks: silenced
    assert audio[int(2.5 * sr)] == pytest.approx(5.0)  # overlap: A's own stream
    assert audio[int(3.5 * sr)] == pytest.approx(1.0)
    other = overlap.speaker_audio(wav, 1.0, 3.0, "B", act[1], [region], fade=0.0, pad=0.0)
    assert other[int(1.5 * sr)] == pytest.approx(7.0)


def test_gain_brings_the_active_level_to_the_target():
    rng = np.random.default_rng(0)
    wav = np.concatenate([np.zeros(16000), 0.01 * rng.standard_normal(32000)]).astype(np.float32)
    gain = climb.gain_for(wav, {"target": -27})
    assert climb.active_level(wav * gain) == pytest.approx(-27, abs=0.01)
    assert climb.gain_for(wav, {"target": -27, "max_db": 3}) == pytest.approx(10 ** (3 / 20))
    assert climb.gain_for(wav * 100, {"target": -27, "only_up": True}) == 1.0


def test_unknown_or_conflicting_settings_are_refused():
    class Engine:
        def __init__(self, device="auto"):
            pass

        def transcribe(self, *args, **kwargs):
            return {}

    run = type("run", (), {"Engine": Engine})
    with pytest.raises(ValueError, match="未知配置项"):
        climb.combine(run, json.loads('{"vda": {}}'))
    with pytest.raises(ValueError, match="不能与 gain 同用"):
        climb.combine(run, {"pyannote": {"model": "m"}, "gain": {"target": -27}})
