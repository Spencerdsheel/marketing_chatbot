"""Admin notification routes -- config + test-send (S9.1). Both ``CLIENT_ADMIN`` only.

``PUT /admin/notifications/config`` sets the tenant's notification provider
config (mirrors ``PUT /admin/schedule/calendar``, S8.2 decision 2) -- the
SMTP password is encrypted at rest and never echoed back.

``POST /admin/notifications/test-send`` is the one enqueuer S9.1 ships: an
admin-initiated test-send to a caller-supplied address (S9.1 decisions 4/7 --
no visitor-consent gate applies here; the real enqueuers land in S9.2). It
idempotently enqueues via ``enqueue_notification`` and only ``.delay()``s the
send task for a genuinely NEW job -- a re-post with the same explicit
``dedupe_key`` returns ``deduplicated: true`` and does NOT enqueue a second
send (proves S9.1 decision 4 at the route).
"""
from __future__ import annotations

from uuid import uuid4

from common.auth import AuthClaims, Role
from common.logging import get_logger
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from api.auth.dependencies import require_roles
from api.notifications.config_repository import upsert_notification_config
from api.notifications.providers import validate_recipient_for_channel
from api.notifications.repository import (
    enqueue_notification,
    get_notification_job_id_by_dedupe_key,
)
from api.notifications.tasks import send_notification

_log = get_logger(__name__)

router = APIRouter(prefix="/admin/notifications", tags=["notifications"])


class NotificationConfigRequest(BaseModel):
    """Body for PUT /admin/notifications/config.

    ``channel`` defaults to ``"email"`` -- S9.1 back-compat: a body with no
    ``channel`` still upserts the email row.
    """

    provider: str
    channel: str = "email"
    from_address: str | None = None
    from_name: str | None = None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_use_tls: bool = True
    smtp_username: str | None = None
    twilio_account_sid: str | None = None
    twilio_from: str | None = None
    credentials: str = ""  # SMTP password OR Twilio Auth Token; encrypted at rest, never echoed
    enabled: bool = False


class NotificationConfigResponse(BaseModel):
    """Leak-free (no password/ciphertext/Auth Token) response for PUT .../config."""

    provider: str
    channel: str
    from_address: str | None
    from_name: str | None
    smtp_host: str | None
    smtp_port: int | None
    smtp_use_tls: bool
    smtp_username: str | None
    twilio_account_sid: str | None
    twilio_from: str | None
    enabled: bool


@router.put("/config")
async def put_notification_config(
    body: NotificationConfigRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> NotificationConfigResponse:
    """Set the calling tenant's notification provider config. ``CLIENT_ADMIN`` only.

    The SMTP password is encrypted at rest (AES-256-GCM via ``SecretBox``)
    and never echoed back in the response (S9.1 decision 2).
    """
    await upsert_notification_config(
        request.app.state.db,
        claims,
        channel=body.channel,
        provider=body.provider,
        from_address=body.from_address,
        from_name=body.from_name,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
        smtp_use_tls=body.smtp_use_tls,
        smtp_username=body.smtp_username,
        twilio_account_sid=body.twilio_account_sid,
        twilio_from=body.twilio_from,
        credentials=body.credentials,
        enabled=body.enabled,
    )

    _log.info(
        "notification config updated",
        extra={
            "event": "notification_config_set",
            "provider": body.provider,
            "channel": body.channel,
            "tenant_id": claims.tenant_id,
            "enabled": body.enabled,
        },
    )

    return NotificationConfigResponse(
        provider=body.provider,
        channel=body.channel,
        from_address=body.from_address,
        from_name=body.from_name,
        smtp_host=body.smtp_host,
        smtp_port=body.smtp_port,
        smtp_use_tls=body.smtp_use_tls,
        smtp_username=body.smtp_username,
        twilio_account_sid=body.twilio_account_sid,
        twilio_from=body.twilio_from,
        enabled=body.enabled,
    )


class TestSendRequest(BaseModel):
    """Body for POST /admin/notifications/test-send.

    ``channel`` defaults to ``"email"`` (S9.1 back-compat). ``subject``
    defaults to ``""`` -- SMS/WhatsApp have no subject field
    (``message.subject`` is ignored by ``TwilioNotificationProvider``).
    """

    channel: str = "email"
    recipient: str
    subject: str = ""
    body: str
    dedupe_key: str | None = None


class TestSendResponse(BaseModel):
    """Leak-free response for POST /admin/notifications/test-send."""

    job_id: str
    deduplicated: bool


@router.post("/test-send", status_code=202)
async def post_test_send(
    body: TestSendRequest,
    request: Request,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> TestSendResponse:
    """Enqueue an admin-initiated test-send email. ``CLIENT_ADMIN`` only.

    ``dedupe_key`` defaults to a fresh ``f"test:{uuid4().hex}"`` (one per
    call) or a caller-supplied value to prove idempotency live. Only a
    genuinely NEW enqueue triggers ``send_notification.delay`` -- a
    duplicate ``dedupe_key`` returns ``deduplicated: true`` with the
    EXISTING job's id and does not enqueue a second send.
    """
    validate_recipient_for_channel(body.channel, body.recipient)

    db = request.app.state.db
    dedupe_key = body.dedupe_key or f"test:{uuid4().hex}"

    job_id = await enqueue_notification(
        db,
        claims,
        channel=body.channel,
        recipient=body.recipient,
        subject=body.subject,
        body=body.body,
        dedupe_key=dedupe_key,
    )

    if job_id is not None:
        from common.logging import _correlation_id  # noqa: PLC0415, PLC2701

        correlation_id = _correlation_id.get() or ""
        send_notification.delay(
            job_id=job_id,
            tenant_id=claims.tenant_id,
            correlation_id=correlation_id,
        )
        return TestSendResponse(job_id=job_id, deduplicated=False)

    # Conflict -- already enqueued under this dedupe_key. Look up the
    # existing job_id so the caller still gets a stable identifier back.
    existing = await get_notification_job_id_by_dedupe_key(db, claims, dedupe_key)
    return TestSendResponse(job_id=existing or "", deduplicated=True)
