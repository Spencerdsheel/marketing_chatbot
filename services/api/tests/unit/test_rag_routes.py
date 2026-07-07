"""Unit tests for POST /debug/rag/search.

Covers:
- CLIENT_ADMIN happy path -> 200, body has chunks[].{doc_id, chunk_id, content,
  score} + confidence + count, and NEVER tenant_id or the embedding.
- Non-CLIENT_ADMIN (CLIENT_AGENT) -> 403.
- No cookie -> 401.
- RAG_EMBEDDING_NOT_CONFIGURED (ValidationError) -> 422.
- LLMError from retrieve -> 502.
"""
from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

from common.auth import AuthClaims, Role
from common.cache import InMemoryCache
from common.errors import ValidationError
from httpx import ASGITransport, AsyncClient

from api.auth.tokens import create_access_token
from api.llm.provider import LLMError
from api.rag.repository import ChunkMatch
from api.rag.service import RetrievalResult

_TEST_JWT_SECRET = "x" * 48
_TENANT_ID = "tenant-abc-123"

_TEST_SETTINGS_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": _TEST_JWT_SECRET,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
}


class _StubDatabase:
    async def fetchrow(self, query: str, *args: object) -> dict[str, Any] | None:
        return None

    async def execute(self, query: str, *args: object) -> str:
        return "INSERT 1"

    async def close(self) -> None:
        pass


class _StubRedis:
    async def get(self, key: str) -> str | None:
        return None

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        pass

    async def getdel(self, key: str) -> str | None:
        return None

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        pass


def _build_app(db: Any = None) -> Any:
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_SETTINGS_ENV, clear=False):
        from api.app import create_app

        app = create_app()

    app.state.db = db if db is not None else _StubDatabase()
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    app.state.rate_limiter = None
    return app


def _mint_cookie(
    *,
    subject: str = "user-1",
    role: Role = Role.CLIENT_ADMIN,
    tenant_id: str | None = _TENANT_ID,
    ttl_seconds: int = 300,
    secret: str = _TEST_JWT_SECRET,
) -> str:
    claims = AuthClaims(subject=subject, role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=secret, ttl_seconds=ttl_seconds)
    return token


async def test_rag_search_client_admin_happy_path_returns_200_leak_free() -> None:
    app = _build_app()
    result = RetrievalResult(
        chunks=[
            ChunkMatch(doc_id="doc-1", chunk_id="doc-1-0000", content="hello world", score=0.87),
        ],
        confidence=0.87,
    )
    token = _mint_cookie(role=Role.CLIENT_ADMIN)

    with patch("api.rag.routes.retrieve", new=AsyncMock(return_value=result)):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/debug/rag/search",
                json={"query": "what can the ai agent do?"},
                cookies={"access_token": token},
            )

    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert body["confidence"] == 0.87
    assert body["chunks"] == [
        {"doc_id": "doc-1", "chunk_id": "doc-1-0000", "content": "hello world", "score": 0.87}
    ]
    # Leak-free: never tenant_id, never the embedding vector.
    body_str = str(body)
    assert "tenant_id" not in body_str
    assert "embedding" not in body_str
    assert _TENANT_ID not in body_str


async def test_rag_search_client_agent_returns_403() -> None:
    app = _build_app()
    token = _mint_cookie(role=Role.CLIENT_AGENT)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post(
            "/debug/rag/search",
            json={"query": "hello"},
            cookies={"access_token": token},
        )
    assert resp.status_code == 403


async def test_rag_search_no_cookie_returns_401() -> None:
    app = _build_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/debug/rag/search", json={"query": "hello"})
    assert resp.status_code == 401


async def test_rag_search_embedding_not_configured_returns_422() -> None:
    app = _build_app()
    token = _mint_cookie(role=Role.CLIENT_ADMIN)

    async def _raise(*args: object, **kwargs: object) -> RetrievalResult:
        raise ValidationError(
            "No embedding model is configured for this tenant.",
            code="RAG_EMBEDDING_NOT_CONFIGURED",
        )

    with patch("api.rag.routes.retrieve", side_effect=_raise):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/debug/rag/search",
                json={"query": "hello"},
                cookies={"access_token": token},
            )

    assert resp.status_code == 422
    assert resp.json()["error_code"] == "RAG_EMBEDDING_NOT_CONFIGURED"


async def test_rag_search_llm_error_returns_502() -> None:
    app = _build_app()
    token = _mint_cookie(role=Role.CLIENT_ADMIN)

    async def _raise(*args: object, **kwargs: object) -> RetrievalResult:
        raise LLMError("upstream failed")

    with patch("api.rag.routes.retrieve", side_effect=_raise):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            resp = await c.post(
                "/debug/rag/search",
                json={"query": "hello"},
                cookies={"access_token": token},
            )

    assert resp.status_code == 502
    assert resp.json()["error_code"] == "LLM_ERROR"
