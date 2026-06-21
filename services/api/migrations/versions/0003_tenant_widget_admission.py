"""Add client_key + allowed_origins to tenants for widget admission.

Raw SQL migration (no ORM models / no autogenerate).
"""
from __future__ import annotations

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenants ADD COLUMN client_key text"
    )
    op.execute(
        "ALTER TABLE tenants ADD COLUMN allowed_origins text[] "
        "NOT NULL DEFAULT '{}'"
    )
    op.execute(
        "CREATE UNIQUE INDEX ix_tenants_client_key ON tenants (client_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tenants_client_key")
    op.execute("ALTER TABLE tenants DROP COLUMN allowed_origins")
    op.execute("ALTER TABLE tenants DROP COLUMN client_key")
