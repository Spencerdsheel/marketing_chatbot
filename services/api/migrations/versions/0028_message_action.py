"""Migration 0028: add messages.action (S10.4).

Raw SQL migration (no ORM models / no autogenerate) -- same style as 0025.

Tags every assistant turn with the CTA signal it emitted --
``"schedule_cta"``/``"lead_form"``/``NULL`` -- so idempotent replay (S10.4
decision 6) can return ``action`` as a stored fact instead of re-deriving it
from ``decision`` (ambiguous now that ``escalate`` can map to either
``schedule_cta`` or ``lead_form`` depending on tenant availability). Nullable,
no CHECK -- kept flexible for future action values; the app writes only the
two literals above or ``NULL``. Additive + nullable + low-risk, mirroring
0025.
"""
from __future__ import annotations

from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN action text")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN action")
