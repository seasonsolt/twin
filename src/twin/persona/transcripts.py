"""Transcript ingestion: detect each file's format, normalise speakers, store meetings.

Formats are detected from the content (the suffix only picks JSON vs text vs subtitles):

- line transcripts: ``张三：内容`` / ``张三: 内容``, optionally with a leading timestamp
  (``[00:01:23] 张三: 内容``) or one after the name (``张三(00:01:23): 内容``, ``张三 00:01:23: 内容``);
- speaker header blocks (Feishu Minutes / Tingwu): ``说话人 1 00:01:23`` alone on a line, content below;
- SRT / WebVTT cues whose text starts with ``张三: `` (or a ``<v 张三>`` voice tag);
- JSON: our own ``Meeting`` dump, or FunASR ``AutoModel.generate`` output.

A label in front of a colon (or a timestamp) only counts as a speaker when it looks like a name: bounded
display width, no sentence punctuation, not an enumeration, a heading word or a sentence fragment
(``问题是``, ``我觉得``, ``上周``), and a long label must recur in the file or be a known name. A one-off
label whose timestamp breaks the time order of the recurring speakers (``会议改到 10:30`` inside a block)
is content too. Anything that is not a speaker continues the previous utterance.
"""

from __future__ import annotations

import bisect
import codecs
import datetime as dt
import json
import math
import numbers
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from ..config import Settings
from ..util import date_from_name
from .transcript_schema import Meeting, Utterance

SUPPORTED_SUFFIXES = {".txt", ".md", ".srt", ".vtt", ".json"}
SIDECAR_SUFFIX = ".speakers.json"
MAX_SPEAKER_WIDTH = 20
SHORT_SPEAKER_WIDTH = 8

_SUBTITLE_SUFFIXES = {".srt", ".vtt"}

_TS = r"\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d{1,3})?"
_RANGE = r"(?:-->|->|-|~|～|–|—|至)"
_OPEN = r"[\[(（【]"
_CLOSE = r"[\])）】]"
_LEAD_TS_RE = re.compile(
    rf"^(?:{_OPEN}\s*(?P<bts>{_TS})(?:\s*{_RANGE}\s*{_TS})?\s*{_CLOSE}|(?P<ts>{_TS})(?:\s*{_RANGE}\s*{_TS})?(?=\s|$))\s*"
)
_SPEAKER_RE = re.compile(
    rf"^(?P<label>[^:：]+?)(?:\s*{_OPEN}\s*(?P<bts>{_TS})(?:\s*{_RANGE}\s*{_TS})?\s*{_CLOSE}|\s+(?P<ts>{_TS}))?"
    r"\s*(?P<colon>[:：])\s*(?P<text>.*)$"
)
_HEADER_RE = re.compile(
    rf"^(?P<label>.+?)\s*(?:{_OPEN}\s*(?P<bts>{_TS})(?:\s*{_RANGE}\s*{_TS})?\s*{_CLOSE}"
    rf"|\s(?P<ts>{_TS})(?:\s*{_RANGE}\s*{_TS})?)$"
)
_CUE_TS = r"(?:\d+:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?"
_CUE_RE = re.compile(rf"^(?P<s>{_CUE_TS})\s*-->\s*(?P<e>{_CUE_TS})")
_CUE_SETTINGS_RE = re.compile(r"(?:\s+(?:vertical|line|position|size|align|region|X1|X2|Y1|Y2):\S+)*\s*")
_VTT_BLOCK_RE = re.compile(r"^(?:WEBVTT|NOTE|STYLE|REGION)(?:\s|$)")
_VOICE_RE = re.compile(r"^<v(?:\.[\w.-]+)?\s+(?P<name>[^>]+)>")
_TAG_RE = re.compile(
    r"</?(?:v|c|i|b|u|ruby|rt|lang|font)(?:[.\s][^>]*)?>|<\d{1,2}:\d{2}[^>]*>|\{\\[^}]*\}", re.IGNORECASE
)
_INVISIBLE_RE = re.compile(r"[\ufeff\u200b\u200c\u200d\u2060]")
_SEPARATOR_RE = re.compile(r"^[-=*_~—–·•]{3,}$")
_MD_HEADING_RE = re.compile(r"^#{1,6}(?:\s|$)")
_MD_PREFIX_RE = re.compile(r"^(?:>\s*|[-*+]\s+)+")
_WS_RE = re.compile(r"\s+")

_LABEL_FORBIDDEN = frozenset(':：，。！？；、,!?;"“”‘’「」『』《》〈〉…/\\|=<>{}')
_GENERIC_LABEL_RE = re.compile(r"^(?:说话人|发言人|讲话人|发言者|参会人|与会者|嘉宾|speaker|spk|guest)[_\-#]?\d+$")
_ENUMERATION_RE = re.compile(
    r"^(?:\(?[0-9一二三四五六七八九十百两]+\)|[第其]?[0-9一二三四五六七八九十百两]+[点条项个步类部]?)$"
)
_NON_SPEAKER_WORDS = """
首先 其次 再次 然后 最后 另外 此外 还有 同时 总之 总结 小结 结论 综上 比如 例如 举例 注 注意 备注 说明 补充 提示
重点 关键 核心 问题 原因 目标 目的 结果 方案 背景 现状 风险 建议 措施 计划 进展 下一步 待办 待办事项 行动项
时间 日期 地点 地址 主题 议题 标题 摘要 关键词 附件 链接 网址 邮箱 电话 会议主题 会议时间 会议日期 会议地点 会议名称
会议纪要 会议记录 纪要 记录人 参会人 参会人员 与会人员 出席人员 列席 缺席
负责人 截止 截止时间 截止日期 完成时间 时间节点 状态 优先级 进度 情况 数据 指标 预算 成本 收入 利润 营收
决定 决议 共识 分工 安排 任务 事项 议程 要求 口径
note notes todo summary agenda date time subject re fw fwd ps fyi eg ie e.g i.e http https
"""
_FRAGMENT_RE = re.compile(
    r"[我你您他她它咱俺们这哪]|那[么个些里样就]|什么|怎么|为何|如何|多少"
    r"|觉得|认为|感觉|以为|表示|指出|提到|强调|发现|知道|希望|估计|意思|问题|原因|关键|重点|核心"
    r"|所以|因为|如果|虽然|而且|并且|不过|但是|可是|其实|尤其|特别是|换句话|也就是"
    r"|今天|明天|昨天|今年|去年|明年|本周|上周|下周|本月|上月|下月|本季|上季|下季|目前|现在|当前|之前|以前|以后|之后|当时|最近"
    r"|(?:[是的了吗呢吧啊呀嘛着过说]|在于|如下|以下|包括|来说|而言|来看|看来|例如|比如)$"
)
_ENGLISH_FUNCTION_WORDS = """
is am are was were be been the a an to of for and or but so if then than we i you he she they it its this that
these those our my your his her their me us them here there what why how when where which
"""
_FUNCTION_WORDS = frozenset(_ENGLISH_FUNCTION_WORDS.split())
_ASCII_WORD_RE = re.compile(r"[A-Za-z']+")

_UNRECOGNISED = (
    "{path}: unrecognised transcript format. Expected lines like '张三：内容' or '[00:01:23] 张三: 内容'; "
    "speaker header lines like '说话人 1 00:01:23' followed by the content; SRT/VTT cues whose text starts "
    "with '张三: '; a Meeting JSON with 'utterances'; or FunASR JSON with 'sentence_info'"
)


@dataclass(frozen=True)
class _Line:
    """One source line: either a speaker candidate (``label``) or content (``raw``), or a bare timestamp."""

    raw: str = ""
    label: str | None = None
    text: str = ""
    start: float | None = None
    end: float | None = None
    explicit: bool = False


@dataclass
class _Turn:
    speaker: str
    text: str
    start: float | None
    end: float | None


@dataclass(frozen=True)
class _Subtitles:
    """Cue text lines, plus the other non-empty lines before the first cue and after it."""

    lines: list[_Line]
    preamble: list[str]
    outside: list[str]


@dataclass(frozen=True)
class _JsonContent:
    utterances: list[Utterance]
    meeting_id: str | None = None
    date: dt.date | None = None
    title: str | None = None


# ---------------------------------------------------------------- speaker labels


def _label_key(label: str) -> str:
    return _WS_RE.sub("", unicodedata.normalize("NFKC", label)).casefold()


_NON_SPEAKER_LABELS = frozenset(_label_key(w) for w in _NON_SPEAKER_WORDS.split())


def _label_width(label: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in label)


def _clean_label(label: str) -> str:
    label = " ".join(label.split())
    for opening, closing in (("[", "]"), ("【", "】")):
        if label.startswith(opening) and label.endswith(closing):
            label = label[1:-1].strip()
    return label


def _is_generic(key: str) -> bool:
    return _GENERIC_LABEL_RE.match(key) is not None


def _label_ok(label: str) -> bool:
    if not label or label[0].isdigit() or _label_width(label) > MAX_SPEAKER_WIDTH:
        return False
    if any(ch in _LABEL_FORBIDDEN for ch in label) or not any(ch.isalpha() for ch in label):
        return False
    key = _label_key(label)
    if _is_generic(key):
        return True
    if key in _NON_SPEAKER_LABELS or _ENUMERATION_RE.match(key) is not None or _FRAGMENT_RE.search(key):
        return False
    return not any(w.lower() in _FUNCTION_WORDS and not w.isupper() for w in _ASCII_WORD_RE.findall(label))


def _accepted_labels(lines: list[_Line], known: set[str]) -> set[str]:
    """Keys of the candidate labels that count as speakers in this file."""
    counts: Counter[str] = Counter()
    labels: dict[str, str] = {}
    explicit: set[str] = set()
    for line in lines:
        if line.label is None:
            continue
        key = _label_key(line.label)
        counts[key] += 1
        labels.setdefault(key, line.label)
        if line.explicit:
            explicit.add(key)
    return {
        key
        for key, label in labels.items()
        if key in explicit
        or key in known
        or (_label_ok(label) and (counts[key] >= 2 or _label_width(label) <= SHORT_SPEAKER_WIDTH or _is_generic(key)))
    }


def _demote_untimely(lines: list[_Line], known: set[str]) -> list[_Line]:
    """Turn one-off labels whose timestamp falls outside the time order of the recurring or known speakers'
    timestamps around them into content: a body line like ``会议改到 10:30`` looks like a header, real ones
    are in time order."""
    keys = [_label_key(line.label) if line.label is not None else None for line in lines]
    counts = Counter(key for key in keys if key is not None)
    accepted = _accepted_labels(lines, known)

    def anchored(key: str) -> bool:
        return key in accepted and (counts[key] >= 2 or key in known or _is_generic(key))

    anchors = [
        (i, line.start)
        for i, (line, key) in enumerate(zip(lines, keys, strict=True))
        if key is not None and line.start is not None and anchored(key)
    ]
    positions = [i for i, _ in anchors]
    out = list(lines)
    for i, (line, key) in enumerate(zip(lines, keys, strict=True)):
        if key is None or line.start is None or line.explicit or anchored(key):
            continue
        j = bisect.bisect_left(positions, i)
        before = anchors[j - 1][1] if j > 0 else None
        after = anchors[j][1] if j < len(anchors) else None
        if (before is not None and line.start < before) or (after is not None and line.start > after):
            out[i] = _Line(raw=line.raw)
    return out


def _speaker_hits(lines: list[_Line], known: set[str]) -> int:
    accepted = _accepted_labels(lines, known)
    return sum(1 for line in lines if line.label is not None and _label_key(line.label) in accepted)


# ---------------------------------------------------------------- text helpers


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        return data.decode("utf-16")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(f"{path}: cannot decode as UTF-8, UTF-16 or GB18030")


def _split_lines(text: str) -> list[str]:
    return [_INVISIBLE_RE.sub("", line).strip() for line in text.splitlines()]


def _strip_markdown(line: str) -> str:
    """Drop list/quote markers and bold; keep a heading only when it is a speaker header (``## 张三 00:01:23``)."""
    heading = _MD_HEADING_RE.match(line)
    line = _MD_PREFIX_RE.sub("", line[heading.end() :] if heading else line).replace("**", "").strip()
    if heading and _HEADER_RE.match(line) is None and _lead_ts(line)[0] is None:
        return ""
    return line


def _strip_tags(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


def _join(a: str, b: str) -> str:
    if not a:
        return b
    if not b:
        return a
    return f"{a} {b}" if a[-1].isascii() and b[0].isascii() else a + b


def _ts_seconds(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    hours = int(parts[-3]) if len(parts) == 3 else 0
    return round(hours * 3600 + int(parts[-2]) * 60 + float(parts[-1]), 3)


def _lead_ts(line: str) -> tuple[float | None, str, bool]:
    """(seconds, rest of line, whether the timestamp was bracketed) for a line starting with a timestamp."""
    m = _LEAD_TS_RE.match(line)
    if m is None:
        return None, line, False
    return _ts_seconds(m["bts"] or m["ts"]), line[m.end() :].strip(), m["bts"] is not None


def _split_speaker(text: str) -> tuple[str, float | None, str] | None:
    """(label, timestamp after the label, content) when ``text`` has the shape ``label：content``."""
    m = _SPEAKER_RE.match(text)
    if m is None:
        return None
    colon = m.start("colon")
    if m["colon"] == ":" and text[colon - 1 : colon].isdigit() and text[colon + 1 : colon + 2].isdigit():
        return None
    body = m["text"]
    if body.startswith(("//", "\\")):
        return None
    label = _clean_label(m["label"])
    if not label:
        return None
    ts = m["bts"] or m["ts"]
    return label, (_ts_seconds(ts) if ts else None), body.strip()


def _header(line: str, ts: float | None, rest: str) -> tuple[str, float] | None:
    """(label, seconds) for a speaker header line: ``说话人 1 00:01:23`` or ``[00:01:23] 说话人 1``."""
    m = _HEADER_RE.match(line)
    if m is not None:
        label = _clean_label(m["label"])
        if label and ":" not in label and "：" not in label:
            return label, _ts_seconds(m["bts"] or m["ts"])
    if ts is not None and rest and ":" not in rest and "：" not in rest:
        return _clean_label(rest), ts
    return None


# ---------------------------------------------------------------- format readers


def _line_mode(lines: list[str]) -> list[_Line]:
    out: list[_Line] = []
    for line in lines:
        if not line:
            continue
        ts, rest, bracketed = _lead_ts(line)
        if ts is not None and not rest:
            out.append(_Line(start=ts))
            continue
        content = rest if bracketed else line
        split = _split_speaker(rest)
        if split is None:
            out.append(_Line(raw=content))
            continue
        label, label_ts, text = split
        out.append(_Line(raw=content, label=label, text=text, start=ts if ts is not None else label_ts))
    return out


def _block_mode(lines: list[str]) -> list[_Line]:
    out: list[_Line] = []
    for line in lines:
        if not line:
            continue
        ts, rest, bracketed = _lead_ts(line)
        if ts is not None and not rest:
            out.append(_Line(start=ts))
            continue
        header = _header(line, ts, rest)
        if header is None:
            out.append(_Line(raw=rest if bracketed else line))
        else:
            out.append(_Line(raw=line, label=header[0], start=header[1]))
    return out


def _cue_line(line: str, start: float, end: float) -> _Line | None:
    voice = _VOICE_RE.match(line)
    if voice is not None and (label := _clean_label(voice["name"])):
        text = _strip_tags(line[voice.end() :])
        return _Line(raw=text, label=label, text=text, start=start, end=end, explicit=True)
    text = _strip_tags(line)
    if not text:
        return None
    split = _split_speaker(text)
    if split is None:
        return _Line(raw=text, end=end)
    return _Line(raw=text, label=split[0], text=split[2], start=start, end=end)


def _cue_timing(line: str) -> tuple[float, float] | None:
    """(start, end) of a cue timing line: the range alone on its line, apart from WebVTT cue settings or SRT
    coordinates. ``10:00 --> 11:30 产品培训`` is text, not a timing line."""
    m = _CUE_RE.match(line)
    if m is None or _CUE_SETTINGS_RE.fullmatch(line, m.end()) is None:
        return None
    return _ts_seconds(m["s"]), _ts_seconds(m["e"])


def _subtitle_lines(lines: list[str]) -> _Subtitles:
    """Cue text lines. Outside cues, cue identifiers and WebVTT header/NOTE/STYLE/REGION blocks are skipped and
    every other line is reported, as preamble before the first cue and as outside after it."""
    out: list[_Line] = []
    preamble: list[str] = []
    outside: list[str] = []
    cue: tuple[float, float] | None = None
    seen_cue = False
    in_block = False
    cue_lines = 0
    for i, line in enumerate(lines):
        timing = _cue_timing(line)
        if timing is not None:
            if cue_lines and out[-1].raw.isdigit():
                out.pop()
            cue = timing
            seen_cue = True
            in_block = False
            cue_lines = 0
        elif not line:
            cue = None
            in_block = False
            cue_lines = 0
        elif cue is not None:
            if (parsed := _cue_line(line, *cue)) is not None:
                out.append(parsed)
                cue_lines += 1
        elif in_block or _VTT_BLOCK_RE.match(line):
            in_block = True
        elif not _is_cue_id(lines, i):
            (outside if seen_cue else preamble).append(line)
    return _Subtitles(out, preamble, outside)


def _is_cue_id(lines: list[str], i: int) -> bool:
    """A line opening a block right before a timing line, unless it reads ``label: text``."""
    return (
        (i == 0 or not lines[i - 1])
        and i + 1 < len(lines)
        and _cue_timing(lines[i + 1]) is not None
        and _split_speaker(lines[i]) is None
    )


def _lost_outside_cues(subtitles: _Subtitles, known: set[str]) -> list[str]:
    """Lines a subtitle reading would drop that another reading keeps: everything outside cues after the first
    one, and the preamble from its first speaker line on (text before any speaker is dropped by every reader)."""
    parsed = _line_mode(subtitles.preamble)
    accepted = _accepted_labels(parsed, known)
    first = next(
        (i for i, line in enumerate(parsed) if line.label is not None and _label_key(line.label) in accepted),
        len(parsed),
    )
    return subtitles.preamble[first:] + subtitles.outside


def _assemble(lines: list[_Line], known: set[str]) -> list[Utterance]:
    accepted = _accepted_labels(lines, known)
    names: dict[str, str] = {}
    turns: list[_Turn] = []
    pending: float | None = None
    for line in lines:
        if line.label is not None and (key := _label_key(line.label)) in accepted:
            speaker = names.setdefault(key, line.label)
            turns.append(_Turn(speaker, line.text, line.start if line.start is not None else pending, line.end))
            pending = None
        elif line.raw and turns:
            turns[-1].text = _join(turns[-1].text, line.raw)
            if line.end is not None:
                turns[-1].end = line.end
        elif not line.raw and line.start is not None:
            pending = line.start
    return [Utterance(idx=i, speaker=t.speaker, text=t.text, start=t.start, end=t.end) for i, t in enumerate(turns)]


def _parse_text(text: str, path: Path, known: set[str]) -> list[Utterance]:
    """Subtitle files are read as cues. Other text is read line by line, as header blocks and as cues, and the
    reading with the most speaker lines wins. Cues win a tie, but only if they drop no text; if cues lead but
    would drop text, raise instead of losing it silently."""
    lines = _split_lines(text)
    suffix = path.suffix.lower()
    subtitles = _subtitle_lines(lines)
    if suffix in _SUBTITLE_SUFFIXES:
        utterances = _assemble(subtitles.lines, known)
        if not utterances:
            raise ValueError(
                f"{path}: subtitle cues carry no speaker labels; expected cue text like '张三: 内容' or '<v 张三>内容'"
            )
        return utterances
    if suffix == ".md":
        lines = [_strip_markdown(line) for line in lines]
    lines = ["" if _SEPARATOR_RE.match(line) else line for line in lines]
    by_line = _demote_untimely(_line_mode(lines), known)
    by_block = _demote_untimely(_block_mode(lines), known)
    line_hits = _speaker_hits(by_line, known)
    block_hits = _speaker_hits(by_block, known)
    cue_hits = _speaker_hits(subtitles.lines, known)
    best = max(line_hits, block_hits)
    if cue_hits and cue_hits >= best:
        lost = _lost_outside_cues(subtitles, known)
        if not lost:
            return _assemble(subtitles.lines, known)
        if cue_hits > best:
            raise ValueError(
                f"{path}: reads as subtitles, but {len(lost)} line(s) outside subtitle cues would be lost "
                f"(first: {lost[0]!r}); move them into a cue or delete them"
            )
    if best == 0:
        raise ValueError(_UNRECOGNISED.format(path=path))
    return _assemble(by_block if block_hits > line_hits else by_line, known)


# ---------------------------------------------------------------- JSON / FunASR


def _ms_to_seconds(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, numbers.Real):
        return None
    ms = float(value)
    return round(ms / 1000.0, 3) if math.isfinite(ms) and ms >= 0 else None


def _funasr_speaker(value: object) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        label = value.strip()
        if not label:
            return None
        return f"spk{int(label)}" if label.isdigit() else label
    if isinstance(value, numbers.Integral):
        return f"spk{int(value)}"
    if isinstance(value, float) and value.is_integer():
        return f"spk{int(value)}"
    return None


def _sentence_text(sentence: Mapping[Any, Any]) -> str:
    return str(sentence.get("text") or sentence.get("sentence") or "").strip()


def funasr_to_utterances(result: object) -> list[Utterance]:
    """Convert FunASR ``AutoModel.generate`` output (a list of results or one result) to utterances.

    Each result needs ``sentence_info: [{text, start, end, spk}]`` (VAD + punctuation + speaker model).
    Times are converted from ms to seconds, speakers become ``spk{n}``. A sentence without a speaker label
    keeps the previous speaker. Raises ``ValueError`` when the output has no sentence-level speaker labels.
    """
    results = list(result) if isinstance(result, list | tuple) else [result]
    sentences: list[Mapping[Any, Any]] = []
    for item in results:
        if not isinstance(item, Mapping):
            raise ValueError(f"unexpected FunASR result item of type {type(item).__name__}")
        info = item.get("sentence_info")
        if info is None:
            if str(item.get("text") or "").strip():
                raise ValueError(
                    "FunASR result has text but no 'sentence_info'; run AutoModel with vad_model, punc_model "
                    "and spk_model='cam++' so sentences carry timestamps and speaker labels"
                )
            continue
        if not isinstance(info, list):
            raise ValueError("FunASR 'sentence_info' must be a list")
        sentences.extend(s for s in info if isinstance(s, Mapping) and _sentence_text(s))
    labels = [_funasr_speaker(s.get("spk")) for s in sentences]
    present = [label for label in labels if label is not None]
    if sentences and not present:
        raise ValueError("FunASR output has no speaker labels ('spk'); run AutoModel with spk_model='cam++'")
    current = present[0] if present else ""
    utterances: list[Utterance] = []
    for sentence, label in zip(sentences, labels, strict=True):
        current = label or current
        utterances.append(
            Utterance(
                idx=len(utterances),
                speaker=current,
                text=_sentence_text(sentence),
                start=_ms_to_seconds(sentence.get("start")),
                end=_ms_to_seconds(sentence.get("end")),
            )
        )
    return utterances


def _is_funasr(data: object) -> bool:
    items: list[object] = list(data) if isinstance(data, list) else [data]
    dicts = [i for i in items if isinstance(i, dict)]
    return bool(dicts) and len(dicts) == len(items) and any("sentence_info" in i for i in dicts)


def _meeting_json(data: dict[str, Any], path: Path) -> _JsonContent:
    raw = data["utterances"]
    if not isinstance(raw, list):
        raise ValueError(f"{path}: 'utterances' must be a list")
    utterances: list[Utterance] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"{path}: utterances[{i}] is not an object")
        try:
            utterances.append(Utterance.model_validate({**item, "idx": i}))
        except ValidationError as e:
            raise ValueError(f"{path}: utterances[{i}] is invalid: {e}") from e
    date: dt.date | None = None
    if data.get("date"):
        try:
            date = dt.date.fromisoformat(str(data["date"]))
        except ValueError as e:
            raise ValueError(f"{path}: invalid date {data['date']!r}") from e
    meeting_id = data.get("meeting_id")
    title = data.get("title")
    return _JsonContent(
        utterances=utterances,
        meeting_id=str(meeting_id) if meeting_id else None,
        date=date,
        title=str(title) if title is not None else None,
    )


def _parse_json(text: str, path: Path) -> _JsonContent:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"{path}: invalid JSON: {e}") from e
    if isinstance(data, dict) and "utterances" in data:
        return _meeting_json(data, path)
    if _is_funasr(data):
        try:
            return _JsonContent(utterances=funasr_to_utterances(data))
        except ValueError as e:
            raise ValueError(f"{path}: {e}") from e
    raise ValueError(
        f"{path}: unrecognised JSON; expected a Meeting dump with 'utterances' or FunASR output with 'sentence_info'"
    )


# ---------------------------------------------------------------- meeting assembly


def _default_meeting_id(stem: str, date: dt.date) -> str:
    return stem if date_from_name(stem) is not None else f"{date.isoformat()}_{stem}"


def _sidecar_path(path: Path) -> Path:
    return path.with_name(path.stem + SIDECAR_SUFFIX)


def _is_sidecar(path: Path) -> bool:
    return path.name.lower().endswith(SIDECAR_SUFFIX)


def load_speaker_map(path: Path, overrides: Mapping[str, str] | None = None) -> dict[str, str]:
    """Raw speaker label → name: the sidecar ``<stem>.speakers.json`` next to ``path``, updated with ``overrides``."""
    mapping: dict[str, str] = {}
    sidecar = _sidecar_path(path)
    if sidecar.is_file():
        try:
            data = json.loads(_read_text(sidecar))
        except ValueError as e:
            raise ValueError(f"{sidecar}: invalid JSON: {e}") from e
        if not isinstance(data, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v.strip() for k, v in data.items()
        ):
            raise ValueError(
                f"{sidecar}: expected a JSON object mapping raw speaker labels to names, "
                'e.g. {"spk0": "本人", "说话人 2": "张三"}'
            )
        mapping.update(data)
    if overrides:
        if any(not name.strip() for name in overrides.values()):
            raise ValueError("speaker_map values must be non-empty names")
        mapping.update(overrides)
    return mapping


def _speaker_resolver(speaker_map: Mapping[str, str], settings: Settings) -> Callable[[str], str]:
    lookup = {_label_key(raw): " ".join(name.split()) for raw, name in speaker_map.items()}
    target_keys = {_label_key(name) for name in (settings.target_name, *settings.target_aliases)}

    def resolve(raw: str) -> str:
        label = _clean_label(raw)
        name = lookup.get(_label_key(label), label)
        return settings.target_name if _label_key(name) in target_keys else name

    return resolve


def _merge_consecutive(turns: list[_Turn]) -> list[_Turn]:
    merged: list[_Turn] = []
    for turn in turns:
        if merged and merged[-1].speaker == turn.speaker:
            previous = merged[-1]
            previous.text = _join(previous.text, turn.text)
            if previous.start is None:
                previous.start = turn.start
            if turn.end is not None:
                previous.end = turn.end
        else:
            merged.append(turn)
    return merged


def build_meeting(
    utterances: list[Utterance],
    path: Path,
    settings: Settings,
    *,
    speaker_map: Mapping[str, str] | None = None,
    meeting_date: dt.date | None = None,
    meeting_id: str | None = None,
    title: str | None = None,
    merge_consecutive: bool = True,
) -> Meeting:
    """Turn raw utterances read from ``path`` into a ``Meeting``.

    Speakers are mapped through ``speaker_map`` (applied as given; see ``load_speaker_map`` for the sidecar),
    then target aliases become ``settings.target_name``. Empty utterances are dropped, adjacent ones of the
    same speaker merged if ``merge_consecutive``, and ``idx`` renumbered 0..n-1. The date defaults to the one
    in the file name, the id to the file stem (prefixed with the ISO date when the stem has none).
    """
    date = meeting_date or date_from_name(path.stem)
    if date is None:
        raise ValueError(
            f"{path}: cannot determine the meeting date; put it in the file name "
            "(2025-03-17, 20250317, 2025_03_17 or 2025年3月17日) or pass it explicitly"
        )
    resolve = _speaker_resolver(speaker_map or {}, settings)
    turns = [_Turn(resolve(u.speaker), text, u.start, u.end) for u in utterances if (text := " ".join(u.text.split()))]
    if merge_consecutive:
        turns = _merge_consecutive(turns)
    if not turns:
        raise ValueError(f"{path}: no utterances found")
    return Meeting(
        meeting_id=meeting_id or _default_meeting_id(path.stem, date),
        date=date,
        title=title if title is not None else path.stem,
        source=str(path),
        utterances=[
            Utterance(idx=i, speaker=t.speaker, text=t.text, start=t.start, end=t.end) for i, t in enumerate(turns)
        ],
    )


def parse_transcript(
    path: Path,
    settings: Settings,
    speaker_map: dict[str, str] | None = None,
    meeting_date: dt.date | None = None,
    meeting_id: str | None = None,
    merge_consecutive: bool = True,
) -> Meeting:
    """Parse one transcript file (format auto-detected) into a normalised ``Meeting``.

    ``speaker_map`` entries override the sidecar ``<stem>.speakers.json``. Raises ``ValueError`` for an
    unsupported suffix, an unrecognised format, a missing date or a file without utterances.
    """
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(f"{path}: unsupported file type {path.suffix or '(none)'}; supported: {supported}")
    mapping = load_speaker_map(path, speaker_map)
    return parse_transcript_text(
        str(path), _read_text(path), settings, mapping, meeting_date, meeting_id, merge_consecutive
    )


def parse_transcript_text(
    name: str,
    text: str,
    settings: Settings,
    speaker_map: Mapping[str, str] | None = None,
    meeting_date: dt.date | None = None,
    meeting_id: str | None = None,
    merge_consecutive: bool = True,
) -> Meeting:
    """Parse uploaded text without reading or writing any server-side path."""
    path = Path(name)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"{name}: unsupported transcript type")
    mapping = speaker_map or {}
    title: str | None = None
    if suffix == ".json":
        content = _parse_json(text, path)
        utterances = content.utterances
        meeting_date = meeting_date or content.date
        meeting_id = meeting_id or content.meeting_id
        title = content.title
    else:
        known = {_label_key(n) for n in (settings.target_name, *settings.target_aliases, *mapping, *mapping.values())}
        utterances = _parse_text(text, path, known)
    return build_meeting(
        utterances,
        path,
        settings,
        speaker_map=mapping,
        meeting_date=meeting_date,
        meeting_id=meeting_id,
        title=title,
        merge_consecutive=merge_consecutive,
    )
