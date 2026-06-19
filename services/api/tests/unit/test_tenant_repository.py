"""Unit tests for TenantRepository — mandatory multi-tenant isolation tests.

Uses a recording Database double that captures SQL and params so we can
assert the tenant filter fragment is present/absent and correctly bound.
"""
from __future__ import annotations

from typing import Any

import pytest
from common.auth import AuthClaims, Role
from common.errors import AuthorizationError

from api.tenants.repository import TenantRepository

# -- Recording Database double -------------------------------------------------


class _RecordingDB:
    """Recording Database double that captures the last SQL + params and returns canned rows."""

    def __init__(self, *, rows: list[dict[str, Any]] | None = None) -> None:
        self.last_sql: str = ""
        self.last_params: tuple[Any, ...] = ()
        self._rows = rows or []

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.last_sql = query
        self.last_params = args
        return self._rows[0] if self._rows else None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.last_sql = query
        self.last_params = args
        return list(self._rows)


# -- Fixtures ------------------------------------------------------------------

_TENANT_A_ID = "aaaaaaaa"
_TENANT_B_ID = "bbbbbbbb"

_PLATFORM_ADMIN = AuthClaims(
    subject="admin-global", role=Role.PLATFORM_ADMIN, tenant_id=None
)
_CLIENT_ADMIN_A = AuthClaims(
    subject="admin-a", role=Role.CLIENT_ADMIN, tenant_id=_TENANT_A_ID
)
_CLIENT_AGENT_A = AuthClaims(
    subject="agent-a", role=Role.CLIENT_AGENT, tenant_id=_TENANT_A_ID
)


# -- get() isolation -----------------------------------------------------------


async def test_get_client_admin_includes_tenant_filter() -> None:
    """CLIENT_ADMIN get() must include 'id = $N' with the tenant id bound."""
    db = _RecordingDB(rows=[{"id": _TENANT_A_ID, "name": "A", "slug": "a"}])
    repo = TenantRepository(db)  # type: ignore[arg-type]
    await repo.get(_CLIENT_ADMIN_A, _TENANT_A_ID)

    assert "id = $2" in db.last_sql
    assert _TENANT_A_ID in db.last_params


async def test_get_platform_admin_no_tenant_filter() -> None:
    """PLATFORM_ADMIN get() must NOT include a tenant filter fragment."""
    db = _RecordingDB(rows=[{"id": _TENANT_A_ID, "name": "A", "slug": "a"}])
    repo = TenantRepository(db)  # type: ignore[arg-type]
    await repo.get(_PLATFORM_ADMIN, _TENANT_A_ID)

    # The only param should be the id being looked up — no tenant filter
    assert "id = $2" not in db.last_sql
    assert db.last_params == (_TENANT_A_ID,)


# -- list() isolation ----------------------------------------------------------


async def test_list_client_admin_includes_tenant_filter() -> None:
    """CLIENT_ADMIN list() must scope to their tenant via 'id = $N'."""
    db = _RecordingDB(rows=[])
    repo = TenantRepository(db)  # type: ignore[arg-type]
    await repo.list(_CLIENT_ADMIN_A)

    assert "id = $1" in db.last_sql
    assert _TENANT_A_ID in db.last_params


async def test_list_platform_admin_no_tenant_filter() -> None:
    """PLATFORM_ADMIN list() must NOT filter by tenant — sees all."""
    db = _RecordingDB(rows=[])
    repo = TenantRepository(db)  # type: ignore[arg-type]
    await repo.list(_PLATFORM_ADMIN)

    assert "id = $" not in db.last_sql
    assert db.last_params == ()


# -- create() RBAC -------------------------------------------------------------


async def test_create_requires_platform_admin() -> None:
    """Only PLATFORM_ADMIN may create tenants; others get AuthorizationError."""
    db = _RecordingDB()
    repo = TenantRepository(db)  # type: ignore[arg-type]

    with pytest.raises(AuthorizationError) as exc_info:
        await repo.create(_CLIENT_ADMIN_A, {"name": "X", "slug": "x"})

    assert exc_info.value.code == "ROLE_NOT_PERMITTED"


async def test_create_client_agent_rejected() -> None:
    """CLIENT_AGENT also cannot create tenants."""
    db = _RecordingDB()
    repo = TenantRepository(db)  # type: ignore[arg-type]

    with pytest.raises(AuthorizationError) as exc_info:
        await repo.create(_CLIENT_AGENT_A, {"name": "Y", "slug": "y"})

    assert exc_info.value.code == "ROLE_NOT_PERMITTED"


async def test_create_platform_admin_succeeds() -> None:
    """PLATFORM_ADMIN create() generates an id and INSERTs."""
    row = {"id": "generated", "name": "New", "slug": "new", "enabled": True}
    db = _RecordingDB(rows=[row])
    repo = TenantRepository(db)  # type: ignore[arg-type]

    result = await repo.create(_PLATFORM_ADMIN, {"name": "New", "slug": "new"})

    assert result["name"] == "New"
    assert "INSERT INTO tenants" in db.last_sql
