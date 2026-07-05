"""Debug task routes: /debug/tasks.

CLIENT_ADMIN only — the ping task carries no tenant data but the endpoints
still authenticate (consistent with all other debug routes).

Routes:
    POST /debug/tasks/ping   — enqueue debug.ping; return {task_id, status:"queued"}.
    GET  /debug/tasks/{id}  — poll result; return {task_id, state, result}.
"""
from __future__ import annotations

from typing import Any

from celery.result import AsyncResult
from common.auth import AuthClaims, Role
from common.logging import _correlation_id, get_logger  # noqa: PLC2701
from fastapi import APIRouter, Depends

from api.auth.dependencies import require_roles
from api.tasks.celery_app import celery_app
from api.tasks.debug_tasks import ping

_log = get_logger(__name__)

router = APIRouter(prefix="/debug/tasks", tags=["tasks"])


@router.post("/ping")
async def enqueue_ping(
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, str]:
    """Enqueue a debug.ping task and return its task_id.

    The current request's correlation_id is passed to the task so the worker
    log carries the same ID as this HTTP request (end-to-end trace).
    """
    # Read the correlation_id that the correlation-id middleware bound for this
    # request. It is always non-None here because the middleware runs first.
    cid: str = _correlation_id.get() or ""

    result = ping.delay(correlation_id=cid)

    _log.info(
        "debug.ping enqueued",
        extra={"event": "task_enqueued", "task": "debug.ping"},
    )

    return {"task_id": result.id, "status": "queued"}


@router.get("/{task_id}")
async def get_task_status(
    task_id: str,
    claims: AuthClaims = Depends(require_roles(Role.CLIENT_ADMIN)),  # noqa: B008
) -> dict[str, Any]:
    """Poll the state and result of a previously enqueued task.

    On FAILURE the raw exception is NOT returned — ``result`` is null (no
    exception object leakage to the client).
    """
    res = AsyncResult(task_id, app=celery_app)

    return {
        "task_id": task_id,
        "state": res.state,
        # Only expose the result when the task succeeded; never leak raw
        # exception objects on failure (CLAUDE.md §3 "no silent fallbacks"
        # does not mean leaking internal errors to the caller).
        "result": res.result if res.successful() else None,
    }
