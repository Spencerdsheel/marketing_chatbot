"""Migration 0027: add tenant_orchestrator_configs.turn_cap (S10.4).

Raw SQL migration (no ORM models / no autogenerate) -- same style as 0025/0026.

Adds a nullable per-tenant ``turn_cap integer`` column to the EXISTING
``tenant_orchestrator_configs`` table (S10.2) -- the turn-count cap is the
same class of orchestration policy as ``answer_threshold``/
``escalate_threshold``, so it belongs on the same row rather than a new
table. A CHECK constraint enforces ``turn_cap IS NULL OR turn_cap >= 1``
(defense-in-depth over ``upsert_orchestrator_config``'s own validation).
Nullable so existing S10.2-era rows keep ``turn_cap = NULL`` and resolve to
``settings.orchestrator_default_turn_cap`` at read time
(``get_orchestrator_config``). Additive + nullable + CHECK-guarded, mirroring
0024/0025's low-risk shape.
"""
from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute("ALTER TABLE tenant_orchestrator_configs ADD COLUMN turn_cap integer")
    op.execute(
        "ALTER TABLE tenant_orchestrator_configs "
        "ADD CONSTRAINT ck_orchestrator_turn_cap CHECK (turn_cap IS NULL OR turn_cap >= 1)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_orchestrator_configs "
        "DROP CONSTRAINT IF EXISTS ck_orchestrator_turn_cap"
    )
    op.execute("ALTER TABLE tenant_orchestrator_configs DROP COLUMN turn_cap")
