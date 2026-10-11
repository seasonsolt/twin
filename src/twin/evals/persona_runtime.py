"""Run public benchmark evidence through the production persona pipeline in private stores."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
import os
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any, Literal

from ..config import Settings, configuration_fingerprint
from ..embed import Embedder
from ..llm import LLM
from ..persona.chat import PersonaChat, index_persona
from ..persona.profile import build_profile
from ..persona.schema import ChatReply, ChatTurn, Expression, ParsedSource, Source, SourceKind
from ..persona.sources import parse_chat, source_id_for
from ..persona.store import PersonaStore
from ..usage import active_recorder, call_stage
from ..util import fingerprint, private_directory

PROTOCOL_VERSION = "production-persona-v1"
IDENTITY_VERSION = "benchmark-user-v1"
TARGET = "Benchmark participant"
LIMITATIONS = [
    "Production extraction and retrieval use target_only=True; assistant-only evidence may not be recalled.",
    "Questionnaire evidence does not grant consent for sensitive facets.",
]


@dataclass(frozen=True)
class SourceInput:
    name: str
    kind: Literal["chat", "questionnaire"]
    # Chat: (role, text, date). Questionnaire: (question/context, answer, date).
    entries: tuple[tuple[str, str, str], ...]
    narrated: bool = False


# Profile building reads these modules; editing any of them invalidates every cached profile, so a cache never
# stands in for a build the current code would do differently. Chat and retrieval code are deliberately absent.
_BUILD_MODULES = (
    "twin.config",
    "twin.llm",
    "twin.util",
    "twin.persona.dimensions",
    "twin.persona.items",
    "twin.persona.profile",
    "twin.persona.questionnaire",
    "twin.persona.schema",
    "twin.persona.sources",
    "twin.persona.store",
    "twin.persona.text",
)


@cache
def build_code_fingerprint() -> str:
    digest = hashlib.sha256()
    for name in _BUILD_MODULES:
        digest.update(Path(importlib.import_module(name).__file__ or "").read_bytes())
    return digest.hexdigest()[:16]


@dataclass(frozen=True)
class ProfileCache:
    """Built profiles kept across runs. ``slot`` (one per repeat) keeps build-to-build variance in the measurement:
    repeat n of every run reuses build n, never one shared build."""

    root: Path
    slot: str

    def path(self, key: str) -> Path:
        return self.root / f"{key}-{build_code_fingerprint()}-{self.slot}.db"

    def save(self, built: Path, key: str) -> None:
        private_directory(self.root)
        target = self.path(key)
        partial = target.with_suffix(".partial")
        with closing(sqlite3.connect(built)) as source, closing(sqlite3.connect(partial)) as copy:
            source.backup(copy)
        partial.chmod(0o600)
        os.replace(partial, target)

    def restore(self, key: str, into: Path) -> bool:
        cached = self.path(key)
        if not cached.exists():
            return False
        with closing(sqlite3.connect(cached)) as source, closing(sqlite3.connect(into)) as copy:
            source.backup(copy)
        into.chmod(0o600)
        return True


class PreparationError(RuntimeError):
    """A cached preparation failure; never answer using a partially built profile."""


def preparation_key(subject: str, sources: tuple[SourceInput, ...], settings: Settings) -> str:
    return fingerprint(
        {
            "subject": subject,
            "sources": [asdict(source) for source in sources],
            "identity": IDENTITY_VERSION,
            "protocol": PROTOCOL_VERSION,
            "llm": settings.llm.model_dump(mode="json"),
            "embed": settings.embed.model_dump(mode="json"),
            "pseudonymize_others": settings.pseudonymize_others,
            "max_workers": settings.max_workers,
        }
    )


def parse_source(source: SourceInput, settings: Settings) -> ParsedSource | None:
    entries = [entry for entry in source.entries if entry[1].strip()]
    if not entries:
        return None
    if source.kind == "chat":
        return parse_chat(
            source.name + ".json",
            json.dumps(
                [
                    {"sender": TARGET if role == "user" else role, "content": text, "date": date}
                    for role, text, date in entries
                ],
                ensure_ascii=False,
            ),
            settings,
            channel=source.name,
            allow_no_target=True,
        )
    raw = json.dumps(entries, ensure_ascii=False)
    sid = source_id_for(SourceKind.QUESTIONNAIRE, source.name, raw)
    expressions = [
        Expression(
            expression_id=f"{sid}#{i:05d}",
            source_id=sid,
            idx=i,
            speaker=TARGET,
            is_target=True,
            text=text,
            context=context,
            channel="wave1-3 self-report questionnaire",
            narrated=source.narrated,
        )
        for i, (context, text, _) in enumerate(entries)
    ]
    return ParsedSource(
        Source(
            source_id=sid,
            kind=SourceKind.QUESTIONNAIRE,
            title=source.name,
            origin=source.name,
            imported_at=dt.datetime.now(dt.UTC).isoformat(),
            n_expressions=len(expressions),
            n_target=len(expressions),
            text_state="raw",
        ),
        expressions,
    )


class PersonaRuntime:
    """One run's disk cache; stores are closed between questions, including failed builds."""

    def __init__(self, settings: Settings, llm: LLM, embedder: Embedder, cache: ProfileCache | None = None) -> None:
        self._temporary = TemporaryDirectory(prefix="twin-public-eval-")
        self.root = Path(self._temporary.name)
        self.root.chmod(0o700)
        self.settings = settings.model_copy(
            deep=True,
            update={
                "db_path": self.root / "unused.db",
                "target_name": TARGET,
                "target_aliases": [],
                "chat_llm": None,
            },
        )
        self.llm, self.embedder, self.cache = llm, embedder, cache
        self._states: dict[str, bool] = {}
        self.metadata: dict[str, Any] = {}

    def close(self) -> None:
        self._temporary.cleanup()

    @property
    def configuration(self) -> str:
        return configuration_fingerprint(
            self.settings, self.llm, self.embedder, [], experiment={"protocol": PROTOCOL_VERSION}
        )

    @contextmanager
    def _stage(self, name: str) -> Iterator[None]:
        start = perf_counter()
        recorder = active_recorder()
        first = len(recorder.rows) if recorder else 0
        try:
            with call_stage("persona." + name):
                yield
        finally:
            rows = recorder.rows[first:] if recorder else []
            self.metadata["stages"][name] = {
                "seconds": perf_counter() - start,
                "calls": len(rows),
                "failed_calls": sum(not row.success for row in rows),
                "known_cost_usd": sum(row.known_cost_usd for row in rows),
                "unknown_cost_calls": sum(row.estimated_cost_usd is None for row in rows),
            }

    def _prepare(self, store: PersonaStore, sources: tuple[SourceInput, ...], settings: Settings) -> None:
        store.set_identity(TARGET, "", None)
        for source in sources:
            parsed = parse_source(source, settings)
            if parsed is not None:
                store.put_source(parsed)
        report = build_profile(store, self.llm, settings)
        if report.degraded:
            self.metadata["preparation_degraded"] = report.degraded
        recorder = active_recorder()
        if report.failures or (recorder is not None and recorder.stop is not None):
            # Content-free: stage, chunk or facet id, error type, stop reason and field paths.
            self.metadata["preparation_failures"] = report.failures
            raise PreparationError("Profile preparation failed")

    def predict(
        self, subject: str, sources: tuple[SourceInput, ...], prompt: str, today: dt.date | None = None
    ) -> ChatReply:
        key = preparation_key(subject, sources, self.settings)
        cached = key in self._states
        self.metadata = {"preparation_key": key, "cache_hit": cached, "stages": {}}
        if cached and not self._states[key]:
            self.metadata["preparation_failure"] = True
            raise PreparationError("Previously failed preparation")
        settings = self.settings.model_copy(update={"db_path": self.root / (key + ".db")})
        try:
            restored = False
            if not cached and self.cache is not None:
                restored = self.cache.restore(key, settings.db_path)
                self.metadata["profile_cache"] = "hit" if restored else "miss"
            with PersonaStore(settings.db_path) as store:
                if not cached:
                    # Save failure first, so parser, constructor and partial-build failures are sticky.
                    self._states[key] = False
                    with self._stage("preparation"):
                        if not restored:
                            self._prepare(store, sources, settings)
                    with self._stage("index"):
                        index_persona(store, self.embedder, settings)
                    # A degraded build retries its merges next time, so it is not frozen into the cache.
                    if self.cache is not None and not restored and "preparation_degraded" not in self.metadata:
                        self.cache.save(settings.db_path, key)
                    self._states[key] = True
                with self._stage("answer"):
                    reply = PersonaChat(store, self.llm, self.embedder, settings).reply(
                        [ChatTurn(role="user", content=prompt)], persist=False, today=today
                    )
                self.metadata.update(reply.model_dump(mode="json"))
                return reply
        except Exception as error:
            if not self._states.get(key, False):
                self._states[key] = False
                self.metadata["preparation_failure"] = True
                raise PreparationError("Persona preparation failed (details hidden)") from error
            raise


def report_system(system: str, retrieval_label: str) -> dict[str, Any]:
    if system not in ("twin", "retrieval"):
        raise ValueError("system must be twin or retrieval")
    return {
        "system": system,
        "system_label": "production Twin persona pipeline" if system == "twin" else retrieval_label,
        "protocol_version": PROTOCOL_VERSION if system == "twin" else "retrieval-v1",
        "limitations": LIMITATIONS if system == "twin" else [],
    }
