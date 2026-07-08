"""Migration 0015: lead_activities table for the CRM activity timeline.

Raw SQL migration (no ORM models / no autogenerate).

S7.3 adds the append-only timeline that records notes, agent assignments,
and pipeline stage changes for a lead:
- ``lead_activities``: one row per timeline event per tenant. Composite PK
  (tenant_id, activity_id). FK (tenant_id, lead_id) -> leads(tenant_id,
  lead_id) ON DELETE CASCADE -- deleting a lead deletes its timeline.
  ``type`` is app-enforced (not a DB CHECK) to stay open for future event
  types. Indexed on (tenant_id, lead_id, created_at DESC) for the timeline
  read path.
"""
from __future__ import annotations

from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE lead_activities (
            tenant_id   text        NOT NULL,
            activity_id text        NOT NULL,
            lead_id     text        NOT NULL,
            type        text        NOT NULL,
            payload     jsonb,
            actor       text,
            created_at  timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, activity_id),
            FOREIGN KEY (tenant_id, lead_id)
                REFERENCES leads (tenant_id, lead_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_lead_activities_tenant_lead_created "
        "ON lead_activities (tenant_id, lead_id, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS lead_activities")
