"""Layer-9 outbound permission boundary shared by CLI and web entry points."""

from __future__ import annotations

from typing import Any

from .config import BackendSettings, EgressKind, Settings, egress_of
from .identity import Identity
from .persona.store import PersonaStore


class EgressDenied(PermissionError):
    """An external backend has no current ledger grant."""


def require_egress(section: BackendSettings, kind: EgressKind, identity_or_store: Identity | PersonaStore) -> None:
    info = egress_of(section)
    if info.kind != kind:
        raise ValueError("出境后端类型不匹配")
    if not info.external:
        return
    identity = (
        identity_or_store
        if isinstance(identity_or_store, Identity)
        else Identity.from_parts("", [], identity_or_store.consent_events())
    )
    if not identity.granted(f"egress:{kind}"):
        raise EgressDenied(
            f"{kind} 后端（主机：{info.host or '未知'}）为外部服务，尚未获得出境许可；"
            f"请运行 `twin identity grant egress:{kind}`"
        )


def require_configured_egress(settings: Settings, section: BackendSettings) -> None:
    """Read the ledger at construction, not app startup; cached backends need a restart after revoke."""
    info = egress_of(section)
    if info.external:
        with PersonaStore(settings.db_path) as store:
            require_egress(section, info.kind, store)


def configured_backends(settings: Settings) -> list[BackendSettings]:
    return [settings.llm, settings.embed, settings.tts, settings.asr, *settings.judges]


def egress_status(settings: Settings, identity_or_store: Identity | PersonaStore) -> list[dict[str, Any]]:
    identity = (
        identity_or_store
        if isinstance(identity_or_store, Identity)
        else Identity.from_parts("", [], identity_or_store.consent_events())
    )
    return [
        {
            "kind": info.kind,
            "provider": section.provider,
            "host": info.host,
            "external": info.external,
            "declared": info.declared,
            "granted": identity.granted(f"egress:{info.kind}"),
        }
        for section in configured_backends(settings)
        for info in [egress_of(section)]
    ]
