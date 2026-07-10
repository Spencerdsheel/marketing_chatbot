"""Unit tests for api.scheduling.slots.compute_slots -- pure, timezone-correct.

Covers:
- Correct count/spacing for an open weekday window.
- Timezone correctness: a 09:00 America/New_York slot maps to the right UTC instant.
- A DST-boundary date (America/New_York, 2026-03-08 spring-forward) behaves.
- A closed weekday produces no slots.
- Past slots are excluded via ``now``.
- A booked interval removes exactly its overlapping slot(s).
- Deterministic: same inputs -> same output.
- The window is capped (``window_max_days``) so it can't run unbounded.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from api.scheduling.slots import Slot, compute_slots

_RULES = {
    "slot_minutes": 30,
    "buffer_minutes": 0,
    "weekly_hours": {
        "mon": [["09:00", "17:00"]],
        "tue": [["09:00", "17:00"]],
        "wed": [["09:00", "17:00"]],
        "thu": [["09:00", "17:00"]],
        "fri": [["09:00", "17:00"]],
        "sat": [],
        "sun": [],
    },
}

_FAR_PAST_NOW = datetime(2000, 1, 1, tzinfo=UTC)


def _monday(d: date) -> date:
    """Return the Monday of the week containing ``d`` (helper for fixed fixtures)."""
    return d - timedelta(days=d.weekday())


def test_weekday_window_count_and_spacing() -> None:
    """09:00-17:00, 30-minute slots, no buffer -> 16 slots, 30 min apart."""
    monday = date(2026, 1, 5)  # a Monday
    slots = compute_slots(
        _RULES, "UTC", monday, monday, booked=[], now=_FAR_PAST_NOW
    )

    assert len(slots) == 16
    assert all(isinstance(s, Slot) for s in slots)
    for i in range(1, len(slots)):
        assert slots[i].starts_at - slots[i - 1].starts_at == timedelta(minutes=30)
    assert slots[0].starts_at == datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    assert slots[0].ends_at == datetime(2026, 1, 5, 9, 30, tzinfo=UTC)
    assert slots[-1].starts_at == datetime(2026, 1, 5, 16, 30, tzinfo=UTC)


def test_buffer_minutes_widens_spacing() -> None:
    """A 15-minute buffer widens spacing between successive slot starts."""
    rules = {
        "slot_minutes": 30,
        "buffer_minutes": 15,
        "weekly_hours": {"mon": [["09:00", "10:30"]], "tue": [], "wed": [], "thu": [],
                          "fri": [], "sat": [], "sun": []},
    }
    monday = date(2026, 1, 5)
    slots = compute_slots(rules, "UTC", monday, monday, booked=[], now=_FAR_PAST_NOW)

    # 09:00-09:30, 09:45-10:15 (10:15+30=10:45 > 10:30 window end for a 3rd)
    assert [s.starts_at.strftime("%H:%M") for s in slots] == ["09:00", "09:45"]


def test_timezone_correctness_new_york_maps_to_correct_utc() -> None:
    """A 09:00 America/New_York slot on a non-DST date maps to 14:00 UTC (EST, UTC-5)."""
    # 2026-01-05 is in EST (America/New_York is UTC-5 in January).
    monday = date(2026, 1, 5)
    slots = compute_slots(
        _RULES, "America/New_York", monday, monday, booked=[], now=_FAR_PAST_NOW
    )

    assert slots[0].starts_at == datetime(2026, 1, 5, 14, 0, tzinfo=UTC)


def test_dst_boundary_date_behaves() -> None:
    """2026-03-08 is the US spring-forward DST date for America/New_York.

    Before the transition (EST, UTC-5), after (EDT, UTC-4). A 09:00 local slot on
    that date is after the 2am transition, so it should be EDT (UTC-4) -> 13:00 UTC.
    The generator must not crash and must produce the expected slot count.
    """
    dst_date = date(2026, 3, 8)  # 2nd Sunday of March 2026 -- actually a Sunday.
    # Use a rules dict with a Sunday window so we exercise the boundary date itself.
    rules = {
        "slot_minutes": 30,
        "buffer_minutes": 0,
        "weekly_hours": {
            "mon": [], "tue": [], "wed": [], "thu": [], "fri": [], "sat": [],
            "sun": [["09:00", "11:00"]],
        },
    }
    slots = compute_slots(
        rules, "America/New_York", dst_date, dst_date, booked=[], now=_FAR_PAST_NOW
    )

    assert len(slots) == 4
    assert slots[0].starts_at == datetime(2026, 3, 8, 13, 0, tzinfo=UTC)  # 09:00 EDT
    # Deterministic UTC spacing across the boundary must still be 30 min apart.
    for i in range(1, len(slots)):
        assert slots[i].starts_at - slots[i - 1].starts_at == timedelta(minutes=30)


def test_closed_weekday_produces_no_slots() -> None:
    """Saturday has an empty weekly_hours list -> no slots."""
    saturday = date(2026, 1, 10)
    slots = compute_slots(_RULES, "UTC", saturday, saturday, booked=[], now=_FAR_PAST_NOW)

    assert slots == []


def test_past_slots_excluded_via_now() -> None:
    """A slot that starts before ``now`` is excluded."""
    monday = date(2026, 1, 5)
    now = datetime(2026, 1, 5, 12, 0, tzinfo=UTC)  # noon UTC on the same day
    slots = compute_slots(_RULES, "UTC", monday, monday, booked=[], now=now)

    assert all(s.starts_at >= now for s in slots)
    assert slots[0].starts_at == datetime(2026, 1, 5, 12, 0, tzinfo=UTC)


def test_booked_interval_removes_exactly_its_slot() -> None:
    """A booked interval exactly matching one slot removes only that slot."""
    monday = date(2026, 1, 5)
    booked = [(datetime(2026, 1, 5, 10, 0, tzinfo=UTC), datetime(2026, 1, 5, 10, 30, tzinfo=UTC))]
    slots = compute_slots(_RULES, "UTC", monday, monday, booked=booked, now=_FAR_PAST_NOW)

    starts = [s.starts_at for s in slots]
    assert datetime(2026, 1, 5, 10, 0, tzinfo=UTC) not in starts
    assert datetime(2026, 1, 5, 9, 30, tzinfo=UTC) in starts
    assert datetime(2026, 1, 5, 10, 30, tzinfo=UTC) in starts
    assert len(slots) == 15


def test_deterministic_same_inputs_same_output() -> None:
    """Calling compute_slots twice with identical inputs returns equal results."""
    monday = date(2026, 1, 5)
    booked = [(datetime(2026, 1, 5, 10, 0, tzinfo=UTC), datetime(2026, 1, 5, 10, 30, tzinfo=UTC))]

    first = compute_slots(_RULES, "UTC", monday, monday, booked=booked, now=_FAR_PAST_NOW)
    second = compute_slots(_RULES, "UTC", monday, monday, booked=booked, now=_FAR_PAST_NOW)

    assert first == second


def test_window_cap_enforced() -> None:
    """A window far exceeding window_max_days is clamped, not run unbounded."""
    monday = _monday(date(2026, 1, 5))
    date_to = monday + timedelta(days=400)  # way beyond any sane cap

    slots = compute_slots(
        _RULES, "UTC", monday, date_to, booked=[], now=_FAR_PAST_NOW, window_max_days=14
    )

    # Every slot must fall within [monday, monday + 14 days).
    cutoff = datetime(monday.year, monday.month, monday.day, tzinfo=UTC) + timedelta(days=14)
    assert all(s.starts_at < cutoff for s in slots)
    assert len(slots) > 0


def test_empty_date_range_end_before_start_returns_empty() -> None:
    """date_to before date_from returns an empty list, not an error."""
    slots = compute_slots(
        _RULES, "UTC", date(2026, 1, 10), date(2026, 1, 5), booked=[], now=_FAR_PAST_NOW
    )

    assert slots == []
