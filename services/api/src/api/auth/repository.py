"""Auth repository -- pre-auth identity resolution.

``get_user_by_email`` is intentionally UNSCOPED (no ``tenant_id`` filter).
At login time there are no AuthClaims yet; the query resolves identity by
email so the caller can verify the password and build claims from the
resulting row. This is the one legitimate pre-auth database query.
"""
from __future__ import annotations

from typing import Any

from common.db import Database

Row = dict[str, Any]


async def get_user_by_email(db: Database, email: str) -> Row | None:
    """Look up a user by email (case-insensitive). Returns the full row or None.

    UNSCOPED by design -- this is the pre-auth identity-resolution query.
    The caller uses the row's ``tenant_id`` and ``role`` to build AuthClaims;
    ``tenant_id`` is never accepted from user input.
    """
    sql = (
        "SELECT id, tenant_id, email, role, password_hash, name, "
        "active, last_login_at "
        "FROM users WHERE lower(email) = lower($1)"
    )
    record = await db.fetchrow(sql, email)
    return dict(record) if record is not None else None


async def set_password_hash(db: Database, user_id: str, new_hash: str) -> None:
    """Update a user's password hash. Parameterized; no tenant filter needed
    (the caller already validated the reset token for this user_id).
    """
    await db.execute(
        "UPDATE users SET password_hash = $1 WHERE id = $2",
        new_hash,
        user_id,
    )
