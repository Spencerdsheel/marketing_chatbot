"""Migration 0024: add messages.decision + messages.grounded (S10.2).

Raw SQL migration (no ORM models / no autogenerate).

Tags every assistant turn with the 3-way decision (``answer``/``clarify``/
``escalate``) and whether the reply was grounded in retrieved context --
the substrate D9/D10 analytics (S11.2) will consume. Nullable, no CHECK on
``decision`` (kept flexible for future decision values; the app writes only
the three literals). Additive + nullable + low-risk, mirroring 0022.
"""
from __future__ import annotations

from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN decision text")
    op.execute("ALTER TABLE messages ADD COLUMN grounded boolean")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN decision")
    op.execute("ALTER TABLE messages DROP COLUMN grounded")
