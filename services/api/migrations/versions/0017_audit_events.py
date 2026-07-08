"""Migration 0017: create audit_events table for the audit trail.

Raw SQL migration (no ORM models / no autogenerate).
"""
from __future__ import annotations

from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "CREATE TABLE audit_events ("
        "    tenant_id     text NOT NULL,"
        "    event_id      text NOT NULL,"
        "    actor         text,"
        "    action        text NOT NULL,"
        "    target_type   text,"
        "    target_id     text,"
        "    metadata      jsonb,"
        "    created_at    timestamptz NOT NULL DEFAULT now(),"
        "    PRIMARY KEY (tenant_id, event_id)"
        ")"
    )
    op.execute(
        "CREATE INDEX ix_audit_events_tenant_created "
        "ON audit_events (tenant_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE audit_events")
