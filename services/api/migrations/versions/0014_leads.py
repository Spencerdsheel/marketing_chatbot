"""Migration 0014: leads table for visitor lead capture.

Raw SQL migration (no ORM models / no autogenerate).

S7.1 adds the schema required for the lead-capture vertical slice:
- ``leads``: one row per captured lead per tenant. Stores visitor contact info
  (name, email, phone), consent (jsonb), and initial pipeline state (status='new',
  stage='captured', qualification_score/assigned_agent_id NULL). Composite PK
  (tenant_id, lead_id). Indexed on (tenant_id, created_at DESC) for recent-lead
  queries and (tenant_id, email) for deduplication.
"""
from __future__ import annotations

from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE leads (
            tenant_id              text        NOT NULL,
            lead_id                text        NOT NULL,
            visitor_id             text,
            name                   text        NOT NULL,
            email                  text        NOT NULL,
            phone                  text,
            status                 text        NOT NULL DEFAULT 'new',
            stage                  text        NOT NULL DEFAULT 'captured',
            qualification_score    integer,
            consent                jsonb       NOT NULL,
            assigned_agent_id      text,
            source                 text        NOT NULL DEFAULT 'widget',
            created_at             timestamptz NOT NULL DEFAULT now(),
            updated_at             timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, lead_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_leads_tenant_created "
        "ON leads (tenant_id, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX idx_leads_tenant_email "
        "ON leads (tenant_id, email)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS leads")
