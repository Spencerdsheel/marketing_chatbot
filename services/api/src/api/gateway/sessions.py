"""Visitor session helpers for the widget admission flow.

``origin_allowed`` validates the request Origin against the tenant's allowlist.
``mint_visitor_session`` creates a short-lived VISITOR JWT carrying a fresh
anonymous ``visitor_id``.
"""
from __future__ import annotations

import datetime as _dt
from uuid import uuid4

from common.auth import AuthClaims, Role

from api.auth.tokens import create_access_token


def origin_allowed(origin: str | None, allowed: list[str]) -> bool:
    """Exact-match check: Origin must be present and in the allowlist."""
    return bool(origin) and origin in allowed


def mint_visitor_session(
    tenant_id: str,
    *,
    secret: str,
    ttl_seconds: int,
) -> tuple[str, str]:
    """Create a short-lived VISITOR JWT.

    Returns ``(token, expires_at_iso)``.
    """
    claims = AuthClaims(
        subject=uuid4().hex,
        role=Role.VISITOR,
        tenant_id=tenant_id,
    )
    token, _ = create_access_token(claims, secret=secret, ttl_seconds=ttl_seconds)
    expires_at = (
        _dt.datetime.now(_dt.UTC) + _dt.timedelta(seconds=ttl_seconds)
    ).isoformat()
    return token, expires_at
