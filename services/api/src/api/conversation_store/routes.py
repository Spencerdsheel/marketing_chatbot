"""Debug conversation routes -- create, append, and read conversations.

These are TEMPORARY debug endpoints (prefixed ``/debug/conversations``) to
prove the conversation store. Real visitor-facing endpoints land in the
orchestrator (Phase 10).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from common.auth import AuthClaims, Role
from common.errors import NotFoundError, ValidationError
from common.logging import get_logger
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from api.auth.dependencies import require_roles
from api.conversation_store.repository import (
    append_message,
    create_conversation,
    delete_conversation,
    export_conversation,
    get_conversation,
    get_messages,
    get_window,
    get_working_memory,
    purge_expired,
    roll_summary,
)
from api.llm.config_repository import get_llm_config
from api.llm.factory import provider_for

_log = get_logger(__name__)

router = APIRouter(prefix="/debug/conversations", tags=["conversations"])


class CreateConversationRequest(BaseModel):
    visitor_id: str | None = None
    channel: str = "widget"
    metadata: dict[str, object] | None = None


class AppendMessageRequest(BaseModel):
    role: str
    content: str
    intent: str | None = None
    confidence: float | None = None
    tokens: int | None = None
    message_id: str | None = None


class RollSummaryRequest(BaseModel):
    keep_recent: int


class PurgeRequest(BaseModel):
    before: datetime


@router.post("")
async def create_conv(
    body: CreateConversationRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, str]:
    """Create a new conversation for the calling tenant."""
    conv_id = await create_conversation(
        request.app.state.db,
        claims,
        visitor_id=body.visitor_id,
        channel=body.channel,
        metadata=body.metadata,
    )
    _log.info(
        "Conversation created",
        extra={"event": "conversation_created", "conversation_id": conv_id},
    )
    return {"conversation_id": conv_id, "status": "active"}


@router.post("/{conversation_id}/messages")
async def append_msg(
    conversation_id: str,
    body: AppendMessageRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, str]:
    """Append a message to a conversation."""
    msg_id = await append_message(
        request.app.state.db,
        claims,
        conversation_id,
        role=body.role,
        content=body.content,
        intent=body.intent,
        confidence=body.confidence,
        tokens=body.tokens,
        message_id=body.message_id,
    )
    return {"message_id": msg_id}


def _iso(dt: datetime | str | None) -> str | None:
    """Return ISO format string for a datetime, or pass through strings."""
    if dt is None:
        return None
    if hasattr(dt, "isoformat"):
        return str(dt.isoformat())
    return str(dt)


@router.get("/{conversation_id}")
async def get_conv(
    conversation_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, object]:
    """Fetch a conversation with its messages.

    Returns 404 ``CONVERSATION_NOT_FOUND`` if absent or not visible.
    Response does NOT include ``tenant_id``.
    """
    db = request.app.state.db

    conv = await get_conversation(db, claims, conversation_id)
    if conv is None:
        raise NotFoundError(
            "Conversation not found.",
            code="CONVERSATION_NOT_FOUND",
        )

    messages = await get_messages(db, claims, conversation_id)

    return {
        "conversation_id": conv.conversation_id,
        "status": conv.status,
        "channel": conv.channel,
        "started_at": _iso(conv.started_at),
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "intent": m.intent,
                "confidence": m.confidence,
                "tokens": m.tokens,
                "created_at": _iso(m.created_at),
            }
            for m in messages
        ],
    }


@router.get("/{conversation_id}/window")
async def get_conv_window(
    conversation_id: str,
    request: Request,
    limit: int | None = Query(default=None),
    token_budget: int | None = Query(default=None),
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, object]:
    """Fetch a windowed slice of conversation history.

    Provide exactly one of ``limit`` (last-N) or ``token_budget``.
    Returns 404 ``CONVERSATION_NOT_FOUND`` if absent or not visible.
    Response does NOT include ``tenant_id``.
    """
    db = request.app.state.db

    msgs = await get_window(
        db, claims, conversation_id, limit=limit, token_budget=token_budget,
    )

    return {
        "conversation_id": conversation_id,
        "count": len(msgs),
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "intent": m.intent,
                "confidence": m.confidence,
                "tokens": m.tokens,
                "created_at": _iso(m.created_at),
            }
            for m in msgs
        ],
    }


@router.post("/{conversation_id}/summary")
async def roll_conv_summary(
    conversation_id: str,
    body: RollSummaryRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, bool]:
    """Fold older messages into the conversation's running summary.

    Resolves the tenant's configured LLM provider and rolls the summary via
    ``roll_summary``. Returns 422 ``LLM_NOT_CONFIGURED`` if the tenant has no
    LLM config. Returns 502 ``LLM_ERROR`` if the provider call fails -- no
    summary is written in that case (no silent fallback).
    """
    db = request.app.state.db

    config = await get_llm_config(db, claims)
    if config is None:
        raise ValidationError(
            "LLM is not configured for this tenant.",
            code="LLM_NOT_CONFIGURED",
        )

    provider = provider_for(config)
    rolled = await roll_summary(
        db,
        claims,
        conversation_id,
        provider=provider,
        model=config.model,
        keep_recent=body.keep_recent,
    )
    _log.info(
        "Conversation summary rolled",
        extra={
            "event": "conversation_summary_rolled",
            "conversation_id": conversation_id,
            "rolled": rolled,
        },
    )
    return {"rolled": rolled}


@router.get("/{conversation_id}/working-memory")
async def get_conv_working_memory(
    conversation_id: str,
    request: Request,
    keep_recent: int = Query(default=1),
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, object]:
    """Fetch the conversation's working memory: running summary + recent window.

    Returns 404 ``CONVERSATION_NOT_FOUND`` if absent or not visible.
    Response does NOT include ``tenant_id``.
    """
    db = request.app.state.db

    memory = await get_working_memory(
        db, claims, conversation_id, keep_recent=keep_recent,
    )
    messages = memory["messages"]

    return {
        "conversation_id": conversation_id,
        "summary": memory["summary"],
        "summary_message_count": memory["summary_message_count"],
        "messages": [
            {
                "message_id": m.message_id,
                "role": m.role,
                "content": m.content,
                "intent": m.intent,
                "confidence": m.confidence,
                "tokens": m.tokens,
                "created_at": _iso(m.created_at),
            }
            for m in messages
        ],
    }


@router.get("/{conversation_id}/export")
async def export_conv(
    conversation_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, Any]:
    """Export a full conversation transcript (data portability).

    Returns 404 ``CONVERSATION_NOT_FOUND`` if absent or not visible.
    Response does NOT include ``tenant_id``.
    """
    db = request.app.state.db

    transcript = await export_conversation(db, claims, conversation_id)

    _log.info(
        "Conversation exported",
        extra={
            "event": "conversation_exported",
            "conversation_id": conversation_id,
            "message_count": len(transcript["messages"]),
        },
    )

    return {
        "conversation_id": transcript["conversation_id"],
        "status": transcript["status"],
        "channel": transcript["channel"],
        "started_at": _iso(transcript["started_at"]),
        "ended_at": _iso(transcript["ended_at"]),
        "summary": transcript["summary"],
        "summary_message_count": transcript["summary_message_count"],
        "messages": [
            {
                "message_id": m["message_id"],
                "role": m["role"],
                "content": m["content"],
                "intent": m["intent"],
                "confidence": m["confidence"],
                "tokens": m["tokens"],
                "created_at": _iso(m["created_at"]),
            }
            for m in transcript["messages"]
        ],
    }


@router.delete("/{conversation_id}")
async def delete_conv(
    conversation_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, bool]:
    """Delete a conversation (right-to-erasure; messages cascade).

    Returns 404 ``CONVERSATION_NOT_FOUND`` if absent or not visible.
    """
    db = request.app.state.db

    await delete_conversation(db, claims, conversation_id)

    _log.info(
        "Conversation deleted",
        extra={
            "event": "conversation_deleted",
            "conversation_id": conversation_id,
        },
    )

    return {"deleted": True}


@router.post("/purge")
async def purge_convs(
    body: PurgeRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, int]:
    """Purge ended conversations older than ``before``.

    Returns the count of conversations deleted.
    """
    db = request.app.state.db

    count = await purge_expired(db, claims, before=body.before)

    _log.info(
        "Conversations purged",
        extra={
            "event": "conversation_purged",
            "count": count,
        },
    )

    return {"purged": count}
