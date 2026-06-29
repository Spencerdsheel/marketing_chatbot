"""Migration 0007: create tenant-scoped conversations + messages tables.

Raw SQL migration (no ORM models / no autogenerate).
"""
from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "CREATE TABLE conversations ("
        "    conversation_id text PRIMARY KEY,"
        "    tenant_id       text NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,"
        "    visitor_id      text,"
        "    status          text NOT NULL DEFAULT 'active' CHECK (status IN ('active','ended')),"
        "    channel         text NOT NULL DEFAULT 'widget',"
        "    started_at      timestamptz NOT NULL DEFAULT now(),"
        "    ended_at        timestamptz,"
        "    metadata        jsonb NOT NULL DEFAULT '{}'::jsonb"
        ")"
    )
    op.execute(
        "CREATE INDEX ix_conversations_tenant ON conversations (tenant_id, visitor_id)"
    )

    op.execute(
        "CREATE TABLE messages ("
        "    message_id      text PRIMARY KEY,"
        "    tenant_id       text NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,"
        "    conversation_id text NOT NULL "
        "REFERENCES conversations(conversation_id) ON DELETE CASCADE,"
        "    role            text NOT NULL CHECK (role IN ('user','bot','system')),"
        "    content         text NOT NULL,"
        "    intent          text,"
        "    confidence      double precision,"
        "    tokens          integer,"
        "    created_at      timestamptz NOT NULL DEFAULT now()"
        ")"
    )
    op.execute(
        "CREATE INDEX ix_messages_window ON messages (tenant_id, conversation_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE messages")
    op.execute("DROP TABLE conversations")
