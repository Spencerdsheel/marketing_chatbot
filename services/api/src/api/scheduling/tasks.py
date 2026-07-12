"""Celery tasks: scheduling.dispatch_due_reminders + scheduling.send_reminder (S8.3).

Same asyncio-loop-per-invocation + ``Database.connect(..., statement_cache_size=0)``
shape as ``api.crm.tasks`` (S5.1 pattern).

``dispatch_due_reminders`` is the Celery Beat periodic task (S8.3 decision 3):
it atomically claims due, pending reminder rows across ALL tenants (the
system-scoped ``claim_due_reminders`` -- decision 4) and ``.delay()``s one
``send_reminder`` per claimed row.

``send_reminder`` is per-job and re-scopes to exactly the claimed row's
tenant before touching any tenant data (decision 4). It is idempotent
(decision 5): a job not in ``queued`` status is a no-op (guards Celery
``acks_late`` redelivery from re-sending a job already ``sent``); a missing
or no-longer-``booked`` event marks the job ``skipped``; a deterministic sink
error (``ValidationError``, e.g. ``ReminderSinkConfigError``) marks the job
``failed`` and does NOT raise (no retry, mirrors ``api.crm.tasks``); any other
(transient) sink error propagates so Celery retries with backoff/jitter.

correlation_id (S5.1 rule): MUST be declared in every task signature. Celery
runs ``check_arguments`` inside ``apply_async`` at enqueue time, before the
base ``_CorrelationTask.__call__`` can consume it. Omitting it makes
``.delay(correlation_id=...)`` raise ``TypeError`` at enqueue.

PII discipline: log lines here carry only ``job_id``/``event_id``/``offset``/
``tenant_id`` -- never consent text or contact fields. The actual PII-safe
dispatch log line is emitted by ``LogReminderSink.dispatch`` itself.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from common.auth import AuthClaims, Role
from common.db import Database
from common.errors import ValidationError
from common.logging import get_logger

from api.notifications.recipients import NoRecipientError
from api.scheduling.reminder_repository import (
    ClaimedReminder,
    claim_due_reminders,
    get_reminder_job,
    mark_reminder,
)
from api.scheduling.reminders import ReminderDispatch, reminder_sink_for
from api.tasks.celery_app import _CorrelationTask, celery_app

_log = get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="scheduling.dispatch_due_reminders",
    base=_CorrelationTask,
)
def dispatch_due_reminders(
    self: _CorrelationTask,
    correlation_id: str | None = None,  # noqa: ARG001 — consumed by _CorrelationTask.__call__
) -> dict[str, object]:
    """Beat periodic task: claim due reminder rows and enqueue one send per row.

    Returns
    -------
    dict
        ``{"claimed": <count>}``.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_dispatch())
    finally:
        loop.close()


async def _run_dispatch() -> dict[str, object]:
    """Async inner body: open a DB connection and delegate to ``_execute_dispatch``."""
    from api.config import get_api_settings  # noqa: PLC0415

    settings = get_api_settings()
    db = await Database.connect(settings.database_url, statement_cache_size=0)
    try:
        return await _execute_dispatch(db, batch_size=settings.reminder_dispatch_batch_size)
    finally:
        await db.close()


async def _execute_dispatch(db: Database, *, batch_size: int) -> dict[str, object]:
    """Core claim -> per-row ``.delay()`` logic."""
    claimed: list[ClaimedReminder] = await claim_due_reminders(db, limit=batch_size)

    for row in claimed:
        send_reminder.delay(
            job_id=row.job_id,
            tenant_id=row.tenant_id,
            event_id=row.event_id,
            offset=row.offset,
        )

    _log.info(
        "reminders_claimed",
        extra={"event": "reminders_claimed", "count": len(claimed)},
    )
    return {"claimed": len(claimed)}


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="scheduling.send_reminder",
    base=_CorrelationTask,
)
def send_reminder(
    self: _CorrelationTask,
    *,
    job_id: str,
    tenant_id: str,
    event_id: str,
    offset: str,
    correlation_id: str | None = None,  # noqa: ARG001 — consumed by _CorrelationTask.__call__
) -> dict[str, object]:
    """Send (dispatch through the ``ReminderSink``) a single claimed reminder job.

    Parameters
    ----------
    job_id, tenant_id, event_id, offset:
        Trusted values from the claimed ``reminder_jobs`` row -- never from
        visitor input.
    correlation_id:
        Must be declared here (see module docstring). Consumed by
        ``_CorrelationTask.__call__`` before this body runs.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run_send(job_id, tenant_id, event_id, offset))
    finally:
        loop.close()


async def _run_send(job_id: str, tenant_id: str, event_id: str, offset: str) -> dict[str, object]:
    """Async inner body: open a DB connection and delegate to ``_execute_send``."""
    from api.config import get_api_settings  # noqa: PLC0415

    settings = get_api_settings()
    db = await Database.connect(settings.database_url, statement_cache_size=0)
    try:
        return await _execute_send(
            db, job_id=job_id, tenant_id=tenant_id, event_id=event_id, offset=offset,
            sink_name=settings.reminder_sink,
        )
    finally:
        await db.close()


async def _execute_send(
    db: Database,
    *,
    job_id: str,
    tenant_id: str,
    event_id: str,
    offset: str,
    sink_name: str,
) -> dict[str, object]:
    """Core re-read -> event-check -> dispatch -> flip logic (S8.3 decision 5).

    ``claims`` is built here from the claimed row's own ``tenant_id`` -- the
    system-scoped dispatcher's exactly-once claim re-scopes to a single
    tenant before this function does any tenant-scoped read/write.
    """
    claims = AuthClaims(subject="system:scheduling", role=Role.CLIENT_ADMIN, tenant_id=tenant_id)

    job = await get_reminder_job(db, claims, job_id)
    if job is None or job.status != "queued":
        # Redelivery guard: a job already sent/failed/skipped (or unknown) is
        # never re-dispatched.
        _log.info(
            "reminder_send_no_op",
            extra={
                "event": "reminder_send_no_op",
                "job_id": job_id,
                "tenant_id": tenant_id,
                "status": job.status if job is not None else "missing",
            },
        )
        return {"job_id": job_id, "status": "no_op"}

    event = await _get_event(db, claims, event_id)
    if event is None or event[0] != "booked":
        await mark_reminder(db, claims, job_id, status="skipped")
        _log.info(
            "reminder_skipped_event_not_booked",
            extra={
                "event": "reminder_skipped_event_not_booked",
                "job_id": job_id,
                "tenant_id": tenant_id,
            },
        )
        return {"job_id": job_id, "status": "skipped"}

    _, starts_at = event
    sink = reminder_sink_for(sink_name, db=db)
    reminder = ReminderDispatch(
        event_id=event_id, offset=offset, run_at=job.run_at, starts_at=starts_at
    )

    try:
        await sink.dispatch(claims, reminder)
    except NoRecipientError:
        # Auditable no-op: nothing went wrong, there was simply nobody to
        # remind (an anonymous booking with no lead/email). NOT a failure,
        # NOT retried (S9.2 decision 2/3).
        await mark_reminder(db, claims, job_id, status="skipped", last_error="NO_RECIPIENT")
        _log.info(
            "reminder_skipped_no_recipient",
            extra={
                "event": "reminder_skipped_no_recipient",
                "job_id": job_id,
                "tenant_id": tenant_id,
            },
        )
        return {"job_id": job_id, "status": "skipped"}
    except ValidationError as exc:
        # Deterministic sink error (bad config) -- do NOT raise, so Celery
        # does not retry (mirrors api.crm.tasks).
        await mark_reminder(db, claims, job_id, status="failed", last_error=str(exc))
        _log.warning(
            "reminder_dispatch_failed",
            extra={"event": "reminder_dispatch_failed", "job_id": job_id, "tenant_id": tenant_id},
        )
        return {"job_id": job_id, "status": "failed"}

    # Transient (network/broker) errors from dispatch propagate here so
    # Celery retries -- intentionally NOT caught.

    await mark_reminder(db, claims, job_id, status="sent")
    return {"job_id": job_id, "status": "sent"}


async def _get_event(
    db: Database, claims: AuthClaims, event_id: str
) -> tuple[str, datetime] | None:
    """Tenant-scoped ``(status, starts_at)`` lookup for a single schedule_events row."""
    row = await db.fetchrow(
        "SELECT status, starts_at FROM schedule_events WHERE tenant_id = $1 AND event_id = $2",
        claims.tenant_id,
        event_id,
    )
    if row is None:
        return None
    return str(row["status"]), row["starts_at"]
