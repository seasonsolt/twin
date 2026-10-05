"""Local identity and append-only consent ledger endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, ValidationError

from ..config import Settings
from ..egress import egress_status
from ..identity import _BIOMETRIC_ERROR, Decision, Identity
from ..persona.dimensions import FACET_BY_ID, FACETS, requires_consent
from ..persona.profile import consented_facets
from ..persona.store import PersonaStore

_DECISION_LABELS = {Decision.GRANT: "已授权", Decision.REVOKE: "已撤回", Decision.DECLINE: "未授权"}
_REBUILD_HINT = "请运行 `twin persona build`，使细项授权变更生效。"
_EGRESS_HINT = "出境许可在下一进程或下一次懒构造后端时生效；已构造的网页后端需重启，不热更新。"


class ConsentBody(BaseModel):
    scope: str
    decision: Literal["grant", "revoke"]
    note: str = Field(default="", max_length=200)


def register(app: FastAPI, settings: Settings) -> None:
    @app.get("/api/identity")
    def get_identity() -> dict[str, Any]:
        with PersonaStore(settings.db_path) as store:
            events = store.consent_events()
            identity = Identity.from_parts(
                settings.target_name, settings.target_aliases, events, voice=settings.tts.voice
            )
            latest = {event.scope: event for event in events}
            allowed = consented_facets(store)
        scopes = set(latest) | {f"facet:{f.facet_id}" for f in FACETS if requires_consent(f.facet_id)}
        consents: list[dict[str, Any]] = []
        for scope in sorted(scopes):
            event = latest.get(scope)
            facet = FACET_BY_ID.get(scope.removeprefix("facet:")) if scope.startswith("facet:") else None
            derived = facet is not None and facet.facet_id in allowed
            consents.append(
                {
                    "scope": scope,
                    "name": facet.name if facet else scope,
                    "decision": event.decision.value if event else None,
                    "label": _DECISION_LABELS[event.decision] if event else "未记录",
                    "at": event.at.isoformat() if event else None,
                    "origin": event.origin if event else None,
                    "granted": event.decision is Decision.GRANT if event else derived,
                    "derived_decision": ("grant" if derived else "decline") if not event and facet else None,
                }
            )
        return {
            "name": identity.name,
            "aliases": identity.aliases,
            "voice": identity.voice,
            "avatar": settings.avatar.preset,
            "consents": consents,
            "egress": egress_status(settings, identity),
            "biometric": {"voice_clone": False, "face": False, "reason": _BIOMETRIC_ERROR},
        }

    @app.post("/api/identity/consent")
    def change_consent(body: ConsentBody) -> dict[str, Any]:
        try:
            with PersonaStore(settings.db_path) as store:
                event = store.append_consent(body.scope, Decision(body.decision), "web", body.note)
        except ValidationError as error:
            # Only contract messages, never Pydantic's rendered input (which can contain the private note).
            detail = "；".join(e["msg"] for e in error.errors(include_input=False))
            raise HTTPException(status_code=400, detail=detail) from None
        facet = event.scope.startswith("facet:")
        egress = event.scope.startswith("egress:")
        message = f"{event.scope}：{_DECISION_LABELS[event.decision]}（记录 {event.seq}）"
        if facet:
            message += "\n" + _REBUILD_HINT
        if egress:
            message += "\n" + _EGRESS_HINT
        return {
            "seq": event.seq,
            "scope": event.scope,
            "decision": event.decision.value,
            "at": event.at.isoformat(),
            "origin": event.origin,
            "rebuild_needed": facet,
            "restart_needed": False,
            "message": message,
        }
