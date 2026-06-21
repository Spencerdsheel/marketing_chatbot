"""Gateway repository -- pre-auth tenant resolution by client key.

``get_tenant_by_client_key`` is intentionally UNSCOPED (no ``tenant_id`` filter).
At widget-admission time there are no AuthClaims yet; the client key IS the tenant
selector, and it is public + Origin-guarded. This is the second legitimate
pre-auth database query (alongside ``auth.repository.get_user_by_email``).
"""
from __future__ import annotations

from typing import Any

from common.db import Database

Row = dict[str, Any]


async def get_tenant_by_client_key(db: Database, client_key: str) -> Row | None:
    """Look up a tenant by its public client key.

    UNSCOPED by design -- this is the pre-auth tenant-resolution query.
    The client key is public; abuse protection comes from the Origin allowlist.
    """
    sql = (
        "SELECT id, slug, enabled, allowed_origins "
        "FROM tenants WHERE client_key = $1"
    )
    record = await db.fetchrow(sql, client_key)
    return dict(record) if record is not None else None
