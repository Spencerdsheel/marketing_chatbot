# Architectural Decision Records

## ADR-001: Server-First Architecture

### Context
Modern web frameworks support server-side rendering and server components. The question was whether to build a traditional SPA or a server-first application.

### Decision
Use Next.js App Router with React Server Components as the default. Client components only for interactivity.

### Consequences
**Positive:**
- Reduced client JavaScript bundle
- Simpler state management (no Redux needed)
- Better SEO and initial load performance
- Server-side security (no secrets in client)

**Negative:**
- Server infrastructure required
- More complex deployment
- Learning curve for RSC patterns

## ADR-002: Repository Pattern for Data Access

### Context
How should the application access data? Direct SQL in route handlers? An ORM? A repository abstraction?

### Decision
Use the Repository pattern with Protocol interface. Two implementations: InMemory (dev) and Postgres (prod). Switch via environment variable.

### Consequences
**Positive:**
- Easy to test with InMemory implementation
- Development without database
- Clear separation of concerns
- Easy to add new storage backends

**Negative:**
- More code to maintain
- Protocol must be kept in sync with implementations
- Slight performance overhead

## ADR-003: Multi-Tenancy at Data Access Layer

### Context
How should multi-tenancy be enforced? At the API layer? At the UI layer? At the data access layer?

### Decision
Enforce multi-tenancy at the repository layer. Every method requires AuthClaims with tenant_id. Tenant ID is never accepted from user input.

### Consequences
**Positive:**
- Impossible to access another tenant's data
- API layer doesn't need tenant checks
- Clear security boundary

**Negative:**
- Every method must accept claims
- Slightly more complex repository interface
- Testing requires mock claims

## ADR-004: JWT in httpOnly Cookies

### Context
Where should JWT tokens be stored? localStorage? sessionStorage? httpOnly cookies?

### Decision
Store JWT tokens in httpOnly cookies with Secure and SameSite flags.

### Consequences
**Positive:**
- XSS-resistant (JavaScript can't access cookie)
- Automatic with requests
- Secure flag prevents transmission over HTTP
- SameSite prevents CSRF

**Negative:**
- CSRF protection still needed (handled by Next.js)
- Cookie size limits
- Cross-origin requests more complex

## ADR-005: No ORM for Database Access

### Context
Should we use an ORM (SQLAlchemy, Prisma) or raw SQL for database access?

### Decision
Use raw async SQL (asyncpg) for read-heavy operations. SQLAlchemy available for migrations only.

### Consequences
**Positive:**
- Full control over queries
- Better performance for reads
- No ORM abstraction overhead
- Explicit transaction management

**Negative:**
- More SQL to write and maintain
- No automatic relationship management
- Migration tooling separate from query code

## ADR-006: Celery for Background Processing

### Context
How should background tasks be handled? In-process threads? A task queue? Serverless functions?

### Decision
Use Celery with Redis broker for background tasks. Celery Beat for scheduled tasks.

### Consequences
**Positive:**
- Mature, well-tested library
- Retry logic built in
- Monitoring and management tools
- Scales horizontally

**Negative:**
- Additional infrastructure (Redis, Celery workers)
- More complex deployment
- Debugging distributed tasks harder

## ADR-007: shadcn/ui for Component Library

### Context
Should we use a component library (MUI, Chakra) or build our own? Or use shadcn/ui?

### Decision
Use shadcn/ui for UI primitives. Copy-paste pattern gives full control over component code.

### Consequences
**Positive:**
- Accessible by default (Radix UI)
- Fully customizable
- No library lock-in
- Tailwind CSS integration

**Negative:**
- More code to maintain
- Updates are manual
- No automatic component upgrades

## ADR-008: PgBouncer for Connection Pooling

### Context
How should PostgreSQL connections be managed? Direct connections? A connection pooler?

### Decision
Use PgBouncer in transaction mode for connection pooling. Max 500 client connections.

### Consequences
**Positive:**
- Efficient connection multiplexing
- Protects database from connection storms
- Transparent to application
- Battle-tested

**Negative:**
- Additional infrastructure
- Configuration complexity
- Transaction mode limitations (no prepared statements)

## ADR-009: AES-256-GCM for Secret Encryption

### Context
How should provider secrets (API keys, OAuth tokens) be stored? Plain text? Encrypted? Hashed?

### Decision
Encrypt secrets at rest using AES-256-GCM. Key stored in environment variable.

### Consequences
**Positive:**
- Secrets useless if database is breached
- Authenticated encryption (tamper detection)
- Industry standard algorithm

**Negative:**
- Key management complexity
- Performance overhead (minimal)
- Key rotation requires re-encryption

## ADR-010: No Silent Fallbacks

### Context
Should the application fall back from live data to sample data when the backend is unavailable?

### Decision
Never silently fall back from live data to sample data. Explicit failures are better than hidden degradation.

### Consequences
**Positive:**
- Users know when something is wrong
- No data inconsistency
- Easier debugging

**Negative:**
- Worse user experience during outages
- Requires explicit error handling
- No graceful degradation for data
