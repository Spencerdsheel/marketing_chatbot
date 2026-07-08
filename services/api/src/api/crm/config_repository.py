"""Per-tenant CRM sync config repository -- secret encrypted at rest.

Mirrors ``api.llm.config_repository``: ``secret_ciphertext`` is stored
encrypted (AES-256-GCM via ``SecretBox``) and decrypted only when building a
``CRMSync`` implementation (``api.crm.sync.crm_sync_for``). Never logged or
echoed by the route layer.
"""
from __future__ import annotations

from dataclasses import dataclass

from common.auth import AuthClaims
from common.crypto import SecretBox
from common.db import Database
from common.errors import ValidationError

from api.config import get_api_settings


@dataclass(frozen=True)
class CRMConfig:
    connector: str
    webhook_url: str | None
    secret: str  # DECRYPTED
    enabled: bool


def _reject_global(claims: AuthClaims) -> None:
    """Raise ``ValidationError`` for global callers (PLATFORM_ADMIN).

    CRM config is always tenant-scoped; a global caller has no tenant_id and
    therefore cannot be filtered to a tenant's row.
    """
    if claims.tenant_id is None:
        raise ValidationError(
            "CRM config repository is tenant-scoped; PLATFORM_ADMIN callers are not permitted.",
            code="GLOBAL_CALLER_NOT_PERMITTED",
        )


async def get_crm_config(db: Database, claims: AuthClaims) -> CRMConfig | None:
    """Fetch the tenant's CRM config, decrypting the secret.

    Raises ``ValidationError`` for global callers (PLATFORM_ADMIN).
    """
    _reject_global(claims)

    row = await db.fetchrow(
        "SELECT connector, webhook_url, secret_ciphertext, enabled "
        "FROM tenant_crm_configs WHERE tenant_id = $1",
        claims.tenant_id,
    )
    if row is None:
        return None

    secret = ""
    ciphertext = row["secret_ciphertext"]
    if ciphertext:
        box = SecretBox(get_api_settings().secret_encryption_key)
        secret = box.decrypt_str(str(ciphertext))

    return CRMConfig(
        connector=str(row["connector"]),
        webhook_url=str(row["webhook_url"]) if row["webhook_url"] is not None else None,
        secret=secret,
        enabled=bool(row["enabled"]),
    )


async def upsert_crm_config(
    db: Database,
    claims: AuthClaims,
    *,
    connector: str,
    webhook_url: str | None,
    secret: str,
    enabled: bool,
) -> None:
    """Insert or update the tenant's CRM config, encrypting the secret.

    Raises ``ValidationError`` for global callers.
    """
    _reject_global(claims)

    box = SecretBox(get_api_settings().secret_encryption_key)
    ciphertext = box.encrypt(secret)

    await db.execute(
        "INSERT INTO tenant_crm_configs "
        "(tenant_id, connector, webhook_url, secret_ciphertext, enabled) "
        "VALUES ($1, $2, $3, $4, $5) "
        "ON CONFLICT (tenant_id) DO UPDATE SET "
        "connector = $2, webhook_url = $3, secret_ciphertext = $4, enabled = $5, "
        "updated_at = now()",
        claims.tenant_id,
        connector,
        webhook_url,
        ciphertext,
        enabled,
    )
