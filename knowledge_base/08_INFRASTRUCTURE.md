# Infrastructure

## Container Architecture

### Docker Multi-Stage Builds
Frontend and backend use multi-stage builds:
- **Stage 1: Dependencies** - Install packages
- **Stage 2: Builder** - Compile/build application
- **Stage 3: Runner** - Minimal runtime image

**Reusable Insight:** Multi-stage builds produce smaller images. The builder stage has all tools; the runner stage has only what's needed.

### Non-Root Containers
- Backend runs as non-root user
- Frontend runs as non-root user
- File permissions set explicitly

**Reusable Insight:** Never run containers as root. If a container is compromised, root access gives the attacker full control.

### Health Checks
- Backend: HTTP check on /healthz
- Frontend: HTTP check on /
- Database: pg_isready
- Redis: redis-cli ping

**Reusable Insight:** Health checks enable orchestrators to detect and restart unhealthy containers. Define them for every service.

## Docker Compose

### Development Compose
- PostgreSQL + Redis only
- Backend and frontend run locally
- Hot reloading enabled
- Environment variables from .env file

### Production Compose
- 9 services: PostgreSQL, PgBouncer, Redis, Backend, Frontend, Celery Worker, Celery Beat, Nginx, Backup
- All services containerized
- Network isolation
- Volume persistence

**Reusable Insight:** Development and production should use the same infrastructure, just different scale. Docker Compose bridges the gap.

## Reverse Proxy (Nginx)

### Path-Based Routing
- /api/* -> Backend
- /auth/* -> Backend
- /admin/* -> Backend
- /metrics -> Backend
- /healthz, /readyz -> Backend
- /* -> Frontend

### SSL Termination
- Nginx handles SSL/TLS
- Backend receives plain HTTP
- Certificate management via Let's Encrypt
- HSTS headers enforced

**Reusable Insight:** Nginx is the edge of your system. It handles SSL, routing, compression, and caching. Keep it simple and well-configured.

### Security Headers
Configured in Nginx:
- Strict-Transport-Security
- X-Frame-Options
- X-Content-Type-Options
- Content-Security-Policy
- Referrer-Policy

**Reusable Insight:** Security headers are easier to manage in Nginx than in application code. Centralize them.

## Database Infrastructure

### PostgreSQL Configuration
- Production tuning (postgresql.conf)
- Connection pooling via PgBouncer
- Transaction mode pooling
- Max 500 client connections

**Reusable Insight:** PgBouncer in transaction mode is the sweet spot for web applications. It multiplexes connections efficiently.

### Backup Strategy
- Automated backups via pg_dump
- Scheduled via cron in backup container
- Retention policy configurable
- Restore procedure documented

**Reusable Insight:** Backups are useless without tested restores. Test your restore procedure regularly.

## Observability

### Prometheus Metrics
- Request counts and latencies
- Error rates by endpoint
- Database connection pool stats
- Cache hit rates
- Business metrics (active tenants, ingestion status)

**Reusable Insight:** Metrics answer "what is happening." Logs answer "why it happened." You need both.

### Structured Logging
- JSON format
- Correlation IDs
- Contextual fields
- Log levels (DEBUG, INFO, WARNING, ERROR)

**Reusable Insight:** Structured logs are queryable. Plain text logs are not. Use JSON from day one.

### Sentry Integration
- Error tracking
- Stack traces
- User context
- Release tracking

**Reusable Insight:** Sentry catches errors you didn't know about. Set it up before you need it.

## Deployment Strategy

### Environment Parity
- Dev: Docker Compose (PostgreSQL + Redis)
- Staging: Same as production, smaller scale
- Production: Full Docker Compose stack

**Reusable Insight:** Environment parity reduces "works on my machine" issues. Use the same infrastructure everywhere.

### Configuration Management
- Environment variables for all configuration
- .env.example as documentation
- No secrets in code or config files
- Pydantic Settings for validation

**Reusable Insight:** Configuration should be injectable. If you can't change it without rebuilding, it's not configuration.

### Zero-Downtime Deployments
- Blue-green or rolling deployments
- Database migrations backward-compatible
- Health checks before traffic switch
- Rollback capability

**Reusable Insight:** Deployments should be boring. If they're exciting, something is wrong.
