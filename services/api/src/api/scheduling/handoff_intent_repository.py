"""Calendly handoff-intent repository -- email-keyed correlation (SR-6, migration 0036).

``calendly_handoff_intents(tenant_id, visitor_id, email, created_at, expires_at)``
is the short-lived server-side record that lets the Calendly webhook
(``api.scheduling.calendly_webhook``) backfill ``visitor_id`` onto an
ingested booking by matching the invitee's email -- a deliberate, documented
reversal of SR-5 decision 7d for the Calendly path only (SR-6 decision 5).

``create_handoff_intent`` follows the standard ``AuthClaims``-scoped
convention (``_reject_global`` first, tenant_id from claims never the body).

``find_handoff_visitor`` is the ONE claims-less exception in this module: it
is called from the Calendly webhook, which has no session/claims (the
signature is the auth). It still filters ``tenant_id`` explicitly on every
predicate -- the tenant_id passed in comes from the already-signature-
verified webhook path, never from user input -- so a same-email intent under
a DIFFERENT tenant is never returned (mandatory tenant isolation, SR-6
Constraints).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from common.auth import AuthClaims
from common.db import Database
from common.errors import ValidationError


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN).

    Handoff intents are always tenant-scoped; a global caller has no
    tenant_id and therefore cannot be filtered to a tenant's rows.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "Handoff intent repository is tenant-scoped; PLATFORM_ADMIN callers "
            "are not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )


@dataclass(frozen=True)
class HandoffIntent:
    """A single pre-handoff email-correlation record."""

    tenant_id: str
    visitor_id: str
    email: str
    created_at: datetime
    expires_at: datetime


async def create_handoff_intent(
    db: Database,
    claims: AuthClaims,
    *,
    visitor_id: str,
    email: str,
    ttl_seconds: int,
) -> None:
    """Insert a new handoff-intent row for the caller's tenant + visitor.

    ``visitor_id`` MUST be ``claims.subject`` (the route enforces this --
    never a body-supplied id). ``expires_at = now() + ttl_seconds`` is
    computed server-side. Every predicate parameterized; email never
    interpolated. Raises ``ValidationError`` for global callers.
    """
    _reject_global(claims)

    await db.execute(
        "INSERT INTO calendly_handoff_intents "
        "(tenant_id, visitor_id, email, expires_at) "
        "VALUES ($1, $2, $3, now() + make_interval(secs => $4))",
        claims.tenant_id,
        visitor_id,
        email,
        ttl_seconds,
    )


async def find_handoff_visitor(
    db: Database, tenant_id: str, email: str, now: datetime
) -> str | None:
    """Resolve the ``visitor_id`` to backfill onto an ingested Calendly booking.

    Claims-less (the ONE exception in this module -- see module docstring):
    called from the signature-verified Calendly webhook, which has no
    session. ``tenant_id`` is bound on every predicate -- a same-email intent
    under a different tenant is NEVER returned (mandatory tenant isolation).

    ``WHERE tenant_id = $1 AND lower(email) = lower($2) AND expires_at > $3
    ORDER BY created_at DESC LIMIT 1`` -- case-insensitive email match, only
    non-expired intents considered, most-recent wins on a tie (SR-6 decision
    5b). Returns ``None`` on no match -- this is NOT an error; the caller
    ingests the booking anyway with ``visitor_id=NULL`` (honest no-match,
    never dropped, never guessed).
    """
    row = await db.fetchrow(
        "SELECT visitor_id FROM calendly_handoff_intents "
        "WHERE tenant_id = $1 AND lower(email) = lower($2) AND expires_at > $3 "
        "ORDER BY created_at DESC LIMIT 1",
        tenant_id,
        email,
        now,
    )
    if row is None:
        return None
    return str(row["visitor_id"])
