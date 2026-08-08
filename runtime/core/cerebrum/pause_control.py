from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Literal

from runtime.platform.config.schema import (
    BUDGET_DEFAULT_MAX_TOKENS,
    BUDGET_DEFAULT_MAX_USD,
)
from runtime.platform.io import atomic_write_json
from runtime.platform.process.paths import app_paths
from runtime.platform.process.service_provider import get_provider

_log = logging.getLogger(__name__)

PauseReason = Literal[
    "user_request",  # Implementation note.
    "budget_near_limit",  # Implementation note.
    "iteration_near_limit",  # Implementation note.
    "model_spinning",  # Implementation note.
    "client_disconnect",  # Implementation note.
    "external",  # Implementation note.
]


@dataclass
class ActiveTask:
    task_id: str
    thread_id: str = ""
    agent_id: str = ""
    started_at: float = field(default_factory=time.time)
    current_iteration: int = 0
    max_iterations: int = 0
    tokens_spent: int = 0
    cost_usd: float = 0.0
    max_tokens: int = BUDGET_DEFAULT_MAX_TOKENS  # Implementation note.
    max_usd: float = BUDGET_DEFAULT_MAX_USD

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "thread_id": self.thread_id,
            "agent_id": self.agent_id,
            "started_at": self.started_at,
            "current_iteration": self.current_iteration,
            "max_iterations": self.max_iterations,
            "tokens_spent": self.tokens_spent,
            "cost_usd": self.cost_usd,
            "max_tokens": self.max_tokens,
            "max_usd": self.max_usd,
        }


@dataclass
class PauseRequest:
    task_id: str
    reason: PauseReason = "user_request"
    requested_at: float = field(default_factory=time.time)
    requested_by: str = ""  # Implementation note.
    note: str = ""  # Implementation note.
    thread_id: str = ""  # Implementation note.
    agent_id: str = ""  # Implementation note.

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "reason": self.reason,
            "requested_at": self.requested_at,
            "requested_by": self.requested_by,
            "note": self.note,
            "thread_id": self.thread_id,
            "agent_id": self.agent_id,
        }


def _default_store_path() -> Path:
    return app_paths().data_dir / "pause_state.json"


_USE_DEFAULT_STORE = object()


class PauseController:
    # Expire granted iteration/token/usd extensions and pending resume
    # handoffs after this long, so a crashed task can't leak dicts
    # forever. Observed pause cycles are seconds; 7 days is a generous
    # upper bound that still guarantees a boot-time GC window.
    _GRANT_TTL_SECONDS = 7 * 24 * 3600
    _PENDING_RESUME_TTL_SECONDS = 7 * 24 * 3600
    # Pause records older than this are considered abandoned and GC'd.
    # If a user hasn't clicked Continue in 7 days, they're not coming back,
    # and the yellow "waiting" light in the sidebar is pure noise.
    _PAUSE_TTL_SECONDS = 7 * 24 * 3600

    def __init__(
        self,
        *,
        store_path: Path | None | object = _USE_DEFAULT_STORE,
        autoload: bool = True,
    ) -> None:
        self._lock = RLock()
        self._pending: dict[str, PauseRequest] = {}
        self._paused: dict[str, PauseRequest] = {}
        self._grants: dict[str, dict[str, int | float]] = {}
        self._grants_ts: dict[str, float] = {}
        self._pending_resumes: dict[str, str] = {}
        self._pending_resumes_ts: dict[str, float] = {}
        self._active: dict[str, ActiveTask] = {}
        self._store_path: Path | None
        if store_path is _USE_DEFAULT_STORE:
            self._store_path = _default_store_path()
        elif store_path is None:
            self._store_path = None
        else:
            assert isinstance(store_path, (str, Path))
            self._store_path = Path(store_path)
        if autoload and self._store_path is not None:
            self._load()

    def _gc_grants_locked(self) -> None:
        cutoff = time.time() - self._GRANT_TTL_SECONDS
        stale = [k for k, ts in self._grants_ts.items() if ts < cutoff]
        for k in stale:
            self._grants.pop(k, None)
            self._grants_ts.pop(k, None)

    def _gc_pending_resumes_locked(self) -> None:
        cutoff = time.time() - self._PENDING_RESUME_TTL_SECONDS
        stale = [k for k, ts in self._pending_resumes_ts.items() if ts < cutoff]
        for k in stale:
            self._pending_resumes.pop(k, None)
            self._pending_resumes_ts.pop(k, None)

    def _gc_stale_pauses_locked(self) -> int:
        """Remove stale pause/pending records:
        - Records older than _PAUSE_TTL_SECONDS (user abandoned them)
        - Records with empty thread_id (orphans: can never map to a sidebar
          thread, so they cannot produce a yellow light but still bloat
          /api/tasks responses and the persisted state file)
        Returns the number of records removed.
        """
        now = time.time()
        cutoff = now - self._PAUSE_TTL_SECONDS
        removed = 0
        for bucket in (self._pending, self._paused):
            stale_keys = [
                k for k, req in bucket.items() if req.requested_at < cutoff or not req.thread_id
            ]
            for k in stale_keys:
                bucket.pop(k, None)
                removed += 1
        return removed

    def _deduplicate_system_pauses_locked(self) -> int:
        """Keep one newest automatic pause per thread across both buckets.

        This is a load-time migration as well as a runtime invariant.  Merely
        deduplicating new writes leaves old production files permanently
        ambiguous and makes "Continue" select by accident.
        """

        newest: dict[str, tuple[str, float]] = {}
        for bucket in (self._pending, self._paused):
            for task_id, request in bucket.items():
                if not (
                    request.thread_id
                    and request.requested_by == "system"
                    and request.reason
                    in {
                        "iteration_near_limit",
                        "budget_near_limit",
                        "model_spinning",
                    }
                ):
                    continue
                current = newest.get(request.thread_id)
                if current is None or request.requested_at > current[1]:
                    newest[request.thread_id] = (task_id, request.requested_at)

        removed = 0
        for bucket in (self._pending, self._paused):
            stale = [
                task_id
                for task_id, request in bucket.items()
                if request.thread_id in newest
                and request.requested_by == "system"
                and request.reason
                in {"iteration_near_limit", "budget_near_limit", "model_spinning"}
                and newest[request.thread_id][0] != task_id
            ]
            for task_id in stale:
                bucket.pop(task_id, None)
                removed += 1
        return removed

    def _load(self) -> None:
        path = self._store_path
        if path is None or not path.is_file():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            for bucket, target in (
                ("pending", self._pending),
                ("paused", self._paused),
            ):
                for rec in data.get(bucket) or []:
                    if not isinstance(rec, dict):
                        continue
                    tid = rec.get("task_id")
                    if not isinstance(tid, str):
                        continue
                    target[tid] = PauseRequest(
                        task_id=tid,
                        reason=rec.get("reason", "user_request"),
                        requested_at=rec.get("requested_at", time.time()),
                        requested_by=rec.get("requested_by", ""),
                        note=rec.get("note", ""),
                        thread_id=rec.get("thread_id", ""),
                        agent_id=rec.get("agent_id", ""),
                    )
            # GC stale/orphan records immediately after load so the
            # persisted file stays clean and /api/tasks doesn't serve
            # yellow-light data for threads that finished long ago.
            removed = self._gc_stale_pauses_locked()
            removed += self._deduplicate_system_pauses_locked()
            if removed:
                _log.info(
                    "pause_control: GC'd %d stale pause record(s) on load",
                    removed,
                )
                self._persist_locked()
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            _log.warning(
                "pause_control load failed (%s: %s) — starting empty",
                type(exc).__name__,
                exc,
            )

    def _persist_locked(self) -> None:
        path = self._store_path
        if path is None:
            return
        try:
            payload = {
                "pending": [asdict(r) for r in self._pending.values()],
                "paused": [asdict(r) for r in self._paused.values()],
            }
            atomic_write_json(path, payload)
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                "pause_control persist failed (%s: %s) — in-memory state still correct",
                type(exc).__name__,
                exc,
            )

    def request_pause(
        self,
        task_id: str,
        reason: PauseReason = "user_request",
        requested_by: str = "",
        note: str = "",
        thread_id: str = "",
        agent_id: str = "",
    ) -> PauseRequest:
        req = PauseRequest(
            task_id=task_id,
            reason=reason,
            requested_by=requested_by,
            note=note,
            thread_id=thread_id,
            agent_id=agent_id,
        )
        with self._lock:
            # A thread can have only one live system-generated iteration
            # boundary. Older releases created a new task when the user typed
            # "继续", leaving several equivalent yellow pause records for the
            # same conversation. Collapse only those automatic records here;
            # explicit user pauses remain independent.
            if (
                reason in {"iteration_near_limit", "budget_near_limit", "model_spinning"}
                and requested_by == "system"
                and thread_id
            ):
                for bucket in (self._pending, self._paused):
                    duplicates = [
                        existing_id
                        for existing_id, existing in bucket.items()
                        if existing_id != task_id
                        and existing.thread_id == thread_id
                        and existing.reason
                        in {"iteration_near_limit", "budget_near_limit", "model_spinning"}
                        and existing.requested_by == "system"
                    ]
                    for existing_id in duplicates:
                        bucket.pop(existing_id, None)
            if task_id not in self._paused:
                self._pending[task_id] = req
            self._persist_locked()
        return req

    def mark_paused(self, task_id: str) -> PauseRequest | None:
        with self._lock:
            req = self._pending.pop(task_id, None)
            if req is None:
                req = PauseRequest(task_id=task_id, reason="external")
            self._paused[task_id] = req
            self._persist_locked()
        return req

    def clear(self, task_id: str) -> None:
        with self._lock:
            changed = (
                self._pending.pop(task_id, None) is not None
                or self._paused.pop(task_id, None) is not None
            )
            if changed:
                self._persist_locked()

    def set_grant(
        self,
        task_id: str,
        *,
        extra_iterations: int = 0,
        extra_tokens: int = 0,
        extra_usd: float = 0.0,
    ) -> None:
        with self._lock:
            self._grants[task_id] = {
                "extra_iterations": int(extra_iterations or 0),
                "extra_tokens": int(extra_tokens or 0),
                "extra_usd": float(extra_usd or 0.0),
            }
            self._grants_ts[task_id] = time.time()
            self._gc_grants_locked()

    def consume_grant(self, task_id: str) -> dict[str, int | float]:
        with self._lock:
            self._grants_ts.pop(task_id, None)
            return self._grants.pop(
                task_id,
                {
                    "extra_iterations": 0,
                    "extra_tokens": 0,
                    "extra_usd": 0.0,
                },
            )

    def set_pending_resume(self, thread_id: str, task_id: str) -> None:
        if not thread_id or not task_id:
            return
        with self._lock:
            self._pending_resumes[thread_id] = task_id
            self._pending_resumes_ts[thread_id] = time.time()
            self._gc_pending_resumes_locked()

    def consume_pending_resume(self, thread_id: str) -> str | None:
        if not thread_id:
            return None
        with self._lock:
            self._pending_resumes_ts.pop(thread_id, None)
            return self._pending_resumes.pop(thread_id, None)

    # ─── Journal-based recovery (D3) ──────────────────

    def recover_from_journal(self, journal: object) -> int:
        if journal is None:
            return 0
        read_by_type = getattr(journal, "read_by_type", None)
        if read_by_type is None:
            return 0
        try:
            ckpts = list(read_by_type("react_checkpoint"))
            paused_events = list(read_by_type("task_paused"))
            resumed_events = list(read_by_type("task_resumed"))
        except (AttributeError, OSError):
            return 0

        last_ckpt: dict[str, object] = {}
        for e in ckpts:
            tid = str(getattr(e, "task_id", "") or "")
            if tid:
                last_ckpt[tid] = e

        last_state_ts: dict[str, tuple[float, str]] = {}
        for e in paused_events:
            tid = str(getattr(e, "task_id", "") or "")
            ts = float(getattr(e, "timestamp", 0) or 0)
            if tid and ts >= last_state_ts.get(tid, (0, ""))[0]:
                last_state_ts[tid] = (ts, "paused")
        for e in resumed_events:
            tid = str(getattr(e, "task_id", "") or "")
            ts = float(getattr(e, "timestamp", 0) or 0)
            if tid and ts >= last_state_ts.get(tid, (0, ""))[0]:
                last_state_ts[tid] = (ts, "resumed")

        recovered = 0
        with self._lock:
            for tid, ckpt in last_ckpt.items():
                if tid in self._pending or tid in self._paused:
                    continue  # Implementation note.
                if getattr(ckpt, "has_final_answer", False):
                    continue  # Implementation note.
                state = last_state_ts.get(tid)
                if state is not None and state[1] == "resumed":
                    # Task was paused then later resumed — the resume means
                    # the pause was resolved. It either ran to completion
                    # (which has_final_answer would have caught above) or
                    # is still in the active list. Either way, it should
                    # NOT be re-added as paused/pending, otherwise every
                    # "pause → resume → complete" sequence leaves a stale
                    # yellow light forever.
                    continue
                if state is not None and state[1] == "paused":
                    self._paused[tid] = PauseRequest(
                        task_id=tid,
                        reason="external",
                        requested_by="journal_recovery",
                        requested_at=state[0],
                        note="从 journal 反演的历史暂停状态",
                        thread_id=str(getattr(ckpt, "conversation_id", "") or ""),
                        agent_id=str(getattr(ckpt, "agent_id", "") or ""),
                    )
                    recovered += 1
                    continue

                # No paused/resumed events: task was mid-execution when the
                # checkpoint was saved. We recover it as pending so the user
                # sees a Continue button, but we stamp it with the checkpoint
                # time (not now()) so the TTL GC can sweep it if abandoned.
                ckpt_ts = float(
                    getattr(ckpt, "timestamp", 0) or getattr(ckpt, "created_at", 0) or time.time()
                )
                self._pending[tid] = PauseRequest(
                    task_id=tid,
                    reason="external",
                    requested_by="journal_recovery",
                    requested_at=ckpt_ts,
                    note=(
                        f"从 journal 反演 · 最后 checkpoint 在 iter "
                        f"{getattr(ckpt, 'iteration_completed', '?')}"
                    ),
                    thread_id=str(getattr(ckpt, "conversation_id", "") or ""),
                    agent_id=str(getattr(ckpt, "agent_id", "") or ""),
                )
                recovered += 1

            # After recovery, sweep any records older than TTL or with
            # no thread_id — these are abandoned and will never resolve.
            gc_removed = self._gc_stale_pauses_locked()
            if recovered > 0 or gc_removed > 0:
                self._persist_locked()
            if recovered > 0:
                _log.info(
                    "pause_control: recovered %d task(s) from journal on startup (gc'd %d)",
                    recovered,
                    gc_removed,
                )
        return recovered

    # ─── Active running tasks (B5) ────────────────────

    def register_active(
        self,
        task_id: str,
        *,
        thread_id: str = "",
        agent_id: str = "",
        max_iterations: int = 0,
        max_tokens: int = BUDGET_DEFAULT_MAX_TOKENS,
        max_usd: float = BUDGET_DEFAULT_MAX_USD,
    ) -> None:
        with self._lock:
            self._active[task_id] = ActiveTask(
                task_id=task_id,
                thread_id=thread_id,
                agent_id=agent_id,
                max_iterations=max_iterations,
                max_tokens=max_tokens,
                max_usd=max_usd,
            )

    def update_active_iteration(self, task_id: str, iteration: int) -> None:
        with self._lock:
            task = self._active.get(task_id)
            if task is not None:
                task.current_iteration = iteration

    def update_active_iteration_limit(self, task_id: str, max_iterations: int) -> None:
        with self._lock:
            task = self._active.get(task_id)
            if task is not None:
                task.max_iterations = max(0, int(max_iterations))

    def update_active_usage(
        self,
        task_id: str,
        *,
        tokens_delta: int = 0,
        cost_delta: float = 0.0,
    ) -> ActiveTask | None:
        with self._lock:
            task = self._active.get(task_id)
            if task is None:
                return None
            task.tokens_spent += max(0, int(tokens_delta))
            task.cost_usd += max(0.0, float(cost_delta))
            return task

    def unregister_active(self, task_id: str) -> None:
        with self._lock:
            self._active.pop(task_id, None)

    def list_active(self) -> list[ActiveTask]:
        with self._lock:
            return list(self._active.values())

    def is_pause_requested(self, task_id: str | None) -> bool:
        if not task_id:
            return False
        with self._lock:
            return task_id in self._pending or task_id in self._paused

    def is_paused(self, task_id: str | None) -> bool:
        if not task_id:
            return False
        with self._lock:
            return task_id in self._paused

    def get_request(self, task_id: str) -> PauseRequest | None:
        with self._lock:
            return self._pending.get(task_id) or self._paused.get(task_id)

    def list_pending(self) -> list[PauseRequest]:
        with self._lock:
            self._gc_stale_pauses_locked()
            return list(self._pending.values())

    def list_paused(self) -> list[PauseRequest]:
        with self._lock:
            self._gc_stale_pauses_locked()
            return list(self._paused.values())

    # ─── ownership helpers (router-side enforcement) ───────────────
    #
    # Endpoints in agents_router (/api/tasks/*) historically had no way
    # to ask "who owns this task?" — so any authenticated user could
    # pause/resume/delete anyone else's task. These helpers expose the
    # task→thread→owner lookup so routers can enforce per-user scoping.
    #
    # The actual owner lookup goes through ThreadStateStore: each task
    # carries a ``thread_id``, and threads have ``metadata["owner_id"]``
    # set at creation time (or None for legacy/dev-mode threads).

    def get_task_thread_id(self, task_id: str) -> str | None:
        """Return the ``thread_id`` for a task, looking through both
        active and paused/pending state. None if task is unknown."""
        with self._lock:
            active = self._active.get(task_id)
            if active is not None and active.thread_id:
                return active.thread_id
            req = self._pending.get(task_id) or self._paused.get(task_id)
            if req is not None and req.thread_id:
                return req.thread_id
        return None

    def list_thread_ids_for_owner(
        self,
        thread_store: object,
        owner_id: str | None,
    ) -> set[str]:
        """Return the set of thread_ids owned by ``owner_id``.

        ``thread_store`` should be a ThreadStateStore with a ``search``
        method. Threads with ``metadata["owner_id"] is None`` are
        legacy/unowned and visible to everyone (matches the
        parallel_agents/team_tasks pattern).
        """
        if owner_id is None or thread_store is None:
            return set()
        if not hasattr(thread_store, "search"):
            return set()
        try:
            owned = thread_store.search(
                metadata={"owner_id": owner_id},
                limit=10000,
            )
        except (TypeError, ValueError, AttributeError):
            return set()
        return {t.get("thread_id", "") for t in owned if t.get("thread_id")}


def get_pause_controller() -> PauseController:
    provider = get_provider()
    ctrl = provider.get("pause_controller")
    if ctrl is None:
        ctrl = PauseController()
        provider.register_instance("pause_controller", ctrl)
    return ctrl
