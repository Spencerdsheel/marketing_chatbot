"""Lead capture routes -- visitor-authenticated endpoint for form submission.

This is a TEMPORARY endpoint (prefixed ``/public/leads``) for lead capture
via the widget form. The endpoint is authenticated by the visitor session
(``get_visitor_claims``), gates persistence on explicit consent, and stores
the lead with a server-stamped consent record.

The response is leak-free: it never includes ``tenant_id``, ``visitor_id``,
or echoed PII.
"""
from __future__ import annotations

from datetime import UTC, datetime

from common.auth import AuthClaims
from common.errors import ValidationError
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, field_validator

from api.gateway.dependencies import get_visitor_claims
from api.leads.repository import create_lead

_log = get_logger(__name__)

router = APIRouter(prefix="/public/leads", tags=["leads"])


class ConsentPayload(BaseModel):
    """Consent metadata provided by the visitor."""

    granted: bool
    purpose: str
    text: str


class LeadCaptureRequest(BaseModel):
    """Body for POST /public/leads (widget lead form)."""

    name: str
    email: str
    phone: str | None = None
    source: str | None = None
    consent: ConsentPayload | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("name must not be blank")
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("email must not be blank")
        if "@" not in v:
            raise ValueError("email must contain @")
        return v


class LeadCaptureResponse(BaseModel):
    """Leak-free response body for POST /public/leads."""

    lead_id: str
    status: str


@router.post("", status_code=201)
async def capture_lead(
    body: LeadCaptureRequest,
    request: Request,
    claims: AuthClaims = Depends(get_visitor_claims),  # noqa: B008
) -> LeadCaptureResponse:
    """Capture a lead via the visitor session.

    The ``consent`` object is required and must have ``granted=true`` for the
    lead to be stored. If consent is missing or ``granted`` is not exactly
    ``True``, returns 422 ``CONSENT_REQUIRED`` and nothing is persisted.

    ``tenant_id`` and ``visitor_id`` come from the visitor session
    (``claims``), never from the request body.

    Returns 201 ``{lead_id, status:"new"}`` on success. The response never
    includes ``tenant_id``, ``visitor_id``, or PII.
    """
    # -- Consent gate (GDPR) -----------------------------------------------
    if body.consent is None or body.consent.granted is not True:
        raise ValidationError(
            "Consent to store contact information is required.",
            code="CONSENT_REQUIRED",
        )

    # -- Stamp consent with server time ------------------------------------
    consent_with_timestamp = {
        "granted": body.consent.granted,
        "purpose": body.consent.purpose,
        "text": body.consent.text,
        "captured_at": datetime.now(UTC).isoformat(),
    }

    # -- Capture the lead --------------------------------------------------
    db = request.app.state.db
    source = body.source or "widget"

    lead_id = await create_lead(
        db,
        claims,
        visitor_id=claims.subject,
        name=body.name,
        email=body.email,
        phone=body.phone,
        consent=consent_with_timestamp,
        source=source,
    )

    # -- Log the event (PII-safe) ------------------------------------------
    _log.info(
        "lead captured",
        extra={"event": "lead_captured", "lead_id": lead_id, "tenant_id": claims.tenant_id},
    )

    return LeadCaptureResponse(lead_id=lead_id, status="new")
