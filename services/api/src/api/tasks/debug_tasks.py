"""Debug Celery task: debug.ping.

A pure no-op task that proves the broker round-trip end-to-end. No database
access, no side effects. Every future task inherits the patterns established here:
- Uses ``_CorrelationTask`` as its base so correlation_id is bound automatically.
- Logs a structured ``task_completed`` event with ``task`` and ``event`` fields
  (both in ``_ALLOWED_EXTRA`` — they survive the JSON formatter's allowlist).
"""
from __future__ import annotations

from common.logging import get_logger

from api.tasks.celery_app import _CorrelationTask, celery_app

_log = get_logger(__name__)


@celery_app.task(bind=True, name="debug.ping", base=_CorrelationTask)  # type: ignore[untyped-decorator]
def ping(self: _CorrelationTask, *, correlation_id: str | None = None) -> dict[str, object]:
    """Enqueue-able no-op that confirms the worker is alive and the pipe works.

    Returns ``{"pong": True, "worker": <hostname>, "task_id": <uuid>}``.

    ``correlation_id`` MUST be declared here even though the base class
    ``__call__`` consumes it: Celery runs ``check_arguments`` inside
    ``apply_async`` at **enqueue time** — before ``__call__`` executes — and
    validates the passed kwargs against this run signature. Omitting it makes
    ``ping.delay(correlation_id=...)`` raise ``TypeError`` at enqueue. The base
    ``__call__`` pops it and binds it into the logging context, so the value is
    ``None`` inside this body (which ignores it). Every task following this
    pattern declares ``correlation_id`` for the same reason.
    """
    task_id: str = str(self.request.id or "")
    worker: str = str(self.request.hostname or "")

    _log.info(
        "debug.ping completed",
        extra={
            "task": "debug.ping",
            "event": "task_completed",
            "attempt": self.request.retries,
        },
    )

    return {"pong": True, "worker": worker, "task_id": task_id}
