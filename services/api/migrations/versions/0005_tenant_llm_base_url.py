"""Add base_url column to tenant_llm_configs for OpenAI-compatible endpoints.

Raw SQL migration (no ORM models / no autogenerate).
"""
from __future__ import annotations

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_llm_configs ADD COLUMN base_url text")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_llm_configs DROP COLUMN base_url")
