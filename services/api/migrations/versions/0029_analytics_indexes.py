"""Migration 0029: analytics-supporting indexes (S11.2).

Raw SQL migration (no ORM models / no autogenerate) -- same style as
0012/0013/0018/0024/0028.

S11.2's conversation-analytics aggregates (``api/analytics/repository.py``)
scan ``messages``/``conversations`` by ``(tenant_id, <time column>)``. The
existing ``ix_messages_window`` (``tenant_id, conversation_id, created_at``)
and ``ix_conversations_tenant`` (``tenant_id, visitor_id``) indexes don't
serve a bare ``tenant_id + time-range`` scan well. This migration adds two
additive, non-unique indexes -- no new columns, no hot-path change:

- ``idx_messages_tenant_created`` on ``messages (tenant_id, created_at)``.
- ``idx_conversations_tenant_started`` on ``conversations (tenant_id, started_at)``.

``schedule_events`` already has ``(tenant_id, starts_at)`` (migration 0018)
and is low-volume; no new index is added there.
"""
from __future__ import annotations

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "CREATE INDEX idx_messages_tenant_created "
        "ON messages (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX idx_conversations_tenant_started "
        "ON conversations (tenant_id, started_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_conversations_tenant_started")
    op.execute("DROP INDEX IF EXISTS idx_messages_tenant_created")
