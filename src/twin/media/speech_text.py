"""Deterministic pronunciation hints, exclusively for synthesizer input."""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from typing import Final

from .schema import SynthCapabilities

SPEECH_TEXT_VERSION: Final = 3

_DIGITS = "零一二三四五六七八九"
_MEASURES = (
    *"个位名人件条次台套家份只本张头辆间座天周年岁倍吨米斤两克升万亿元百千亩页笔项块支艘所组种箱瓶包对双颗棵层",
    "小时",
    "分钟",
    "公里",
    "公斤",
    "平方",
    "秒",
)
_NUMBER = r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?"
_SIGNED = rf"-?{_NUMBER}"
_TOKENS = re.compile(
    rf"(?P<protected>"
    r"(?:https?://|ftp://|www\.)[^\s，。！？；<>]+"
    r"|[A-Za-z0-9_.+-]+@[A-Za-z0-9.-]+"
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:Z.+-]+"
    r"|[0-9]+(?:\.[0-9]+){2,}"
    r"|(?=[A-Za-z0-9_./:@+-]*[A-Za-z_])[A-Za-z0-9_]+(?:[./:@+-][A-Za-z0-9_]+)*)"
    r"|(?P<date>(?<![A-Za-z0-9_./:+-])(?:[0-9]{4}-[0-9]{2}-[0-9]{2}"
    r"|[0-9]{4}/[0-9]{2}/[0-9]{2})(?![A-Za-z0-9_/:+-]|\.[A-Za-z0-9_]))"
    r"|(?P<month_day>(?<![A-Za-z0-9_./:+-])(?:"
    r"[0-9]{1,2}/[0-9]{1,2}(?= ?(?:前|后|起|截止|日))"
    r"|(?:(?<=[于在到至])|(?<=[于在到至] ))[0-9]{1,2}/[0-9]{1,2})(?![A-Za-z0-9_./:+-]))"
    r"|(?P<phone>(?:\+86[- ]?)?1[3-9][0-9]{9}(?![0-9])"
    r"|0[0-9]{2,3}-[0-9]{7,8}(?![0-9])|[0-9]{3}-[0-9]{3}-[0-9]{4}(?![0-9]))"
    r"|(?P<year>[0-9]{4})(?=年)"
    r"|(?P<time>(?:[01]?[0-9]|2[0-3]):[0-5][0-9])(?![0-9:])"
    rf"|(?P<range>{_SIGNED}-{_SIGNED})"
    rf"|(?P<currency>[¥￥]{_SIGNED}[万亿]?元?)"
    rf"|(?P<percent>{_SIGNED}%)"
    rf"|(?P<number>{_SIGNED})"
)


def _digits(text: str) -> str:
    return "".join(_DIGITS[int(char)] if char in "0123456789" else char for char in text)


def _group(number: int, *, initial: bool) -> str:
    result = ""
    zero = False
    for position, unit in ((3, "千"), (2, "百"), (1, "十"), (0, "")):
        digit = number // 10**position % 10
        if not digit:
            zero = bool(result)
            continue
        if zero:
            result += "零"
            zero = False
        if digit == 1 and position == 1 and initial and not result:
            result += unit
        else:
            result += ("两" if digit == 2 and position >= 2 and not result else _DIGITS[digit]) + unit
    return result


def _integer(text: str, *, liang: bool = False) -> str:
    if len(text) > 16 or (len(text) > 1 and text.startswith("0")):
        return _digits(text)
    number = int(text)
    if number == 0:
        return "零"
    if number == 2 and liang:
        return "两"
    groups: list[int] = []
    while number:
        groups.append(number % 10000)
        number //= 10000
    result = ""
    zero = False
    for index in range(len(groups) - 1, -1, -1):
        value = groups[index]
        if not value:
            zero = bool(result)
            continue
        if result and (zero or value < 1000):
            result += "零"
        unit = ("", "万", "亿", "万亿")[index]
        result += ("两" if value == 2 and index else _group(value, initial=not result)) + unit
        zero = False
    return result


def _number(text: str, *, liang: bool = False) -> str:
    sign = "负" if text.startswith("-") else ""
    integer, dot, fraction = text.removeprefix("-").replace(",", "").partition(".")
    spoken = _integer(integer, liang=liang and not dot and not sign)
    return sign + spoken + ("点" + _digits(fraction) if dot else "")


def _cjk(char: str) -> bool:
    return any(
        start <= ord(char) <= end
        for start, end in ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF), (0x20000, 0x323AF))
    )


def _latin_digit(char: str) -> bool:
    return char.isdecimal() or (char.isalpha() and "LATIN" in unicodedata.name(char, ""))


def _boundary(left: str, right: str) -> bool:
    return (_cjk(left) and _latin_digit(right)) or (_latin_digit(left) and _cjk(right))


def _space_spans(spans: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Add pronunciation-only spaces with empty source spans; URL interiors remain opaque."""
    spaced: list[tuple[str, str]] = []
    previous = ""
    for original, spoken in spans:
        if previous and spoken and _boundary(previous, spoken[0]):
            spaced.append(("", " "))
        if original == spoken and not original.startswith(("https://", "http://", "ftp://", "www.")):
            start = 0
            for index in range(1, len(spoken)):
                if _boundary(spoken[index - 1], spoken[index]):
                    spaced.extend([(original[start:index], spoken[start:index]), ("", " ")])
                    start = index
            spaced.append((original[start:], spoken[start:]))
        else:
            spaced.append((original, spoken))
        if spoken:
            previous = spoken[-1]
    return spaced


def speech_text_spans(
    text: str, language: str, *, capabilities: SynthCapabilities | None = None
) -> list[tuple[str, str]]:
    """Return ordered original/spoken spans, retaining provenance for audio splitting.

    Valid ISO dates and unambiguous Chinese-context M/D are read as calendar dates.
    ISO timestamps, URLs and identifiers remain opaque. Bare local/mobile phone-like strings
    use digit readings; quantity/currency context takes precedence for bare numbers.
    Non-Chinese input is unchanged, including backend acronym hints.
    """
    if language != "zh":
        return [(text, text)] if text else []
    spans: list[tuple[str, str]] = []
    offset = 0
    for match in _TOKENS.finditer(text):
        if match.start() > offset:
            gap = text[offset : match.start()]
            spans.append((gap, gap))
        original = match.group()
        tail = text[match.end() :]
        following = tail[:1]
        quantity = tail.startswith(_MEASURES)
        ordinal = text[match.start() - 1 : match.start()] == "第"
        kind = match.lastgroup
        spoken = original
        if kind == "protected":
            if (
                capabilities is not None
                and not capabilities.reads_latin_acronyms
                and re.fullmatch(r"[A-Z]{2,5}", original)
            ):
                spoken = " ".join(original)
        elif kind in {"date", "month_day"}:
            fields = [int(field) for field in re.split(r"[-/]", original)]
            year, month, day = fields if kind == "date" else [2000, *fields]
            try:
                date(year, month, day)
            except ValueError:
                pass  # Invalid dates are opaque, not numbers or ranges.
            else:
                spoken = _digits(original[:4]) + "年" if kind == "date" else ""
                spoken += _integer(str(month)) + "月" + _integer(str(day))
                spoken += "" if tail.lstrip(" ").startswith("日") else "日"
        elif kind == "year":
            spoken = _digits(original)
        elif kind == "phone":
            spoken = _number(original) if original.isdigit() and quantity else _digits(original)
        elif kind == "time":
            hour, minute = original.split(":")
            spoken = _integer(str(int(hour))) + "点" + _integer(str(int(minute))) + "分"
        elif kind == "range":
            bounds = re.fullmatch(rf"({_SIGNED})-({_SIGNED})", original)
            assert bounds is not None
            spoken = _number(bounds[1], liang=not ordinal) + "到" + _number(bounds[2], liang=not ordinal)
        elif kind == "currency":
            amount = original[1:].removesuffix("元")
            unit = amount[-1] if amount[-1] in "万亿" else ""
            spoken = _number(amount.removesuffix(unit) if unit else amount, liang=True) + unit + "元"
        elif kind == "percent":
            amount = original[:-1]
            sign = "负" if amount.startswith("-") else ""
            spoken = sign + "百分之" + _number(amount.removeprefix("-"))
        elif kind == "number":
            phone_like = (
                original.isascii()
                and original.isdigit()
                and (len(original) in (7, 8) or (len(original) == 11 and original.startswith("1")))
            )
            liang = not ordinal and (quantity or not following or following in "，。！？；、,.!?; \n")
            spoken = (
                _digits(original) if phone_like and not quantity and not ordinal else _number(original, liang=liang)
            )
        spans.append((original, spoken))
        offset = match.end()
    if offset < len(text):
        spans.append((text[offset:], text[offset:]))
    return _space_spans(spans)


def speech_text(text: str, language: str, *, capabilities: SynthCapabilities | None = None) -> str:
    """Normalize numeric pronunciation and opt-in acronym spelling without changing content."""
    return "".join(spoken for _, spoken in speech_text_spans(text, language, capabilities=capabilities))
