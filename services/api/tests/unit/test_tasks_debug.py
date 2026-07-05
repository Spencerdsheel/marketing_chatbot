"""Unit tests for debug_tasks.ping — eager mode, no real broker.

Covers:
- ping returns {"pong": True, "worker": ..., "task_id": ...}.
- Correlation propagation: calling with correlation_id="abc123" results in the
  ContextVar carrying "abc123" during task execution (verified via a capturing wrapper).
- Calling without a correlation_id still produces a non-empty correlation_id.
- The "task" and "event" structured fields are logged (allowlist survives) —
  verified by adding the caplog handler to the task's logger directly.
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any
from unittest.mock import patch

# -- Env bootstrap -------------------------------------------------------------

_TEST_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": "x" * 48,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}


def _reset_modules() -> None:
    """Remove cached task/config modules to allow fresh imports under patched env."""
    for key in list(sys.modules.keys()):
        if key.startswith("api.tasks") or key == "api.config":
            del sys.modules[key]

    from common.settings import get_settings

    get_settings.cache_clear()


# ==============================================================================
# ping return value
# ==============================================================================


def test_ping_returns_pong_with_task_id_and_worker() -> None:
    """ping.apply() in eager mode must return {pong, worker, task_id}."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=True):
        import api.tasks.celery_app as capp  # noqa: PLC0415
        import api.tasks.debug_tasks  # noqa: PLC0415, F401

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = True

        from api.tasks.debug_tasks import ping  # noqa: PLC0415

        result = ping.apply(kwargs={"correlation_id": "test-cid"})
        rv = result.get()

    assert rv["pong"] is True
    assert "task_id" in rv
    assert "worker" in rv


def test_ping_delay_accepts_correlation_id_kwarg() -> None:
    """Regression: ``ping.delay(correlation_id=...)`` must not raise TypeError.

    The route enqueues via ``ping.delay(correlation_id=cid)``. Celery runs
    ``check_arguments`` inside ``apply_async`` at enqueue time — BEFORE the base
    ``__call__`` can consume the kwarg — so ``ping`` must declare
    ``correlation_id`` in its signature. ``.apply()`` (used by the other tests)
    bypasses that check, which is exactly why the original bug slipped through to
    the live worker pass. This test uses ``.delay()`` to exercise the real
    enqueue path.
    """
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=True):
        import api.tasks.celery_app as capp  # noqa: PLC0415
        import api.tasks.debug_tasks  # noqa: PLC0415, F401

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = True

        from api.tasks.debug_tasks import ping  # noqa: PLC0415

        # Would raise TypeError at enqueue if correlation_id were not declared.
        result = ping.delay(correlation_id="cid-xyz")
        rv = result.get()

    assert rv["pong"] is True


# ==============================================================================
# Correlation propagation — verified via the common.logging ContextVar
# ==============================================================================


def test_ping_propagates_supplied_correlation_id() -> None:
    """The _correlation_id ContextVar must carry the passed value during task execution."""
    _reset_modules()

    captured: list[str | None] = []

    with patch.dict("os.environ", _TEST_ENV, clear=True):
        import api.tasks.celery_app as capp  # noqa: PLC0415

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = True

        # Patch the task body to capture what the ContextVar holds at execution time.
        from common.logging import _correlation_id  # noqa: PLC2701, PLC0415

        @capp.celery_app.task(
            bind=True,
            name="test.correlation.capture",
            base=capp._CorrelationTask,  # type: ignore[attr-defined]
        )
        def _capture_task(self: Any) -> dict[str, object]:
            captured.append(_correlation_id.get())
            return {"captured": True}

        _capture_task.apply(kwargs={"correlation_id": "abc123"})

    assert len(captured) == 1, "Task body must have run once"
    assert captured[0] == "abc123", (
        f"Expected _correlation_id ContextVar to be 'abc123' during task, got {captured[0]!r}"
    )


def test_ping_generates_non_empty_correlation_id_when_none_passed() -> None:
    """When no correlation_id is passed, the task must bind a non-empty one."""
    _reset_modules()

    captured: list[str | None] = []

    with patch.dict("os.environ", _TEST_ENV, clear=True):
        import api.tasks.celery_app as capp  # noqa: PLC0415

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = True

        from common.logging import _correlation_id  # noqa: PLC2701, PLC0415

        @capp.celery_app.task(
            bind=True,
            name="test.correlation.capture.noid",
            base=capp._CorrelationTask,  # type: ignore[attr-defined]
        )
        def _capture_noid(self: Any) -> dict[str, object]:
            captured.append(_correlation_id.get())
            return {"captured": True}

        # Call without a correlation_id — base class should generate one.
        _capture_noid.apply(kwargs={})

    assert len(captured) == 1
    assert captured[0], (
        "Expected a non-empty correlation_id in the ContextVar even when none was supplied."
    )


# ==============================================================================
# Structured log fields — verified by attaching caplog to the task logger
# ==============================================================================


def test_ping_logs_task_and_event_fields(caplog: logging.LogCaptureFixture) -> None:
    """The ping task must log a record with 'task' and 'event' extras (allowlist items).

    We attach the caplog handler to the specific logger used by debug_tasks so
    that propagate=False (set by get_logger) does not hide the records.
    """
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=True):
        import api.tasks.celery_app as capp  # noqa: PLC0415
        import api.tasks.debug_tasks  # noqa: PLC0415, F401

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = True

        from api.tasks.debug_tasks import ping  # noqa: PLC0415

        # Add caplog's handler to the task's logger so records are captured.
        task_logger = logging.getLogger("api.tasks.debug_tasks")
        task_logger.addHandler(caplog.handler)
        task_logger.setLevel(logging.INFO)

        try:
            with caplog.at_level(logging.INFO, logger="api.tasks.debug_tasks"):
                ping.apply(kwargs={"correlation_id": "struct-test"})
        finally:
            task_logger.removeHandler(caplog.handler)

    from common.logging import JsonFormatter  # noqa: PLC0415

    fmt = JsonFormatter()
    found_task = False
    found_event = False
    for record in caplog.records:
        formatted = fmt.format(record)
        try:
            payload = json.loads(formatted)
            if "task" in payload:
                found_task = True
            if "event" in payload:
                found_event = True
        except (json.JSONDecodeError, AttributeError):
            pass

    assert found_task, "Expected 'task' field in task log (it is in _ALLOWED_EXTRA)."
    assert found_event, "Expected 'event' field in task log (it is in _ALLOWED_EXTRA)."
