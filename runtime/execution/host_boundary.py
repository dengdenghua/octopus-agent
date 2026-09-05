"""Create server-owned execution tasks for non-realtime entrypoints.

Realtime turns already build this boundary in ``RealtimeExecutionContext``.
HTTP dispatchers and durable background orchestrators use this module so a
delegated worker receives the same immutable task identity, permission ceiling,
deadline and coordination state instead of a loosely populated ``Session``.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from runtime.execution.artifact_contracts import HandoffRecorder
from runtime.execution.request import (
    ExecutionRequest,
    ExecutionResources,
    ExecutionTask,
)
from runtime.platform.config.schema import BudgetConfig
from runtime.platform.process.scope import resolve_execution_scope
from runtime.platform.process.session import Session

_PRIVATE_METADATA_KEYS = frozenset(
    {
        "_execution_task",
        "_execution_handoff_recorder",
        "_file_write_leases",
        "_file_write_lease_handoffs",
        "_file_write_lease_history",
        "_file_read_snapshots",
    }
)


@dataclass(frozen=True, slots=True)
class HostExecutionBoundary:
    """The Session and immutable request owned by one host entrypoint."""

    session: Session
    request: ExecutionRequest


def inherit_host_execution_session(
    parent: Session,
    *,
    thread_id: str,
    actor_id: str | None,
    tenant_id: str | None,
    metadata: Mapping[str, Any] | None = None,
) -> Session:
    """Add trusted orchestration metadata while retaining the parent's boundary."""

    task = parent.metadata.get("_execution_task")
    if not isinstance(task, ExecutionTask):
        raise ValueError("parent session has no host execution task")
    normalized_thread = str(thread_id or "").strip()
    normalized_actor = str(actor_id or "").strip() or None
    normalized_tenant = str(tenant_id or "").strip() or None
    if normalized_thread != task.thread_id:
        raise ValueError("child orchestration thread does not match host task")
    if normalized_actor != task.actor_id or normalized_tenant != task.tenant_id:
        raise ValueError("child orchestration principal does not match host task")

    merged = dict(parent.metadata)
    additions = dict(metadata or {})
    for key in _PRIVATE_METADATA_KEYS:
        additions.pop(key, None)
    merged.update(additions)
    # Restore the exact Python-owned objects after merging ordinary metadata.
    for key in _PRIVATE_METADATA_KEYS:
        if key in parent.metadata:
            merged[key] = parent.metadata[key]
    return replace(parent, metadata=merged)


def create_host_execution_boundary(
    *,
    task_id: str,
    thread_id: str,
    goal: str,
    timeout_s: float,
    actor_id: str | None = None,
    tenant_id: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    parent_task_id: str | None = None,
    handoff_recorder: HandoffRecorder | None = None,
    budget: BudgetConfig | None = None,
) -> HostExecutionBoundary:
    """Build a fresh trusted boundary from server-validated coordinates.

    Callers must validate identity and workspace values before invoking this
    function. Host-private objects and coordination tables are always replaced,
    so JSON/model metadata cannot forge a task or file-ownership state.
    """

    normalized_task_id = str(task_id or "").strip()
    normalized_thread_id = str(thread_id or "").strip()
    normalized_goal = str(goal or "").strip()
    normalized_actor = str(actor_id or "").strip() or None
    normalized_tenant = str(tenant_id or "").strip() or None
    if not normalized_task_id or not normalized_thread_id:
        raise ValueError("host execution requires task and thread coordinates")
    if bool(normalized_actor) != bool(normalized_tenant):
        raise ValueError("host execution principal is incomplete")
    try:
        duration = float(timeout_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("host execution timeout must be positive") from exc
    if duration <= 0:
        raise ValueError("host execution timeout must be positive")

    trusted_metadata = dict(metadata or {})
    for key in _PRIVATE_METADATA_KEYS:
        trusted_metadata.pop(key, None)
    trusted_metadata.update(
        _file_write_leases={},
        _file_write_lease_handoffs={},
        _file_write_lease_history=[],
        _file_read_snapshots={},
    )
    if normalized_tenant:
        trusted_metadata["tenant_id"] = normalized_tenant
    if normalized_actor:
        trusted_metadata["owner_actor_id"] = normalized_actor

    session = Session(
        actor=normalized_actor,
        thread_id=normalized_thread_id,
        conversation_id=normalized_thread_id,
        turn_id=normalized_task_id,
        metadata=trusted_metadata,
    )
    limits = budget or BudgetConfig()
    task = ExecutionTask(
        task_id=normalized_task_id,
        thread_id=normalized_thread_id,
        actor_id=normalized_actor,
        tenant_id=normalized_tenant,
        goal=normalized_goal,
        permissions=resolve_execution_scope(session),
        resources=ExecutionResources(
            token_target=limits.max_tokens,
            usd_target=limits.max_usd,
            deadline=time.monotonic() + duration,
        ),
        parent_task_id=str(parent_task_id or "").strip() or None,
    )
    trusted_metadata["_execution_task"] = task
    if handoff_recorder is not None:
        trusted_metadata["_execution_handoff_recorder"] = handoff_recorder
    return HostExecutionBoundary(session=session, request=ExecutionRequest(task, normalized_goal))


__all__ = [
    "HostExecutionBoundary",
    "create_host_execution_boundary",
    "inherit_host_execution_session",
]
