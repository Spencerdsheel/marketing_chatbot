"""Chat orchestrator routes -- POST /public/chat/message (S10.1).

Mirrors the ``/public/leads`` shape: visitor-authenticated
(``get_visitor_claims``), leak-free response (no ``tenant_id``/``visitor_id``
ever), and ``tenant_id``/``visitor_id`` come only from the signed visitor
session -- never the request body.
"""
from __future__ import annotations

from typing import Literal

from common.auth import AuthClaims
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_validator

from api.gateway.dependencies import get_visitor_claims
from api.orchestrator.service import answer_turn

_log = get_logger(__name__)

router = APIRouter(prefix="/public/chat", tags=["chat"])


class ChatMessageRequest(BaseModel):
    """Body for POST /public/chat/message."""

    message: str
    conversation_id: str | None = None
    message_id: str | None = None

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("message must not be blank")
        return v


class ChatSource(BaseModel):
    """A cited chunk in the response -- identifiers + score only, never raw content."""

    doc_id: str
    chunk_id: str
    score: float | None
    matched_by: list[str]


class ChatMessageResponse(BaseModel):
    """Leak-free response body for POST /public/chat/message.

    ``intent``/``grounded``/``guardrail_flag`` are stored (analytics) but
    never surfaced here -- keep the public surface minimal; still leak-free
    (never ``tenant_id``/``visitor_id``). ``action`` (S10.3) IS surfaced --
    it tells the widget to render the consent-gated lead form on either
    ``decision`` value that means "offer a human" (``escalate``/``blocked``).
    """

    conversation_id: str
    message_id: str
    reply: str
    decision: Literal["answer", "clarify", "escalate", "blocked"]
    confidence: float | None
    sources: list[ChatSource]
    action: Literal["lead_form"] | None = None


@router.post("/message")
async def post_message(
    body: ChatMessageRequest,
    request: Request,
    claims: AuthClaims = Depends(get_visitor_claims),  # noqa: B008
) -> ChatMessageResponse:
    """Run one visitor turn: store -> classify -> branch -> store.

    ``tenant_id`` and ``visitor_id`` come from the visitor session
    (``claims``), never from the request body. Errors from ``answer_turn``
    (``LLM_NOT_CONFIGURED``/``RAG_EMBEDDING_NOT_CONFIGURED`` 422,
    ``LLM_ERROR`` 502 -- including a ``classify`` failure, S10.2 decision 9,
    ``CONVERSATION_NOT_FOUND`` 404) propagate to the centralized error
    middleware.
    """
    db = request.app.state.db

    result = await answer_turn(
        db,
        claims,
        message=body.message,
        conversation_id=body.conversation_id,
        message_id=body.message_id,
    )

    # -- Log the event (PII-safe: never the message text, reply, or raw
    # intent free text -- decision/intent/guardrail_flag are closed-set,
    # non-PII labels) --------------------------------------------------------
    _log.info(
        "chat turn",
        extra={
            "event": "chat_turn",
            "tenant_id": claims.tenant_id,
            "conversation_id": result.conversation_id,
            "confidence": result.confidence,
            "decision": result.decision,
            "intent": result.intent,
            "guardrail_flag": result.guardrail_flag,
        },
    )

    return ChatMessageResponse(
        conversation_id=result.conversation_id,
        message_id=result.message_id,
        reply=result.reply,
        decision=result.decision,  # type: ignore[arg-type]
        confidence=result.confidence,
        sources=[
            ChatSource(doc_id=s.doc_id, chunk_id=s.chunk_id, score=s.score, matched_by=s.matched_by)
            for s in result.sources
        ],
        action=result.action,  # type: ignore[arg-type]
    )
