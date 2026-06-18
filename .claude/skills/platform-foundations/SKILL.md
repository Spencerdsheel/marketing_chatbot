---
name: platform-foundations
description: Use when building or modifying anything in services/common or any shared cross-cutting concern of the chatbot platform — the repository Protocol, AuthClaims/tenant context, multi-tenancy enforcement, error hierarchy, Pydantic Settings, structured logging, cache-aside helpers, pgvector access, RBAC primitives, or AES/PBKDF2 crypto. Every other service skill depends on this one.
---

# Platform Foundations (`services/common`)

> Shared library every service imports. This skill is the deep reference for the universal patterns named in
> `CLAUDE.md`. If you are writing a repository, handling auth claims, raising an error, reading config,
> logging, caching, or touching crypto/pgvector, the shapes live here. **Read `CLAUDE.md` first.**

## Purpose & responsibilities
Provide the single, consistent implementation of cross-cutting concerns so no service reinvents them:
- Repository `Protocol` base + tenant-scoping helpers.
- `AuthClaims` (the only carrier of `tenant_id`) and RBAC primitives.
- Exception hierarchy + the contract the gateway error middleware relies on.
- Pydantic `Settings`, structured JSON logging, correlation-ID context.
- Cache-aside helpers (tenant-scoped keys), Redis client with in-memory fallback.
- pgvector access helpers.
- Crypto: AES-256-GCM secret box + PBKDF2 password hashing.

## Boundaries
- **In scope:** generic, tenant-agnostic-but-tenant-enforcing primitives reused everywhere.
- **Out of scope:** any business logic (lead pipeline, booking rules, prompt building). Those live in their
  own services and *depend on* these primitives.
- **Downstream:** every service. A breaking change here is a breaking change everywhere — version carefully.

## Key contracts

### AuthClaims (the tenant boundary)
```python
class Role(str, Enum):
    PLATFORM_ADMIN = "PLATFORM_ADMIN"
    CLIENT_ADMIN = "CLIENT_ADMIN"
    CLIENT_AGENT = "CLIENT_AGENT"
    VISITOR = "VISITOR"

@dataclass(frozen=True)
class AuthClaims:
    subject: str                 # user_id or visitor_id
    role: Role
    tenant_id: str | None        # None ONLY for PLATFORM_ADMIN (global scope)
    project_ids: tuple[str, ...] = ()   # optional finer scoping
    # PLATFORM_ADMIN: tenant_id is None → global access (no tenant filter)
    # all other roles: tenant_id REQUIRED; requests without it are rejected
```
- `tenant_id` enters the system **only** from a validated admin JWT or a gateway-minted visitor session.
  Never from a path/query/body parameter.

### Repository Protocol + tenancy helpers
```python
class Repository(Protocol):
    """All data methods take claims first and filter by claims.tenant_id."""
    async def get(self, claims: AuthClaims, id: str) -> dict | None: ...
    async def list(self, claims: AuthClaims, **filters) -> list[dict]: ...

def tenant_filter(claims: AuthClaims) -> tuple[str, list]:
    """Returns ('AND tenant_id = $N', [tenant_id]) — or ('', []) for PLATFORM_ADMIN global scope."""

def assert_tenant_access(claims: AuthClaims, row_tenant_id: str) -> None:
    """Raise AuthorizationError if claims may not touch this row."""
```
- Switch implementation (InMemory for dev/tests, Postgres for prod) via env (`REPOSITORY=memory|postgres`).
- Every SQL query is parameterized (`$1, $2`) — never f-strings/`%` formatting.

### Error hierarchy
```python
class AppException(Exception):
    code: str          # UPPER_SNAKE_CASE, stable, part of the API contract
    http_status: int
    message: str       # user-safe
class NotFoundError(AppException): http_status = 404
class AuthorizationError(AppException): http_status = 403   # 401 when unauthenticated
class RateLimitError(AppException): http_status = 429
class ValidationError(AppException): http_status = 422
class InternalServerError(AppException): http_status = 500
```
The gateway middleware (see `api-gateway-bff`) catches these, attaches `correlation_id`, logs server-side,
returns `{error_code, message, correlation_id}`.

### Settings
```python
class Settings(BaseSettings):
    deployment_mode: Literal["saas", "single_tenant"]  # drives hybrid behavior
    database_url: str
    redis_url: str | None = None     # optional → graceful in-memory fallback
    jwt_secret: str                  # required, min length enforced
    secret_encryption_key: str       # 32 bytes for AES-256-GCM
    # validate at import; FAIL FAST if required values missing
```

### Logging & correlation
- `get_logger(__name__)` → JSON logs. A `correlation_id` ContextVar is set by the gateway and auto-injected
  into every log line, plus `tenant_id`, `user_id`/`visitor_id`, `endpoint`. **Never** log secrets/tokens/PII.

### Cache-aside helpers
```python
def cache_key(claims: AuthClaims, kind: str, *parts: str) -> str:
    # e.g. "tenant:{tenant_id}:{kind}:{...}" — ALWAYS tenant-scoped
async def cache_get_or_set(key, ttl, loader): ...
async def invalidate(pattern: str): ...   # used on mutations only
```

### pgvector access
- Embeddings stored in a `vector(N)` column in tenant-scoped tables. Similarity via `<=>` (cosine) with an
  index (IVFFlat/HNSW). Queries **always** include the tenant filter. Exposed through the repository pattern;
  there is exactly one implementation (pgvector) — do not add a second vector backend.

### Crypto
- `SecretBox` — AES-256-GCM (unique nonce per encryption, verified auth tag) for provider keys/OAuth tokens.
- `hash_password` / `verify_password` — PBKDF2-SHA256, 120k iterations, per-password salt, constant-time
  compare. Never invent crypto.

## Security & multi-tenancy notes
- This library is where tenant isolation is *guaranteed*. A repository method that forgets `tenant_filter`
  is a critical security bug. Make the safe path the only easy path (helpers, not raw SQL in services).
- `assert_tenant_access` runs even for reads fetched by primary key.

## Observability
- Expose helpers for `/healthz`, `/readyz` (DB + Redis checks), and Prometheus registry so each process wires
  them identically.

## Testing requirements
- Unit tests for `tenant_filter`/`assert_tenant_access` across all four roles.
- Crypto round-trip + tamper-detection tests; password hash/verify timing-safety.
- Settings fail-fast tests (missing required env).
- An InMemory repository used as the test double for every downstream service.

## Reusable insights (knowledge_base)
- Multi-tenancy is a *data-access* concern, enforced where data is accessed — not at the API. (`02`, ADR-003)
- Protocol defines the interface; implementations swap via env. (`02`, ADR-002)
- Fail fast on missing config; JSON logs from day one; correlation IDs everywhere. (`02`, `03`, `08`)
- Encrypt secrets at rest; never roll your own crypto. (`07`, ADR-009)
