"""Migration 0009: add running-summary columns to conversations.

Raw SQL migration (no ORM models / no autogenerate).

Adds the count-watermarked running summary (decision D8 / S4.3):
``summary`` holds the rolled-up text for everything older than the kept
recent tail; ``summary_message_count`` records how many of the oldest
(chronological) messages are already folded into ``summary``.
"""
from __future__ import annotations

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE conversations ADD COLUMN summary text")
    op.execute(
        "ALTER TABLE conversations "
        "ADD COLUMN summary_message_count integer NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN summary_message_count")
    op.execute("ALTER TABLE conversations DROP COLUMN summary")
