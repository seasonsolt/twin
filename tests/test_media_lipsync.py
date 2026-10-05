"""Offline mouth tracks from invented timing spans and generated PCM."""

from __future__ import annotations

import io
import math
import struct
import wave

import pytest

from twin.media.lipsync import (
    LipSyncWavError,
    lipsync_for,
    lipsync_from_timings,
    lipsync_from_wav,
    lipsync_pattern,
)
from twin.media.schema import SpeechResult, WordTiming


def pcm_wav(*, width: int = 2, channels: int = 1, tone: bool = True, gain: float = 1.0) -> bytes:
    rate = 8000
    samples = bytearray()
    for index in range(rate):
        amplitude = math.sin(2 * math.pi * 200 * index / rate) * gain if tone and 0.25 <= index / rate < 0.75 else 0
        sample = bytes([128 + round(amplitude * 100)]) if width == 1 else struct.pack("<h", round(amplitude * 24000))
        samples.extend(sample * channels)
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(rate)
        wav.writeframes(samples)
    return output.getvalue()


@pytest.mark.parametrize("width", [1, 2])
@pytest.mark.parametrize("channels", [1, 2])
def test_silence_and_200_hz_burst(width: int, channels: int) -> None:
    silence = lipsync_from_wav(pcm_wav(width=width, channels=channels, tone=False))
    assert silence.source == "energy" and silence.fps == 25
    assert silence.levels == [0] * 25
    audio = pcm_wav(width=width, channels=channels)
    track = lipsync_from_wav(audio)
    assert len(track.levels) == 25
    assert track.levels[:5] == [0] * 5 and track.levels[-4:] == [0] * 4
    assert track.levels[9:16] == [3] * 7
    assert track == lipsync_from_wav(audio)
    assert track == lipsync_for(SpeechResult(audio=audio, audio_format="mp3"))


def test_quantization_is_relative_to_clip() -> None:
    def clip(scale: int) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(1000)
            wav.writeframes(
                b"".join(struct.pack("<h", round(amplitude * scale)) * 1000 for amplitude in (0, 0.2, 0.5, 1))
            )
        return output.getvalue()

    track = lipsync_from_wav(clip(20000), fps=10)
    assert [track.levels[index] for index in (5, 15, 25, 35)] == [0, 1, 2, 3]
    assert track == lipsync_from_wav(clip(2000), fps=10)


def test_stereo_uses_both_channels_without_cancellation() -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(2)
        wav.setsampwidth(2)
        wav.setframerate(1000)
        wav.writeframes(struct.pack("<hh", 12000, -12000) * 1000)
    assert lipsync_from_wav(output.getvalue()).levels == [3] * 25


def test_timing_path_and_word_gaps() -> None:
    timings = [WordTiming(text="合成", start_s=0.2, end_s=0.6), WordTiming(text="词", start_s=0.8, end_s=0.9)]
    track = lipsync_from_timings(timings, 1.0, fps=10)
    assert track.source == "timings"
    assert track.levels == [0, 0, 2, 2, 3, 3, 0, 0, 2, 0]
    assert track == lipsync_from_timings(timings, 1.0, fps=10)
    result = SpeechResult(audio=pcm_wav(tone=False), timings=timings, duration_s=1)
    assert lipsync_for(result, fps=10) == track
    assert len(lipsync_for(result.model_copy(update={"duration_s": None}), fps=10).levels) == 9
    assert lipsync_from_timings([WordTiming(text="空", start_s=0.5, end_s=0.1)], 1, 10).levels == [0] * 10
    assert lipsync_from_timings([WordTiming(text="越界", start_s=2, end_s=3)], 1, 10).levels == [0] * 10


def test_pattern_fallback_for_mp3_and_unknown_duration() -> None:
    result = SpeechResult(audio=b"\xff\xfb\x90\x00" + b"\0" * 100, audio_format="mp3", duration_s=2)
    track = lipsync_for(result)
    assert track.source == "pattern" and len(track.levels) == 50
    assert set(track.levels) == {0, 1, 2, 3}
    assert track == lipsync_pattern(2) == lipsync_for(result)
    assert len(lipsync_for(result.model_copy(update={"duration_s": None})).levels) == 25
    assert lipsync_pattern(0).levels == []
    assert len(lipsync_pattern(0.01).levels) == 1
    assert len(lipsync_pattern(601, fps=10).levels) == 6000


@pytest.mark.parametrize("width,channels", [(3, 1), (4, 1), (2, 3)])
def test_unsupported_wav_raises_typed_error_and_falls_back(width: int, channels: int) -> None:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(width)
        wav.setframerate(8000)
        wav.writeframes(b"\0" * 8000 * width * channels)
    audio = output.getvalue()
    with pytest.raises(LipSyncWavError):
        lipsync_from_wav(audio)
    assert lipsync_for(SpeechResult(audio=audio, duration_s=1)) == lipsync_pattern(1)


@pytest.mark.parametrize("audio", [b"not-wav", b"RIFF\0\0\0\0WAVE", pcm_wav()[:-100]])
def test_invalid_wav_raises_typed_error(audio: bytes) -> None:
    with pytest.raises(LipSyncWavError):
        lipsync_from_wav(audio)
    assert lipsync_for(SpeechResult(audio=audio, duration_s=1)).source == "pattern"


@pytest.mark.parametrize("duration", [-1, float("inf"), float("nan")])
def test_invalid_duration(duration: float) -> None:
    with pytest.raises(ValueError):
        lipsync_pattern(duration)


@pytest.mark.parametrize("fps", [0, -1, True])
def test_invalid_fps(fps: int) -> None:
    with pytest.raises(ValueError):
        lipsync_from_wav(pcm_wav(), fps)
