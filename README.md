# Chatbot Platform — Local Development Guide

This guide covers all steps to start and run the embeddable multi-tenant chatbot platform locally on Windows using a conda venv.

## 1. Prerequisites

- **Python 3.11+** via conda venv (located at `venv/` in repo root)
- **Docker Desktop** (running) — for Postgres, PgBouncer, and Redis
- **psql** (PostgreSQL client) — for manual DB inspection (included in most Postgres distributions)
- **cmd.exe** — primary shell for running commands (PowerShell syntax differs for env vars)

## 2. Environment Setup

### Create `.env` at repo root

Copy `.env.example` to `.env` and fill in required values:

```bash
copy .env.example .env
```

Then edit `.env` with your values. **Minimum required vars:**

```
DEPLOYMENT_MODE=saas
POSTGRES_USER=chatbot
POSTGRES_PASSWORD=chatbot
POSTGRES_DB=chatbot
POSTGRES_PORT=5432
PGBOUNCER_PORT=6432
REDIS_PORT=6379
DATABASE_URL=postgresql://chatbot:chatbot@localhost:6432/chatbot
DATABASE_URL_DIRECT=postgresql://chatbot:chatbot@localhost:5432/chatbot
TEST_DATABASE_URL=postgresql://chatbot:chatbot@localhost:5432/chatbot_test
REDIS_URL=redis://localhost:6379/0
REPOSITORY=postgres
JWT_SECRET=change-me-to-a-long-random-string-min-32-chars-for-jwt-signing
SECRET_ENCRYPTION_KEY=change-me-32-bytes-base64url-or-hex-for-aes256-gcm
STORAGE_BACKEND=local
STORAGE_LOCAL_ROOT=C:\temp\chatbot-storage
LOG_LEVEL=INFO
SERVICE_NAME=chatbot-api
```

**Notes:**
- `JWT_SECRET` and `SECRET_ENCRYPTION_KEY` must be strong random values (never commit real values).
- `DATABASE_URL_DIRECT` (port 5432) is used for migrations; `DATABASE_URL` (port 6432 via PgBouncer) is used by the running app.
- `STORAGE_LOCAL_ROOT` must exist and be writable.

### Create storage directory (one-time)

```cmd
mkdir C:\temp\chatbot-storage
```

## 3. Start Infrastructure (Docker Compose)

Start Postgres, PgBouncer, and Redis:

```cmd
docker compose -f deploy\docker-compose.dev.yml up -d
```

Verify all services are healthy:

```cmd
docker compose -f deploy\docker-compose.dev.yml ps
```

All three containers should show status `healthy`.

## 4. Apply Database Migrations

Migrations must connect directly to Postgres (port 5432), not PgBouncer (transaction mode cannot run DDL).

From the `services/api` directory:

```cmd
cd services\api
..\..\venv\python.exe -m alembic upgrade head
```

Verify the migration was applied:

```cmd
..\..\venv\python.exe -m alembic current
```

## 5. (Optional) Seed Initial Data

To create an initial tenant, platform admin, and client admin:

First, set the seed environment variables in `cmd.exe`:

```cmd
set "SEED_TENANT_NAME=Demo Corp"
set "SEED_TENANT_SLUG=demo"
set "SEED_PLATFORM_ADMIN_EMAIL=platform-admin@example.com"
set "SEED_CLIENT_ADMIN_EMAIL=client-admin@example.com"
```

Then run the seed script (still in `services/api`):

```cmd
..\..\venv\python.exe -m api.seed
```

The script generates random passwords and prints them once. Save them for login.

**Note:** If you omit the password env vars (`SEED_PLATFORM_ADMIN_PASSWORD`, `SEED_CLIENT_ADMIN_PASSWORD`), they are auto-generated and printed. Only set them if you want specific passwords.

## 6. Start the FastAPI Server

From the repo root, start the API with auto-reload for development:

```cmd
venv\python.exe -m uvicorn api.app:create_app --factory --reload --host 127.0.0.1 --port 8000
```

Expected startup output:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
```

The API is now serving on `http://localhost:8000`.

## 7. Start the Celery Worker (separate terminal)

Open a new `cmd.exe` window and run from the repo root:

```cmd
venv\python.exe -m celery -A api.tasks.celery_app worker --loglevel=info --pool=solo
```

**Important:** On Windows, the `--pool=solo` flag is required (synchronous single-process pool; thread pool is not reliable on Windows).

Expected output:
```
 ---------- celery@... v5.3.x ----------
mingle v1.0.5
Worker is ready. Ready to accept tasks!
```

## 8. Start Celery Beat Scheduler (separate terminal, optional)

For periodic tasks (currently minimal; populated in future phases):

```cmd
venv\python.exe -m celery -A api.tasks.celery_app beat --loglevel=info
```

Celery Beat will use a local schedule database (`celerybeat-schedule*` files in the repo root).

## 9. Verify Health and Readiness

### Liveness check

```cmd
curl http://localhost:8000/healthz
```

Expected response (200 OK):
```json
{"status": "ok"}
```

### Readiness check

```cmd
curl http://localhost:8000/readyz
```

Expected response (200 OK) when all dependencies (DB, Redis) are ready:
```json
{"ready": true, "checks": {"database": true, "redis": true}}
```

If Redis is unavailable, the readiness check still passes (Redis is optional; the app falls back to in-memory rate limiting).

## 10. Run Tests and Gate Checks

From the repo root, run the full test + lint + type-check gate:

### Lint (Ruff)

```cmd
venv\python.exe -m ruff check services\api
venv\python.exe -m ruff check services\common
```

### Type checking (Mypy)

```cmd
cd services\api
..\..\venv\python.exe -m mypy --strict src
cd ..\..

cd services\common
..\..\venv\python.exe -m mypy --strict src
cd ..\..
```

### Unit tests (Pytest)

```cmd
venv\python.exe -m pytest services\api\tests\unit -q
venv\python.exe -m pytest services\common\tests\unit -q
```

To also run integration tests (requires `TEST_DATABASE_URL` and live Postgres):

```cmd
venv\python.exe -m pytest services\api\tests -q
venv\python.exe -m pytest services\common\tests -q
```

## 11. Useful PostgreSQL Inspection Commands

### Check database connection

```cmd
docker compose -f deploy\docker-compose.dev.yml exec postgres psql -U chatbot -d chatbot -c "SELECT 1;"
```

Expected output: single row with value `1`.

### List all tables

```cmd
docker compose -f deploy\docker-compose.dev.yml exec postgres psql -U chatbot -d chatbot -c "\dt"
```

### Inspect knowledge_chunks table (if created by migration)

```cmd
docker compose -f deploy\docker-compose.dev.yml exec postgres psql -U chatbot -d chatbot -c "\d knowledge_chunks"
```

### Check pgvector extension

```cmd
docker compose -f deploy\docker-compose.dev.yml exec postgres psql -U chatbot -d chatbot -c "SELECT extversion FROM pg_extension WHERE extname='vector';"
```

### Connect interactively via PgBouncer (connection pooler)

```cmd
psql "postgresql://chatbot:chatbot@localhost:6432/chatbot"
```

(Then use `\q` to exit.)

### Direct connection to Postgres (bypassing PgBouncer)

```cmd
psql "postgresql://chatbot:chatbot@localhost:5432/chatbot"
```

## 12. Troubleshooting

### "connection refused" errors

- Check `docker compose -f deploy\docker-compose.dev.yml ps` — all services should be `healthy`.
- Ensure ports 5432, 6432, 6379 are not blocked or used by other processes.
- If using a different POSTGRES_PORT, PGBOUNCER_PORT, or REDIS_PORT, verify the `.env` file matches.

### "DATABASE_URL_DIRECT required for migrations"

- If alembic fails with this message, ensure `DATABASE_URL_DIRECT` is set in `.env` (e.g., `postgresql://chatbot:chatbot@localhost:5432/chatbot`).

### Celery worker won't start

- Verify Redis is running: `docker compose -f deploy\docker-compose.dev.yml exec redis redis-cli ping` (expect `PONG`).
- Ensure `REDIS_URL` is set in `.env` (e.g., `redis://localhost:6379/0`).
- On Windows, always use `--pool=solo` with Celery.

### Tests skip integration markers

- Integration tests are skipped if `TEST_DATABASE_URL` is not set. Set it in `.env` to `postgresql://chatbot:chatbot@localhost:5432/chatbot_test` to enable them.

## 13. Stopping Infrastructure

### Stop containers (keep volumes)

```cmd
docker compose -f deploy\docker-compose.dev.yml down
```

### Stop and remove everything (including data)

```cmd
docker compose -f deploy\docker-compose.dev.yml down -v
```

---

## Quick Start Checklist

1. `copy .env.example .env` and fill in required values
2. `docker compose -f deploy\docker-compose.dev.yml up -d`
3. `cd services\api && ..\..\venv\python.exe -m alembic upgrade head && cd ..\..`
4. `venv\python.exe -m uvicorn api.app:create_app --factory --reload --host 127.0.0.1 --port 8000`
5. In a new terminal: `venv\python.exe -m celery -A api.tasks.celery_app worker --loglevel=info --pool=solo`
6. Verify: `curl http://localhost:8000/healthz`

Done! The API is running on `http://localhost:8000`, the worker is listening for tasks, and the database is initialized.
