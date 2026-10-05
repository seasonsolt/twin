"""Lossless transcript corpus contracts; no meeting runtime."""

from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class Utterance(BaseModel):
    idx: int
    speaker: str
    text: str
    start: float | None = None
    end: float | None = None


class Meeting(BaseModel):
    meeting_id: str
    date: dt.date
    title: str = ""
    source: str = ""
    utterances: list[Utterance]
