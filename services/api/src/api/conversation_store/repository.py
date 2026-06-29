"""Conversation store repository -- tenant-scoped, idempotent append.

Every method takes ``AuthClaims`` and filters by ``claims.tenant_id`` at the
repository layer.  ``PLATFORM_ADMIN`` (global) is rejected with a
``ValidationError``.  ``VISITOR`` callers are additionally scoped to their own
``visitor_id``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from common.auth import AuthClaims, Role
from common.db import Database
from common.errors import NotFoundError, ValidationError


@dataclass(frozen=True)
class Conversation:
    conversation_id: str
    status: str
    channel: str
    visitor_id: str | None
    started_at: datetime
    ended_at: datetime | None
    metadata: dict[str, Any]


@dataclass(frozen=True)
class Message:
    message_id: str
    role: str
    content: str
    intent: str | None
    confidence: float | None
    tokens: int | None
    created_at: datetime


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN)."""
    if claims.tenant_id is None:
        raise ValidationError("Conversation store is tenant-scoped.")


def _scope_filter(claims: AuthClaims) -> tuple[str, list[Any]]:
    """Extra WHERE clause + params for VISITOR scoping (visitor param is $3 in all
    three read queries, which bind tenant_id=$1, conversation_id=$2 first).
    CLIENT_ADMIN / CLIENT_AGENT: empty clause."""
    if claims.role == Role.VISITOR:
        return " AND visitor_id = $3", [claims.subject]
    return "", []


async def _verify_conversation_visible(
    db: Database, claims: AuthClaims, conversation_id: str,
) -> None:
    """Raise ``NotFoundError`` if the conversation is not visible to the caller."""
    extra, extra_params = _scope_filter(claims)
    # Parameterized SQL; `extra` is a safe constant clause from _scope_filter.
    # ruff: noqa: S608
    sql = (
        "SELECT 1 FROM conversations "
        "WHERE tenant_id = $1 AND conversation_id = $2" + extra
    )
    row = await db.fetchrow(sql, claims.tenant_id, conversation_id, *extra_params)
    if row is None:
        raise NotFoundError(
            "Conversation not found.",
            code="CONVERSATION_NOT_FOUND",
        )


async def create_conversation(
    db: Database,
    claims: AuthClaims,
    *,
    visitor_id: str | None = None,
    channel: str = "widget",
    metadata: dict[str, Any] | None = None,
) -> str:
    """Create a new conversation for the caller's tenant.

    Returns the generated ``conversation_id`` (32-char hex).
    For ``VISITOR`` callers, ``visitor_id`` defaults to ``claims.subject``.
    """
    _reject_global(claims)

    if claims.role == Role.VISITOR and visitor_id is None:
        visitor_id = claims.subject

    conversation_id = uuid4().hex
    meta = metadata or {}

    await db.execute(
        "INSERT INTO conversations "
        "(conversation_id, tenant_id, visitor_id, status, channel, metadata) "
        "VALUES ($1, $2, $3, 'active', $4, $5)",
        conversation_id,
        claims.tenant_id,
        visitor_id,
        channel,
        meta,
    )
    return conversation_id


async def append_message(
    db: Database,
    claims: AuthClaims,
    conversation_id: str,
    *,
    role: str,
    content: str,
    intent: str | None = None,
    confidence: float | None = None,
    tokens: int | None = None,
    message_id: str | None = None,
) -> str:
    """Append a message to a conversation (idempotent by ``message_id``).

    Raises ``NotFoundError`` if the conversation is not visible to the caller.
    Returns the ``message_id`` (supplied or generated).
    """
    _reject_global(claims)
    await _verify_conversation_visible(db, claims, conversation_id)

    message_id = message_id or uuid4().hex

    await db.execute(
        "INSERT INTO messages "
        "(message_id, tenant_id, conversation_id, role, content, "
        " intent, confidence, tokens) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
        "ON CONFLICT (message_id) DO NOTHING",
        message_id,
        claims.tenant_id,
        conversation_id,
        role,
        content,
        intent,
        confidence,
        tokens,
    )
    return message_id


async def get_conversation(
    db: Database, claims: AuthClaims, conversation_id: str,
) -> Conversation | None:
    """Fetch a conversation if visible to the caller.

    Returns ``None`` if absent or not visible.
    """
    _reject_global(claims)

    extra, extra_params = _scope_filter(claims)
    # Parameterized SQL; `extra` is a safe constant clause from _scope_filter.
    # ruff: noqa: S608
    sql = (
        "SELECT conversation_id, status, channel, visitor_id, "
        "started_at, ended_at, metadata "
        "FROM conversations "
        "WHERE tenant_id = $1 AND conversation_id = $2" + extra
    )
    row = await db.fetchrow(sql, claims.tenant_id, conversation_id, *extra_params)
    if row is None:
        return None

    return Conversation(
        conversation_id=str(row["conversation_id"]),
        status=str(row["status"]),
        channel=str(row["channel"]),
        visitor_id=row["visitor_id"],
        started_at=row["started_at"],
        ended_at=row["ended_at"],
        metadata=row["metadata"] or {},
    )


async def get_messages(
    db: Database, claims: AuthClaims, conversation_id: str,
) -> list[Message]:
    """Fetch all messages for a visible conversation, ordered by creation.

    Raises ``NotFoundError`` if the conversation is not visible to the caller.
    """
    _reject_global(claims)
    await _verify_conversation_visible(db, claims, conversation_id)

    extra, extra_params = _scope_filter(claims)
    # Parameterized SQL; `extra` is a safe constant clause from _scope_filter.
    # ruff: noqa: S608
    sql = (
        "SELECT message_id, role, content, intent, confidence, tokens, "
        "created_at "
        "FROM messages "
        "WHERE tenant_id = $1 AND conversation_id = $2" + extra + " "
        "ORDER BY created_at, message_id"
    )
    rows = await db.fetch(sql, claims.tenant_id, conversation_id, *extra_params)
    return [
        Message(
            message_id=str(r["message_id"]),
            role=str(r["role"]),
            content=str(r["content"]),
            intent=r["intent"],
            confidence=r["confidence"],
            tokens=r["tokens"],
            created_at=r["created_at"],
        )
        for r in rows
    ]
