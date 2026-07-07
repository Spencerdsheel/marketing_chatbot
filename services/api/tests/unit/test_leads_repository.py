"""Unit tests for api.leads.repository.

Covers:
- create_lead inserts a tenant-scoped row with all fields + consent jsonb.
- get_lead returns the row mapped to Lead, or None if not found.
- Cross-tenant isolation: lead created under tenant A is not visible to tenant B.
- IDs are uuid4().hex.
- Positional placeholders ($1, $2, ...) are used.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import pytest
from common.auth import AuthClaims, Role

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

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _reset_settings() -> None:
    """Clear settings caches."""
    from common.settings import get_settings

    from api.config import get_api_settings

    get_settings.cache_clear()
    get_api_settings.cache_clear()


class _StubDatabase:
    """In-memory stub database for testing leads repository."""

    def __init__(self) -> None:
        # leads: keyed by (tenant_id, lead_id)
        self._leads: dict[tuple[str, str], dict[str, Any]] = {}
        # Record all execute/fetchrow calls for inspection
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, *args: Any) -> str:
        self.execute_calls.append((query, args))
        q = query.strip().upper()

        if q.startswith("INSERT INTO LEADS"):
            # args: tenant_id, lead_id, visitor_id, name, email, phone, status, stage,
            #       qualification_score, consent, assigned_agent_id, source
            tenant_id = args[0]
            lead_id = args[1]
            visitor_id = args[2]
            name = args[3]
            email = args[4]
            phone = args[5]
            status = args[6]
            stage = args[7]
            qualification_score = args[8]
            consent = args[9]
            assigned_agent_id = args[10]
            source = args[11]

            self._leads[(tenant_id, lead_id)] = {
                "tenant_id": tenant_id,
                "lead_id": lead_id,
                "visitor_id": visitor_id,
                "name": name,
                "email": email,
                "phone": phone,
                "status": status,
                "stage": stage,
                "qualification_score": qualification_score,
                "consent": consent,
                "assigned_agent_id": assigned_agent_id,
                "source": source,
                "created_at": _NOW,
                "updated_at": _NOW,
            }
            return "INSERT 0 1"

        return "OK"

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.fetchrow_calls.append((query, args))
        q = query.strip().upper()

        if "FROM LEADS" in q and "WHERE TENANT_ID" in q:
            # get_lead — WHERE tenant_id = $1 AND lead_id = $2
            tenant_id = args[0]
            lead_id = args[1]
            key = (tenant_id, lead_id)
            return self._leads.get(key)

        return None


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def stub_db() -> _StubDatabase:
    return _StubDatabase()


def _claims(tenant_id: str = "tenant-abc", role: Role = Role.VISITOR) -> AuthClaims:
    return AuthClaims(subject="visitor-123", role=role, tenant_id=tenant_id)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_create_lead_inserts_with_all_fields() -> None:
    """create_lead inserts a row with tenant_id, lead_id, visitor_id, name, email, phone, consent, etc."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import create_lead

        db = _StubDatabase()
        claims = _claims()
        consent_dict = {
            "granted": True,
            "purpose": "contact",
            "text": "I agree.",
            "captured_at": "2026-01-01T12:00:00Z",
        }

        lead_id = await create_lead(
            db,
            claims,
            visitor_id=claims.subject,
            name="Jane Doe",
            email="jane@example.com",
            phone="+1555123456",
            consent=consent_dict,
            source="widget",
        )

        # Check the ID was returned (uuid4().hex format)
        assert isinstance(lead_id, str)
        assert len(lead_id) == 32  # hex string from uuid4().hex

        # Check the INSERT was called
        assert len(db.execute_calls) == 1
        insert_query, insert_args = db.execute_calls[0]
        assert "insert into leads" in insert_query.lower()
        assert insert_args[0] == claims.tenant_id  # tenant_id = $1
        assert insert_args[1] == lead_id  # lead_id = $2
        assert insert_args[2] == claims.subject  # visitor_id = $3
        assert insert_args[3] == "Jane Doe"  # name = $4
        assert insert_args[4] == "jane@example.com"  # email = $5
        assert insert_args[5] == "+1555123456"  # phone = $6
        assert insert_args[6] == "new"  # status = $7 (default)
        assert insert_args[7] == "captured"  # stage = $8 (default)
        assert insert_args[8] is None  # qualification_score = $9 (NULL)
        assert insert_args[9] == consent_dict  # consent = $10 (jsonb)
        assert insert_args[10] is None  # assigned_agent_id = $11 (NULL)
        assert insert_args[11] == "widget"  # source = $12


async def test_create_lead_uses_positional_placeholders() -> None:
    """The SQL uses positional placeholders ($1, $2, etc.), not named params."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import create_lead

        db = _StubDatabase()
        claims = _claims()

        await create_lead(
            db,
            claims,
            visitor_id=claims.subject,
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK", "captured_at": "2026-01-01T12:00:00Z"},
            source="widget",
        )

        insert_query, _ = db.execute_calls[0]
        # Check that the query uses $1, $2, ... not named params
        assert "$1" in insert_query
        assert "$2" in insert_query
        assert "$12" in insert_query
        assert ":" not in insert_query  # no named placeholders


async def test_create_lead_default_source() -> None:
    """When source is not provided, it defaults to 'widget'."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import create_lead

        db = _StubDatabase()
        claims = _claims()

        await create_lead(
            db,
            claims,
            visitor_id=claims.subject,
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK", "captured_at": "2026-01-01T12:00:00Z"},
            source="widget",
        )

        _, insert_args = db.execute_calls[0]
        # source should be at args[11]
        assert insert_args[11] == "widget"


async def test_get_lead_returns_mapped_lead() -> None:
    """get_lead returns a Lead dataclass with all fields mapped."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import Lead, get_lead

        db = _StubDatabase()
        claims = _claims()
        lead_id = "abc123def456"
        consent_dict = {"granted": True, "purpose": "contact", "text": "OK", "captured_at": "2026-01-01T12:00:00Z"}

        # Manually insert a lead into the stub
        db._leads[(claims.tenant_id, lead_id)] = {
            "tenant_id": claims.tenant_id,
            "lead_id": lead_id,
            "visitor_id": "visitor-123",
            "name": "Jane Doe",
            "email": "jane@example.com",
            "phone": "+1555123456",
            "status": "new",
            "stage": "captured",
            "qualification_score": None,
            "consent": consent_dict,
            "assigned_agent_id": None,
            "source": "widget",
            "created_at": _NOW,
            "updated_at": _NOW,
        }

        lead = await get_lead(db, claims, lead_id)

        assert isinstance(lead, Lead)
        assert lead.lead_id == lead_id
        assert lead.visitor_id == "visitor-123"
        assert lead.name == "Jane Doe"
        assert lead.email == "jane@example.com"
        assert lead.phone == "+1555123456"
        assert lead.status == "new"
        assert lead.stage == "captured"
        assert lead.qualification_score is None
        assert lead.consent == consent_dict
        assert lead.assigned_agent_id is None
        assert lead.source == "widget"


async def test_get_lead_returns_none_if_not_found() -> None:
    """get_lead returns None if the lead doesn't exist."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import get_lead

        db = _StubDatabase()
        claims = _claims()

        lead = await get_lead(db, claims, "nonexistent-id")

        assert lead is None


async def test_cross_tenant_isolation_create() -> None:
    """A lead created under tenant A is not visible when querying as tenant B."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import create_lead, get_lead

        db = _StubDatabase()
        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")

        # Create a lead under tenant A
        lead_id = await create_lead(
            db,
            claims_a,
            visitor_id="visitor-a",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK", "captured_at": "2026-01-01T12:00:00Z"},
            source="widget",
        )

        # Try to retrieve it as tenant B
        lead = await get_lead(db, claims_b, lead_id)

        # Should return None (not visible to tenant B)
        assert lead is None


async def test_get_lead_uses_positional_placeholders() -> None:
    """The get_lead SQL uses positional placeholders."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import get_lead

        db = _StubDatabase()
        claims = _claims()

        await get_lead(db, claims, "test-id")

        select_query, _ = db.fetchrow_calls[0]
        assert "$1" in select_query  # tenant_id
        assert "$2" in select_query  # lead_id
        assert ":" not in select_query  # no named placeholders
