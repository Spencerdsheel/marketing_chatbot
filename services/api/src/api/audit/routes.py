"""Admin audit routes — read the audit trail.

GET /admin/audit returns a paginated list of audit events for the caller's
tenant.  CLIENT_ADMIN only; CLIENT_AGENT/VISITOR → 403.
"""
from __future__ import annotations

from common.auth import AuthClaims, Role
from common.logging import get_logger
from fastapi import APIRouter, Depends, Query, Request

from api.audit.repository import list_audit
from api.auth.dependencies import require_roles

_log = get_logger(__name__)

router = APIRouter(prefix="/admin/audit", tags=["audit"])


def _iso(dt: object) -> str | None:
    """Return ISO format string for a datetime, or pass through strings."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return str(dt.isoformat())
    return str(dt)


@router.get("")
async def list_audit_events(
    request: Request,
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> list[dict[str, object]]:
    """List audit events for the caller's tenant, newest first.

    ``limit`` is clamped to ``[1, 200]``.
    Response excludes ``tenant_id``.
    """
    db = request.app.state.db

    events = await list_audit(db, claims, limit=limit, offset=offset)

    return [
        {
            "event_id": e.event_id,
            "actor": e.actor,
            "action": e.action,
            "target_type": e.target_type,
            "target_id": e.target_id,
            "metadata": e.metadata,
            "created_at": _iso(e.created_at),
        }
        for e in events
    ]
