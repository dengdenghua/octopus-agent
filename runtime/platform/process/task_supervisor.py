from __future__ import annotations

import socket
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from runtime.platform.io import atomic_write_json, read_json_with_backup
from runtime.platform.io.atomic import _cross_process_lock

_SCHEMA = "octopus.task_supervisor.v1"
_DEFAULT_HOLDER_ID = f"{socket.gethostname()}:{uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _clean_optional(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


class TaskRunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    PAUSED = "paused"
    VERIFYING = "verifying"
    REPAIRING = "repairing"
    CANCELLED = "cancelled"
    FAILED = "failed"
    COMPLETED = "completed"


class TaskLeaseError(RuntimeError):
    def __init__(self, task_id: str, message: str) -> None:
        super().__init__(message)
        self.task_id = task_id


class TaskLeaseConflict(TaskLeaseError):
    def __init__(self, task_id: str, holder_id: str) -> None:
        super().__init__(
            task_id,
            f"task {task_id!r} is already leased by {holder_id!r}",
        )
        self.holder_id = holder_id


class LostTaskLease(TaskLeaseError):
    def __init__(self, task_id: str, reason: str) -> None:
        super().__init__(task_id, f"task {task_id!r} lease is no longer current: {reason}")
        self.reason = reason


TERMINAL_TASK_STATUSES = {
    TaskRunStatus.CANCELLED,
    TaskRunStatus.FAILED,
    TaskRunStatus.COMPLETED,
}
ACTIVE_TASK_STATUSES = {
    TaskRunStatus.RUNNING,
    TaskRunStatus.WAITING_APPROVAL,
    TaskRunStatus.PAUSED,
    TaskRunStatus.VERIFYING,
    TaskRunStatus.REPAIRING,
}


DEFAULT_CAPABILITY_GROUPS: dict[str, bool] = {
    "builtin": True,
    "web": True,
    "browser": True,
    "computer": True,
    "fs_write": True,
    "git": True,
    "shell": True,
    "memory": True,
}


class TaskCapabilityManifest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    groups: dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_CAPABILITY_GROUPS))
    workspace_paths: list[str] = Field(default_factory=list)
    source: str = "default"
    created_at: str = Field(default_factory=_now_iso)

    @field_validator("groups", mode="before")
    @classmethod
    def _normalize_groups(cls, value: Any) -> dict[str, bool]:
        groups = dict(DEFAULT_CAPABILITY_GROUPS)
        if isinstance(value, dict):
            for key, enabled in value.items():
                clean_key = str(key or "").strip()
                if clean_key:
                    groups[clean_key] = bool(enabled)
        return groups

    @field_validator("workspace_paths", mode="before")
    @classmethod
    def _normalize_paths(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        out: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text and text not in out:
                out.append(text)
        return out

    def allows_group(self, group: str | None) -> bool:
        if not group:
            return True
        return bool(self.groups.get(str(group), False))


class TaskLease(BaseModel):
    model_config = ConfigDict(extra="ignore")

    holder_id: str
    token: int = Field(ge=1)
    acquired_at: str = Field(default_factory=_now_iso)
    heartbeat_at: str = Field(default_factory=_now_iso)
    expires_at: float = 0.0

    @property
    def expired(self) -> bool:
        return self.expires_at > 0 and time.time() >= self.expires_at


class TaskRunRecord(BaseModel):
    model_config = ConfigDict(extra="ignore")

    task_id: str = Field(..., min_length=1)
    kind: str = "task"
    owner_id: str | None = None
    thread_id: str | None = None
    parent_task_id: str | None = None
    origin_task_id: str | None = None
    resume_checkpoint_id: str | None = None
    status: TaskRunStatus = TaskRunStatus.PENDING
    title: str = ""
    goal: str = ""
    mode: str = ""
    workspace_path: str | None = None
    capabilities: TaskCapabilityManifest = Field(default_factory=TaskCapabilityManifest)
    lease: TaskLease | None = None
    terminal_reason: str = ""
    latest_checkpoint_id: str | int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=_now_iso)
    updated_at: str = Field(default_factory=_now_iso)
    started_at: str | None = None
    completed_at: str | None = None
    heartbeat_at: str | None = None

    @field_validator(
        "owner_id",
        "thread_id",
        "parent_task_id",
        "origin_task_id",
        "resume_checkpoint_id",
        "workspace_path",
        mode="before",
    )
    @classmethod
    def _normalize_optional_fields(cls, value: Any) -> str | None:
        return _clean_optional(value)


def task_lease_health(record: TaskRunRecord) -> dict[str, Any]:
    lease = record.lease
    if record.status in TERMINAL_TASK_STATUSES:
        state = "terminal"
    elif lease is None:
        state = "missing_lease"
    elif lease.expired:
        state = "expired"
    else:
        state = "ok"
    recovery = task_recovery_advice(record, lease_state=state)
    return {
        "task_id": record.task_id,
        "status": record.status.value,
        "kind": record.kind,
        "state": state,
        "holder_id": lease.holder_id if lease is not None else None,
        "lease_token": lease.token if lease is not None else None,
        "lease_expires_at": lease.expires_at if lease is not None else None,
        "lease_heartbeat_at": lease.heartbeat_at if lease is not None else None,
        "task_heartbeat_at": record.heartbeat_at,
        "updated_at": record.updated_at,
        "can_takeover": recovery["can_takeover"],
        "can_resume": recovery["can_resume"],
        "has_checkpoint": recovery["has_checkpoint"],
        "recommended_action": recovery["recommended_action"],
        "recovery_reason": recovery["reason"],
        "recovery": recovery,
    }


def task_recovery_advice(
    record: TaskRunRecord,
    *,
    lease_state: str | None = None,
) -> dict[str, Any]:
    state = str(lease_state or "").strip()
    if not state:
        if record.status in TERMINAL_TASK_STATUSES:
            state = "terminal"
        elif record.lease is None:
            state = "missing_lease"
        elif record.lease.expired:
            state = "expired"
        else:
            state = "ok"
    has_checkpoint = bool(record.latest_checkpoint_id or record.resume_checkpoint_id)
    can_takeover = False
    can_resume = False
    action = "monitor"
    reason = "task is active with a healthy lease"

    if record.status in TERMINAL_TASK_STATUSES:
        action = "none"
        reason = "task is already terminal"
        if record.status in {TaskRunStatus.FAILED, TaskRunStatus.CANCELLED}:
            can_resume = True
            action = "resume_from_checkpoint" if has_checkpoint else "restart"
            reason = f"task ended as {record.status.value}"
    elif record.status == TaskRunStatus.PENDING:
        action = "dispatch"
        reason = "task has not started"
    elif record.status == TaskRunStatus.WAITING_APPROVAL:
        if bool(record.metadata.get("capability_denied")):
            action = "capability_policy_denied"
            reason = "task is blocked by disabled capability"
        elif bool(record.metadata.get("approval_denied")) and not bool(
            record.metadata.get("approval_required")
        ):
            action = "approval_policy_denied"
            reason = "task is blocked by approval policy"
        elif state in {"expired", "missing_lease"}:
            can_takeover = True
            action = "takeover_for_approval"
            reason = "task is waiting for approval but has no live lease"
        else:
            action = "await_operator_approval"
            reason = "task is waiting for approval"
    elif state in {"expired", "missing_lease"}:
        can_takeover = True
        can_resume = has_checkpoint
        action = "takeover_and_resume" if has_checkpoint else "takeover"
        reason = "task has no live lease"
    elif record.status == TaskRunStatus.PAUSED:
        can_resume = has_checkpoint
        action = "resume_paused_task"
        reason = "task is paused"

    checkpoint_id = record.latest_checkpoint_id or record.resume_checkpoint_id
    operation, steps = _task_recovery_operation(action)
    return {
        "can_takeover": can_takeover,
        "can_resume": can_resume,
        "has_checkpoint": has_checkpoint,
        "recommended_action": action,
        "operation": operation,
        "steps": steps,
        "reason": reason,
        "latest_checkpoint_id": record.latest_checkpoint_id,
        "resume_checkpoint_id": record.resume_checkpoint_id,
        "checkpoint_id": checkpoint_id,
    }


def build_task_runs_overview(tasks: list[TaskRunRecord]) -> dict[str, Any]:
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_recommended_action: dict[str, int] = {}
    active_task_ids: list[str] = []
    expired_lease_task_ids: list[str] = []
    stale_nonterminal_task_ids: list[str] = []
    leased_task_ids: list[str] = []
    takeover_task_ids: list[str] = []
    resumable_task_ids: list[str] = []
    lease_health: list[dict[str, Any]] = []
    for task in tasks:
        status = task.status.value
        by_status[status] = by_status.get(status, 0) + 1
        kind = str(task.kind or "task")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        health = task_lease_health(task)
        action = str(health.get("recommended_action") or "unknown")
        by_recommended_action[action] = by_recommended_action.get(action, 0) + 1
        if bool(health.get("can_takeover")):
            takeover_task_ids.append(task.task_id)
        if bool(health.get("can_resume")):
            resumable_task_ids.append(task.task_id)
        if task.status in TERMINAL_TASK_STATUSES:
            continue
        active_task_ids.append(task.task_id)
        lease_health.append(health)
        if task.lease is None:
            stale_nonterminal_task_ids.append(task.task_id)
            continue
        leased_task_ids.append(task.task_id)
        if task.lease.expired:
            expired_lease_task_ids.append(task.task_id)
            stale_nonterminal_task_ids.append(task.task_id)
    return {
        "schema": "octopus.task_runs_overview.v1",
        "total": len(tasks),
        "active_count": len(active_task_ids),
        "terminal_count": len(tasks) - len(active_task_ids),
        "leased_count": len(leased_task_ids),
        "expired_lease_count": len(expired_lease_task_ids),
        "stale_nonterminal_count": len(stale_nonterminal_task_ids),
        "takeover_recommended_count": len(takeover_task_ids),
        "resumable_count": len(resumable_task_ids),
        "by_status": dict(sorted(by_status.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "by_recommended_action": dict(sorted(by_recommended_action.items())),
        "active_task_ids": active_task_ids,
        "expired_lease_task_ids": expired_lease_task_ids,
        "stale_nonterminal_task_ids": stale_nonterminal_task_ids,
        "takeover_task_ids": takeover_task_ids,
        "resumable_task_ids": resumable_task_ids,
        "lease_health": lease_health,
        "generated_at": _now_iso(),
    }


def build_task_recovery_queue(
    tasks: list[TaskRunRecord],
    *,
    include_monitor: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    clean_limit = max(1, int(limit or 100))
    items: list[dict[str, Any]] = []
    for task in tasks:
        health = task_lease_health(task)
        action = str(health.get("recommended_action") or "monitor")
        actionable = bool(
            health.get("can_takeover")
            or health.get("can_resume")
            or action
            in {
                "dispatch",
                "await_operator_approval",
                "takeover_for_approval",
                "approval_policy_denied",
                "capability_policy_denied",
            }
        )
        if not include_monitor and not actionable:
            continue
        items.append(
            {
                "task_id": task.task_id,
                "status": task.status.value,
                "kind": task.kind,
                "title": task.title,
                "owner_id": task.owner_id,
                "thread_id": task.thread_id,
                "workspace_path": task.workspace_path,
                "recommended_action": action,
                "priority": _task_recovery_priority(action, health),
                "can_takeover": bool(health.get("can_takeover")),
                "can_resume": bool(health.get("can_resume")),
                "has_checkpoint": bool(health.get("has_checkpoint")),
                "latest_checkpoint_id": health.get("recovery", {}).get("latest_checkpoint_id"),
                "resume_checkpoint_id": health.get("recovery", {}).get("resume_checkpoint_id"),
                "checkpoint_id": health.get("recovery", {}).get("checkpoint_id"),
                "operation": health.get("recovery", {}).get("operation"),
                "steps": health.get("recovery", {}).get("steps", []),
                "recovery_plan": health.get("recovery"),
                "lease_health": health,
                "updated_at": task.updated_at,
                "created_at": task.created_at,
            }
        )
    items.sort(
        key=lambda item: (
            int(item["priority"]),
            str(item.get("updated_at") or ""),
            str(item.get("task_id") or ""),
        ),
        reverse=True,
    )
    return {
        "schema": "octopus.task_recovery_queue.v1",
        "total": len(items),
        "count": min(len(items), clean_limit),
        "limit": clean_limit,
        "items": items[:clean_limit],
        "generated_at": _now_iso(),
    }


def _task_recovery_priority(action: str, health: dict[str, Any]) -> int:
    priorities = {
        "takeover_and_resume": 100,
        "takeover_for_approval": 95,
        "resume_from_checkpoint": 90,
        "restart": 80,
        "resume_paused_task": 75,
        "takeover": 70,
        "dispatch": 60,
        "await_operator_approval": 50,
        "approval_policy_denied": 40,
        "capability_policy_denied": 40,
        "monitor": 10,
        "none": 0,
    }
    score = priorities.get(action, 20)
    if bool(health.get("can_takeover")):
        score += 5
    if bool(health.get("can_resume")):
        score += 3
    return score


def _task_recovery_operation(action: str) -> tuple[str, list[str]]:
    plans = {
        "takeover_and_resume": (
            "takeover_then_resume",
            ["takeover_task", "resume_from_checkpoint"],
        ),
        "takeover_for_approval": (
            "takeover_then_approval",
            ["takeover_task", "approval_decision"],
        ),
        "resume_from_checkpoint": ("resume_from_checkpoint", ["resume_from_checkpoint"]),
        "restart": ("restart_task", ["restart_task"]),
        "resume_paused_task": ("resume_paused_task", ["resume_task"]),
        "takeover": ("takeover_task", ["takeover_task"]),
        "dispatch": ("dispatch_task", ["dispatch_task"]),
        "await_operator_approval": ("approval_decision", ["approval_decision"]),
        "approval_policy_denied": ("review_policy", ["review_policy"]),
        "capability_policy_denied": ("review_policy", ["review_policy"]),
        "monitor": ("monitor", []),
        "none": ("none", []),
    }
    return plans.get(action, ("inspect_task", ["inspect_task"]))


def _empty_payload() -> dict[str, Any]:
    return {
        "schema": _SCHEMA,
        "version": 1,
        "lastUpdated": "",
        "leaseCounter": 0,
        "tasks": [],
    }


def _normalize_payload(raw: Any) -> dict[str, Any]:
    payload = _empty_payload()
    if not isinstance(raw, dict):
        return payload
    payload["lastUpdated"] = str(raw.get("lastUpdated") or "")
    try:
        payload["leaseCounter"] = max(0, int(raw.get("leaseCounter") or 0))
    except (TypeError, ValueError):
        payload["leaseCounter"] = 0
    rows: list[dict[str, Any]] = []
    for item in raw.get("tasks") or []:
        if not isinstance(item, dict):
            continue
        try:
            record = TaskRunRecord.model_validate(item)
        except Exception:
            continue
        rows.append(record.model_dump(mode="json"))
    payload["tasks"] = rows
    return payload


class TaskSupervisorStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()

    def upsert(self, record: TaskRunRecord) -> TaskRunRecord:
        def _mutate(
            existing: TaskRunRecord | None,
            next_lease_token: Callable[[], int],
        ) -> TaskRunRecord:
            del existing, next_lease_token
            return record

        return self.upsert_mutate(record.task_id, _mutate)

    def upsert_mutate(
        self,
        task_id: str,
        mutator: Callable[[TaskRunRecord | None, Callable[[], int]], TaskRunRecord],
    ) -> TaskRunRecord:
        with self._write_lock():
            payload = self._read_payload()
            tasks = self._read_tasks_from_payload(payload)
            now = _now_iso()
            existing: TaskRunRecord | None = None
            next_tasks: list[TaskRunRecord] = []
            for task in tasks:
                if task.task_id != task_id:
                    next_tasks.append(task)
                    continue
                existing = task

            def _next_lease_token() -> int:
                token = max(0, int(payload.get("leaseCounter") or 0)) + 1
                payload["leaseCounter"] = token
                return token

            candidate = mutator(existing, _next_lease_token)
            updated = candidate.model_copy(
                update={
                    "created_at": existing.created_at
                    if existing is not None
                    else candidate.created_at,
                    "updated_at": now,
                },
                deep=True,
            )
            next_tasks.append(updated)
            payload["tasks"] = self._dump_tasks(next_tasks)
            payload["lastUpdated"] = now
            self._write_payload(payload)
            return updated

    def get(self, task_id: str) -> TaskRunRecord | None:
        with self._lock:
            for task in self._read_tasks():
                if task.task_id == task_id:
                    return task
        return None

    def list(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        owner_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TaskRunRecord]:
        return self.list_page(
            status=status,
            kind=kind,
            owner_id=owner_id,
            thread_id=thread_id,
            limit=limit,
            offset=offset,
        )["items"]

    def list_page(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        owner_id: str | None = None,
        thread_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        clean_limit = max(1, int(limit or 100))
        clean_offset = max(0, int(offset or 0))
        with self._lock:
            tasks = self._filtered_tasks(
                status=status,
                kind=kind,
                owner_id=owner_id,
                thread_id=thread_id,
            )
            return {
                "items": tasks[clean_offset : clean_offset + clean_limit],
                "total": len(tasks),
                "limit": clean_limit,
                "offset": clean_offset,
            }

    def count(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        owner_id: str | None = None,
        thread_id: str | None = None,
    ) -> int:
        with self._lock:
            return len(
                self._filtered_tasks(
                    status=status,
                    kind=kind,
                    owner_id=owner_id,
                    thread_id=thread_id,
                )
            )

    def _filtered_tasks(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        owner_id: str | None = None,
        thread_id: str | None = None,
    ) -> list[TaskRunRecord]:
        tasks = self._read_tasks()
        if status:
            tasks = [task for task in tasks if task.status.value == str(status)]
        if kind:
            tasks = [task for task in tasks if task.kind == str(kind)]
        if owner_id is not None:
            tasks = [task for task in tasks if task.owner_id in (None, "", owner_id)]
        if thread_id is not None:
            tasks = [task for task in tasks if task.thread_id == thread_id]
        tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
        return tasks

    def overview(self) -> dict[str, Any]:
        with self._lock:
            tasks = self._read_tasks()
        return build_task_runs_overview(tasks)

    def recovery_queue(
        self,
        *,
        status: str | None = None,
        kind: str | None = None,
        owner_id: str | None = None,
        thread_id: str | None = None,
        include_monitor: bool = False,
        limit: int = 100,
    ) -> dict[str, Any]:
        with self._lock:
            tasks = self._filtered_tasks(
                status=status,
                kind=kind,
                owner_id=owner_id,
                thread_id=thread_id,
            )
        return build_task_recovery_queue(
            tasks,
            include_monitor=include_monitor,
            limit=limit,
        )

    def mutate(
        self,
        task_id: str,
        mutator: Callable[[TaskRunRecord], TaskRunRecord],
    ) -> TaskRunRecord:
        with self._write_lock():
            payload = self._read_payload()
            tasks = self._read_tasks_from_payload(payload)
            updated: TaskRunRecord | None = None
            next_tasks: list[TaskRunRecord] = []
            for task in tasks:
                if task.task_id != task_id:
                    next_tasks.append(task)
                    continue
                candidate = mutator(task)
                updated = candidate.model_copy(update={"updated_at": _now_iso()}, deep=True)
                next_tasks.append(updated)
            if updated is None:
                raise KeyError(task_id)
            payload["tasks"] = self._dump_tasks(next_tasks)
            payload["lastUpdated"] = updated.updated_at
            self._write_payload(payload)
            return updated

    def next_lease_token(self) -> int:
        with self._write_lock():
            payload = self._read_payload()
            token = max(0, int(payload.get("leaseCounter") or 0)) + 1
            payload["leaseCounter"] = token
            payload["lastUpdated"] = _now_iso()
            self._write_payload(payload)
            return token

    def _read_payload(self) -> dict[str, Any]:
        return _normalize_payload(read_json_with_backup(self.path, default=None))

    def _write_payload(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self.path, _normalize_payload(payload))

    def _write_lock(self) -> Any:
        target = self.path.parent / f"{self.path.name}.rw"
        return _StoreWriteLock(self._lock, target)

    def _read_tasks(self) -> list[TaskRunRecord]:
        return self._read_tasks_from_payload(self._read_payload())

    @staticmethod
    def _read_tasks_from_payload(payload: dict[str, Any]) -> list[TaskRunRecord]:
        tasks: list[TaskRunRecord] = []
        for item in payload.get("tasks") or []:
            if not isinstance(item, dict):
                continue
            try:
                tasks.append(TaskRunRecord.model_validate(item))
            except Exception:
                continue
        return tasks

    @staticmethod
    def _dump_tasks(tasks: list[TaskRunRecord]) -> list[dict[str, Any]]:
        return [cast(dict[str, Any], task.model_dump(mode="json")) for task in tasks]


class _StoreWriteLock:
    def __init__(self, thread_lock: threading.RLock, target: Path) -> None:
        self._thread_lock = thread_lock
        self._target = target
        self._process_lock: Any = None

    def __enter__(self) -> None:
        self._thread_lock.__enter__()
        self._process_lock = _cross_process_lock(self._target)
        self._process_lock.__enter__()

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            if self._process_lock is not None:
                self._process_lock.__exit__(exc_type, exc, tb)
        finally:
            self._thread_lock.__exit__(exc_type, exc, tb)


class TaskSupervisor:
    def __init__(
        self,
        store: TaskSupervisorStore,
        *,
        holder_id: str | None = None,
        lease_ttl_seconds: float = 300.0,
    ) -> None:
        self.store = store
        self.holder_id = str(holder_id or _DEFAULT_HOLDER_ID)
        self.lease_ttl_seconds = max(1.0, float(lease_ttl_seconds))
        self._lease_tokens: dict[str, int] = {}
        self._lease_lock = threading.RLock()

    @classmethod
    def from_path(
        cls,
        path: str | Path,
        *,
        holder_id: str | None = None,
        lease_ttl_seconds: float = 300.0,
    ) -> TaskSupervisor:
        return cls(
            TaskSupervisorStore(path),
            holder_id=holder_id,
            lease_ttl_seconds=lease_ttl_seconds,
        )

    def start_task(
        self,
        *,
        task_id: str,
        kind: str = "task",
        owner_id: str | None = None,
        thread_id: str | None = None,
        title: str = "",
        goal: str = "",
        mode: str = "",
        workspace_path: str | None = None,
        capabilities: TaskCapabilityManifest | dict[str, Any] | None = None,
        parent_task_id: str | None = None,
        origin_task_id: str | None = None,
        resume_checkpoint_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        status: TaskRunStatus = TaskRunStatus.RUNNING,
    ) -> TaskRunRecord:
        def _mutate(
            existing: TaskRunRecord | None,
            next_lease_token: Callable[[], int],
        ) -> TaskRunRecord:
            lease = existing.lease if existing is not None else None
            if (
                existing is not None
                and existing.status not in TERMINAL_TASK_STATUSES
                and lease is not None
                and not lease.expired
                and lease.holder_id != self.holder_id
            ):
                raise TaskLeaseConflict(task_id, lease.holder_id)
            if lease is None or lease.expired or lease.holder_id == self.holder_id:
                lease = self._new_lease(next_lease_token())
            now = _now_iso()
            completed_at = (
                existing.completed_at
                if existing is not None and status in TERMINAL_TASK_STATUSES
                else None
            )
            if status in TERMINAL_TASK_STATUSES:
                completed_at = completed_at or now
                lease = None
            next_workspace_path = _prefer_text(
                workspace_path,
                existing.workspace_path if existing is not None else None,
            )
            manifest = _coerce_manifest(
                capabilities
                if capabilities is not None
                else existing.capabilities
                if existing is not None
                else None,
                workspace_path=next_workspace_path,
            )
            next_metadata = dict(existing.metadata) if existing is not None else {}
            if isinstance(metadata, dict):
                next_metadata.update(metadata)
            if existing is not None and existing.status in TERMINAL_TASK_STATUSES:
                events = list(next_metadata.get("restart_events") or [])
                restart_event = {
                    "previous_status": existing.status.value,
                    "previous_completed_at": existing.completed_at,
                    "previous_terminal_reason": existing.terminal_reason,
                    "previous_checkpoint_id": existing.latest_checkpoint_id,
                    "restarted_at": now,
                    "holder_id": self.holder_id,
                    "next_status": status.value,
                }
                events.append(restart_event)
                next_metadata.update(
                    {
                        "restart": True,
                        "restart_at": now,
                        "restart_holder_id": self.holder_id,
                        "restart_from_status": existing.status.value,
                        "restart_from_checkpoint_id": existing.latest_checkpoint_id,
                        "restart_events": events,
                    }
                )
            return TaskRunRecord(
                task_id=task_id,
                kind=_prefer_kind(kind, existing.kind if existing is not None else None),
                owner_id=_prefer_text(
                    owner_id,
                    existing.owner_id if existing is not None else None,
                ),
                thread_id=_prefer_text(
                    thread_id,
                    existing.thread_id if existing is not None else None,
                ),
                parent_task_id=_prefer_text(
                    parent_task_id,
                    existing.parent_task_id if existing is not None else None,
                ),
                origin_task_id=_prefer_text(
                    origin_task_id,
                    existing.origin_task_id if existing is not None else None,
                ),
                resume_checkpoint_id=_prefer_text(
                    resume_checkpoint_id,
                    existing.resume_checkpoint_id if existing is not None else None,
                ),
                status=status,
                title=_prefer_text(title, existing.title if existing is not None else None) or "",
                goal=_prefer_text(goal, existing.goal if existing is not None else None) or "",
                mode=_prefer_text(mode, existing.mode if existing is not None else None) or "",
                workspace_path=next_workspace_path,
                capabilities=manifest,
                lease=lease,
                terminal_reason=(
                    existing.terminal_reason
                    if existing is not None and status in TERMINAL_TASK_STATUSES
                    else ""
                ),
                latest_checkpoint_id=existing.latest_checkpoint_id
                if existing is not None
                else None,
                metadata=next_metadata,
                started_at=(existing.started_at if existing is not None else None) or now,
                completed_at=completed_at,
                heartbeat_at=now,
            )

        record = self.store.upsert_mutate(task_id, _mutate)
        self._remember_lease(record)
        return record

    def transition(
        self,
        task_id: str,
        status: TaskRunStatus | str,
        *,
        reason: str = "",
        checkpoint_id: str | int | None = None,
        metadata_patch: dict[str, Any] | None = None,
    ) -> TaskRunRecord:
        next_status = status if isinstance(status, TaskRunStatus) else TaskRunStatus(str(status))
        now = _now_iso()

        def _mutate(current: TaskRunRecord) -> TaskRunRecord:
            if current.status in TERMINAL_TASK_STATUSES:
                metadata = dict(current.metadata)
                if isinstance(metadata_patch, dict):
                    metadata.update(metadata_patch)
                terminal_events = list(metadata.get("terminal_transition_events") or [])
                terminal_events.append(
                    {
                        "ignored_status": next_status.value,
                        "reason": str(reason or ""),
                        "checkpoint_id": checkpoint_id,
                        "previous_status": current.status.value,
                        "previous_terminal_reason": current.terminal_reason,
                        "previous_completed_at": current.completed_at,
                        "recorded_at": now,
                        "holder_id": self.holder_id,
                    }
                )
                metadata["terminal_transition_events"] = terminal_events
                return current.model_copy(
                    update={
                        "latest_checkpoint_id": checkpoint_id
                        if checkpoint_id is not None
                        else current.latest_checkpoint_id,
                        "metadata": metadata,
                        "heartbeat_at": current.heartbeat_at or now,
                        "lease": None,
                    },
                    deep=True,
                )
            if current.status not in TERMINAL_TASK_STATUSES:
                self._assert_current_holder(current)
            metadata = dict(current.metadata)
            if isinstance(metadata_patch, dict):
                metadata.update(metadata_patch)
            completed_at = current.completed_at
            lease = current.lease
            if current.status not in TERMINAL_TASK_STATUSES and lease is not None:
                lease = lease.model_copy(
                    update={
                        "heartbeat_at": now,
                        "expires_at": time.time() + self.lease_ttl_seconds,
                    }
                )
            if next_status in TERMINAL_TASK_STATUSES:
                completed_at = completed_at or now
                lease = None
            return current.model_copy(
                update={
                    "status": next_status,
                    "terminal_reason": reason or current.terminal_reason,
                    "latest_checkpoint_id": checkpoint_id
                    if checkpoint_id is not None
                    else current.latest_checkpoint_id,
                    "metadata": metadata,
                    "heartbeat_at": now,
                    "completed_at": completed_at,
                    "lease": lease,
                },
                deep=True,
            )

        record = self.store.mutate(task_id, _mutate)
        self._remember_lease(record)
        return record

    def record_approval_decision(
        self,
        task_id: str,
        *,
        approved: bool,
        decided_by: str | None = None,
        reason: str = "",
        resume_status: TaskRunStatus = TaskRunStatus.RUNNING,
    ) -> TaskRunRecord:
        now = _now_iso()
        clean_reason = str(reason or "").strip()
        clean_actor = str(decided_by or "").strip() or None
        next_status = resume_status if approved else TaskRunStatus.PAUSED
        if next_status in TERMINAL_TASK_STATUSES:
            raise ValueError("approval decision cannot transition directly to terminal")

        def _mutate(current: TaskRunRecord) -> TaskRunRecord:
            if current.status != TaskRunStatus.WAITING_APPROVAL:
                raise ValueError("task is not waiting for approval")
            self._assert_current_holder(current)
            metadata = dict(current.metadata)
            if bool(metadata.get("capability_denied")):
                raise ValueError("task is blocked by disabled capability")
            if bool(metadata.get("approval_denied")) and not bool(
                metadata.get("approval_required")
            ):
                raise ValueError("task is blocked by approval policy")
            decisions = list(metadata.get("approval_decisions") or [])
            decision = {
                "approved": bool(approved),
                "decided_by": clean_actor,
                "reason": clean_reason,
                "decided_at": now,
                "tool_name": metadata.get("approval_tool_name"),
                "approval_action": metadata.get("approval_action"),
            }
            decisions.append(decision)
            metadata.update(
                {
                    "approval_required": False,
                    "approval_denied": not approved,
                    "approval_decision": "approved" if approved else "rejected",
                    "approval_decided_by": clean_actor,
                    "approval_decided_at": now,
                    "approval_decision_reason": clean_reason,
                    "approval_decisions": decisions,
                }
            )
            if approved:
                metadata.pop("approval_reason", None)
            lease = current.lease
            if lease is not None:
                lease = lease.model_copy(
                    update={
                        "heartbeat_at": now,
                        "expires_at": time.time() + self.lease_ttl_seconds,
                    }
                )
            return current.model_copy(
                update={
                    "status": next_status,
                    "terminal_reason": "" if approved else clean_reason,
                    "metadata": metadata,
                    "heartbeat_at": now,
                    "completed_at": None,
                    "lease": lease,
                },
                deep=True,
            )

        record = self.store.mutate(task_id, _mutate)
        self._remember_lease(record)
        return record

    def takeover_task(
        self,
        task_id: str,
        *,
        by: str | None = None,
        reason: str = "",
        status: TaskRunStatus | str | None = None,
    ) -> TaskRunRecord:
        requested_status = (
            status
            if isinstance(status, TaskRunStatus)
            else TaskRunStatus(str(status))
            if status is not None
            else TaskRunStatus.RUNNING
        )
        if requested_status in TERMINAL_TASK_STATUSES:
            raise ValueError("takeover cannot transition directly to terminal")
        clean_actor = str(by or "").strip() or None
        clean_reason = str(reason or "").strip()

        def _mutate(
            existing: TaskRunRecord | None,
            next_lease_token: Callable[[], int],
        ) -> TaskRunRecord:
            if existing is None:
                raise KeyError(task_id)
            if existing.status in TERMINAL_TASK_STATUSES:
                raise ValueError("terminal task cannot be taken over")
            if existing.status == TaskRunStatus.WAITING_APPROVAL and (
                bool(existing.metadata.get("capability_denied"))
                or (
                    bool(existing.metadata.get("approval_denied"))
                    and not bool(existing.metadata.get("approval_required"))
                )
            ):
                raise ValueError("non-approvable task cannot be taken over")
            lease = existing.lease
            if lease is not None and not lease.expired and lease.holder_id != self.holder_id:
                raise TaskLeaseConflict(task_id, lease.holder_id)
            if lease is not None and not lease.expired and lease.holder_id == self.holder_id:
                raise ValueError("task is already held by this worker")
            now = _now_iso()
            metadata = dict(existing.metadata)
            events = list(metadata.get("takeover_events") or [])
            event = {
                "by": clean_actor,
                "reason": clean_reason,
                "previous_holder_id": lease.holder_id if lease is not None else None,
                "previous_lease_token": lease.token if lease is not None else None,
                "previous_status": existing.status.value,
                "taken_over_at": now,
            }
            events.append(event)
            metadata.update(
                {
                    "takeover": True,
                    "takeover_by": clean_actor,
                    "takeover_reason": clean_reason,
                    "takeover_at": now,
                    "takeover_events": events,
                }
            )
            next_status = (
                TaskRunStatus.WAITING_APPROVAL
                if existing.status == TaskRunStatus.WAITING_APPROVAL
                else requested_status
            )
            return existing.model_copy(
                update={
                    "status": next_status,
                    "metadata": metadata,
                    "heartbeat_at": now,
                    "lease": self._new_lease(next_lease_token()),
                    "completed_at": None,
                    "terminal_reason": "",
                },
                deep=True,
            )

        record = self.store.upsert_mutate(task_id, _mutate)
        self._remember_lease(record)
        return record

    def heartbeat(self, task_id: str) -> TaskRunRecord:
        now = _now_iso()

        def _mutate(current: TaskRunRecord) -> TaskRunRecord:
            if current.status in TERMINAL_TASK_STATUSES:
                return current
            self._assert_current_holder(current)
            lease = current.lease
            assert lease is not None
            lease = lease.model_copy(
                update={
                    "heartbeat_at": now,
                    "expires_at": time.time() + self.lease_ttl_seconds,
                }
            )
            return current.model_copy(
                update={
                    "heartbeat_at": now,
                    "lease": lease,
                },
                deep=True,
            )

        record = self.store.mutate(task_id, _mutate)
        self._remember_lease(record)
        return record

    def is_current_holder(self, task_id: str) -> bool:
        record = self.store.get(task_id)
        if record is None or record.status in TERMINAL_TASK_STATUSES:
            return False
        try:
            self._assert_current_holder(record)
        except LostTaskLease:
            return False
        return True

    def assert_current_holder(self, task_id: str) -> TaskRunRecord:
        record = self.store.get(task_id)
        if record is None:
            raise KeyError(task_id)
        if record.status in TERMINAL_TASK_STATUSES:
            raise LostTaskLease(task_id, "task is already terminal")
        self._assert_current_holder(record)
        return record

    def task_capabilities(self, task_id: str) -> TaskCapabilityManifest | None:
        record = self.store.get(task_id)
        return record.capabilities if record is not None else None

    def _new_lease(self, token: int) -> TaskLease:
        return TaskLease(
            holder_id=self.holder_id,
            token=token,
            expires_at=time.time() + self.lease_ttl_seconds,
        )

    def _assert_current_holder(self, record: TaskRunRecord) -> None:
        lease = record.lease
        if lease is None:
            raise LostTaskLease(record.task_id, "missing lease")
        if lease.expired:
            raise LostTaskLease(record.task_id, "lease expired")
        if lease.holder_id != self.holder_id:
            raise LostTaskLease(record.task_id, f"held by {lease.holder_id!r}")
        with self._lease_lock:
            expected_token = self._lease_tokens.get(record.task_id)
        if expected_token is not None and lease.token != expected_token:
            raise LostTaskLease(record.task_id, "lease token changed")

    def _remember_lease(self, record: TaskRunRecord) -> None:
        with self._lease_lock:
            if record.lease is not None and record.lease.holder_id == self.holder_id:
                self._lease_tokens[record.task_id] = record.lease.token
            else:
                self._lease_tokens.pop(record.task_id, None)


def _coerce_manifest(
    value: TaskCapabilityManifest | dict[str, Any] | None,
    *,
    workspace_path: str | None = None,
) -> TaskCapabilityManifest:
    if isinstance(value, TaskCapabilityManifest):
        manifest = value
    elif isinstance(value, dict):
        manifest = TaskCapabilityManifest.model_validate(value)
    else:
        manifest = TaskCapabilityManifest()
    workspace = str(workspace_path or "").strip()
    if workspace and workspace not in manifest.workspace_paths:
        manifest = manifest.model_copy(
            update={"workspace_paths": [*manifest.workspace_paths, workspace]},
            deep=True,
        )
    return manifest


def _prefer_text(value: Any, fallback: Any = None) -> str | None:
    text = str(value or "").strip()
    if text:
        return text
    fallback_text = str(fallback or "").strip()
    return fallback_text or None


def _prefer_kind(value: Any, fallback: Any = None) -> str:
    fallback_text = str(fallback or "").strip()
    text = str(value or "").strip()
    if fallback_text and text in {"", "task"}:
        return fallback_text
    return text or fallback_text or "task"


def manifest_from_session_metadata(
    metadata: dict[str, Any] | None,
) -> TaskCapabilityManifest | None:
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("task_capability_manifest") or metadata.get("capability_manifest")
    if isinstance(raw, TaskCapabilityManifest):
        return raw
    if isinstance(raw, dict):
        try:
            return TaskCapabilityManifest.model_validate(raw)
        except Exception:
            return None
    return None


__all__ = [
    "ACTIVE_TASK_STATUSES",
    "DEFAULT_CAPABILITY_GROUPS",
    "LostTaskLease",
    "TERMINAL_TASK_STATUSES",
    "TaskCapabilityManifest",
    "TaskLease",
    "TaskLeaseConflict",
    "TaskLeaseError",
    "TaskRunRecord",
    "TaskRunStatus",
    "TaskSupervisor",
    "TaskSupervisorStore",
    "build_task_recovery_queue",
    "build_task_runs_overview",
    "manifest_from_session_metadata",
    "task_lease_health",
    "task_recovery_advice",
]
