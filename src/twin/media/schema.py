"""Versioned, frozen contracts for labelled AI presentations."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION: Final = 1
EXPLICIT_LABEL: Final = "AI 合成 · 模拟推演，不代表本人意见"
OPENING_NOTICE = "以下内容由 AI 合成，是模拟推演，不代表本人意见。"
CHAT_NOTICE: Final = (
    "分身以本人身份、第一人称作答，只依据人格档案和本人原话；"
    "没有依据时会直说并标注“需要本人确认”。回复是模拟，不代表本人意见。"
)


def disclaimer(name: str, external: bool) -> str:
    storage = "部分数据经配置的外部服务处理，详见页面顶部的出境提示。" if external else "数据只保存在本机。"
    return f"所有推演结果均为模拟，供个人使用参考，不代表{name}本人的意见或决定。{storage}"


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
    voices: list[str] | None = None


class LipSyncTrack(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    fps: int = Field(default=25, gt=0, strict=True)
    levels: list[Annotated[int, Field(ge=0, le=3, strict=True)]] = Field(default_factory=list)
    source: Literal["timings", "energy", "pattern"]

    @model_validator(mode="after")
    def length_cap(self) -> LipSyncTrack:
        if len(self.levels) > self.fps * 600:
            raise ValueError("口型轨不能超过 600 秒")
        return self


class AvatarSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    avatar_id: str
    label: Literal["AI 合成 · 模拟推演，不代表本人意见"] = EXPLICIT_LABEL
    palette: dict[str, str]
    mouth_states: Literal[4] = 4
    stylized: Literal[True] = True

    @field_validator("palette")
    @classmethod
    def flat_palette(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) != {"skin", "hair", "outfit", "background", "accent"} or any(
            re.fullmatch(r"#[0-9a-fA-F]{6}", color) is None for color in value.values()
        ):
            raise ValueError("形象仅接受 skin、hair、outfit、background、accent 五种十六进制颜色")
        return value


AVATAR_PRESETS: dict[str, AvatarSpec] = {
    "default": AvatarSpec(
        avatar_id="default",
        palette={
            "skin": "#F4CFAC",
            "hair": "#57477D",
            "outfit": "#447B91",
            "background": "#E8F1F3",
            "accent": "#C55C7D",
        },
    ),
    "ink": AvatarSpec(
        avatar_id="ink",
        palette={
            "skin": "#DBDFE8",
            "hair": "#34364F",
            "outfit": "#676D91",
            "background": "#F1F0F7",
            "accent": "#925F9F",
        },
    ),
    "dawn": AvatarSpec(
        avatar_id="dawn",
        palette={
            "skin": "#FFE1AC",
            "hair": "#AB5E71",
            "outfit": "#CB8055",
            "background": "#FFF3DE",
            "accent": "#7069A6",
        },
    ),
}


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
    lipsync: LipSyncTrack | None = None


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


class VideoSegment(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    id: str = Field(pattern=r"^s[0-9]+$")
    text: str
    heard: str
    cer: float = Field(ge=0, allow_inf_nan=False)


class VideoResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal[1] = SCHEMA_VERSION
    output: Path
    duration_s: float = Field(ge=0, allow_inf_nan=False)
    segments: list[VideoSegment] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


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
