"""Migration 0008: repoint messages PK to (tenant_id, conversation_id, message_id).

Raw SQL migration (no ORM models / no autogenerate).

Fixes a tenant-isolation bug: ``message_id`` was a GLOBAL primary key, so
``ON CONFLICT (message_id) DO NOTHING`` in ``append_message`` could silently
no-op an insert in one conversation/tenant because the same ``message_id``
already existed in a completely different conversation/tenant. Scoping the
PK to the composite key makes idempotency conversation-scoped, as intended.
"""
from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE messages DROP CONSTRAINT messages_pkey")
    op.execute(
        "ALTER TABLE messages ADD PRIMARY KEY (tenant_id, conversation_id, message_id)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP CONSTRAINT messages_pkey")
    op.execute("ALTER TABLE messages ADD PRIMARY KEY (message_id)")
