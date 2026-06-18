---
name: api-gateway-bff
description: Use when building or modifying the edge/gateway layer of the chatbot platform — Nginx config, the FastAPI BFF, request routing, SSL/security headers, CORS, correlation-ID generation, rate limiting, validation of the widget public client key against the per-tenant Origin allowlist, and minting short-lived signed visitor sessions. Start here for anything about how requests enter the system or how the widget authenticates.
---

# API Gateway / BFF

> The edge of the system. Everything external enters here. Obey `CLAUDE.md` + `platform-foundations`.

## Purpose & responsibilities
- **Nginx edge:** SSL/TLS termination, path-based routing, security headers, compression, generating a
  `correlation_id` per request if absent.
- **FastAPI BFF:** central error middleware, CORS, rate limiting, and **widget admission control** — validate
  the public client key + Origin, then mint a signed visitor session.
- Aggregate/forward to core modules; never contains business logic.

## Boundaries
- **In scope:** routing, edge auth/admission, rate limiting, correlation IDs, error envelope, CORS/headers.
- **Out of scope:** conversation logic, lead/scheduling rules, persistence. Delegate to the relevant service.
- **Upstream:** widget, admin-web, external callers. **Downstream:** all core modules + `auth-session-service`.

## Routing (Nginx, from knowledge_base/08)
- `/api/*` → BFF/backend · `/auth/*` → auth · `/admin/*` → admin-api · `/widget/*` → widget admission
  endpoints · `/metrics`, `/healthz`, `/readyz` → backend · `/` → admin-web (or static widget host).

## Widget admission flow (the security-critical part)
1. Widget loads with a **public client key** (`pk_...`, non-secret, identifies the tenant).
2. `POST /widget/session` arrives with the client key; the gateway:
   - looks up the tenant by client key;
   - validates the request **`Origin`/`Referer` against that tenant's domain allowlist** (reject otherwise);
   - applies **rate limiting by IP + client key**;
   - mints a **short-lived signed visitor session** (JWT/PASETO) carrying `tenant_id` + a fresh anonymous
     `visitor_id`, returned as a bearer token (cross-origin) and/or httpOnly cookie where possible.
3. Subsequent widget calls present the visitor session; the gateway resolves `AuthClaims(role=VISITOR,
   tenant_id=...)` and forwards. **The widget never sends `tenant_id` directly.**

## API contract (representative)
- `POST /widget/session` → `{ visitor_token, expires_at }` (422 bad key, 403 origin not allowed, 429 limited).
- All proxied responses carry `X-Correlation-Id`, `X-RateLimit-*` headers.
- Errors use the standard envelope `{ error_code, message, correlation_id }`.

## Patterns & standards
- Multi-tier rate limiting (knowledge_base/03): auth 10/min by IP, admin 5/hr by user, global 100/min;
  Redis-backed with in-memory fallback; sliding window.
- Central error middleware translates `AppException` → HTTP (see `platform-foundations`).
- Security headers (HSTS, X-Frame-Options DENY, nosniff, CSP, Referrer-Policy) at Nginx. Strict CORS:
  explicit allowed origins (no wildcard), credentials for authenticated requests.
- Correlation ID generated at the edge, propagated downstream, returned in responses + every log line.

## Security & multi-tenancy notes
- The Origin allowlist is the primary defense against client-key theft / unauthorized embedding.
- Tenant is resolved at the edge and carried in claims; downstream services trust claims, not raw input.

## Observability
- Metrics: request count/latency/error rate per route, rate-limit rejections, widget-session mint rate,
  origin-rejection count. All logs carry correlation_id + tenant_id.

## Testing requirements
- Origin allowlist accept/reject; client-key → tenant resolution; rate-limit thresholds; visitor session
  mint + downstream claim resolution; error-envelope shape; CORS preflight.

## Reusable insights (knowledge_base)
- Rate limiting is a security concern; rate limit by identity when possible, IP otherwise. (`03`)
- Correlation IDs are the single most useful debugging tool in distributed systems. (`03`)
- Nginx is the edge: SSL, routing, headers, compression — keep it simple. (`08`)
