"""Notification service (S9.1) -- carved-out worker realized as this subpackage.

See ``.claude/skills/notification-service/SKILL.md`` and CLAUDE.md's
"Structure note" in ``dev_plan/sprints/S9.1.md``: this is operationally a
carved-out deployable (a dedicated Celery worker can run only its tasks) but
structurally lives inside the one ``services/api`` FastAPI app, exactly like
``api.ingestion`` and ``api.crm``.
"""
from __future__ import annotations
