"""Unit tests for HTTP request Prometheus metrics.

Verifies that after driving requests through the app, the default registry
contains the expected metric families with low-cardinality labels (method,
route template, status).  Does NOT reload the metrics module (duplicate-
registration trap).
"""
from __future__ import annotations

from typing import Any
from unittest.mock import patch

from common.auth import AuthClaims, Role
from httpx import ASGITransport, AsyncClient
from prometheus_client import REGISTRY, generate_latest

from api.auth.tokens import create_access_token

# -- Constants -----------------------------------------------------------------

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-abc-123"

# -- Test doubles --------------------------------------------------------------


class _StubDatabase:
    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        return None

    async def fetch(self, query: str, *args: object) -> list[dict[str, Any]]:
        return []

    async def execute(self, query: str, *args: object) -> str:
        return "INSERT 1"

    async def close(self) -> None:
        pass


class _StubRedis:
    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        pass

    async def getdel(self, key: str) -> str | None:
        return None

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


# -- Helpers -------------------------------------------------------------------

_TEST_SETTINGS_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": _TEST_JWT_SECRET,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
    "SENTRY_DSN": "",
    "ENVIRONMENT": "test",
}


def _build_app() -> Any:
    """Create app with test doubles."""
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app

        app = create_app()

    app.state.db = _StubDatabase()
    app.state.redis = _StubRedis()
    app.state.cache = None
    app.state.rate_limiter = None
    return app


def _mint_cookie(
    *,
    subject: str = "user-1",
    role: Role = Role.CLIENT_ADMIN,
    tenant_id: str | None = _TENANT_ID,
    ttl_seconds: int = 300,
    secret: str = _TEST_JWT_SECRET,
) -> str:
    claims = AuthClaims(subject=subject, role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=secret, ttl_seconds=ttl_seconds)
    return token


# -- Tests ---------------------------------------------------------------------


async def test_healthz_request_records_http_metrics() -> None:
    """GET /healthz → http_requests_total{method="GET",route="/healthz",status="200"}
    and http_request_duration_seconds observed."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/healthz")
    assert resp.status_code == 200

    output = generate_latest(REGISTRY).decode("utf-8")
    assert 'http_requests_total{method="GET",route="/healthz",status="200"}' in output
    assert "http_request_duration_seconds" in output


async def test_404_request_labels_unmatched_route() -> None:
    """GET /nonexistent → route="__unmatched__" in the metric."""
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.get("/nonexistent-path-xyz")
    assert resp.status_code == 404

    output = generate_latest(REGISTRY).decode("utf-8")
    assert 'route="__unmatched__"' in output


async def test_metrics_route_label_is_template_not_raw_id() -> None:
    """The route label is the low-cardinality TEMPLATE, never a concrete id.

    Drives a request to a parameterized route (``/admin/leads/{lead_id}``) with
    a distinctive concrete id, then asserts that id NEVER appears in the metric
    output (that would be a high-cardinality / PII-ish label) while the route
    TEMPLATE does. Scoped to this request's own effect — it does NOT scan the
    shared global ``REGISTRY`` for substrings (which false-positives on
    legitimate templates like ``/admin/tenants/{tenant_id}`` once other tests
    have recorded them).
    """
    app = _build_app()
    token = _mint_cookie()
    secret_id = "raw-id-must-not-appear-98765"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        await c.get(f"/admin/leads/{secret_id}", cookies={"access_token": token})

    output = generate_latest(REGISTRY).decode("utf-8")
    # The concrete id must never leak into a label.
    assert secret_id not in output
    # The parameterized route template is what gets labeled.
    assert 'route="/admin/leads/{lead_id}"' in output
