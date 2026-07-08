"""CRMSync Protocol + ExternalRef + WebhookSync + crm_sync_for selector.

Decision 1 (S7.4): ``CRMSync`` is a ``typing.Protocol``; ``WebhookSync`` is the
only implementation this sprint (HubSpot/Salesforce connectors are deferred
behind the same Protocol -- drop-in later). ``WebhookSync`` POSTs a JSON lead
payload to the tenant's ``webhook_url`` via httpx, signing the raw body with
an HMAC-SHA256 ``X-Signature`` header keyed by the tenant's decrypted CRM
secret so the receiver can verify authenticity.

2xx -> success. Non-2xx / network error -> raise, so the caller (the
``crm.sync_lead`` Celery task) lets Celery retry (transient). An unknown
connector, or a webhook config missing ``webhook_url``, is a deterministic
configuration error -- ``crm_sync_for`` raises ``ValidationError`` immediately
(before any network call), which the task catches and does NOT retry.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Protocol

import httpx
from common.auth import AuthClaims
from common.errors import ValidationError

from api.crm.config_repository import CRMConfig
from api.leads.repository import Lead

_DEFAULT_TIMEOUT_SECONDS = 10.0


@dataclass(frozen=True)
class ExternalRef:
    """The result of a successful ``CRMSync.upsert_lead`` call."""

    connector: str
    external_id: str | None
    status: str


class CRMSync(Protocol):
    """Outbound CRM sync contract. Implementations are selected per tenant."""

    async def upsert_lead(self, claims: AuthClaims, lead: Lead) -> ExternalRef: ...


class CRMSyncConfigError(ValidationError):
    """Deterministic CRM sync configuration error -- never retried."""

    code = "CRM_SYNC_CONFIG_ERROR"


def _lead_payload(lead: Lead) -> dict[str, object]:
    """Build the JSON-serializable payload sent to the external CRM.

    Contains contact fields by design (that is the point of an outbound
    sync) -- this is never logged (see api.crm.tasks).
    """
    return {
        "lead_id": lead.lead_id,
        "name": lead.name,
        "email": lead.email,
        "phone": lead.phone,
        "status": lead.status,
        "stage": lead.stage,
        "qualification_score": lead.qualification_score,
        "source": lead.source,
    }


class WebhookSync:
    """``CRMSync`` implementation: HMAC-signed webhook POST."""

    def __init__(
        self,
        *,
        webhook_url: str,
        secret: str,
        timeout: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._webhook_url = webhook_url
        self._secret = secret
        self._timeout = timeout

    async def upsert_lead(self, claims: AuthClaims, lead: Lead) -> ExternalRef:
        body = json.dumps(_lead_payload(lead), separators=(",", ":")).encode("utf-8")
        signature = hmac.new(self._secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            try:
                response = await client.post(
                    self._webhook_url,
                    content=body,
                    headers={
                        "Content-Type": "application/json",
                        "X-Signature": signature,
                    },
                )
            except httpx.HTTPError as exc:
                # Transient (network) failure -- propagate for Celery retry.
                raise RuntimeError(f"CRM webhook request failed: {exc}") from exc

        if not (200 <= response.status_code < 300):
            # Transient (server) failure -- propagate for Celery retry.
            raise RuntimeError(
                f"CRM webhook returned non-2xx status: {response.status_code}"
            )

        return ExternalRef(connector="webhook", external_id=None, status="ok")


def crm_sync_for(config: CRMConfig) -> CRMSync:
    """Select a ``CRMSync`` implementation for the tenant's config.

    Raises ``CRMSyncConfigError`` (a ``ValidationError``) for an unknown
    connector or an incomplete webhook config -- these are deterministic and
    must never be retried by the caller.
    """
    if config.connector == "webhook":
        if not config.webhook_url:
            raise CRMSyncConfigError(
                "Webhook connector requires webhook_url.",
                code="CRM_WEBHOOK_URL_MISSING",
            )
        return WebhookSync(webhook_url=config.webhook_url, secret=config.secret)

    raise CRMSyncConfigError(
        f"Unsupported CRM connector: {config.connector!r}.",
        code="CRM_CONNECTOR_NOT_SUPPORTED",
    )
