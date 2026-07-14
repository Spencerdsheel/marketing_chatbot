"""Tenant user-management repository (S12.2) -- list/invite/deactivate a
tenant's ``CLIENT_AGENT``s.

Unlike ``api.admin.repository`` (S12.1, deliberately global -- there is no
tenant yet at onboarding time), every function here is strictly own-tenant
-scoped (decision 2): ``tenant_id`` is always bound from ``claims.tenant_id``,
never accepted from the request. A ``PLATFORM_ADMIN``/global caller is
rejected with ``ValidationError GLOBAL_CALLER_NOT_PERMITTED`` (mirrors
``api.orchestrator.config_repository._reject_global``); any other
non-``CLIENT_ADMIN`` role is rejected with ``AuthorizationError
ROLE_NOT_PERMITTED`` via ``common.tenancy.require_role`` (defense in depth --
the route layer already gates on ``Role.CLIENT_ADMIN``).

``create_tenant_agent`` hardcodes ``role='CLIENT_AGENT'`` in the bound INSERT
param -- there is no ``role`` field on the request body to even attempt
overriding (decision 1). ``set_user_active`` enforces the "manage agents, not
peers" symmetry (decisions 3-4): the target must be a same-tenant
``CLIENT_AGENT`` and must not be the caller themselves, else ``ValidationError
INVALID_TARGET_USER``; a missing/cross-tenant target returns ``None`` (route
maps to 404), never leaking which case it was.
"""
from __future__ import annotations

import secrets
from typing import Any
from uuid import uuid4

import asyncpg
from common.auth import AuthClaims, Role
from common.crypto import hash_password
from common.db import Database
from common.errors import ValidationError
from common.tenancy import require_role

_GENERATED_PASSWORD_BYTES = 16


def _require_tenant_scoped_client_admin(claims: AuthClaims) -> None:
    """Reject a global (PLATFORM_ADMIN) caller, then require Role.CLIENT_ADMIN.

    PLATFORM_ADMIN callers always have ``tenant_id is None`` (see
    ``common.auth.AuthClaims.__post_init__``), so the global check always
    catches them first with the decision-2-mandated
    ``GLOBAL_CALLER_NOT_PERMITTED`` code. Any other non-CLIENT_ADMIN role
    (CLIENT_AGENT, VISITOR) is rejected by ``require_role``.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "User management is tenant-scoped; PLATFORM_ADMIN callers are "
            "not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )
    require_role(claims, Role.CLIENT_ADMIN)


async def list_tenant_users(db: Database, claims: AuthClaims) -> list[dict[str, Any]]:
    """List the caller's tenant's users, newest first. Never includes ``password_hash``."""
    _require_tenant_scoped_client_admin(claims)

    rows = await db.fetch(
        "SELECT id, tenant_id, email, role, name, active, last_login_at, created_at "
        "FROM users WHERE tenant_id = $1 ORDER BY created_at DESC",
        claims.tenant_id,
    )
    return [dict(row) for row in rows]


async def create_tenant_agent(
    db: Database,
    claims: AuthClaims,
    *,
    email: str,
    name: str | None,
) -> dict[str, Any]:
    """Create a new ``CLIENT_AGENT`` in the caller's tenant.

    ``role='CLIENT_AGENT'`` is hardcoded -- there is no request-body ``role``
    field to even attempt to override (decision 1). Generates and hashes a
    fresh temp password (``secrets.token_urlsafe``, mirrors S12.1's generated-
    password pattern); the raw value is returned exactly once, never
    persisted anywhere but its hash. A duplicate email (case-insensitive,
    ``users_email_lower_uniq``) raises ``ValidationError ADMIN_EMAIL_TAKEN``.
    """
    _require_tenant_scoped_client_admin(claims)

    raw_password = secrets.token_urlsafe(_GENERATED_PASSWORD_BYTES)
    password_hash = hash_password(raw_password)

    user_id = uuid4().hex
    try:
        await db.execute(
            "INSERT INTO users (id, tenant_id, email, role, password_hash, name) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            user_id,
            claims.tenant_id,
            email,
            Role.CLIENT_AGENT.value,
            password_hash,
            name,
        )
    except asyncpg.UniqueViolationError as exc:
        raise ValidationError(
            "A user with this email already exists.",
            code="ADMIN_EMAIL_TAKEN",
        ) from exc

    return {
        "user_id": user_id,
        "tenant_id": claims.tenant_id,
        "email": email,
        "role": Role.CLIENT_AGENT.value,
        "name": name,
        "active": True,
        "temp_password": raw_password,
    }


async def set_user_active(
    db: Database,
    claims: AuthClaims,
    user_id: str,
    *,
    active: bool,
) -> dict[str, Any] | None:
    """Set ``users.active`` for a same-tenant ``CLIENT_AGENT`` target.

    Returns ``None`` for a missing or cross-tenant ``user_id`` (route maps to
    404 ``USER_NOT_FOUND`` -- indistinguishable from "doesn't exist",
    decision 2). Raises ``ValidationError INVALID_TARGET_USER`` when the
    target is the caller themselves (decision 4) or is not a ``CLIENT_AGENT``
    in the caller's tenant (decision 3) -- the row exists and is visible via
    ``list_tenant_users``, it is just not a legal PATCH target.
    """
    _require_tenant_scoped_client_admin(claims)

    row = await db.fetchrow(
        "SELECT id, tenant_id, email, role, name, active, last_login_at, created_at "
        "FROM users WHERE id = $1 AND tenant_id = $2",
        user_id,
        claims.tenant_id,
    )
    if row is None:
        return None

    if user_id == claims.subject or row["role"] != Role.CLIENT_AGENT.value:
        raise ValidationError(
            "This user is not a legal target for activation/deactivation.",
            code="INVALID_TARGET_USER",
        )

    updated = await db.fetchrow(
        "UPDATE users SET active = $1, updated_at = now() "
        "WHERE id = $2 AND tenant_id = $3 "
        "RETURNING id, tenant_id, email, role, name, active, last_login_at, created_at",
        active,
        user_id,
        claims.tenant_id,
    )
    return dict(updated) if updated is not None else None
