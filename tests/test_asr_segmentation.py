"""Speaker segmentation of the transcription pack against numbers from the real pyannote.audio 4.0.7.

The expected values were produced by ``pyannote.audio`` 4.0.7 (``Inference`` with ``skip_aggregation=True`` and
``Inference.aggregate`` as in 3D-Speaker's infer_diarization.py) on CPU from the same synthetic waveform.
"""

import hashlib
import importlib.util
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("torch")
pytest.importorskip("safetensors")

PACK = Path(__file__).resolve().parents[1] / "deploy" / "compute" / "asr-funasr"
WEIGHTS = PACK / "weights" / "segmentation-community-1.safetensors"


def load(name):
    spec = importlib.util.spec_from_file_location(name, PACK / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


segmentation = load("segmentation")


def synthetic_waveform():
    """25.3 s at 16 kHz: two harmonic "voices" with syllable-rate envelopes, alone, together and apart, plus noise.

    Built from integer-seeded noise and float64 arithmetic, then quantized to 16 bits so that last-ulp differences
    of ``np.sin`` between platforms cannot change a single sample.
    """
    sr = 16000
    t = np.arange(round(25.3 * sr)) / sr
    rng = np.random.default_rng(20261021)

    def voice(f0, rate, phase):
        pitch = f0 * (1 + 0.08 * np.sin(2 * np.pi * 0.7 * t + phase))
        cycles = 2 * np.pi * np.cumsum(pitch) / sr
        tone = sum(np.sin(k * cycles) / k for k in range(1, 12))
        syllables = 0.5 * (1 + np.sin(2 * np.pi * rate * t + phase)) ** 2
        return tone * syllables

    def gate(*spans):
        return sum(((t >= a) & (t < b)).astype(float) for a, b in spans)

    a = voice(120.0, 4.0, 0.0) * gate((1.0, 9.0), (12.0, 17.5), (20.0, 24.0))
    b = voice(210.0, 5.0, 1.3) * gate((6.0, 13.5), (16.0, 22.0))
    mix = 0.12 * a + 0.1 * b + 0.003 * rng.standard_normal(t.size)
    pcm = np.clip(np.rint(mix * 32767), -32768, 32767).astype(np.int16)
    return pcm.astype(np.float32) / 32768


# Expected values from pyannote.audio 4.0.7 (CPU) on synthetic_waveform().
WAVEFORM_SHA256 = "99c97ca1227d6f5a95761730255d5800730997ca484f34d4ec96a4a06ca9da6a"
NUM_CHUNKS = 17  # 16 full chunks and a zero-padded last one
MULTILABEL_SHA256 = "84984b621d9b42396fd1eb78ef9192caf44e0d565919d4deddcd654dbde2efb1"
# (speakers, run length) over the 1542 count frames.
COUNT_RUNS = [
    (1, 17), (0, 37), (1, 317), (2, 153), (1, 37), (0, 137), (1, 9),
    (2, 93), (1, 153), (2, 83), (1, 145), (2, 122), (1, 234), (0, 5),
]  # fmt: skip
FRAMES = (0.0, 0.0619375, 0.016875)  # receptive field: start, duration, step (991 and 270 samples)
# (t, count.sliding_window.closest_frame(t), count.sliding_window[that frame].middle)
CLOSEST_FRAMES = [
    (0.0, -2, -0.0027812500000000025),
    (0.03, 0, 0.03096875),
    (1.234567, 71, 1.22909375),
    (7.5, 443, 7.50659375),
    (10.03096875, 593, 10.03784375),
    (12.3456789, 730, 12.349718750000001),
    (25.3, 1497, 25.292843750000003),
]


def runs(values):
    out = []
    for v in values.tolist():
        if out and out[-1][0] == v:
            out[-1][1] += 1
        else:
            out.append([v, 1])
    return [tuple(r) for r in out]


@pytest.fixture(scope="module")
def result():
    return segmentation.Segmenter(WEIGHTS, "cpu")(synthetic_waveform(), keep_log_probs=True)


def test_waveform_is_the_one_pyannote_saw():
    pcm = np.rint(synthetic_waveform() * 32768).astype("<i2")
    assert hashlib.sha256(pcm.tobytes()).hexdigest() == WAVEFORM_SHA256


def test_chunks_and_frames_match_pyannote(result):
    assert (result.chunks.start, result.chunks.duration, result.chunks.step) == (0.0, 10.0, 1.0)
    assert result.multilabel.shape == (NUM_CHUNKS, 589, 3)
    assert result.multilabel.dtype == np.float32
    assert result.log_probs.shape == (NUM_CHUNKS, 589, 7)
    assert (result.frames.start, result.frames.duration, result.frames.step) == FRAMES
    assert (result.count_frames.start, result.count_frames.duration, result.count_frames.step) == (0.0, *FRAMES[1:])
    assert segmentation.num_frames(160000) == 589


def test_binarized_speakers_and_count_match_pyannote(result):
    assert hashlib.sha256(result.multilabel.astype(np.uint8).tobytes()).hexdigest() == MULTILABEL_SHA256
    assert result.count.dtype == np.uint8 and result.count.shape[1] == 1
    assert runs(result.count[:, 0]) == COUNT_RUNS


def test_window_positions_match_pyannote(result):
    frames = result.count_frames
    for t, frame, middle in CLOSEST_FRAMES:
        assert frames.closest_frame(t) == frame
        assert frames[frame].middle == middle
    chunk = result.chunks[3]
    assert (chunk.start, chunk.end, chunk.middle) == (3.0, 13.0, 8.0)


def test_a_short_waveform_is_one_padded_chunk():
    found = segmentation.Segmenter(WEIGHTS, "cpu")(np.zeros(16000 * 3, dtype=np.float32))
    assert found.multilabel.shape == (1, 589, 3)
    assert found.count.shape == (found.count_frames.closest_frame(10.0 + 0.5 * found.frames.duration) + 1, 1)
