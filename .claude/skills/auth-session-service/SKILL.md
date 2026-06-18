---
name: auth-session-service
description: Use when building or modifying authentication, sessions, or RBAC for the chatbot platform — admin/agent login, JWT issuance in httpOnly cookies, token blacklist/logout, password hashing and reset flows, the four-role RBAC model (PLATFORM_ADMIN/CLIENT_ADMIN/CLIENT_AGENT/VISITOR), and the signed anonymous visitor sessions minted for the widget. Use this for any login, token, permission, or role question.
---

# Auth & Session Service

> Owns identity and the role model. Obey `CLAUDE.md` + `platform-foundations` (AuthClaims, crypto live there).

## Purpose & responsibilities
- Admin/agent authentication: validate credentials, issue JWT (HS256) with claims, set httpOnly+Secure+
  SameSite cookies, validate on each request, blacklist on logout (Redis).
- Password lifecycle: PBKDF2-SHA256 hashing, single-use time-limited reset tokens.
- Issue/verify the **signed visitor sessions** used by the widget (minted via the gateway).
- Define and enforce the **four-role RBAC** model and produce `AuthClaims`.

## Boundaries
- **In scope:** credentials, tokens, sessions, role/permission resolution, password reset.
- **Out of scope:** user CRUD (that's `admin-api`), tenant data access (repositories enforce that).
- **Upstream:** gateway, admin-web. **Downstream:** every service consumes the `AuthClaims` it produces.

## RBAC model
| Role | tenant_id | Scope |
|------|-----------|-------|
| `PLATFORM_ADMIN` | `null` | global — all tenants; platform ops only (keep the set tiny, audited) |
| `CLIENT_ADMIN` | required | own tenant: bot/knowledge/users/config |
| `CLIENT_AGENT` | required | own tenant: review leads & conversations; **no config changes** |
| `VISITOR` | required | anonymous; signed short-lived session only |

JWT claims: `{ sub, role, tenant_id, project_ids?, exp }`. Authorization is enforced at the data layer (a
*filter*), with the API/UI as defense-in-depth.

## Token lifecycles
- **Admin/agent:** login → validate → JWT in httpOnly cookie (Secure, SameSite) → validate per request →
  logout adds jti to Redis blacklist until exp.
- **Visitor:** gateway calls this service to mint a short-TTL signed token carrying `tenant_id` + anonymous
  `visitor_id`; refreshed transparently; no PII.
- **Password reset:** request → time-limited single-use token (stored hashed) → emailed via
  `notification-service` → consume → update hash → invalidate token.

## API contract (representative)
- `POST /auth/login` → sets cookie, returns user profile (no token in body).
- `POST /auth/logout` → blacklists token.
- `POST /auth/password-reset/request` / `POST /auth/password-reset/confirm`.
- `POST /auth/visitor-session` (internal, gateway-only) → signed visitor token.
- `GET /auth/me` → current claims (server-side).

## Patterns & standards
- Auth endpoints rate-limited (10/min by IP) to stop brute force.
- Never store/log plaintext passwords or tokens. Audit login/logout/reset and failed attempts.
- `tenant_id` is taken from the user record at login, never from the request.

## Security & multi-tenancy notes
- A `CLIENT_ADMIN` can only ever mint/act within their own `tenant_id`. Creating `PLATFORM_ADMIN` requires
  existing platform-admin + audit log (rare).
- Visitor tokens are scoped to one tenant and short-lived; compromise blast radius is minimal.

## Observability
- Metrics: login success/fail, reset requests, blacklist size, visitor mint rate. Audit trail for all auth
  events with correlation_id.

## Testing requirements
- Password hash/verify + reset single-use/expiry; JWT issue/validate/blacklist; cookie flags; RBAC per role;
  visitor-token scope; cross-tenant denial; brute-force rate limit.

## Reusable insights (knowledge_base)
- httpOnly cookies over localStorage (XSS). JWTs stateless + Redis blacklist for logout. (`07`, ADR-004)
- RBAC enforced at data layer; reset tokens single-use + time-limited. (`07`, RBAC_MODEL)
