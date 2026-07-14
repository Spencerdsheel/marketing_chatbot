"""Tenant bot-settings routes -- GET/PUT /admin/settings (S12.2).

``GET`` is readable by ``CLIENT_ADMIN`` and ``CLIENT_AGENT`` (a read-only
view of the bot's config is reasonable for an agent reviewing conversations,
mirrors S11.2's RBAC choice). ``PUT`` is ``CLIENT_ADMIN``-only (CLAUDE.md:
``CLIENT_AGENT`` "cannot change config") and writes ONLY the four qualitative
columns -- thresholds/provider/model are read-only here, unchanged by this
endpoint (decision 6).
"""
from __future__ import annotations

from typing import Any

from common.auth import AuthClaims, Role
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from api.admin.settings_repository import BotSettings, get_bot_settings, upsert_bot_settings
from api.auth.dependencies import require_roles

_log = get_logger(__name__)

router = APIRouter(prefix="/admin/settings", tags=["admin"])


class AdminBotSettingsRequest(BaseModel):
    """Body for PUT /admin/settings -- the four new qualitative fields only."""

    greeting: str | None = Field(default=None, max_length=2000)
    business_hours: dict[str, Any] | None = None
    escalation_policy: str | None = Field(default=None, max_length=2000)
    tone: str | None = Field(default=None, max_length=100)


class AdminBotSettingsResponse(BaseModel):
    """Unified read: qualitative fields + EXISTING thresholds + provider/model."""

    greeting: str | None
    business_hours: dict[str, Any] | None
    escalation_policy: str | None
    tone: str | None
    answer_threshold: float
    escalate_threshold: float
    turn_cap: int
    llm_provider: str | None
    llm_model: str | None


def _to_response(settings: BotSettings) -> AdminBotSettingsResponse:
    return AdminBotSettingsResponse(
        greeting=settings.greeting,
        business_hours=settings.business_hours,
        escalation_policy=settings.escalation_policy,
        tone=settings.tone,
        answer_threshold=settings.answer_threshold,
        escalate_threshold=settings.escalate_threshold,
        turn_cap=settings.turn_cap,
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
    )


@router.get("")
async def get_settings(
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> AdminBotSettingsResponse:
    """Unified read: qualitative bot config + existing thresholds + provider/model."""
    db = request.app.state.db

    settings = await get_bot_settings(db, claims)
    return _to_response(settings)


@router.put("")
async def put_settings(
    body: AdminBotSettingsRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> AdminBotSettingsResponse:
    """Write ONLY the four qualitative fields; thresholds/provider/model are untouched."""
    db = request.app.state.db

    await upsert_bot_settings(
        db,
        claims,
        greeting=body.greeting,
        business_hours=body.business_hours,
        escalation_policy=body.escalation_policy,
        tone=body.tone,
    )

    _log.info(
        "tenant bot settings updated",
        extra={"event": "tenant_bot_settings_updated", "tenant_id": claims.tenant_id},
    )

    settings = await get_bot_settings(db, claims)
    return _to_response(settings)
