"""CRM config route -- POST /admin/crm/config (CLIENT_ADMIN only).

Config changes are a tenant admin decision -- CLIENT_AGENT (reviews leads,
cannot change config, per CLAUDE.md RBAC) and VISITOR are rejected. The
response echoes ``connector``/``webhook_url``/``enabled`` but NEVER the
secret (mirrors ``api.llm.routes.set_llm_config``).
"""
from __future__ import annotations

from common.auth import AuthClaims, Role
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from api.auth.dependencies import require_roles
from api.crm.config_repository import upsert_crm_config

_log = get_logger(__name__)

router = APIRouter(prefix="/admin/crm", tags=["crm"])


class CRMConfigRequest(BaseModel):
    """Body for POST /admin/crm/config."""

    connector: str
    webhook_url: str | None = None
    secret: str
    enabled: bool = False


class CRMConfigResponse(BaseModel):
    """Leak-free (no secret) response for POST /admin/crm/config."""

    connector: str
    webhook_url: str | None
    enabled: bool


@router.post("/config")
async def set_crm_config(
    body: CRMConfigRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> CRMConfigResponse:
    """Set the calling tenant's CRM connector + webhook URL + signing secret.

    The secret is encrypted at rest (AES-256-GCM via ``SecretBox``) and never
    echoed back in the response.
    """
    await upsert_crm_config(
        request.app.state.db,
        claims,
        connector=body.connector,
        webhook_url=body.webhook_url,
        secret=body.secret,
        enabled=body.enabled,
    )

    _log.info(
        "CRM config updated",
        extra={
            "event": "crm_config_set",
            "connector": body.connector,
            "tenant_id": claims.tenant_id,
            "enabled": body.enabled,
        },
    )

    return CRMConfigResponse(
        connector=body.connector,
        webhook_url=body.webhook_url,
        enabled=body.enabled,
    )
