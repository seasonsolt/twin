"""When a question points at a time relative to today ("last Saturday", "four weeks ago", "上周六"), the dates it
can mean. Retrieval then also looks among what the person said in that window: "who did I go with last Saturday"
shares few words with the message that answers it, but that message was said around that day.
"""

from __future__ import annotations

import datetime as dt
import re

_NUMBERS = {
    "a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
    "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5,
}  # fmt: skip
_WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6,
}  # fmt: skip
# Days per unit, and how far either side of the computed day the event or its mention may fall.
_UNITS = {
    "day": (1, 2), "week": (7, 3), "month": (30.44, 10), "year": (365.25, 45),
    "天": (1, 2), "日": (1, 2), "周": (7, 3), "星期": (7, 3), "个星期": (7, 3), "个月": (30.44, 10), "月": (30.44, 10),
    "年": (365.25, 45),
}  # fmt: skip
_NUMBER = (
    r"(\d+(?:\.\d+)?|an?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|[一两二三四五六七八九十半])"
)
_AGO = re.compile(rf"\b{_NUMBER}\s+(day|week|month|year)s?\s+ago\b", re.IGNORECASE)
_AGO_ZH = re.compile(rf"{_NUMBER}\s*(个星期|星期|个月|天|日|周|月|年)(?:之|以)?前")
_LAST_WEEKDAY = re.compile(r"\blast\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.IGNORECASE)
_LAST_WEEKDAY_ZH = re.compile(r"上(?:个)?(?:周|星期|礼拜)([一二三四五六日天])")
_YESTERDAY = re.compile(r"\byesterday\b|昨天")
_DAY_BEFORE = re.compile(r"\bday before yesterday\b|前天")
_LAST_WEEK = re.compile(r"\blast week\b|上(?:个)?(?:周|星期|礼拜)(?![一二三四五六日天])", re.IGNORECASE)
_LAST_MONTH = re.compile(r"\blast month\b|上个月", re.IGNORECASE)
_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
           "november", "december")  # fmt: skip
_IN_MONTH = re.compile(rf"\b(?:in|during)\s+({'|'.join(_MONTHS)})(?:\s+(\d{{4}}))?\b", re.IGNORECASE)
_IN_MONTH_ZH = re.compile(r"(?:(\d{4})年)?(1[0-2]|[1-9]|十[一二]?|[一二三四五六七八九])月份?(?!前|以前|之前)")


def time_window(text: str, today: dt.date) -> tuple[dt.date, dt.date] | None:
    """The first relative time in ``text``, as an inclusive date range no later than ``today``; None without one."""
    found: list[tuple[int, dt.date, int]] = []  # (position, centre, slack in days)
    for pattern in (_AGO, _AGO_ZH):
        for ago in pattern.finditer(text):
            amount = float(ago.group(1)) if ago.group(1)[0].isdigit() else _NUMBERS[ago.group(1).lower()]
            days, slack = _UNITS[ago.group(2).lower()]
            found.append((ago.start(), today - dt.timedelta(days=round(amount * days)), slack))
    for pattern in (_LAST_WEEKDAY, _LAST_WEEKDAY_ZH):
        for last in pattern.finditer(text):
            back = (today.weekday() - _WEEKDAYS[last.group(1).lower()]) % 7 or 7
            found.append((last.start(), today - dt.timedelta(days=back), 1))
    fixed = ((_DAY_BEFORE, 2, 1), (_YESTERDAY, 1, 1), (_LAST_WEEK, 7, 4), (_LAST_MONTH, 30, 15))
    for pattern, back, slack in fixed:
        if (match := pattern.search(text)) is not None:
            found.append((match.start(), today - dt.timedelta(days=back), slack))
    if not found:
        return None
    _, centre, slack = min(found, key=lambda f: f[0])
    # The person may mention an event a few days after it happened, so the window reaches a little further forward.
    return centre - dt.timedelta(days=slack), min(today, centre + dt.timedelta(days=slack + 2))


def named_month(text: str, today: dt.date) -> tuple[dt.date, dt.date] | None:
    """The calendar month a question names ("in March", "3月份"), as an inclusive date range; without a year it is
    the latest such month not after ``today``. None when no month is named."""
    if (english := _IN_MONTH.search(text)) is not None:
        month, year = _MONTHS.index(english.group(1).lower()) + 1, english.group(2)
    elif (chinese := _IN_MONTH_ZH.search(text)) is not None:
        number = chinese.group(2)
        tens = number[0] == "十"
        month = int(number) if number.isdigit() else int(10 * tens + _NUMBERS.get(number[tens:], 0))
        year = chinese.group(1)
    else:
        return None
    start = dt.date(int(year) if year else today.year - (month > today.month), month, 1)
    following = dt.date(start.year + start.month // 12, start.month % 12 + 1, 1)
    return start, following - dt.timedelta(days=1)


_DAY_ZH = re.compile(r"(?:(\d{4})年)?(1[0-2]|0?[1-9])月(3[01]|[12]\d|0?[1-9])[日号]")
_SECOND_LAST = re.compile(r"上上(?:一)?次")
_LAST_FEW = re.compile(r"最近(?:两|三|几)次")
_LAST_ONE = re.compile(r"最近一次|最新一次|最近的一次|最近那次|上一次|上次")
# How many of the latest meetings "最近几次" means.
LAST_FEW = 3


def meeting_window(text: str, days: list[dt.date], today: dt.date) -> tuple[dt.date, dt.date] | None:
    """The meetings a question names by their day ("7月8号的会"), month ("2019年7月") or order ("最近一次",
    "上上次", "最近几次"), as an inclusive date range among ``days`` (the twin's meeting days, in order). A day
    without a year is the latest meeting on that day; None when the question names no meeting this way."""
    past = [d for d in days if d <= today]
    if not past:
        return None
    if (day := _DAY_ZH.search(text)) is not None:
        month, number = int(day.group(2)), int(day.group(3))
        if day.group(1):
            try:
                named = dt.date(int(day.group(1)), month, number)
            except ValueError:
                return None
            return named, named
        same = [d for d in past if (d.month, d.day) == (month, number)]
        return (same[-1], same[-1]) if same else None
    if (span := named_month(text, today)) is not None:
        return span if any(span[0] <= d <= span[1] for d in past) else None
    if _SECOND_LAST.search(text):
        return (past[-2], past[-2]) if len(past) > 1 else None
    if _LAST_FEW.search(text):
        return past[-LAST_FEW:][0], past[-1]
    if _LAST_ONE.search(text):
        return past[-1], past[-1]
    return None
