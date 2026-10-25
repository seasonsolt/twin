"""asr-funasr 1.4 overlap-aware path: the model-free parts of overlap.py and diarize.py."""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

# The pack's own environment can run these too (it has scipy and sklearn), so no twin imports here.
PACK = Path(__file__).resolve().parents[1] / "deploy" / "compute" / "asr-funasr"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"asr_pack_{name}", PACK / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def overlap():
    return _load("overlap")


@pytest.fixture(scope="module")
def diarize():
    return _load("diarize")


def test_turns_are_cleaned_and_chunked(overlap):
    turns = [(0.0, 10.0, "A"), (2.0, 2.3, "B"), (5.0, 6.0, "B"), (9.5, 12.0, "B"), (12.5, 13.0, "B")]
    # B's 0.3 s turn inside A's is dropped; a 1 s one stays, and so does a short one not wholly inside.
    kept = overlap.drop_enclosed(turns)
    assert (2.0, 2.3, "B") not in kept and (5.0, 6.0, "B") in kept and len(kept) == 4
    assert overlap.chunks([(0.0, 4.0, "A"), (4.5, 6.0, "A"), (6.2, 7.0, "B"), (7.5, 8.0, "A")]) == [
        (0.0, 6.0, "A"),
        (6.2, 7.0, "B"),
        (7.5, 8.0, "A"),
    ]
    # Longer than 15 s: split evenly.
    assert overlap.chunks([(0.0, 40.0, "A")]) == [(0.0, 40 / 3, "A"), (40 / 3, 80 / 3, "A"), (80 / 3, 40.0, "A")]


def test_overlap_regions_pick_the_two_longest(overlap):
    speakers = ["A", "B", "C"]
    act = overlap.activity([(0.0, 3.0, "A"), (1.0, 2.0, "B"), (1.5, 2.5, "C")], speakers, 400)
    regions = overlap.overlap_regions(act, speakers)
    assert [(r["start"], r["end"]) for r in regions] == [(1.0, 2.5)]
    assert regions[0]["pair"] == ["A", "B"]  # B and C both 1 s inside; argsort keeps the first on a tie
    assert [len(r) for r in overlap.runs_of(np.array([0, 1, 1, 0, 1], bool))] == [2, 1]


def test_speaker_audio_mutes_others_and_uses_own_stream(overlap):
    rate = overlap.SAMPLE_RATE
    wav = np.ones(4 * rate, np.float32)
    speakers = ["A", "B"]
    act = overlap.activity([(0.0, 1.0, "A"), (2.0, 4.0, "A"), (1.5, 3.0, "B")], speakers, len(wav) // 160 + 1)
    regions = [{"start": 2.0, "end": 3.0, "pair": ["A", "B"], "audio": {"A": np.full(rate, 0.5, np.float32)}}]
    audio = overlap.speaker_audio(wav, 0.0, 4.0, "A", act[0], regions)
    assert len(audio) == len(wav)
    assert audio[int(0.5 * rate)] == pytest.approx(1.0)  # alone: the mixture
    assert audio[int(1.5 * rate)] == pytest.approx(0.0)  # B alone inside A's chunk: muted
    assert audio[int(2.5 * rate)] == pytest.approx(0.5)  # overlap: A's own stream
    assert audio[int(3.5 * rate)] == pytest.approx(1.0)


def test_loudness_and_loop_detection(overlap):
    quiet = (0.01 * np.sin(np.arange(48000) / 5)).astype(np.float32)
    louder = quiet * overlap.gain(quiet)
    assert overlap.active_level(louder) == pytest.approx(overlap.TARGET_DBFS, abs=0.01)
    assert overlap.gain(np.zeros(100, np.float32)) == 1.0
    assert overlap.degenerate("对对对对对对对对", 3.0)
    assert overlap.degenerate("我" * 50, 2.0)
    assert not overlap.degenerate("今天我们讨论一下预算。", 3.0)


@pytest.mark.parametrize(
    ("turns", "region", "expected_calls"),
    [
        ([(0, 3, 0), (3, 6, 1), (6, 9, 2)], None, (3, 0)),
        ([(0, 4, 0), (3, 7, 1), (8, 11, 2)], None, (4, 3)),
        ([(0, 3, 0), (2.95, 6, 1), (6, 9, 2)], None, (4, 1)),
        # B has no clean run, so assign must retain its existing loudness fallback.
        ([(0, 4, 0), (1, 2, 1), (5, 8, 2)], None, (3, 2)),
        # Compare integer sample positions exactly as assign does, not duration in seconds.
        ([(0, 4, 0), (3, 7, 1), (8, 11, 2)], (3.00001, 3.1), (4, 3)),
        ([(0, 4, 0), (3, 7, 1), (8, 11, 2)], (3, 3.099999), (4, 1)),
    ],
    ids=["no-overlap", "overlap", "short-overlap", "missing-prototype", "1600-samples", "1599-samples"],
)
def test_only_usable_overlap_pairs_need_separated_prototypes(overlap, monkeypatch, turns, region, expected_calls):
    wav = np.linspace(-0.4, 0.5, 12 * overlap.SAMPLE_RATE, dtype=np.float32)
    monkeypatch.setitem(sys.modules, "librosa", SimpleNamespace(load=lambda *a, **k: (wav.copy(), overlap.SAMPLE_RATE)))
    if region is not None:
        monkeypatch.setattr(
            overlap,
            "overlap_regions",
            lambda *args: [{"start": region[0], "end": region[1], "pair": ["S0", "S1"]}],
        )

    def run(eager):
        calls = {"separation": 0, "probe_embedding": 0, "claim_windows": 0}
        assigned, recognized = [], []

        def separate(clip):
            calls["separation"] += 1
            return [clip * 0.25, clip * 0.75]

        def vector(clip):
            return overlap.unit(np.array([clip.mean(), np.square(clip).mean(), 1.0]))

        def embed(clip):
            calls["probe_embedding"] += 1
            return vector(clip)

        def embed_all(windows, progress, singles_on_gpu=False):
            assert singles_on_gpu
            calls["claim_windows"] += len(windows)
            return np.stack([vector(w) for w in windows])

        def describe(order, names, totals, claims, reference, references):
            return [
                {"speaker": names[x], "seconds": totals[x], "embedding": claims[x].tolist() if x in claims else None}
                for x in order
            ]

        def recognize(clips):
            recognized.extend(c.copy() for c in clips)
            return ["同一段转写" for _ in clips]

        path = overlap.Overlap.__new__(overlap.Overlap)
        path.engine = SimpleNamespace(embed_gpu=embed, embed_all=embed_all, describe=describe)
        path.diarizer = lambda samples: turns
        path.separate = separate
        path.firered = recognize
        path.finish = lambda clips, raw, hotwords: raw
        original_voiceprints = path.voiceprints
        if eager:
            # Before 1.5.5 every speaker got a prototype, whether assign used it or not.
            path.voiceprints = lambda wav, act, speakers, overlapping: original_voiceprints(
                wav, act, speakers, set(speakers)
            )
        original_assign = path.assign

        def assign(wav, regions, separated, progress):
            original_assign(wav, regions, separated, progress)
            assigned.extend({x: s.copy() for x, s in r["audio"].items()} for r in regions)

        path.assign = assign
        result = path.transcribe(Path("unused.wav"), True, None, [], lambda f: None)
        return result, assigned, recognized, calls

    before, after = run(True), run(False)
    assert before[0] == after[0]  # All speakers' claim vectors and returned transcript stay identical.
    assert len(before[1]) == len(after[1])
    for old, new in zip(before[1], after[1], strict=True):
        assert old.keys() == new.keys()
        for speaker in old:
            np.testing.assert_array_equal(old[speaker], new[speaker])
    assert len(before[2]) == len(after[2])
    for old, new in zip(before[2], after[2], strict=True):
        np.testing.assert_array_equal(old, new)
    assert (before[3]["separation"], after[3]["separation"]) == expected_calls
    assert before[3]["claim_windows"] == after[3]["claim_windows"] > 0
    saved = expected_calls[0] - expected_calls[1]
    assert before[3]["probe_embedding"] - after[3]["probe_embedding"] == saved


def test_diarize_timeline_helpers(diarize):
    assert diarize.merge_spans([[0, 1], [3, 4]], [[0.5, 2], [5, 6]]) == [[0, 2], [3, 4], [5, 6]]
    assert diarize.windows(0.0, 3.0) == [[0.0, 1.5], [0.75, 2.25], [1.5, 3.0]]
    assert diarize.windows(0.0, 1.0) == [[0.0, 1.0]]
    assert diarize.compress([[0, 1.5, 0], [0.75, 2.25, 0], [1.5, 3.0, 1], [4.0, 5.0, 1]]) == [
        [0, 1.875, 0],
        [1.875, 3.0, 1],
        [4.0, 5.0, 1],
    ]
    window = _Window(0.0, 0.1, 0.1)
    assert diarize.speech_spans(np.array([0, 1, 1, 0, 2, 2]), window) == [
        [window[1].middle, window[3].middle],
        [window[4].middle, window[5].middle],
    ]
    binary = np.array([[1, 0], [1, 1], [0, 1], [0, 0]], float)
    assert diarize.binary_turns(binary, [0.0, 0.1, 0.2, 0.3]) == [(0.0, 0.2, 0), (0.1, 0.3, 1)]


class _Span:
    def __init__(self, start, duration):
        self.start, self.middle = start, start + duration / 2


class _Window:
    def __init__(self, start, duration, step):
        self.start, self.duration, self.step = start, duration, step

    def __getitem__(self, i):
        return _Span(self.start + i * self.step, self.duration)

    def closest_frame(self, t):
        return int(np.rint((t - self.start - 0.5 * self.duration) / self.step))


def test_clustering_separates_two_voices_and_folds_tiny_clusters(diarize):
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(0)
    a, b = np.eye(192)[0], np.eye(192)[1]
    voices = [a + 0.05 * rng.standard_normal(192) for _ in range(30)] + [
        b + 0.05 * rng.standard_normal(192) for _ in range(30)
    ]
    labels = diarize.cluster(np.stack(voices))
    assert len(set(labels[:30])) == 1 and len(set(labels[30:])) == 1 and labels[0] != labels[30]
    # Same input, same labels: the clustering is seeded.
    assert diarize.cluster(np.stack(voices)).tolist() == labels.tolist()
    # Under 40 windows: agglomerative; b's 3 windows are a cluster of at most 4, folded into a.
    few = np.stack(voices[:10] + voices[30:33])
    assert len(set(diarize.cluster(few).tolist())) == 1


def test_overlap_keeps_as_many_clusters_as_the_model_counts(diarize):
    pytest.importorskip("scipy")
    frames = _Window(0.0, 0.1, 0.1)
    # Two clusters back to back; the segmentation model hears both at once in frames 4-5.
    turns = [[0.0, 0.55, 0], [0.55, 1.0, 1]]
    local = np.zeros((1, 10, 3), np.float32)
    local[0, :6, 0] = 1
    local[0, 4:, 1] = 1
    count = np.array([1, 1, 1, 1, 2, 2, 1, 1, 1, 1], np.uint8)[:, None]
    segmentation = SimpleNamespace(multilabel=local, chunks=_Window(0.0, 1.0, 1.0), count=count, count_frames=frames)
    binary = diarize.add_overlap(turns, 2, segmentation)
    assert binary[:, 0].tolist() == [1, 1, 1, 1, 1, 1, 0, 0, 0, 0]
    assert binary[:, 1].tolist() == [0, 0, 0, 0, 1, 1, 1, 1, 1, 1]


def voices(count, speakers, seed=0):
    """Voiceprint-like windows: `speakers` directions in 192 dimensions, each window one of them plus noise."""
    rng = np.random.default_rng(seed)
    centres = rng.normal(size=(speakers, 192))
    return (centres[rng.integers(speakers, size=count)] + 0.9 * rng.normal(size=(count, 192))).astype(np.float32)


def test_a_long_recording_is_clustered_on_the_same_affinity_stored_sparsely(diarize, monkeypatch):
    pytest.importorskip("scipy")
    pytest.importorskip("sklearn")
    x = voices(600, 5)
    keep = int((1 - 0.012) * len(x))
    affinity = diarize.cosine(x, x)
    for row in affinity:
        row[np.argsort(row)[:keep]] = 0
    affinity = 0.5 * (affinity + affinity.T)
    np.fill_diagonal(affinity, 0)
    dense = -affinity
    dense[np.diag_indices_from(dense)] = np.abs(affinity).sum(axis=1)
    np.testing.assert_allclose(diarize.sparse_laplacian(x, len(x) - keep).toarray(), dense, atol=1e-5)

    before = diarize.spectral(x)
    monkeypatch.setattr(diarize, "DENSE_WINDOWS", 0)
    assert (diarize.spectral(x) == before).all() and len(set(before)) == 5
