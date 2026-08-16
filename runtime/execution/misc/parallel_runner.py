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
    def __init__(self, max_workers: int = 3, stack: Any = None):
        self._tasks: dict[str, ParallelTask] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="parallel-task")
        self._cancelled: set[str] = set()
        # Audit T-09: one CancellationSource per in-flight task, installed as
        # the ambient token around run_react_loop so cancel() actually stops
        # the running loop instead of just labelling it cancelled.
        self._sources: dict[str, Any] = {}
        # The wired execution stack (``StackProtocol``) this runner drives
        # ``run_react_loop`` against. Previously ``_run_task`` reached for a
        # ``get_app_state()`` helper that never existed, so every task failed
        # on ImportError. Hold the stack here instead.
        self._stack = stack

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
        # Fire the task's cancellation source so the running react loop (which
        # polls the ambient token each iteration) stops promptly (audit T-09).
        source = self._sources.get(task_id)
        if source is not None:
            source.cancel(reason="cancelled by operator")
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

        # Audit T-09: install a per-task cancellation source as the ambient
        # token so a cancel() from the API thread reaches the running loop.
        from runtime.safety.approval.cancellation import (
            CancellationSource,
            scoped_cancellation,
        )

        source = CancellationSource()
        self._sources[task_id] = source
        try:
            from runtime.core.cerebrum.react_loop import run_react_loop
            from runtime.platform.models import ParsedIntent

            intent = ParsedIntent(
                raw=task.prompt,
                intent_type="task",
                normalized_goal=task.prompt,
                user_context={
                    "workspace_path": task.workspace_path,
                    "mode": "code",
                    "auto_approve": True,
                    **task.context,
                },
            )

            state = self._stack
            if not state:
                raise RuntimeError("parallel runner has no execution stack wired in")

            with scoped_cancellation(source.token):
                result = run_react_loop(
                    stack=state,
                    intent=intent,
                    agent=None,
                    max_iterations=6,
                    thread_id=task.thread_id or task.id,
                )
            if task_id in self._cancelled:
                # Audit T-09: a cancelled task must keep its CANCELLED
                # terminal state instead of being overwritten by the
                # loop's normal completion path.
                task.result = str(result) if result else "cancelled"
                task.status = TaskStatus.CANCELLED
            else:
                task.result = str(result) if result else "completed"
                task.status = TaskStatus.COMPLETED
        except Exception as exc:
            _logger.exception("parallel task %s failed", task_id)
            if task_id in self._cancelled:
                task.status = TaskStatus.CANCELLED
            else:
                task.error = str(exc)
                task.status = TaskStatus.FAILED
        finally:
            self._sources.pop(task_id, None)
            task.finished_at = time.time()


_runner: ParallelTaskRunner | None = None


def get_runner() -> ParallelTaskRunner:
    global _runner
    if _runner is None:
        _runner = ParallelTaskRunner(max_workers=3)
    return _runner


def create_parallel_task_router(stack: Any = None) -> Any:
    require_fastapi(__name__)

    # Wire the execution stack into the runner so ``_run_task`` can drive
    # ``run_react_loop``. Without this the runner has no stack to run against.
    global _runner
    _runner = get_runner()
    if stack is not None:
        _runner._stack = stack

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
