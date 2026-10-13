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
