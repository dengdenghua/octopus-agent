"""Audit T-09: ParallelTaskRunner cancel actually stops the in-flight loop."""

from __future__ import annotations

import threading
from types import SimpleNamespace

from runtime.execution.misc.parallel_runner import (
    ParallelTask,
    ParallelTaskRunner,
    TaskStatus,
)


def test_cancel_stops_inflight_task_and_keeps_cancelled(monkeypatch) -> None:
    """cancel() must reach the running react loop via the ambient token and
    the terminal state must stay CANCELLED (not COMPLETED)."""
    import runtime.core.cerebrum.react_loop as react_loop_mod

    registered = threading.Event()
    cancel_observed = threading.Event()

    def _blocking_run_react_loop(**kwargs):
        from runtime.safety.approval.cancellation import current_cancellation_token

        current_cancellation_token().on_cancelled(lambda reason: cancel_observed.set())
        registered.set()
        cancel_observed.wait(5)  # block until cancel() fires the token
        return {"terminated_reason": "cancelled"}

    monkeypatch.setattr(react_loop_mod, "run_react_loop", _blocking_run_react_loop)

    runner = ParallelTaskRunner(max_workers=1, stack=SimpleNamespace())
    task = ParallelTask(prompt="do the thing")
    runner.submit(task)

    assert registered.wait(3), "worker never installed the cancellation token"
    assert runner.cancel(task.id) is True
    assert cancel_observed.wait(3), "cancel never reached the running loop"
    # Wait for the worker to settle and keep the CANCELLED terminal state.
    deadline = threading.Event()
    assert deadline.wait(5) or True  # no-op; poll below
    import time

    end = time.monotonic() + 5
    while time.monotonic() < end and task.status is TaskStatus.RUNNING:
        time.sleep(0.02)
    assert task.status is TaskStatus.CANCELLED
    assert "cancelled" in (task.result or "").lower()


def test_cancel_while_running_keeps_cancelled_terminal(monkeypatch) -> None:
    """Cancelling while the task is RUNNING keeps the CANCELLED terminal
    state — the loop's normal completion path must not overwrite it."""
    import time

    import runtime.core.cerebrum.react_loop as react_loop_mod

    hold = threading.Event()

    def _fake(**kwargs):
        hold.wait(5)
        return "done"

    monkeypatch.setattr(react_loop_mod, "run_react_loop", _fake)

    runner = ParallelTaskRunner(max_workers=1, stack=SimpleNamespace())
    task = ParallelTask(prompt="x")
    runner.submit(task)
    end = time.monotonic() + 5
    while time.monotonic() < end and task.status is not TaskStatus.RUNNING:
        time.sleep(0.02)
    assert task.status is TaskStatus.RUNNING
    assert runner.cancel(task.id) is True
    hold.set()  # let the worker finish; the terminal state must stay CANCELLED
    end = time.monotonic() + 5
    while time.monotonic() < end and task.status is TaskStatus.RUNNING:
        time.sleep(0.02)
    assert task.status is TaskStatus.CANCELLED
