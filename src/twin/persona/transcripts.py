"""Saying which speaker of multi-person text transcripts is the person, for all of them at once.

A transcript in which no speaker is known to be the person waits (``media_status="needs_name"``) with every line
counted as someone else's. The person answers once for the names across every waiting transcript: the names they
pick become their aliases (``identity:aliases``), the names they leave are not theirs (``identity:not_me``). A
transcript whose speakers carry only labels such as ``发言人1`` gets a label picked for it alone, or is kept as other
people's words. Every answer attributes the transcripts again (``settle``), so no line is counted as the person's
before the person said so.
"""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from ..config import Settings
from .schema import Expression, Source
from .sources import NEEDS_NAME, _with_identity_alias, attribute, is_generic_speaker, is_transcript
from .store import PersonaStore, SpeakerNames

SAMPLES = 3
SAMPLE_CHARS = 160
# Enough to pick from in one sitting; the rest come back once these are answered.
MAX_NAMES = 200
MAX_FILES = 100
MAX_NAME_CHARS = 40


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip())


@dataclass
class _Tally:
    segments: int = 0
    chars: int = 0
    files: set[str] = field(default_factory=set)
    samples: list[str] = field(default_factory=list)

    def add(self, expression: Expression) -> None:
        self.segments += 1
        self.chars += len(expression.text)
        self.files.add(expression.source_id)
        text = " ".join(expression.text.split())
        if text not in self.samples:
            self.samples = sorted([*self.samples, text], key=len, reverse=True)[:SAMPLES]

    def view(self) -> dict[str, Any]:
        return {
            "segments": self.segments,
            "chars": self.chars,
            "files": len(self.files),
            "samples": [t if len(t) <= SAMPLE_CHARS else t[: SAMPLE_CHARS - 1] + "…" for t in self.samples],
        }


def _similar(name: str, known: list[str]) -> bool:
    """A name written like one the person goes by: one inside the other (``林沐老师``), or mostly the same letters.
    A single letter (a surname alone) says too little."""
    if len(name) < 2:
        return False
    for other in known:
        short, long = sorted((name, other), key=len)
        if len(short) >= 2 and short in long:
            return True
        if SequenceMatcher(None, name, other).ratio() >= 0.6:
            return True
    return False


def _speakers(expressions: list[Expression]) -> set[str]:
    return {e.speaker for e in expressions}


def roster(store: PersonaStore, settings: Settings) -> dict[str, Any]:
    """What the person is asked about the waiting transcripts.

    ``names``: every named speaker of them the person has not answered for, most words first, with the longest
    things they said, how many transcripts they speak in, and ``likely`` (why it may be the person) when written like
    the person's name or the one who speaks most. Nothing is picked for the person.
    ``files``: waiting transcripts left with only labels such as ``发言人1`` once the names are answered."""
    names = store.speaker_names()
    effective = _with_identity_alias(settings, names)
    known = [n for n in dict.fromkeys([effective.target_name, *effective.target_aliases]) if n]
    pending = [s for s in store.list_sources() if s.media_status == NEEDS_NAME and is_transcript(s)]
    tallies: dict[str, _Tally] = defaultdict(_Tally)
    labelled: list[tuple[Source, dict[str, _Tally]]] = []
    for source in pending:
        expressions = store.list_expressions(source.source_id)
        undecided = {
            s
            for s in _speakers(expressions)
            if not is_generic_speaker(s) and s not in names.not_me and not effective.is_target(s)
        }
        for e in expressions:
            if e.speaker in undecided:
                tallies[e.speaker].add(e)
        if not undecided:
            speakers: dict[str, _Tally] = defaultdict(_Tally)
            for e in expressions:
                if e.speaker not in names.not_me:
                    speakers[e.speaker].add(e)
            labelled.append((source, speakers))
    ranked = sorted(tallies.items(), key=lambda kv: (-kv[1].chars, -kv[1].segments, kv[0]))
    rows = []
    for position, (name, tally) in enumerate(ranked[:MAX_NAMES]):
        likely = "和你的名字相近" if _similar(name, known) else "说得最多" if position == 0 else None
        rows.append({"name": name, **tally.view(), "likely": likely})
    files = [
        {
            "source_id": source.source_id,
            "title": source.title,
            "first_date": source.first_date.isoformat() if source.first_date else None,
            "speakers": [
                {"label": label, **tally.view()}
                for label, tally in sorted(speakers.items(), key=lambda kv: (-kv[1].chars, kv[0]))
            ],
        }
        for source, speakers in labelled[:MAX_FILES]
    ]
    return {
        "pending": len(pending),
        "names": rows,
        "names_total": len(ranked),
        "files": files,
        "files_total": len(labelled),
        **aliases_view(names, settings),
    }


def aliases_view(names: SpeakerNames, settings: Settings) -> dict[str, Any]:
    """The names the person goes by in transcripts: ``aliases`` they picked (and may remove), ``fixed`` ones from the
    name they gave and the configuration."""
    fixed = list(dict.fromkeys(n for n in (names.name or settings.target_name, *settings.target_aliases) if n))
    return {"aliases": [a for a in names.aliases if a not in fixed], "fixed": fixed, "not_me": len(names.not_me)}


def settle(store: PersonaStore, settings: Settings, only: set[str] | None = None) -> list[str]:
    """Attribute every transcript (those in ``only``) again with what the person said so far, storing the ones that
    changed so the next build reads them anew. Returns their ids."""
    names = store.speaker_names()
    changed: list[str] = []
    for source in store.list_sources():
        if not is_transcript(source) or (only is not None and source.source_id not in only):
            continue
        expressions = store.list_expressions(source.source_id)
        parsed = attribute(source, expressions, settings, names)
        before = [(e.is_target, e.context) for e in sorted(expressions, key=lambda e: e.idx)]
        after = [(e.is_target, e.context) for e in parsed.expressions]
        if before == after and parsed.source.media_status == source.media_status:
            continue
        store.reattribute_source(parsed)
        changed.append(source.source_id)
    return changed


def _names(values: list[str]) -> list[str]:
    cleaned = list(dict.fromkeys(n for v in values if (n := normalize_name(v))))
    if any(len(n) > MAX_NAME_CHARS for n in cleaned):
        raise ValueError(f"称呼最多 {MAX_NAME_CHARS} 个字")
    if any(is_generic_speaker(n) for n in cleaned):
        raise ValueError("「发言人1」这类标签不是名字，请在对应的文件里单独选择")
    return cleaned


def claim_names(store: PersonaStore, settings: Settings, mine: list[str], others: list[str]) -> list[str]:
    """``mine`` are the person's names from now on, ``others`` are not; every transcript is attributed again."""
    names = store.speaker_names()
    effective = _with_identity_alias(settings, names)
    mine, others = _names(mine), _names(others)
    if set(mine) & set(others):
        raise ValueError("同一个名字不能既是你又不是你")
    aliases = list(dict.fromkeys([*names.aliases, *(n for n in mine if not effective.is_target(n))]))
    not_me = (names.not_me | {n for n in others if not effective.is_target(n)}) - set(aliases)
    store.set_speaker_names(aliases, sorted(not_me))
    return settle(store, settings)


def remove_alias(store: PersonaStore, settings: Settings, name: str) -> list[str] | None:
    """The person does not go by ``name``: its lines become other people's again. None when it is not an alias."""
    names = store.speaker_names()
    name = normalize_name(name)
    if name not in names.aliases:
        return None
    store.set_speaker_names([a for a in names.aliases if a != name], sorted(names.not_me | {name}))
    return settle(store, settings)


def claim_labels(store: PersonaStore, settings: Settings, source_id: str, labels: list[str]) -> list[str] | None:
    """In this transcript alone, ``labels`` are the person (none: no one is). None when there is no such
    transcript."""
    source = store.get_source(source_id)
    if source is None or not is_transcript(source):
        return None
    labels = list(dict.fromkeys(normalize_name(label) for label in labels))
    if not set(labels) <= _speakers(store.list_expressions(source_id)):
        raise ValueError("请选择这份文字记录里的说话人")
    store.set_speaker_claim(source_id, labels)
    return settle(store, settings, {source_id})
