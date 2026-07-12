"""Reminder offsets + the ``ReminderSink`` seam (S8.3 decisions 1/6).

``OFFSETS``/``reminder_run_ats`` are pure -- no I/O -- so ``run_at`` computation
is fully unit-testable without a DB. ``ReminderSink`` is a ``typing.Protocol``
mirroring ``NotificationProvider``'s eventual shape; the only implementation
this sprint is ``LogReminderSink``, a deterministic, PII-safe stub that never
raises (dev/live-testable without a broker-external service -- mirrors S8.2's
``StubCalendarProvider``). S9.2 replaces the impl with one that enqueues a
real ``notification-service`` job; the scheduling side is unchanged by that
swap.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from common.auth import AuthClaims
from common.errors import ValidationError
from common.logging import get_logger

if TYPE_CHECKING:
    from common.db import Database

_log = get_logger(__name__)

# Offsets before ``starts_at`` a reminder fires at (S8.3 decision 2).
OFFSETS: dict[str, timedelta] = {
    "3d": timedelta(days=3),
    "24h": timedelta(hours=24),
    "1h": timedelta(hours=1),
}


def reminder_run_ats(starts_at: datetime) -> list[tuple[str, datetime]]:
    """Return ``[(offset, run_at), ...]`` for every offset, ``run_at = starts_at - offset``.

    Pure function -- no I/O, no "now" dependency. Order matches ``OFFSETS``
    insertion order (``"3d"``, ``"24h"``, ``"1h"``); callers that need a
    specific ordering (e.g. earliest-first) should sort explicitly.
    """
    return [(offset, starts_at - delta) for offset, delta in OFFSETS.items()]


@dataclass(frozen=True)
class ReminderDispatch:
    """Non-PII payload passed to a ``ReminderSink`` -- no contact details.

    Recipient resolution lives in ``notification-service`` (S9.1/S9.2); this
    sprint's sink has no contact details to send in the first place.
    """

    event_id: str
    offset: str
    run_at: datetime
    starts_at: datetime


@dataclass(frozen=True)
class DispatchRef:
    """Result of a successful ``ReminderSink.dispatch`` call."""

    sink: str
    ref: str


class ReminderSink(Protocol):
    """Outbound reminder-dispatch contract (mirrors ``NotificationProvider``)."""

    async def dispatch(self, claims: AuthClaims, reminder: ReminderDispatch) -> DispatchRef: ...


class ReminderSinkConfigError(ValidationError):
    """Deterministic reminder-sink config error -- raised before any dispatch."""

    code = "REMINDER_SINK_CONFIG_ERROR"


class LogReminderSink:
    """``ReminderSink`` implementation: a deterministic, PII-safe logging stub.

    Logs a single ``event="reminder_dispatched"`` line carrying only
    ``event_id``/``offset``/``tenant_id``/``run_at`` -- never consent text or
    contact fields (CLAUDE.md §3 PII discipline). Never raises, so it is
    fully dev/live-testable without a real notification channel. Returns a
    deterministic ``DispatchRef`` derived from the job id passed by the
    caller.
    """

    async def dispatch(self, claims: AuthClaims, reminder: ReminderDispatch) -> DispatchRef:
        _log.info(
            "reminder dispatched",
            extra={
                "event": "reminder_dispatched",
                "event_id": reminder.event_id,
                "offset": reminder.offset,
                "tenant_id": claims.tenant_id,
                "run_at": reminder.run_at.isoformat(),
            },
        )
        return DispatchRef(sink="log", ref=reminder.event_id)


def reminder_sink_for(sink: str, *, db: Database | None = None) -> ReminderSink:
    """Select a ``ReminderSink`` implementation for the configured ``sink`` name.

    Raises ``ReminderSinkConfigError`` for an unknown value -- deterministic,
    never retried, never a network call. Mirrors
    ``api.scheduling.calendar.calendar_provider_for`` /
    ``api.crm.sync.crm_sync_for``.

    ``db`` is required for ``"notification"`` (ignored for ``"log"``, which
    stays byte-identical to pre-S9.2 behaviour -- S9.2 decision 6/2). The
    ``NotificationReminderSink`` import is function-local so this module
    never imports ``api.notifications`` at load time -- breaks a circular
    import between scheduling and notifications (S9.2 constraint).
    """
    if sink == "log":
        return LogReminderSink()

    if sink == "notification":
        from api.notifications.reminder_sink import NotificationReminderSink  # noqa: PLC0415

        return NotificationReminderSink(db)  # type: ignore[arg-type]

    raise ReminderSinkConfigError(
        f"Unsupported reminder sink: {sink!r}.",
        code="REMINDER_SINK_NOT_SUPPORTED",
    )
