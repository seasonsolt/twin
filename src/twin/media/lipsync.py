"""Deterministic, backend-neutral mouth openness for stylized presentations."""

from __future__ import annotations

import io
import math
import struct
import wave
from collections.abc import Sequence

from .schema import LipSyncTrack, SpeechResult, WordTiming


class LipSyncWavError(ValueError):
    """Invalid or unsupported PCM; rendering may use a synthetic pattern instead."""


def _frame_count(duration_s: float, fps: int) -> int:
    if isinstance(fps, bool) or not isinstance(fps, int) or fps <= 0:
        raise ValueError("fps must be a positive integer")
    if not math.isfinite(duration_s) or duration_s < 0:
        raise ValueError("duration must be finite and nonnegative")
    return math.ceil(min(duration_s, 600) * fps)


def lipsync_from_timings(timings: Sequence[WordTiming], duration_s: float, fps: int = 25) -> LipSyncTrack:
    levels = [0] * _frame_count(duration_s, fps)
    for word in timings:
        if word.end_s <= word.start_s or not word.text:
            continue
        start = min(len(levels), math.ceil(word.start_s * fps))
        end = min(len(levels), math.ceil(word.end_s * fps))
        for index in range(start, end):
            character = min(
                len(word.text) - 1, int((index / fps - word.start_s) / (word.end_s - word.start_s) * len(word.text))
            )
            levels[index] = 2 + character % 2
    return LipSyncTrack(fps=fps, levels=levels, source="timings")


def lipsync_from_wav(wav_bytes: bytes, fps: int = 25) -> LipSyncTrack:
    _frame_count(0, fps)
    rms: list[float] = []
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav:
            width, channels, rate = wav.getsampwidth(), wav.getnchannels(), wav.getframerate()
            if width not in (1, 2) or channels not in (1, 2) or wav.getcomptype() != "NONE" or rate <= 0:
                raise LipSyncWavError("Unsupported WAV PCM")
            count = _frame_count(wav.getnframes() / rate, fps)
            for index in range(count):
                start = index * rate // fps
                end = min((index + 1) * rate // fps, wav.getnframes())
                data = wav.readframes(end - start)
                if len(data) != (end - start) * width * channels:
                    raise LipSyncWavError("Truncated WAV PCM")
                samples = (
                    [value - 128 for value in data]
                    if width == 1
                    else [value[0] for value in struct.iter_unpack("<h", data)]
                )
                rms.append(math.sqrt(sum(value * value for value in samples) / len(samples)) if samples else 0.0)
    except (wave.Error, EOFError, OSError, struct.error) as exc:
        raise LipSyncWavError("Invalid WAV PCM") from exc
    smoothed = [sum(rms[max(0, i - 1) : i + 2]) / len(rms[max(0, i - 1) : i + 2]) for i in range(len(rms))]
    ranked = sorted(smoothed)
    reference = ranked[max(0, math.ceil(len(ranked) * 0.95) - 1)] if ranked else 0.0
    reference = reference or max(smoothed, default=0.0)
    levels = (
        [sum(value > reference * threshold for threshold in (0.1, 0.35, 0.7)) for value in smoothed]
        if reference
        else [0] * len(rms)
    )
    return LipSyncTrack(fps=fps, levels=levels, source="energy")


def lipsync_pattern(duration_s: float, fps: int = 25) -> LipSyncTrack:
    rhythm = (0, 1, 2, 3, 2, 1, 0, 2, 3, 1, 0, 0)
    return LipSyncTrack(
        fps=fps,
        levels=[rhythm[(index * 8 // fps) % len(rhythm)] for index in range(_frame_count(duration_s, fps))],
        source="pattern",
    )


def lipsync_for(result: SpeechResult, fps: int = 25) -> LipSyncTrack:
    duration = result.duration_s
    if result.timings:
        if duration is None:
            duration = max(word.end_s for word in result.timings)
        return lipsync_from_timings(result.timings, duration, fps)
    if result.audio[:4] == b"RIFF" and result.audio[8:12] == b"WAVE":
        try:
            return lipsync_from_wav(result.audio, fps)
        except LipSyncWavError:
            pass
    return lipsync_pattern(duration if duration is not None else 1.0, fps)
