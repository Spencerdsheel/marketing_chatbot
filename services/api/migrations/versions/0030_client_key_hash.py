"""Migration 0030: hash tenants.client_key at rest (audit P3-1, S12.1 decision 3).

Raw SQL migration (no ORM models / no autogenerate) -- same style as
0003/0029.

``tenants.client_key`` (migration 0003) was stored and looked up in
plaintext. This migration renames the column to ``client_key_hash`` and
rebuilds the unique index under the new name. From this point forward, only
a SHA-256 hex digest of the raw client key is ever persisted (see
``api.admin.repository._hash_client_key``); the raw key is generated,
returned once, and never stored.

``downgrade()`` restores the *schema* (column + index names), not the
plaintext data -- the hash is not reversible, so a downgrade leaves
``client_key`` populated with hash values, not the original raw keys. This
is a documented, intentional one-way data-shape change (schema-only
downgrade), matching how other renaming/additive migrations in this repo
treat downgrade.
"""
from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE tenants RENAME COLUMN client_key TO client_key_hash")
    op.execute("DROP INDEX IF EXISTS ix_tenants_client_key")
    op.execute(
        "CREATE UNIQUE INDEX ix_tenants_client_key_hash ON tenants (client_key_hash)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenants_client_key_hash")
    op.execute("ALTER TABLE tenants RENAME COLUMN client_key_hash TO client_key")
    op.execute("CREATE UNIQUE INDEX ix_tenants_client_key ON tenants (client_key)")
