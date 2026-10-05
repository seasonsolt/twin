"""Outbound backend classification for transparent status displays."""

from __future__ import annotations

from typing import Any

from .config import BackendSettings, Settings, egress_of


def configured_backends(settings: Settings) -> list[BackendSettings]:
    return [settings.llm, settings.embed, settings.tts, settings.asr, *settings.judges]


def egress_status(settings: Settings) -> list[dict[str, Any]]:
    return [
        {
            "kind": info.kind,
            "provider": section.provider,
            "host": info.host,
            "external": info.external,
            "declared": info.declared,
        }
        for section in configured_backends(settings)
        for info in [egress_of(section)]
    ]
