"""Add api_version column to tenant_llm_configs for Azure OpenAI.

Raw SQL migration (no ORM models / no autogenerate).
"""
from __future__ import annotations

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_llm_configs ADD COLUMN api_version text")


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_llm_configs DROP COLUMN api_version")
