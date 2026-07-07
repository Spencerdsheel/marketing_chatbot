"""Debug RAG routes -- tenant-scoped retrieval over knowledge_chunks.

This is a TEMPORARY debug endpoint (prefixed ``/debug/rag``), mirroring the
``/debug/llm`` shape, to prove the retrieval boundary end-to-end. Real
retrieval is internal to the conversation-orchestrator (Phase 10); this
endpoint exists so the retrieval seam can be exercised directly.

The response is leak-free: it never includes ``tenant_id``, the query
embedding, or the raw distance internals.
"""
from __future__ import annotations

from typing import Literal

from common.auth import AuthClaims, Role
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from api.auth.dependencies import require_roles
from api.config import get_api_settings
from api.rag.service import retrieve, retrieve_hybrid

router = APIRouter(prefix="/debug/rag", tags=["rag"])


class RagSearchRequest(BaseModel):
    """Body for POST /debug/rag/search.

    ``mode="hybrid"`` (default) fuses vector + keyword search (S6.2, RRF) and
    returns the richer confidence signal. ``mode="vector"`` uses the S6.1
    vector-only path, unchanged, for comparison.
    """

    query: str
    k: int | None = None
    mode: Literal["hybrid", "vector"] = "hybrid"


class RagChunkResponse(BaseModel):
    """A single leak-free chunk result (``mode=vector``) -- no tenant_id, no embedding."""

    doc_id: str
    chunk_id: str
    content: str
    score: float


class RagSearchResponse(BaseModel):
    """Leak-free response body (``mode=vector``) for POST /debug/rag/search."""

    count: int
    confidence: float
    chunks: list[RagChunkResponse]


class RagHybridChunkResponse(BaseModel):
    """A single leak-free fused chunk result (``mode=hybrid``).

    ``score`` is nullable -- ``None`` for a keyword-only hit (never
    back-filled with a fake distance). ``rrf_score`` and ``matched_by`` carry
    fusion provenance.
    """

    doc_id: str
    chunk_id: str
    content: str
    score: float | None
    rrf_score: float
    matched_by: list[str]


class RagHybridSearchResponse(BaseModel):
    """Leak-free response body (``mode=hybrid``) for POST /debug/rag/search."""

    count: int
    confidence: float
    chunks: list[RagHybridChunkResponse]


@router.post("/search")
async def search(
    body: RagSearchRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> RagSearchResponse | RagHybridSearchResponse:
    """Embed ``body.query`` and search the caller's tenant-scoped chunks.

    ``mode="hybrid"`` (default) -> ``retrieve_hybrid`` (vector + keyword RRF
    fusion + richer confidence). ``mode="vector"`` -> ``retrieve`` (S6.1,
    unchanged). Returns 422 ``RAG_EMBEDDING_NOT_CONFIGURED`` if the tenant has
    no embedding model configured. Returns 502 ``LLM_ERROR`` if the embed call
    fails.
    """
    settings = get_api_settings()
    db = request.app.state.db
    k = body.k if body.k is not None else settings.rag_default_top_k

    if body.mode == "vector":
        vector_result = await retrieve(db, claims, body.query, k=k)
        return RagSearchResponse(
            count=len(vector_result.chunks),
            confidence=vector_result.confidence,
            chunks=[
                RagChunkResponse(
                    doc_id=chunk.doc_id,
                    chunk_id=chunk.chunk_id,
                    content=chunk.content,
                    score=chunk.score,
                )
                for chunk in vector_result.chunks
            ],
        )

    hybrid_result = await retrieve_hybrid(db, claims, body.query, k=k)
    return RagHybridSearchResponse(
        count=len(hybrid_result.chunks),
        confidence=hybrid_result.confidence,
        chunks=[
            RagHybridChunkResponse(
                doc_id=chunk.doc_id,
                chunk_id=chunk.chunk_id,
                content=chunk.content,
                score=chunk.score,
                rrf_score=chunk.rrf_score,
                matched_by=chunk.matched_by,
            )
            for chunk in hybrid_result.chunks
        ],
    )
