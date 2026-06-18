"""AuthClaims — the tenant boundary — and the four-role RBAC model.

``AuthClaims`` is the only object that carries ``tenant_id`` through the system. It is
minted from a validated admin JWT or a gateway-signed visitor session — NEVER from a
path/query/body parameter. The invariant enforced here is the load-bearing one for
multi-tenancy:

- ``PLATFORM_ADMIN`` → ``tenant_id is None`` (global scope, no tenant filter).
- every other role → a non-empty ``tenant_id`` is REQUIRED.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from common.errors import ValidationError


class Role(StrEnum):
    """Platform RBAC roles. Stored in JWT claims; enforced at the data layer."""

    PLATFORM_ADMIN = "PLATFORM_ADMIN"  # global operator, tenant_id is None
    CLIENT_ADMIN = "CLIENT_ADMIN"      # manages own tenant
    CLIENT_AGENT = "CLIENT_AGENT"      # reviews leads/conversations, no config
    VISITOR = "VISITOR"                # anonymous, signed short-lived session


@dataclass(frozen=True)
class AuthClaims:
    """Immutable, tenant-scoped identity passed to every repository method."""

    subject: str                      # user_id (admin/agent) or visitor_id
    role: Role
    tenant_id: str | None             # None ONLY for PLATFORM_ADMIN
    project_ids: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if self.role is Role.PLATFORM_ADMIN:
            if self.tenant_id is not None:
                raise ValidationError(
                    "PLATFORM_ADMIN is global and must not carry a tenant_id.",
                    code="INVALID_AUTH_CLAIMS",
                )
        else:
            if self.tenant_id is None or not self.tenant_id.strip():
                raise ValidationError(
                    f"Role {self.role.value} requires a non-empty tenant_id.",
                    code="INVALID_AUTH_CLAIMS",
                )

    @property
    def is_platform_admin(self) -> bool:
        return self.role is Role.PLATFORM_ADMIN

    @property
    def is_global(self) -> bool:
        """True when the caller is not scoped to a single tenant."""
        return self.tenant_id is None
