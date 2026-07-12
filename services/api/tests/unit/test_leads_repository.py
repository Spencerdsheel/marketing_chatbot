"""Unit tests for api.leads.repository.

Covers:
- create_lead inserts a tenant-scoped row with all fields + consent jsonb.
- get_lead returns the row mapped to Lead, or None if not found.
- Cross-tenant isolation: lead created under tenant A is not visible to tenant B.
- IDs are uuid4().hex.
- Positional placeholders ($1, $2, ...) are used.
- update_lead_stage issues a tenant-scoped UPDATE, returns the updated Lead,
  no-ops (returns None) cross-tenant, and rejects global callers.
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
        # lead_activities: keyed by (tenant_id, activity_id)
        self._activities: dict[tuple[str, str], dict[str, Any]] = {}
        # Record all execute/fetchrow/fetch calls for inspection
        self.execute_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetchrow_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.fetch_calls: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self, query: str, *args: Any) -> str:
        self.execute_calls.append((query, args))
        q = query.strip().upper()

        if q.startswith("UPDATE LEADS SET ASSIGNED_AGENT_ID"):
            # args: assigned_agent_id, tenant_id, lead_id
            assigned_agent_id = args[0]
            tenant_id = args[1]
            lead_id = args[2]
            key = (tenant_id, lead_id)
            existing = self._leads.get(key)
            if existing is None:
                return "UPDATE 0"
            existing["assigned_agent_id"] = assigned_agent_id
            existing["updated_at"] = _NOW
            return "UPDATE 1"

        if q.startswith("UPDATE LEADS"):
            # args: stage, status, qualification_score, tenant_id, lead_id
            stage = args[0]
            status = args[1]
            qualification_score = args[2]
            tenant_id = args[3]
            lead_id = args[4]
            key = (tenant_id, lead_id)
            existing = self._leads.get(key)
            if existing is None:
                return "UPDATE 0"
            existing["stage"] = stage
            existing["status"] = status
            existing["qualification_score"] = qualification_score
            existing["updated_at"] = _NOW
            return "UPDATE 1"

        if q.startswith("INSERT INTO LEAD_ACTIVITIES"):
            # args: tenant_id, activity_id, lead_id, type, payload, actor
            tenant_id = args[0]
            activity_id = args[1]
            lead_id = args[2]
            activity_type = args[3]
            payload = args[4]
            actor = args[5]
            self._activities[(tenant_id, activity_id)] = {
                "tenant_id": tenant_id,
                "activity_id": activity_id,
                "lead_id": lead_id,
                "type": activity_type,
                "payload": payload,
                "actor": actor,
                "created_at": _NOW,
            }
            return "INSERT 0 1"

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

        if "FROM LEADS" in q and "AND VISITOR_ID = $2" in q:
            # get_lead_email_by_visitor_id -- WHERE tenant_id = $1 AND
            # visitor_id = $2 ORDER BY created_at DESC LIMIT 1
            tenant_id, visitor_id = args
            matches = [
                row
                for row in self._leads.values()
                if row["tenant_id"] == tenant_id and row["visitor_id"] == visitor_id
            ]
            if not matches:
                return None
            matches.sort(key=lambda r: r["created_at"], reverse=True)
            return matches[0]

        if "FROM LEADS" in q and "WHERE TENANT_ID" in q:
            # get_lead — WHERE tenant_id = $1 AND lead_id = $2
            tenant_id = args[0]
            lead_id = args[1]
            key = (tenant_id, lead_id)
            return self._leads.get(key)

        return None

    async def fetch(self, query: str, *args: Any) -> list[dict[str, Any]]:
        self.fetch_calls.append((query, args))
        q = query.strip().upper()

        if "FROM LEAD_ACTIVITIES" in q:
            # list_activities — WHERE tenant_id = $1 AND lead_id = $2
            tenant_id = args[0]
            lead_id = args[1]
            rows = [
                row
                for row in self._activities.values()
                if row["tenant_id"] == tenant_id and row["lead_id"] == lead_id
            ]
            rows.sort(key=lambda r: r["created_at"], reverse=True)
            return rows

        return []


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


# ---------------------------------------------------------------------------
# update_lead_stage
# ---------------------------------------------------------------------------


async def test_update_lead_stage_updates_and_returns_lead() -> None:
    """update_lead_stage issues a tenant-scoped UPDATE and returns the updated Lead."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import Lead, create_lead, update_lead_stage

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")

        lead_id = await create_lead(
            db,
            claims,
            visitor_id="visitor-1",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )

        updated = await update_lead_stage(
            db,
            claims,
            lead_id,
            stage="qualified",
            status="open",
            qualification_score=55,
        )

        assert isinstance(updated, Lead)
        assert updated.lead_id == lead_id
        assert updated.stage == "qualified"
        assert updated.status == "open"
        assert updated.qualification_score == 55


async def test_update_lead_stage_uses_tenant_scoped_positional_sql() -> None:
    """The UPDATE statement filters WHERE tenant_id=$_ AND lead_id=$_ with positional params."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import create_lead, update_lead_stage

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")

        lead_id = await create_lead(
            db,
            claims,
            visitor_id="visitor-1",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )

        await update_lead_stage(
            db,
            claims,
            lead_id,
            stage="qualified",
            status="open",
            qualification_score=55,
        )

        update_query, update_args = db.execute_calls[-1]
        assert "update leads" in update_query.lower()
        assert "where" in update_query.lower()
        assert "tenant_id" in update_query.lower()
        assert "lead_id" in update_query.lower()
        assert "updated_at" in update_query.lower()
        assert ":" not in update_query  # no named placeholders
        # tenant_id and lead_id must be among the bound params
        assert claims.tenant_id in update_args
        assert lead_id in update_args


async def test_update_lead_stage_cross_tenant_returns_none() -> None:
    """A caller from tenant B updating tenant A's lead matches 0 rows -> None."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import create_lead, update_lead_stage

        db = _StubDatabase()
        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")

        lead_id = await create_lead(
            db,
            claims_a,
            visitor_id="visitor-1",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )

        result = await update_lead_stage(
            db,
            claims_b,
            lead_id,
            stage="qualified",
            status="open",
            qualification_score=55,
        )

        assert result is None


async def test_update_lead_stage_missing_lead_returns_none() -> None:
    """Updating a nonexistent lead_id returns None."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import update_lead_stage

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")

        result = await update_lead_stage(
            db,
            claims,
            "nonexistent-id",
            stage="qualified",
            status="open",
            qualification_score=55,
        )

        assert result is None


async def test_update_lead_stage_rejects_global_caller() -> None:
    """A PLATFORM_ADMIN (global, tenant_id=None) caller raises ValidationError."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from common.errors import ValidationError

        from api.leads.repository import update_lead_stage

        db = _StubDatabase()
        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await update_lead_stage(
                db,
                global_claims,
                "some-lead-id",
                stage="qualified",
                status="open",
                qualification_score=55,
            )


# ---------------------------------------------------------------------------
# add_activity / list_activities / assign_lead
# ---------------------------------------------------------------------------


async def test_add_activity_inserts_tenant_scoped_row() -> None:
    """add_activity issues a tenant-scoped INSERT and returns a uuid4().hex activity_id."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import add_activity, create_lead

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")
        lead_id = await create_lead(
            db,
            claims,
            visitor_id="visitor-1",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )

        activity_id = await add_activity(
            db,
            claims,
            lead_id,
            type="note",
            payload={"text": "Called, left voicemail."},
            actor="user-1",
        )

        assert isinstance(activity_id, str)
        assert len(activity_id) == 32

        insert_query, insert_args = db.execute_calls[-1]
        assert "insert into lead_activities" in insert_query.lower()
        assert "$1" in insert_query
        assert ":" not in insert_query
        assert insert_args[0] == claims.tenant_id
        assert insert_args[1] == activity_id
        assert insert_args[2] == lead_id
        assert insert_args[3] == "note"
        assert insert_args[4] == {"text": "Called, left voicemail."}
        assert insert_args[5] == "user-1"


async def test_add_activity_rejects_global_caller() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from common.errors import ValidationError

        from api.leads.repository import add_activity

        db = _StubDatabase()
        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await add_activity(
                db,
                global_claims,
                "some-lead-id",
                type="note",
                payload={"text": "x"},
                actor="admin-1",
            )


async def test_list_activities_returns_tenant_scoped_ordered() -> None:
    """list_activities returns only this tenant's activities for the lead, newest first."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import LeadActivity, add_activity, create_lead, list_activities

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")
        lead_id = await create_lead(
            db,
            claims,
            visitor_id="visitor-1",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )

        first_id = await add_activity(
            db, claims, lead_id, type="note", payload={"text": "first"}, actor="user-1"
        )
        second_id = await add_activity(
            db, claims, lead_id, type="note", payload={"text": "second"}, actor="user-1"
        )
        # Force distinct timestamps so DESC ordering is unambiguous.
        db._activities[(claims.tenant_id, first_id)]["created_at"] = datetime(
            2026, 1, 1, 12, 0, 0, tzinfo=UTC
        )
        db._activities[(claims.tenant_id, second_id)]["created_at"] = datetime(
            2026, 1, 1, 12, 5, 0, tzinfo=UTC
        )

        activities = await list_activities(db, claims, lead_id)

        assert all(isinstance(a, LeadActivity) for a in activities)
        assert [a.activity_id for a in activities] == [second_id, first_id]


async def test_list_activities_cross_tenant_empty() -> None:
    """A tenant B caller sees no activities for tenant A's lead."""
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import add_activity, create_lead, list_activities

        db = _StubDatabase()
        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")

        lead_id = await create_lead(
            db,
            claims_a,
            visitor_id="visitor-1",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )
        await add_activity(db, claims_a, lead_id, type="note", payload={"text": "hi"}, actor="user-1")

        activities = await list_activities(db, claims_b, lead_id)

        assert activities == []


async def test_list_activities_rejects_global_caller() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from common.errors import ValidationError

        from api.leads.repository import list_activities

        db = _StubDatabase()
        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await list_activities(db, global_claims, "some-lead-id")


async def test_assign_lead_updates_assigned_agent_id() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import Lead, assign_lead, create_lead

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")
        lead_id = await create_lead(
            db,
            claims,
            visitor_id="visitor-1",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )

        updated = await assign_lead(db, claims, lead_id, agent_id="agent-1")

        assert isinstance(updated, Lead)
        assert updated.assigned_agent_id == "agent-1"

        update_query, update_args = db.execute_calls[-1]
        assert "update leads" in update_query.lower()
        assert "assigned_agent_id" in update_query.lower()
        assert "$1" in update_query
        assert ":" not in update_query
        assert claims.tenant_id in update_args
        assert lead_id in update_args


async def test_assign_lead_cross_tenant_returns_none() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import assign_lead, create_lead

        db = _StubDatabase()
        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")

        lead_id = await create_lead(
            db,
            claims_a,
            visitor_id="visitor-1",
            name="Jane",
            email="jane@example.com",
            phone=None,
            consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )

        result = await assign_lead(db, claims_b, lead_id, agent_id="agent-1")

        assert result is None
        stored = db._leads[("tenant-a", lead_id)]
        assert stored["assigned_agent_id"] is None


async def test_assign_lead_rejects_global_caller() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from common.errors import ValidationError

        from api.leads.repository import assign_lead

        db = _StubDatabase()
        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await assign_lead(db, global_claims, "some-lead-id", agent_id="agent-1")


# ---------------------------------------------------------------------------
# get_lead_email_by_visitor_id (S9.2, Scope §7)
# ---------------------------------------------------------------------------


async def test_get_lead_email_by_visitor_id_returns_most_recent() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import create_lead, get_lead_email_by_visitor_id

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")

        await create_lead(
            db, claims, visitor_id="visitor-1", name="First", email="first@example.com",
            phone=None, consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )
        # A later lead for the same visitor -- created_at defaults to _NOW for
        # both rows in this stub, so bump the second row's created_at
        # explicitly to make "most recent" observable.
        second_lead_id = await create_lead(
            db, claims, visitor_id="visitor-1", name="Second", email="second@example.com",
            phone=None, consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )
        from datetime import timedelta

        db._leads[("tenant-abc", second_lead_id)]["created_at"] = _NOW + timedelta(minutes=5)

        email = await get_lead_email_by_visitor_id(db, claims, "visitor-1")

        assert email == "second@example.com"


async def test_get_lead_email_by_visitor_id_returns_none_when_no_lead() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import get_lead_email_by_visitor_id

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")

        result = await get_lead_email_by_visitor_id(db, claims, "visitor-does-not-exist")

        assert result is None


async def test_get_lead_email_by_visitor_id_cross_tenant_isolation() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import create_lead, get_lead_email_by_visitor_id

        db = _StubDatabase()
        claims_a = _claims(tenant_id="tenant-a")
        claims_b = _claims(tenant_id="tenant-b")

        await create_lead(
            db, claims_a, visitor_id="visitor-shared", name="Jane", email="jane@example.com",
            phone=None, consent={"granted": True, "purpose": "contact", "text": "OK"},
            source="widget",
        )

        result = await get_lead_email_by_visitor_id(db, claims_b, "visitor-shared")

        assert result is None


async def test_get_lead_email_by_visitor_id_uses_positional_placeholders() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from api.leads.repository import get_lead_email_by_visitor_id

        db = _StubDatabase()
        claims = _claims(tenant_id="tenant-abc")

        await get_lead_email_by_visitor_id(db, claims, "visitor-1")

        query, args = db.fetchrow_calls[-1]
        assert "$1" in query
        assert "$2" in query
        assert ":" not in query
        assert args[0] == "tenant-abc"
        assert args[1] == "visitor-1"


async def test_get_lead_email_by_visitor_id_rejects_global_caller() -> None:
    with patch.dict("os.environ", _TEST_ENV, clear=False):
        _reset_settings()
        from common.errors import ValidationError

        from api.leads.repository import get_lead_email_by_visitor_id

        db = _StubDatabase()
        global_claims = AuthClaims(subject="admin-1", role=Role.PLATFORM_ADMIN, tenant_id=None)

        with pytest.raises(ValidationError):
            await get_lead_email_by_visitor_id(db, global_claims, "visitor-1")
