"""Create tenant_llm_configs table for per-tenant LLM provider settings.

Raw SQL migration (no ORM models / no autogenerate).
"""
from __future__ import annotations

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        "CREATE TABLE tenant_llm_configs ("
        "    tenant_id           text PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,"
        "    provider            text NOT NULL CHECK (provider IN ('anthropic','openai','azure')),"
        "    model               text NOT NULL,"
        "    api_key_ciphertext  text NOT NULL,"
        "    created_at          timestamptz NOT NULL DEFAULT now(),"
        "    updated_at          timestamptz NOT NULL DEFAULT now()"
        ")"
    )


def downgrade() -> None:
    op.execute("DROP TABLE tenant_llm_configs")
