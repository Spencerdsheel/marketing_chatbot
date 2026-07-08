"""Admin/agent lead pipeline routes -- GET and PATCH /admin/leads/{lead_id}.

An authenticated ``CLIENT_ADMIN`` or ``CLIENT_AGENT`` reviews a lead and
moves it through the pipeline state machine (``api.leads.pipeline``). Every
access is tenant-scoped via ``claims.tenant_id`` -- a cross-tenant
``lead_id`` is indistinguishable from a missing one and returns 404.

The response is an authenticated admin/agent surface, so it MAY include
contact fields (unlike the leak-free ``/public/leads`` response) -- but
``tenant_id`` and raw consent text are never included, and the transition
log never carries PII.
"""
from __future__ import annotations

import csv
import io
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from common.auth import AuthClaims, Role
from common.errors import NotFoundError, ValidationError
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator

from api.auth.dependencies import require_roles
from api.auth.repository import get_user_by_id
from api.leads.pipeline import compute_qualification_score, status_for_stage, validate_transition
from api.leads.repository import (
    Lead,
    LeadActivity,
    add_activity,
    assign_lead,
    get_lead,
    list_activities,
    list_leads_for_export,
    update_lead_stage,
)

_log = get_logger(__name__)

_NOTE_MAX_LENGTH = 4000

router = APIRouter(prefix="/admin/leads", tags=["leads"])


class LeadStageUpdateRequest(BaseModel):
    """Body for PATCH /admin/leads/{lead_id}."""

    stage: str


class LeadNoteRequest(BaseModel):
    """Body for POST /admin/leads/{lead_id}/notes."""

    text: str = Field(min_length=1, max_length=_NOTE_MAX_LENGTH)

    @field_validator("text")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Note text must not be blank.")
        return value


class LeadAssignmentRequest(BaseModel):
    """Body for POST /admin/leads/{lead_id}/assignment."""

    agent_id: str


class LeadActivityResponse(BaseModel):
    """Leak-free (no ``tenant_id``) activity for the admin/agent timeline surface."""

    activity_id: str
    lead_id: str
    type: str
    payload: dict[str, Any] | None
    actor: str | None
    created_at: datetime


def _to_activity_response(activity: LeadActivity) -> LeadActivityResponse:
    return LeadActivityResponse(
        activity_id=activity.activity_id,
        lead_id=activity.lead_id,
        type=activity.type,
        payload=activity.payload,
        actor=activity.actor,
        created_at=activity.created_at,
    )


class LeadDetailResponse(BaseModel):
    """Leak-free (no ``tenant_id``) lead detail for the admin/agent surface."""

    lead_id: str
    name: str
    email: str
    phone: str | None
    status: str
    stage: str
    qualification_score: int | None
    assigned_agent_id: str | None
    source: str


def _to_response(lead: Lead) -> LeadDetailResponse:
    return LeadDetailResponse(
        lead_id=lead.lead_id,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        status=lead.status,
        stage=lead.stage,
        qualification_score=lead.qualification_score,
        assigned_agent_id=lead.assigned_agent_id,
        source=lead.source,
    )


_EXPORT_COLUMNS = (
    "lead_id",
    "name",
    "email",
    "phone",
    "status",
    "stage",
    "qualification_score",
    "assigned_agent_id",
    "source",
    "created_at",
)


def _lead_to_csv_row(lead: Lead) -> list[str]:
    return [
        lead.lead_id,
        lead.name,
        lead.email,
        lead.phone or "",
        lead.status,
        lead.stage,
        str(lead.qualification_score) if lead.qualification_score is not None else "",
        lead.assigned_agent_id or "",
        lead.source,
        lead.created_at.isoformat(),
    ]


@router.get("/export")
async def export_leads(
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> StreamingResponse:
    """Stream a tenant-scoped CSV export of leads (S7.4 decision 5).

    Columns: ``lead_id, name, email, phone, status, stage,
    qualification_score, assigned_agent_id, source, created_at``. Consent
    text is intentionally excluded (contains free-text PII). Cross-tenant
    leads never appear -- ``list_leads_for_export`` filters by
    ``claims.tenant_id``. Logs a PII-free export event (row count only).

    NOTE: this route is registered ABOVE ``GET /{lead_id}`` -- FastAPI
    matches routes in declaration order, and ``/export`` would otherwise be
    swallowed by the ``{lead_id}`` path parameter.
    """
    db = request.app.state.db

    leads = await list_leads_for_export(db, claims)

    def _generate() -> Iterator[str]:
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        writer.writerow(_EXPORT_COLUMNS)
        yield buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)

        for lead in leads:
            writer.writerow(_lead_to_csv_row(lead))
            yield buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)

    _log.info(
        "lead export",
        extra={
            "event": "lead_export",
            "row_count": len(leads),
            "tenant_id": claims.tenant_id,
        },
    )

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@router.get("/{lead_id}")
async def get_lead_detail(
    lead_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> LeadDetailResponse:
    """Fetch a lead's pipeline detail. Returns 404 if missing or cross-tenant."""
    db = request.app.state.db

    lead = await get_lead(db, claims, lead_id)
    if lead is None:
        raise NotFoundError("Lead not found.", code="NOT_FOUND")

    return _to_response(lead)


@router.patch("/{lead_id}")
async def patch_lead_stage(
    lead_id: str,
    body: LeadStageUpdateRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> LeadDetailResponse:
    """Move a lead to a new pipeline stage.

    Flow: ``get_lead`` (404 if missing/cross-tenant) -> ``validate_transition``
    (422 ``INVALID_STAGE_TRANSITION`` if illegal; nothing persisted) ->
    derive ``status`` + recompute ``qualification_score`` -> persist via
    ``update_lead_stage``. ``status`` and ``qualification_score`` are always
    derived server-side -- callers never set them directly.
    """
    db = request.app.state.db

    lead = await get_lead(db, claims, lead_id)
    if lead is None:
        raise NotFoundError("Lead not found.", code="NOT_FOUND")

    validate_transition(lead.stage, body.stage)

    new_status = status_for_stage(body.stage)
    scored_lead = Lead(
        lead_id=lead.lead_id,
        visitor_id=lead.visitor_id,
        name=lead.name,
        email=lead.email,
        phone=lead.phone,
        status=new_status,
        stage=body.stage,
        qualification_score=lead.qualification_score,
        consent=lead.consent,
        assigned_agent_id=lead.assigned_agent_id,
        source=lead.source,
        created_at=lead.created_at,
        updated_at=lead.updated_at,
    )
    new_score = compute_qualification_score(scored_lead)

    updated = await update_lead_stage(
        db,
        claims,
        lead_id,
        stage=body.stage,
        status=new_status,
        qualification_score=new_score,
    )
    if updated is None:
        raise NotFoundError("Lead not found.", code="NOT_FOUND")

    await add_activity(
        db,
        claims,
        lead_id,
        type="stage_change",
        payload={"from_stage": lead.stage, "to_stage": body.stage},
        actor=claims.subject,
    )

    # PII-safe transition log: lead_id/tenant_id/from_stage/to_stage/event only.
    _log.info(
        "lead stage transitioned",
        extra={
            "event": "lead_stage_transitioned",
            "lead_id": lead_id,
            "tenant_id": claims.tenant_id,
            "from_stage": lead.stage,
            "to_stage": body.stage,
        },
    )

    return _to_response(updated)


@router.post("/{lead_id}/notes", status_code=status.HTTP_201_CREATED)
async def post_lead_note(
    lead_id: str,
    body: LeadNoteRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> LeadActivityResponse:
    """Append a free-text note to a lead's timeline.

    404 if the lead is missing or cross-tenant; 422 if the note is blank or
    exceeds the length bound (enforced by ``LeadNoteRequest``). Note text may
    contain PII -- it is stored, never logged.
    """
    db = request.app.state.db

    lead = await get_lead(db, claims, lead_id)
    if lead is None:
        raise NotFoundError("Lead not found.", code="NOT_FOUND")

    activity_id = await add_activity(
        db,
        claims,
        lead_id,
        type="note",
        payload={"text": body.text},
        actor=claims.subject,
    )

    _log.info(
        "lead note added",
        extra={
            "event": "lead_note_added",
            "activity_id": activity_id,
            "lead_id": lead_id,
            "tenant_id": claims.tenant_id,
            "type": "note",
        },
    )

    return LeadActivityResponse(
        activity_id=activity_id,
        lead_id=lead_id,
        type="note",
        payload={"text": body.text},
        actor=claims.subject,
        created_at=datetime.now(tz=UTC),
    )


@router.post("/{lead_id}/assignment")
async def post_lead_assignment(
    lead_id: str,
    body: LeadAssignmentRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> LeadDetailResponse:
    """Assign a lead to a same-tenant, active ``CLIENT_AGENT``.

    404 if the lead is missing/cross-tenant. The assignee is validated via
    ``auth.repository.get_user_by_id`` -- a not-found, cross-tenant,
    wrong-role, or inactive assignee are all indistinguishable 422
    ``INVALID_ASSIGNEE`` responses (never leak whether a user id exists in
    another tenant). On success, appends an ``assignment`` activity.
    """
    db = request.app.state.db

    lead = await get_lead(db, claims, lead_id)
    if lead is None:
        raise NotFoundError("Lead not found.", code="NOT_FOUND")

    assignee = await get_user_by_id(db, body.agent_id)
    if (
        assignee is None
        or assignee.get("tenant_id") != claims.tenant_id
        or not assignee.get("active")
        or assignee.get("role") != Role.CLIENT_AGENT.value
    ):
        raise ValidationError(
            "The specified assignee is not a valid, active agent in this tenant.",
            code="INVALID_ASSIGNEE",
        )

    updated = await assign_lead(db, claims, lead_id, agent_id=body.agent_id)
    if updated is None:
        raise NotFoundError("Lead not found.", code="NOT_FOUND")

    activity_id = await add_activity(
        db,
        claims,
        lead_id,
        type="assignment",
        payload={"agent_id": body.agent_id, "previous_agent_id": lead.assigned_agent_id},
        actor=claims.subject,
    )

    _log.info(
        "lead assigned",
        extra={
            "event": "lead_assigned",
            "activity_id": activity_id,
            "lead_id": lead_id,
            "tenant_id": claims.tenant_id,
            "type": "assignment",
        },
    )

    return _to_response(updated)


@router.get("/{lead_id}/activities")
async def get_lead_activities(
    lead_id: str,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN, Role.CLIENT_AGENT)),  # noqa: B008
) -> list[LeadActivityResponse]:
    """Fetch a lead's timeline, newest first. 404 if missing or cross-tenant."""
    db = request.app.state.db

    lead = await get_lead(db, claims, lead_id)
    if lead is None:
        raise NotFoundError("Lead not found.", code="NOT_FOUND")

    activities = await list_activities(db, claims, lead_id)
    return [_to_activity_response(a) for a in activities]
