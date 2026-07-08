"""Unit tests for api.crm.sync (CRMSync Protocol, ExternalRef, WebhookSync, crm_sync_for).

Covers:
- WebhookSync.upsert_lead POSTs to webhook_url with an HMAC-SHA256 X-Signature
  header, verifiable against the raw body with the shared secret.
- 2xx response -> ExternalRef(connector="webhook", status="ok").
- non-2xx / network error -> raises (Celery-retryable).
- crm_sync_for: "webhook" connector -> WebhookSync; unknown connector ->
  deterministic ValidationError (no raise-for-retry semantics -- caller decides).
- Webhook config missing webhook_url -> deterministic ValidationError.
"""
from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from common.errors import ValidationError

from api.crm.config_repository import CRMConfig
from api.crm.sync import ExternalRef, WebhookSync, crm_sync_for
from api.leads.repository import Lead

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _lead(**overrides: Any) -> Lead:
    base: dict[str, Any] = {
        "lead_id": "lead-1",
        "visitor_id": "visitor-1",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "phone": "+15551234567",
        "status": "new",
        "stage": "captured",
        "qualification_score": None,
        "consent": {"granted": True, "purpose": "contact", "text": "OK"},
        "assigned_agent_id": None,
        "source": "widget",
        "created_at": _NOW,
        "updated_at": _NOW,
    }
    base.update(overrides)
    return Lead(**base)


class _StubTransport(httpx.AsyncBaseTransport):
    """httpx transport double that records the request and returns a canned response."""

    def __init__(self, *, status_code: int = 200, raise_exc: Exception | None = None) -> None:
        self.status_code = status_code
        self.raise_exc = raise_exc
        self.captured_request: httpx.Request | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.captured_request = request
        if self.raise_exc is not None:
            raise self.raise_exc
        return httpx.Response(status_code=self.status_code, request=request)


async def _post_via_stub(monkeypatch: pytest.MonkeyPatch, transport: _StubTransport) -> None:
    """Patch httpx.AsyncClient construction inside api.crm.sync to use the stub transport."""
    import api.crm.sync as sync_mod

    original_client = httpx.AsyncClient

    def _client_factory(*args: Any, **kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("timeout", None)
        return original_client(transport=transport, timeout=5.0)

    monkeypatch.setattr(sync_mod.httpx, "AsyncClient", _client_factory)


# ==============================================================================
# WebhookSync.upsert_lead
# ==============================================================================


async def test_webhook_sync_posts_to_webhook_url_with_hmac_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = _StubTransport(status_code=200)
    await _post_via_stub(monkeypatch, transport)

    sync = WebhookSync(webhook_url="https://example.com/hook", secret="whsec_test")
    lead = _lead()

    ref = await sync.upsert_lead(claims=None, lead=lead)  # type: ignore[arg-type]

    assert isinstance(ref, ExternalRef)
    assert ref.connector == "webhook"
    assert ref.status == "ok"

    assert transport.captured_request is not None
    assert str(transport.captured_request.url) == "https://example.com/hook"
    signature = transport.captured_request.headers.get("x-signature")
    assert signature is not None

    body = transport.captured_request.content
    expected_signature = hmac.new(b"whsec_test", body, hashlib.sha256).hexdigest()
    assert signature == expected_signature


async def test_webhook_sync_2xx_returns_ok_status(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _StubTransport(status_code=201)
    await _post_via_stub(monkeypatch, transport)

    sync = WebhookSync(webhook_url="https://example.com/hook", secret="whsec_test")
    ref = await sync.upsert_lead(claims=None, lead=_lead())  # type: ignore[arg-type]

    assert ref.status == "ok"


async def test_webhook_sync_non_2xx_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _StubTransport(status_code=500)
    await _post_via_stub(monkeypatch, transport)

    sync = WebhookSync(webhook_url="https://example.com/hook", secret="whsec_test")

    with pytest.raises(Exception):  # noqa: B017 -- retryable transient error, type not part of contract
        await sync.upsert_lead(claims=None, lead=_lead())  # type: ignore[arg-type]


async def test_webhook_sync_network_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = _StubTransport(raise_exc=httpx.ConnectError("boom"))
    await _post_via_stub(monkeypatch, transport)

    sync = WebhookSync(webhook_url="https://example.com/hook", secret="whsec_test")

    with pytest.raises(Exception):  # noqa: B017 -- retryable transient error, type not part of contract
        await sync.upsert_lead(claims=None, lead=_lead())  # type: ignore[arg-type]


# ==============================================================================
# crm_sync_for
# ==============================================================================


def test_crm_sync_for_webhook_returns_webhook_sync() -> None:
    config = CRMConfig(connector="webhook", webhook_url="https://example.com/hook", secret="s", enabled=True)
    sync = crm_sync_for(config)
    assert isinstance(sync, WebhookSync)


def test_crm_sync_for_unknown_connector_raises_deterministic_error() -> None:
    config = CRMConfig(connector="hubspot", webhook_url=None, secret="s", enabled=True)
    with pytest.raises(ValidationError):
        crm_sync_for(config)


def test_crm_sync_for_webhook_missing_url_raises_deterministic_error() -> None:
    config = CRMConfig(connector="webhook", webhook_url=None, secret="s", enabled=True)
    with pytest.raises(ValidationError):
        crm_sync_for(config)
