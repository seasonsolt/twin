"""Sources of what a person said or wrote, normalised into ``Expression`` rows.

Every source becomes a list of expressions: who said it, when, where (channel), what it answered (context) and the
words. Each source kind is either *behavior* (what the person actually did: chats, documents, meetings) or *self
report* (what the person says about themself: questionnaires, interviews); completeness counts the two apart.

Parsers here are pure: text in, ``ParsedSource`` out. Formats:

- questionnaire: the 建档问卷 exported as Markdown or plain text. A question line starts with its number
  (``**13.【测试题】…**　*情境 · 3.4 3.6*``), the answer follows ``回答：``. 【测试题】 answers are held out
  (test probes, never profile evidence); an empty answer to a 【可跳过】 question means the person did not consent
  to those facets.
- chat: plain text with one message per ``<date time> <speaker>：<text>`` line (also ``[date time] speaker: text``),
  or WeChat-style blocks (a ``<speaker> <date time>`` header line, then the message lines); CSV or JSON with
  time / sender / content columns. Lines without a header continue the previous message.
- interview: ``<speaker>：<text>`` lines (no times); the date comes from the file name or the caller.
- document: Markdown or plain text written by the person; one expression per paragraph.
- meeting: an already normalised ``Meeting``; one expression per utterance, with an exact inverse. No text parsing
  or speaker pseudonymisation is done by the converter.
- biography: Markdown or plain text written by someone else about the person (a biography, chronicle, obituary,
  profile); one *narrated* expression per paragraph. The narration is evidence of what the person did, not their
  words; extraction marks the spans that quote them. A Markdown heading carrying a date (or only a year: taken as
  1 July) dates the paragraphs under it.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from ..util import date_from_name
from .dimensions import FACET_BY_ID
from .schema import Expression, ParsedSource, Source, SourceKind
from .store import PersonaStore
from .transcript_schema import Meeting, Utterance
from .transcripts import parse_transcript, parse_transcript_text

CONTEXT_MESSAGES = 3
CONTEXT_CHARS = 400


# ---------------------------------------------------------------- shared helpers

_DATE = r"(?P<y>\d{4})[-/.年](?P<m>\d{1,2})[-/.月](?P<d>\d{1,2})日?"
_TIME = r"(?:\s*(?:T|\s)\s*\d{1,2}:\d{2}(?::\d{2})?)?"


def _date(y: str, m: str, d: str) -> dt.date | None:
    try:
        return dt.date(int(y), int(m), int(d))
    except ValueError:
        return None


def parse_date(value: str) -> dt.date | None:
    m = re.search(_DATE, value)
    return _date(m["y"], m["m"], m["d"]) if m else None


def source_id_for(kind: SourceKind, origin: str, text: str) -> str:
    digest = hashlib.sha256(f"{kind}\x1f{origin}\x1f{text}".encode()).hexdigest()
    return f"src_{digest[:12]}"


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else "…" + text[-(limit - 1) :]


@dataclass
class _Message:
    date: dt.date | None
    speaker: str
    text: str


PSEUDONYM_PREFIX = "他人"
MIN_NAME_CHARS = 2


def pseudonym(name: str) -> str:
    """A stable code for another person's name: the same name gets the same code in every source, and no table of
    real names is kept."""
    return f"{PSEUDONYM_PREFIX}{hashlib.sha256(name.strip().encode()).hexdigest()[:4].upper()}"


def expression_view(
    store: PersonaStore,
    settings: Settings,
    *,
    source_id: str | None = None,
    target_only: bool = False,
    until: dt.date | None = None,
    expressions: list[Expression] | None = None,
) -> list[Expression]:
    """The L2/L3 view, never written back to L1.

    Known names are non-target speakers in the raw corpus (not guessed from prose); the same name is replaced in
    every source kind, including documents and meetings. Legacy sources bypass replacement entirely: their lost
    names cannot be recovered, and hashing their codes again would change existing profiles. Target names/aliases
    and existing codes are protected even when they contain another speaker's name.
    """
    sources = {s.source_id: s for s in store.list_sources()}
    corpus = store.list_expressions()
    entries = [
        e
        for e in (corpus if expressions is None else expressions)
        if (source_id is None or e.source_id == source_id)
        and (not target_only or e.is_target)
        and (until is None or (e.date is not None and e.date <= until))
    ]
    if not settings.pseudonymize_others:
        return entries
    protected = {settings.target_name, *settings.target_aliases}
    others = {
        e.speaker
        for e in corpus
        if sources[e.source_id].text_state == "raw"
        and not e.is_target
        and not settings.is_target(e.speaker)
        and len(e.speaker) >= MIN_NAME_CHARS
        and not re.fullmatch(r"他人[0-9A-F]{4}", e.speaker)
    }
    if not others:
        return entries
    names = sorted(others | protected, key=lambda n: (-len(n), n))
    pattern = re.compile(r"他人[0-9A-F]{4}|" + "|".join(re.escape(n) for n in names if n))
    codes = {n: pseudonym(n) for n in others - protected}

    def swap(text: str) -> str:
        return pattern.sub(lambda m: codes.get(m.group(0), m.group(0)), text)

    return [
        e.model_copy(
            update={
                "speaker": e.speaker if e.is_target else swap(e.speaker),
                "text": swap(e.text),
                "context": swap(e.context),
                "channel": swap(e.channel),
            }
        )
        if sources[e.source_id].text_state == "raw"
        else e
        for e in entries
    ]


def _message_context(recent: list[str], speaker: str, text: str, target: bool) -> str:
    if target:
        context = _clip("\n".join(recent[-CONTEXT_MESSAGES:]), CONTEXT_CHARS)
        recent.clear()
        return context
    recent.append(f"{speaker}：{text}")
    return ""


def _assemble(
    kind: SourceKind,
    title: str,
    origin: str,
    raw: str,
    messages: list[_Message],
    settings: Settings,
    channel: str,
    skipped: list[str],
) -> ParsedSource:
    """Messages to expressions; a target message gets the other people's messages just before it as context."""
    source_id = source_id_for(kind, origin, raw)
    expressions: list[Expression] = []
    recent: list[str] = []
    for i, msg in enumerate(m for m in messages if m.text.strip()):
        target = settings.is_target(msg.speaker)
        expressions.append(
            Expression(
                expression_id=f"{source_id}#{i:05d}",
                source_id=source_id,
                idx=i,
                date=msg.date,
                speaker=msg.speaker,
                is_target=target,
                text=msg.text.strip(),
                context=_message_context(recent, msg.speaker, msg.text.strip(), target),
                channel=channel,
            )
        )
    return ParsedSource(_source(kind, title, origin, source_id, expressions), expressions, skipped)


def _source(
    kind: SourceKind,
    title: str,
    origin: str,
    source_id: str,
    expressions: list[Expression],
    declined: list[str] | None = None,
) -> Source:
    dates = [e.date for e in expressions if e.date is not None]
    return Source(
        source_id=source_id,
        kind=kind,
        title=title,
        origin=origin,
        first_date=min(dates, default=None),
        last_date=max(dates, default=None),
        imported_at=dt.datetime.now().isoformat(timespec="seconds"),
        n_expressions=len(expressions),
        n_target=sum(e.is_target for e in expressions),
        declined_facets=declined or [],
        text_state="raw",
    )


# ---------------------------------------------------------------- meeting


def meeting_to_source(meeting: Meeting, settings: Settings) -> ParsedSource:
    """Convert without re-normalising speakers, trimming text or dropping utterances."""
    source_id = source_id_for(SourceKind.MEETING, meeting.source, meeting.model_dump_json())
    expressions: list[Expression] = []
    recent: list[str] = []
    for i, utterance in enumerate(meeting.utterances):
        target = settings.is_target(utterance.speaker)
        expressions.append(
            Expression(
                expression_id=f"{source_id}#{i:05d}",
                source_id=source_id,
                idx=i,
                date=meeting.date,
                speaker=utterance.speaker,
                is_target=target,
                text=utterance.text,
                context=_message_context(recent, utterance.speaker, utterance.text.strip(), target),
                channel=meeting.title or meeting.meeting_id,
                utterance_idx=utterance.idx,
                start=utterance.start,
                end=utterance.end,
            )
        )
    source = _source(SourceKind.MEETING, meeting.title, meeting.source, source_id, expressions)
    source.meeting_id = meeting.meeting_id
    source.first_date = source.last_date = meeting.date
    return ParsedSource(source, expressions)


def source_to_meeting(parsed: ParsedSource) -> Meeting:
    """Restore a source produced by ``meeting_to_source`` in its stored expression order."""
    source = parsed.source
    if source.kind is not SourceKind.MEETING:
        raise ValueError("source_to_meeting requires a meeting source")
    if source.meeting_id is None or source.first_date is None:
        raise ValueError("meeting source is missing meeting_id or date")
    utterances: list[Utterance] = []
    for expression in parsed.expressions:
        if expression.utterance_idx is None:
            raise ValueError(f"{expression.expression_id}: missing utterance_idx")
        utterances.append(
            Utterance(
                idx=expression.utterance_idx,
                speaker=expression.speaker,
                text=expression.text,
                start=expression.start,
                end=expression.end,
            )
        )
    return Meeting(
        meeting_id=source.meeting_id,
        date=source.first_date,
        title=source.title,
        source=source.origin,
        utterances=utterances,
    )


# ---------------------------------------------------------------- chat

_SEP = r"\s*[：:]\s*"
_INLINE = re.compile(rf"^\s*\[?\s*{_DATE}{_TIME}\s*\]?\s+(?P<speaker>[^：:\s][^：:]{{0,30}}?){_SEP}(?P<text>.*)$")
_HEADER = re.compile(rf"^\s*(?P<speaker>[^：:\s\d][^：:]{{0,30}}?)\s+{_DATE}{_TIME}\s*$")
_CSV_TIME = ("time", "date", "datetime", "timestamp", "时间", "日期", "发送时间")
_CSV_SENDER = ("sender", "from", "speaker", "name", "talker", "发送者", "发言人", "发送人", "昵称")
_CSV_TEXT = ("content", "text", "message", "msg", "内容", "消息", "消息内容")


def _pick(row: dict[str, str], names: tuple[str, ...]) -> str:
    lowered = {k.strip().lower(): v for k, v in row.items() if k}
    return next((str(lowered[n]) for n in names if lowered.get(n) not in (None, "")), "")


def _rows_to_messages(rows: list[dict[str, str]]) -> tuple[list[_Message], list[str]]:
    messages: list[_Message] = []
    skipped: list[str] = []
    for row in rows:
        speaker, text = _pick(row, _CSV_SENDER).strip(), _pick(row, _CSV_TEXT)
        if not speaker or not text.strip():
            skipped.append(json.dumps(row, ensure_ascii=False)[:120])
            continue
        messages.append(_Message(parse_date(_pick(row, _CSV_TIME)), speaker, text))
    return messages, skipped


_PLAIN = re.compile(rf"^\s*(?P<speaker>[^：:\s][^：:]{{0,30}}?){_SEP}(?P<text>.+)$")


def _text_to_messages(
    text: str, default_date: dt.date | None, speaker_lines: bool = False
) -> tuple[list[_Message], list[str]]:
    """``speaker_lines``: every ``speaker：text`` line starts a message (transcripts without times); otherwise only
    timestamped lines do and other lines continue the previous message (chat exports, where a message may contain a
    colon)."""
    messages: list[_Message] = []
    skipped: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if m := _INLINE.match(line):
            messages.append(_Message(_date(m["y"], m["m"], m["d"]), m["speaker"].strip(), m["text"]))
        elif m := _HEADER.match(line):
            messages.append(_Message(_date(m["y"], m["m"], m["d"]), m["speaker"].strip(), ""))
        elif (speaker_lines or not messages) and (m := _PLAIN.match(line)):
            messages.append(_Message(default_date, m["speaker"].strip(), m["text"]))
        elif messages:
            last = messages[-1]
            last.text = f"{last.text}\n{line.strip()}" if last.text else line.strip()
        else:
            skipped.append(line[:120])
    return messages, skipped


def parse_chat(path_name: str, raw: str, settings: Settings, channel: str = "") -> ParsedSource:
    suffix = Path(path_name).suffix.lower()
    if suffix == ".csv":
        messages, skipped = _rows_to_messages(list(csv.DictReader(io.StringIO(raw))))
    elif suffix == ".json":
        data = json.loads(raw)
        rows = data.get("messages", data) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            raise ValueError(f"{path_name}: expected a list of messages")
        messages, skipped = _rows_to_messages([r for r in rows if isinstance(r, dict)])
    else:
        messages, skipped = _text_to_messages(raw, date_from_name(Path(path_name).stem))
    if not any(settings.is_target(m.speaker) for m in messages):
        raise ValueError(
            f"{path_name}: no message from {settings.target_name}; check target_name / target_aliases "
            f"(speakers seen: {', '.join(sorted({m.speaker for m in messages})[:8]) or 'none'})"
        )
    title = channel or Path(path_name).stem
    return _assemble(SourceKind.CHAT, title, path_name, raw, messages, settings, title, skipped)


def parse_interview(path_name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    date = date or date_from_name(Path(path_name).stem)
    messages, skipped = _text_to_messages(raw, date, speaker_lines=True)
    for m in messages:
        m.date = m.date or date
    if not any(settings.is_target(m.speaker) for m in messages):
        raise ValueError(f"{path_name}: no line spoken by {settings.target_name}")
    title = Path(path_name).stem
    return _assemble(SourceKind.INTERVIEW, title, path_name, raw, messages, settings, title, skipped)


# ---------------------------------------------------------------- document


def _paragraphs(
    kind: SourceKind, path_name: str, raw: str, settings: Settings, date: dt.date | None, narrated: bool
) -> ParsedSource:
    title = Path(path_name).stem
    source_id = source_id_for(kind, path_name, raw)
    expressions: list[Expression] = []
    heading = title
    for block in re.split(r"\n\s*\n", raw):
        text = block.strip()
        if not text:
            continue
        if m := re.match(r"^#{1,6}\s+(.+)$", text):
            heading = m[1].strip()
            if narrated:
                date = _heading_date(heading) or date
            if "\n" not in text:
                continue
        i = len(expressions)
        expressions.append(
            Expression(
                expression_id=f"{source_id}#{i:05d}",
                source_id=source_id,
                idx=i,
                date=date,
                speaker=settings.target_name,
                is_target=True,
                text=text,
                channel=heading,
                narrated=narrated,
            )
        )
    return ParsedSource(_source(kind, title, path_name, source_id, expressions), expressions)


def _heading_date(heading: str) -> dt.date | None:
    if full := parse_date(heading):
        return full
    m = re.search(r"(?<!\d)(1\d{3}|20\d{2})(?!\d)", heading)
    return dt.date(int(m[1]), 7, 1) if m else None


def parse_document(path_name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    """A text the person wrote: every paragraph is theirs. Markdown headings become the channel of what follows."""
    date = date or date_from_name(Path(path_name).stem)
    return _paragraphs(SourceKind.DOCUMENT, path_name, raw, settings, date, narrated=False)


def parse_biography(path_name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    """A text about the person written by someone else: every paragraph is narration about them, dated by the
    nearest dated heading above it (else the file name or ``date``)."""
    date = date or date_from_name(Path(path_name).stem)
    return _paragraphs(SourceKind.BIOGRAPHY, path_name, raw, settings, date, narrated=True)


# ---------------------------------------------------------------- questionnaire

_QUESTION = re.compile(r"^\s*(?:\*\*)?\s*(?P<n>\d{1,3})\s*[.、．]\s*(?P<body>.+)$")
_TAGS = re.compile(r"(?P<type>[一-龥]{2})\s*·\s*(?P<facets>\d\.\d(?:\s+\d\.\d)*)\s*\*?\s*$")
_ANSWER = re.compile(r"^\s*回答\s*[：:]\s*(?P<text>.*)$")
_MARKUP = re.compile(r"[*_`]")


@dataclass
class _Question:
    number: int
    text: str
    facets: list[str]
    held_out: bool
    optional: bool
    answer: list[str] = field(default_factory=list)


def parse_questionnaire(path_name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    date = date or date_from_name(Path(path_name).stem) or dt.date.today()
    questions: list[_Question] = []
    current: _Question | None = None
    in_answer = False
    for line in raw.splitlines():
        if (m := _QUESTION.match(line)) and _TAGS.search(line):
            body = m["body"]
            tags = _TAGS.search(body)
            if tags is None:
                continue
            text = _MARKUP.sub("", body[: tags.start()]).strip()
            facets = [f for f in tags["facets"].split() if f in FACET_BY_ID]
            current = _Question(int(m["n"]), text, facets, "【测试题】" in text, "【可跳过】" in text)
            current.text = current.text.replace("【测试题】", "").replace("【可跳过】", "").strip()
            questions.append(current)
            in_answer = False
        elif current is not None and (a := _ANSWER.match(line)):
            in_answer = True
            if a["text"].strip():
                current.answer.append(a["text"].strip())
        elif current is not None and in_answer:
            if line.lstrip().startswith("#"):
                in_answer = False
            elif line.strip():
                current.answer.append(line.strip())
    if not questions:
        raise ValueError(f"{path_name}: no questionnaire question found (expected lines like '1. … 开放 · 1.1')")
    source_id = source_id_for(SourceKind.QUESTIONNAIRE, path_name, raw)
    expressions: list[Expression] = []
    declined: list[str] = []
    for q in questions:
        answer = "\n".join(q.answer).strip()
        if not answer:
            if q.optional:
                declined.extend(q.facets)
            continue
        i = len(expressions)
        expressions.append(
            Expression(
                expression_id=f"{source_id}#{i:05d}",
                source_id=source_id,
                idx=i,
                date=date,
                speaker=settings.target_name,
                is_target=True,
                text=answer,
                context=f"问卷第 {q.number} 题：{q.text}",
                channel="建档问卷",
                facets_hint=q.facets,
                held_out=q.held_out,
            )
        )
    title = Path(path_name).stem
    return ParsedSource(
        _source(SourceKind.QUESTIONNAIRE, title, path_name, source_id, expressions, sorted(set(declined))),
        expressions,
    )


def parse_text(kind: SourceKind, name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    if kind is SourceKind.MEETING:
        return meeting_to_source(parse_transcript_text(name, raw, settings, meeting_date=date), settings)
    if kind is SourceKind.CHAT:
        return parse_chat(name, raw, settings)
    if kind is SourceKind.INTERVIEW:
        return parse_interview(name, raw, settings, date)
    if kind is SourceKind.DOCUMENT:
        return parse_document(name, raw, settings, date)
    if kind is SourceKind.BIOGRAPHY:
        return parse_biography(name, raw, settings, date)
    return parse_questionnaire(name, raw, settings, date)


def parse_source(kind: SourceKind, path: Path, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    if kind is SourceKind.MEETING:
        return meeting_to_source(parse_transcript(path, settings, meeting_date=date), settings)
    return parse_text(kind, path.name, path.read_text(encoding="utf-8-sig"), settings, date)
