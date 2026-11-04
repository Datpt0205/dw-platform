"""A company's day and month, in its own time zone (ADR-0121 decision 9; DO-50).

The one owner of where a day starts: the roll-up lane hands SQL the `[start,
end)` this returns, never a time zone to convert in SQL, and the limits'
counters of ticket 03 use the same function. A company with no time zone set
is in `Asia/Ho_Chi_Minh`.

Changing a company's time zone does not re-cut the days already rolled up; the
roll-up lane recomputes today and yesterday only (M1).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Final, Literal
from zoneinfo import ZoneInfo

__all__ = ["DEFAULT_TIMEZONE", "Window", "WindowKind", "window_bounds"]

DEFAULT_TIMEZONE: Final = "Asia/Ho_Chi_Minh"

WindowKind = Literal["day", "month"]


@dataclass(frozen=True)
class Window:
    """`[start, end)` in UTC, the local `day` it begins on, and the zone that cut it."""

    kind: WindowKind
    start: datetime
    end: datetime
    day: date
    timezone: str


def window_bounds(timezone: str | None, kind: WindowKind, at: datetime) -> Window:
    """The day or month containing `at`, cut in `timezone` (the default when
    `None`). An unknown zone name raises: guessing one would move every day
    boundary the company reads."""
    if at.tzinfo is None:
        raise ValueError("a window is asked for at an aware moment")
    name = timezone or DEFAULT_TIMEZONE
    zone = ZoneInfo(name)
    local = at.astimezone(zone)
    if kind == "day":
        first = local.date()
        following = first + timedelta(days=1)
    else:
        first = local.date().replace(day=1)
        following = (first + timedelta(days=32)).replace(day=1)
    start = datetime.combine(first, time(), tzinfo=zone)
    end = datetime.combine(following, time(), tzinfo=zone)
    return Window(
        kind=kind,
        start=start.astimezone(UTC),
        end=end.astimezone(UTC),
        day=first,
        timezone=name,
    )
