
from __future__ import annotations

import contextvars
import logging
import random
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from runtime.adapters.instrumentation import trace_stage

from .cron import CronExpression

_logger = logging.getLogger(__name__)

_MAIN_LOOP_MAX_SLEEP_S = 0.5


@dataclass
class TaskStats:

    name: str
    interval_s: float
    last_run_ts: float | None = None
    last_duration_s: float | None = None
    next_run_ts: float | None = None
    success_count: int = 0
    error_count: int = 0
    last_error: str | None = None
    in_flight: int = 0              # Implementation note.


@dataclass
class PeriodicTask:

    name: str
    interval_s: float
    callback: Callable[[], None]
    jitter_s: float = 0.0
    run_on_start: bool = False
    cron_expr: CronExpression | None = None
    _next_ts: float = 0.0
    stats: TaskStats = field(init=False)

    def __post_init__(self) -> None:
        if self.cron_expr is None and self.interval_s <= 0:
            raise ValueError(f"interval_s must be > 0 (got {self.interval_s})")
        if self.jitter_s < 0:
            raise ValueError(f"jitter_s must be >= 0 (got {self.jitter_s})")
        self.stats = TaskStats(name=self.name, interval_s=self.interval_s)

    @property
    def is_cron(self) -> bool:
        return self.cron_expr is not None


class BackgroundRunner:

    def __init__(
        self,
        *,
        name: str = "octopus-scheduler",
        max_workers: int = 1,
    ) -> None:
        if max_workers < 1:
            raise ValueError(f"max_workers must be >= 1 (got {max_workers})")
        self.name = name
        self.max_workers = max_workers
        self._tasks: list[PeriodicTask] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state: str = "idle"  # idle | running | stopped
        self._pool: ThreadPoolExecutor | None = None


    def start(self) -> None:
        with self._lock:
            if self._state == "running":
                return
            if self._state == "stopped":
                raise RuntimeError(
                    "BackgroundRunner cannot restart after stop · create a new instance"
                )
            self._state = "running"
            self._stop_event.clear()
            if self.max_workers > 1:
                self._pool = ThreadPoolExecutor(
                    max_workers=self.max_workers,
                    thread_name_prefix=f"{self.name}-worker",
                )
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name=self.name,
            )
            self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        with self._lock:
            if self._state != "running":
                return
            self._state = "stopped"
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self._pool is not None:
            try:
                self._pool.shutdown(wait=True, cancel_futures=False)
            except Exception:  # noqa: BLE001
                _logger.warning("BackgroundRunner pool shutdown timed out · forcing")
                self._pool.shutdown(wait=False, cancel_futures=True)
            self._pool = None

    def __enter__(self) -> BackgroundRunner:
        self.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    @property
    def state(self) -> str:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state == "running" and self._thread is not None and self._thread.is_alive()


    def add_periodic(
        self,
        name: str,
        interval_s: float,
        callback: Callable[[], None],
        *,
        jitter_s: float = 0.0,
        run_on_start: bool = False,
    ) -> PeriodicTask:
        with self._lock:
            if self._state == "stopped":
                raise RuntimeError("cannot add to stopped runner")
            if any(t.name == name for t in self._tasks):
                raise ValueError(f"duplicate task name: {name!r}")
            task = PeriodicTask(
                name=name,
                interval_s=interval_s,
                callback=callback,
                jitter_s=jitter_s,
                run_on_start=run_on_start,
            )
            now = time.monotonic()
            task._next_ts = now if run_on_start else now + interval_s
            task.stats.next_run_ts = task._next_ts
            self._tasks.append(task)
            return task

    def add_cron(
        self,
        name: str,
        expr: str,
        callback: Callable[[], None],
        *,
        run_on_start: bool = False,
    ) -> PeriodicTask:
        cron = CronExpression.parse(expr)
        with self._lock:
            if self._state == "stopped":
                raise RuntimeError("cannot add to stopped runner")
            if any(t.name == name for t in self._tasks):
                raise ValueError(f"duplicate task name: {name!r}")
            task = PeriodicTask(
                name=name,
                interval_s=0.0,    # Implementation note.
                callback=callback,
                run_on_start=run_on_start,
                cron_expr=cron,
            )
            if run_on_start:
                task._next_ts = time.monotonic()
            else:
                task._next_ts = _cron_next_mono(cron, time.monotonic())
            task.stats.next_run_ts = task._next_ts
            self._tasks.append(task)
            return task

    def remove(self, name: str) -> bool:
        with self._lock:
            before = len(self._tasks)
            self._tasks = [t for t in self._tasks if t.name != name]
            return len(self._tasks) < before


    def stats(self) -> dict[str, TaskStats]:
        with self._lock:
            return {t.name: t.stats for t in self._tasks}

    def task_names(self) -> list[str]:
        with self._lock:
            return [t.name for t in self._tasks]


    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            now = time.monotonic()
            with self._lock:
                due = [t for t in self._tasks if t._next_ts <= now]

            for task in due:
                if self._stop_event.is_set():
                    break
                self._execute(task)

            with self._lock:
                if self._tasks:
                    next_ts = min(t._next_ts for t in self._tasks)
                else:
                    next_ts = now + _MAIN_LOOP_MAX_SLEEP_S
            wait_s = max(0.0, min(_MAIN_LOOP_MAX_SLEEP_S, next_ts - time.monotonic()))
            self._stop_event.wait(timeout=wait_s)

    def _execute(self, task: PeriodicTask) -> None:
        if self._pool is None:
            self._invoke(task)
            self._reschedule(task)  # Implementation note.
        else:
            self._reschedule(task)
            with self._lock:
                task.stats.in_flight += 1
            future: Future = self._pool.submit(self._invoke, task)
            future.add_done_callback(lambda _f, t=task: self._on_future_done(t))

    def _invoke(self, task: PeriodicTask) -> None:
        with trace_stage("scheduler.task") as span:
            span.set_attribute("octopus.scheduler.task", task.name)
            started = time.monotonic()
            task.stats.last_run_ts = started
            try:
                # Run in a fresh context copy so ContextVars a task sets
                # (e.g. _current_session / _current_agent_id via
                # bind_thread_session) don't leak into the next task that
                # reuses this pool/loop thread — that cross-task bleed would
                # break per-task session isolation.
                contextvars.copy_context().run(task.callback)
                task.stats.success_count += 1
                task.stats.last_error = None
            except Exception as e:  # noqa: BLE001
                task.stats.error_count += 1
                task.stats.last_error = f"{type(e).__name__}: {e}"
                span.set_attribute("octopus.scheduler.error", task.stats.last_error)
                _logger.exception("scheduler task %s failed: %s", task.name, e)

            duration = time.monotonic() - started
            task.stats.last_duration_s = duration
            span.set_attribute("octopus.scheduler.duration_s", duration)

    def _reschedule(self, task: PeriodicTask) -> None:
        if task.cron_expr is not None:
            task._next_ts = _cron_next_mono(task.cron_expr, time.monotonic())
        else:
            jitter = 0.0
            if task.jitter_s > 0:
                jitter = random.uniform(-task.jitter_s, task.jitter_s)
            task._next_ts = time.monotonic() + task.interval_s + jitter
        task.stats.next_run_ts = task._next_ts

    def _on_future_done(self, task: PeriodicTask) -> None:
        with self._lock:
            if task.stats.in_flight > 0:
                task.stats.in_flight -= 1


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _cron_next_mono(cron: CronExpression, mono_now: float) -> float:
    wall_now = datetime.now().astimezone()
    wall_next = cron.next_after(wall_now)
    delta = (wall_next - wall_now).total_seconds()
    if delta < 0:
        delta = 0.0
    return mono_now + delta
