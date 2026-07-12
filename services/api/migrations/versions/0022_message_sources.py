"""Migration 0022: add messages.sources jsonb (S10.1).

Raw SQL migration (no ORM models / no autogenerate).

The orchestrator's grounded answer cites retrieved chunks; this column
persists that citation list alongside the assistant turn so idempotent
replay (S10.1 decision 3.3/7) can return identical sources and the audit
trail can show what was cited. Additive, nullable, low-risk -- mirrors
``conversations.metadata jsonb`` (migration 0007).
"""
from __future__ import annotations

from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN sources jsonb")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN sources")
