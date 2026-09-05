"""Carry the host task boundary into an existing delegated worker."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any

from runtime.execution.artifact_contracts import ArtifactContract
from runtime.execution.request import (
    ExecutionRequest,
    ExecutionTask,
    execution_request_scope,
)
from runtime.platform.process.scope import execution_scope_ceiling, resolve_execution_scope
from runtime.platform.process.session import Session


def parent_execution_task(session: Any) -> ExecutionTask | None:
    # JSON/model context cannot supply a Session or an ExecutionTask. This
    # accessor deliberately does not inspect a caller's arbitrary context.
    if not isinstance(session, Session):
        return None
    task = session.metadata.get("_execution_task")
    return task if isinstance(task, ExecutionTask) else None


def readonly_execution_parent(session: Any) -> Any:
    """Narrow a host task for reviewers without changing its shared identity/budget."""
    task = parent_execution_task(session)
    if task is None:
        return session
    metadata = dict(session.metadata)
    metadata.pop("_locked_write_root", None)
    metadata["_execution_task"] = replace(
        task, permissions=replace(task.permissions, writable_roots=())
    )
    return replace(session, metadata=metadata)


@contextmanager
def child_execution_scope(
    parent: Any,
    child: Any,
    *,
    child_id: str,
    instruction: str,
    artifacts: ArtifactContract | None = None,
) -> Iterator[ExecutionRequest | None]:
    task = parent_execution_task(parent)
    if task is None or not isinstance(child, Session):
        yield None
        return
    task.resources.remaining_seconds()
    with execution_scope_ceiling(task.permissions):
        permissions = resolve_execution_scope(child)
        locked_root = child.metadata.get("_locked_write_root")
        if isinstance(locked_root, str) and locked_root:
            root = Path(locked_root).resolve(strict=True)
            if not permissions.allows_write(root):
                if permissions.writable_roots or not permissions.allows_read(root):
                    raise PermissionError("child write root is outside the parent execution scope")
                # The bridge also carries its project read root in this legacy
                # field. A read-only reviewer must not turn that coordinate
                # into a write grant or fail before it can inspect the project.
                child.metadata.pop("_locked_write_root", None)
            else:
                permissions = replace(permissions, writable_roots=(root,))
        child_task = replace(
            task,
            task_id=child_id,
            thread_id=child_id,
            parent_task_id=task.task_id,
            goal=instruction,
            permissions=permissions,
            artifacts=artifacts,
        )
        child.metadata["_execution_task"] = child_task
        request = ExecutionRequest(child_task, instruction)
        with execution_request_scope(request):
            yield request


def child_timeout_seconds(session: Any, requested: float | None) -> float | None:
    """The existing cancellation monitor enforces the parent's remaining time."""
    task = parent_execution_task(session)
    if task is None or task.resources.deadline is None:
        return requested
    # Returning zero makes the existing bridge produce its structured timeout
    # outcome; it does not need another child lifecycle or timer thread.
    remaining = max(0.0, task.resources.deadline - time.monotonic())
    return min(requested, remaining) if requested is not None else remaining
