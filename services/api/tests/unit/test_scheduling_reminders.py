"""Unit tests for api.scheduling.reminders.

Covers:
- reminder_run_ats returns exactly {"3d", "24h", "1h"} at starts_at - 3d/-24h/-1h.
- LogReminderSink.dispatch returns a DispatchRef, logs a PII-safe line
  (no consent/contact fields), never raises.
- reminder_sink_for("log") -> the stub; unknown sink -> deterministic config error.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from common.auth import AuthClaims, Role
from common.errors import ValidationError


def _claims(tenant_id: str = "tenant-abc") -> AuthClaims:
    return AuthClaims(subject="visitor-1", role=Role.VISITOR, tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# reminder_run_ats
# ---------------------------------------------------------------------------


def test_reminder_run_ats_returns_exactly_three_offsets() -> None:
    from api.scheduling.reminders import reminder_run_ats

    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)
    result = reminder_run_ats(starts_at)

    offsets = {offset for offset, _run_at in result}
    assert offsets == {"3d", "24h", "1h"}
    assert len(result) == 3


def test_reminder_run_ats_computes_correct_utc_run_ats() -> None:
    from api.scheduling.reminders import reminder_run_ats

    starts_at = datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC)
    result = dict(reminder_run_ats(starts_at))

    assert result["3d"] == starts_at - timedelta(days=3)
    assert result["24h"] == starts_at - timedelta(hours=24)
    assert result["1h"] == starts_at - timedelta(hours=1)


def test_reminder_run_ats_order_independent_lookup() -> None:
    """Callers should look up by offset key, not rely on list order."""
    from api.scheduling.reminders import reminder_run_ats

    starts_at = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)
    as_dict = dict(reminder_run_ats(starts_at))

    assert as_dict["3d"] < as_dict["24h"] < as_dict["1h"] < starts_at


# ---------------------------------------------------------------------------
# LogReminderSink
# ---------------------------------------------------------------------------


async def test_log_reminder_sink_dispatch_returns_dispatch_ref() -> None:
    from api.scheduling.reminders import DispatchRef, LogReminderSink, ReminderDispatch

    sink = LogReminderSink()
    claims = _claims(tenant_id="tenant-abc")
    reminder = ReminderDispatch(
        event_id="event-1",
        offset="1h",
        run_at=datetime(2026, 7, 20, 13, 0, 0, tzinfo=UTC),
        starts_at=datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC),
    )

    ref = await sink.dispatch(claims, reminder)

    assert isinstance(ref, DispatchRef)
    assert ref.sink == "log"
    assert ref.ref == "event-1"


async def test_log_reminder_sink_logs_pii_safe_line_no_consent_or_contact_fields() -> None:
    from api.scheduling.reminders import LogReminderSink, ReminderDispatch

    sink = LogReminderSink()
    claims = _claims(tenant_id="tenant-abc")
    reminder = ReminderDispatch(
        event_id="event-1",
        offset="24h",
        run_at=datetime(2026, 7, 19, 14, 0, 0, tzinfo=UTC),
        starts_at=datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC),
    )

    with patch("api.scheduling.reminders._log") as mock_log:
        await sink.dispatch(claims, reminder)

    mock_log.info.assert_called_once()
    _msg, kwargs = mock_log.info.call_args
    extra = kwargs["extra"]

    assert extra["event"] == "reminder_dispatched"
    assert extra["event_id"] == "event-1"
    assert extra["offset"] == "24h"
    assert extra["tenant_id"] == "tenant-abc"
    assert "run_at" in extra

    forbidden = {"consent", "text", "email", "phone", "name", "contact"}
    assert forbidden.isdisjoint(extra.keys())


async def test_log_reminder_sink_never_raises() -> None:
    from api.scheduling.reminders import LogReminderSink, ReminderDispatch

    sink = LogReminderSink()
    claims = _claims(tenant_id="tenant-abc")
    reminder = ReminderDispatch(
        event_id="event-1",
        offset="3d",
        run_at=datetime(2026, 7, 17, 14, 0, 0, tzinfo=UTC),
        starts_at=datetime(2026, 7, 20, 14, 0, 0, tzinfo=UTC),
    )

    # Should not raise under any normal input.
    await sink.dispatch(claims, reminder)


# ---------------------------------------------------------------------------
# reminder_sink_for
# ---------------------------------------------------------------------------


def test_reminder_sink_for_log_returns_stub() -> None:
    from api.scheduling.reminders import LogReminderSink, reminder_sink_for

    sink = reminder_sink_for("log")

    assert isinstance(sink, LogReminderSink)


def test_reminder_sink_for_unknown_raises_deterministic_config_error() -> None:
    from api.scheduling.reminders import reminder_sink_for

    with pytest.raises(ValidationError) as exc_info:
        reminder_sink_for("not-a-real-sink")

    assert exc_info.value.code == "REMINDER_SINK_NOT_SUPPORTED"
