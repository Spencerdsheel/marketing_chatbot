# System Design

## Architecture Overview

### Layered Architecture Pattern

The system follows a clear layered architecture with strict boundaries:

`
+--------------------------------------------------+
|                    Client Layer                  |
|  (Next.js App Router, React Server Components)   |
+--------------------------------------------------+
|               Provider Abstraction Layer         |
|  (Strategy Pattern: REST / Sample / Direct API)  |
+--------------------------------------------------+
|                 API Gateway Layer                |
|  (Nginx: SSL termination, path-based routing)    |
+--------------------------------------------------+
|              Backend Service Layer               |
|  (FastAPI: REST API, Auth, Admin, Health)        |
+--------------------------------------------------+
|              Repository Layer                    |
|  (Protocol: InMemory / Postgres implementations) |
+--------------------------------------------------+
|              Data Layer                          |
|  (PostgreSQL, Redis)                             |
+--------------------------------------------------+
`

### Key Design Principles

#### 1. Separation of Concerns
- **Frontend** handles presentation and user interaction only
- **Backend** handles business logic, data access, and security
- **Ingestion** runs as a separate process (Celery workers)
- **Database** is never accessed directly by the frontend

#### 2. Strategy Pattern for Data Sources
The provider abstraction allows swapping data sources without changing UI code:
- **REST API Provider** - Production: calls backend API
- **Sample Data Provider** - Development: static data, no backend needed
- **Direct API Provider** - Alternative: calls external API directly

**Reusable Insight:** Define interfaces (Protocols/TypeScript interfaces) at the boundary. Implementations can be swapped via environment configuration.

#### 3. Repository Pattern for Data Access
- Define a Protocol/interface for all data operations
- Implement for each storage backend (memory, PostgreSQL, etc.)
- Switch implementations via configuration
- All methods accept tenant context as a required parameter

**Reusable Insight:** The repository pattern decouples business logic from storage details. Use language-native interface mechanisms (Python Protocol, TypeScript interface).

#### 4. Multi-Tenancy as First-Class Concern
- Tenant ID is established at data ingestion time
- Tenant ID is embedded in authentication tokens
- Every data access requires tenant-scoped credentials
- Tenant ID is never accepted from user input
- Data isolation is enforced at the repository layer, not the API layer

**Reusable Insight:** Multi-tenancy should be baked into the data access layer, not bolted on at the API layer. The repository should reject any request without proper tenant context.

#### 5. Server-First Architecture
- Data fetching happens on the server (React Server Components)
- Form submissions handled by server actions
- Session state stored in httpOnly cookies (not localStorage)
- Client JavaScript is minimized to interactive components only

**Reusable Insight:** With modern frameworks supporting server components, push as much logic to the server as possible. This reduces bundle size, improves security, and simplifies state management.

#### 6. Graceful Degradation with Explicit Boundaries
- Redis unavailable -> fall back to in-memory rate limiting
- Replica database unavailable -> fall back to primary
- **BUT:** Never silently fall back from live data to sample data

**Reusable Insight:** Define which fallbacks are acceptable (infrastructure) and which are not (data integrity). Document these boundaries clearly.

## Component Communication Patterns

### Synchronous Communication
- Frontend -> Backend: REST API over HTTPS
- Backend -> Database: Async SQL (asyncpg)
- Backend -> Redis: Sync/async depending on context

### Asynchronous Communication
- Celery workers process ingestion tasks
- Redis acts as message broker
- Celery Beat schedules periodic tasks

**Reusable Insight:** Use async processing for anything that:
- Takes longer than a request cycle
- Is not user-facing
- Can be retried on failure
- Benefits from batching

## Configuration Management

### Environment Variable Strategy
- All configuration via environment variables
- Pydantic Settings for validation and type safety
- .env.example as documentation, not defaults
- Different env vars for dev vs prod

**Reusable Insight:** Use Pydantic Settings (Python) or Zod schema (TypeScript) to validate environment variables at startup. Fail fast if required configuration is missing.

### Configuration Categories
| Category | Examples | Validation |
|----------|----------|------------|
| Database | Host, port, credentials, pool size | Required, format validated |
| Redis | Host, port, password | Optional, graceful fallback |
| Security | JWT secret, encryption key | Required, minimum length |
| Feature Flags | Repository type, data provider | Enum validation |

## Scalability Considerations

### Horizontal Scaling
- Stateless API servers (multiple instances behind Nginx)
- Stateless frontend (Next.js standalone)
- Redis shared state for rate limiting and caching
- PostgreSQL connection pooling via PgBouncer

### Vertical Scaling Points
- Database: Connection pool size, work_mem, shared_buffers
- Redis: Max memory, eviction policy
- Celery: Worker concurrency, prefetch multiplier

**Reusable Insight:** Design for horizontal scaling from day one. Even if you start with a single instance, the architecture should support adding instances without code changes.

## Error Handling Philosophy

### Layered Error Handling
1. **Repository Layer:** Converts DB errors to domain exceptions
2. **Service Layer:** Adds business context to errors
3. **API Layer:** Converts to HTTP responses with correlation IDs
4. **Frontend Layer:** Displays user-friendly messages

### Error Categories
- **NotFoundError** (404) - Resource doesn't exist
- **AuthorizationError** (401/403) - Auth or permission issue
- **RateLimitError** (429) - Too many requests
- **ValidationError** (422) - Invalid input
- **InternalServerError** (500) - Unexpected failure

**Reusable Insight:** Never expose internal error details to clients. Always include a correlation ID for debugging. Log the full error server-side.
