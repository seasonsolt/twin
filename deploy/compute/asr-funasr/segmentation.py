"""Speaker segmentation with the pyannote ``community-1`` model, without pyannote.

A self-contained port of what 3D-Speaker's ``speakerlab/bin/infer_diarization.py`` gets from pyannote.audio 4.0.7
for the segmentation model of ``pyannote/speaker-diarization-community-1``::

    seg = Inference(model, duration=10.0, step=1.0, skip_aggregation=True, batch_size=32, device=device)
    segmentations = seg({"waveform": wav, "sample_rate": 16000})
    count = Inference.aggregate(np.sum(segmentations, axis=-1, keepdims=True), model.receptive_field,
                                hamming=False, missing=0.0, skip_average=False)
    count.data = np.rint(count.data).astype(np.uint8)

Only numpy, torch and safetensors are needed. The weights are the checkpoint's tensors converted to safetensors
(``weights/segmentation-community-1.safetensors``) and loaded with ``strict=True``; the hyper-parameters below are
copied from the checkpoint. Numbers match pyannote bit for bit on the same device, batch size and torch build: the
model runs the same torch ops in the same order, chunks are batched the same way, and TF32 is off on CUDA as
pyannote's ``fix_reproducibility`` does (here only for the duration of the call, pyannote leaves it off for good).

API
---
``Segmenter(weights, device="cpu", batch_size=32)`` loads the model; calling it on a float32 mono 16 kHz waveform
(``np.ndarray`` or ``torch.Tensor``, shape ``[T]`` or ``[1, T]``) returns a :class:`Segmentation`:

- ``chunks``: :class:`Window` of the 10 s chunks (start 0, step 1 s), i.e. ``segmentations.sliding_window``;
  chunk ``i`` is ``chunks[i]`` (``.start``, ``.end``, ``.middle``).
- ``multilabel``: float32 ``[num_chunks, 589, 3]`` of 0/1 per chunk frame and local speaker, i.e.
  ``segmentations.data``; ``for i, data in enumerate(seg.multilabel)`` with ``chunks[i]`` replaces
  ``for c, data in segmentations``.
- ``frames``: :class:`Window` of the model's output frames, i.e. ``model.receptive_field``
  (start 0, duration 991 / 16000 s, step 270 / 16000 s).
- ``count``: uint8 ``[num_frames, 1]``, number of speakers per frame, i.e. ``count.data``.
- ``count_frames``: :class:`Window` of ``count``, i.e. ``count.sliding_window`` (``len(count)`` is
  ``seg.count.shape[0]``; ``count.sliding_window[t].middle`` is ``seg.count_frames[t].middle``).
- ``log_probs``: float32 ``[num_chunks, 589, 7]`` powerset log-probabilities before binarization, only when the
  Segmenter is called with ``keep_log_probs=True`` (else ``None``).

:class:`Window` mirrors ``pyannote.core.SlidingWindow`` for what 3D-Speaker uses: ``start``, ``duration``,
``step``, ``closest_frame(t)`` and ``window[i]`` returning a :class:`Span` with ``start``, ``end`` and ``middle``
computed with the same float operations as pyannote.
"""

import contextlib
from dataclasses import dataclass
from itertools import combinations, pairwise
from pathlib import Path

import numpy as np
import torch
import torch.nn.functional as F
from safetensors.torch import load_file
from torch import nn

SAMPLE_RATE = 16000
# Specifications of the checkpoint: 10 s chunks, 3 local speakers, at most 2 at once (7 powerset classes).
CHUNK_DURATION = 10.0
CHUNK_STEP = 0.1 * CHUNK_DURATION
NUM_SPEAKERS = 3
MAX_SPEAKERS_PER_FRAME = 2
# Hyper-parameters of the checkpoint (PyanNet: SincNet stride 10, 4 bidirectional LSTM layers of 128, 2 linear).
SINC_FILTERS = 80
SINC_KERNEL = 251
SINC_STRIDE = 10
SINC_MIN_LOW_HZ = 50
SINC_MIN_BAND_HZ = 50
LSTM_HIDDEN = 128
LSTM_LAYERS = 4
LINEAR_HIDDEN = 128
LINEAR_LAYERS = 2
# SincNet's convolution and pooling stack, used for the frame count and the receptive field.
_KERNELS = (SINC_KERNEL, 3, 5, 3, 5, 3)
_STRIDES = (SINC_STRIDE, 3, 1, 3, 1, 3)


@dataclass(frozen=True)
class Span:
    """One position of a :class:`Window` (``pyannote.core.Segment``)."""

    start: float
    end: float

    @property
    def middle(self) -> float:
        return 0.5 * (self.start + self.end)


@dataclass(frozen=True)
class Window:
    """Infinite sliding window, as ``pyannote.core.SlidingWindow`` with ``end=None``."""

    start: float
    duration: float
    step: float

    def closest_frame(self, t: float) -> int:
        """Index of the position whose middle is closest to ``t`` seconds."""
        return int(np.rint((t - self.start - 0.5 * self.duration) / self.step))

    def __getitem__(self, i: int) -> Span:
        start = self.start + i * self.step
        return Span(start, start + self.duration)


@dataclass
class Segmentation:
    """Output of :class:`Segmenter`; see the module docstring."""

    chunks: Window
    multilabel: np.ndarray
    frames: Window
    count: np.ndarray
    count_frames: Window
    log_probs: np.ndarray | None = None


def _receptive_field_size(num_frames: int) -> int:
    size = num_frames
    for kernel, stride in reversed(list(zip(_KERNELS, _STRIDES, strict=True))):
        size = kernel + (size - 1) * stride
    return size


def _receptive_field_center(frame: int) -> int:
    center = frame
    for kernel, stride in reversed(list(zip(_KERNELS, _STRIDES, strict=True))):
        center = center * stride + (kernel - 1) // 2
    return center


def num_frames(num_samples: int) -> int:
    """Number of output frames of the model for ``num_samples`` input samples."""
    frames = num_samples
    for kernel, stride in zip(_KERNELS, _STRIDES, strict=True):
        frames = 1 + (frames - kernel) // stride
    return frames


def receptive_field() -> Window:
    """Window of the model's output frames (``Model.receptive_field``)."""
    size = _receptive_field_size(1)
    step = _receptive_field_size(2) - size
    start = _receptive_field_center(0) - (size - 1) / 2
    return Window(start=start / SAMPLE_RATE, duration=size / SAMPLE_RATE, step=step / SAMPLE_RATE)


class _ParamSincFB(nn.Module):
    """asteroid_filterbanks.ParamSincFB: band-pass sinc filters, cosine and sine halves."""

    def __init__(self) -> None:
        super().__init__()
        half = SINC_FILTERS // 2
        self.low_hz_ = nn.Parameter(torch.zeros(half, 1))
        self.band_hz_ = nn.Parameter(torch.zeros(half, 1))
        self.register_buffer("window_", torch.zeros(SINC_KERNEL // 2))
        self.register_buffer("n_", torch.zeros(1, SINC_KERNEL // 2))

    def filters(self) -> torch.Tensor:
        low = SINC_MIN_LOW_HZ + torch.abs(self.low_hz_)
        high = torch.clamp(low + SINC_MIN_BAND_HZ + torch.abs(self.band_hz_), SINC_MIN_LOW_HZ, SAMPLE_RATE / 2)
        return torch.cat([self._make(low, high, cosine=True), self._make(low, high, cosine=False)], dim=0)

    def _make(self, low: torch.Tensor, high: torch.Tensor, cosine: bool) -> torch.Tensor:
        band = (high - low)[:, 0]
        ft_low = torch.matmul(low, self.n_)
        ft_high = torch.matmul(high, self.n_)
        if cosine:
            left = ((torch.sin(ft_high) - torch.sin(ft_low)) / (self.n_ / 2)) * self.window_
            center = 2 * band.view(-1, 1)
            right = torch.flip(left, dims=[1])
        else:
            left = ((torch.cos(ft_low) - torch.cos(ft_high)) / (self.n_ / 2)) * self.window_
            center = torch.zeros_like(band.view(-1, 1))
            right = -torch.flip(left, dims=[1])
        band_pass = torch.cat([left, center, right], dim=1)
        band_pass = band_pass / (2 * band[:, None])
        return band_pass.view(SINC_FILTERS // 2, 1, SINC_KERNEL)


class _SincEncoder(nn.Module):
    """asteroid_filterbanks.Encoder around ParamSincFB, for (batch, 1, time) input."""

    def __init__(self) -> None:
        super().__init__()
        self.filterbank = _ParamSincFB()

    def forward(self, waveforms: torch.Tensor) -> torch.Tensor:
        return F.conv1d(waveforms, self.filterbank.filters(), stride=SINC_STRIDE, padding=0)


class _SincNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.wav_norm1d = nn.InstanceNorm1d(1, affine=True)
        self.conv1d = nn.ModuleList([_SincEncoder(), nn.Conv1d(SINC_FILTERS, 60, 5), nn.Conv1d(60, 60, 5)])
        self.pool1d = nn.ModuleList([nn.MaxPool1d(3, stride=3) for _ in range(3)])
        self.norm1d = nn.ModuleList([nn.InstanceNorm1d(n, affine=True) for n in (SINC_FILTERS, 60, 60)])

    def forward(self, waveforms: torch.Tensor) -> torch.Tensor:
        outputs = self.wav_norm1d(waveforms)
        for c, (conv1d, pool1d, norm1d) in enumerate(zip(self.conv1d, self.pool1d, self.norm1d, strict=True)):
            outputs = conv1d(outputs)
            if c == 0:
                outputs = torch.abs(outputs)
            outputs = F.leaky_relu(norm1d(pool1d(outputs)))
        return outputs


class PyanNet(nn.Module):
    """SincNet > LSTM > feed forward > classifier, with log-softmax over the powerset classes."""

    def __init__(self) -> None:
        super().__init__()
        self.sincnet = _SincNet()
        self.lstm = nn.LSTM(60, LSTM_HIDDEN, num_layers=LSTM_LAYERS, bidirectional=True, batch_first=True)
        sizes = [2 * LSTM_HIDDEN] + [LINEAR_HIDDEN] * LINEAR_LAYERS
        self.linear = nn.ModuleList([nn.Linear(a, b) for a, b in pairwise(sizes)])
        self.classifier = nn.Linear(LINEAR_HIDDEN, len(_powerset_classes()))

    def forward(self, waveforms: torch.Tensor) -> torch.Tensor:
        outputs = self.sincnet(waveforms)
        outputs, _ = self.lstm(outputs.permute(0, 2, 1))
        for linear in self.linear:
            outputs = F.leaky_relu(linear(outputs))
        return F.log_softmax(self.classifier(outputs), dim=-1)


def _powerset_classes() -> list[tuple[int, ...]]:
    return [s for size in range(MAX_SPEAKERS_PER_FRAME + 1) for s in combinations(range(NUM_SPEAKERS), size)]


def _powerset_mapping() -> torch.Tensor:
    """(7, 3) matrix: row k marks the speakers active in powerset class k (pyannote's Powerset.mapping)."""
    classes = _powerset_classes()
    mapping = torch.zeros(len(classes), NUM_SPEAKERS)
    for k, speakers in enumerate(classes):
        mapping[k, list(speakers)] = 1
    return mapping


@contextlib.contextmanager
def _no_tf32(device: torch.device):
    if device.type != "cuda":
        yield
        return
    saved = torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    try:
        yield
    finally:
        torch.backends.cuda.matmul.allow_tf32, torch.backends.cudnn.allow_tf32 = saved


def aggregate_count(multilabel: np.ndarray, chunks: Window, frames: Window) -> tuple[np.ndarray, Window]:
    """Speakers per frame over the whole file: overlap-add of each chunk's speaker count, averaged, rounded.

    ``Inference.aggregate(np.sum(segmentations, -1, keepdims=True), frames, hamming=False, missing=0.0,
    skip_average=False)`` followed by ``np.rint(...).astype(np.uint8)``, with the same dtypes at every step.
    """
    scores = np.sum(multilabel, axis=-1, keepdims=True)
    num_chunks, frames_per_chunk, num_classes = scores.shape
    frames = Window(start=chunks.start, duration=frames.duration, step=frames.step)
    hamming_window = np.ones((frames_per_chunk, 1))  # hamming=False
    warm_up_window = np.ones((frames_per_chunk, 1))  # warm_up=(0.0, 0.0)
    last_end = chunks.start + chunks.duration + (num_chunks - 1) * chunks.step
    total = frames.closest_frame(last_end + 0.5 * frames.duration) + 1
    summed = np.zeros((total, num_classes), dtype=np.float32)
    overlapping = np.zeros((total, num_classes), dtype=np.float32)
    covered = np.zeros((total, num_classes), dtype=np.float32)
    for i in range(num_chunks):
        score = scores[i]
        mask = 1 - np.isnan(score)
        np.nan_to_num(score, copy=False, nan=0.0)
        first = frames.closest_frame(chunks[i].start + 0.5 * frames.duration)
        rows = slice(first, first + frames_per_chunk)
        summed[rows] += score * mask * hamming_window * warm_up_window
        overlapping[rows] += mask * hamming_window * warm_up_window
        covered[rows] = np.maximum(covered[rows], mask)
    average = summed / np.maximum(overlapping, 1e-12)
    average[covered == 0.0] = 0.0
    return np.rint(average).astype(np.uint8), frames


class Segmenter:
    """Sliding-window speaker segmentation; ``Segmenter(weights, device)(waveform)`` -> :class:`Segmentation`."""

    def __init__(self, weights: Path | str, device: torch.device | str = "cpu", batch_size: int = 32) -> None:
        self.device = torch.device(device)
        self.batch_size = batch_size
        self.model = PyanNet()
        self.model.load_state_dict(load_file(str(weights)), strict=True)
        self.model.eval()
        self.model.to(self.device)
        self.mapping = _powerset_mapping().to(self.device)
        self.window_size = round(CHUNK_DURATION * SAMPLE_RATE)
        self.step_size = round(CHUNK_STEP * SAMPLE_RATE)

    def _infer(self, batch: torch.Tensor, log_probs: list[np.ndarray] | None) -> np.ndarray:
        with torch.inference_mode():
            outputs = self.model(batch.to(self.device))
            hard = F.one_hot(torch.argmax(outputs, dim=-1), self.mapping.shape[0]).float()
            multilabel = torch.matmul(hard, self.mapping).cpu().numpy()
        if log_probs is not None:
            log_probs.append(outputs.cpu().numpy())
        return multilabel

    def __call__(self, waveform: np.ndarray | torch.Tensor, keep_log_probs: bool = False) -> Segmentation:
        audio = torch.as_tensor(waveform, dtype=torch.float32)
        if audio.ndim == 1:
            audio = audio[None]
        if audio.ndim != 2 or audio.shape[0] != 1:
            raise ValueError(f"expected a mono waveform of shape [T] or [1, T], got {tuple(audio.shape)}")
        num_samples = audio.shape[1]
        window_size, step_size = self.window_size, self.step_size
        num_chunks = 0
        if num_samples >= window_size:
            chunks = audio.unfold(1, window_size, step_size).permute(1, 0, 2)
            num_chunks = chunks.shape[0]
        has_last_chunk = num_samples < window_size or (num_samples - window_size) % step_size > 0
        log_probs: list[np.ndarray] | None = [] if keep_log_probs else None
        outputs = []
        with _no_tf32(self.device):
            for c in range(0, num_chunks, self.batch_size):
                outputs.append(self._infer(chunks[c : c + self.batch_size], log_probs))
            if has_last_chunk:
                last = audio[:, num_chunks * step_size :]
                last = F.pad(last, (0, window_size - last.shape[1]))
                outputs.append(self._infer(last[None], log_probs))
        multilabel = np.vstack(outputs)
        chunk_window = Window(start=0.0, duration=CHUNK_DURATION, step=CHUNK_STEP)
        frames = receptive_field()
        count, count_frames = aggregate_count(multilabel, chunk_window, frames)
        return Segmentation(
            chunks=chunk_window,
            multilabel=multilabel,
            frames=frames,
            count=count,
            count_frames=count_frames,
            log_probs=np.vstack(log_probs) if log_probs is not None else None,
        )
