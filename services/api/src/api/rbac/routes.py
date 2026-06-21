"""Reference RBAC probe endpoints.

These endpoints establish the **route-level RBAC guard pattern** that every
later admin/agent router (Phase 12 admin-api) will reuse.

**Exact-membership semantics:** a role passes only if it is in the allowed set.
There is no implicit "PLATFORM_ADMIN bypasses every gate" -- global admin is
included explicitly where intended.
"""
from __future__ import annotations

from common.auth import AuthClaims, Role
from fastapi import APIRouter, Depends

from api.auth.dependencies import require_roles

router = APIRouter(prefix="/debug/rbac", tags=["rbac"])


@router.get("/admin")
async def rbac_admin(
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.PLATFORM_ADMIN)),  # noqa: B008
) -> dict[str, str | None]:
    """Admin-tier endpoint: CLIENT_ADMIN or PLATFORM_ADMIN only."""
    return {
        "subject": claims.subject,
        "role": claims.role.value,
        "tenant_id": claims.tenant_id,
    }


@router.get("/platform")
async def rbac_platform(
    claims: AuthClaims = Depends(require_roles(Role.PLATFORM_ADMIN)),  # noqa: B008
) -> dict[str, str | None]:
    """Platform-operator-only endpoint: PLATFORM_ADMIN only."""
    return {
        "subject": claims.subject,
        "role": claims.role.value,
        "tenant_id": claims.tenant_id,
    }
