"""节奏提醒 (docs/PRODUCT_PERSONA_AGENT.md P3.6): a pace the person sets themself for talking with their twin, and one
line when it is reached, so that keeping them company does not turn into leaning on it.

Off unless the person turns it on: at most so many minutes a day, or so many times a week. Nothing new is counted or
kept of their use: how long and how often they talked is read from when they wrote in their own conversations, which
are already kept on this machine. A time is a run of their messages with no gap over ``SESSION_GAP``; its length runs
from its first message to its last, plus ``MESSAGE_MINUTES`` for the last. Days and weeks (from Monday) are the
machine's own. Once they choose to go on, the line is not said again that day.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .store import PersonaStore

Kind = Literal["off", "daily_minutes", "weekly_times"]
PACE_KEY = "pace"
QUIET_KEY = "pace:quiet"
SESSION_GAP = dt.timedelta(minutes=30)
MESSAGE_MINUTES = 1
REMINDER = "今天聊了挺久了，要不要先停一停？"


class Pace(BaseModel):
    """The pace the person set: off, or at most ``limit`` minutes a day or ``limit`` times a week."""

    model_config = ConfigDict(extra="forbid")
    kind: Kind = "off"
    limit: int = Field(default=30, ge=1, le=1440)


class Used(BaseModel):
    minutes_today: int
    times_week: int


def get(store: PersonaStore) -> Pace:
    raw = store.get_meta(PACE_KEY)
    return Pace.model_validate_json(raw) if raw else Pace()


def put(store: PersonaStore, pace: Pace) -> None:
    store.set_meta(PACE_KEY, pace.model_dump_json())


def _sessions(times: list[dt.datetime]) -> list[tuple[dt.datetime, dt.datetime]]:
    """Runs of messages with no gap over ``SESSION_GAP``, as (first, last)."""
    runs: list[tuple[dt.datetime, dt.datetime]] = []
    for at in sorted(times):
        if runs and at - runs[-1][1] <= SESSION_GAP:
            runs[-1] = (runs[-1][0], at)
        else:
            runs.append((at, at))
    return runs


def used(store: PersonaStore, owner: str | None, now: dt.datetime) -> Used:
    """How long the person talked today and how many times this week, on the clock of ``now`` (timezone-aware)."""
    week_start = dt.datetime.combine(now.date() - dt.timedelta(days=now.weekday()), dt.time(), now.tzinfo)
    # A run that began late the evening before still counts for the part of it today.
    since = min(week_start, dt.datetime.combine(now.date(), dt.time(), now.tzinfo)) - SESSION_GAP
    stamps = [dt.datetime.fromisoformat(s) for s in store.owner_messages_since(owner, since.astimezone(dt.UTC))]
    local = [s.astimezone(now.tzinfo) if s.tzinfo else s.replace(tzinfo=dt.UTC).astimezone(now.tzinfo) for s in stamps]
    runs = _sessions(local)
    midnight = dt.datetime.combine(now.date(), dt.time(), now.tzinfo)
    minutes = sum(
        (last - max(first, midnight)).total_seconds() / 60 + MESSAGE_MINUTES for first, last in runs if last >= midnight
    )
    return Used(minutes_today=round(minutes), times_week=sum(1 for _, last in runs if last >= week_start))


def due(pace: Pace, use: Used) -> bool:
    """Whether the pace is reached: the day's minutes, or a time beyond the week's."""
    if pace.kind == "daily_minutes":
        return use.minutes_today >= pace.limit
    if pace.kind == "weekly_times":
        return use.times_week > pace.limit
    return False


def quiet(store: PersonaStore, today: dt.date) -> bool:
    """Whether the person chose to go on today, so the line is not said again."""
    return store.get_meta(QUIET_KEY) == today.isoformat()


def go_on(store: PersonaStore, today: dt.date) -> None:
    store.set_meta(QUIET_KEY, today.isoformat())


def state(store: PersonaStore, owner: str | None, now: dt.datetime) -> dict[str, object]:
    """What the page needs: the pace, what was used, and the line to show now, if any."""
    pace = get(store)
    if pace.kind == "off":
        return {"pace": pace.model_dump(), "used": None, "reminder": None}
    use = used(store, owner, now)
    remind = due(pace, use) and not quiet(store, now.date())
    return {"pace": pace.model_dump(), "used": use.model_dump(), "reminder": REMINDER if remind else None}
