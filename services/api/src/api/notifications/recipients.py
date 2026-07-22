"""Recipient resolution for scheduled events (S9.2, Scope §2 / Decision 3).

``schedule_events`` may carry an invite email alongside ``lead_id?``/``visitor_id?``.
``leads`` carries the visitor's ``email``. ``resolve_event_recipient`` reads
the event's contact fields via ``scheduling.repository.get_event_contact``
and resolves an email via the ``leads`` repository -- never reaching into
another module's tables directly.

No email found is a normal, expected case (anonymous bookings capture no
contact) -- returns ``None`` rather than raising. Callers that need a hard
failure signal (the reminder sink) raise ``NoRecipientError`` themselves.
"""
from __future__ import annotations

from common.auth import AuthClaims
from common.db import Database
from common.errors import ValidationError

from api.leads.repository import get_lead, get_lead_email_by_visitor_id
from api.scheduling.repository import get_event_contact


class NoRecipientError(ValidationError):
    """Raised by callers (e.g. the reminder sink) when no recipient resolves."""

    code = "NO_RECIPIENT"


async def resolve_event_recipient(db: Database, claims: AuthClaims, event_id: str) -> str | None:
    """Resolve the email address to notify for a scheduled event, or ``None``.

    Resolution order (Decision 3):
    1. event missing -> ``None``.
    2. event invite email set -> that address.
    3. ``lead_id`` set -> ``leads.get_lead(...).email`` (``None`` if the lead
       is missing).
    4. else ``visitor_id`` set -> ``leads.get_lead_email_by_visitor_id(...)``
       (most-recent lead for that visitor).
    5. else -> ``None``.

    Tenant-scoped throughout -- every underlying read rejects a global caller
    (``_reject_global``), so this raises ``ValidationError`` for
    PLATFORM_ADMIN callers rather than silently resolving nothing.
    """
    contact = await get_event_contact(db, claims, event_id)
    if contact is None:
        return None

    if contact.email is not None:
        return contact.email

    if contact.lead_id is not None:
        lead = await get_lead(db, claims, contact.lead_id)
        return lead.email if lead is not None else None

    if contact.visitor_id is not None:
        return await get_lead_email_by_visitor_id(db, claims, contact.visitor_id)

    return None
