"""Unit tests for api.rag.service.retrieve.

Covers:
- Success path with a stub provider (correct-dim vector) + stub search_chunks
  (3 matches): embeds the query once with model=config.embedding_model,
  returns chunks ordered, confidence == top score (clamped).
- No embedding_model configured -> RAG_EMBEDDING_NOT_CONFIGURED (422),
  provider_for/embed never called.
- embed raises LLMError -> propagates (not swallowed, no partial result).
- Empty result set -> confidence == 0.0, chunks == [], no exception.
- Negative top similarity -> confidence floored at 0.0.
- k clamping: k=0 -> 1; k=9999 -> rag_max_top_k (20).
"""
from __future__ import annotations

import sys
from unittest.mock import AsyncMock, patch

import pytest
from common.auth import AuthClaims, Role
from common.errors import ValidationError

from api.llm.provider import LLMError
from api.rag.repository import ChunkMatch

_TENANT_ID = "tenant-abc"

_TEST_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": "x" * 48,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}


def _reset_modules() -> None:
    # Reimport rag modules fresh + clear settings caches. Do NOT delete
    # api.config -- that splits the module graph and poisons later tests
    # (see the S4.4/S5.1 fallout). Clearing the caches is sufficient.
    for key in list(sys.modules.keys()):
        if key.startswith("api.rag"):
            del sys.modules[key]
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


def _claims(tenant_id: str | None = _TENANT_ID, role: Role = Role.CLIENT_ADMIN) -> AuthClaims:
    return AuthClaims(subject="user-1", role=role, tenant_id=tenant_id)


class _StubConfig:
    def __init__(self, embedding_model: str | None = "nomic-embed-text") -> None:
        self.embedding_model = embedding_model
        self.provider = "openai"
        self.model = "gpt-4o"


class _StubProvider:
    def __init__(self, vector: list[float], *, error: Exception | None = None) -> None:
        self._vector = vector
        self._error = error
        self.embed_calls: list[tuple[list[str], str]] = []

    async def embed(self, texts: list[str], *, model: str) -> list[list[float]]:
        self.embed_calls.append((texts, model))
        if self._error is not None:
            raise self._error
        return [self._vector]


async def test_retrieve_success_orders_chunks_and_confidence_is_top_score() -> None:
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()
        settings = get_api_settings()
        dim = settings.embedding_dimension

        from api.rag.service import retrieve  # noqa: PLC0415

        matches = [
            ChunkMatch(doc_id="d1", chunk_id="c1", content="a", score=0.9),
            ChunkMatch(doc_id="d1", chunk_id="c2", content="b", score=0.5),
            ChunkMatch(doc_id="d2", chunk_id="c3", content="c", score=0.2),
        ]
        provider = _StubProvider([0.1] * dim)

        with (
            patch("api.rag.service.get_llm_config", new=AsyncMock(return_value=_StubConfig())),
            patch("api.rag.service.provider_for", return_value=provider),
            patch("api.rag.service.search_chunks", new=AsyncMock(return_value=matches)),
        ):
            result = await retrieve(object(), _claims(), "what can it do?", k=5)

    assert result.chunks == matches
    assert result.confidence == pytest.approx(0.9)
    assert provider.embed_calls == [(["what can it do?"], "nomic-embed-text")]


async def test_retrieve_no_embedding_model_raises_422_and_provider_not_called() -> None:
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        from api.rag.service import retrieve  # noqa: PLC0415

        provider_for_mock = AsyncMock()

        with (
            patch(
                "api.rag.service.get_llm_config",
                new=AsyncMock(return_value=_StubConfig(embedding_model=None)),
            ),
            patch("api.rag.service.provider_for", new=provider_for_mock),
        ):
            with pytest.raises(ValidationError) as exc_info:
                await retrieve(object(), _claims(), "hello", k=5)

    assert exc_info.value.code == "RAG_EMBEDDING_NOT_CONFIGURED"
    provider_for_mock.assert_not_called()


async def test_retrieve_no_config_raises_422() -> None:
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        from api.rag.service import retrieve  # noqa: PLC0415

        with patch("api.rag.service.get_llm_config", new=AsyncMock(return_value=None)):
            with pytest.raises(ValidationError) as exc_info:
                await retrieve(object(), _claims(), "hello", k=5)

    assert exc_info.value.code == "RAG_EMBEDDING_NOT_CONFIGURED"


async def test_retrieve_embed_llm_error_propagates() -> None:
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        from api.rag.service import retrieve  # noqa: PLC0415

        provider = _StubProvider([0.1], error=LLMError("upstream failed"))
        search_mock = AsyncMock()

        with (
            patch("api.rag.service.get_llm_config", new=AsyncMock(return_value=_StubConfig())),
            patch("api.rag.service.provider_for", return_value=provider),
            patch("api.rag.service.search_chunks", new=search_mock),
        ):
            with pytest.raises(LLMError):
                await retrieve(object(), _claims(), "hello", k=5)

    search_mock.assert_not_awaited()


async def test_retrieve_empty_result_set_confidence_zero_no_exception() -> None:
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()
        dim = get_api_settings().embedding_dimension

        from api.rag.service import retrieve  # noqa: PLC0415

        provider = _StubProvider([0.1] * dim)

        with (
            patch("api.rag.service.get_llm_config", new=AsyncMock(return_value=_StubConfig())),
            patch("api.rag.service.provider_for", return_value=provider),
            patch("api.rag.service.search_chunks", new=AsyncMock(return_value=[])),
        ):
            result = await retrieve(object(), _claims(), "hello", k=5)

    assert result.chunks == []
    assert result.confidence == 0.0


async def test_retrieve_negative_top_score_confidence_floored_at_zero() -> None:
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()
        dim = get_api_settings().embedding_dimension

        from api.rag.service import retrieve  # noqa: PLC0415

        matches = [ChunkMatch(doc_id="d1", chunk_id="c1", content="a", score=-0.3)]
        provider = _StubProvider([0.1] * dim)

        with (
            patch("api.rag.service.get_llm_config", new=AsyncMock(return_value=_StubConfig())),
            patch("api.rag.service.provider_for", return_value=provider),
            patch("api.rag.service.search_chunks", new=AsyncMock(return_value=matches)),
        ):
            result = await retrieve(object(), _claims(), "hello", k=5)

    assert result.confidence == 0.0
    # The raw per-chunk score is surfaced as-is (not clamped) per decision 4.
    assert result.chunks[0].score == pytest.approx(-0.3)


async def test_retrieve_k_clamps_below_minimum_to_one() -> None:
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()
        dim = get_api_settings().embedding_dimension

        from api.rag.service import retrieve  # noqa: PLC0415

        provider = _StubProvider([0.1] * dim)
        search_mock = AsyncMock(return_value=[])

        with (
            patch("api.rag.service.get_llm_config", new=AsyncMock(return_value=_StubConfig())),
            patch("api.rag.service.provider_for", return_value=provider),
            patch("api.rag.service.search_chunks", new=search_mock),
        ):
            await retrieve(object(), _claims(), "hello", k=0)

    assert search_mock.await_args.kwargs["top_k"] == 1


async def test_retrieve_k_clamps_above_maximum_to_rag_max_top_k() -> None:
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()
        settings = get_api_settings()
        dim = settings.embedding_dimension

        from api.rag.service import retrieve  # noqa: PLC0415

        provider = _StubProvider([0.1] * dim)
        search_mock = AsyncMock(return_value=[])

        with (
            patch("api.rag.service.get_llm_config", new=AsyncMock(return_value=_StubConfig())),
            patch("api.rag.service.provider_for", return_value=provider),
            patch("api.rag.service.search_chunks", new=search_mock),
        ):
            await retrieve(object(), _claims(), "hello", k=9999)

    assert search_mock.await_args.kwargs["top_k"] == settings.rag_max_top_k


async def test_retrieve_dimension_mismatch_raises_internal_error() -> None:
    """A wrong-dim query vector is a misconfiguration -- fail loud, never search."""
    _reset_modules()
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from common.errors import InternalServerError  # noqa: PLC0415

        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        from api.rag.service import retrieve  # noqa: PLC0415

        provider = _StubProvider([0.1, 0.2])  # wrong dimension
        search_mock = AsyncMock()

        with (
            patch("api.rag.service.get_llm_config", new=AsyncMock(return_value=_StubConfig())),
            patch("api.rag.service.provider_for", return_value=provider),
            patch("api.rag.service.search_chunks", new=search_mock),
        ):
            with pytest.raises(InternalServerError) as exc_info:
                await retrieve(object(), _claims(), "hello", k=5)

    assert exc_info.value.code == "EMBEDDING_DIM_MISMATCH"
    search_mock.assert_not_awaited()
