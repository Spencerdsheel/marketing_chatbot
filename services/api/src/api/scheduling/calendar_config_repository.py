"""Per-tenant calendar config repository -- credentials encrypted at rest.

Mirrors ``api.crm.config_repository`` / ``api.llm.config_repository``:
``credentials_ciphertext`` is stored encrypted (AES-256-GCM via ``SecretBox``)
and decrypted only when building a ``CalendarProvider``
(``api.scheduling.calendar.calendar_provider_for``). Never logged or echoed
by the route layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from common.auth import AuthClaims
from common.crypto import SecretBox
from common.db import Database
from common.errors import ValidationError

from api.config import get_api_settings


@dataclass(frozen=True)
class CalendarConfig:
    """A tenant's calendar sync config, credentials decrypted."""

    provider: str
    calendar_id: str | None
    credentials: str  # DECRYPTED
    busy: list[dict[str, Any]]
    enabled: bool
    scheduling_url: str | None = None


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN).

    Calendar config is always tenant-scoped; a global caller has no
    tenant_id and therefore cannot be filtered to a tenant's row.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "Calendar config repository is tenant-scoped; PLATFORM_ADMIN callers "
            "are not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )


async def get_calendar_config(db: Database, claims: AuthClaims) -> CalendarConfig | None:
    """Fetch the caller's tenant calendar config, decrypting the credentials.

    Returns ``None`` if no calendar has been configured for the tenant.
    Raises ``ValidationError`` for global callers.
    """
    _reject_global(claims)

    row = await db.fetchrow(
        "SELECT provider, calendar_id, credentials_ciphertext, busy, enabled, scheduling_url "
        "FROM tenant_calendar_configs WHERE tenant_id = $1",
        claims.tenant_id,
    )
    if row is None:
        return None

    return _row_to_calendar_config(row)


async def get_calendar_config_by_tenant_id(db: Database, tenant_id: str) -> CalendarConfig | None:
    """Fetch a tenant's calendar config by RAW tenant id -- NO ``AuthClaims``.

    Used ONLY by the Calendly webhook receiver (``api.scheduling.calendly_webhook``),
    which has no session/claims at all (SR-6 decision 4a): the signature IS
    the auth, and the path ``{tenant_id}`` is used solely to load that
    tenant's decrypted signing secret to VERIFY the signature -- it is never
    trusted as authentication on its own. Every other caller in this module
    MUST go through the ``AuthClaims``-scoped ``get_calendar_config`` above;
    this function exists to serve the one legitimate claims-less caller
    without weakening the tenant-scoping convention elsewhere.
    """
    row = await db.fetchrow(
        "SELECT provider, calendar_id, credentials_ciphertext, busy, enabled, scheduling_url "
        "FROM tenant_calendar_configs WHERE tenant_id = $1",
        tenant_id,
    )
    if row is None:
        return None

    return _row_to_calendar_config(row)


def _row_to_calendar_config(row: Any) -> CalendarConfig:
    credentials = ""
    ciphertext = row["credentials_ciphertext"]
    if ciphertext:
        box = SecretBox(get_api_settings().secret_encryption_key)
        credentials = box.decrypt_str(str(ciphertext))

    busy = row["busy"] if row["busy"] is not None else []

    return CalendarConfig(
        provider=str(row["provider"]),
        calendar_id=str(row["calendar_id"]) if row["calendar_id"] is not None else None,
        credentials=credentials,
        busy=list(busy),
        enabled=bool(row["enabled"]),
        scheduling_url=(
            str(row["scheduling_url"]) if row["scheduling_url"] is not None else None
        ),
    )


async def upsert_calendar_config(
    db: Database,
    claims: AuthClaims,
    *,
    provider: str,
    calendar_id: str | None,
    credentials: str,
    busy: list[dict[str, Any]],
    enabled: bool,
    scheduling_url: str | None = None,
) -> None:
    """Insert or update the caller's tenant calendar config, encrypting credentials.

    ``scheduling_url`` (SR-6) is NOT a secret -- stored plaintext, unlike
    ``credentials``. Only meaningful for ``provider="calendly"``; the caller
    passes ``None`` for other providers.

    Raises ``ValidationError`` for global callers.
    """
    _reject_global(claims)

    box = SecretBox(get_api_settings().secret_encryption_key)
    ciphertext = box.encrypt(credentials)

    await db.execute(
        "INSERT INTO tenant_calendar_configs "
        "(tenant_id, provider, calendar_id, credentials_ciphertext, busy, enabled, scheduling_url) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) "
        "ON CONFLICT (tenant_id) DO UPDATE SET "
        "provider = $2, calendar_id = $3, credentials_ciphertext = $4, busy = $5, "
        "enabled = $6, scheduling_url = $7, updated_at = now()",
        claims.tenant_id,
        provider,
        calendar_id,
        ciphertext,
        busy,
        enabled,
        scheduling_url,
    )
