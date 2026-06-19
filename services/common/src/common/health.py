"""Health, readiness, and Prometheus helpers shared by every process.

- ``liveness`` — ``/healthz``: process is up; checks NO dependencies.
- ``readiness`` — ``/readyz``: runs dependency checks (DB, Redis, ...). A failing or
  raising check marks the service not-ready (never fail silently).
- ``metrics_payload`` — render a Prometheus registry for ``/metrics``.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import TYPE_CHECKING, Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    generate_latest,
)

if TYPE_CHECKING:
    from common.db import Database

ReadinessCheck = Callable[[], Awaitable[bool]]


def liveness() -> dict[str, str]:
    """Liveness probe payload. No dependency checks."""
    return {"status": "ok"}


async def readiness(
    checks: Mapping[str, ReadinessCheck],
) -> tuple[bool, dict[str, str]]:
    """Run each named check; return (all_ready, {name: "ok"|"fail"})."""
    detail: dict[str, str] = {}
    ready = True
    for name, check in checks.items():
        try:
            ok = await check()
        except Exception:
            ok = False
        detail[name] = "ok" if ok else "fail"
        ready = ready and ok
    return ready, detail


async def check_database(db: Database) -> bool:
    """Readiness check: the database answers ``SELECT 1``."""
    try:
        return bool(await db.fetchval("SELECT 1") == 1)
    except Exception:
        return False


async def check_redis(client: Any) -> bool:
    """Readiness check: Redis answers ``PING``."""
    try:
        return bool(await client.ping())
    except Exception:
        return False


def metrics_payload(
    registry: CollectorRegistry = REGISTRY,
) -> tuple[bytes, str]:
    """Return ``(body, content_type)`` for a Prometheus ``/metrics`` response."""
    return generate_latest(registry), CONTENT_TYPE_LATEST
