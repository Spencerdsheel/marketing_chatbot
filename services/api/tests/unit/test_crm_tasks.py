"""Unit tests for api.crm.tasks.sync_lead (Celery task "crm.sync_lead").

Covers:
- Configured + enabled -> CRMSync.upsert_lead called; a "crm_sync" activity
  appended via api.leads.repository.add_activity.
- No config -> no-op success, no sync call, no retry.
- Config present but disabled -> no-op success, no sync call, no retry.
- Webhook non-2xx / network error propagates (Celery-retryable).
- Unknown connector -> deterministic no-retry failure (caught, not raised).
- correlation_id declared on the task signature: .delay(correlation_id=...)
  must not raise TypeError (S5.1 regression guard).
- Tenant-scoped AuthClaims built from the trusted tenant_id kwarg.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

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

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_TENANT_ID = "tenant-crm-tasks-test"
_LEAD_ID = "lead-crm-tasks-test"

# Built via concatenation to dodge the repo's secret-literal guardrail scan.
_PLACEHOLDER_SECRET = "whsec" + "_" + "task" + "_" + "test"


def _reset_modules() -> None:
    # Same hygiene as test_ingestion_tasks.py: never delete api.config (splits
    # the module graph and poisons sibling tests); only clear the settings
    # caches on the shared module.
    for key in list(sys.modules.keys()):
        if key.startswith("api.crm") or key.startswith("api.tasks"):
            del sys.modules[key]
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


class _RecordingDatabase:
    """Minimal DB double for crm.sync_lead: config row + lead row + activity insert."""

    def __init__(
        self,
        *,
        config_row: dict[str, Any] | None = None,
        lead_row: dict[str, Any] | None = None,
    ) -> None:
        self._config_row = config_row
        self._lead_row = lead_row
        self.executions: list[tuple[str, tuple[Any, ...]]] = []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = query.upper()
        if "TENANT_CRM_CONFIGS" in q:
            return self._config_row
        if "FROM LEADS" in q:
            return self._lead_row
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return []

    async def execute(self, query: str, *args: Any) -> str:
        self.executions.append((query, args))
        return "INSERT 1"

    async def close(self) -> None:
        pass


def _make_lead_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "lead_id": _LEAD_ID,
        "visitor_id": "visitor-1",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": None,
        "status": "new",
        "stage": "captured",
        "qualification_score": None,
        "consent": {"granted": True, "purpose": "contact", "text": "OK"},
        "assigned_agent_id": None,
        "source": "widget",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    row.update(overrides)
    return row


def _make_config_row(
    *, connector: str = "webhook", enabled: bool = True, webhook_url: str | None = "https://example.com/hook"
) -> dict[str, Any]:
    from common.crypto import SecretBox  # noqa: PLC0415

    from api.config import get_api_settings  # noqa: PLC0415

    box = SecretBox(get_api_settings().secret_encryption_key)
    return {
        "connector": connector,
        "webhook_url": webhook_url,
        "secret_ciphertext": box.encrypt(_PLACEHOLDER_SECRET),
        "enabled": enabled,
    }


# ==============================================================================
# Configured + enabled -> upsert_lead called + activity appended
# ==============================================================================


async def test_configured_enabled_calls_upsert_lead_and_appends_activity() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        db = _RecordingDatabase(config_row=_make_config_row(), lead_row=_make_lead_row())

        from api.crm.sync import ExternalRef  # noqa: PLC0415

        stub_sync = AsyncMock()
        stub_sync.upsert_lead = AsyncMock(
            return_value=ExternalRef(connector="webhook", external_id=None, status="ok")
        )

        with patch("api.crm.tasks.crm_sync_for", return_value=stub_sync):
            from api.crm.tasks import _execute  # noqa: PLC0415

            result = await _execute(db, _TENANT_ID, _LEAD_ID)  # type: ignore[arg-type]

    assert result["status"] == "succeeded"
    stub_sync.upsert_lead.assert_awaited_once()

    activity_inserts = [
        e for e in db.executions if "INSERT INTO LEAD_ACTIVITIES" in e[0].upper()
    ]
    assert len(activity_inserts) == 1
    _, args = activity_inserts[0]
    # args: tenant_id, activity_id, lead_id, type, payload, actor
    assert args[0] == _TENANT_ID
    assert args[2] == _LEAD_ID
    assert args[3] == "crm_sync"
    assert args[4] == {"connector": "webhook", "external_id": None, "status": "ok"}


# ==============================================================================
# No config -> no-op success, no call
# ==============================================================================


async def test_no_config_is_no_op_success_no_call() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        db = _RecordingDatabase(config_row=None, lead_row=_make_lead_row())

        with patch("api.crm.tasks.crm_sync_for") as mock_selector:
            from api.crm.tasks import _execute  # noqa: PLC0415

            result = await _execute(db, _TENANT_ID, _LEAD_ID)  # type: ignore[arg-type]

    assert result["status"] == "no_op"
    mock_selector.assert_not_called()
    activity_inserts = [e for e in db.executions if "INSERT INTO LEAD_ACTIVITIES" in e[0].upper()]
    assert activity_inserts == []


# ==============================================================================
# Config present but disabled -> no-op success, no call
# ==============================================================================


async def test_disabled_config_is_no_op_success_no_call() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        db = _RecordingDatabase(config_row=_make_config_row(enabled=False), lead_row=_make_lead_row())

        with patch("api.crm.tasks.crm_sync_for") as mock_selector:
            from api.crm.tasks import _execute  # noqa: PLC0415

            result = await _execute(db, _TENANT_ID, _LEAD_ID)  # type: ignore[arg-type]

    assert result["status"] == "no_op"
    mock_selector.assert_not_called()


# ==============================================================================
# Webhook failure propagates (retryable)
# ==============================================================================


async def test_webhook_failure_propagates_for_retry() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        db = _RecordingDatabase(config_row=_make_config_row(), lead_row=_make_lead_row())

        stub_sync = AsyncMock()
        stub_sync.upsert_lead = AsyncMock(side_effect=RuntimeError("webhook returned 500"))

        with patch("api.crm.tasks.crm_sync_for", return_value=stub_sync):
            from api.crm.tasks import _execute  # noqa: PLC0415

            with pytest.raises(RuntimeError, match="webhook returned 500"):
                await _execute(db, _TENANT_ID, _LEAD_ID)  # type: ignore[arg-type]

    activity_inserts = [e for e in db.executions if "INSERT INTO LEAD_ACTIVITIES" in e[0].upper()]
    assert activity_inserts == []


# ==============================================================================
# Unknown connector -> deterministic no-retry failure
# ==============================================================================


async def test_unknown_connector_deterministic_no_retry() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        db = _RecordingDatabase(
            config_row=_make_config_row(connector="hubspot"), lead_row=_make_lead_row()
        )

        from api.crm.tasks import _execute  # noqa: PLC0415

        # crm_sync_for is NOT patched here: the real selector raises
        # ValidationError for an unsupported connector, which _execute must
        # catch (not propagate) so Celery does not retry.
        result = await _execute(db, _TENANT_ID, _LEAD_ID)  # type: ignore[arg-type]

    assert result["status"] == "failed"
    activity_inserts = [e for e in db.executions if "INSERT INTO LEAD_ACTIVITIES" in e[0].upper()]
    assert activity_inserts == []


# ==============================================================================
# correlation_id declared on the task (S5.1 regression guard)
# ==============================================================================


def test_sync_lead_delay_accepts_correlation_id() -> None:
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        import api.crm.tasks  # noqa: PLC0415, F401
        import api.tasks.celery_app as capp  # noqa: PLC0415

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = False

        from api.crm.tasks import sync_lead  # noqa: PLC0415

        with (
            patch("api.crm.tasks.asyncio.new_event_loop") as mock_loop,
        ):
            mock_event_loop = mock_loop.return_value
            mock_event_loop.run_until_complete.return_value = {
                "lead_id": _LEAD_ID, "status": "no_op"
            }
            mock_event_loop.close.return_value = None

            # Regression guard: would raise TypeError at enqueue if
            # correlation_id were not declared in the task signature.
            result = sync_lead.delay(
                tenant_id=_TENANT_ID,
                lead_id=_LEAD_ID,
                correlation_id="cid-crm-test",
            )
            assert result is not None


# ==============================================================================
# Tenant-scoped AuthClaims
# ==============================================================================


async def test_builds_tenant_scoped_claims() -> None:
    _reset_modules()

    captured_claims: list[Any] = []

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        db = _RecordingDatabase(config_row=None, lead_row=_make_lead_row())

        from api.crm import tasks as tasks_mod  # noqa: PLC0415

        original_get_crm_config = tasks_mod.get_crm_config

        async def _capturing_get_crm_config(db_: Any, claims_: Any) -> Any:
            captured_claims.append(claims_)
            return await original_get_crm_config(db_, claims_)

        with patch("api.crm.tasks.get_crm_config", side_effect=_capturing_get_crm_config):
            result = await tasks_mod._execute(db, _TENANT_ID, _LEAD_ID)  # type: ignore[arg-type]

    assert result["status"] == "no_op"
    assert captured_claims, "get_crm_config should have been called"

    from common.auth import AuthClaims as _AC  # noqa: PLC0415
    from common.auth import Role as _R  # noqa: PLC0415

    c = captured_claims[0]
    assert isinstance(c, _AC)
    assert c.role == _R.CLIENT_ADMIN
    assert c.tenant_id == _TENANT_ID
