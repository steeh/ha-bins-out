"""Pure collection-schedule logic. No Home Assistant imports, so it is easy to test."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from .const import (
    STATUS_COLLECTED,
    STATUS_FORGOTTEN,
    STATUS_NONE,
    STATUS_OUT,
    STATUS_TODAY,
    STATUS_TOMORROW,
    STATUS_UPCOMING,
)

# How far a one-off move (e.g. bank holiday) may shift a collection.
MAX_SHIFT = timedelta(days=14)


@dataclass(frozen=True)
class BinSchedule:
    """When a bin is collected.

    Either regular (every `interval_weeks` weeks from `first_collection`) or, when
    `fixed_dates` is set, exactly those dates (e.g. read from a council calendar).
    One-off `moved` and `cancelled` dates are applied on top of both.
    """

    first_collection: date | None = None
    interval_weeks: int = 1
    fixed_dates: tuple[date, ...] | None = None
    moved: dict[date, date] = field(default_factory=dict)
    cancelled: frozenset[date] = frozenset()

    def _base(self, start: date, end: date) -> list[date]:
        if self.fixed_dates is not None:
            return [d for d in self.fixed_dates if start <= d <= end]
        if self.first_collection is None or end < self.first_collection:
            return []
        step = timedelta(weeks=self.interval_weeks)
        if start <= self.first_collection:
            current = self.first_collection
        else:
            periods = -(-(start - self.first_collection).days // step.days)
            current = self.first_collection + step * periods
        dates = []
        while current <= end:
            dates.append(current)
            current += step
        return dates

    def collections(self, start: date, end: date) -> list[date]:
        """Collection dates in [start, end], with moves and cancellations applied."""
        candidates = self._base(start - MAX_SHIFT, end + MAX_SHIFT)
        # Moves whose original date isn't a scheduled date act as extra collections.
        extra = [d for d in self.moved if d not in candidates]
        result = {self.moved.get(d, d) for d in [*candidates, *extra]} - self.cancelled
        return sorted(d for d in result if start <= d <= end)

    def next_collection(self, today: date) -> date | None:
        """The first collection on or after `today`."""
        found = self.upcoming(today, 1)
        return found[0] if found else None

    def upcoming(self, today: date, count: int) -> list[date]:
        """The next `count` collections on or after `today`."""
        if self.fixed_dates is not None:
            end = max((*self.fixed_dates, *self.moved.values()), default=today)
        else:
            # Each cancellation can push the window out by one more collection.
            weeks = self.interval_weeks * (count + len(self.cancelled))
            end = today + timedelta(weeks=weeks) + MAX_SHIFT
        return self.collections(today, end)[:count]


@dataclass(frozen=True)
class BinState:
    """Everything the entities need to know about a bin at a moment in time."""

    next_collection: date | None
    days_until: int | None
    status: str
    put_out: bool
    due: bool
    forgotten: bool
    upcoming: list[date]


def compute_state(
    schedule: BinSchedule,
    now: datetime,
    put_out_for: date | None,
    evening_time: time,
    collection_time: time,
    upcoming_count: int = 6,
) -> BinState:
    """Work out a bin's state.

    `put_out_for` is the collection date the user said the bin was put out for.
    Stale values (before today) are ignored.
    """
    today = now.date()
    clock = now.time()
    upcoming = schedule.upcoming(today, upcoming_count)
    nxt = upcoming[0] if upcoming else None

    if nxt is None:
        return BinState(None, None, STATUS_NONE, False, False, False, [])

    days = (nxt - today).days
    put_out = put_out_for is not None and put_out_for == nxt
    forgotten = False

    if days == 0:
        if put_out:
            status = STATUS_COLLECTED if clock >= collection_time else STATUS_OUT
        elif clock >= collection_time:
            status = STATUS_FORGOTTEN
            forgotten = True
        else:
            status = STATUS_TODAY
        # Should go out now: collection day, not yet out, before the lorry comes.
        due = not put_out and clock < collection_time
    elif days == 1:
        status = STATUS_OUT if put_out else STATUS_TOMORROW
        due = not put_out and clock >= evening_time
    else:
        status = STATUS_OUT if put_out else STATUS_UPCOMING
        due = False

    return BinState(nxt, days, status, put_out, due, forgotten, upcoming)


def dates_from_events(events: list[dict], match: str) -> tuple[date, ...]:
    """Dates of calendar events whose summary contains `match` (case-insensitive).

    `events` are as returned by `calendar.get_events`: `start` is an ISO date or
    a local ISO datetime, so the first 10 characters are the local date.
    """
    needle = match.strip().lower()
    found = set()
    for event in events:
        if needle not in str(event.get("summary", "")).lower():
            continue
        try:
            found.add(date.fromisoformat(str(event.get("start", ""))[:10]))
        except ValueError:
            continue
    return tuple(sorted(found))


def spoken_name(name: str, colour: str) -> str:
    """'Recycling' + 'blue' -> 'blue recycling bin'."""
    text = name.strip().lower()
    if colour and colour.lower() not in text:
        text = f"{colour.lower()} {text}"
    if "bin" not in text:
        text = f"{text} bin"
    return text


def join_names(names: list[str]) -> str:
    """['a', 'b', 'c'] -> 'the a, the b and the c'."""
    parts = [f"the {n}" for n in names]
    if len(parts) <= 1:
        return "".join(parts)
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def evening_message(names: list[str]) -> str | None:
    if not names:
        return None
    return f"Reminder: put {join_names(names)} out tonight. Collection is tomorrow."


def morning_message(names: list[str]) -> str | None:
    if not names:
        return None
    return f"It's bin day! Put {join_names(names)} out now."


def forgotten_message(names: list[str]) -> str | None:
    if not names:
        return None
    verb = "were" if len(names) > 1 else "was"
    return f"Looks like {join_names(names)} {verb} not put out for collection today."
