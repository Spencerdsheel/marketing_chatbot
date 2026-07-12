"""Migration 0023: create tenant_orchestrator_configs (S10.2).

Raw SQL migration (no ORM models / no autogenerate).

Per-tenant orchestrator policy thresholds -- the answer/clarify/escalate
3-way decision (S10.2 decision 2/3) compares retrieval confidence against
two tenant-tunable thresholds. Owned by ``api/orchestrator/config_repository
.py`` -- a distinct table from ``tenant_llm_configs`` (CLAUDE.md §4 "keep
module seams strict": thresholds are orchestration policy, not LLM-provider
config). Unconfigured tenants read settings defaults via a get-or-default
repository function -- this table only holds explicit overrides.
"""
from __future__ import annotations

from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels: tuple[str, ...] = ()
depends_on: tuple[str, ...] = ()


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE tenant_orchestrator_configs (
            tenant_id           text PRIMARY KEY REFERENCES tenants(id) ON DELETE CASCADE,
            answer_threshold    double precision NOT NULL,
            escalate_threshold  double precision NOT NULL,
            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_orchestrator_thresholds
                CHECK (escalate_threshold >= 0.0 AND answer_threshold <= 1.0
                       AND escalate_threshold <= answer_threshold)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE tenant_orchestrator_configs")
