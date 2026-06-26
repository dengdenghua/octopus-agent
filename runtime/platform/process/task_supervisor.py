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
                    "created_at": existing.created_at if existing is not None else candidate.created_at,
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
        with self._lock:
            tasks = self._read_tasks()
        if status:
            tasks = [task for task in tasks if task.status.value == str(status)]
        if kind:
            tasks = [task for task in tasks if task.kind == str(kind)]
        if owner_id is not None:
            tasks = [task for task in tasks if task.owner_id == owner_id]
        if thread_id is not None:
            tasks = [task for task in tasks if task.thread_id == thread_id]
        tasks.sort(key=lambda task: (task.created_at, task.task_id), reverse=True)
        return tasks[offset: offset + limit]

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
        manifest = _coerce_manifest(capabilities, workspace_path=workspace_path)

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
            return TaskRunRecord(
                task_id=task_id,
                kind=kind,
                owner_id=owner_id,
                thread_id=thread_id,
                parent_task_id=parent_task_id,
                origin_task_id=origin_task_id,
                resume_checkpoint_id=resume_checkpoint_id,
                status=status,
                title=title,
                goal=goal,
                mode=mode,
                workspace_path=workspace_path,
                capabilities=manifest,
                lease=lease,
                metadata=metadata if isinstance(metadata, dict) else {},
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


def manifest_from_session_metadata(metadata: dict[str, Any] | None) -> TaskCapabilityManifest | None:
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
    "manifest_from_session_metadata",
]
