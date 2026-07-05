"""Unit tests for /debug/tasks routes.

Covers:
- POST /debug/tasks/ping: CLIENT_ADMIN + mocked ping.delay → 200 {task_id, status:"queued"};
  delay called with the request's correlation_id.
- GET /debug/tasks/{task_id}: mocked AsyncResult for SUCCESS → state + result;
  PENDING → state="PENDING", result=null; FAILURE → state="FAILURE", result=null.
- RBAC: CLIENT_AGENT → 403; no cookie → 401.
"""
from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock, patch

from common.auth import AuthClaims, Role
from common.cache import InMemoryCache
from httpx import ASGITransport, AsyncClient

# -- Constants -----------------------------------------------------------------

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-route-test"

_TEST_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": _TEST_JWT_SECRET,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}

# -- Test doubles --------------------------------------------------------------


class _StubDatabase:
    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        return None

    async def execute(self, query: str, *args: object) -> str:
        return "OK"

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

    def pipeline(self, transaction: bool = False) -> _StubPipeline:
        return _StubPipeline()


class _StubPipeline:
    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        pass

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        pass

    def zcard(self, key: str) -> None:
        pass

    def expire(self, key: str, seconds: int) -> None:
        pass

    async def execute(self) -> list[Any]:
        return [0, None, 0, True]

    async def zrange(self, key: str, start: int, end: int, withscores: bool = False) -> list[Any]:
        return []


# -- Helpers -------------------------------------------------------------------


def _reset_modules() -> None:
    for key in list(sys.modules.keys()):
        if key.startswith("api.tasks") or key == "api.config":
            del sys.modules[key]
    from common.settings import get_settings

    get_settings.cache_clear()


def _build_app() -> Any:
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.app import create_app

        app = create_app()

    app.state.db = _StubDatabase()
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    app.state.rate_limiter = None
    return app


def _mint_cookie(
    *,
    role: Role = Role.CLIENT_ADMIN,
    tenant_id: str | None = _TENANT_ID,
    secret: str = _TEST_JWT_SECRET,
) -> str:
    from api.auth.tokens import create_access_token

    claims = AuthClaims(subject="user-1", role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=secret, ttl_seconds=300)
    return token


# ==============================================================================
# POST /debug/tasks/ping
# ==============================================================================


async def test_post_ping_client_admin_returns_queued() -> None:
    """CLIENT_ADMIN → 200 {task_id, status:"queued"}, delay called once."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()
        token = _mint_cookie(role=Role.CLIENT_ADMIN)

        mock_async_result = MagicMock()
        mock_async_result.id = "mock-task-uuid-001"

        with patch("api.tasks.debug_tasks.ping.delay", return_value=mock_async_result) as mock_delay:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/debug/tasks/ping",
                    cookies={"access_token": token},
                    headers={"x-correlation-id": "req-cid-001"},
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "mock-task-uuid-001"
    assert body["status"] == "queued"
    mock_delay.assert_called_once()


async def test_post_ping_passes_correlation_id_to_delay() -> None:
    """delay must be called with the request's correlation_id as a kwarg."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()
        token = _mint_cookie(role=Role.CLIENT_ADMIN)

        mock_async_result = MagicMock()
        mock_async_result.id = "mock-task-uuid-002"

        with patch("api.tasks.debug_tasks.ping.delay", return_value=mock_async_result) as mock_delay:
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/debug/tasks/ping",
                    cookies={"access_token": token},
                    headers={"x-correlation-id": "propagated-cid"},
                )

    assert resp.status_code == 200
    # The delay must have been called with correlation_id matching the request header.
    call_kwargs = mock_delay.call_args.kwargs
    assert call_kwargs.get("correlation_id") == "propagated-cid", (
        f"Expected correlation_id='propagated-cid' in delay kwargs, got {call_kwargs!r}"
    )


async def test_post_ping_client_agent_returns_403() -> None:
    """CLIENT_AGENT must receive 403 ROLE_NOT_PERMITTED."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()
        token = _mint_cookie(role=Role.CLIENT_AGENT)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/debug/tasks/ping",
                cookies={"access_token": token},
            )

    assert resp.status_code == 403


async def test_post_ping_no_cookie_returns_401() -> None:
    """No authentication cookie must yield 401."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/debug/tasks/ping")

    assert resp.status_code == 401


# ==============================================================================
# GET /debug/tasks/{task_id}
# ==============================================================================


async def test_get_task_success_returns_state_and_result() -> None:
    """AsyncResult in SUCCESS state returns state + result dict."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()
        token = _mint_cookie(role=Role.CLIENT_ADMIN)

        expected_result = {"pong": True, "worker": "worker@host", "task_id": "t-001"}
        mock_result = MagicMock()
        mock_result.state = "SUCCESS"
        mock_result.successful.return_value = True
        mock_result.result = expected_result

        with patch("api.tasks.routes.AsyncResult", return_value=mock_result):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/debug/tasks/t-001",
                    cookies={"access_token": token},
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["task_id"] == "t-001"
    assert body["state"] == "SUCCESS"
    assert body["result"] == expected_result


async def test_get_task_pending_returns_null_result() -> None:
    """AsyncResult in PENDING state returns state='PENDING', result=null."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()
        token = _mint_cookie(role=Role.CLIENT_ADMIN)

        mock_result = MagicMock()
        mock_result.state = "PENDING"
        mock_result.successful.return_value = False
        mock_result.result = None

        with patch("api.tasks.routes.AsyncResult", return_value=mock_result):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/debug/tasks/t-pending",
                    cookies={"access_token": token},
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "PENDING"
    assert body["result"] is None


async def test_get_task_failure_returns_null_result_no_exception_leaked() -> None:
    """AsyncResult in FAILURE state returns state='FAILURE', result=null (no raw exception)."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()
        token = _mint_cookie(role=Role.CLIENT_ADMIN)

        mock_result = MagicMock()
        mock_result.state = "FAILURE"
        mock_result.successful.return_value = False
        mock_result.result = Exception("internal error details")

        with patch("api.tasks.routes.AsyncResult", return_value=mock_result):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    "/debug/tasks/t-fail",
                    cookies={"access_token": token},
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["state"] == "FAILURE"
    assert body["result"] is None, "Raw exceptions must NOT be leaked in the response."


async def test_get_task_client_agent_returns_403() -> None:
    """GET /debug/tasks/{id} with CLIENT_AGENT must yield 403."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()
        token = _mint_cookie(role=Role.CLIENT_AGENT)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/debug/tasks/some-task-id",
                cookies={"access_token": token},
            )

    assert resp.status_code == 403


async def test_get_task_no_cookie_returns_401() -> None:
    """GET /debug/tasks/{id} without a cookie must yield 401."""
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/debug/tasks/some-task-id")

    assert resp.status_code == 401
