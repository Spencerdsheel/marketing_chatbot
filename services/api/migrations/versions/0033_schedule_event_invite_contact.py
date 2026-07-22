"""Migration 0033: invite contact fields for native scheduling (SR-5)."""
from __future__ import annotations

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE schedule_events ADD COLUMN email text")
    op.execute("ALTER TABLE schedule_events ADD COLUMN name text")


def downgrade() -> None:
    op.execute("ALTER TABLE schedule_events DROP COLUMN IF EXISTS name")
    op.execute("ALTER TABLE schedule_events DROP COLUMN IF EXISTS email")
