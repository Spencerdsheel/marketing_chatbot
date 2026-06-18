# Backend Philosophy

## Core Principles

### 1. FastAPI as the Foundation
FastAPI provides automatic OpenAPI/Swagger documentation, Pydantic validation for request/response models, dependency injection for cross-cutting concerns, and async support for high-concurrency workloads.

**Reusable Insight:** Choose a framework that gives you validation, documentation, and dependency injection out of the box. These reduce boilerplate and enforce consistency.

### 2. Dependency Injection Pattern
FastAPI dependency injection is used for authentication claims extraction, repository instance provisioning, database session management, and tenant context propagation.

**Reusable Insight:** Use dependency injection for anything that is needed across multiple endpoints, has different implementations (dev vs prod), needs setup/teardown lifecycle, or carries request-scoped context.

### 3. Repository Pattern with Protocol
Define the contract via Protocol, implement for each backend, switch via environment variable. All methods require tenant-scoped credentials (AuthClaims).

**Reusable Insight:**
- Protocol defines the interface, not the implementation
- Switch implementations via environment variable
- All methods require tenant-scoped credentials
- No method should work without tenant context

### 4. Async-First Database Access
Using asyncpg directly (no ORM) gives full control over SQL queries, no ORM abstraction overhead, explicit transaction management, and better performance for read-heavy workloads.

**Reusable Insight:** For read-heavy dashboards and analytics, raw async SQL often outperforms ORMs. Use an ORM only when you need complex relationship management or write-heavy workflows.

### 5. Multi-Tenancy Enforcement
Tenant isolation is enforced at multiple layers: Request contains JWT with tenant_id, dependency extracts claims, repository methods require claims, SQL queries filter by tenant_id, response strips internal tenant fields.

**Key Rules:**
- Tenant ID is NEVER accepted from user input
- Tenant ID is established at ingestion time and is immutable
- Every repository method requires AuthClaims with tenant_id
- Client-facing responses strip internal tenant-scoped fields

**Reusable Insight:** Multi-tenancy is a data access concern, not an API concern. Enforce it where data is accessed, not where it is exposed.

### 6. Structured Logging
JSON structured logging with correlation ID per request, log levels (DEBUG, INFO, WARNING, ERROR), contextual fields (tenant_id, user_id, endpoint), and machine-parseable format for log aggregation.

**Reusable Insight:** Log in JSON format from day one. It costs nothing extra and makes debugging in production dramatically easier.

### 7. Settings Management
Pydantic Settings for configuration provides type validation at startup, environment variable mapping, default values where appropriate, and required field enforcement.

**Reusable Insight:** Fail fast on startup if required configuration is missing. Don't discover missing config at runtime.

## Data Access Patterns

### Cache-Aside Pattern
Cache keys should include tenant context. TTLs should be tuned per endpoint. Invalidate cache on data mutations. Use pattern scanning for bulk invalidation.

**Reusable Insight:** Cache-aside is the simplest and most effective caching pattern for most web applications.

### Connection Pooling
- PgBouncer in transaction mode
- Pool size tuned to workload
- Connection timeout handling
- Graceful connection recovery

**Reusable Insight:** Always use connection pooling for PostgreSQL. PgBouncer in transaction mode is the sweet spot for most web applications.

## Background Processing

### Celery for Async Tasks
Celery handles scheduled data ingestion, manual refresh triggers, retry logic with exponential backoff, and task monitoring and logging.

**Reusable Insight:**
- Use Celery for anything that takes more than 1 second
- Configure retry policies for external API calls
- Monitor task queues for backlog
- Use Celery Beat for cron-like scheduling

### Task Design Principles
- Idempotent tasks (safe to retry)
- Atomic operations (all or nothing)
- Clear success/failure states
- Detailed logging for debugging

**Reusable Insight:** Design every background task as if it will be retried 3 times. Because it will be.

## Error Handling

### Custom Exception Hierarchy
AppException base class with NotFoundError (404), AuthorizationError (401/403), RateLimitError (429), ValidationError (422).

### Centralized Error Handler
Single middleware catches all exceptions and maps to appropriate HTTP status codes, includes correlation ID in response, logs full error details server-side, and returns user-friendly messages to clients.

**Reusable Insight:** Never let framework default error responses reach clients. Always wrap with your own error handler that includes correlation IDs and consistent formatting.

## Security Philosophy

### Defense in Depth
1. Network Level: Nginx security headers, CORS
2. Application Level: Rate limiting, input validation
3. Authentication Level: JWT with httpOnly cookies
4. Authorization Level: RBAC, tenant isolation
5. Data Level: AES encryption for secrets, PBKDF2 for passwords

**Reusable Insight:** Each layer should assume the layers above it have been compromised. Defense in depth means no single point of failure.

### Password Handling
- PBKDF2-SHA256 with 120,000 iterations
- Salt generated per password
- Timing-attack resistant comparison
- Password reset via time-limited tokens

**Reusable Insight:** Never roll your own crypto. Use well-tested libraries for hashing and encryption.

### Secret Encryption
- AES-256-GCM for encrypting provider secrets
- Key stored in environment variable
- Nonce generated per encryption
- Auth tag verified on decryption

**Reusable Insight:** Encrypt sensitive configuration at rest. API keys, OAuth tokens, and connection strings should never be stored in plain text in the database.
