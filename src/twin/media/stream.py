"""Framed PCM playback with an immediate header and atomic, persona-local replay cache."""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import AsyncGenerator
from pathlib import Path

import numpy as np

from ..util import fingerprint, private_directory
from .render import _cached_speech, _speech_parts, _write_private
from .schema import MediaScript, SpeechRequest
from .speech_text import SPEECH_SEGMENT_VERSION, SPEECH_TEXT_VERSION
from .tts import CloudflareMeloTTS, MediaUnavailable, OpenAICompatSpeech, SpeechSynthesizer, wav_pcm

SAMPLE_RATE = 24000


def frame(kind: int, payload: bytes | dict[str, object]) -> bytes:
    data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    return struct.pack(">BI", kind, len(data)) + data


class PCMResampler:
    """Linear interpolation with an integer sample clock, independent of HTTP chunk boundaries."""

    def __init__(self, rate: int) -> None:
        self.rate = rate
        self.received = 0
        self.emitted = 0
        self.previous = 0

    def convert(self, pcm: bytes, *, final: bool = False) -> bytes:
        samples = np.frombuffer(pcm, dtype="<i2")
        start = self.received
        self.received += len(samples)
        values = np.concatenate(([self.previous], samples))
        # Retain one sample for interpolation across chunk boundaries.
        limit = self.received if final else max(0, self.received - 1)
        count = max(0, (limit * SAMPLE_RATE + self.rate - 1) // self.rate - self.emitted)
        positions = (np.arange(count) + self.emitted) * self.rate / SAMPLE_RATE
        result = np.interp(positions, np.arange(start - 1, self.received), values)
        self.emitted += count
        if len(samples):
            self.previous = int(samples[-1])
        return np.rint(result).astype("<i2").tobytes()


async def _fallback_pcm(
    request: SpeechRequest, synth: SpeechSynthesizer, directory: Path
) -> AsyncGenerator[tuple[int, bytes]]:
    if isinstance(synth, CloudflareMeloTTS):
        result = await synth.synthesize_async(request)
    else:
        _, result = await asyncio.to_thread(_cached_speech, request, synth, directory)
    try:
        rate, pcm = wav_pcm(result.audio)
    except MediaUnavailable:
        # Other providers may return compressed audio; normalize via the existing ffmpeg dependency.
        try:
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                str(SAMPLE_RATE),
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            raise MediaUnavailable("Cannot decode speech audio") from None
        try:
            pcm, _ = await process.communicate(result.audio)
            if process.returncode or not pcm:
                raise MediaUnavailable("Cannot decode speech audio")
            rate = SAMPLE_RATE
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    for offset in range(0, len(pcm), 8192):
        yield rate, pcm[offset : offset + 8192]


async def stream_audio(script: MediaScript, synth: SpeechSynthesizer, cache_dir: Path) -> AsyncGenerator[bytes]:
    directory = cache_dir / "requests"
    private_directory(cache_dir)
    private_directory(directory)
    key = fingerprint(
        {
            "stream_version": 1,
            "identity": synth.identity,
            "voice": synth.voice.model_dump(mode="json"),
            "segments": [segment.model_dump(mode="json") for segment in script.segments],
            "speech_text_version": SPEECH_TEXT_VERSION,
            "speech_segment_version": SPEECH_SEGMENT_VERSION,
        }
    )
    path = directory / (key + ".pcm-stream")
    if path.is_file() and not path.is_symlink():
        with path.open("rb") as cached:
            while chunk := cached.read(32768):
                yield chunk
                await asyncio.sleep(0)
        return
    capabilities = await asyncio.to_thread(lambda: synth.capabilities)
    if not capabilities.audio_formats:
        raise MediaUnavailable("Speech backend declares no audio formats")
    assembled = bytearray()
    size = 0
    for segment in script.segments:
        meta = frame(1, {"segment": segment.index, "caption": segment.text})
        assembled.extend(meta)
        yield meta
        for _, spoken in _speech_parts(segment.text, synth.voice.language, capabilities):
            request = SpeechRequest(text=spoken, voice=synth.voice, audio_format=capabilities.audio_formats[0])
            chunks = (
                synth.stream_pcm(request)
                if isinstance(synth, OpenAICompatSpeech)
                else _fallback_pcm(request, synth, directory)
            )
            converter: PCMResampler | None = None
            try:
                async for rate, pcm in chunks:
                    if converter is None:
                        converter = PCMResampler(rate)
                    elif converter.rate != rate:
                        raise MediaUnavailable("Speech sample rate changed")
                    data = converter.convert(pcm)
                    if data:
                        encoded = frame(2, data)
                        size += len(data)
                        assembled.extend(encoded)
                        yield encoded
                if converter is not None:
                    data = converter.convert(b"", final=True)
                    if data:
                        encoded = frame(2, data)
                        size += len(data)
                        assembled.extend(encoded)
                        yield encoded
            finally:
                await chunks.aclose()
    ending = frame(3, {"duration_s": size / (SAMPLE_RATE * 2)})
    assembled.extend(ending)
    await asyncio.to_thread(_write_private, path, bytes(assembled))
    yield ending
