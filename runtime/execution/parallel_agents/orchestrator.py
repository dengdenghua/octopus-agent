
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import AsyncIterator, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from runtime.core.cerebrum.completion_receipt import build_completion_receipt
from runtime.core.cerebrum.run_state import converge_run_state
from runtime.execution.misc.file_write_leases import (
    file_write_lease_snapshot,
)
from runtime.execution.misc.multiagent_contracts import validate_work_plan

from .helpers import (
    authorize_dependency_file_handoffs as _authorize_dependency_file_handoffs,
)
from .helpers import (
    build_plan as _build_plan,
)
from .helpers import (
    contract_for as _contract_for,
)
from .helpers import (
    default_runner as _default_runner,
)
from .helpers import (
    deps_terminal_success as _deps_terminal_success,
)
from .helpers import (
    initial_runtime_session_metadata as _initial_runtime_session_metadata,
)
from .helpers import (
    preview as _preview,
)
from .models import (
    BatchPlan,
    BatchResult,
    BatchStreamEvent,
    DispatchTaskInput,
    OrchestratorStatus,
    SplitResult,
    SplitTask,
    TaskResult,
    WorkContract,
)
from .ownership import OwnershipMixin

_log = logging.getLogger(__name__)


TaskRunner = Callable[..., str]


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _now() -> datetime:
    return datetime.now(UTC)


def _context_risk_level(context: dict[str, Any]) -> str:
    for key in (
        "task_risk_level",
        "risk_level",
        "approval_risk_level",
        "quality_risk_level",
    ):
        value = context.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "low"


def _route_decision(agent_id: str, context: dict[str, Any]) -> dict[str, Any]:
    try:
        from runtime.safety.evolution.subagent_routing import (
            decide_subagent_route,
        )
        decision = decide_subagent_route(
            role=agent_id,
            risk_level=_context_risk_level(context),
            review_queue_path=context.get("review_queue_path"),
            subagent_policy_path=context.get("subagent_policy_path"),
            enabled=bool(context.get("enable_subagent_fitness_routing", True)),
        )
        return decision.to_dict()
    except Exception as exc:  # noqa: BLE001
        _log.debug(
            "parallel subagent fitness routing skipped · agent_id=%s error=%s",
            agent_id,
            exc,
        )
        return {
            "schema": "octopus.subagent_route_decision.v1",
            "role": agent_id,
            "action": "allow",
            "reason": "subagent fitness routing unavailable",
            "risk_level": _context_risk_level(context),
            "verdict": "unknown",
            "score": None,
            "confidence": 0.0,
            "evidence_item_ids": [],
        }




@dataclass
class _TaskEntry:
    task_id: str
    batch_id: str
    description: str
    subagent_name: str
    depends_on: list[str]
    priority: int
    write_paths: list[str] = field(default_factory=list)

    status: str = "pending"
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None
    work_contract: WorkContract | None = None
    route_decision: dict[str, Any] | None = None

    def duration(self) -> float | None:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None

    def to_wire(self) -> TaskResult:
        return TaskResult(
            task_id=self.task_id,
            batch_id=self.batch_id,
            description=self.description,
            status=self.status,
            result=self.result,
            error=self.error,
            started_at=_iso(self.started_at),
            completed_at=_iso(self.completed_at),
            duration_seconds=self.duration(),
            subagent_name=self.subagent_name,
            work_contract=self.work_contract,
        )


@dataclass
class _BatchEntry:
    batch_id: str
    tasks: dict[str, _TaskEntry]
    created_at: datetime
    completed_at: datetime | None = None
    aggregation_strategy: str | None = None
    aggregated_content: str | None = None
    conflicts: list[str] = field(default_factory=list)
    plan: BatchPlan | None = None
    runtime_session_metadata: dict[str, Any] = field(default_factory=dict)
    subscribers: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = \
        field(default_factory=list)
    event_log: list[Any] = field(default_factory=list)
    event_sequence: int = 0
    # Owner enforcement: set by dispatch() from the calling actor's id.
    # ``None`` means "no owner recorded" — for batches created before
    # ownership tracking was added, or in single-user dev mode where
    # require_auth is off. Endpoints treat ``None`` as "visible to
    # everyone" so legacy state isn't suddenly hidden.
    owner_id: str | None = None

    # ── counters ──
    def derived_status(self) -> str:
        return converge_run_state([t.status for t in self.tasks.values()]).state

    def counts(self) -> tuple[int, int, int, int]:
        """(total, completed, failed, cancelled)."""
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks.values() if t.status == "completed")
        failed = sum(1 for t in self.tasks.values() if t.status == "failed")
        cancelled = sum(
            1 for t in self.tasks.values() if t.status == "cancelled"
        )
        return total, completed, failed, cancelled

    def to_wire(self) -> BatchResult:
        total, completed, failed, cancelled = self.counts()
        validation_issues = (
            list(self.plan.validation_issues)
            if self.plan is not None else []
        )
        validation_warnings = (
            list(self.plan.validation_warnings)
            if self.plan is not None else []
        )
        artifact_count = sum(
            len(event.artifact_paths)
            for event in self.event_log
            if getattr(event, "artifact_paths", None)
        )
        return BatchResult(
            batch_id=self.batch_id,
            status=self.derived_status(),
            total_tasks=total,
            completed_tasks=completed,
            failed_tasks=failed,
            cancelled_tasks=cancelled,
            created_at=_iso(self.created_at),
            completed_at=_iso(self.completed_at),
            results=[t.to_wire() for t in self.tasks.values()],
            aggregated_content=self.aggregated_content,
            aggregation_strategy=self.aggregation_strategy,
            conflicts=list(self.conflicts),
            plan=self.plan,
            event_log=list(self.event_log),
            completion_receipt=build_completion_receipt(
                [t.status for t in self.tasks.values()],
                contract_issues=validation_issues,
                contract_warnings=validation_warnings,
                artifact_count=artifact_count,
                output_present=bool(self.aggregated_content),
            ).to_dict(),
            file_write_observability=file_write_lease_snapshot(
                self.runtime_session_metadata,
            ),
            batch_metrics=_batch_metrics(self),
        )


def _batch_metrics(batch: _BatchEntry) -> dict[str, object]:
    tasks = list(batch.tasks.values())
    starts = [
        entry.started_at.timestamp()
        for entry in tasks
        if entry.started_at is not None
    ]
    finishes = [
        entry.completed_at.timestamp()
        for entry in tasks
        if entry.completed_at is not None
    ]
    durations = [
        float(duration)
        for entry in tasks
        if (duration := entry.duration()) is not None
    ]
    execution_window_seconds = (
        max(finishes) - min(starts)
        if starts and finishes else 0.0
    )
    observed_serial_work_seconds = sum(durations)
    critical_path_speedup = (
        observed_serial_work_seconds / execution_window_seconds
        if execution_window_seconds > 0.0 else 0.0
    )
    event_sequences = [
        int(event.sequence)
        for event in batch.event_log
        if event.sequence is not None
    ]
    status_by_task = {
        entry.task_id: entry.status
        for entry in tasks
    }
    return {
        "schema": "octopus.parallel_agent_batch_metrics.v1",
        "task_count": len(tasks),
        "planned_phase_count": (
            len(batch.plan.phases)
            if batch.plan is not None else 0
        ),
        "parallel_phase_count": (
            sum(1 for phase in batch.plan.phases if phase.parallel)
            if batch.plan is not None else 0
        ),
        "started_count": len(starts),
        "finished_count": len(finishes),
        "completed_count": sum(1 for entry in tasks if entry.status == "completed"),
        "failed_count": sum(1 for entry in tasks if entry.status == "failed"),
        "cancelled_count": sum(1 for entry in tasks if entry.status == "cancelled"),
        "execution_window_seconds": round(max(execution_window_seconds, 0.0), 4),
        "observed_serial_work_seconds": round(observed_serial_work_seconds, 4),
        "critical_path_speedup": round(critical_path_speedup, 3),
        "max_active_estimate": _max_active_estimate(tasks),
        "failure_isolation": _failure_isolation_ok(tasks),
        "event_sequences_contiguous": event_sequences == list(
            range(1, len(event_sequences) + 1),
        ),
        "conflict_count": len(batch.conflicts),
        "conflicts": list(batch.conflicts),
        "status_by_task": status_by_task,
    }


def _max_active_estimate(tasks: list[_TaskEntry]) -> int:
    marks: list[tuple[float, int]] = []
    for entry in tasks:
        if entry.started_at is None:
            continue
        started = entry.started_at.timestamp()
        completed = (
            entry.completed_at.timestamp()
            if entry.completed_at is not None else started
        )
        marks.append((started, 1))
        marks.append((max(completed, started), -1))
    active = 0
    max_active = 0
    for _, delta in sorted(marks, key=lambda item: (item[0], -item[1])):
        active += delta
        max_active = max(max_active, active)
    return max_active


def _failure_isolation_ok(tasks: list[_TaskEntry]) -> bool:
    failed = [entry for entry in tasks if entry.status == "failed"]
    if not failed:
        return True
    succeeded = [
        entry
        for entry in tasks
        if entry.status == "completed"
        and not any(dep in {item.task_id for item in failed} for dep in entry.depends_on)
    ]
    return bool(succeeded)


# ─── orchestrator ────────────────────────────────────────────


class ParallelAgentOrchestrator(OwnershipMixin):
    """Multi-agent work orchestrator with dependency + concurrency control.

    Manages batches of parallel tasks, each with optional dependencies.
    Phases are derived from the dependency graph via topological sort.
    """

    def __init__(
        self,
        *,
        max_concurrency: int = 4,
        task_runner: TaskRunner | None = None,
        splitter: Callable[..., SplitResult] | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self._max_concurrency = max_concurrency
        self._pool = ThreadPoolExecutor(
            max_workers=max_concurrency,
            thread_name_prefix="parallel-agent",
        )
        self._lock = threading.RLock()
        self._batches: dict[str, _BatchEntry] = {}
        self._task_index: dict[str, str] = {}    # task_id → batch_id
        self._runner: TaskRunner = task_runner or _default_runner
        self._splitter = splitter
        self._closed = False

    # ═══ public API ═══════════════════════════════════════════

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    def dispatch(
        self,
        tasks: list[DispatchTaskInput] | list[dict[str, Any]],
        *,
        max_concurrency: int | None = None,   # Implementation note.
        aggregation_strategy: str | None = None,
        execution_mode: str | None = None,
        thread_id: str | None = None,
        model_name: str | None = None,
        context: dict[str, Any] | None = None,
        owner_id: str | None = None,
    ) -> BatchResult:
        """Create + start a batch.

        ``owner_id`` is stamped on the batch and used by ``get_batch``,
        ``cancel_task``, ``cancel_all`` and ``subscribe`` to enforce
        per-user scoping at the endpoint layer. ``None`` means
        unscoped (legacy / dev mode) and is visible to everyone.
        """
        self._guard_open()

        raw: list[DispatchTaskInput] = [
            t if isinstance(t, DispatchTaskInput) else DispatchTaskInput(**t)
            for t in tasks
        ]
        if not raw:
            raise ValueError("dispatch: tasks must be non-empty")

        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        now = _now()
        entries: dict[str, _TaskEntry] = {}
        for t in raw:
            tid = t.task_id or f"task_{uuid.uuid4().hex[:10]}"
            entries[tid] = _TaskEntry(
                task_id=tid,
                batch_id=batch_id,
                description=t.description,
                subagent_name=t.subagent_name,
                depends_on=list(t.depends_on),
                priority=t.priority,
                write_paths=list(t.write_paths),
            )

        batch = _BatchEntry(
            batch_id=batch_id,
            tasks=entries,
            created_at=now,
            aggregation_strategy=aggregation_strategy,
            runtime_session_metadata=_initial_runtime_session_metadata(context),
            owner_id=owner_id,
        )
        batch.plan = _build_plan(
            batch_id=batch_id,
            entries=entries,
            max_concurrency=max_concurrency or self._max_concurrency,
        )
        validation = validate_work_plan(batch.plan)
        batch.plan.validation_issues = list(validation.errors)
        batch.plan.validation_warnings = list(validation.warnings)
        batch.conflicts.extend(validation.errors)
        for entry in entries.values():
            entry.work_contract = _contract_for(batch.plan, entry.task_id)

        run_context = {
            "thread_id": thread_id,
            "model_name": model_name,
            "execution_mode": execution_mode,
        }
        if context:
            run_context.update(context)

        # Carry the spawning parent's prompt-injection taint into the batch's
        # subagents. dispatch() runs in the parent's context; the per-task
        # threads spawned by the scheduler start with a fresh contextvar, so
        # capture HERE (before the pool boundary) and let the runner thread it
        # into each subagent intent's user_context (honored at react-loop start).
        try:
            from runtime.safety.validation.prompt_injection import (
                current_injection_taint,
            )
            _taint = current_injection_taint()
            if _taint and _taint != "none":
                run_context.setdefault("_inherited_injection_taint", _taint)
        except Exception:  # noqa: BLE001 - taint propagation is best-effort
            pass

        with self._lock:
            self._batches[batch_id] = batch
            for tid in entries:
                self._task_index[tid] = batch_id
            self._publish_stage_change_locked(
                batch,
                stage="task_analysis",
                status="running",
                progress=0.10,
                message="Task graph received",
            )
            self._publish_stage_change_locked(
                batch,
                stage="matching_agents",
                status="running",
                progress=0.22,
                message="Matching available agents to work lanes",
            )
            for entry in entries.values():
                self._publish_task_update_locked(
                    batch,
                    entry,
                    phase="planned",
                    message=(
                        f"{entry.subagent_name} queued for a focused "
                        "research lane"
                    ),
                )
            self._publish_stage_change_locked(
                batch,
                stage="assigning_tasks",
                status="running",
                progress=0.35,
                message="Tasks assigned; agents are starting",
            )
            if batch.plan.validation_issues or batch.plan.validation_warnings:
                self._publish_stage_change_locked(
                    batch,
                    stage="contract_validation",
                    status="failed" if batch.plan.validation_issues else "warning",
                    progress=0.36,
                    message="Work contracts validated",
                )

        threading.Thread(
            target=self._schedule_batch,
            args=(batch.batch_id, run_context),
            name=f"parallel-agent-scheduler-{batch.batch_id}",
            daemon=True,
        ).start()

        return batch.to_wire()

    def get_batch(self, batch_id: str) -> BatchResult | None:
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return None
            return batch.to_wire()

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            bid = self._task_index.get(task_id)
            if bid is None:
                return False
            batch = self._batches[bid]
            entry = batch.tasks.get(task_id)
            if entry is None:
                return False
            if entry.status in ("completed", "failed", "cancelled", "timed_out"):
                return False
            entry.cancel_event.set()
            if entry.status == "pending":
                entry.status = "cancelled"
                entry.completed_at = _now()
                self._publish_task_update_locked(
                    batch,
                    entry,
                    phase="cancelled",
                    message=f"{entry.subagent_name} cancelled before start",
                )
                self._maybe_close_batch_locked(batch)
            return True

    def cancel_all(self) -> bool:
        with self._lock:
            for batch in self._batches.values():
                for entry in batch.tasks.values():
                    if entry.status in ("completed", "failed", "cancelled", "timed_out"):
                        continue
                    entry.cancel_event.set()
                    if entry.status == "pending":
                        entry.status = "cancelled"
                        entry.completed_at = _now()
                        self._publish_task_update_locked(
                            batch,
                            entry,
                            phase="cancelled",
                            message=(
                                f"{entry.subagent_name} cancelled before start"
                            ),
                        )
                self._maybe_close_batch_locked(batch)
        return True

    # Ownership helpers (get_batch_owner, get_task_owner,
    # list_batch_ids_for_owner, cancel_all_for_owner) live in
    # OwnershipMixin — see runtime/execution/parallel_agents/ownership.py.

    def status(self) -> OrchestratorStatus:
        with self._lock:
            active = 0
            pending = 0
            completed = 0
            failed = 0
            cancelled = 0
            batches_map: dict[str, str] = {}
            for bid, batch in self._batches.items():
                batches_map[bid] = batch.derived_status()
                for t in batch.tasks.values():
                    s = t.status
                    if s == "running":
                        active += 1
                    elif s == "pending":
                        pending += 1
                    elif s == "completed":
                        completed += 1
                    elif s == "failed" or s == "timed_out":
                        failed += 1
                    elif s == "cancelled":
                        cancelled += 1
            return OrchestratorStatus(
                active_count=active,
                pending_count=pending,
                completed_count=completed,
                failed_count=failed,
                cancelled_count=cancelled,
                max_concurrency=self._max_concurrency,
                batches=batches_map,
            )

    def split(
        self,
        task: str,
        *,
        max_subtasks: int | None = None,
        context: str | None = None,
        model_name: str | None = None,
    ) -> SplitResult:
        if self._splitter is not None:
            try:
                return self._splitter(
                    task,
                    max_subtasks=max_subtasks,
                    context=context,
                    model_name=model_name,
                )
            except Exception as e:   # noqa: BLE001
                _log.warning("splitter failed · fallback stub · err=%s", e)

        tid = f"task_{uuid.uuid4().hex[:10]}"
        return SplitResult(
            tasks=[SplitTask(
                task_id=tid,
                description=task,
                subagent_name="general-purpose",
                depends_on=[],
                priority=0,
            )],
            dag_levels=[[tid]],
            total_levels=1,
            is_parallelizable=False,
        )

    async def subscribe(
        self,
        batch_id: str,
        *,
        after_sequence: int = 0,
    ) -> AsyncIterator[BatchStreamEvent]:
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return
            for past in batch.event_log:
                if (past.sequence or 0) > after_sequence:
                    queue.put_nowait(past)
            if batch.completed_at is not None and queue.empty():
                return
            batch.subscribers.append((queue, loop))

        try:
            while True:
                ev: BatchStreamEvent = await queue.get()
                yield ev
                if ev.type == "batch_complete":
                    return
        finally:
            with self._lock:
                batch = self._batches.get(batch_id)
                if batch is not None:
                    batch.subscribers = [
                        (q, lease) for (q, lease) in batch.subscribers if q is not queue
                    ]

    def shutdown(self, wait: bool = False) -> None:
        self._closed = True
        self._pool.shutdown(wait=wait, cancel_futures=True)


    def _guard_open(self) -> None:
        if self._closed:
            raise RuntimeError("orchestrator is closed")

    def _run_task(self, entry: _TaskEntry, context: dict[str, Any]) -> None:
        if entry.cancel_event.is_set():
            with self._lock:
                if entry.status == "pending":
                    entry.status = "cancelled"
                    entry.completed_at = _now()
                    batch = self._batches[entry.batch_id]
                    self._publish_task_update_locked(
                        batch,
                        entry,
                        phase="cancelled",
                        message=f"{entry.subagent_name} cancelled before start",
                    )
                    self._maybe_close_batch_locked(batch)
            return

        route_decision = _route_decision(entry.subagent_name, context)
        with self._lock:
            entry.route_decision = route_decision
        if route_decision.get("action") == "block":
            with self._lock:
                if entry.status == "pending":
                    entry.status = "failed"
                    entry.started_at = _now()
                    entry.completed_at = entry.started_at
                    entry.error = (
                        "subagent_route_blocked: "
                        f"{route_decision.get('reason') or 'blocked by routing policy'}"
                    )
                    batch = self._batches[entry.batch_id]
                    self._publish_task_update_locked(
                        batch,
                        entry,
                        phase="subagent_route_blocked",
                        message=f"{entry.subagent_name} blocked by fitness routing",
                    )
                    self._maybe_close_batch_locked(batch)
            return

        with self._lock:
            entry.status = "running"
            entry.started_at = _now()
            batch = self._batches[entry.batch_id]
            self._publish_task_update_locked(
                batch,
                entry,
                phase="started",
                message=f"{entry.subagent_name} started working",
            )

        run_context = dict(context)
        run_context["subagent_route_decision"] = route_decision
        with self._lock:
            batch = self._batches[entry.batch_id]
            run_context["runtime_session_metadata"] = batch.runtime_session_metadata
            run_context["file_write_owner"] = entry.task_id
            if entry.work_contract is not None:
                run_context["work_contract"] = entry.work_contract.model_dump()
            _authorize_dependency_file_handoffs(batch, entry, run_context)
        run_context["emit_tool_event"] = self._make_tool_event_emitter(entry)

        output: str | None = None
        error: str | None = None
        try:
            output = self._runner(
                entry.description,
                subagent_name=entry.subagent_name,
                context=run_context,
                cancel_event=entry.cancel_event,
            )
        except TypeError:
            try:
                output = self._runner(
                    entry.description,
                    subagent_name=entry.subagent_name,
                    context=run_context,
                )
            except Exception as e:   # noqa: BLE001
                error = f"{type(e).__name__}: {e}"
        except Exception as e:   # noqa: BLE001
            error = f"{type(e).__name__}: {e}"

        with self._lock:
            entry.completed_at = _now()
            if entry.cancel_event.is_set() and error is None:
                entry.status = "cancelled"
            elif error is not None:
                entry.status = "failed"
                entry.error = error
            else:
                cleaned_output = output or ""
                if not cleaned_output.strip():
                    entry.status = "failed"
                    entry.error = "empty_result_contract_violation"
                    entry.result = cleaned_output
                else:
                    entry.status = "completed"
                    entry.result = cleaned_output
            batch = self._batches[entry.batch_id]
            self._publish_task_update_locked(
                batch,
                entry,
                phase="failed" if entry.status == "failed" else entry.status,
                message=f"{entry.subagent_name} {entry.status}",
                result_preview=_preview(entry.result),
            )
            self._maybe_close_batch_locked(batch)

    def _schedule_batch(self, batch_id: str, context: dict[str, Any]) -> None:
        while True:
            with self._lock:
                batch = self._batches.get(batch_id)
                if batch is None or batch.completed_at is not None:
                    return
                ready = [
                    entry for entry in batch.tasks.values()
                    if entry.status == "pending"
                    and entry.future is None
                    and _deps_terminal_success(batch, entry)
                ]
                blocked_failed = [
                    entry for entry in batch.tasks.values()
                    if entry.status == "pending"
                    and any(
                        batch.tasks[dep].status in {
                            "failed", "cancelled", "timed_out",
                        }
                        for dep in entry.depends_on
                        if dep in batch.tasks
                    )
                ]
                for entry in blocked_failed:
                    entry.status = "cancelled"
                    entry.completed_at = _now()
                    entry.error = "dependency_failed"
                    self._publish_task_update_locked(
                        batch,
                        entry,
                        phase="dependency_blocked",
                        message=f"{entry.subagent_name} blocked by dependency",
                    )
                if blocked_failed:
                    self._maybe_close_batch_locked(batch)
                if ready:
                    ready.sort(key=lambda e: (-e.priority, e.task_id))
                    for entry in ready:
                        try:
                            entry.future = self._pool.submit(
                                self._run_task, entry, context,
                            )
                        except RuntimeError:
                            return

            if not ready:
                time.sleep(0.01)

    def _maybe_close_batch_locked(self, batch: _BatchEntry) -> None:
        if batch.completed_at is not None:
            return
        if any(
            t.status in ("pending", "running") for t in batch.tasks.values()
        ):
            return
        batch.completed_at = _now()
        batch.aggregated_content = self._aggregate_locked(batch)
        self._publish_stage_change_locked(
            batch,
            stage="final_report",
            status=batch.derived_status(),
            progress=1.0,
            message="Agent results integrated",
        )
        ev = BatchStreamEvent(
            type="batch_complete",
            batch_id=batch.batch_id,
            lane="timeline",
            status=batch.derived_status(),
            payload={
                "total_tasks": len(batch.tasks),
                "completed_tasks": batch.counts()[1],
                "batch_metrics": _batch_metrics(batch),
            },
        )
        self._broadcast_locked(batch, ev)

    def _aggregate_locked(self, batch: _BatchEntry) -> str | None:
        strategy = batch.aggregation_strategy or "concat"
        parts: list[str] = []
        for t in batch.tasks.values():
            if t.status == "completed" and t.result:
                parts.append(f"[{t.subagent_name}] {t.result}")
        if not parts:
            return None
        if strategy == "concat":
            return "\n\n".join(parts)
        return "\n\n".join(parts)

    def _publish_task_update_locked(
        self,
        batch: _BatchEntry,
        entry: _TaskEntry,
        *,
        phase: str | None = None,
        message: str | None = None,
        result_preview: str | None = None,
    ) -> None:
        ev = BatchStreamEvent(
            type="task_update",
            batch_id=batch.batch_id,
            task_id=entry.task_id,
            lane="agent",
            status=entry.status,
            subagent_name=entry.subagent_name,
            phase=phase,
            node_ids=[entry.task_id],
            payload={
                "contract_id": (
                    entry.work_contract.contract_id
                    if entry.work_contract is not None else entry.task_id
                ),
                "depends_on": list(entry.depends_on),
                "owned_scope": (
                    list(entry.work_contract.owned_scope)
                    if entry.work_contract is not None else [f"task:{entry.task_id}"]
                ),
                "write_paths": list(entry.write_paths),
                **(
                    {"subagent_route_decision": entry.route_decision}
                    if entry.route_decision is not None else {}
                ),
            },
            message=message,
            description=entry.description,
            result_preview=result_preview,
            duration_seconds=entry.duration(),
            error=entry.error,
        )
        self._broadcast_locked(batch, ev)

    def _publish_stage_change_locked(
        self,
        batch: _BatchEntry,
        *,
        stage: str,
        status: str,
        progress: float | None = None,
        message: str | None = None,
    ) -> None:
        ev = BatchStreamEvent(
            type="stage_change",
            batch_id=batch.batch_id,
            lane="workflow",
            status=status,
            stage=stage,
            payload={
                "stage": stage,
                "total_tasks": len(batch.tasks),
                "completed_tasks": batch.counts()[1],
                "failed_tasks": batch.counts()[2],
                "cancelled_tasks": batch.counts()[3],
            },
            progress=progress,
            message=message,
        )
        self._broadcast_locked(batch, ev)

    def _make_tool_event_emitter(
        self, entry: _TaskEntry,
    ) -> Callable[..., None]:
        def emit_tool_event(
            *,
            tool_name: str,
            status: str | None = None,
            input_preview: str | None = None,
            output_preview: str | None = None,
            artifact_paths: list[str] | None = None,
            message: str | None = None,
            payload: dict[str, object] | None = None,
        ) -> None:
            with self._lock:
                batch = self._batches.get(entry.batch_id)
                if batch is None:
                    return
                ev = BatchStreamEvent(
                    type="tool_call",
                    batch_id=batch.batch_id,
                    task_id=entry.task_id,
                    lane="computer",
                    status=status,
                    subagent_name=entry.subagent_name,
                    tool_name=tool_name,
                    tool_input_preview=input_preview,
                    tool_output_preview=output_preview,
                    artifact_paths=artifact_paths or [],
                    node_ids=[entry.task_id],
                    payload=payload or {},
                    message=message,
                    description=entry.description,
                )
                self._broadcast_locked(batch, ev)

        return emit_tool_event

    def _broadcast_locked(
        self, batch: _BatchEntry, ev: BatchStreamEvent,
    ) -> None:
        batch.event_sequence += 1
        ev.sequence = batch.event_sequence
        ev.created_at = _iso(_now())
        batch.event_log.append(ev)
        dead: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = []
        for queue, loop in batch.subscribers:
            try:
                loop.call_soon_threadsafe(queue.put_nowait, ev)
            except RuntimeError:
                dead.append((queue, loop))
        if dead:
            batch.subscribers = [
                x for x in batch.subscribers if x not in dead
            ]
