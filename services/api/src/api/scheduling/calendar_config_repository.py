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
        "SELECT provider, calendar_id, credentials_ciphertext, busy, enabled "
        "FROM tenant_calendar_configs WHERE tenant_id = $1",
        claims.tenant_id,
    )
    if row is None:
        return None

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
) -> None:
    """Insert or update the caller's tenant calendar config, encrypting credentials.

    Raises ``ValidationError`` for global callers.
    """
    _reject_global(claims)

    box = SecretBox(get_api_settings().secret_encryption_key)
    ciphertext = box.encrypt(credentials)

    await db.execute(
        "INSERT INTO tenant_calendar_configs "
        "(tenant_id, provider, calendar_id, credentials_ciphertext, busy, enabled) "
        "VALUES ($1, $2, $3, $4, $5, $6) "
        "ON CONFLICT (tenant_id) DO UPDATE SET "
        "provider = $2, calendar_id = $3, credentials_ciphertext = $4, busy = $5, "
        "enabled = $6, updated_at = now()",
        claims.tenant_id,
        provider,
        calendar_id,
        ciphertext,
        busy,
        enabled,
    )
