"""RAG service -- embed the query, search the tenant's chunks, score confidence.

``retrieve`` is the read-side counterpart of ingestion (S5.3): embed an
incoming query via the tenant's own provider + embedding model, run a
tenant-scoped pgvector cosine search, and return the top-k chunks plus a
single ``confidence`` signal. No silent fallback: a misconfigured or failing
embedding step fails loud, and an empty knowledge base returns a low-confidence
empty result rather than an error or a fabricated chunk.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.auth import AuthClaims
from common.db import Database
from common.errors import InternalServerError, ValidationError

from api.config import get_api_settings
from api.llm.config_repository import get_llm_config
from api.llm.factory import provider_for
from api.rag.repository import ChunkMatch, search_chunks


@dataclass(frozen=True)
class RetrievalResult:
    """The result of a single retrieval call."""

    chunks: list[ChunkMatch]
    confidence: float


def _clamp_k(k: int, *, max_k: int) -> int:
    """Clamp ``k`` to ``[1, max_k]`` -- an unbounded/huge k must not run."""
    if k < 1:
        return 1
    if k > max_k:
        return max_k
    return k


async def retrieve(
    db: Database,
    claims: AuthClaims,
    query: str,
    *,
    k: int,
) -> RetrievalResult:
    """Embed ``query`` with the tenant's provider and search their chunks.

    Raises
    ------
    ValidationError (``RAG_EMBEDDING_NOT_CONFIGURED``)
        If the tenant has no LLM config or no ``embedding_model`` set. Never
        embed with a guessed model, never fabricate a zero vector.
    InternalServerError (``EMBEDDING_DIM_MISMATCH``)
        If the embedded query vector's dimension does not match
        ``settings.embedding_dimension`` -- a mismatched query model is a
        misconfiguration, fail loud rather than bind a malformed vector.
    LLMError
        Propagates untouched from ``provider.embed`` (transient upstream
        failure) -- never swallowed, never a partial result.

    An empty result set (no chunks for the tenant, or empty KB) returns
    ``confidence=0.0`` and ``chunks=[]`` -- never raises.
    """
    settings = get_api_settings()
    bounded_k = _clamp_k(k, max_k=settings.rag_max_top_k)

    config = await get_llm_config(db, claims)
    if config is None or not config.embedding_model:
        raise ValidationError(
            "No embedding model is configured for this tenant.",
            code="RAG_EMBEDDING_NOT_CONFIGURED",
        )

    provider = provider_for(config)
    # LLMError from embed propagates untouched -- transient, never swallowed.
    vectors = await provider.embed([query], model=config.embedding_model)
    qvec = vectors[0]

    if len(qvec) != settings.embedding_dimension:
        raise InternalServerError(
            f"Query embedding has dimension {len(qvec)}, "
            f"expected {settings.embedding_dimension}.",
            code="EMBEDDING_DIM_MISMATCH",
        )

    chunks = await search_chunks(db, claims, qvec, top_k=bounded_k)

    # confidence = top-1 score clamped to [0.0, 1.0]; empty result -> 0.0.
    confidence = max(0.0, min(1.0, chunks[0].score)) if chunks else 0.0

    return RetrievalResult(chunks=chunks, confidence=confidence)
