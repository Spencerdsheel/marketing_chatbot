"""Unit tests for api.notifications.recipients.resolve_event_recipient (S9.2, Scope §2).

Covers (Decision 3):
- lead_id set -> resolves via leads.get_lead(...).email.
- lead_id unset, visitor_id set -> falls back to
  leads.get_lead_email_by_visitor_id(...).
- Neither yields an email -> None (no exception -- normal/expected case).
- Tenant isolation: a global caller (PLATFORM_ADMIN) raises ValidationError
  on get_event_contact / get_lead_email_by_visitor_id (mandatory).
"""
from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from common.auth import AuthClaims, Role
from common.errors import ValidationError

from api.notifications.recipients import NoRecipientError, resolve_event_recipient
from api.scheduling.repository import EventContact

_TENANT_ID = "tenant-recipients-test"
_NOW = datetime(2026, 7, 10, 12, 0, 0, tzinfo=UTC)


def _claims(tenant_id: str | None = _TENANT_ID, role: Role = Role.CLIENT_ADMIN) -> AuthClaims:
    return AuthClaims(subject="system:notifications", role=role, tenant_id=tenant_id)


def _contact(**overrides: object) -> EventContact:
    fields: dict[str, object] = {
        "lead_id": None,
        "visitor_id": "visitor-1",
        "timezone": "UTC",
        "starts_at": _NOW,
        "status": "booked",
    }
    fields.update(overrides)
    return EventContact(**fields)  # type: ignore[arg-type]


async def test_resolves_via_lead_id() -> None:
    contact = _contact(lead_id="lead-1", visitor_id=None)
    lead = AsyncMock()
    lead.email = "lead@example.com"

    with (
        patch("api.notifications.recipients.get_event_contact", AsyncMock(return_value=contact)),
        patch("api.notifications.recipients.get_lead", AsyncMock(return_value=lead)) as mock_get_lead,
        patch(
            "api.notifications.recipients.get_lead_email_by_visitor_id", AsyncMock()
        ) as mock_by_visitor,
    ):
        result = await resolve_event_recipient(object(), _claims(), "event-1")

    assert result == "lead@example.com"
    mock_get_lead.assert_awaited_once()
    mock_by_visitor.assert_not_called()


async def test_falls_back_to_visitor_id_when_no_lead_id() -> None:
    contact = _contact(lead_id=None, visitor_id="visitor-1")

    with (
        patch("api.notifications.recipients.get_event_contact", AsyncMock(return_value=contact)),
        patch(
            "api.notifications.recipients.get_lead_email_by_visitor_id",
            AsyncMock(return_value="visitor@example.com"),
        ) as mock_by_visitor,
    ):
        result = await resolve_event_recipient(object(), _claims(), "event-1")

    assert result == "visitor@example.com"
    mock_by_visitor.assert_awaited_once()


async def test_returns_none_when_no_lead_id_and_no_visitor_id() -> None:
    contact = _contact(lead_id=None, visitor_id=None)

    with patch("api.notifications.recipients.get_event_contact", AsyncMock(return_value=contact)):
        result = await resolve_event_recipient(object(), _claims(), "event-1")

    assert result is None


async def test_returns_none_when_lead_id_set_but_lead_missing() -> None:
    contact = _contact(lead_id="lead-missing", visitor_id=None)

    with (
        patch("api.notifications.recipients.get_event_contact", AsyncMock(return_value=contact)),
        patch("api.notifications.recipients.get_lead", AsyncMock(return_value=None)),
    ):
        result = await resolve_event_recipient(object(), _claims(), "event-1")

    assert result is None


async def test_returns_none_when_visitor_id_lookup_yields_no_email() -> None:
    contact = _contact(lead_id=None, visitor_id="visitor-no-lead")

    with (
        patch("api.notifications.recipients.get_event_contact", AsyncMock(return_value=contact)),
        patch(
            "api.notifications.recipients.get_lead_email_by_visitor_id", AsyncMock(return_value=None)
        ),
    ):
        result = await resolve_event_recipient(object(), _claims(), "event-1")

    assert result is None


async def test_returns_none_when_event_contact_missing() -> None:
    with patch("api.notifications.recipients.get_event_contact", AsyncMock(return_value=None)):
        result = await resolve_event_recipient(object(), _claims(), "event-missing")

    assert result is None


# ==============================================================================
# Tenant isolation (MANDATORY)
# ==============================================================================


async def test_global_caller_rejected() -> None:
    """A global caller (PLATFORM_ADMIN) must be rejected -- propagates from
    the underlying tenant-scoped getters (_reject_global)."""
    with pytest.raises(ValidationError):
        await resolve_event_recipient(object(), _claims(tenant_id=None, role=Role.PLATFORM_ADMIN), "event-1")


def test_no_recipient_error_is_validation_error_with_code() -> None:
    err = NoRecipientError("no contact")
    assert isinstance(err, ValidationError)
    assert err.code == "NO_RECIPIENT"
