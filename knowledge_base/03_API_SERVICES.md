# API Services

## REST API Design Philosophy

### Resource-Based URL Design
- URLs represent resources, not actions: /projects, /projects/ID/visits
- HTTP verbs convey intent: GET (read), POST (create/trigger), PATCH (update)
- Nested resources reflect relationships: /projects/ID/summary
- No verbs in URLs

**Reusable Insight:** RESTful URLs should be self-documenting. A developer should understand what an endpoint does by reading the URL and HTTP method alone.

### Pydantic Request/Response Models
Every endpoint uses Pydantic models for request validation (automatic 422 on invalid input), response serialization (consistent output shape), API documentation (auto-generated OpenAPI schema), and type safety across the codebase.

**Reusable Insight:** Define your API contract in code, not in documentation. Pydantic models serve as both validation and documentation.

### Dependency Injection for Cross-Cutting Concerns
FastAPI dependencies handle authentication (extract and validate JWT), authorization (check role and permissions), repository provisioning (select implementation), and database session management.

**Reusable Insight:** Dependencies are the ideal place for cross-cutting concerns. They run before the endpoint handler and can short-circuit the request.

## Caching Strategy

### Cache-Aside Pattern Implementation
Request checks cache (Redis), cache hit returns cached data, cache miss fetches from DB, stores in cache, returns data.

### Cache Key Design
- Include tenant context: summary:tenant_id:project_id
- Include resource type: visits:tenant_id:project_id
- Use pattern prefixes for bulk invalidation: tenant:tenant_id:*

### TTL Strategy
| Data Type | TTL | Rationale |
|-----------|-----|-----------|
| Summary | 5 minutes | Changes infrequently, high read volume |
| Visits | 2 minutes | More dynamic, moderate read volume |
| User profile | 30 minutes | Rarely changes |
| Configuration | 60 minutes | Changes very rarely |

**Reusable Insight:** TTLs should reflect data volatility, not a one-size-fits-all value. High-volatility data gets shorter TTLs.

### Cache Invalidation
- Invalidate on data mutations (POST, PATCH)
- Use pattern scanning for tenant-wide invalidation
- Invalidate after ingestion completes
- Never invalidate on read paths

**Reusable Insight:** Cache invalidation is harder than caching. Keep invalidation logic close to the mutation point.

## Rate Limiting

### Multi-Tier Rate Limiting
| Tier | Limit | Window | Purpose |
|------|-------|--------|---------|
| Authentication | 10 requests | 1 minute | Prevent brute force |
| Admin operations | 5 requests | 1 hour | Prevent misuse |
| Global API | 100 requests | 1 minute | Prevent abuse |

### Implementation Strategy
- Redis-backed for distributed deployments
- In-memory fallback for single-instance or Redis unavailable
- Sliding window algorithm for accuracy
- Rate limit headers in response (X-RateLimit-Limit, X-RateLimit-Remaining)

**Reusable Insight:** Rate limiting is a security concern, not a performance concern. Implement it even if you don't expect high traffic.

### Rate Limit Key Design
- Auth endpoints: by IP address
- Authenticated endpoints: by user ID
- Admin endpoints: by user ID + role

**Reusable Insight:** Rate limit by identity when possible, by IP when not. Identity-based limits are more accurate and harder to circumvent.

## Error Response Design

### Consistent Error Format
Error responses include error code (UPPER_SNAKE_CASE), user-friendly message, and correlation_id for debugging.

### Error Code Convention
- UPPER_SNAKE_CASE for machine parsing
- Stable across API versions
- Documented in API specification
- Mapped to HTTP status codes

**Reusable Insight:** Error codes are part of your API contract. Change them as carefully as you change endpoint URLs.

### Correlation ID Propagation
- Generated at request entry (Nginx or middleware)
- Propagated through all service layers
- Included in all log entries
- Returned in error responses

**Reusable Insight:** Correlation IDs are the single most useful debugging tool in distributed systems. Implement them from day one.

## Health and Readiness Endpoints

### /healthz
- Returns 200 if the service is running
- No dependencies checked
- Used by load balancers for liveness probes

### /readyz
- Returns 200 if the service can serve traffic
- Checks database connectivity
- Checks Redis connectivity
- Used by orchestrators for readiness probes

### /metrics
- Prometheus metrics endpoint
- Request counts, latencies, error rates
- Business metrics (active tenants, ingestion status)

**Reusable Insight:** Health and readiness are different. Liveness means the process is running; readiness means it can serve traffic. Separate them.
