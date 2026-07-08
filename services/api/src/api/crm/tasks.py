"""Celery task: crm.sync_lead.

S7.4 decision 3. Outbound CRM sync is a Celery job so it never blocks the
capture path (decision 4, wired in ``api.leads.routes``). This task:

  1. Builds a tenant-scoped service ``AuthClaims`` (like ingestion,
     ``subject="system:crm"``, ``role=CLIENT_ADMIN``) from the trusted
     ``tenant_id`` kwarg -- never from visitor input.
  2. Loads the tenant's CRM config. No config / ``enabled=false`` -> no-op
     success (nothing to sync, not an error).
  3. Loads the lead. Missing lead -> no-op success (nothing to sync; the
     lead may have been captured before the config was set, or removed).
  4. Selects the connector via ``crm_sync_for``. An unknown connector /
     incomplete config raises a deterministic ``ValidationError`` -- caught
     here and returned as a failure WITHOUT re-raising, so Celery does not
     retry (S5.2 deterministic-vs-transient split).
  5. Calls ``CRMSync.upsert_lead``. A webhook non-2xx / network failure
     raises ``RuntimeError`` -- NOT caught here, so it propagates and Celery
     retries with backoff (transient).
  6. On success, appends a ``crm_sync`` activity (S7.3 ``add_activity``,
     payload ``{connector, external_id, status}``). No silent fabrication of
     success -- the activity is only appended after ``upsert_lead`` returns.

correlation_id (S5.1 rule): MUST be declared in the signature. Celery runs
``check_arguments`` inside ``apply_async`` at enqueue time, before the base
``_CorrelationTask.__call__`` can consume it. Omitting it makes
``.delay(correlation_id=...)`` raise ``TypeError`` at enqueue.

PII discipline: the lead payload (name/email/phone) is sent to the external
webhook by design, but log lines here carry only ``lead_id``/``tenant_id``/
connector metadata -- never contact fields.
"""
from __future__ import annotations

import asyncio

from common.auth import AuthClaims, Role
from common.db import Database
from common.errors import ValidationError
from common.logging import get_logger

from api.crm.config_repository import get_crm_config
from api.crm.sync import crm_sync_for
from api.leads.repository import add_activity, get_lead
from api.tasks.celery_app import _CorrelationTask, celery_app

_log = get_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="crm.sync_lead",
    base=_CorrelationTask,
)
def sync_lead(
    self: _CorrelationTask,
    *,
    tenant_id: str,
    lead_id: str,
    correlation_id: str | None = None,  # noqa: ARG001 — consumed by _CorrelationTask.__call__
) -> dict[str, object]:
    """Sync a single lead to the tenant's configured external CRM, if any.

    Parameters
    ----------
    tenant_id:
        Trusted tenant identifier. Originates from ``claims.tenant_id`` at
        enqueue time -- never from visitor input.
    lead_id:
        The ``leads.lead_id`` to sync.
    correlation_id:
        Must be declared here (see module docstring). Consumed by
        ``_CorrelationTask.__call__`` before this body runs.

    Returns
    -------
    dict
        ``{"lead_id": ..., "status": "succeeded"|"no_op"|"failed"}``.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run(tenant_id, lead_id))
    finally:
        loop.close()


async def _run(tenant_id: str, lead_id: str) -> dict[str, object]:
    """Async inner body: open a DB connection and delegate to ``_execute``."""
    from api.config import get_api_settings  # noqa: PLC0415

    settings = get_api_settings()
    db = await Database.connect(settings.database_url, statement_cache_size=0)
    try:
        return await _execute(db, tenant_id, lead_id)
    finally:
        await db.close()


async def _execute(db: Database, tenant_id: str, lead_id: str) -> dict[str, object]:
    """Core config-load -> connector-select -> sync -> activity logic."""
    claims = AuthClaims(subject="system:crm", role=Role.CLIENT_ADMIN, tenant_id=tenant_id)

    config = await get_crm_config(db, claims)
    if config is None or not config.enabled:
        _log.info(
            "crm_sync_no_op",
            extra={
                "event": "crm_sync_no_op",
                "lead_id": lead_id,
                "tenant_id": tenant_id,
                "reason": "no_config" if config is None else "disabled",
            },
        )
        return {"lead_id": lead_id, "status": "no_op"}

    lead = await get_lead(db, claims, lead_id)
    if lead is None:
        # Nothing to sync (e.g. lead removed between capture and worker run).
        # Not an error -- no-op success, no retry.
        _log.warning(
            "crm_sync_lead_missing",
            extra={"event": "crm_sync_lead_missing", "lead_id": lead_id, "tenant_id": tenant_id},
        )
        return {"lead_id": lead_id, "status": "no_op"}

    try:
        provider = crm_sync_for(config)
    except ValidationError as exc:
        # Deterministic config error (unknown connector / incomplete config)
        # -- do NOT raise, so Celery does not retry.
        _log.warning(
            "crm_sync_config_error",
            extra={
                "event": "crm_sync_config_error",
                "lead_id": lead_id,
                "tenant_id": tenant_id,
                "error_code": exc.code,
            },
        )
        return {"lead_id": lead_id, "status": "failed"}

    # Transient (network/non-2xx) errors from upsert_lead propagate here so
    # Celery retries -- intentionally NOT caught.
    ref = await provider.upsert_lead(claims, lead)

    await add_activity(
        db,
        claims,
        lead_id,
        type="crm_sync",
        payload={"connector": ref.connector, "external_id": ref.external_id, "status": ref.status},
        actor="system:crm",
    )

    _log.info(
        "crm_sync_succeeded",
        extra={
            "event": "crm_sync_succeeded",
            "lead_id": lead_id,
            "tenant_id": tenant_id,
            "connector": ref.connector,
        },
    )
    return {"lead_id": lead_id, "status": "succeeded"}
