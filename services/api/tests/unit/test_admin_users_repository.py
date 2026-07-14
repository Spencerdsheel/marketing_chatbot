"""Unit tests for api.admin.users_repository (S12.2) -- list/invite/deactivate
a tenant's CLIENT_AGENTs.

Uses a recording Database double (mirrors test_admin_repository.py's
_RecordingDB) so we can assert the bound SQL/params, plus a seed-backed stub
for set_user_active's SELECT-then-UPDATE flow.
"""
from __future__ import annotations

from typing import Any

import asyncpg
import pytest
from common.auth import AuthClaims, Role
from common.crypto import verify_password
from common.errors import AuthorizationError, ValidationError

from api.admin.users_repository import create_tenant_agent, list_tenant_users, set_user_active

_TENANT_A = "tenant-a-123"
_TENANT_B = "tenant-b-999"

_CLIENT_ADMIN = AuthClaims(subject="ca-1", role=Role.CLIENT_ADMIN, tenant_id=_TENANT_A)
_OTHER_CLIENT_ADMIN = AuthClaims(subject="ca-2", role=Role.CLIENT_ADMIN, tenant_id=_TENANT_B)
_CLIENT_AGENT = AuthClaims(subject="cg-1", role=Role.CLIENT_AGENT, tenant_id=_TENANT_A)
_VISITOR = AuthClaims(subject="v-1", role=Role.VISITOR, tenant_id=_TENANT_A)
_PLATFORM_ADMIN = AuthClaims(subject="pa-1", role=Role.PLATFORM_ADMIN, tenant_id=None)


class _Call:
    def __init__(self, kind: str, query: str, params: tuple[Any, ...]) -> None:
        self.kind = kind
        self.query = query
        self.params = params


class _RecordingDB:
    """Recording Database double (mirrors test_admin_repository.py's)."""

    def __init__(self) -> None:
        self.calls: list[_Call] = []
        self.execute_side_effects: list[Exception | None] = []
        self.fetchrow_returns: list[dict[str, Any] | None] = []
        self.fetch_returns: list[list[dict[str, Any]]] = []
        self._execute_i = 0
        self._fetchrow_i = 0
        self._fetch_i = 0

    async def execute(self, query: str, *args: Any) -> str:
        self.calls.append(_Call("execute", query, args))
        if self._execute_i < len(self.execute_side_effects):
            effect = self.execute_side_effects[self._execute_i]
            self._execute_i += 1
            if effect is not None:
                raise effect
        else:
            self._execute_i += 1
        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append(_Call("fetchrow", query, args))
        if self._fetchrow_i < len(self.fetchrow_returns):
            row = self.fetchrow_returns[self._fetchrow_i]
            self._fetchrow_i += 1
            return row
        self._fetchrow_i += 1
        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.calls.append(_Call("fetch", query, args))
        if self._fetch_i < len(self.fetch_returns):
            rows = self.fetch_returns[self._fetch_i]
            self._fetch_i += 1
            return rows
        self._fetch_i += 1
        return []


def _unique_violation() -> asyncpg.UniqueViolationError:
    return asyncpg.UniqueViolationError()


def _user_row(
    *,
    user_id: str = "user-1",
    tenant_id: str = _TENANT_A,
    email: str = "agent@acme.test",
    role: str = "CLIENT_AGENT",
    name: str | None = "Agent Smith",
    active: bool = True,
) -> dict[str, Any]:
    return {
        "id": user_id,
        "tenant_id": tenant_id,
        "email": email,
        "role": role,
        "name": name,
        "active": active,
        "last_login_at": None,
        "created_at": None,
    }


# -- list_tenant_users -------------------------------------------------------


async def test_list_tenant_users_binds_tenant_id_and_excludes_password_hash() -> None:
    db = _RecordingDB()
    db.fetch_returns = [[_user_row()]]

    rows = await list_tenant_users(db, _CLIENT_ADMIN)

    assert len(rows) == 1
    assert "password_hash" not in rows[0]
    assert "password_hash" not in db.calls[0].query.lower().replace("_", "")
    assert _TENANT_A in db.calls[0].params
    assert "WHERE tenant_id = $1" in db.calls[0].query


@pytest.mark.parametrize("claims", [_CLIENT_AGENT, _VISITOR])
async def test_list_tenant_users_rejects_non_client_admin(claims: AuthClaims) -> None:
    db = _RecordingDB()

    with pytest.raises(AuthorizationError) as exc_info:
        await list_tenant_users(db, claims)

    assert exc_info.value.code == "ROLE_NOT_PERMITTED"
    assert db.calls == []


async def test_list_tenant_users_rejects_global_caller() -> None:
    db = _RecordingDB()

    with pytest.raises(ValidationError) as exc_info:
        await list_tenant_users(db, _PLATFORM_ADMIN)

    assert exc_info.value.code == "GLOBAL_CALLER_NOT_PERMITTED"
    assert db.calls == []


# -- create_tenant_agent ------------------------------------------------------


async def test_create_tenant_agent_hardcodes_role_client_agent() -> None:
    db = _RecordingDB()

    result = await create_tenant_agent(
        db, _CLIENT_ADMIN, email="new-agent@acme.test", name="New Agent"
    )

    assert len(db.calls) == 1
    assert "INSERT INTO users" in db.calls[0].query
    params = db.calls[0].params
    assert "CLIENT_AGENT" in params
    assert _TENANT_A in params
    assert result["role"] == "CLIENT_AGENT"
    assert result["tenant_id"] == _TENANT_A


async def test_create_tenant_agent_generates_and_binds_hashed_temp_password() -> None:
    db = _RecordingDB()

    result = await create_tenant_agent(db, _CLIENT_ADMIN, email="a@acme.test", name=None)

    raw_password = result["temp_password"]
    assert raw_password
    params = db.calls[0].params
    bound_hash = next(
        p for p in params if isinstance(p, str) and p.startswith("pbkdf2_sha256$")
    )
    assert verify_password(raw_password, bound_hash)
    assert raw_password not in params


async def test_create_tenant_agent_email_collision() -> None:
    db = _RecordingDB()
    db.execute_side_effects = [_unique_violation()]

    with pytest.raises(ValidationError) as exc_info:
        await create_tenant_agent(db, _CLIENT_ADMIN, email="dup@acme.test", name=None)

    assert exc_info.value.code == "ADMIN_EMAIL_TAKEN"


@pytest.mark.parametrize("claims", [_CLIENT_AGENT, _VISITOR])
async def test_create_tenant_agent_rejects_non_client_admin(claims: AuthClaims) -> None:
    db = _RecordingDB()

    with pytest.raises(AuthorizationError) as exc_info:
        await create_tenant_agent(db, claims, email="x@acme.test", name=None)

    assert exc_info.value.code == "ROLE_NOT_PERMITTED"
    assert db.calls == []


async def test_create_tenant_agent_rejects_global_caller() -> None:
    db = _RecordingDB()

    with pytest.raises(ValidationError) as exc_info:
        await create_tenant_agent(db, _PLATFORM_ADMIN, email="x@acme.test", name=None)

    assert exc_info.value.code == "GLOBAL_CALLER_NOT_PERMITTED"
    assert db.calls == []


# -- set_user_active -----------------------------------------------------------


async def test_set_user_active_missing_returns_none() -> None:
    db = _RecordingDB()
    db.fetchrow_returns = [None]

    result = await set_user_active(db, _CLIENT_ADMIN, "does-not-exist", active=False)

    assert result is None


async def test_set_user_active_cross_tenant_returns_none() -> None:
    db = _RecordingDB()
    # SELECT with tenant filter returns nothing for a cross-tenant id.
    db.fetchrow_returns = [None]

    result = await set_user_active(db, _CLIENT_ADMIN, "user-in-tenant-b", active=False)

    assert result is None
    select_params = db.calls[0].params
    assert _TENANT_A in select_params


async def test_set_user_active_self_targeting_raises_invalid_target() -> None:
    db = _RecordingDB()
    db.fetchrow_returns = [_user_row(user_id=_CLIENT_ADMIN.subject, role="CLIENT_ADMIN")]

    with pytest.raises(ValidationError) as exc_info:
        await set_user_active(db, _CLIENT_ADMIN, _CLIENT_ADMIN.subject, active=False)

    assert exc_info.value.code == "INVALID_TARGET_USER"
    # Only the SELECT ran -- no UPDATE.
    assert len(db.calls) == 1


async def test_set_user_active_targeting_client_admin_raises_invalid_target() -> None:
    db = _RecordingDB()
    db.fetchrow_returns = [_user_row(user_id="other-admin", role="CLIENT_ADMIN")]

    with pytest.raises(ValidationError) as exc_info:
        await set_user_active(db, _CLIENT_ADMIN, "other-admin", active=False)

    assert exc_info.value.code == "INVALID_TARGET_USER"
    assert len(db.calls) == 1


async def test_set_user_active_targeting_platform_admin_raises_invalid_target() -> None:
    db = _RecordingDB()
    db.fetchrow_returns = [_user_row(user_id="platform-admin-1", role="PLATFORM_ADMIN")]

    with pytest.raises(ValidationError) as exc_info:
        await set_user_active(db, _CLIENT_ADMIN, "platform-admin-1", active=False)

    assert exc_info.value.code == "INVALID_TARGET_USER"


async def test_set_user_active_legit_target_succeeds() -> None:
    db = _RecordingDB()
    db.fetchrow_returns = [
        _user_row(user_id="agent-1", role="CLIENT_AGENT", active=True),
        _user_row(user_id="agent-1", role="CLIENT_AGENT", active=False),
    ]

    result = await set_user_active(db, _CLIENT_ADMIN, "agent-1", active=False)

    assert result is not None
    assert result["active"] is False
    assert len(db.calls) == 2
    assert "UPDATE users" in db.calls[1].query
    update_params = db.calls[1].params
    assert False in update_params
    assert "agent-1" in update_params
    assert _TENANT_A in update_params


@pytest.mark.parametrize("claims", [_CLIENT_AGENT, _VISITOR])
async def test_set_user_active_rejects_non_client_admin(claims: AuthClaims) -> None:
    db = _RecordingDB()

    with pytest.raises(AuthorizationError) as exc_info:
        await set_user_active(db, claims, "agent-1", active=False)

    assert exc_info.value.code == "ROLE_NOT_PERMITTED"
    assert db.calls == []


async def test_set_user_active_rejects_global_caller() -> None:
    db = _RecordingDB()

    with pytest.raises(ValidationError) as exc_info:
        await set_user_active(db, _PLATFORM_ADMIN, "agent-1", active=False)

    assert exc_info.value.code == "GLOBAL_CALLER_NOT_PERMITTED"
    assert db.calls == []
