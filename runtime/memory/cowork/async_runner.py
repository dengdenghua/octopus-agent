"""The loop that makes async coworkers actually work.

Polls the thread's pending tasks, builds each one's context (history sliced by
the assignee's grant + the shared blackboard), runs the agent, posts the result
to the board, and records the outcome into competence memory. Can run once
(``drain``) or as a background daemon.

How an agent is *run* is injected (``execute``) — the production wiring passes a
bridge to the ephemeral sub-agent runner at bootstrap (same pattern as
``set_ephemeral_role_runner``); tests pass a stub. So this whole loop is testable
without an LLM and never touches the realtime streaming path.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any

from runtime.memory.cowork.async_work import AsyncTask, AsyncWorkStore
from runtime.memory.cowork.context_view import materialize_messages, resolve_view
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.nominate import CompetenceStore, tokenize

_LOG = logging.getLogger("octopus.cowork.async_runner")

# execute(task, context) -> result text. ``context`` carries the grant-sliced
# history, the shared blackboard, and the roster.
Executor = Callable[[AsyncTask, dict[str, Any]], str]
HistoryProvider = Callable[[str], list[Any]]
CompletionObserver = Callable[[AsyncTask, bool, str], None]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class AsyncWorkRunner:
    """Drives pending async tasks to completion via an injected ``execute``."""

    def __init__(
        self,
        store: AsyncWorkStore,
        group_store: GroupStore,
        execute: Executor,
        *,
        competence: CompetenceStore | None = None,
        history_provider: HistoryProvider | None = None,
        completion_observer: CompletionObserver | None = None,
        recover_stale_seconds: float = 900.0,
        max_attempts: int = 3,
        max_concurrency: int = 4,
        max_tasks_per_tick: int = 64,
    ) -> None:
        self._store = store
        self._groups = group_store
        self._execute = execute
        self._competence = competence
        self._history = history_provider or (lambda _tid: [])
        self._completion_observer = completion_observer
        self._recover_stale_seconds = max(0.0, float(recover_stale_seconds))
        self._max_attempts = max(1, int(max_attempts))
        self._max_concurrency = max(1, int(max_concurrency))
        self._max_tasks_per_tick = max(1, int(max_tasks_per_tick))
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._total_ticks = 0
        self._total_failures = 0
        self._consecutive_failures = 0
        self._last_tick_at: str | None = None
        self._last_success_at: str | None = None
        self._last_failure_at: str | None = None
        self._last_error: str | None = None
        self._last_recovered: dict[str, int] = {"requeued": 0, "failed": 0}
        self._last_ran_count = 0
        self._last_concurrency = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict[str, Any]:
        """Operational health snapshot for UI/API diagnostics."""
        with self._state_lock:
            return {
                "running": self.running,
                "recover_stale_seconds": self._recover_stale_seconds,
                "max_attempts": self._max_attempts,
                "max_concurrency": self._max_concurrency,
                "max_tasks_per_tick": self._max_tasks_per_tick,
                "total_ticks": self._total_ticks,
                "total_failures": self._total_failures,
                "consecutive_failures": self._consecutive_failures,
                "last_tick_at": self._last_tick_at,
                "last_success_at": self._last_success_at,
                "last_failure_at": self._last_failure_at,
                "last_error": self._last_error,
                "last_recovered": dict(self._last_recovered),
                "last_ran_count": self._last_ran_count,
                "last_concurrency": self._last_concurrency,
            }

    def _record_tick_result(
        self,
        *,
        success: bool,
        recovered: dict[str, int] | None = None,
        ran_count: int = 0,
        concurrency: int = 0,
        error: str | None = None,
    ) -> None:
        now = _now_iso()
        with self._state_lock:
            self._total_ticks += 1
            self._last_tick_at = now
            self._last_recovered = dict(recovered or {"requeued": 0, "failed": 0})
            self._last_ran_count = int(ran_count)
            self._last_concurrency = max(0, int(concurrency))
            if success:
                self._consecutive_failures = 0
                self._last_error = None
                self._last_success_at = now
                return
            self._total_failures += 1
            self._consecutive_failures += 1
            self._last_error = error or "tick failed"
            self._last_failure_at = now

    def _build_context(self, task: AsyncTask) -> dict[str, Any]:
        state = self._groups.state(task.thread_id)
        msgs = self._history(task.thread_id)
        view = resolve_view(state, task.assignee, max(0, len(msgs) - 1))
        history = materialize_messages(view, msgs) if view else []
        return {
            "history": history,
            "blackboard": self._groups.blackboard_snapshot(task.thread_id),
            "roster": [m.id for m in state.roster],
            "grant_scope": view.scope if view else None,
        }

    def _record_competence(self, assignee: str, prompt: str, success: bool) -> None:
        if not self._competence:
            return
        for tag in list(tokenize(prompt))[:5]:
            self._competence.record(assignee, tag, success)

    def _notify_completion(self, task: AsyncTask, *, success: bool, result: str) -> None:
        if self._completion_observer is None:
            return
        try:
            self._completion_observer(task, success, result)
        except Exception as exc:  # noqa: BLE001 - durable task outcome remains authoritative
            _LOG.warning("async task %s completion observer failed: %s", task.task_id, exc)

    def run_one(self, task: AsyncTask) -> bool:
        """Claim → execute → complete (or fail) one task. False if not claimable."""
        if not self._store.claim(task.task_id):
            return False
        try:
            result = self._execute(task, self._build_context(task))
        except Exception as exc:  # noqa: BLE001 — a failed task must not kill the loop
            error = f"{type(exc).__name__}: {exc}"
            failed = self._store.fail(task.task_id, error)
            current = self._store.get(task.task_id)
            if not failed and current is not None and current.status == "cancelled":
                _LOG.info("discarded late failure from cancelled async task %s", task.task_id)
                return True
            self._record_competence(task.assignee, task.prompt, success=False)
            self._notify_completion(task, success=False, result=error)
            _LOG.warning("async task %s failed: %s", task.task_id, exc)
            return True
        completed = self._store.complete(task.task_id, result)
        current = self._store.get(task.task_id)
        if not completed and current is not None and current.status == "cancelled":
            _LOG.info("discarded late result from cancelled async task %s", task.task_id)
            return True
        self._record_competence(task.assignee, task.prompt, success=True)
        self._notify_completion(task, success=True, result=result)
        return True

    def drain(self, thread_id: str) -> int:
        """Run every currently-pending task in a thread. Returns how many ran."""
        ran = 0
        for task in self._store.pending(thread_id):
            if self.run_one(task):
                ran += 1
        return ran

    def _fair_pending(self, *, limit: int | None = None) -> list[AsyncTask]:
        """Interleave threads so one large room cannot starve smaller rooms."""

        queues = {
            thread_id: list(self._store.pending(thread_id))
            for thread_id in self._store.threads_with_pending()
        }
        selected: list[AsyncTask] = []
        while queues and (limit is None or len(selected) < limit):
            for thread_id in list(queues):
                queue = queues[thread_id]
                if queue:
                    selected.append(queue.pop(0))
                if not queue:
                    queues.pop(thread_id, None)
                if limit is not None and len(selected) >= limit:
                    break
        return selected

    def _adaptive_worker_count(self, task_count: int) -> int:
        """Scale gently with backlog instead of spawning one worker per task."""

        if task_count <= 0:
            return 0
        return min(self._max_concurrency, max(1, math.ceil(math.sqrt(task_count))))

    def _run_fair_pending(self, *, limit: int | None = None) -> tuple[int, int]:
        tasks = self._fair_pending(limit=limit)
        concurrency = self._adaptive_worker_count(len(tasks))
        if concurrency <= 1:
            return sum(1 for task in tasks if self.run_one(task)), concurrency
        with ThreadPoolExecutor(
            max_workers=concurrency,
            thread_name_prefix="cowork-task",
        ) as pool:
            ran = sum(1 for completed in pool.map(self.run_one, tasks) if completed)
        return ran, concurrency

    def recover_stale(self) -> dict[str, int]:
        """Requeue abandoned working tasks before polling pending work."""
        staged = self._store.staged_older_than(
            max_age_seconds=self._recover_stale_seconds,
        )
        recovered = self._store.recover_stale_working(
            max_age_seconds=self._recover_stale_seconds,
            max_attempts=self._max_attempts,
        )
        for task in staged:
            current = self._store.get(task.task_id)
            if current is None or current.status != "failed":
                continue
            self._notify_completion(
                current,
                success=False,
                result=current.result or "task staging did not complete",
            )
        if recovered.get("requeued") or recovered.get("failed"):
            _LOG.warning("async runner recovered stale tasks: %s", recovered)
        return recovered

    def drain_all(self) -> int:
        self.recover_stale()
        ran, _concurrency = self._run_fair_pending()
        return ran

    def tick_once(self) -> int:
        """Run one recover+drain tick and record runner health."""
        try:
            recovered = self.recover_stale()
            ran, concurrency = self._run_fair_pending(limit=self._max_tasks_per_tick)
        except Exception as exc:  # noqa: BLE001 — tick health must capture store/context failures
            self._record_tick_result(
                success=False,
                error=f"{type(exc).__name__}: {exc}",
            )
            _LOG.warning("async runner tick error: %s", exc, exc_info=True)
            return 0
        self._record_tick_result(
            success=True,
            recovered=recovered,
            ran_count=ran,
            concurrency=concurrency,
        )
        return ran

    # ── background daemon ────────────────────────────────────────────────────
    def start(self, *, poll_seconds: float = 5.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._wake.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(poll_seconds,), name="cowork-async-runner", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def wake(self) -> None:
        """Prompt the background loop after new work is queued."""

        self._wake.set()

    def _loop(self, poll_seconds: float) -> None:
        while not self._stop.is_set():
            self._wake.wait(timeout=poll_seconds)
            self._wake.clear()
            if self._stop.is_set():
                break
            self.tick_once()
