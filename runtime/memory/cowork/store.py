"""
CoworkStore · the on-disk plan/assignment/artifact triple.

Public surface (see ``__init__.py`` for the why):

    create_plan(session_id, created_by, tasks)   → Plan
    read_plan(session_id)                        → Plan | None
    advance_phase(session_id, target)            → Plan
    fail_stale_synthesis(session_id, ...)        → bool
    claim_task(session_id, task_id, agent_id)    → bool
    release_expired_leases(session_id)           → list[str]  ← NEW
    update_assignment_status(...)                → bool
    write_artifact(session_id, task_id, ...)     → Path
    read_artifacts(session_id)                   → dict[str, dict]
    list_sessions()                              → list[str]

Kanban upgrades
--------------
``claim_task`` now stamps a ``lease_expires_at`` on every claim.
``release_expired_leases`` scans all ``claimed``/``in_progress``
assignments and resets any whose lease has expired back to unclaimed,
so another worker can pick them up. The default lease is 10 minutes.

``KanbanDispatcher`` is a background daemon thread that calls
``release_expired_leases`` on a configurable tick (default 60 s) for
all active sessions, then optionally calls a user-supplied
``on_task_available`` callback so a worker pool can react immediately.

All writes go through ``atomic_write_json``; reads use
``read_json_with_backup`` so a corrupt primary file is automatically
recovered from ``<file>.bak``.

Concurrency
-----------
``claim_task`` is the only operation with non-trivial concurrency.
We take a per-session ``threading.Lock`` keyed on the assignments
file path, read-check-write inside it, and rely on the lock dict
dedupe-by-path (same approach used in ``ambient_suggestions``).
For a multi-process deployment we'd add an OS-level file lock here,
but the current contract is "single host, possibly multiple threads"
which the in-process lock + atomic rename covers.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from runtime.platform.io import atomic_write_json, read_json_with_backup

_LOG = logging.getLogger("octopus.memory.cowork")

# Default lease duration for a claimed task. Workers must call
# ``update_assignment_status`` to keep the lease alive (or complete
# the task). Expired leases are reset by ``KanbanDispatcher``.
DEFAULT_LEASE_SECONDS = 600  # 10 minutes
DEFAULT_SYNTHESIS_TIMEOUT_SECONDS = 1800  # 30 minutes


# ─── Phase model ────────────────────────────────────────────

PHASE_PLAN = "plan"
PHASE_WORK = "work"
PHASE_SYNTHESIZE = "synthesize"
PHASE_COMPLETE = "complete"
PHASE_FAILED = "failed"

VALID_PHASES = frozenset({PHASE_PLAN, PHASE_WORK, PHASE_SYNTHESIZE, PHASE_COMPLETE, PHASE_FAILED})

# Allowed forward transitions. ``failed`` is reachable from any
# phase as a manual irreversible escape hatch and is added below.
_ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    PHASE_PLAN: frozenset({PHASE_WORK, PHASE_FAILED}),
    PHASE_WORK: frozenset({PHASE_SYNTHESIZE, PHASE_FAILED}),
    PHASE_SYNTHESIZE: frozenset({PHASE_COMPLETE, PHASE_FAILED}),
    PHASE_COMPLETE: frozenset(),  # terminal
    PHASE_FAILED: frozenset(),  # terminal
}

# Assignment status values. We don't enforce a strict status machine
# here — agents may legitimately go claimed → in_progress → done, or
# straight to failed — but we DO validate the literal value to catch
# typos that would otherwise silently corrupt the on-disk JSON.
_VALID_ASSIGN_STATUS = frozenset({"claimed", "in_progress", "done", "failed"})

_FINAL_TASK_ID = "__final__"


# ─── Data classes ───────────────────────────────────────────


@dataclass
class Task:
    """One unit of work in the plan."""

    id: str
    title: str
    description: str = ""
    required_capabilities: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "required_capabilities": list(self.required_capabilities),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Task:
        return cls(
            id=str(raw["id"]),
            title=str(raw.get("title") or ""),
            description=str(raw.get("description") or ""),
            required_capabilities=[str(c) for c in (raw.get("required_capabilities") or [])],
        )


@dataclass
class Plan:
    """Top-level cowork plan persisted as ``plan.json``."""

    session_id: str
    created_at: str
    created_by: str
    phase: str
    tasks: list[Task] = field(default_factory=list)
    phase_updated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "created_by": self.created_by,
            "phase": self.phase,
            "tasks": [t.to_dict() for t in self.tasks],
            "phase_updated_at": self.phase_updated_at or self.created_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Plan:
        phase = str(raw.get("phase") or PHASE_PLAN)
        if phase not in VALID_PHASES:
            phase = PHASE_PLAN
        tasks_raw = raw.get("tasks") or []
        return cls(
            session_id=str(raw["session_id"]),
            created_at=str(raw.get("created_at") or ""),
            created_by=str(raw.get("created_by") or ""),
            phase=phase,
            tasks=[Task.from_dict(t) for t in tasks_raw if isinstance(t, dict) and t.get("id")],
            phase_updated_at=str(raw.get("phase_updated_at") or raw.get("created_at") or ""),
        )


@dataclass
class Assignment:
    """One row of ``assignments.json``."""

    agent_id: str
    claimed_at: str
    status: str = "claimed"
    artifact_ref: str | None = None
    completed_at: str | None = None
    # Kanban lease: ISO timestamp after which the claim expires and
    # another worker may re-claim the task. None = no expiry (legacy).
    lease_expires_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "claimed_at": self.claimed_at,
            "status": self.status,
            "artifact_ref": self.artifact_ref,
            "completed_at": self.completed_at,
            "lease_expires_at": self.lease_expires_at,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> Assignment:
        status = str(raw.get("status") or "claimed")
        if status not in _VALID_ASSIGN_STATUS:
            status = "claimed"
        return cls(
            agent_id=str(raw.get("agent_id") or ""),
            claimed_at=str(raw.get("claimed_at") or ""),
            status=status,
            artifact_ref=(
                str(raw["artifact_ref"]) if raw.get("artifact_ref") is not None else None
            ),
            completed_at=(
                str(raw["completed_at"]) if raw.get("completed_at") is not None else None
            ),
            lease_expires_at=(
                str(raw["lease_expires_at"]) if raw.get("lease_expires_at") is not None else None
            ),
        )


# ─── Helpers ────────────────────────────────────────────────


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _session_hash(session_id: str) -> str:
    return hashlib.sha1(session_id.encode("utf-8")).hexdigest()


# ─── Per-path lock registry ─────────────────────────────────


class _PathLockRegistry:
    """One ``threading.Lock`` per absolute path, deduped on creation.

    Same trick ``ambient_suggestions._BucketLock`` uses; reproduced
    here to keep the cowork module self-contained.
    """

    _locks: dict[str, threading.Lock] = {}
    _guard = threading.Lock()

    @classmethod
    def for_path(cls, path: Path) -> threading.Lock:
        key = str(path.resolve() if path.exists() else path.absolute())
        with cls._guard:
            lock = cls._locks.get(key)
            if lock is None:
                lock = threading.Lock()
                cls._locks[key] = lock
            return lock


# ─── Default base directory ─────────────────────────────────


def _default_base_dir() -> Path:
    """Resolve ``data/cowork`` the same way other memory modules do.

    ``OCTOPUS_DATA_DIR`` wins when set (tests, alternative installs);
    falls back to ``<cwd>/data/cowork`` via ``app_paths``.
    """
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "cowork"


# ─── Store ──────────────────────────────────────────────────


class CoworkStore:
    """File-system-backed multi-agent coordination state machine.

    A single instance can serve many sessions; sessions are isolated
    by ``<session_hash>/`` subdirectories under ``base_dir``.
    """

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._base_dir = Path(base_dir) if base_dir else _default_base_dir()

    # ─── Path helpers ───────────────────────────────────────

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def _session_dir(self, session_id: str) -> Path:
        return self._base_dir / _session_hash(session_id)

    def _plan_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "plan.json"

    def _assignments_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "assignments.json"

    def _artifacts_dir(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "artifacts"

    def _artifact_path(self, session_id: str, task_id: str) -> Path:
        return self._artifacts_dir(session_id) / f"{task_id}.json"

    # ─── Plan ───────────────────────────────────────────────

    def create_plan(
        self,
        session_id: str,
        created_by: str,
        tasks: list[Task] | list[dict[str, Any]],
    ) -> Plan:
        """Materialize a new plan.

        ``tasks`` accepts either ``Task`` instances or dicts with
        ``title``/``description``/``required_capabilities`` (``id``
        is auto-assigned when missing). Phase always starts at
        ``"plan"`` regardless of caller intent — they advance it
        explicitly via ``advance_phase``.
        """
        if not session_id:
            raise ValueError("session_id is required")
        if not created_by:
            raise ValueError("created_by is required")

        materialized: list[Task] = []
        for entry in tasks:
            if isinstance(entry, Task):
                t = entry
                if not t.id:
                    t = Task(
                        id=uuid4().hex,
                        title=t.title,
                        description=t.description,
                        required_capabilities=list(t.required_capabilities),
                    )
            elif isinstance(entry, dict):
                t = Task(
                    id=str(entry.get("id") or uuid4().hex),
                    title=str(entry.get("title") or ""),
                    description=str(entry.get("description") or ""),
                    required_capabilities=[
                        str(c) for c in (entry.get("required_capabilities") or [])
                    ],
                )
            else:
                raise TypeError(f"unexpected task entry type: {type(entry)!r}")
            materialized.append(t)

        now = _now_iso()
        plan = Plan(
            session_id=session_id,
            created_at=now,
            created_by=created_by,
            phase=PHASE_PLAN,
            tasks=materialized,
            phase_updated_at=now,
        )

        path = self._plan_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(path, plan.to_dict())

        # Also stamp an empty assignments file so subsequent reads
        # see a well-formed shape rather than missing-file fallbacks.
        assign_path = self._assignments_path(session_id)
        if not assign_path.exists():
            atomic_write_json(
                assign_path,
                {"session_id": session_id, "assignments": {}},
            )

        return plan

    def read_plan(self, session_id: str) -> Plan | None:
        """Return the plan for ``session_id`` or ``None`` if absent."""
        path = self._plan_path(session_id)
        raw = read_json_with_backup(path, default=None)
        if not isinstance(raw, dict) or not raw.get("session_id"):
            return None
        try:
            return Plan.from_dict(raw)
        except (KeyError, TypeError, ValueError):
            return None

    def advance_phase(self, session_id: str, target_phase: str) -> Plan:
        """Move the plan into ``target_phase`` if the transition is valid.

        Raises ``ValueError`` for unknown phases or illegal transitions
        (e.g. ``complete → plan``). Special-cases:

          - ``plan → work`` requires at least one task — moving to
            work with an empty task list deadlocks coordination.
          - ``work → synthesize`` is allowed regardless of how many
            assignments are done; callers can implement an "all
            done" gate by only calling this when ready.
          - ``synthesize → complete`` requires a final artifact written
            with ``task_id="__final__"``.
        """
        if target_phase not in VALID_PHASES:
            raise ValueError(f"unknown phase: {target_phase!r}")

        plan = self.read_plan(session_id)
        if plan is None:
            raise ValueError(f"no plan for session_id={session_id!r}; call create_plan first")

        if plan.phase == target_phase:
            return plan

        allowed = _ALLOWED_TRANSITIONS.get(plan.phase, frozenset())
        if target_phase not in allowed:
            raise ValueError(f"invalid phase transition {plan.phase!r} → {target_phase!r}")

        # Phase-specific preconditions.
        if plan.phase == PHASE_PLAN and target_phase == PHASE_WORK and not plan.tasks:
            raise ValueError("cannot advance to 'work': plan has 0 tasks")
        if plan.phase == PHASE_SYNTHESIZE and target_phase == PHASE_COMPLETE:
            final_path = self._artifact_path(session_id, _FINAL_TASK_ID)
            if not final_path.exists():
                raise ValueError(
                    "cannot advance to 'complete': no __final__ artifact "
                    "written; synthesizer must call write_artifact("
                    f"task_id={_FINAL_TASK_ID!r}) first"
                )

        plan.phase = target_phase
        plan.phase_updated_at = _now_iso()
        atomic_write_json(self._plan_path(session_id), plan.to_dict())
        return plan

    def fail_stale_synthesis(
        self,
        session_id: str,
        *,
        max_age_seconds: float = DEFAULT_SYNTHESIS_TIMEOUT_SECONDS,
        reason: str | None = None,
    ) -> bool:
        """Fail a synthesize-phase plan that has no final artifact past its TTL.

        The normal successful exit from ``synthesize`` is writing the
        ``__final__`` artifact and advancing to ``complete``. If the synthesizer
        crashes or never writes that artifact, the session otherwise remains
        stuck forever. This method is the recovery hatch used by
        ``KanbanDispatcher``: after the synthesize lease expires, mark the plan
        failed and write a diagnostic final artifact that UI/API callers can
        surface instead of waiting indefinitely.
        """
        plan = self.read_plan(session_id)
        if plan is None or plan.phase != PHASE_SYNTHESIZE:
            return False
        if self._artifact_path(session_id, _FINAL_TASK_ID).exists():
            return False

        ts_raw = plan.phase_updated_at or plan.created_at
        try:
            phase_updated_at = datetime.fromisoformat(ts_raw)
            if phase_updated_at.tzinfo is None:
                phase_updated_at = phase_updated_at.replace(tzinfo=UTC)
        except (TypeError, ValueError):
            phase_updated_at = datetime.now(UTC)

        age = (datetime.now(UTC) - phase_updated_at).total_seconds()
        if age < max(0.0, float(max_age_seconds)):
            return False

        message = reason or ("synthesis timed out before __final__ artifact was written")
        self.write_artifact(
            session_id,
            _FINAL_TASK_ID,
            "system",
            {
                "status": PHASE_FAILED,
                "reason": message,
                "phase": PHASE_SYNTHESIZE,
                "age_seconds": round(age, 3),
            },
        )
        plan.phase = PHASE_FAILED
        plan.phase_updated_at = _now_iso()
        atomic_write_json(self._plan_path(session_id), plan.to_dict())
        _LOG.warning(
            "cowork: session %s failed stale synthesis after %.1fs: %s",
            session_id,
            age,
            message,
        )
        return True

    # ─── Assignments ────────────────────────────────────────

    def _read_assignments_raw(self, session_id: str) -> dict[str, Any]:
        path = self._assignments_path(session_id)
        raw = read_json_with_backup(path, default=None)
        if not isinstance(raw, dict):
            return {"session_id": session_id, "assignments": {}}
        if not isinstance(raw.get("assignments"), dict):
            raw["assignments"] = {}
        raw.setdefault("session_id", session_id)
        return raw

    def claim_task(
        self,
        session_id: str,
        task_id: str,
        agent_id: str,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        """Atomically reserve ``task_id`` for ``agent_id``.

        Returns ``True`` on success, ``False`` if the task was already
        claimed (by anyone, including the same agent — claiming is
        idempotent only at the bool level: a re-claim returns False
        without overwriting the original ``claimed_at``).

        Kanban lease: the claim is stamped with ``lease_expires_at``
        (``now + lease_seconds``). If the worker does not complete or
        renew the task before that timestamp, ``release_expired_leases``
        will reset it so another worker can pick it up.

        Implementation: we serialize all read-modify-write cycles
        for the same assignments file through a per-path mutex, then
        the actual disk write is via ``atomic_write_json`` (temp +
        rename). Concurrent ``claim_task`` calls from N threads in
        the same process produce exactly one ``True``; the rest see
        the slot already filled inside the lock and return False
        without writing.
        """
        if not task_id:
            raise ValueError("task_id is required")
        if not agent_id:
            raise ValueError("agent_id is required")

        plan = self.read_plan(session_id)
        if plan is None:
            raise ValueError(f"no plan for session_id={session_id!r}")
        if not any(t.id == task_id for t in plan.tasks):
            raise ValueError(f"task_id {task_id!r} not in plan for session {session_id!r}")

        path = self._assignments_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = _PathLockRegistry.for_path(path)

        with lock:
            data = self._read_assignments_raw(session_id)
            assignments: dict[str, Any] = data["assignments"]

            existing = assignments.get(task_id)
            if isinstance(existing, dict) and existing.get("agent_id"):
                return False

            now = datetime.now(UTC)
            expires = (now + timedelta(seconds=lease_seconds)).isoformat()
            assignments[task_id] = Assignment(
                agent_id=agent_id,
                claimed_at=now.isoformat(),
                status="claimed",
                lease_expires_at=expires,
            ).to_dict()
            data["assignments"] = assignments
            atomic_write_json(path, data)
            return True

    def release_expired_leases(self, session_id: str) -> list[str]:
        """Reset any claimed/in_progress tasks whose lease has expired.

        Returns the list of task_ids that were released so callers
        (e.g. ``KanbanDispatcher``) can notify waiting workers.

        A released task has its assignment row deleted entirely so
        ``claim_task`` treats it as unclaimed on the next attempt.
        """
        path = self._assignments_path(session_id)
        if not path.exists():
            return []
        lock = _PathLockRegistry.for_path(path)
        released: list[str] = []
        now = datetime.now(UTC)

        with lock:
            data = self._read_assignments_raw(session_id)
            assignments: dict[str, Any] = data["assignments"]
            changed = False

            for task_id, raw in list(assignments.items()):
                if not isinstance(raw, dict):
                    continue
                status = raw.get("status", "")
                if status in ("done", "failed"):
                    continue  # terminal — never expire
                lease_raw = raw.get("lease_expires_at")
                if not lease_raw:
                    continue  # no lease set (legacy row)
                try:
                    expires = datetime.fromisoformat(lease_raw)
                    if expires.tzinfo is None:
                        expires = expires.replace(tzinfo=UTC)
                except ValueError:
                    continue
                if now >= expires:
                    del assignments[task_id]
                    released.append(task_id)
                    changed = True
                    _LOG.info(
                        "cowork: lease expired for task %s in session %s (was held by %s)",
                        task_id,
                        session_id,
                        raw.get("agent_id", "?"),
                    )

            if changed:
                data["assignments"] = assignments
                atomic_write_json(path, data)

        return released

    def renew_lease(
        self,
        session_id: str,
        task_id: str,
        agent_id: str,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> bool:
        """Extend the lease on an active assignment.

        Returns ``True`` if the lease was renewed, ``False`` if the
        assignment doesn't exist or belongs to a different agent.
        Workers should call this periodically for long-running tasks.
        """
        path = self._assignments_path(session_id)
        lock = _PathLockRegistry.for_path(path)

        with lock:
            data = self._read_assignments_raw(session_id)
            assignments: dict[str, Any] = data["assignments"]
            existing = assignments.get(task_id)
            if not isinstance(existing, dict):
                return False
            if existing.get("agent_id") != agent_id:
                return False
            if existing.get("status") in ("done", "failed"):
                return False
            new_expires = (datetime.now(UTC) + timedelta(seconds=lease_seconds)).isoformat()
            existing["lease_expires_at"] = new_expires
            assignments[task_id] = existing
            data["assignments"] = assignments
            atomic_write_json(path, data)
            return True

    def update_assignment_status(
        self,
        session_id: str,
        task_id: str,
        status: str,
        artifact_ref: str | None = None,
    ) -> bool:
        """Update an existing assignment's lifecycle state.

        Returns ``True`` on success, ``False`` when there is no
        assignment for ``task_id`` yet (a noisy no-op rather than a
        raise so coordinator code can call this opportunistically).
        ``ValueError`` on unknown status — that's a programming
        error worth surfacing.

        Side effect: setting status=``done`` or ``failed`` stamps
        ``completed_at``.
        """
        if status not in _VALID_ASSIGN_STATUS:
            raise ValueError(f"invalid status {status!r}")

        path = self._assignments_path(session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        lock = _PathLockRegistry.for_path(path)

        with lock:
            data = self._read_assignments_raw(session_id)
            assignments: dict[str, Any] = data["assignments"]
            existing = assignments.get(task_id)
            if not isinstance(existing, dict):
                return False
            previous_status = str(existing.get("status") or "")
            if previous_status in {"done", "failed"}:
                if previous_status == status == "done" and artifact_ref is not None:
                    existing["artifact_ref"] = artifact_ref
                    assignments[task_id] = existing
                    data["assignments"] = assignments
                    atomic_write_json(path, data)
                    return True
                return False
            existing["status"] = status
            if artifact_ref is not None:
                existing["artifact_ref"] = artifact_ref
            if status in ("done", "failed"):
                existing["completed_at"] = _now_iso()
            assignments[task_id] = existing
            data["assignments"] = assignments
            atomic_write_json(path, data)
            return True

    def read_assignments(self, session_id: str) -> dict[str, Assignment]:
        """Return all assignments for a session, keyed by task_id."""
        data = self._read_assignments_raw(session_id)
        out: dict[str, Assignment] = {}
        for task_id, raw in data["assignments"].items():
            if isinstance(raw, dict):
                out[str(task_id)] = Assignment.from_dict(raw)
        return out

    # ─── Artifacts ──────────────────────────────────────────

    def write_artifact(
        self,
        session_id: str,
        task_id: str,
        agent_id: str,
        output: Any,
    ) -> Path:
        """Persist a task artifact and update the assignment.

        For a regular ``task_id`` we additionally flip its
        assignment to status=``done`` and stamp ``artifact_ref`` to
        the relative path. The synthesizer's final artifact uses
        the sentinel ``task_id="__final__"`` and skips the
        assignment update — there's no slot for it.
        """
        if not task_id:
            raise ValueError("task_id is required")
        if not agent_id:
            raise ValueError("agent_id is required")

        artifact_path = self._artifact_path(session_id, task_id)
        artifact_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "task_id": task_id,
            "agent_id": agent_id,
            "output": output,
            "ts": _now_iso(),
        }
        atomic_write_json(artifact_path, payload)

        # Update assignment for non-synthetic task ids only. Use a
        # path RELATIVE to the session dir for ``artifact_ref`` so
        # the on-disk JSON stays portable across machines / mounts.
        if task_id != _FINAL_TASK_ID:
            rel_ref = f"artifacts/{task_id}.json"
            self.update_assignment_status(
                session_id,
                task_id,
                status="done",
                artifact_ref=rel_ref,
            )

        return artifact_path

    def read_artifacts(self, session_id: str) -> dict[str, dict[str, Any]]:
        """Return every artifact for ``session_id`` keyed by task_id.

        Reads each ``artifacts/<task_id>.json`` via
        ``read_json_with_backup`` so a corrupt primary still recovers
        from ``.bak``. Skips files that fail to parse outright.
        """
        out: dict[str, dict[str, Any]] = {}
        artifacts_dir = self._artifacts_dir(session_id)
        if not artifacts_dir.is_dir():
            return out
        for entry in sorted(artifacts_dir.iterdir()):
            if not entry.is_file() or not entry.name.endswith(".json"):
                continue
            # Skip .bak siblings — read_json_with_backup will pick
            # them up automatically when the primary is unreadable.
            if entry.name.endswith(".json.bak"):
                continue
            raw = read_json_with_backup(entry, default=None)
            if not isinstance(raw, dict):
                continue
            task_id = str(raw.get("task_id") or entry.stem)
            out[task_id] = raw
        return out

    # ─── Discovery ──────────────────────────────────────────

    def list_sessions(self) -> list[str]:
        """Return every session id with at least a ``plan.json`` on disk.

        We can't reverse a SHA-1 directory name back to its session id,
        so we recover the id by reading the plan file inside each
        session directory. Directories without a parseable plan are
        ignored — they're either mid-creation or were corrupted.
        """
        if not self._base_dir.is_dir():
            return []
        ids: list[str] = []
        for entry in self._base_dir.iterdir():
            if not entry.is_dir():
                continue
            plan_path = entry / "plan.json"
            raw = read_json_with_backup(plan_path, default=None)
            if not isinstance(raw, dict):
                continue
            sid = raw.get("session_id")
            if isinstance(sid, str) and sid:
                ids.append(sid)
        ids.sort()
        return ids


# ─── KanbanDispatcher ───────────────────────────────────────


class KanbanDispatcher:
    """Background daemon that periodically expires stale leases.

    Starts a single daemon thread that wakes every ``tick_seconds``
    (default 60) and calls ``CoworkStore.release_expired_leases`` for
    every active session. When tasks are released it fires the optional
    ``on_task_available`` callback with the session_id and the list of
    newly-available task_ids so a worker pool can react immediately.

    Usage::

        store = CoworkStore()
        dispatcher = KanbanDispatcher(store)
        dispatcher.start()          # daemon — stops when process exits
        # …
        dispatcher.stop()           # graceful shutdown (joins thread)

    The dispatcher is intentionally lightweight: it does not maintain
    its own session registry — it calls ``store.list_sessions()`` on
    every tick so newly-created sessions are picked up automatically
    and deleted sessions are silently skipped.
    """

    def __init__(
        self,
        store: CoworkStore,
        *,
        tick_seconds: float = 60.0,
        synthesis_timeout_seconds: float = DEFAULT_SYNTHESIS_TIMEOUT_SECONDS,
        on_task_available: Callable[[str, list[str]], None] | None = None,
    ) -> None:
        self._store = store
        self._tick = tick_seconds
        self._synthesis_timeout = synthesis_timeout_seconds
        self._on_task_available = on_task_available
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._total_ticks = 0
        self._total_failures = 0
        self._consecutive_failures = 0
        self._last_tick_at: str | None = None
        self._last_success_at: str | None = None
        self._last_failure_at: str | None = None
        self._last_error: str | None = None
        self._last_released_count = 0
        self._last_failed_synthesis_count = 0

    # ── lifecycle ───────────────────────────────────────────

    def start(self) -> None:
        """Start the background daemon thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="KanbanDispatcher",
            daemon=True,
        )
        self._thread.start()
        _LOG.debug("KanbanDispatcher started (tick=%.0fs)", self._tick)

    def stop(self, timeout: float = 5.0) -> None:
        """Signal the daemon to stop and wait for it to exit."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        _LOG.debug("KanbanDispatcher stopped")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        """Operational health snapshot for observability endpoints/tests."""
        with self._state_lock:
            return {
                "running": self.running,
                "tick_seconds": self._tick,
                "synthesis_timeout_seconds": self._synthesis_timeout,
                "total_ticks": self._total_ticks,
                "total_failures": self._total_failures,
                "consecutive_failures": self._consecutive_failures,
                "last_tick_at": self._last_tick_at,
                "last_success_at": self._last_success_at,
                "last_failure_at": self._last_failure_at,
                "last_error": self._last_error,
                "last_released_count": self._last_released_count,
                "last_failed_synthesis_count": self._last_failed_synthesis_count,
            }

    # ── internal ────────────────────────────────────────────

    def _run(self) -> None:
        while not self._stop_event.wait(timeout=self._tick):
            self._tick_once()

    def _record_tick_result(
        self,
        *,
        success: bool,
        released_count: int = 0,
        failed_synthesis_count: int = 0,
        error: str | None = None,
    ) -> None:
        now = _now_iso()
        with self._state_lock:
            self._total_ticks += 1
            self._last_tick_at = now
            self._last_released_count = released_count
            self._last_failed_synthesis_count = failed_synthesis_count
            if success:
                self._consecutive_failures = 0
                self._last_error = None
                self._last_success_at = now
                return
            self._total_failures += 1
            self._consecutive_failures += 1
            self._last_error = error or "tick failed"
            self._last_failure_at = now

    @staticmethod
    def _format_error(scope: str, exc: BaseException) -> str:
        return f"{scope}: {type(exc).__name__}: {exc}"

    def _tick_once(self) -> None:
        released_count = 0
        failed_synthesis_count = 0
        errors: list[str] = []
        try:
            sessions = self._store.list_sessions()
        except Exception as exc:  # noqa: BLE001
            error = self._format_error("list_sessions", exc)
            _LOG.warning("KanbanDispatcher: list_sessions failed: %s", exc, exc_info=True)
            self._record_tick_result(success=False, error=error)
            return

        for session_id in sessions:
            try:
                released = self._store.release_expired_leases(session_id)
                failed_synthesis = self._store.fail_stale_synthesis(
                    session_id,
                    max_age_seconds=self._synthesis_timeout,
                )
                released_count += len(released)
                if failed_synthesis:
                    failed_synthesis_count += 1
                if released:
                    _LOG.info(
                        "KanbanDispatcher: released %d task(s) in session %s: %s",
                        len(released),
                        session_id,
                        released,
                    )
                    if self._on_task_available is not None:
                        try:
                            self._on_task_available(session_id, released)
                        except Exception as cb_exc:  # noqa: BLE001
                            errors.append(self._format_error(f"callback:{session_id}", cb_exc))
                            _LOG.warning(
                                "KanbanDispatcher: on_task_available callback raised: %s",
                                cb_exc,
                                exc_info=True,
                            )
                if failed_synthesis:
                    _LOG.warning(
                        "KanbanDispatcher: failed stale synthesis in session %s",
                        session_id,
                    )
            except Exception as exc:  # noqa: BLE001
                errors.append(self._format_error(f"session:{session_id}", exc))
                _LOG.warning(
                    "KanbanDispatcher: error processing session %s: %s",
                    session_id,
                    exc,
                    exc_info=True,
                )
        self._record_tick_result(
            success=not errors,
            released_count=released_count,
            failed_synthesis_count=failed_synthesis_count,
            error="; ".join(errors) if errors else None,
        )


__all__ = [
    "Assignment",
    "CoworkStore",
    "DEFAULT_LEASE_SECONDS",
    "DEFAULT_SYNTHESIS_TIMEOUT_SECONDS",
    "KanbanDispatcher",
    "PHASE_COMPLETE",
    "PHASE_FAILED",
    "PHASE_PLAN",
    "PHASE_SYNTHESIZE",
    "PHASE_WORK",
    "Plan",
    "Task",
    "VALID_PHASES",
]
