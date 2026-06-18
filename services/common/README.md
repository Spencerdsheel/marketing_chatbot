# `services/common` — Platform Foundations

Shared cross-cutting library every chatbot-platform service imports. It is the single,
consistent implementation of the universal patterns in `CLAUDE.md` and the deep reference
`.claude/skills/platform-foundations/SKILL.md`:

- `errors` — `AppException` hierarchy (stable `code` + `http_status`).
- `auth` — `Role` (4 roles) + `AuthClaims` (the only carrier of `tenant_id`).
- `tenancy` — `tenant_filter` / `assert_tenant_access` (multi-tenancy enforced at the data layer).
- `crypto` — `SecretBox` (AES-256-GCM) + PBKDF2-SHA256 password hashing.
- `settings` — Pydantic Settings; fail fast on missing required config.
- `logging` — structured JSON logs with correlation-ID context.
- `cache` — tenant-scoped cache-aside helpers (Redis + in-memory fallback).
- `repository` — `Repository` Protocol + `InMemoryRepository` (the downstream test double).
- `db` / `postgres_repo` / `pgvector` — asyncpg access (parameterized SQL, no ORM) + vector search.
- `health` — `/healthz`, `/readyz`, Prometheus registry helpers.

## Develop

This project uses a conda env at `D:\Project\chatbot\venv` (Python 3.11). Run everything through it:

```bash
conda run -p D:\Project\chatbot\venv pip install -e "services/common[dev]"
conda run -p D:\Project\chatbot\venv ruff check services/common
conda run -p D:\Project\chatbot\venv mypy services/common/src
conda run -p D:\Project\chatbot\venv pytest services/common/tests/unit -v
```

Integration tests (asyncpg + pgvector) need a real Postgres:

```bash
# Postgres must allow: CREATE EXTENSION vector
TEST_DATABASE_URL=postgresql://user:pass@localhost:5432/chatbot_test \
  conda run -p D:\Project\chatbot\venv pytest services/common/tests/integration -v
```

Without `TEST_DATABASE_URL`, integration tests are skipped (unit tests always run).
