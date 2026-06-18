---
name: guardrails
description: >
  Always-relevant agent guardrails for the chatbot platform. Load this whenever you are about to
  change files, run shell commands, or finish a task in this repo. It states the hard rules the agent
  must obey — version control is hands-off (never git add/commit/push), the project spec is read-only,
  no hardcoded secrets, no silent fallbacks, scope discipline, and TDD for backend — and documents
  which of those rules are mechanically ENFORCED by the Claude Code hooks in `.claude/hooks/`.
  Use this for any "am I allowed to…?" question about git, deleting files, editing the spec, or secrets.
---

# Guardrails — how agents must behave in this repo

This skill is the behavioral contract for **every** agent working on the chatbot platform. It complements
the always-loaded `CLAUDE.md` (the *what* we're building) by pinning down *how you are allowed to work*.

Some rules are **[ENFORCED]** — Claude Code PreToolUse/Stop hooks in `.claude/hooks/` will hard-block the
action (exit code 2) and feed the reason back to you. The rest are **[EXPECTED]** — not yet mechanically
blocked, but mandatory and reviewed. Treat both identically; the hooks are a safety net, not the boundary.

> If a hook blocks you, **stop and reconsider** — do not try to route around it (see §7). The block is the
> system working as designed.

---

## §0 — Git is hands-off  **[ENFORCED]**

**You must NEVER run the git write path.** All version control — staging, committing, branching, pushing,
merging, rebasing, resetting, tagging — is the **user's** responsibility, always.

- ❌ Forbidden (blocked by `block_commands.py`): `git add`, `git commit`, `git push`, `git merge`,
  `git rebase`, `git reset`, `git checkout`/`switch` (state-changing), `git stash`, `git cherry-pick`,
  `git branch -d/-D/-m`, `git tag -d`, `git remote add/remove/set-url`, `git clean`, and any other
  history- or state-mutating subcommand.
- ✅ Allowed (read-only): `git status`, `git log`, `git diff`, `git show`, `git branch` (list),
  `git remote -v`, `git rev-parse`, `git blame`, `git describe`, `git fetch`, etc.

When work is ready to be versioned, **ask the user to run the git commands themselves** — they can use the
`!` prefix in the prompt (e.g. `!git add -A && git commit -m "…"`) so it runs in their session. Never offer
to do it for them, and never suggest `--no-verify` or other hook-bypass flags.

Also blocked by the same hook: **recursive force deletes** (`rm -rf`, `rm -fr`, PowerShell
`Remove-Item -Recurse -Force`). Delete specific paths explicitly, or ask the user to confirm.

---

## §1 — Architecture & stack are locked  **[EXPECTED]**

Obey `CLAUDE.md` §2 (architecture map) and §4 (locked tech stack). Do not introduce new frameworks,
datastores, or vector DBs. Notably: FastAPI (async) · PostgreSQL + `asyncpg` (**no ORM** for queries,
SQLAlchemy/Alembic for migrations only) · pgvector · Redis · Celery + Beat · Next.js App Router + RSC +
shadcn/ui · React + Shadow DOM widget · Nginx · Docker. When `knowledge_base/` conflicts with
`system_flow/solution_flow.docx`, **knowledge_base wins**; when `CLAUDE.md` conflicts with a service skill,
**CLAUDE.md wins**.

---

## §2 — Multi-tenancy & data access  **[EXPECTED]**

The highest-priority correctness rule (see `CLAUDE.md` §3 and `platform-foundations`):

- Tenant isolation is enforced at the **repository layer**, not the API layer.
- `tenant_id` is **never** accepted from user/visitor input — it comes from `AuthClaims` (admin JWT) or the
  signed visitor session. Every repository method takes `AuthClaims` and filters by `tenant_id`.
- **No ORM for queries; parameterized SQL only** — never string-format/concatenate SQL.
- Cache keys **always include `tenant_id`**; invalidate on mutation, never on read.
- Enforce RBAC (`PLATFORM_ADMIN`/`CLIENT_ADMIN`/`CLIENT_AGENT`/`VISITOR`) at the data layer, not just the UI.

Multi-tenant isolation tests and per-role RBAC tests are **mandatory** (see §5).

---

## §3 — Security & secrets  **[ENFORCED secret scan]**

`protect_paths.py` blocks writing content that looks like a **hardcoded credential** (AWS keys, private
keys, `sk-ant-…`/`sk-…` LLM keys, `api_key = "…"`/`password = "…"`/`token = "…"` literals).

- Secrets come from **env / Pydantic Settings** and are encrypted at rest (AES-256-GCM) via the
  `platform-foundations` SecretBox. Never commit real secrets; use placeholders in `.env.example`.
- Passwords: PBKDF2-SHA256 (120k iters, per-password salt, constant-time compare).
- Validate all input with Pydantic (422). Never log secrets/tokens/PII. Capture GDPR consent before storing
  contact details or scheduling reminders.

Exempt from the scan (placeholders expected): `.env.example`, `secrets.md`, `SKILL.md`.

---

## §4 — No silent fallbacks  **[EXPECTED]**

Per `CLAUDE.md` §3 / ADR "no silent fallbacks": **never serve fake/sample/placeholder data** when live
data or the LLM fails — fail explicitly with the proper `AppException` and a correlation ID. Infrastructure
fallbacks are allowed but must be **explicit** (e.g. Redis down → in-memory rate limit; replica down →
primary). Background tasks are idempotent and retryable (backoff + jitter, max retries, dead-letter).

---

## §5 — Process & TDD  **[Stop-hook reminder ENFORCED]**

- **Backend logic is test-first (TDD): red → green → refactor.** Tests must include multi-tenant isolation
  (tenant A cannot read tenant B) and RBAC-per-role, plus idempotency tests for ingestion/notification jobs.
- UI is pragmatic test-after, but still tested at boundaries.
- Before claiming work complete, **run the service's lint + typecheck + tests and paste real output** — do
  not assert success without evidence. The `verify_reminder.py` Stop hook will remind you on every stop.
- Process before implementation: brainstorm/plan, then build.

---

## §6 — Scope & spec protection  **[ENFORCED]**

`protect_paths.py` enforces the project boundary:

- **`knowledge_base/` and `system_flow/` are read-only source material — ALWAYS blocked.** Build *from* the
  spec; never modify it.
- **`CLAUDE.md`, `.claude/skills/**`, `.claude/settings.json`, `.claude/hooks/**` are the project spec** and
  are blocked unless this is deliberate spec work. Intentional spec edits require an explicit escape:
  set `CHATBOT_EDIT_SPEC=1` for the session **or** create the `.claude/.allow_spec_edit` sentinel file
  (remove it when done so protection re-arms).

Stay inside the service folder you're working on. Cross-module access goes through repository **contracts**
(`typing.Protocol`) and `services/common` — never reach into another module's internals or tables directly.

---

## §7 — Don't circumvent the guardrails  **[EXPECTED]**

The hooks exist to keep the codebase safe and the spec stable. Do not attempt to disable, edit, or bypass
them to get an action through (e.g. rewriting `.claude/hooks/*`, deleting `settings.json`, base64-encoding a
blocked command, or shelling out to write a spec file to dodge the Edit-tool guard). If a guardrail is
genuinely wrong or in the way, **surface it to the user and let them decide** — changing the guardrails is
the user's call, not the agent's.

---

## Reusable insights (KB-style)

- **A guardrail must fail open on its own bugs, closed on policy.** Every hook here `exit(0)`s (allows) on a
  parse/internal error so a broken script can't brick the agent — but `exit(2)`s (blocks) on a real policy
  hit. A guardrail that crashes-closed becomes the outage.
- **Wire hooks with absolute paths.** Relative hook commands (`python .claude/hooks/x.py`) break the moment
  the working directory changes mid-session, and a hook that can't find its script exits non-zero =
  everything blocked. `settings.json` uses absolute paths for exactly this reason.
- **Self-referential spec edits need a deliberate escape, not a backdoor.** Editing the spec/hooks is gated;
  the sanctioned way through is the `CHATBOT_EDIT_SPEC=1` env var or the `.allow_spec_edit` sentinel — used
  consciously and then removed — not weakening the hook.
- **Git stays with the human.** Treating the entire git write path as off-limits (not just `push`) removes a
  whole class of "the agent committed/force-pushed something" incidents and keeps authorship + review human.

See also: `CLAUDE.md` (constitution) and `platform-foundations` (shared implementations of the patterns
referenced above).
