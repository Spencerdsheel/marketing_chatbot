"""Migration 0032: backfill plaintext tenants.client_key_hash values left
over from 0030 (confirmed live, S12.1 follow-up fix).

Raw SQL migration in spirit (no ORM models / no autogenerate), but this is a
genuine **data** backfill rather than DDL, so unlike 0029/0030/0031 it
cannot be expressed as a single ``op.execute(...)`` string -- it needs a
Python-side hash computed per row via ``op.get_bind()``.

Bug this fixes
---------------
0030 renamed ``tenants.client_key`` to ``client_key_hash`` (+ rebuilt the
unique index) but never backfilled/rehashed the *existing* plaintext values
already in that column for tenants that existed before 0030 ran. Confirmed
live via psql: the ``isngs`` tenant's ``client_key_hash`` was still the raw
``pk_...`` key (35 chars) after 0030, while tenants created after 0030 (via
``create_tenant_with_admin``/``rotate_client_key``, e.g. ``demo``/``acme``)
correctly got a 64-hex-char SHA-256 digest from
``api.admin.repository._hash_client_key``.

``api.gateway.repository.get_tenant_by_client_key`` (S12.1) hashes the
incoming raw key and looks up ``WHERE client_key_hash = $1``. For any
pre-0030 tenant the stored value is still plaintext, so the hashed lookup
can never match -- widget admission (``POST /widget/session``) was
permanently broken for every tenant that existed before 0030 ran.

Detection + idempotency
------------------------
A SHA-256 hex digest is always exactly 64 lowercase hex characters, which a
generated ``pk_...`` client key never is (it's a URL-safe base64 token
prefixed with ``pk_``). ``api.admin.repository._is_client_key_hash`` (unit
tested in ``test_admin_repository.py``) implements this check and is reused
here so the "already hashed?" logic has one source of truth. Rows that
already look like a valid digest are left untouched, so re-running this
migration is a no-op the second time (nothing gets double-hashed) -- see
``test_migration_0032_client_key_backfill.py``.

pgcrypto was considered (to hash in-SQL) but is not used anywhere else in
this codebase's migrations and may not be enabled in every dev environment,
so this backfill uses a dependency-free Python loop (``hashlib``, stdlib)
via ``op.get_bind()`` instead.

``downgrade()`` is a one-way-data-change no-op: SHA-256 is not reversible,
so there is no way to recover the original plaintext keys. This mirrors
0030's own documented downgrade stance (schema-only / cannot restore data).
"""
from __future__ import annotations

import hashlib

from alembic import op
from sqlalchemy import text

from api.admin.repository import _is_client_key_hash

revision = "0032"
down_revision = "0031"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    bind = op.get_bind()
    rows = bind.execute(text("SELECT id, client_key_hash FROM tenants")).fetchall()

    for tenant_id, current_value in rows:
        if current_value is None or _is_client_key_hash(current_value):
            continue
        rehashed = hashlib.sha256(current_value.encode()).hexdigest()
        bind.execute(
            text("UPDATE tenants SET client_key_hash = :hash WHERE id = :id"),
            {"hash": rehashed, "id": tenant_id},
        )


def downgrade() -> None:
    # One-way data backfill -- SHA-256 is not reversible, so there is no
    # way to recover the original plaintext client keys. Schema-only /
    # documented no-op, matching 0030's own downgrade() precedent.
    pass
