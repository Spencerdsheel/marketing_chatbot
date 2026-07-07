"""Debug RAG routes -- tenant-scoped retrieval over knowledge_chunks.

This is a TEMPORARY debug endpoint (prefixed ``/debug/rag``), mirroring the
``/debug/llm`` shape, to prove the retrieval boundary end-to-end. Real
retrieval is internal to the conversation-orchestrator (Phase 10); this
endpoint exists so the retrieval seam can be exercised directly.

The response is leak-free: it never includes ``tenant_id``, the query
embedding, or the raw distance internals.
"""
from __future__ import annotations

from common.auth import AuthClaims, Role
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from api.auth.dependencies import require_roles
from api.config import get_api_settings
from api.rag.service import retrieve

router = APIRouter(prefix="/debug/rag", tags=["rag"])


class RagSearchRequest(BaseModel):
    """Body for POST /debug/rag/search."""

    query: str
    k: int | None = None


class RagChunkResponse(BaseModel):
    """A single leak-free chunk result -- no tenant_id, no embedding."""

    doc_id: str
    chunk_id: str
    content: str
    score: float


class RagSearchResponse(BaseModel):
    """Leak-free response body for POST /debug/rag/search."""

    count: int
    confidence: float
    chunks: list[RagChunkResponse]


@router.post("/search")
async def search(
    body: RagSearchRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> RagSearchResponse:
    """Embed ``body.query`` and search the caller's tenant-scoped chunks.

    Returns 422 ``RAG_EMBEDDING_NOT_CONFIGURED`` if the tenant has no embedding
    model configured. Returns 502 ``LLM_ERROR`` if the embed call fails.
    """
    settings = get_api_settings()
    db = request.app.state.db

    result = await retrieve(
        db,
        claims,
        body.query,
        k=body.k if body.k is not None else settings.rag_default_top_k,
    )

    return RagSearchResponse(
        count=len(result.chunks),
        confidence=result.confidence,
        chunks=[
            RagChunkResponse(
                doc_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                score=chunk.score,
            )
            for chunk in result.chunks
        ],
    )
