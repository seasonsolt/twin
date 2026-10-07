"""Render presentation contracts without knowing upstream types or vendor fields.

Long speech segments keep ordered, independently playable parts rather than concatenating
compressed streams. Timing coordinates are local to each part; missing durations stay unknown.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import os
import struct
import tempfile
from collections.abc import Callable
from html import escape
from pathlib import Path

from ..util import fingerprint, private_directory
from .lipsync import lipsync_for
from .schema import (
    AudioManifest,
    AudioPart,
    AudioRender,
    AudioSegment,
    MediaManifest,
    MediaScript,
    SpeechRequest,
    SpeechResult,
    SynthCapabilities,
)
from .speech_text import SPEECH_SEGMENT_VERSION, SPEECH_TEXT_VERSION, speech_text, speech_text_spans
from .tts import MediaUnavailable, SpeechSynthesizer

EXPORT_CSP = (
    "default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; "
    "object-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)


def export_html(script: MediaScript, *, clock: Callable[[], dt.datetime]) -> str:
    """Render escaped text and inert JSON metadata using an injected creation clock."""
    manifest = MediaManifest(
        source_fingerprint=script.source_fingerprint,
        created_at=clock(),
    )
    data = manifest.model_dump_json().replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    segments = "".join(f'<p class="{s.kind}">{escape(s.text)}</p>' for s in script.segments)
    citations = "".join(f"<li>{escape(c.ref_id)}：{escape(c.reason)}</li>" for c in script.citations)
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="ai-generated" content="true"><meta name="generator" content="twin">'
        '<meta name="referrer" content="no-referrer">'
        f'<meta http-equiv="Content-Security-Policy" content="{escape(EXPORT_CSP)}">'
        "<title>分身回答回放</title><style>"
        "body{margin:0;padding:2rem 1rem;font-family:system-ui;overflow-wrap:anywhere}"
        "main{max-width:50rem;margin:auto}p{white-space:pre-wrap}.notice{font-weight:bold}"
        "</style></head><body><main>"
        f"<h1>{escape(script.persona_name)} · 分身回答回放</h1>"
        f"<p>资料截至：{escape(str(script.as_of or '未限定'))} · 模型自评置信度：{script.confidence}</p>"
        f"{segments}<h2>回答依据</h2><p>引用属于整份回答，不代表逐句对应。</p><ul>{citations}</ul>"
        f'<script type="application/json" id="media-manifest">{data}</script>'
        "</main></body></html>"
    )


def _split_text(text: str, max_chars: int) -> list[str]:
    """Prefer sentence/comma boundaries, hard-splitting only unpunctuated overlong runs."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    pieces: list[str] = []
    while len(text) > max_chars:
        window = text[:max_chars]
        end = max((i + 1 for i, char in enumerate(window) if char in "。！？!?；;…\n\r"), default=0)
        if not end:
            end = max(
                (i + 1 for i, char in enumerate(window) if char in "，,、. " and window[: i + 1].strip()),
                default=max_chars,
            )
        pieces.append(text[:end])
        text = text[end:]
    if text:
        pieces.append(text)
    return pieces


def _speech_parts(text: str, language: str, capabilities: SynthCapabilities) -> list[tuple[str, str]]:
    """Split spoken input within backend limits while retaining ordered original text.

    An expanded numeric span belongs to the part where its pronunciation starts.
    Continuation parts may have empty original text when even one span exceeds the limit.
    """
    spoken = speech_text(text, language, capabilities=capabilities)
    originals: list[str] = []
    for original, normalized in speech_text_spans(text, language, capabilities=capabilities):
        if original == normalized:
            originals.extend(original)
        else:
            originals.extend([original, *([""] * (len(normalized) - 1))])
    parts: list[tuple[str, str]] = []
    offset = 0
    for piece in _split_text(spoken, capabilities.max_chars):
        end = offset + len(piece)
        parts.append(("".join(originals[offset:end]), piece))
        offset = end
    return parts


def _write_private(path: Path, content: bytes) -> None:
    """Replace atomically with an owner-only file, including under a permissive umask."""
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=".audio-")
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(content)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _wav_label(audio: bytes, label: str) -> bytes:
    if len(audio) < 12 or audio[:4] != b"RIFF" or audio[8:12] != b"WAVE":
        raise MediaUnavailable("Invalid WAV for labelling")
    size = struct.unpack_from("<I", audio, 4)[0]
    if size + 8 != len(audio):
        raise MediaUnavailable("Invalid WAV length for labelling")
    comment = label.encode("utf-8") + b"\0"
    info = b"INFOICMT" + struct.pack("<I", len(comment)) + comment + b"\0" * (len(comment) % 2)
    chunk = b"LIST" + struct.pack("<I", len(info)) + info
    body = audio[8:] + chunk
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _mp3_label(audio: bytes, label: str) -> bytes:
    # ID3v2.3 uses a synchsafe tag size, a big-endian frame size and UTF-16 text with BOM.
    payload = b"\x01" + "AI-generated".encode("utf-16") + b"\0\0" + label.encode("utf-16")
    frame = b"TXXX" + struct.pack(">I", len(payload)) + b"\0\0" + payload
    size = len(frame)
    synchsafe = bytes((size >> shift) & 0x7F for shift in (21, 14, 7, 0))
    if audio.startswith(b"ID3"):
        if len(audio) < 10 or audio[3] not in (2, 3, 4) or any(n & 0x80 for n in audio[6:10]):
            raise MediaUnavailable("Invalid MP3 tag for labelling")
        old_size = sum(n << shift for n, shift in zip(audio[6:10], (21, 14, 7, 0), strict=True))
        end = 10 + old_size + (10 if audio[3] == 4 and audio[5] & 0x10 else 0)
        if end >= len(audio):
            raise MediaUnavailable("Invalid MP3 tag length for labelling")
        audio = audio[end:]
    return b"ID3\x03\x00\x00" + synchsafe + frame + audio


def _cached_speech(request: SpeechRequest, synthesizer: SpeechSynthesizer, directory: Path) -> tuple[str, SpeechResult]:
    key = fingerprint(
        {
            "identity": synthesizer.identity,
            "request": request.model_dump(mode="json"),
            "speech_text_version": SPEECH_TEXT_VERSION,
        }
    )
    path = directory / (key + ".json")
    if path.is_file():
        try:
            values = json.loads(path.read_text(encoding="utf-8"))
            values["audio"] = base64.b64decode(values["audio"], validate=True)
            result = SpeechResult.model_validate(values)
            if not result.audio or result.audio_format not in synthesizer.capabilities.audio_formats:
                raise ValueError("Invalid cached result")
            path.chmod(0o600)
            return key, result
        except (ValueError, TypeError, KeyError):
            pass
    result = synthesizer.synthesize(request)
    if not result.audio or result.audio_format not in synthesizer.capabilities.audio_formats:
        raise MediaUnavailable("Speech backend violated the result contract")
    values = result.model_dump(mode="json", exclude={"audio", "extras"})
    values["audio"] = base64.b64encode(result.audio).decode("ascii")
    _write_private(path, json.dumps(values, ensure_ascii=False).encode("utf-8"))
    return key, result


def render_audio(
    script: MediaScript,
    synthesizer: SpeechSynthesizer,
    cache_dir: Path,
    *,
    segments: list[int] | None = None,
) -> AudioRender:
    """Speak notices and non-abstaining speech, cache requests, and label every exported file.

    Cache entries store only normalized contract fields (audio as base64 JSON); exports are
    separately labelled per source, so shared text cannot reuse another answer's fingerprint.
    A backend may return another declared format; the result controls file names and metadata.
    """
    private_directory(cache_dir)
    requests_dir = cache_dir / "requests"
    private_directory(requests_dir)
    formats = synthesizer.capabilities.audio_formats
    if not formats:
        raise MediaUnavailable("Speech backend declares no audio formats")
    rendered: list[AudioSegment] = []
    label = f"AI-generated; twin; source {script.source_fingerprint}"
    for segment in script.segments:
        if segments is not None and segment.index not in segments:
            continue
        if script.abstain and segment.kind != "notice":
            continue
        parts: list[AudioPart] = []
        for text, spoken in _speech_parts(segment.text, synthesizer.voice.language, synthesizer.capabilities):
            request = SpeechRequest(text=spoken, voice=synthesizer.voice, audio_format=formats[0])
            key, result = _cached_speech(request, synthesizer, requests_dir)
            export_key = fingerprint({"request": key, "label": label, "writer": 1})
            file_name = f"{export_key}.{result.audio_format}"
            audio = _wav_label(result.audio, label) if result.audio_format == "wav" else _mp3_label(result.audio, label)
            _write_private(cache_dir / file_name, audio)
            parts.append(
                AudioPart(
                    text=text,
                    file_name=file_name,
                    audio_format=result.audio_format,
                    duration_s=result.duration_s,
                    timings=result.timings,
                    speech_text_version=SPEECH_TEXT_VERSION,
                    spoken_text=spoken,
                    warnings=result.warnings,
                    lipsync=lipsync_for(result),
                )
            )
        rendered.append(AudioSegment(index=segment.index, kind=segment.kind, parts=parts))
    manifest = AudioManifest(
        source_fingerprint=script.source_fingerprint,
        created_at=dt.datetime.now(dt.UTC),
        voice=synthesizer.voice,
        backend=synthesizer.name,
        segments=rendered,
        speech_text_version=SPEECH_TEXT_VERSION,
    )
    manifest_file = (
        fingerprint(
            {
                "script": script.model_dump(mode="json"),
                "identity": synthesizer.identity,
                "voice": synthesizer.voice.model_dump(mode="json"),
                "speech_text_version": SPEECH_TEXT_VERSION,
                "speech_segment_version": SPEECH_SEGMENT_VERSION,
                "capabilities": synthesizer.capabilities.model_dump(mode="json"),
                **({"segments": sorted(set(segments))} if segments is not None else {}),
            }
        )
        + ".audio.json"
    )
    _write_private(cache_dir / manifest_file, manifest.model_dump_json(indent=2).encode("utf-8"))
    return AudioRender(segments=rendered, manifest_file=manifest_file)
