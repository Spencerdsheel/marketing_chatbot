"""Pure, timezone-correct slot generation (S8.1 decision 2).

``compute_slots`` has NO I/O: given a tenant's availability rules + IANA
timezone, a bounded date window, already-booked intervals, and the current
time, it deterministically returns the open ``Slot``s (UTC). Callers
(``api.scheduling.routes``) are responsible for fetching ``rules``/``tz`` from
the repository and ``booked`` from ``list_booked`` -- this module never talks
to the database.

DST is handled entirely by the stdlib ``zoneinfo`` module: each candidate slot
is first built as an aware local datetime in the tenant's timezone, then
converted to UTC. This is safe across both directions of a DST transition.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

# Python's date.weekday(): Monday=0 .. Sunday=6.
_WEEKDAY_KEYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class Slot:
    """A single open booking slot, expressed in UTC."""

    starts_at: datetime
    ends_at: datetime


def compute_slots(
    rules: dict[str, Any],
    tz: str,
    date_from: date,
    date_to: date,
    booked: list[tuple[datetime, datetime]],
    *,
    now: datetime,
    window_max_days: int = 60,
) -> list[Slot]:
    """Compute the open UTC slots for ``[date_from, date_to]`` (inclusive).

    ``rules`` is the validated availability shape: ``{"slot_minutes": int>0,
    "buffer_minutes": int>=0, "weekly_hours": {"mon": [["09:00","17:00"], ...],
    ...}}``. ``booked`` is a list of ``(starts_at, ends_at)`` UTC-aware
    intervals to exclude (already-booked events). ``now`` excludes any slot
    that starts in the past. The window is capped at ``window_max_days`` from
    ``date_from`` regardless of how far ``date_to`` reaches, so a caller-
    supplied window can never make this run unbounded.

    Deterministic: identical inputs always produce identical output (no
    randomness, no wall-clock reads other than the injected ``now``).
    """
    if date_to < date_from:
        return []

    capped_date_to = min(date_to, date_from + timedelta(days=window_max_days - 1))

    zone = ZoneInfo(tz)
    slot_minutes = int(rules["slot_minutes"])
    buffer_minutes = int(rules.get("buffer_minutes", 0))
    weekly_hours: dict[str, list[list[str]]] = rules.get("weekly_hours", {})

    duration = timedelta(minutes=slot_minutes)
    step = timedelta(minutes=slot_minutes + buffer_minutes)

    slots: list[Slot] = []
    current_date = date_from
    while current_date <= capped_date_to:
        weekday_key = _WEEKDAY_KEYS[current_date.weekday()]
        for window in weekly_hours.get(weekday_key, []):
            slots.extend(
                _slots_for_window(current_date, window, zone, duration, step, booked, now)
            )
        current_date += timedelta(days=1)

    return slots


def _slots_for_window(
    day: date,
    window: list[str],
    zone: ZoneInfo,
    duration: timedelta,
    step: timedelta,
    booked: list[tuple[datetime, datetime]],
    now: datetime,
) -> list[Slot]:
    start_h, start_m = _parse_hhmm(window[0])
    end_h, end_m = _parse_hhmm(window[1])
    local_window_end = datetime(day.year, day.month, day.day, end_h, end_m, tzinfo=zone)

    slots: list[Slot] = []
    local_slot_start = datetime(day.year, day.month, day.day, start_h, start_m, tzinfo=zone)
    while local_slot_start + duration <= local_window_end:
        utc_start = local_slot_start.astimezone(UTC)
        utc_end = (local_slot_start + duration).astimezone(UTC)
        if utc_start >= now and not _overlaps(utc_start, utc_end, booked):
            slots.append(Slot(starts_at=utc_start, ends_at=utc_end))
        local_slot_start = local_slot_start + step

    return slots


def _parse_hhmm(value: str) -> tuple[int, int]:
    hour_str, minute_str = value.split(":")
    return int(hour_str), int(minute_str)


def _overlaps(
    start: datetime, end: datetime, booked: list[tuple[datetime, datetime]]
) -> bool:
    return any(start < b_end and b_start < end for b_start, b_end in booked)
