"""Migration 0031: tenant_bot_settings (S12.2 decision 5) -- qualitative bot
config, additive to the EXISTING tenant_orchestrator_configs (thresholds/
turn_cap) and tenant_llm_configs (provider/model) tables.

One row per tenant, upserted by ``api.admin.settings_repository
.upsert_bot_settings``. A tenant with no row yet is a genuinely absent/empty
qualitative config (not a fabricated default) -- see
``get_bot_settings``.

Raw SQL migration (no ORM models / no autogenerate), same style as 0029/0030.
"""
from __future__ import annotations

from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_bot_settings (
            tenant_id         text PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
            greeting          text,
            business_hours    jsonb,
            escalation_policy text,
            tone              text,
            created_at        timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_bot_settings")
