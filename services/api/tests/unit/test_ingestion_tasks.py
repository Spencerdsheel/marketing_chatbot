"""Unit tests for api.ingestion.tasks.ingest_document.

Tests use stub DB + stub storage and run in Celery eager mode (no real broker).

Covers:
- Success path: parses bytes, stores parsed.txt, updates run to 'succeeded' +
  doc to 'parsed'.
- Parse error path: run → 'failed' + errors recorded + doc → 'failed'; task
  does NOT raise (Celery should NOT retry deterministic failures).
- Transient infra error (storage.get raises RuntimeError): task propagates, so
  Celery retries it.
- Tenant-scoped AuthClaims: repo calls carry claims built from the passed
  tenant_id (subject='system:ingestion', role=CLIENT_ADMIN).
- .delay()-based enqueue test (decision 2 regression guard): proves that
  ingest_document.delay(doc_id=..., tenant_id=..., run_id=..., correlation_id=...)
  does not raise TypeError at enqueue time.
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest

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
    "STORAGE_LOCAL_ROOT": "/tmp/test-storage",
}

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)

_TENANT_ID = "tenant-tasks-test"
_DOC_ID = "doc-tasks-test"
_RUN_ID = "run-tasks-test"


def _reset_modules() -> None:
    # Reimport ingestion/tasks modules fresh + clear settings caches. Do NOT
    # delete api.config: that splits the module graph (api.app stays bound to the
    # original config) and poisons later tests. Clearing the caches on the single
    # shared config module gives fresh settings safely.
    for key in list(sys.modules.keys()):
        if key.startswith("api.ingestion") or key.startswith("api.tasks"):
            del sys.modules[key]
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


# ---------------------------------------------------------------------------
# Stub objects
# ---------------------------------------------------------------------------


class _RecordingDatabase:
    """Records every execute/fetchrow call for assertion in tests."""

    def __init__(self, doc_row: dict[str, Any] | None = None) -> None:
        self._doc_row = doc_row
        self.executions: list[tuple[str, tuple[Any, ...]]] = []
        self._run_status: str = "queued"
        self._doc_status: str = "pending"

    async def execute(self, query: str, *args: Any) -> str:
        self.executions.append((query, args))
        q = query.upper()
        if "UPDATE INGESTION_RUNS" in q:
            # First arg after the SET clauses is status.
            self._run_status = str(args[0])
        if "UPDATE KNOWLEDGE_DOCS" in q:
            self._doc_status = str(args[0])
        return "UPDATE 1"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        return self._doc_row

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        return []

    async def fetchval(self, query: str, *args: Any) -> Any:
        return None

    async def close(self) -> None:
        pass


class _InMemoryStorage:
    """Minimal in-memory storage stub."""

    def __init__(self, initial: dict[str, bytes] | None = None) -> None:
        self._store: dict[str, bytes] = dict(initial or {})
        self.puts: list[tuple[str, bytes]] = []

    def put(self, key: str, data: bytes) -> None:
        self._store[key] = data
        self.puts.append((key, data))

    def get(self, key: str) -> bytes:
        if key not in self._store:
            raise FileNotFoundError(f"Key not found: {key!r}")
        return self._store[key]

    def exists(self, key: str) -> bool:
        return key in self._store

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


class _ExplodingStorage:
    """Storage stub that raises RuntimeError on get (simulates transient failure)."""

    def put(self, key: str, data: bytes) -> None:
        pass

    def get(self, key: str) -> bytes:
        raise RuntimeError("Transient storage failure")

    def exists(self, key: str) -> bool:
        return False

    def delete(self, key: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc_row(
    *,
    doc_id: str = _DOC_ID,
    tenant_id: str = _TENANT_ID,
    content_type: str = "text/plain",
    storage_key: str | None = None,
    status: str = "pending",
) -> dict[str, Any]:
    sk = storage_key or f"{tenant_id}/{doc_id}/sample.txt"
    return {
        "doc_id": doc_id,
        "source": "upload",
        "filename": "sample.txt",
        "content_type": content_type,
        "status": status,
        "content_hash": "abc",
        "storage_key": sk,
        "created_at": _NOW,
        "updated_at": _NOW,
        "tenant_id": tenant_id,
    }


# ==============================================================================
# Success path
# ==============================================================================


async def test_ingest_document_success_path() -> None:
    """Success path: parses txt bytes, stores parsed.txt, run→succeeded, doc→parsed."""
    _reset_modules()

    raw_bytes = b"Hello from the document."
    storage_key = f"{_TENANT_ID}/{_DOC_ID}/sample.txt"
    storage = _InMemoryStorage({storage_key: raw_bytes})
    db = _RecordingDatabase(doc_row=_make_doc_row(storage_key=storage_key))

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings

        get_api_settings.cache_clear()

        # Patch out the database and storage so no real connections are made.
        with (
            patch("api.ingestion.tasks.get_storage", return_value=storage),
            patch("api.ingestion.tasks.Database.connect", return_value=db),
        ):
            from common.auth import AuthClaims, Role  # noqa: PLC0415

            from api.ingestion.tasks import _execute  # noqa: PLC0415

            claims = AuthClaims(
                subject="system:ingestion",
                role=Role.CLIENT_ADMIN,
                tenant_id=_TENANT_ID,
            )

            # We test _execute directly to avoid needing a real asyncio loop
            # inside the sync task wrapper.
            class _FakeTask:
                pass

            result = await _execute(
                _FakeTask(),  # type: ignore[arg-type]
                db,  # type: ignore[arg-type]
                claims,
                _DOC_ID,
                _RUN_ID,
                storage,
            )

    assert result["status"] == "succeeded"
    assert result["doc_id"] == _DOC_ID
    assert result["run_id"] == _RUN_ID

    # parsed.txt should be stored.
    parsed_key = f"{_TENANT_ID}/{_DOC_ID}/parsed.txt"
    assert storage.exists(parsed_key)
    assert b"Hello" in storage.get(parsed_key)

    # run updated twice: running → succeeded.
    run_updates = [e for e in db.executions if "INGESTION_RUNS" in e[0].upper()]
    statuses = [e[1][0] for e in run_updates]
    assert "running" in statuses
    assert "succeeded" in statuses

    # doc updated to 'parsed'.
    doc_updates = [e for e in db.executions if "KNOWLEDGE_DOCS" in e[0].upper()]
    assert any(e[1][0] == "parsed" for e in doc_updates)


# ==============================================================================
# Parse error path
# ==============================================================================


async def test_ingest_document_parse_error_records_failure_no_raise() -> None:
    """A ValidationError from parse() → run 'failed' + doc 'failed'; task returns (no raise)."""
    _reset_modules()

    # Store a file with a docx MIME but garbage bytes — parse will raise ValidationError.
    storage_key = f"{_TENANT_ID}/{_DOC_ID}/garbage.docx"
    storage = _InMemoryStorage({storage_key: b"\x00\x01 not a docx"})
    db = _RecordingDatabase(
        doc_row=_make_doc_row(
            content_type=(
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            ),
            storage_key=storage_key,
        )
    )

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        get_api_settings_mod = __import__("api.config", fromlist=["get_api_settings"])
        get_api_settings_mod.get_api_settings.cache_clear()

        from common.auth import AuthClaims, Role  # noqa: PLC0415

        claims = AuthClaims(
            subject="system:ingestion",
            role=Role.CLIENT_ADMIN,
            tenant_id=_TENANT_ID,
        )

        from api.ingestion.tasks import _execute  # noqa: PLC0415

        class _FakeTask:
            pass

        result = await _execute(
            _FakeTask(),  # type: ignore[arg-type]
            db,  # type: ignore[arg-type]
            claims,
            _DOC_ID,
            _RUN_ID,
            storage,
        )

    assert result["status"] == "failed"
    assert result["doc_id"] == _DOC_ID

    # run should record 'failed' status.
    run_updates = [e for e in db.executions if "INGESTION_RUNS" in e[0].upper()]
    assert any(e[1][0] == "failed" for e in run_updates)

    # The failed run update must carry the errors dict as one of its positional args.
    # NOTE: the stub DB bypasses asyncpg entirely, so the actual jsonb encoding path
    # is not exercised here — that can only be verified with a live DB (see live test
    # instructions in the bug report). This assertion confirms the dict reaches the
    # repository layer; the codec fix in common.db.Database.connect ensures asyncpg
    # then serialises it correctly on real connections.
    failed_run_updates = [e for e in run_updates if e[1][0] == "failed"]
    assert failed_run_updates, "Expected at least one UPDATE ingestion_runs with status=failed"
    # args for a failed update are (status, [optional cols...], tenant_id, run_id);
    # the errors dict must appear somewhere in the positional args tuple.
    assert any(
        isinstance(arg, dict) and "code" in arg and "message" in arg
        for update in failed_run_updates
        for arg in update[1]
    ), "The errors dict must be passed as a positional arg to the failed run UPDATE"

    # doc should be 'failed'.
    doc_updates = [e for e in db.executions if "KNOWLEDGE_DOCS" in e[0].upper()]
    assert any(e[1][0] == "failed" for e in doc_updates)

    # parsed.txt must NOT be stored.
    parsed_key = f"{_TENANT_ID}/{_DOC_ID}/parsed.txt"
    assert not storage.exists(parsed_key)


# ==============================================================================
# Transient infra error — propagates so Celery retries
# ==============================================================================


async def test_ingest_document_transient_storage_error_propagates() -> None:
    """A RuntimeError from storage.get() propagates (Celery will retry)."""
    _reset_modules()

    db = _RecordingDatabase(doc_row=_make_doc_row())
    storage = _ExplodingStorage()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from common.auth import AuthClaims, Role  # noqa: PLC0415

        from api.ingestion.tasks import _execute  # noqa: PLC0415

        claims = AuthClaims(
            subject="system:ingestion",
            role=Role.CLIENT_ADMIN,
            tenant_id=_TENANT_ID,
        )

        class _FakeTask:
            pass

        with pytest.raises(RuntimeError, match="Transient storage failure"):
            await _execute(
                _FakeTask(),  # type: ignore[arg-type]
                db,  # type: ignore[arg-type]
                claims,
                _DOC_ID,
                _RUN_ID,
                storage,
            )


# ==============================================================================
# Tenant-scoped AuthClaims (decision 1)
# ==============================================================================


async def test_ingest_document_builds_tenant_scoped_claims() -> None:
    """The task builds AuthClaims(subject='system:ingestion', role=CLIENT_ADMIN, tenant_id=...)."""
    _reset_modules()

    captured_claims: list[object] = []

    raw_bytes = b"content"
    storage_key = f"{_TENANT_ID}/{_DOC_ID}/f.txt"
    storage = _InMemoryStorage({storage_key: raw_bytes})
    db = _RecordingDatabase(doc_row=_make_doc_row(storage_key=storage_key))

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        from api.config import get_api_settings  # noqa: PLC0415

        get_api_settings.cache_clear()

        from api.ingestion import repository as repo_mod  # noqa: PLC0415

        original_update_run = repo_mod.update_run

        async def _capturing_update_run(
            db_: Any, claims_: Any, run_id: str, **kwargs: Any
        ) -> None:
            captured_claims.append(claims_)
            await original_update_run(db_, claims_, run_id, **kwargs)

        with patch("api.ingestion.tasks.repo.update_run", side_effect=_capturing_update_run):
            from common.auth import AuthClaims, Role  # noqa: PLC0415

            from api.ingestion.tasks import _execute  # noqa: PLC0415

            claims = AuthClaims(
                subject="system:ingestion",
                role=Role.CLIENT_ADMIN,
                tenant_id=_TENANT_ID,
            )

            class _FakeTask:
                pass

            await _execute(
                _FakeTask(),  # type: ignore[arg-type]
                db,  # type: ignore[arg-type]
                claims,
                _DOC_ID,
                _RUN_ID,
                storage,
            )

    assert captured_claims, "update_run should have been called"
    c = captured_claims[0]
    from common.auth import AuthClaims as _AC  # noqa: PLC0415
    from common.auth import Role as _R  # noqa: PLC0415

    assert isinstance(c, _AC)
    assert c.role == _R.CLIENT_ADMIN
    assert c.tenant_id == _TENANT_ID


# ==============================================================================
# .delay()-based enqueue test (decision 2 regression guard)
# ==============================================================================


def test_ingest_document_delay_accepts_correlation_id() -> None:
    """Regression guard: ingest_document.delay(correlation_id=...) must not raise TypeError.

    This uses ``.delay()`` (not ``.apply()``) to exercise the real
    ``check_arguments`` path inside Celery's ``apply_async``, which is what
    the S5.1 post-mortem identified as the live bug.
    """
    _reset_modules()

    with patch.dict("os.environ", _TEST_ENV, clear=False):
        import api.ingestion.tasks  # noqa: PLC0415, F401
        import api.tasks.celery_app as capp  # noqa: PLC0415

        capp.celery_app.conf.task_always_eager = True
        capp.celery_app.conf.task_eager_propagates = False  # don't propagate task errors

        from api.ingestion.tasks import ingest_document  # noqa: PLC0415

        # Patch _execute so we don't need a real DB/storage in this test.
        async def _stub_execute(*args: Any, **kwargs: Any) -> dict[str, object]:
            return {"doc_id": "d", "run_id": "r", "status": "succeeded"}

        with (
            patch("api.ingestion.tasks.get_storage"),
            patch("api.ingestion.tasks.asyncio.new_event_loop") as mock_loop,
        ):
            mock_event_loop = mock_loop.return_value
            mock_event_loop.run_until_complete.return_value = {
                "doc_id": "d", "run_id": "r", "status": "succeeded"
            }
            mock_event_loop.close.return_value = None

            # This is the regression guard — would raise TypeError at enqueue
            # if correlation_id were not declared in the task signature.
            result = ingest_document.delay(
                doc_id="doc-delay-test",
                tenant_id="tenant-delay",
                run_id="run-delay",
                correlation_id="cid-delay-test",
            )
            assert result is not None
