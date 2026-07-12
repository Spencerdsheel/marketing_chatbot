"""Migration 0025: add messages.guardrail_flag (S10.3).

Raw SQL migration (no ORM models / no autogenerate).

Tags every assistant turn with the violated output-guardrail rule name
(``empty_output``/``instruction_leak``/``human_impersonation``/
``context_sentinel_leak``), or ``NULL`` on a clean turn -- the substrate the
S11.2 "guardrail blocks" analytics metric will consume. Nullable, no CHECK
(kept flexible for future rule names; the app writes only the four rule
literals or ``NULL``). Additive + nullable + low-risk, mirroring 0024.
"""
from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE messages ADD COLUMN guardrail_flag text")


def downgrade() -> None:
    op.execute("ALTER TABLE messages DROP COLUMN guardrail_flag")
