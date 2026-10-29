"""Sources of what a person said or wrote, normalised into ``Expression`` rows.

Every source becomes a list of expressions: who said it, when, where (channel), what it answered (context) and the
words. Each source kind is either *behavior* (what the person actually did: chats, documents) or *self
report* (what the person says about themself: questionnaires, interviews); completeness counts the two apart.

Parsers here are pure: text in, ``ParsedSource`` out. Formats:

- questionnaire: the 建档问卷 exported as Markdown or plain text. A question line starts with its number
  (``**13.【可跳过】…**　*情境 · 3.4 3.6*``), the answer follows ``回答：``.
  An empty answer to a 【可跳过】 question means the person did not consent
  to those facets.
- chat: plain text with one message per ``<date time> <speaker>：<text>`` line (also ``[date time] speaker: text``),
  or WeChat-style blocks (a ``<speaker> <date time>`` header line, then the message lines); CSV or JSON with
  time / sender / content columns. Lines without a header continue the previous message.
- interview: ``<speaker>：<text>`` lines (no times); the date comes from the file name or the caller. A transcript in
  which no speaker is known to be the person is kept with ``media_status="needs_name"`` and every line counted as
  someone else's, until the person says which name or label is theirs (``attribute``).
- document: Markdown or plain text written by the person; one expression per paragraph.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import re
import unicodedata
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..config import Settings
from ..util import date_from_name
from .dimensions import FACET_BY_ID
from .schema import Expression, ParsedSource, Source, SourceKind
from .store import PersonaStore, SpeakerNames, stored_speaker_names
from .text import MAX_FILE_BYTES, extract_text

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
    # Seconds into the meeting, for a turn a transcript timed.
    clock: float | None = None


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
    mirror: bool = False,
) -> list[Expression]:
    """The L2/L3 view, never written back to L1 (see ``ExpressionView``)."""
    return ExpressionView(store, settings).select(
        source_id=source_id, target_only=target_only, until=until, expressions=expressions, mirror=mirror
    )


class ExpressionView:
    """The L2/L3 view, never written back to L1, read from the store once and selected from as often as needed.

    Known names are non-target speakers in the raw corpus (not guessed from prose); the same name is replaced in
    every source kind, including documents. Legacy sources bypass replacement entirely: their lost
    names cannot be recovered, and hashing their codes again would change existing profiles. Target names/aliases
    and existing codes are protected even when they contain another speaker's name.
    """

    def __init__(self, store: PersonaStore, settings: Settings) -> None:
        sources, self.corpus = store.read_corpus()
        self.sources = {s.source_id: s for s in sources}
        self._swap: Callable[[str], str] | None = None
        self._restore: Callable[[str], str] | None = None
        if not settings.pseudonymize_others:
            return
        protected = {
            settings.target_name,
            store.get_meta("identity:name") or settings.target_name,
            *settings.target_aliases,
            *store.speaker_names().aliases,
        }
        others = {
            e.speaker
            for e in self.corpus
            if self.sources[e.source_id].text_state == "raw"
            and not e.is_target
            and not settings.is_target(e.speaker)
            and len(e.speaker) >= MIN_NAME_CHARS
            and not re.fullmatch(r"他人[0-9A-F]{4}|其他人\d+", e.speaker)
        }
        if not others:
            return
        names = sorted(others | protected, key=lambda n: (-len(n), n))
        pattern = re.compile(r"他人[0-9A-F]{4}|" + "|".join(re.escape(n) for n in names if n))
        codes = {n: pseudonym(n) for n in others - protected}
        self._swap = lambda text: pattern.sub(lambda m: codes.get(m.group(0), m.group(0)), text)
        names_of = {code: name for name, code in codes.items()}
        self._restore = lambda text: re.sub(
            rf"{PSEUDONYM_PREFIX}[0-9A-F]{{4}}", lambda m: names_of.get(m.group(0), m.group(0)), text
        )

    def mask(self, text: str) -> str:
        """``text`` as the model is shown it: the names of the other people in the corpus replaced by their codes."""
        return self._swap(text) if self._swap else text

    def restore(self, text: str) -> str:
        """``text`` the model wrote about what it was shown through ``mask``, with the names put back, for the
        person to read."""
        return self._restore(text) if self._restore else text

    def select(
        self,
        *,
        source_id: str | None = None,
        target_only: bool = False,
        until: dt.date | None = None,
        expressions: list[Expression] | None = None,
        mirror: bool = False,
    ) -> list[Expression]:
        """The corpus (or ``expressions``) in the view, narrowed to one source, the person's own words (from sources
        that are ready) and what was said up to ``until``. What is kept for the mirror only (dreams) is left out
        unless ``mirror``: memories are never extracted from it, and chat never answers from it."""
        sources = self.sources
        entries = [
            e
            for e in (self.corpus if expressions is None else expressions)
            if (mirror or not e.mirror)
            and (source_id is None or e.source_id == source_id)
            and (not target_only or (e.is_target and sources[e.source_id].media_status in (None, "ready")))
            and (until is None or (e.date is not None and e.date <= until))
        ]
        swap = self._swap
        if swap is None:
            return entries
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
    source_id: str | None = None,
) -> ParsedSource:
    """Messages to expressions; a target message gets the other people's messages just before it as context."""
    source_id = source_id or source_id_for(kind, origin, raw)
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


# ---------------------------------------------------------------- chat

_SEP = r"\s*[：:]\s*"
_CLOCK = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?"
_INLINE = re.compile(rf"^\s*\[?\s*{_DATE}{_TIME}\s*\]?\s+(?P<speaker>[^：:\s][^：:]{{0,30}}?){_SEP}(?P<text>.*)$")
_HEADER = re.compile(rf"^\s*(?P<speaker>[^：:\s\d][^：:]{{0,30}}?)\s+{_DATE}{_TIME}\s*$")
# Meeting transcripts (飞书妙记、通义听悟、腾讯会议 exports and PDFs of them) time each turn instead of dating it:
# ``<speaker> <clock>`` or ``<speaker>(<clock>)`` on a line of its own before the words,
# ``<speaker>(<clock>)：<words>``, or ``[<clock>] <speaker>：<words>``.
_CLOCK_AFTER = re.compile(
    rf"^\s*(?P<speaker>[^：:\s\d(（\[【][^：:()（）\[\]【】]{{0,30}}?)"
    rf"(?:\s+{_CLOCK}|\s*[(（\[【]\s*{_CLOCK}\s*[)）\]】])\s*(?:[：:]\s*(?P<text>.*))?$"
)
_CLOCK_BEFORE = re.compile(
    rf"^\s*[\[(（【]?\s*{_CLOCK}\s*[\])）】]?\s+(?P<speaker>[^：:\s\d\-–—>][^：:]{{0,30}}?){_SEP}(?P<text>.*)$"
)
# Labels a transcription service gives speakers it could not name.
_GENERIC_SPEAKER = re.compile(r"(?:发言人|说话人|讲话人|speaker|spk)\s*(?:\d+|[a-z])", re.IGNORECASE)


def is_generic_speaker(speaker: str) -> bool:
    """``发言人1``, ``Speaker A``: a label that names no one, so it never becomes one of the person's names."""
    return bool(_GENERIC_SPEAKER.fullmatch(speaker))


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
MIN_TRANSCRIPT_HEADERS = 3


def _speaker(value: str) -> str:
    # PDF extraction can turn common CJK characters such as 子 into compatibility forms.
    return unicodedata.normalize("NFKC", value.strip())


def _turn_clock(line: str) -> float | None:
    """The time a timed turn starts at, in seconds: ``1:02:03`` is hours, minutes and seconds, ``12:30`` minutes and
    seconds."""
    found = re.search(_CLOCK, line)
    if found is None:
        return None
    parts = [float(part.replace(",", ".")) for part in found[0].split(":")]
    seconds = 0.0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def _timed_turn(line: str) -> tuple[str, str] | None:
    """The speaker and words of a transcript line that starts a timed turn (the words may follow on later lines)."""
    m = _CLOCK_AFTER.match(line) or _CLOCK_BEFORE.match(line)
    return (_speaker(m["speaker"]), m["text"] or "") if m else None


def _talking(speakers: list[str], settings: Settings) -> bool:
    """Whether turn speakers are people talking rather than labelled lines in a text (an agenda's ``签到 09:00``, a
    note's ``备注：``): the person or an unnamed 发言人 speaks, or a few names take turns again and again."""
    if any(settings.is_target(s) or _GENERIC_SPEAKER.fullmatch(s) for s in speakers):
        return True
    counts = Counter(speakers)
    return len(speakers) >= 4 and 2 <= len(counts) <= 0.6 * len(speakers)


def _text_to_messages(
    text: str, default_date: dt.date | None, speaker_lines: bool = False, timed: bool = False
) -> tuple[list[_Message], list[str]]:
    """``speaker_lines``: every ``speaker：text`` line starts a message (transcripts without times); otherwise only
    timestamped lines do and other lines continue the previous message (chat exports, where a message may contain a
    colon). ``timed``: a transcript whose turns carry clock times, where only those lines start a message."""
    messages: list[_Message] = []
    skipped: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if m := _INLINE.match(line):
            messages.append(_Message(_date(m["y"], m["m"], m["d"]), _speaker(m["speaker"]), m["text"]))
        elif m := _HEADER.match(line):
            messages.append(_Message(_date(m["y"], m["m"], m["d"]), _speaker(m["speaker"]), ""))
        elif speaker_lines and (turn := _timed_turn(line)):
            messages.append(_Message(default_date, *turn, clock=_turn_clock(line)))
        elif ((speaker_lines and not timed) or not messages) and (m := _PLAIN.match(line)):
            messages.append(_Message(default_date, _speaker(m["speaker"]), m["text"]))
        elif messages:
            last = messages[-1]
            last.text = f"{last.text}\n{line.strip()}" if last.text else line.strip()
        else:
            skipped.append(line[:120])
    return messages, skipped


def _with_identity_alias(settings: Settings, names: SpeakerNames | None = None) -> Settings:
    """``settings`` that also know the person by the name they gave and the names they claimed in transcripts."""
    names = names or stored_speaker_names(settings.db_path)
    extra = [n for n in (names.name, *names.aliases) if n and not settings.is_target(n)]
    return settings.model_copy(update={"target_aliases": [*settings.target_aliases, *extra]}) if extra else settings


NEEDS_NAME = "needs_name"


def is_transcript(source: Source) -> bool:
    """A multi-person text transcript whose speakers can be attributed again: not a recording (its speakers are
    claimed by voice), not the person's answer to a follow-up question, and with its real names still stored."""
    return (
        source.kind is SourceKind.INTERVIEW
        and not source.media_sha
        and source.text_state == "raw"
        and not source.origin.startswith("followup:")
    )


def attribute(
    source: Source, expressions: list[Expression], settings: Settings, names: SpeakerNames | None = None
) -> ParsedSource:
    """A transcript's lines attributed again with what the person said so far: their names and aliases everywhere,
    plus the labels they picked in this transcript. Nothing found leaves the transcript waiting
    (``media_status="needs_name"``) unless the person said none of its speakers is them: they picked nothing in it,
    or every speaker has a name they said is not theirs."""
    names = names or stored_speaker_names(settings.db_path)
    settings = _with_identity_alias(settings, names)
    claim = names.claims.get(source.source_id)
    if claim:
        settings = settings.model_copy(update={"target_aliases": [*settings.target_aliases, *claim]})
    messages = [_Message(e.date, e.speaker, e.text) for e in sorted(expressions, key=lambda e: e.idx)]
    parsed = _assemble(
        source.kind, source.title, source.origin, "", messages, settings, source.title, [], source.source_id
    )
    speakers = {e.speaker for e in parsed.expressions}
    decided = claim is not None or all(s in names.not_me for s in speakers)
    waiting = not any(e.is_target for e in parsed.expressions) and not decided
    parsed.source = source.model_copy(
        update={
            "n_expressions": len(parsed.expressions),
            "n_target": sum(e.is_target for e in parsed.expressions),
            "media_status": NEEDS_NAME if waiting else None,
        }
    )
    return parsed


def parse_chat(
    path_name: str, raw: str, settings: Settings, channel: str = "", *, allow_no_target: bool = False
) -> ParsedSource:
    settings = _with_identity_alias(settings)
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
    if not allow_no_target and not any(settings.is_target(m.speaker) for m in messages):
        raise ValueError(
            f"{path_name}: no message from {settings.target_name}; check target_name / target_aliases "
            f"(speakers seen: {', '.join(sorted({m.speaker for m in messages})[:8]) or 'none'})"
        )
    title = channel or Path(path_name).stem
    return _assemble(SourceKind.CHAT, title, path_name, raw, messages, settings, title, skipped)


def parse_interview(path_name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    """A transcript of several people. When none of its speakers is known to be the person, it is kept waiting for
    them to say which is (``attribute``) rather than refused, its lines all counted as someone else's meanwhile."""
    names = stored_speaker_names(settings.db_path)
    name = names.name or settings.target_name
    date = date or date_from_name(Path(path_name).stem)
    timed = sum(bool(_timed_turn(line)) for line in raw.splitlines()) >= MIN_TRANSCRIPT_HEADERS
    messages, skipped = _text_to_messages(raw, date, speaker_lines=True, timed=timed)
    for m in messages:
        m.date = m.date or date
    if not messages:
        raise ValueError(f"{path_name}：没有找到{name}或其他人的发言")
    title = Path(path_name).stem
    parsed = _assemble(SourceKind.INTERVIEW, title, path_name, raw, messages, settings, title, skipped)
    attributed = attribute(parsed.source, parsed.expressions, settings, names)
    attributed.skipped_lines = parsed.skipped_lines
    return attributed


# ---------------------------------------------------------------- meeting transcripts for the team's library


@dataclass(frozen=True)
class Turn:
    """One turn of a meeting transcript: who spoke, what was said, and when it began when the export timed it."""

    speaker: str
    text: str
    clock: float | None


@dataclass(frozen=True)
class TurnsFile:
    title: str
    date: dt.date | None
    turns: list[Turn]
    skipped: int


# Someone speaks again in a conversation; a text whose "label: words" lines never repeat a label is no conversation.
MIN_TURNS = 3


def parse_turns(name: str, data: bytes) -> TurnsFile:
    """The turns of a meeting transcript file, as 飞书妙记, 通义听悟 and 腾讯会议 export them (a speaker, often a time,
    and the words, on one line or the next) and as plain ``speaker：words`` lines. The speakers are the labels as
    written, for whoever imports it to say who they are (a name, or ``发言人1``). ``ValueError`` when the file is
    no transcript of several turns."""
    raw = extract_text(name, data)
    stem = Path(name).stem
    lines = raw.splitlines()
    date = date_from_name(stem) or next((day for line in lines[:12] if (day := parse_date(line)) is not None), None)
    timed = sum(bool(_timed_turn(line)) for line in lines) >= MIN_TRANSCRIPT_HEADERS
    messages, skipped = _text_to_messages(raw, date, speaker_lines=True, timed=timed)
    turns = [Turn(m.speaker, m.text.strip(), m.clock) for m in messages if m.text.strip()]
    speakers = {t.speaker for t in turns}
    if len(turns) < MIN_TURNS or len(turns) <= len(speakers):
        raise ValueError("没有找到按说话人分段的发言，请确认这是会议转写稿")
    return TurnsFile(stem, date, turns, len(skipped))


# ---------------------------------------------------------------- document


def _paragraphs(kind: SourceKind, path_name: str, raw: str, settings: Settings, date: dt.date | None) -> ParsedSource:
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
            )
        )
    return ParsedSource(_source(kind, title, path_name, source_id, expressions), expressions)


def parse_document(path_name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    """A text the person wrote: every paragraph is theirs. Markdown headings become the channel of what follows."""
    date = date or date_from_name(Path(path_name).stem)
    return _paragraphs(SourceKind.DOCUMENT, path_name, raw, settings, date)


# ---------------------------------------------------------------- diary

# A day's heading: the date opening a line, as a Markdown heading or not, with at most a few words after it (the
# weekday, the weather). 梦 among them marks the whole day as a dream; a paragraph of a day opening with 梦： or 【梦】
# is one. Words after the date that read as a sentence are the day's first words, not its heading.
_DIARY_HEADING = re.compile(rf"^\s*(?:#{{1,6}}\s*)?(?P<date>{_DATE})(?P<rest>.*)$")
_HEADING_WORDS = 12
_SENTENCE = re.compile(r"[，。！？；,.!?;]")
_DREAM_WORD = re.compile(r"(?:^|[\s·,，、(（\[【])梦(?:$|[\s·,，、)）\]】])")
_DREAM_PARAGRAPH = re.compile(r"^(?:【梦】|\[梦\]|梦\s*[：:])\s*")
# Days a text must open under before it is read as a diary.
MIN_DIARY_DAYS = 2


def _diary_day(line: str) -> tuple[dt.date, str, bool, str] | None:
    """The day a line opens: the date, the heading as written (without Markdown), whether the day is a dream, and the
    words after the date when they are the day's first words rather than its heading."""
    m = _DIARY_HEADING.match(line)
    if m is None or (day := _date(m["y"], m["m"], m["d"])) is None:
        return None
    rest = m["rest"].strip()
    words = rest.lstrip(" -—–:：·|").strip()
    if len(words) > _HEADING_WORDS or _SENTENCE.search(words):
        return day, m["date"], False, words
    return day, line.strip().lstrip("#").strip(), bool(_DREAM_WORD.search(rest)), ""


def is_diary(text: str) -> bool:
    """Whether ``text`` is written day by day: at least ``MIN_DIARY_DAYS`` different days under their own headings."""
    days = {found[0] for line in text.splitlines() if (found := _diary_day(line)) is not None}
    return len(days) >= MIN_DIARY_DAYS


def parse_diary(path_name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    """Entries the person wrote, each day under its date heading: every paragraph is theirs and dated by the heading
    above it (``date`` for what comes before the first one). Other Markdown headings name the paragraphs under them,
    after the day's. A dream (a day whose heading says 梦, or a paragraph or line opening with 梦： or 【梦】) is kept
    for the mirror only. A short line alone before the first day is the diary's title, not an entry."""
    title = Path(path_name).stem
    source_id = source_id_for(SourceKind.DIARY, path_name, raw)
    expressions: list[Expression] = []
    day, heading, dreaming = date, title, False
    started = False
    section = ""
    block: list[str] = []

    def flush() -> None:
        text = "\n".join(block).strip()
        block.clear()
        if not text:
            return
        if not started and not expressions and "\n" not in text and len(text) <= 20 and not _SENTENCE.search(text):
            return
        dream = dreaming or bool(_DREAM_PARAGRAPH.match(text))
        text = _DREAM_PARAGRAPH.sub("", text, count=1).strip() or text
        i = len(expressions)
        expressions.append(
            Expression(
                expression_id=f"{source_id}#{i:05d}",
                source_id=source_id,
                idx=i,
                date=day,
                speaker=settings.target_name,
                is_target=True,
                text=text,
                channel=f"{heading} · {section}" if section else heading,
                mirror="dream" if dream else "",
            )
        )

    for line in raw.splitlines():
        if (found := _diary_day(line)) is not None:
            flush()
            day, heading, dreaming, first = found
            started = True
            section = ""
            if first:
                block.append(first)
        elif m := re.match(r"^\s*#{1,6}\s+(.+)$", line):
            flush()
            section = m[1].strip()
        elif not line.strip():
            flush()
        elif _DREAM_PARAGRAPH.match(line.strip()):
            flush()
            block.append(line.strip())
        else:
            block.append(line)
    flush()
    return ParsedSource(_source(SourceKind.DIARY, title, path_name, source_id, expressions), expressions)


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
            current = _Question(int(m["n"]), text, facets, "【可跳过】" in text)
            current.text = current.text.replace("【可跳过】", "").strip()
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
                channel="回答几个问题",
                facets_hint=q.facets,
            )
        )
    title = Path(path_name).stem
    return ParsedSource(
        _source(SourceKind.QUESTIONNAIRE, title, path_name, source_id, expressions, sorted(set(declined))),
        expressions,
    )


def parse_media(source: Source, lines: list[tuple[str, str, bool]]) -> ParsedSource:
    """Use the same context assembly as chats, with an explicitly claimed target."""
    recent: list[str] = []
    expressions = [
        Expression(
            expression_id=f"{source.source_id}#{i:05d}",
            source_id=source.source_id,
            idx=i,
            date=parse_date(source.creation_time or ""),
            speaker=speaker,
            is_target=target,
            text=text,
            context=_message_context(recent, speaker, text, target),
            channel=source.title,
        )
        for i, (speaker, text, target) in enumerate(lines)
        if text.strip()
    ]
    dates = [e.date for e in expressions if e.date]
    source = source.model_copy(
        update={
            "n_expressions": len(expressions),
            "n_target": sum(e.is_target for e in expressions),
            "first_date": min(dates, default=None),
            "last_date": max(dates, default=None),
        }
    )
    return ParsedSource(source, expressions)


def parse_text(kind: SourceKind, name: str, raw: str, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    if kind is SourceKind.CHAT:
        return parse_chat(name, raw, settings)
    if kind is SourceKind.INTERVIEW:
        return parse_interview(name, raw, settings, date)
    if kind in {SourceKind.VIDEO, SourceKind.AUDIO}:
        return _paragraphs(kind, name, raw, settings, date)
    if kind is SourceKind.DOCUMENT:
        return parse_document(name, raw, settings, date)
    if kind is SourceKind.DIARY:
        return parse_diary(name, raw, settings, date)
    return parse_questionnaire(name, raw, settings, date)


MEMORY_KIND_LABELS = {
    SourceKind.DOCUMENT: "文档",
    SourceKind.CHAT: "聊天记录",
    SourceKind.QUESTIONNAIRE: "问卷",
    SourceKind.INTERVIEW: "访谈",
    SourceKind.VIDEO: "视频",
    SourceKind.AUDIO: "音频",
    SourceKind.DIARY: "日记",
}


def detect_kind(name: str, text: str, settings: Settings | None = None) -> SourceKind:
    settings = _with_identity_alias(settings or Settings())
    lines = [line for line in text.splitlines() if line.strip()]
    if any(_QUESTION.match(line) and _TAGS.search(line) for line in lines) and any(
        _ANSWER.match(line) for line in lines
    ):
        return SourceKind.QUESTIONNAIRE
    suffix = Path(name).suffix.lower()
    rows: list[dict[str, str]] = []
    if suffix == ".csv":
        rows = list(csv.DictReader(io.StringIO(text)))
    elif suffix == ".json":
        try:
            data = json.loads(text)
            data = data.get("messages", data) if isinstance(data, dict) else data
            if isinstance(data, list):
                rows = [row for row in data if isinstance(row, dict)]
        except ValueError:
            pass
    if any(_pick(row, _CSV_TIME) and _pick(row, _CSV_SENDER) and _pick(row, _CSV_TEXT) for row in rows):
        return SourceKind.CHAT
    if lines and sum(bool(_INLINE.match(line) or _HEADER.match(line)) for line in lines) / len(lines) >= 0.6:
        return SourceKind.CHAT
    timed = [turn[0] for line in lines if (turn := _timed_turn(line))]
    if len(timed) >= MIN_TRANSCRIPT_HEADERS and _talking(timed, settings):
        return SourceKind.INTERVIEW
    speakers = [_speaker(m["speaker"]) for line in lines if (m := _PLAIN.match(line))]
    if lines and len(speakers) / len(lines) >= 0.6 and any(settings.is_target(s) for s in speakers):
        return SourceKind.INTERVIEW
    # Turns that run over several lines: judge by turns, not lines, once the text opens with one (a title may come
    # first).
    if any(_PLAIN.match(line) for line in lines[:2]) and len(set(speakers)) >= 2 and _talking(speakers, settings):
        return SourceKind.INTERVIEW
    if is_diary(text):
        return SourceKind.DIARY
    return SourceKind.DOCUMENT


def parse_upload(
    name: str, data: bytes, settings: Settings, kind: SourceKind | None = None, date: dt.date | None = None
) -> ParsedSource:
    raw = extract_text(name, data)
    detected = kind or detect_kind(name, raw, settings)
    when = date or date_from_name(Path(name).stem)
    if when is None and detected is SourceKind.CHAT:
        when = next((day for line in raw.splitlines() if (day := parse_date(line)) is not None), None)
    when = when or dt.date.today()
    parsed = parse_text(detected, name, raw, settings, when)
    for expression in parsed.expressions:
        expression.date = expression.date or when
    dates = [e.date for e in parsed.expressions if e.date is not None]
    parsed.source.first_date = min(dates, default=when)
    parsed.source.last_date = max(dates, default=when)
    return parsed


def parse_note(text: str, settings: Settings, title: str | None = None) -> ParsedSource:
    if not 1 <= len(text) <= 20000 or not text.strip():
        raise ValueError("笔记需要 1–20000 个字")
    title = (title or "").strip() or f"笔记 {dt.datetime.now():%Y-%m-%d %H:%M}"
    parsed = parse_document(title + ".txt", text, settings, dt.date.today())
    parsed.source.title = title
    parsed.source.origin = "note:" + parsed.source.source_id
    return parsed


ANSWER_CHANNEL = "回答分身答不上的问题"


def parse_answer(
    question: str,
    answer: str,
    name: str,
    origin: str,
    *,
    previous: str = "",
    date: dt.date | None = None,
    channel: str = ANSWER_CHANNEL,
) -> ParsedSource:
    """The person's own answer to a question the twin could not answer: one expression in their words, the question
    (after ``previous``, the asker's turn before it, when there was one) as its context. ``origin`` names the question
    it answers; ``channel`` where it was answered."""
    answer = answer.strip()
    if not 1 <= len(answer) <= 20000:
        raise ValueError("回答需要 1–20000 个字")
    date = date or dt.date.today()
    asked = " ".join(question.split())
    source_id = source_id_for(SourceKind.INTERVIEW, origin, answer)
    expression = Expression(
        expression_id=f"{source_id}#00000",
        source_id=source_id,
        idx=0,
        date=date,
        speaker=name,
        is_target=True,
        text=answer,
        context=f"有人先问：{' '.join(previous.split())[:300]}；接着问：{asked[:500]}"
        if previous.strip()
        else f"有人问：{asked[:500]}",
        channel=channel,
    )
    title = f"回答：{asked if len(asked) <= 40 else asked[:39] + '…'}"
    return ParsedSource(_source(SourceKind.INTERVIEW, title, origin, source_id, [expression]), [expression])


def parse_source(kind: SourceKind | None, path: Path, settings: Settings, date: dt.date | None = None) -> ParsedSource:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise ValueError("每个文件最多 1 GB")
    return parse_upload(path.name, path.read_bytes(), settings, kind, date)
