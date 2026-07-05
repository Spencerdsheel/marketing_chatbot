"""Unit tests for api.ingestion.routes.

Uses ASGI test client + stub DB + stub storage + mocked task .delay().

Covers:
- POST /admin/ingestion/upload:
  - txt upload → 200 {doc_id, run_id, status:"pending"}, task enqueued.
  - docx upload → 200, task enqueued.
  - correlation_id propagated to ingest_document.delay().
  - Idempotent re-upload (same bytes) → same doc_id, .delay NOT called again.
  - File too large → 413.
  - Unsupported content type → 422 UNSUPPORTED_CONTENT_TYPE.
  - CLIENT_AGENT → 403.
  - No cookie → 401.
- GET /admin/ingestion/docs/{doc_id}:
  - 200 shape: contains doc_id, filename, content_type, status, content_hash,
    latest_run, parsed_preview; does NOT contain tenant_id or storage_key.
  - Missing doc → 404 DOC_NOT_FOUND.
"""
from __future__ import annotations

import io
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock, patch

from common.auth import AuthClaims, Role
from common.cache import InMemoryCache
from httpx import ASGITransport, AsyncClient

_TEST_ENV = {
    "DEPLOYMENT_MODE": "saas",
    "DATABASE_URL": "postgres://stub-host:5432/appdb",
    "REDIS_URL": "redis://stub-host:6379",
    "JWT_SECRET": "x" * 48,
    "SECRET_ENCRYPTION_KEY": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=",
    "SERVICE_NAME": "api",
    "LOG_LEVEL": "WARNING",
    "COOKIE_SECURE": "false",
    "STORAGE_BACKEND": "local",
    "STORAGE_LOCAL_ROOT": "/tmp/test-ingestion-routes",
}

_TENANT_ID = "tenant-route-ingestion"
_DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Stub database
# ---------------------------------------------------------------------------


class _StubDatabase:
    def __init__(self) -> None:
        self._docs: dict[tuple[str, str], dict[str, Any]] = {}
        self._runs: dict[tuple[str, str], dict[str, Any]] = {}
        self._hashes: dict[tuple[str, str], str] = {}  # (tenant_id, hash) -> doc_id

    async def execute(self, query: str, *args: Any) -> str:
        q = query.strip().upper()
        if "INSERT INTO KNOWLEDGE_DOCS" in q:
            tenant_id, doc_id, source, filename, content_type, status, content_hash, storage_key = args
            self._docs[(tenant_id, doc_id)] = {
                "doc_id": doc_id,
                "source": source,
                "filename": filename,
                "content_type": content_type,
                "status": status,
                "content_hash": content_hash,
                "storage_key": storage_key,
                "created_at": _NOW,
                "updated_at": _NOW,
                "tenant_id": tenant_id,
            }
            self._hashes[(tenant_id, content_hash)] = doc_id
            return "INSERT 0 1"

        if "UPDATE KNOWLEDGE_DOCS" in q:
            new_status, tenant_id, doc_id = args[0], args[-2], args[-1]
            key = (str(tenant_id), str(doc_id))
            if key in self._docs:
                self._docs[key] = {**self._docs[key], "status": new_status, "updated_at": _NOW}
            return "UPDATE 1"

        if "INSERT INTO INGESTION_RUNS" in q:
            tenant_id, run_id, doc_id, status = args
            self._runs[(tenant_id, run_id)] = {
                "run_id": run_id,
                "doc_id": doc_id,
                "status": status,
                "chars_out": None,
                "errors": None,
                "started_at": _NOW,
                "finished_at": None,
                "duration_ms": None,
                "tenant_id": tenant_id,
            }
            return "INSERT 0 1"

        if "UPDATE INGESTION_RUNS" in q:
            return "UPDATE 1"

        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        q = query.upper()

        if "FROM KNOWLEDGE_DOCS" in q and "AND CONTENT_HASH" in q:
            # find_doc_by_hash — WHERE ... AND content_hash = $2
            tenant_id, content_hash = args[0], args[1]
            doc_id = self._hashes.get((str(tenant_id), str(content_hash)))
            if doc_id is None:
                return None
            return self._docs.get((str(tenant_id), str(doc_id)))

        if "FROM KNOWLEDGE_DOCS" in q:
            # get_doc or re-fetch after create — WHERE ... AND doc_id = $2
            tenant_id, doc_id = args[0], args[1]
            return self._docs.get((str(tenant_id), str(doc_id)))

        if "FROM INGESTION_RUNS" in q and "LIMIT 1" in q:
            tenant_id, doc_id = args[0], args[1]
            candidates = [
                r for (tid, _), r in self._runs.items()
                if tid == tenant_id and r["doc_id"] == doc_id
            ]
            if not candidates:
                return None
            return max(candidates, key=lambda r: (r["started_at"], r["run_id"]))

        if "FROM INGESTION_RUNS" in q:
            tenant_id, run_id = args[0], args[1]
            return self._runs.get((tenant_id, run_id))

        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return []

    async def fetchval(self, query: str, *args: Any) -> Any:
        return None

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Stub storage
# ---------------------------------------------------------------------------


class _InMemoryStorage:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def put(self, key: str, data: bytes) -> None:
        self._store[key] = data

    def get(self, key: str) -> bytes:
        if key not in self._store:
            raise FileNotFoundError(key)
        return self._store[key]

    def exists(self, key: str) -> bool:
        return key in self._store

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_modules() -> None:
    """Clear the settings caches so the next ``create_app`` re-reads the patched env.

    NOTE: this must NOT delete ``api.config`` from ``sys.modules``. Doing so
    creates a *second* config module while ``api.app`` (and other already-imported
    modules) stay bound to the ORIGINAL one — ``create_app`` then caches settings
    on the original module, while this test's ``cache_clear`` targets the reimported
    one, leaving stale limits that poison later tests (rate-limiting/password-reset).
    Clearing the caches on the single, shared config module is sufficient and safe.
    """
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


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

    def pipeline(self, transaction: bool = False) -> _StubPipeline:
        return _StubPipeline()


class _StubPipeline:
    def zremrangebyscore(self, key: str, min_score: float, max_score: float) -> None:
        pass

    def zadd(self, key: str, mapping: dict[str, float]) -> None:
        pass

    def zcard(self, key: str) -> None:
        pass

    def expire(self, key: str, seconds: int) -> None:
        pass

    async def execute(self) -> list[Any]:
        return [0, None, 0, True]


def _build_app(stub_db: _StubDatabase) -> Any:
    from api.config import get_api_settings

    get_api_settings.cache_clear()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.app import create_app

        app = create_app()

    app.state.db = stub_db
    app.state.redis = _StubRedis()
    app.state.cache = InMemoryCache()
    app.state.rate_limiter = None
    return app


def _mint_cookie(
    *,
    role: Role = Role.CLIENT_ADMIN,
    tenant_id: str | None = _TENANT_ID,
    secret: str = "x" * 48,
) -> str:
    from api.auth.tokens import create_access_token

    claims = AuthClaims(subject="user-1", role=role, tenant_id=tenant_id)
    token, _ = create_access_token(claims, secret=secret, ttl_seconds=300)
    return token


def _make_txt_upload(content: bytes = b"hello document") -> tuple[bytes, str]:
    return content, "text/plain"


def _make_docx_upload() -> tuple[bytes, str]:
    """Build a minimal docx fixture in-memory."""
    from docx import Document  # type: ignore[import-untyped]

    doc = Document()
    doc.add_paragraph("Docx content for testing.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue(), _DOCX_MIME


# ==============================================================================
# POST /admin/ingestion/upload — success paths
# ==============================================================================


async def test_upload_txt_returns_200_with_pending_status() -> None:
    """txt upload → 200 with {doc_id, run_id, status:'pending'}."""
    _reset_modules()

    stub_db = _StubDatabase()
    stub_storage = _InMemoryStorage()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie()

        with (
            patch("api.ingestion.routes.ingest_document") as mock_task,
            patch("api.ingestion.routes.get_storage", return_value=stub_storage),
        ):
            mock_delay = MagicMock()
            mock_delay.id = "task-id-1"
            mock_task.delay = MagicMock(return_value=mock_delay)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/admin/ingestion/upload",
                    cookies={"access_token": token},
                    files={"file": ("sample.txt", b"hello document", "text/plain")},
                )

    assert resp.status_code == 200
    body = resp.json()
    assert "doc_id" in body
    assert "run_id" in body
    assert body["status"] == "pending"
    assert mock_task.delay.called


async def test_upload_docx_returns_200() -> None:
    """docx upload → 200 with {doc_id, run_id, status:'pending'}."""
    _reset_modules()

    stub_db = _StubDatabase()
    stub_storage = _InMemoryStorage()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie()
        docx_bytes, _ = _make_docx_upload()

        with (
            patch("api.ingestion.routes.ingest_document") as mock_task,
            patch("api.ingestion.routes.get_storage", return_value=stub_storage),
        ):
            mock_delay = MagicMock()
            mock_delay.id = "task-id-docx"
            mock_task.delay = MagicMock(return_value=mock_delay)

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/admin/ingestion/upload",
                    cookies={"access_token": token},
                    files={"file": ("sample.docx", docx_bytes, _DOCX_MIME)},
                )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "pending"


async def test_upload_passes_correlation_id_to_delay() -> None:
    """The route must pass the request correlation_id to ingest_document.delay()."""
    _reset_modules()

    stub_db = _StubDatabase()
    stub_storage = _InMemoryStorage()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie()

        with (
            patch("api.ingestion.routes.ingest_document") as mock_task,
            patch("api.ingestion.routes.get_storage", return_value=stub_storage),
        ):
            mock_delay = MagicMock(return_value=MagicMock(id="task-cid"))
            mock_task.delay = mock_delay

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/admin/ingestion/upload",
                    cookies={"access_token": token},
                    files={"file": ("f.txt", b"correlation test", "text/plain")},
                    headers={"x-correlation-id": "expected-cid"},
                )

    assert resp.status_code == 200
    call_kwargs = mock_delay.call_args.kwargs
    assert call_kwargs.get("correlation_id") == "expected-cid"


# ==============================================================================
# Idempotent re-upload
# ==============================================================================


async def test_upload_idempotent_same_bytes_returns_existing_doc_id() -> None:
    """Re-uploading the same bytes returns the same doc_id; .delay NOT called again."""
    _reset_modules()

    stub_db = _StubDatabase()
    stub_storage = _InMemoryStorage()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie()
        content = b"idempotent content"

        delay_call_count = 0

        with (
            patch("api.ingestion.routes.ingest_document") as mock_task,
            patch("api.ingestion.routes.get_storage", return_value=stub_storage),
        ):
            def _counting_delay(**kwargs: Any) -> MagicMock:
                nonlocal delay_call_count
                delay_call_count += 1
                m = MagicMock()
                m.id = "task-idem"
                return m

            mock_task.delay = _counting_delay

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp1 = await client.post(
                    "/admin/ingestion/upload",
                    cookies={"access_token": token},
                    files={"file": ("idem.txt", content, "text/plain")},
                )
                doc_id_first = resp1.json()["doc_id"]

                resp2 = await client.post(
                    "/admin/ingestion/upload",
                    cookies={"access_token": token},
                    files={"file": ("idem.txt", content, "text/plain")},
                )
                doc_id_second = resp2.json()["doc_id"]

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert doc_id_first == doc_id_second, "Same content must return the same doc_id"
    assert delay_call_count == 1, ".delay must be called only once (not on re-upload)"


# ==============================================================================
# Negative cases — upload
# ==============================================================================


async def test_upload_oversize_returns_413() -> None:
    """A file larger than ingestion_max_upload_bytes → 413."""
    _reset_modules()

    stub_db = _StubDatabase()

    # Tiny limit for this test.
    env = {**_TEST_ENV, "INGESTION_MAX_UPLOAD_BYTES": "10"}
    with patch.dict("os.environ", env, clear=False):
        from api.config import get_api_settings

        get_api_settings.cache_clear()

        app = _build_app(stub_db)
        token = _mint_cookie()

        with patch("api.ingestion.routes.ingest_document"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/admin/ingestion/upload",
                    cookies={"access_token": token},
                    files={"file": ("big.txt", b"x" * 20, "text/plain")},
                )

    assert resp.status_code == 413


async def test_upload_unsupported_content_type_returns_422() -> None:
    """Unsupported content type → 422 UNSUPPORTED_CONTENT_TYPE."""
    _reset_modules()

    stub_db = _StubDatabase()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie()

        with patch("api.ingestion.routes.ingest_document"):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/admin/ingestion/upload",
                    cookies={"access_token": token},
                    files={"file": ("photo.png", b"\x89PNG", "image/png")},
                )

    assert resp.status_code == 422
    assert resp.json()["error_code"] == "UNSUPPORTED_CONTENT_TYPE"


async def test_upload_client_agent_returns_403() -> None:
    """CLIENT_AGENT → 403."""
    _reset_modules()

    stub_db = _StubDatabase()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie(role=Role.CLIENT_AGENT)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/ingestion/upload",
                cookies={"access_token": token},
                files={"file": ("f.txt", b"data", "text/plain")},
            )

    assert resp.status_code == 403


async def test_upload_no_cookie_returns_401() -> None:
    """No cookie → 401."""
    _reset_modules()

    stub_db = _StubDatabase()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/admin/ingestion/upload",
                files={"file": ("f.txt", b"data", "text/plain")},
            )

    assert resp.status_code == 401


# ==============================================================================
# GET /admin/ingestion/docs/{doc_id}
# ==============================================================================


async def test_get_doc_returns_shape_without_tenant_id_or_storage_key() -> None:
    """GET /docs/{doc_id} → 200 with correct fields; no tenant_id or storage_key."""
    _reset_modules()

    stub_db = _StubDatabase()
    stub_storage = _InMemoryStorage()

    # Pre-populate DB and storage with a doc + run + parsed.txt.
    doc_id = "doc-get-test"
    storage_key = f"{_TENANT_ID}/{doc_id}/sample.txt"
    parsed_key = f"{_TENANT_ID}/{doc_id}/parsed.txt"
    stub_db._docs[(_TENANT_ID, doc_id)] = {
        "doc_id": doc_id,
        "source": "upload",
        "filename": "sample.txt",
        "content_type": "text/plain",
        "status": "parsed",
        "content_hash": "sha256-abc",
        "storage_key": storage_key,
        "created_at": _NOW,
        "updated_at": _NOW,
        "tenant_id": _TENANT_ID,
    }
    stub_db._runs[(_TENANT_ID, "run-get-test")] = {
        "run_id": "run-get-test",
        "doc_id": doc_id,
        "status": "succeeded",
        "chars_out": 42,
        "errors": None,
        "started_at": _NOW,
        "finished_at": _NOW,
        "duration_ms": 100,
        "tenant_id": _TENANT_ID,
    }
    stub_storage.put(parsed_key, b"Hello parsed content.")

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie()

        with patch("api.ingestion.routes.get_storage", return_value=stub_storage):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(
                    f"/admin/ingestion/docs/{doc_id}",
                    cookies={"access_token": token},
                )

    assert resp.status_code == 200
    body = resp.json()

    # Required fields.
    assert body["doc_id"] == doc_id
    assert "filename" in body
    assert "content_type" in body
    assert "status" in body
    assert "content_hash" in body
    assert "latest_run" in body
    assert "parsed_preview" in body

    # Must NOT expose internal fields.
    assert "tenant_id" not in body
    assert "storage_key" not in body

    # Latest run shape.
    run = body["latest_run"]
    assert run["status"] == "succeeded"
    assert run["chars_out"] == 42

    # Parsed preview.
    assert body["parsed_preview"] is not None
    assert "Hello" in body["parsed_preview"]


async def test_get_doc_missing_returns_404() -> None:
    """GET /docs/{doc_id} for a nonexistent doc → 404 DOC_NOT_FOUND."""
    _reset_modules()

    stub_db = _StubDatabase()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie()

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/admin/ingestion/docs/does-not-exist",
                cookies={"access_token": token},
            )

    assert resp.status_code == 404
    assert resp.json()["error_code"] == "DOC_NOT_FOUND"


async def test_get_doc_no_cookie_returns_401() -> None:
    """GET /docs/{doc_id} without a cookie → 401."""
    _reset_modules()

    stub_db = _StubDatabase()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/admin/ingestion/docs/any-id")

    assert resp.status_code == 401


async def test_get_doc_client_agent_returns_403() -> None:
    """GET /docs/{doc_id} with CLIENT_AGENT → 403."""
    _reset_modules()

    stub_db = _StubDatabase()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie(role=Role.CLIENT_AGENT)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/admin/ingestion/docs/any-id",
                cookies={"access_token": token},
            )

    assert resp.status_code == 403


# ==============================================================================
# Regression: upload at INFO log level must not crash (reserved 'filename' key)
# ==============================================================================


async def test_upload_at_info_log_level_returns_200_not_500() -> None:
    """Regression: POST /upload with LOG_LEVEL=INFO must return 200, not 500.

    The original bug: the route passed ``filename`` (a reserved LogRecord
    attribute) in ``extra=``, causing ``logging.makeRecord`` to raise
    ``KeyError: "Attempt to overwrite 'filename' in LogRecord"`` at INFO level.
    Tests ran with LOG_LEVEL=WARNING so ``isEnabledFor(INFO)`` short-circuited
    before makeRecord — hiding the crash from CI. Live deploys used INFO → 500
    on every upload.

    This test forces LOG_LEVEL=INFO so the logger actually calls makeRecord and
    would have surfaced the crash before the hardening fix.
    """
    import logging as _logging

    _reset_modules()

    # Override LOG_LEVEL to INFO to exercise the makeRecord path.
    env_info = {**_TEST_ENV, "LOG_LEVEL": "INFO"}

    stub_db = _StubDatabase()
    stub_storage = _InMemoryStorage()

    with patch.dict("os.environ", env_info, clear=False):
        app = _build_app(stub_db)
        token = _mint_cookie()

        # Also set the ingestion route logger to INFO at the Python level to
        # guarantee makeRecord is called even if settings propagation is delayed.
        route_logger = _logging.getLogger("api.ingestion.routes")
        prev_level = route_logger.level
        route_logger.setLevel(_logging.INFO)

        try:
            with (
                patch("api.ingestion.routes.ingest_document") as mock_task,
                patch("api.ingestion.routes.get_storage", return_value=stub_storage),
            ):
                mock_task.delay = MagicMock(return_value=MagicMock(id="task-info"))

                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(
                        "/admin/ingestion/upload",
                        cookies={"access_token": token},
                        files={"file": ("report.txt", b"content for info test", "text/plain")},
                    )
        finally:
            route_logger.setLevel(prev_level)

    # Would have been 500 (KeyError from makeRecord) without the fix.
    assert resp.status_code == 200, (
        f"Expected 200 at INFO log level — got {resp.status_code}. "
        "This indicates the reserved-key crash in makeRecord is NOT fixed."
    )
    body = resp.json()
    assert body["status"] == "pending"
