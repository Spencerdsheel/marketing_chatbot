"""Admin/agent conversation review routes -- GET /admin/conversations(/{id}).

An authenticated ``CLIENT_ADMIN`` or ``CLIENT_AGENT`` lists their tenant's
conversations (paginated, filterable) and opens the full transcript of one.
This is the read-only "conversation review" console surface (S12.4) -- a new
sibling of the existing ``/debug/conversations/**`` routes (``CLIENT_ADMIN``
-only, id-required, not an enumeration surface) and distinct from S11.2's
aggregate ``/admin/analytics/overview``. Every access is tenant-scoped via
``claims.tenant_id`` -- a cross-tenant ``conversation_id`` is indistinguishable
from a missing one and returns 404. Responses never include ``tenant_id``.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from common.auth import AuthClaims, Role
from common.errors import NotFoundError, ValidationError
from common.logging import get_logger
from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from api.auth.dependencies import require_roles, resolve_tenant_scope
from api.conversation_store.repository import (
    ConversationSummaryRow,
    get_conversation,
    get_messages,
    list_conversations,
)

_log = get_logger(__name__)

router = APIRouter(prefix="/admin/conversations", tags=["conversations"])
tenant_scoped_router = APIRouter(
    prefix="/admin/tenants/{tenant_id}/conversations", tags=["conversations"]
)

_VALID_STATUSES: set[str] = {"active", "ended"}


class ConversationListItem(BaseModel):
    """A single row in the paginated ``GET /admin/conversations`` list --
    leak-free (no ``tenant_id``)."""

    conversation_id: str
    status: str
    channel: str
    visitor_id: str | None
    started_at: datetime
    ended_at: datetime | None
    message_count: int
    summary: str | None


class ConversationListResponse(BaseModel):
    """Paginated envelope for ``GET /admin/conversations`` -- mirrors
    ``LeadListResponse``'s extension of the ``api/audit/routes.py``
    limit/offset convention with ``total``."""

    items: list[ConversationListItem]
    total: int
    limit: int
    offset: int


class MessageResponse(BaseModel):
    """A single transcript message -- leak-free (no ``tenant_id``)."""

    message_id: str
    role: str
    content: str
    intent: str | None
    confidence: float | None
    tokens: int | None
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    """Full transcript detail for ``GET /admin/conversations/{conversation_id}``
    -- leak-free (no ``tenant_id``)."""

    conversation_id: str
    status: str
    channel: str
    started_at: datetime
    ended_at: datetime | None
    summary: str | None
    messages: list[MessageResponse]


def _to_list_item(row: ConversationSummaryRow) -> ConversationListItem:
    return ConversationListItem(
        conversation_id=row.conversation_id,
        status=row.status,
        channel=row.channel,
        visitor_id=row.visitor_id,
        started_at=row.started_at,
        ended_at=row.ended_at,
        message_count=row.message_count,
        summary=row.summary,
    )


async def _list_conversations(
    request: Request,
    claims: AuthClaims,
    *,
    limit: int,
    offset: int,
    status_: str | None,
    channel: str | None,
    escalated: bool | None,
    started_from: datetime | None,
    started_to: datetime | None,
) -> ConversationListResponse:
    """List/filter the caller's tenant conversations, newest first, paginated.

    ``status`` is validated against ``{active, ended}`` (422
    ``INVALID_CONVERSATION_FILTER`` on an unknown value). ``channel`` is an
    exact-match pass-through. ``escalated`` restricts to conversations with
    (``true``) / without (``false``) a bot turn with ``decision='escalate'``.
    ``from``/``to`` filter ``started_at`` as a half-open ``[from, to)`` window
    (422 ``INVALID_LIST_WINDOW`` if ``from >= to``). ``limit`` clamped to
    ``[1, 200]``, ``offset`` to ``>= 0``.
    """
    db = request.app.state.db

    if status_ is not None and status_ not in _VALID_STATUSES:
        raise ValidationError(
            f"Unknown status filter {status_!r}.", code="INVALID_CONVERSATION_FILTER",
        )
    if started_from is not None and started_to is not None and started_from >= started_to:
        raise ValidationError(
            "`from` must be earlier than `to`.", code="INVALID_LIST_WINDOW",
        )

    clamped_limit = max(1, min(limit, 200))
    clamped_offset = max(0, offset)

    rows, total = await list_conversations(
        db,
        claims,
        limit=clamped_limit,
        offset=clamped_offset,
        started_from=started_from,
        started_to=started_to,
        status=status_,
        channel=channel,
        escalated=escalated,
    )

    filter_keys: dict[str, Any] = {
        "status": status_,
        "channel": channel,
        "escalated": escalated,
        "from": started_from,
        "to": started_to,
    }
    _log.info(
        "conversations listed",
        extra={
            "event": "conversations_listed",
            "tenant_id": claims.tenant_id,
            "filter_keys": sorted(k for k, v in filter_keys.items() if v is not None),
            "result_count": len(rows),
        },
    )

    return ConversationListResponse(
        items=[_to_list_item(r) for r in rows],
        total=total,
        limit=clamped_limit,
        offset=clamped_offset,
    )


@router.get("")
async def list_conversations_route(
    request: Request,
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    status_: str | None = Query(default=None, alias="status"),
    channel: str | None = Query(default=None),
    escalated: bool | None = Query(default=None),
    started_from: datetime | None = Query(default=None, alias="from"),  # noqa: B008
    started_to: datetime | None = Query(default=None, alias="to"),  # noqa: B008
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> ConversationListResponse:
    return await _list_conversations(
        request, claims,
        limit=limit, offset=offset, status_=status_, channel=channel,
        escalated=escalated, started_from=started_from, started_to=started_to,
    )


@tenant_scoped_router.get("")
async def list_conversations_route_for_tenant(
    request: Request,
    limit: int = Query(default=50),
    offset: int = Query(default=0),
    status_: str | None = Query(default=None, alias="status"),
    channel: str | None = Query(default=None),
    escalated: bool | None = Query(default=None),
    started_from: datetime | None = Query(default=None, alias="from"),  # noqa: B008
    started_to: datetime | None = Query(default=None, alias="to"),  # noqa: B008
    claims: AuthClaims = Depends(resolve_tenant_scope(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> ConversationListResponse:
    """PLATFORM_ADMIN super-user variant of ``GET /admin/conversations`` (S12.7)."""
    return await _list_conversations(
        request, claims,
        limit=limit, offset=offset, status_=status_, channel=channel,
        escalated=escalated, started_from=started_from, started_to=started_to,
    )


async def _get_conversation_detail(
    conversation_id: str,
    request: Request,
    claims: AuthClaims,
) -> ConversationDetailResponse:
    """Fetch a conversation's full transcript. Reuses ``get_conversation`` +
    ``get_messages`` (already tenant-scoped) -- no new single-conversation
    read logic. Returns 404 ``CONVERSATION_NOT_FOUND`` if missing or
    cross-tenant.
    """
    db = request.app.state.db

    conv = await get_conversation(db, claims, conversation_id)
    if conv is None:
        raise NotFoundError(
            "Conversation not found.", code="CONVERSATION_NOT_FOUND",
        )

    messages = await get_messages(db, claims, conversation_id)

    _log.info(
        "conversation viewed",
        extra={
            "event": "conversation_viewed",
            "conversation_id": conversation_id,
            "tenant_id": claims.tenant_id,
            "message_count": len(messages),
        },
    )

    return ConversationDetailResponse(
        conversation_id=conv.conversation_id,
        status=conv.status,
        channel=conv.channel,
        started_at=conv.started_at,
        ended_at=conv.ended_at,
        summary=conv.summary,
        messages=[
            MessageResponse(
                message_id=m.message_id,
                role=m.role,
                content=m.content,
                intent=m.intent,
                confidence=m.confidence,
                tokens=m.tokens,
                created_at=m.created_at,
            )
            for m in messages
        ],
    )


@router.get("/{conversation_id}")
async def get_conversation_detail(
    conversation_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> ConversationDetailResponse:
    return await _get_conversation_detail(conversation_id, request, claims)


@tenant_scoped_router.get("/{conversation_id}")
async def get_conversation_detail_for_tenant(
    conversation_id: str,
    request: Request,
    claims: AuthClaims = Depends(resolve_tenant_scope(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> ConversationDetailResponse:
    """PLATFORM_ADMIN super-user variant of
    ``GET /admin/conversations/{conversation_id}`` (S12.7)."""
    return await _get_conversation_detail(conversation_id, request, claims)
