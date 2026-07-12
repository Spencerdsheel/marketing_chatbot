"""Unit tests for api.scheduling.tasks (scheduling.dispatch_due_reminders + scheduling.send_reminder).

Covers:
- dispatch_due_reminders claims due jobs and .delay()s one send_reminder per
  claimed row (mock claim_due_reminders + send_reminder.delay).
- send_reminder on a queued job -> dispatch + flip to sent.
- A job not in queued -> no-op, no dispatch (redelivery guard).
- Event missing/not-booked -> skipped, no dispatch.
- Deterministic sink error -> failed + last_error, NOT raised (no retry).
- Transient sink error -> raises (Celery retry).
- Tenant re-scoping: the task builds AuthClaims from the claimed row's tenant_id.
- correlation_id declared on both task signatures (S5.1 regression guard).
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from common.errors import ValidationError

from api.notifications.recipients import NoRecipientError

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

_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)
_TENANT_ID = "tenant-reminder-tasks-test"
_JOB_ID = "job-reminder-tasks-test"
_EVENT_ID = "event-reminder-tasks-test"


def _reset_modules() -> None:
    for key in list(sys.modules.keys()):
        if key.startswith("api.scheduling") or key.startswith("api.tasks"):
            del sys.modules[key]
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


class _StubDatabase:
    async def close(self) -> None:
        pass


def _make_reminder_job(**overrides: Any) -> Any:
    from api.scheduling.reminder_repository import ReminderJob

    fields: dict[str, Any] = {
        "job_id": _JOB_ID,
        "event_id": _EVENT_ID,
        "offset": "1h",
        "run_at": _NOW,
        "status": "queued",
        "attempts": 1,
        "last_error": None,
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    fields.update(overrides)
    return ReminderJob(**fields)


def _make_claimed_reminder(**overrides: Any) -> Any:
    from api.scheduling.reminder_repository import ClaimedReminder

    fields: dict[str, Any] = {
        "job_id": _JOB_ID,
        "tenant_id": _TENANT_ID,
        "event_id": _EVENT_ID,
        "offset": "1h",
    }
    fields.update(overrides)
    return ClaimedReminder(**fields)


# ==============================================================================
# dispatch_due_reminders -- claims + delays one send per claimed row
# ==============================================================================


async def test_dispatch_claims_due_jobs_and_delays_one_send_per_row() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        claimed = [
            _make_claimed_reminder(job_id="job-1", offset="3d"),
            _make_claimed_reminder(job_id="job-2", offset="1h"),
        ]

        with (
            patch("api.scheduling.tasks.claim_due_reminders", AsyncMock(return_value=claimed)),
            patch("api.scheduling.tasks.send_reminder") as mock_send_reminder,
        ):
            from api.scheduling.tasks import _execute_dispatch  # noqa: PLC0415

            result = await _execute_dispatch(_StubDatabase(), batch_size=100)  # type: ignore[arg-type]

    assert result == {"claimed": 2}
    assert mock_send_reminder.delay.call_count == 2
    mock_send_reminder.delay.assert_any_call(
        job_id="job-1", tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="3d"
    )
    mock_send_reminder.delay.assert_any_call(
        job_id="job-2", tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h"
    )


async def test_dispatch_no_claimed_jobs_delays_nothing() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        with (
            patch("api.scheduling.tasks.claim_due_reminders", AsyncMock(return_value=[])),
            patch("api.scheduling.tasks.send_reminder") as mock_send_reminder,
        ):
            from api.scheduling.tasks import _execute_dispatch  # noqa: PLC0415

            result = await _execute_dispatch(_StubDatabase(), batch_size=100)  # type: ignore[arg-type]

    assert result == {"claimed": 0}
    mock_send_reminder.delay.assert_not_called()


# ==============================================================================
# send_reminder -- queued job -> dispatch + flip to sent
# ==============================================================================


async def test_send_reminder_queued_job_dispatches_and_marks_sent() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="queued")
        stub_sink = AsyncMock()
        stub_sink.dispatch = AsyncMock()

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=("booked", _NOW))),
            patch("api.scheduling.tasks.reminder_sink_for", return_value=stub_sink),
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()) as mock_mark,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            result = await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="log",
            )

    assert result == {"job_id": _JOB_ID, "status": "sent"}
    stub_sink.dispatch.assert_awaited_once()
    mock_mark.assert_awaited_once()
    _, kwargs = mock_mark.call_args
    assert kwargs["status"] == "sent"


# ==============================================================================
# send_reminder -- not queued -> no-op, no dispatch (redelivery guard)
# ==============================================================================


async def test_send_reminder_non_queued_job_is_no_op_no_dispatch() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="sent")

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks.reminder_sink_for") as mock_sink_selector,
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()) as mock_mark,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            result = await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="log",
            )

    assert result == {"job_id": _JOB_ID, "status": "no_op"}
    mock_sink_selector.assert_not_called()
    mock_mark.assert_not_called()


async def test_send_reminder_missing_job_is_no_op() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=None)),
            patch("api.scheduling.tasks.reminder_sink_for") as mock_sink_selector,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            result = await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="log",
            )

    assert result == {"job_id": _JOB_ID, "status": "no_op"}
    mock_sink_selector.assert_not_called()


# ==============================================================================
# send_reminder -- event missing/not-booked -> skipped, no dispatch
# ==============================================================================


async def test_send_reminder_missing_event_marks_skipped_no_dispatch() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="queued")

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=None)),
            patch("api.scheduling.tasks.reminder_sink_for") as mock_sink_selector,
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()) as mock_mark,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            result = await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="log",
            )

    assert result == {"job_id": _JOB_ID, "status": "skipped"}
    mock_sink_selector.assert_not_called()
    mock_mark.assert_awaited_once()
    _, kwargs = mock_mark.call_args
    assert kwargs["status"] == "skipped"


async def test_send_reminder_cancelled_event_marks_skipped_no_dispatch() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="queued")

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=("cancelled", _NOW))),
            patch("api.scheduling.tasks.reminder_sink_for") as mock_sink_selector,
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()) as mock_mark,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            result = await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="log",
            )

    assert result == {"job_id": _JOB_ID, "status": "skipped"}
    mock_sink_selector.assert_not_called()
    mock_mark.assert_awaited_once()


# ==============================================================================
# send_reminder -- deterministic vs transient sink errors
# ==============================================================================


async def test_send_reminder_deterministic_sink_error_marks_failed_not_raised() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="queued")
        stub_sink = AsyncMock()
        stub_sink.dispatch = AsyncMock(
            side_effect=ValidationError("bad config", code="REMINDER_SINK_CONFIG_ERROR")
        )

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=("booked", _NOW))),
            patch("api.scheduling.tasks.reminder_sink_for", return_value=stub_sink),
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()) as mock_mark,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            result = await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="log",
            )

    assert result == {"job_id": _JOB_ID, "status": "failed"}
    mock_mark.assert_awaited_once()
    _, kwargs = mock_mark.call_args
    assert kwargs["status"] == "failed"
    assert kwargs["last_error"] is not None


async def test_send_reminder_transient_sink_error_raises_for_celery_retry() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="queued")
        stub_sink = AsyncMock()
        stub_sink.dispatch = AsyncMock(side_effect=RuntimeError("broker unavailable"))

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=("booked", _NOW))),
            patch("api.scheduling.tasks.reminder_sink_for", return_value=stub_sink),
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()) as mock_mark,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            with pytest.raises(RuntimeError, match="broker unavailable"):
                await _execute_send(
                    _StubDatabase(),  # type: ignore[arg-type]
                    job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                    sink_name="log",
                )

    mock_mark.assert_not_called()


# ==============================================================================
# send_reminder -- NoRecipientError -> skipped/NO_RECIPIENT, NOT failed, NOT raised (S9.2)
# ==============================================================================


async def test_send_reminder_no_recipient_error_marks_skipped_not_failed_not_raised() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="queued")
        stub_sink = AsyncMock()
        stub_sink.dispatch = AsyncMock(side_effect=NoRecipientError("no contact"))

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=("booked", _NOW))),
            patch("api.scheduling.tasks.reminder_sink_for", return_value=stub_sink),
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()) as mock_mark,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            result = await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="notification",
            )

    assert result == {"job_id": _JOB_ID, "status": "skipped"}
    mock_mark.assert_awaited_once()
    _, kwargs = mock_mark.call_args
    assert kwargs["status"] == "skipped"
    assert kwargs["last_error"] == "NO_RECIPIENT"


async def test_execute_send_passes_db_to_reminder_sink_for() -> None:
    """reminder_sink_for is called with db= (S9.2 Scope §5)."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="queued")
        stub_sink = AsyncMock()
        stub_sink.dispatch = AsyncMock()
        stub_db = _StubDatabase()

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=("booked", _NOW))),
            patch("api.scheduling.tasks.reminder_sink_for", return_value=stub_sink) as mock_selector,
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()),
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            await _execute_send(
                stub_db,  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="notification",
            )

    mock_selector.assert_called_once_with("notification", db=stub_db)


# ==============================================================================
# The "log" path is unchanged (regression, S9.2 decision 6)
# ==============================================================================


async def test_send_reminder_log_path_unchanged_regression() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        job = _make_reminder_job(status="queued")

        with (
            patch("api.scheduling.tasks.get_reminder_job", AsyncMock(return_value=job)),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=("booked", _NOW))),
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()) as mock_mark,
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            result = await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="log",
            )

    assert result == {"job_id": _JOB_ID, "status": "sent"}
    mock_mark.assert_awaited_once()
    _, kwargs = mock_mark.call_args
    assert kwargs["status"] == "sent"


# ==============================================================================
# Tenant re-scoping -- claims built from the claimed row's tenant_id
# ==============================================================================


async def test_send_reminder_builds_tenant_scoped_claims_from_row() -> None:
    _reset_modules()

    captured_claims: list[Any] = []

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        async def _capturing_get_reminder_job(db_: Any, claims_: Any, job_id_: str) -> Any:
            captured_claims.append(claims_)
            return _make_reminder_job(status="queued")

        with (
            patch("api.scheduling.tasks.get_reminder_job", side_effect=_capturing_get_reminder_job),
            patch("api.scheduling.tasks._get_event", AsyncMock(return_value=("booked", _NOW))),
            patch("api.scheduling.tasks.reminder_sink_for", return_value=AsyncMock()),
            patch("api.scheduling.tasks.mark_reminder", AsyncMock()),
        ):
            from api.scheduling.tasks import _execute_send  # noqa: PLC0415

            await _execute_send(
                _StubDatabase(),  # type: ignore[arg-type]
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                sink_name="log",
            )

    assert captured_claims
    from common.auth import AuthClaims as _AC  # noqa: PLC0415
    from common.auth import Role as _R  # noqa: PLC0415

    c = captured_claims[0]
    assert isinstance(c, _AC)
    assert c.tenant_id == _TENANT_ID
    assert c.role == _R.CLIENT_ADMIN


# ==============================================================================
# correlation_id declared on both task signatures (S5.1 regression guard)
# ==============================================================================


def test_dispatch_due_reminders_delay_accepts_correlation_id() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        import api.scheduling.tasks  # noqa: PLC0415, F401
        import api.tasks.celery_app as capp  # noqa: PLC0415

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = False

        from api.scheduling.tasks import dispatch_due_reminders  # noqa: PLC0415

        with patch("api.scheduling.tasks.asyncio.new_event_loop") as mock_loop:
            mock_event_loop = mock_loop.return_value
            mock_event_loop.run_until_complete.return_value = {"claimed": 0}
            mock_event_loop.close.return_value = None

            result = dispatch_due_reminders.delay(correlation_id="cid-dispatch-test")
            assert result is not None


def test_send_reminder_delay_accepts_correlation_id() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        import api.scheduling.tasks  # noqa: PLC0415, F401
        import api.tasks.celery_app as capp  # noqa: PLC0415

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = False

        from api.scheduling.tasks import send_reminder  # noqa: PLC0415

        with patch("api.scheduling.tasks.asyncio.new_event_loop") as mock_loop:
            mock_event_loop = mock_loop.return_value
            mock_event_loop.run_until_complete.return_value = {
                "job_id": _JOB_ID, "status": "sent"
            }
            mock_event_loop.close.return_value = None

            result = send_reminder.delay(
                job_id=_JOB_ID, tenant_id=_TENANT_ID, event_id=_EVENT_ID, offset="1h",
                correlation_id="cid-send-test",
            )
            assert result is not None
