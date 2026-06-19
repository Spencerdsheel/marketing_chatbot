"""Baseline revision.

This is a no-op revision that establishes the alembic_version table and the
revision chain. Real business tables are introduced in later sprints.

Revision ID: 0001
Revises:
Create Date: 2026-06-19 00:00:00.000000

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """No-op upgrade. The alembic_version table is created by Alembic itself."""
    pass


def downgrade() -> None:
    """No-op downgrade."""
    pass
