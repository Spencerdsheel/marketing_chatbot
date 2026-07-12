"""Per-tenant orchestrator config repository -- the 3-way decision thresholds.

Mirrors ``api.scheduling.calendar_config_repository`` / ``api.llm
.config_repository``'s tenant-scoping conventions, but the thresholds are
plain floats (no secret material, nothing to encrypt). Owned by the
orchestrator module (CLAUDE.md §4 "keep module seams strict") -- a distinct
table from ``tenant_llm_configs``, since thresholds are orchestration policy,
not LLM-provider config.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.auth import AuthClaims
from common.db import Database
from common.errors import ValidationError

from api.config import get_api_settings


@dataclass(frozen=True)
class OrchestratorConfig:
    """A tenant's 3-way decision thresholds."""

    answer_threshold: float
    escalate_threshold: float


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN).

    Orchestrator config is always tenant-scoped; a global caller has no
    tenant_id and therefore cannot be filtered to a tenant's row.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "Orchestrator config repository is tenant-scoped; PLATFORM_ADMIN "
            "callers are not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )


async def get_orchestrator_config(db: Database, claims: AuthClaims) -> OrchestratorConfig:
    """Fetch the caller's tenant orchestrator config, or settings defaults.

    Never returns ``None`` -- an unconfigured tenant is deterministic via
    ``settings.orchestrator_default_answer_threshold`` /
    ``orchestrator_default_escalate_threshold``. Raises ``ValidationError``
    for global callers.
    """
    _reject_global(claims)

    row = await db.fetchrow(
        "SELECT answer_threshold, escalate_threshold "
        "FROM tenant_orchestrator_configs WHERE tenant_id = $1",
        claims.tenant_id,
    )
    if row is None:
        settings = get_api_settings()
        return OrchestratorConfig(
            answer_threshold=settings.orchestrator_default_answer_threshold,
            escalate_threshold=settings.orchestrator_default_escalate_threshold,
        )

    return OrchestratorConfig(
        answer_threshold=float(row["answer_threshold"]),
        escalate_threshold=float(row["escalate_threshold"]),
    )


async def upsert_orchestrator_config(
    db: Database,
    claims: AuthClaims,
    *,
    answer_threshold: float,
    escalate_threshold: float,
) -> None:
    """Insert or update the caller's tenant orchestrator config.

    Raises ``ValidationError`` for global callers, and ``ValidationError``
    (``INVALID_ORCHESTRATOR_THRESHOLDS``) if
    ``0 <= escalate_threshold <= answer_threshold <= 1`` does not hold
    (defense-in-depth over the DB CHECK constraint).
    """
    _reject_global(claims)

    if not (0.0 <= escalate_threshold <= answer_threshold <= 1.0):
        raise ValidationError(
            "Thresholds must satisfy 0 <= escalate_threshold <= "
            "answer_threshold <= 1.",
            code="INVALID_ORCHESTRATOR_THRESHOLDS",
        )

    await db.execute(
        "INSERT INTO tenant_orchestrator_configs "
        "(tenant_id, answer_threshold, escalate_threshold) "
        "VALUES ($1, $2, $3) "
        "ON CONFLICT (tenant_id) DO UPDATE SET "
        "answer_threshold = $2, escalate_threshold = $3, updated_at = now()",
        claims.tenant_id,
        answer_threshold,
        escalate_threshold,
    )
