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
import threading
from collections.abc import Callable
from typing import Any

from runtime.memory.cowork.async_work import AsyncTask, AsyncWorkStore
from runtime.memory.cowork.context_view import resolve_view, slice_messages
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.nominate import CompetenceStore, tokenize

_LOG = logging.getLogger("octopus.cowork.async_runner")

# execute(task, context) -> result text. ``context`` carries the grant-sliced
# history, the shared blackboard, and the roster.
Executor = Callable[[AsyncTask, dict[str, Any]], str]
HistoryProvider = Callable[[str], list[Any]]


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
    ) -> None:
        self._store = store
        self._groups = group_store
        self._execute = execute
        self._competence = competence
        self._history = history_provider or (lambda _tid: [])
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _build_context(self, task: AsyncTask) -> dict[str, Any]:
        state = self._groups.state(task.thread_id)
        msgs = self._history(task.thread_id)
        view = resolve_view(state, task.assignee, max(0, len(msgs) - 1))
        history = slice_messages(view, msgs) if view else []
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

    def run_one(self, task: AsyncTask) -> bool:
        """Claim → execute → complete (or fail) one task. False if not claimable."""
        if not self._store.claim(task.task_id):
            return False
        try:
            result = self._execute(task, self._build_context(task))
        except Exception as exc:  # noqa: BLE001 — a failed task must not kill the loop
            self._store.fail(task.task_id, f"{type(exc).__name__}: {exc}")
            self._record_competence(task.assignee, task.prompt, success=False)
            _LOG.warning("async task %s failed: %s", task.task_id, exc)
            return True
        self._store.complete(task.task_id, result)
        self._record_competence(task.assignee, task.prompt, success=True)
        return True

    def drain(self, thread_id: str) -> int:
        """Run every currently-pending task in a thread. Returns how many ran."""
        ran = 0
        for task in self._store.pending(thread_id):
            if self.run_one(task):
                ran += 1
        return ran

    def drain_all(self) -> int:
        return sum(self.drain(tid) for tid in self._store.threads_with_pending())

    # ── background daemon ────────────────────────────────────────────────────
    def start(self, *, poll_seconds: float = 5.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, args=(poll_seconds,), name="cowork-async-runner", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def _loop(self, poll_seconds: float) -> None:
        while not self._stop.wait(timeout=poll_seconds):
            try:
                self.drain_all()
            except Exception as exc:  # noqa: BLE001 — the daemon must never die
                _LOG.debug("async runner tick error: %s", exc)
