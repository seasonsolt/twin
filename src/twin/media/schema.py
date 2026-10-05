"""Versioned, frozen contracts for labelled AI presentations."""

from __future__ import annotations

import datetime as dt
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION: Final = 1
EXPLICIT_LABEL: Final = "AI 合成 · 模拟推演，不代表本人意见"
OPENING_NOTICE = "以下内容由 AI 合成，是模拟推演，不代表本人意见。"


class Segment(BaseModel):
    model_config = ConfigDict(frozen=True)

    index: int = Field(ge=0)
    kind: Literal["notice", "speech"]
    text: str


class MediaCitation(BaseModel):
    model_config = ConfigDict(frozen=True)

    ref_id: str
    reason: str


class PresentableAnswer(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    source_kind: Literal["chat_reply"]
    source_fingerprint: str
    text: str
    abstain: bool
    abstain_reason: str
    confidence: float
    as_of: dt.date | None
    citations: list[MediaCitation]


class MediaScript(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = SCHEMA_VERSION
    source_kind: Literal["chat_reply"]
    source_fingerprint: str
    persona_name: str
    as_of: dt.date | None
    confidence: float
    abstain: bool
    segments: list[Segment]
    citations: list[MediaCitation]
    explicit_label: Literal["AI 合成 · 模拟推演，不代表本人意见"] = EXPLICIT_LABEL


class MediaManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = SCHEMA_VERSION
    generator: Literal["twin"] = "twin"
    ai_generated: Literal[True] = True
    label: Literal["AI 合成 · 模拟推演，不代表本人意见"] = EXPLICIT_LABEL
    source_fingerprint: str
    created_at: dt.datetime


AudioFormat = Literal["wav", "mp3"]


class VoiceSpec(BaseModel):
    """A preset voice, never a cloned identity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    voice_id: str = "default"
    language: str = "zh"
    label: str = "Preset voice"


class SpeechRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    text: str = ""
    voice: VoiceSpec = Field(default_factory=VoiceSpec)
    audio_format: AudioFormat = "wav"


class WordTiming(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    text: str = ""
    start_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)
    end_s: float = Field(default=0.0, ge=0, allow_inf_nan=False)


class SpeechResult(BaseModel):
    """Vendor-specific response fields belong exclusively in extras."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    audio: bytes = b""
    audio_format: AudioFormat = "wav"
    sample_rate: int | None = Field(default=None, gt=0)
    duration_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    timings: list[WordTiming] | None = None
    extras: dict[str, str] = Field(default_factory=dict)
    warnings: list[Literal["possibly-truncated"]] = Field(default_factory=list)


class SynthCapabilities(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    provides_timings: bool = False
    max_chars: int = Field(default=500, gt=0)
    audio_formats: list[AudioFormat] = Field(default=["wav"])
    languages: list[str] = Field(default_factory=lambda: ["zh"])
    streaming: bool = False
    reads_latin_acronyms: bool = True


class AudioPart(BaseModel):
    """One ordered piece of a segment; timings are relative to this file."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    text: str = ""
    file_name: str = ""
    audio_format: AudioFormat = "wav"
    duration_s: float | None = None
    timings: list[WordTiming] | None = None
    speech_text_version: int = Field(default=0, ge=0)
    spoken_text: str = ""
    warnings: list[Literal["possibly-truncated"]] = Field(default_factory=list)


class AudioSegment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    index: int = 0
    kind: Literal["notice", "speech"] = "notice"
    parts: list[AudioPart] = Field(default_factory=list)


class AudioManifest(MediaManifest):
    voice: VoiceSpec = Field(default_factory=VoiceSpec)
    backend: str = "silent"
    segments: list[AudioSegment] = Field(default_factory=list)
    speech_text_version: int = Field(default=0, ge=0)


class AudioRender(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    segments: list[AudioSegment] = Field(default_factory=list)
    manifest_file: str = ""


class TranscriptionRequest(BaseModel):
    """Evaluation-only audio input, independent of the recognition vendor."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    audio: bytes = b""
    audio_format: AudioFormat = "wav"
    language: str = "zh"
    prompt: str | None = None


class Transcription(BaseModel):
    """Normalized recognition output; vendor metadata is opaque to evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    text: str = ""
    language: str | None = None
    duration_s: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    extras: dict[str, str] = Field(default_factory=dict)


class ASRCapabilities(BaseModel):
    """Declared local input limits and supported recognition features."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    audio_formats: list[AudioFormat] = Field(default=["wav", "mp3"])
    languages: list[str] = Field(default_factory=lambda: ["zh"])
    max_audio_bytes: int = Field(default=25 * 1024 * 1024, gt=0)
    supports_prompt: bool = True
    provides_duration: bool = False
    streaming: bool = False
