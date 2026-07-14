"""Gateway repository -- pre-auth tenant resolution by client key.

``get_tenant_by_client_key`` is intentionally UNSCOPED (no ``tenant_id`` filter).
At widget-admission time there are no AuthClaims yet; the client key IS the tenant
selector, and it is public + Origin-guarded. This is the second legitimate
pre-auth database query (alongside ``auth.repository.get_user_by_email``).

Since S12.1 (migration 0030), ``tenants.client_key`` is stored as a SHA-256
hash (``client_key_hash``), not plaintext -- the incoming raw key is hashed
with ``api.admin.repository._hash_client_key`` (imported here, not
duplicated -- ``admin/`` is the module that *creates* keys, ``gateway/``
only *validates* them) before the lookup. Same signature, same return shape,
same ``None``-on-miss behavior; only the WHERE clause + the hash step
changed.
"""
from __future__ import annotations

from typing import Any

from common.db import Database

from api.admin.repository import _hash_client_key

Row = dict[str, Any]


async def get_tenant_by_client_key(db: Database, client_key: str) -> Row | None:
    """Look up a tenant by its public client key (hashed lookup, S12.1).

    UNSCOPED by design -- this is the pre-auth tenant-resolution query.
    The client key is public; abuse protection comes from the Origin allowlist.
    Hashing here is corruption/leak hygiene, not a secrecy requirement.
    """
    sql = (
        "SELECT id, slug, enabled, allowed_origins "
        "FROM tenants WHERE client_key_hash = $1"
    )
    record = await db.fetchrow(sql, _hash_client_key(client_key))
    return dict(record) if record is not None else None
