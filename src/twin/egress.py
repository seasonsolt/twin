"""Outbound backend classification for transparent status displays."""

from __future__ import annotations

import os
from typing import Any

from .config import (
    ASRSettings,
    BackendSettings,
    EmbedSettings,
    LLMSettings,
    Settings,
    TTSSettings,
    VideoSettings,
    VisionSettings,
    egress_of,
)


def configured_backends(settings: Settings) -> list[BackendSettings]:
    return [
        settings.llm,
        settings.embed,
        settings.tts,
        settings.asr,
        settings.video,
        *settings.judges,
        *([settings.vision] if settings.vision.command else []),
        *([settings.chat_llm] if settings.chat_llm is not None else []),
    ]


def _is_configured(section: BackendSettings) -> bool:
    if isinstance(section, VideoSettings):
        return section.provider == "remote" and bool(section.command)
    if isinstance(section, VisionSettings):
        return bool(section.command and section.command.strip())
    if isinstance(section, ASRSettings) and section.provider == "command":
        return bool(section.command and section.command.strip())
    if section.provider in {"silent", "hashing"}:
        return False
    if isinstance(section, LLMSettings) and section.provider in {"anthropic", "claude_cli"}:
        return True
    endpoint = section.base_url
    if isinstance(section, (LLMSettings, EmbedSettings)):
        endpoint = endpoint or os.environ.get("OPENAI_BASE_URL")
    if not endpoint or not endpoint.strip():
        return False
    if section.provider == "openai_compat" and isinstance(section, (LLMSettings, TTSSettings, ASRSettings)):
        return bool(section.model and section.model.strip())
    return True


def egress_status(settings: Settings, *, external_only: bool = False) -> list[dict[str, Any]]:
    rows = []
    for index, section in enumerate(configured_backends(settings)):
        info = egress_of(section)
        if external_only and (not _is_configured(section) or not info.external):
            continue
        rows.append(
            {
                "kind": "chat_llm"
                if settings.chat_llm is not None and section is settings.chat_llm
                else "judge"
                if external_only and 5 <= index < 5 + len(settings.judges)
                else info.kind,
                "provider": section.provider,
                "host": info.host,
                "external": info.external,
                "declared": info.declared,
            }
        )
    return rows
