"""Parallel task runner — run multiple agent tasks concurrently.

Each task gets its own thread and runs independently. The runner
manages lifecycle (start, cancel, status) and exposes results via
a REST API. Frontend polls or uses SSE to track progress.
"""

from __future__ import annotations

import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

try:
    from fastapi import APIRouter, HTTPException

    FASTAPI_AVAILABLE = True
except ImportError:
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi

_logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):  # noqa: UP042 — keep str-mixin for JSON-wire compat with frontend
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ParallelTask:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    thread_id: str = ""
    prompt: str = ""
    agent_id: str = "coder"
    status: TaskStatus = TaskStatus.QUEUED
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    workspace_path: str = ""
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "prompt": self.prompt[:200],
            "agent_id": self.agent_id,
            "status": self.status.value,
            "result": self.result[:500] if self.result else "",
            "error": self.error,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "workspace_path": self.workspace_path,
        }


class ParallelTaskRunner:
    def __init__(self, max_workers: int = 3):
        self._tasks: dict[str, ParallelTask] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="parallel-task")
        self._cancelled: set[str] = set()

    def submit(self, task: ParallelTask) -> ParallelTask:
        # Carry the spawning parent's prompt-injection taint into the
        # subagent: the thread-pool worker starts with a fresh contextvar,
        # so without this an injection-tainted parent could launder a risky
        # action through a freshly-spawned subagent. Captured HERE, in the
        # parent's context, before crossing the pool boundary.
        try:
            from runtime.safety.validation.prompt_injection import (
                current_injection_taint,
            )

            _taint = current_injection_taint()
            if _taint and _taint != "none" and isinstance(task.context, dict):
                task.context.setdefault("_inherited_injection_taint", _taint)
        except Exception:  # noqa: BLE001 - taint propagation is best-effort
            pass
        self._tasks[task.id] = task
        self._pool.submit(self._run_task, task.id)
        return task

    def cancel(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        if not task or task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED):
            return False
        self._cancelled.add(task_id)
        task.status = TaskStatus.CANCELLED
        task.finished_at = time.time()
        return True

    def get(self, task_id: str) -> ParallelTask | None:
        return self._tasks.get(task_id)

    def list_tasks(self, workspace_path: str | None = None) -> list[ParallelTask]:
        tasks = list(self._tasks.values())
        if workspace_path:
            tasks = [t for t in tasks if t.workspace_path == workspace_path]
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    def _run_task(self, task_id: str) -> None:
        task = self._tasks.get(task_id)
        if not task:
            return
        if task_id in self._cancelled:
            return

        task.status = TaskStatus.RUNNING
        task.started_at = time.time()

        try:
            from runtime.core.cerebrum.react_loop import run_react_loop
            from runtime.platform.models import ParsedIntent
            from runtime.platform.models.pipeline import IntentType

            intent = ParsedIntent(
                raw=task.prompt,
                intent_type=IntentType.TASK,
                normalized_goal=task.prompt,
                user_context={
                    "workspace_path": task.workspace_path,
                    "mode": "code",
                    "auto_approve": True,
                    **task.context,
                },
            )

            from runtime.platform.ui.app import get_app_state

            state = get_app_state()
            if not state:
                raise RuntimeError("app state not available")

            result = run_react_loop(
                stack=state,
                intent=intent,
                agent=None,
                max_iterations=6,
                thread_id=task.thread_id or task.id,
            )
            task.result = str(result) if result else "completed"
            task.status = TaskStatus.COMPLETED
        except Exception as exc:
            _logger.exception("parallel task %s failed", task_id)
            task.error = str(exc)
            task.status = TaskStatus.FAILED
        finally:
            task.finished_at = time.time()


_runner: ParallelTaskRunner | None = None


def get_runner() -> ParallelTaskRunner:
    global _runner
    if _runner is None:
        _runner = ParallelTaskRunner(max_workers=3)
    return _runner


def create_parallel_task_router() -> Any:
    require_fastapi(__name__)

    router = APIRouter(tags=["parallel-tasks"])

    @router.post(
        "/api/tasks/submit",
        operation_id="parallel_submit_task",
    )
    def submit_task(body: dict[str, Any]) -> dict[str, Any]:
        runner = get_runner()
        task = ParallelTask(
            prompt=body.get("prompt", ""),
            agent_id=body.get("agent_id", "coder"),
            workspace_path=body.get("workspace_path", ""),
            thread_id=body.get("thread_id", ""),
            context=body.get("context", {}),
        )
        runner.submit(task)
        return task.to_dict()

    @router.get(
        "/api/tasks",
        operation_id="parallel_list_tasks",
    )
    def list_tasks(workspace_path: str | None = None) -> dict[str, Any]:
        runner = get_runner()
        tasks = runner.list_tasks(workspace_path)
        return {"tasks": [t.to_dict() for t in tasks[:50]]}

    @router.get(
        "/api/tasks/{task_id}",
        operation_id="parallel_get_task",
    )
    def get_task(task_id: str) -> dict[str, Any]:
        runner = get_runner()
        task = runner.get(task_id)
        if not task:
            raise HTTPException(404, "task not found")
        return task.to_dict()

    @router.post(
        "/api/tasks/{task_id}/cancel",
        operation_id="parallel_cancel_task",
    )
    def cancel_task(task_id: str) -> dict[str, Any]:
        runner = get_runner()
        ok = runner.cancel(task_id)
        return {"cancelled": ok}

    return router
