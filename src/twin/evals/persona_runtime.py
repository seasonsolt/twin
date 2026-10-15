"""Run public benchmark evidence through the production persona pipeline in private stores."""

from __future__ import annotations

import datetime as dt
import hashlib
import importlib
import json
import os
import sqlite3
import threading
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing, contextmanager, nullcontext
from contextvars import copy_context
from dataclasses import asdict, dataclass
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any, Literal

from ..config import Settings, configuration_fingerprint, make_llm
from ..embed import Embedder
from ..llm import LLM, T
from ..persona.chat import PersonaChat, index_persona
from ..persona.profile import build_profile
from ..persona.schema import ChatReply, ChatTurn, Expression, ParsedSource, Source, SourceKind
from ..persona.sources import parse_chat, parse_note, source_id_for
from ..persona.store import PersonaStore
from ..usage import active_recorder, call_stage, collect_calls
from ..util import fingerprint, private_directory, run_parallel

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
    kind: Literal["chat", "questionnaire", "intro"]
    # Chat: (role, text, date). Questionnaire: (question/context, answer, date). Intro: ("", self-introduction, "").
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


# One lock per cached profile across every run of a process: repeats sharing a slot build each profile once.
_BUILD_LOCKS: dict[Path, threading.Lock] = {}
_BUILD_LOCKS_GUARD = threading.Lock()


@dataclass(frozen=True)
class ProfileCache:
    """Built profiles kept across runs. ``slot`` (one per build) keeps build-to-build variance in the measurement:
    repeat n of every run reuses build n. Repeats given the same slot share one build; ``building`` makes the first
    of them build it and the others wait and restore it."""

    root: Path
    slot: str

    def path(self, key: str) -> Path:
        return self.root / f"{key}-{build_code_fingerprint()}-{self.slot}.db"

    def building(self, key: str) -> threading.Lock:
        with _BUILD_LOCKS_GUARD:
            return _BUILD_LOCKS.setdefault(self.path(key), threading.Lock())

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


class LimitedLLM:
    """Shares one cap on in-flight model calls among every run of a process, so running benchmarks and repeats at
    the same time cannot overload the model endpoint. Time spent waiting for a slot is not part of call latency."""

    def __init__(self, llm: LLM, slots: threading.Semaphore) -> None:
        self.llm, self.slots, self.name = llm, slots, llm.name

    def structured(self, *, system: str, user: str, schema: type[T], **options: Any) -> T:
        with self.slots:
            return self.llm.structured(system=system, user=user, schema=schema, **options)


def limit_calls(llm: LLM, slots: threading.Semaphore | None) -> LLM:
    return llm if slots is None else LimitedLLM(llm, slots)


def chat_model(settings: Settings, slots: threading.Semaphore | None) -> LLM | None:
    """The model a configured ``[eval_chat_llm]`` answers with; None keeps answering on the profile model."""
    return (
        None
        if settings.eval_chat_llm is None
        else limit_calls(make_llm(settings.eval_chat_llm, "eval_chat_llm"), slots)
    )


def in_order[A, R](fn: Callable[[A], R], items: Sequence[A], workers: int) -> Iterator[tuple[A, R]]:
    """Run ``fn`` over items ``workers`` at a time and yield each result in input order as soon as it and every
    earlier one are done, so callers persist rows in a stable order while later items are still running. An
    exception from ``fn`` propagates at its item; items not yet started are cancelled and running ones finish."""
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(copy_context().run, fn, item) for item in items]
        try:
            for item, future in zip(items, futures, strict=True):
                yield item, future.result()
        finally:
            for future in futures:
                future.cancel()


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
    if not entries or source.kind == "intro":
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
    """One run's disk cache; stores are closed between questions, including failed builds.

    ``predict`` may run in several threads once ``prepare`` has built the subjects; ``metadata`` is the calling
    thread's last answer. Profiles are built with ``llm``; answers use ``chat_llm`` when given, so a different
    answering model reuses the cached profiles."""

    def __init__(
        self,
        settings: Settings,
        llm: LLM,
        embedder: Embedder,
        cache: ProfileCache | None = None,
        grant_gated: bool = False,
        chat_llm: LLM | None = None,
    ) -> None:
        self._temporary = TemporaryDirectory(prefix="twin-public-eval-")
        self.root = Path(self._temporary.name)
        self.root.chmod(0o700)
        self.settings = settings.model_copy(
            deep=True,
            update={
                "db_path": self.root / "unused.db",
                "target_name": TARGET,
                "target_aliases": [],
                "chat_llm": settings.eval_chat_llm if chat_llm is not None else None,
            },
        )
        self.llm, self.embedder, self.cache, self.grant_gated = llm, embedder, cache, grant_gated
        self.chat_llm = chat_llm or llm
        self._states: dict[str, bool] = {}
        # Built by ``prepare``, waiting for the subject's first question.
        self._prepared: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._local = threading.local()

    @property
    def metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = getattr(self._local, "metadata", {})
        return metadata

    @metadata.setter
    def metadata(self, value: dict[str, Any]) -> None:
        self._local.metadata = value

    def close(self) -> None:
        self._temporary.cleanup()

    @property
    def configuration(self) -> str:
        return configuration_fingerprint(
            self.settings,
            self.chat_llm,
            self.embedder,
            [],
            # Only a granted run adds the field, so default runs keep their earlier fingerprint.
            experiment={"protocol": PROTOCOL_VERSION} | ({"grant_gated": True} if self.grant_gated else {}),
        )

    @contextmanager
    def _stage(self, metadata: dict[str, Any], name: str) -> Iterator[None]:
        start = perf_counter()
        with collect_calls() as rows:
            try:
                with call_stage("persona." + name):
                    yield
            finally:
                metadata["stages"][name] = {
                    "seconds": perf_counter() - start,
                    "calls": len(rows),
                    "failed_calls": sum(not row.success for row in rows),
                    "known_cost_usd": sum(row.known_cost_usd for row in rows),
                    "unknown_cost_calls": sum(row.estimated_cost_usd is None for row in rows),
                }

    def _db_settings(self, key: str) -> Settings:
        return self.settings.model_copy(update={"db_path": self.root / (key + ".db")})

    def _prepare(
        self, store: PersonaStore, sources: tuple[SourceInput, ...], settings: Settings, metadata: dict[str, Any]
    ) -> None:
        # A benchmark's description of the user enters as the person's self-introduction, as one written in the app
        # would: a note of their own, kept as the identity's "about".
        about = "\n\n".join(text for s in sources if s.kind == "intro" for _, text, _ in s.entries if text.strip())
        store.set_identity(TARGET, about, parse_note(about, settings, "自我介绍") if about else None)
        for source in sources:
            parsed = parse_source(source, settings)
            if parsed is not None:
                store.put_source(parsed)
        report = build_profile(store, self.llm, settings, grant_gated=self.grant_gated)
        if report.degraded:
            metadata["preparation_degraded"] = report.degraded
        recorder = active_recorder()
        if report.failures or (recorder is not None and recorder.stop is not None):
            # Content-free: stage, chunk or facet id, error type, stop reason and field paths.
            metadata["preparation_failures"] = report.failures
            raise PreparationError("Profile preparation failed")

    def _build(self, key: str, sources: tuple[SourceInput, ...], metadata: dict[str, Any]) -> None:
        """Build or restore one profile and index it; a failure is sticky for the key."""
        settings = self._db_settings(key)
        # Save failure first, so parser, constructor and partial-build failures are sticky.
        self._states[key] = False
        try:
            # Held through the build and save, so a repeat sharing this slot restores the build instead of redoing it.
            with self.cache.building(key) if self.cache is not None else nullcontext():
                restored = False
                if self.cache is not None:
                    restored = self.cache.restore(key, settings.db_path)
                    metadata["profile_cache"] = "hit" if restored else "miss"
                with PersonaStore(settings.db_path) as store:
                    with self._stage(metadata, "preparation"):
                        if not restored:
                            self._prepare(store, sources, settings, metadata)
                    with self._stage(metadata, "index"):
                        index_persona(store, self.embedder, settings)
                # A degraded build retries its merges next time, so it is not frozen into the cache.
                if self.cache is not None and not restored and "preparation_degraded" not in metadata:
                    self.cache.save(settings.db_path, key)
        except Exception as error:
            metadata["preparation_failure"] = True
            raise PreparationError("Persona preparation failed (details hidden)") from error
        self._states[key] = True

    def prepare(self, subjects: Iterable[tuple[str, tuple[SourceInput, ...]]], workers: int) -> None:
        """Build the distinct subjects' profiles ``workers`` at a time ahead of ``predict``, which then reports each
        build on the subject's first question as if it had built it there."""
        pending: dict[str, tuple[SourceInput, ...]] = {}
        for subject, sources in subjects:
            key = preparation_key(subject, sources, self.settings)
            if key not in self._states:
                pending.setdefault(key, sources)

        def build(item: tuple[str, tuple[SourceInput, ...]]) -> None:
            key, sources = item
            self._prepared[key] = metadata = {"preparation_key": key, "cache_hit": False, "stages": {}}
            self._build(key, sources, metadata)

        # Failures stay in each subject's metadata and state; predict raises them on that subject's questions.
        run_parallel(build, list(pending.items()), workers)

    def predict(
        self, subject: str, sources: tuple[SourceInput, ...], prompt: str, today: dt.date | None = None
    ) -> ChatReply:
        key = preparation_key(subject, sources, self.settings)
        # Concurrent answers start in submission order, so the build lands on the subject's earliest question.
        # Building here is the unprepared path; the lock keeps two threads from building one subject twice.
        with self._lock:
            prepared = self._prepared.pop(key, None)
            if prepared is None:
                cached = key in self._states
                self.metadata = {"preparation_key": key, "cache_hit": cached, "stages": {}}
                if not cached:
                    self._build(key, sources, self.metadata)
        if prepared is not None:
            self.metadata = prepared
            if prepared.get("preparation_failure"):
                raise PreparationError("Persona preparation failed (details hidden)")
        elif cached and not self._states[key]:
            self.metadata["preparation_failure"] = True
            raise PreparationError("Previously failed preparation")
        settings = self._db_settings(key)
        with PersonaStore(settings.db_path) as store:
            with self._stage(self.metadata, "answer"):
                reply = PersonaChat(store, self.chat_llm, self.embedder, settings).reply(
                    [ChatTurn(role="user", content=prompt)], persist=False, today=today
                )
            self.metadata.update(reply.model_dump(mode="json"))
            return reply


def report_system(system: str, retrieval_label: str) -> dict[str, Any]:
    if system not in ("twin", "retrieval"):
        raise ValueError("system must be twin or retrieval")
    return {
        "system": system,
        "system_label": "production Twin persona pipeline" if system == "twin" else retrieval_label,
        "protocol_version": PROTOCOL_VERSION if system == "twin" else "retrieval-v1",
        "limitations": LIMITATIONS if system == "twin" else [],
    }
