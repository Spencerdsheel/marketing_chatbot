"""Debug endpoints for tenants -- now protected by real auth.

Routes resolve the caller's identity from the JWT cookie via
``get_current_claims`` and pass the real ``AuthClaims`` to the repository,
making per-role tenant isolation observable end-to-end.
"""
from __future__ import annotations

from typing import Any

from common.auth import AuthClaims
from fastapi import APIRouter, Depends, Request

from api.auth.dependencies import get_current_claims
from api.tenants.repository import TenantRepository

router = APIRouter(prefix="/debug/tenants", tags=["debug"])


@router.get("")
async def list_tenants(
    request: Request,
    claims: AuthClaims = Depends(get_current_claims),  # noqa: B008
) -> list[dict[str, Any]]:
    repo = TenantRepository(request.app.state.db)
    return await repo.list(claims)


@router.get("/{tenant_id}")
async def get_tenant(
    request: Request,
    tenant_id: str,
    claims: AuthClaims = Depends(get_current_claims),  # noqa: B008
) -> dict[str, Any] | None:
    repo = TenantRepository(request.app.state.db)
    return await repo.get(claims, tenant_id)
