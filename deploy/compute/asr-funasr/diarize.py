# Adapted from 3D-Speaker (https://github.com/modelscope/3D-Speaker, commit 065629c),
# speakerlab/bin/infer_diarization.py and speakerlab/process/cluster.py.
# Copyright 3D-Speaker. Licensed under the Apache License, Version 2.0 (see THIRD_PARTY.md in this directory).
# Changes: models come from local paths (FSMN VAD and CAM++ through funasr, the segmentation model through
# segmentation.py) instead of ModelScope/pyannote downloads; only the spectral path is kept; scipy's average
# linkage replaces fastcluster; k-means and the eigensolver are seeded so a recording always gets the same result.
"""Speaker diarization that allows two people at once: 3D-Speaker's audio-only pipeline with overlap detection.

1. FSMN VAD (its own default settings, not run.py's shorter segments); the segmentation model's speech frames are
   added to the VAD spans.
2. 1.5 s windows every 0.75 s, CAM++ zh-en voiceprints, spectral clustering (pval 0.012, at most 15 speakers),
   clusters of four windows or fewer folded into the nearest bigger one, clusters closer than cosine 0.8 merged.
3. Overlap (segmentation.py): per 10 s chunk the segmentation model's local speakers are matched to the clusters
   (Hungarian on shared frames); each frame keeps as many of the most active clusters as the model counts there.

`Diarizer(...)(wav)` returns `[(start, end, label), ...]` in seconds, sorted by start; turns of different labels
may overlap. Default parameters are 3D-Speaker's, chosen on its own data, and were not tuned on AliMeeting.
"""

from __future__ import annotations

import numpy as np

SAMPLE_RATE = 16000
WINDOW = 1.5
STEP = 0.75
BATCH = 64


def merge_spans(first, second):
    """Union of two lists of [start, end] spans, sorted."""
    merged = []
    for span in sorted([list(s) for s in first + second], key=lambda s: s[0]):
        if not merged or merged[-1][1] < span[0]:
            merged.append(span)
        else:
            merged[-1][1] = max(merged[-1][1], span[1])
    return merged


def windows(start, end, length=WINDOW, step=STEP):
    """Embedding windows over one speech span; the last ends at the span's end."""
    found, t = [], start
    while t + length < end + step:
        found.append([t, min(t + length, end)])
        t += step
    return found


def compress(labelled):
    """Consecutive windows of one label become one turn; where two labels' windows overlap, cut in the middle."""
    result = []
    for start, end, label in labelled:
        if not result:
            result.append([start, end, label])
        elif label == result[-1][2]:
            if start > result[-1][1]:
                result.append([start, end, label])
            else:
                result[-1][1] = end
        else:
            if start < result[-1][1]:
                middle = (result[-1][1] + start) / 2
                result[-1][1] = middle
                start = middle
            result.append([start, end, label])
    return result


def circle_pad(x, length):
    """Repeat a clip until it is `length` samples long (as 3D-Speaker does for its shorter last windows)."""
    import torch

    if x.shape[0] >= length:
        return x
    return torch.cat([x] * int(np.ceil(length / x.shape[0])))[:length]


def cosine(a, b):
    a = a / np.linalg.norm(a, axis=1, keepdims=True)
    b = b / np.linalg.norm(b, axis=1, keepdims=True)
    return a @ b.T


def spectral(x, pval=0.012, min_speakers=1, max_speakers=15, min_pnum=6):
    """Spectral clustering on the p-pruned cosine affinity; the number of speakers is the largest eigengap."""
    import scipy.sparse.linalg
    from sklearn.cluster import k_means

    affinity = cosine(x, x)
    keep = min(int((1 - pval) * affinity.shape[0]), affinity.shape[0] - min_pnum)
    for row in affinity:
        row[np.argsort(row)[:keep]] = 0
    affinity = 0.5 * (affinity + affinity.T)
    np.fill_diagonal(affinity, 0)
    laplacian = -affinity
    laplacian[np.diag_indices_from(laplacian)] = np.abs(affinity).sum(axis=1)
    size = laplacian.shape[0]
    values, vectors = scipy.sparse.linalg.eigsh(laplacian, k=min(max_speakers + 1, size), which="SM", v0=np.ones(size))
    gaps = np.diff(values[min_speakers - 1 : max_speakers + 1].astype(float))
    speakers = int(np.argmax(gaps)) + min_speakers
    return k_means(vectors[:, :speakers], speakers, random_state=0)[1]


def agglomerative(x, threshold=0.4):
    """Average-linkage clustering on cosine similarity, stopping at `threshold`; used for fewer than 40 windows."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    tree = linkage(squareform(-cosine(x, x), checks=False), method="average")
    adjust = abs(tree[:, 2].min())
    tree[:, 2] += adjust
    return fcluster(tree, -threshold + adjust, criterion="distance") - 1


def cluster(x, small=40, min_size=4, merge=0.8):
    """Cluster labels for voiceprints `x` (n, d)."""
    if x.shape[0] <= 1:
        return np.zeros(x.shape[0], dtype=int)
    labels = np.asarray(agglomerative(x) if x.shape[0] < small else spectral(x)).copy()
    # Fold clusters of `min_size` windows or fewer into the nearest bigger one.
    names, sizes = np.unique(labels, return_counts=True)
    minor, major = names[sizes <= min_size], names[sizes > min_size]
    if len(minor):
        if not len(major):
            return np.zeros_like(labels)
        centres = np.stack([x[labels == c].mean(axis=0) for c in major])
        for i in np.flatnonzero(np.isin(labels, minor)):
            labels[i] = major[int(cosine(x[i][None], centres).argmax())]
    # Merge the two closest clusters while their centroids are at least `merge` alike.
    while True:
        names = np.unique(labels)
        if len(names) == 1:
            break
        centres = np.stack([x[labels == c].mean(axis=0) for c in names])
        affinity = np.triu(cosine(centres, centres), 1)
        i, j = np.unravel_index(np.argmax(affinity), affinity.shape)
        if affinity[i, j] < merge:
            break
        labels[labels == names[j]] = names[i]
    return labels


def speech_spans(count, frames):
    """Spans where the segmentation model hears anyone: from the middle of the first such frame to the middle of the
    first silent one after it (the last frame closes an open span)."""
    spans, start = [], None
    for i, c in enumerate(count):
        if c == 0 or i == len(count) - 1:
            if start is not None:
                spans.append([start, frames[i].middle])
                start = None
        elif start is None:
            start = frames[i].middle
    return spans


def add_overlap(turns, speakers, segmentation):
    """(frames, speakers) 0/1 activity: per chunk, the model's local speakers matched to the clusters by shared frames
    (Hungarian), summed over chunks; each frame keeps the `count` most active clusters (frames the model calls silent
    keep the clustering's own label)."""
    from scipy.optimize import linear_sum_assignment

    frames, count = segmentation.count_frames, np.asarray(segmentation.count).reshape(-1)
    size = len(count)
    clustered = np.zeros((size, speakers))
    for start, end, label in turns:
        half = frames.duration / 2
        clustered[frames.closest_frame(start + half) : frames.closest_frame(end + half), label] = 1
    activity = np.zeros((size, speakers))
    _, per_chunk, local = segmentation.multilabel.shape
    for i, data in enumerate(segmentation.multilabel):
        first = frames.closest_frame(segmentation.chunks[i].start + frames.duration / 2)
        mine = clustered[first : first + per_chunk]
        mine = np.pad(mine, ((0, per_chunk - len(mine)), (0, 0)))
        aligned = np.zeros((per_chunk, speakers))
        cost = np.array(
            [
                [(data[:, j].astype(int) & d.astype(int)).sum() for d in mine.T]
                if data[:, j].sum() > 0
                else [-1] * speakers
                for j in range(local)
            ]
        )
        rows, cols = linear_sum_assignment(-cost)
        for r, c in zip(rows, cols, strict=True):
            if cost[r, c] > 0:
                aligned[:, c] = np.maximum(data[:, r], aligned[:, c])
        activity[first : first + per_chunk] += aligned[: max(0, size - first)]
    ranked = np.argsort(-activity, axis=-1)
    binary = np.zeros_like(activity)
    for t in range(size):
        for s in ranked[t, : min(speakers, int(count[t]))]:
            if activity[t, s] > 0:
                binary[t, s] = 1.0
    fill = (binary.sum(-1) == 0) & (clustered.sum(-1) != 0)
    binary[fill] = clustered[fill]
    return binary


def binary_turns(binary, times, threshold=0.5):
    """Turns from a (frames, speakers) activity matrix sampled at `times`."""
    turns = []
    for label, scores in enumerate(binary.T):
        start, active = times[0], scores[0] > threshold
        for t, y in zip(times[1:], scores[1:], strict=True):
            if active and y < threshold:
                turns.append((round(start, 3), round(t, 3), label))
                active = False
            elif not active and y > threshold:
                start, active = t, True
        if active:
            turns.append((round(start, 3), round(times[-1], 3), label))
    return sorted(turns, key=lambda turn: turn[0])


class Diarizer:
    """`vad`: a funasr FSMN VAD AutoModel with its default settings; `speaker`: path of 3D-Speaker's
    campplus_cn_en_common.pt; `segmenter`: segmentation.Segmenter (None to skip overlap detection)."""

    def __init__(self, vad, speaker, segmenter, device):
        import torch
        import torchaudio.compliance.kaldi as kaldi
        from funasr.models.campplus.model import CAMPPlus

        self.torch, self.device, self.vad, self.segmenter = torch, torch.device(device), vad, segmenter
        self.model = CAMPPlus(feat_dim=80, embedding_size=192)
        self.model.load_state_dict(torch.load(speaker, map_location="cpu", weights_only=True))
        self.model.eval().to(self.device)

        def fbank(wav):
            feat = kaldi.fbank(wav, num_mel_bins=80, sample_frequency=SAMPLE_RATE, dither=0)
            return feat - feat.mean(0, keepdim=True)

        self.fbank = fbank

    def embed(self, wav, spans):
        torch = self.torch
        clips = [wav[0, int(b * SAMPLE_RATE) : int(e * SAMPLE_RATE)] for b, e in spans]
        longest = max(clip.shape[0] for clip in clips)
        batch = torch.stack([circle_pad(clip, longest) for clip in clips]).unsqueeze(1)
        found = []
        with torch.no_grad():
            for i in range(0, len(clips), BATCH):
                part = batch[i : i + BATCH].to(self.device)
                found.append(self.model(torch.vmap(self.fbank)(part)).cpu())
        return torch.cat(found).numpy()

    def __call__(self, samples):
        # The evaluated runs had TF32 off on CUDA throughout (pyannote turns it off for good on import); keep the
        # voiceprints the same, and leave the setting as found for the rest of the pack.
        torch = self.torch
        saved = torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32
        torch.backends.cuda.matmul.allow_tf32 = torch.backends.cudnn.allow_tf32 = False
        try:
            return self.diarize(samples)
        finally:
            torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32 = saved

    def diarize(self, samples):
        torch = self.torch
        wav = torch.from_numpy(np.asarray(samples, dtype=np.float32))[None]
        found = self.vad.generate(input=wav[0], cache={}, disable_pbar=True)[0]["value"]
        spans = [[b / 1000, e / 1000] for b, e in found]
        segmentation = self.segmenter(wav) if self.segmenter is not None else None
        if segmentation is not None:
            count = np.asarray(segmentation.count).reshape(-1)
            spans = merge_spans(spans, speech_spans(count, segmentation.count_frames))
        pieces = [w for b, e in spans for w in windows(b, e)]
        if not pieces:
            return []
        labels = cluster(self.embed(wav, pieces))
        turns = compress([[b, e, int(label)] for (b, e), label in zip(pieces, labels, strict=True)])
        if segmentation is None:
            return [(round(b, 3), round(e, 3), label) for b, e, label in turns]
        binary = add_overlap(turns, int(labels.max()) + 1, segmentation)
        frames = segmentation.count_frames
        return binary_turns(binary, [frames[i].middle for i in range(binary.shape[0])])
