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
    BatchRecoverySnapshot,
    BatchRecoveryTask,
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
from .process_worker import (
    close_process_messages,
    poll_process_message,
    spawn_process_runner,
    terminate_process,
)

_log = logging.getLogger(__name__)


TaskRunner = Callable[..., str]
_TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled", "timed_out"}
_UNRUNNABLE_PLAN_ISSUE_PREFIXES = ("dependency_cycle:", "unknown_dependency:")


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


def _timeout_setting(
    context: dict[str, Any],
    key: str,
    *,
    default: float,
    maximum: float,
) -> float:
    try:
        value = float(context.get(key, default))
    except (TypeError, ValueError):
        return default
    return max(0.01, min(value, maximum))


def _timeout_policy(context: dict[str, Any]) -> dict[str, float]:
    return {
        "task_timeout_s": _timeout_setting(
            context,
            "subagent_task_timeout_s",
            default=900.0,
            maximum=3600.0,
        ),
        "queue_timeout_s": _timeout_setting(
            context,
            "subagent_queue_timeout_s",
            default=60.0,
            maximum=900.0,
        ),
        "cancel_grace_s": _timeout_setting(
            context,
            "subagent_cancel_grace_s",
            default=5.0,
            maximum=60.0,
        ),
        "worker_replacement_limit": _timeout_setting(
            context,
            "subagent_worker_replacement_limit",
            default=8.0,
            maximum=32.0,
        ),
    }


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
    submitted_at: datetime | None = None
    cancel_requested_at: datetime | None = None
    completed_at: datetime | None = None
    cancel_event: threading.Event = field(default_factory=threading.Event)
    future: Future | None = None
    work_contract: WorkContract | None = None
    route_decision: dict[str, Any] | None = None
    worker_generation: int | None = None
    worker_state: str = "pending"
    replacement_generation: int | None = None
    late_result_ignored_at: datetime | None = None
    worker_isolation: str = "thread"
    worker_process: Any = None
    process_cancel_event: Any = None
    process_messages: Any = None

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
            worker_generation=self.worker_generation,
            worker_state=self.worker_state,
            replacement_generation=self.replacement_generation,
            late_result_ignored_at=_iso(self.late_result_ignored_at),
            worker_isolation=self.worker_isolation,
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
    timeout_policy: dict[str, float] = field(default_factory=dict)
    worker_replacements: list[dict[str, Any]] = field(default_factory=list)
    subscribers: list[tuple[asyncio.Queue, asyncio.AbstractEventLoop]] = field(default_factory=list)
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

    def validation_issues(self) -> list[str]:
        return list(self.plan.validation_issues) if self.plan is not None else []

    def validation_warnings(self) -> list[str]:
        return list(self.plan.validation_warnings) if self.plan is not None else []

    def artifact_count(self) -> int:
        return sum(
            len(event.artifact_paths)
            for event in self.event_log
            if getattr(event, "artifact_paths", None)
        )

    def completion_receipt(self) -> dict[str, object]:
        return build_completion_receipt(
            [t.status for t in self.tasks.values()],
            contract_issues=self.validation_issues(),
            contract_warnings=self.validation_warnings(),
            artifact_count=self.artifact_count(),
            output_present=bool(self.aggregated_content),
        ).to_dict()

    def counts(self) -> tuple[int, int, int, int]:
        """(total, completed, failed, cancelled)."""
        total = len(self.tasks)
        completed = sum(1 for t in self.tasks.values() if t.status == "completed")
        failed = sum(1 for t in self.tasks.values() if t.status in ("failed", "timed_out"))
        cancelled = sum(1 for t in self.tasks.values() if t.status == "cancelled")
        return total, completed, failed, cancelled

    def to_wire(self) -> BatchResult:
        total, completed, failed, cancelled = self.counts()
        coordination_summary = _build_coordination_summary(self)
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
            completion_receipt=self.completion_receipt(),
            file_write_observability=file_write_lease_snapshot(
                self.runtime_session_metadata,
            ),
            coordination_summary=coordination_summary,
            worker_observability=_build_worker_observability(self),
        )


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
        self._pool_generation = 0
        self._retired_pools: dict[int, ThreadPoolExecutor] = {}
        self._lock = threading.RLock()
        self._batches: dict[str, _BatchEntry] = {}
        self._task_index: dict[str, str] = {}  # task_id → batch_id
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
        max_concurrency: int | None = None,  # Implementation note.
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
            t if isinstance(t, DispatchTaskInput) else DispatchTaskInput(**t) for t in tasks
        ]
        if not raw:
            raise ValueError("dispatch: tasks must be non-empty")

        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        now = _now()
        entries: dict[str, _TaskEntry] = {}
        for t in raw:
            tid = t.task_id or f"task_{uuid.uuid4().hex[:10]}"
            if tid in entries:
                raise ValueError(f"dispatch: duplicate task_id {tid!r}")
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
        batch.timeout_policy = _timeout_policy(run_context)

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

        should_start_scheduler = True
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
                    message=(f"{entry.subagent_name} queued for a focused research lane"),
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
            if self._fail_unrunnable_plan_locked(batch):
                should_start_scheduler = False

        if should_start_scheduler:
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

    def recovery_snapshot(self, batch_id: str) -> BatchRecoverySnapshot | None:
        """Return a redacted recovery/audit view for a parallel batch."""
        with self._lock:
            batch = self._batches.get(batch_id)
            if batch is None:
                return None
            return self._build_recovery_snapshot_locked(batch)

    def cancel_task(self, task_id: str) -> bool:
        with self._lock:
            bid = self._task_index.get(task_id)
            if bid is None:
                return False
            batch = self._batches[bid]
            entry = batch.tasks.get(task_id)
            if entry is None:
                return False
            if entry.status in _TERMINAL_TASK_STATUSES:
                return False
            entry.cancel_event.set()
            entry.cancel_requested_at = entry.cancel_requested_at or _now()
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
                    if entry.status in _TERMINAL_TASK_STATUSES:
                        continue
                    entry.cancel_event.set()
                    entry.cancel_requested_at = entry.cancel_requested_at or _now()
                    if entry.status == "pending":
                        entry.status = "cancelled"
                        entry.completed_at = _now()
                        self._publish_task_update_locked(
                            batch,
                            entry,
                            phase="cancelled",
                            message=(f"{entry.subagent_name} cancelled before start"),
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
                worker_generation=self._pool_generation,
                worker_replacement_count=sum(
                    1
                    for batch in self._batches.values()
                    for row in batch.worker_replacements
                    if row.get("event")
                    in {"worker_generation_replaced", "process_worker_terminated"}
                ),
                retired_worker_generation_count=len(self._retired_pools),
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
            except Exception as e:  # noqa: BLE001
                _log.warning("splitter failed · fallback stub · err=%s", e)

        tid = f"task_{uuid.uuid4().hex[:10]}"
        return SplitResult(
            tasks=[
                SplitTask(
                    task_id=tid,
                    description=task,
                    subagent_name="general-purpose",
                    depends_on=[],
                    priority=0,
                )
            ],
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
        for pool in list(self._retired_pools.values()):
            pool.shutdown(wait=wait, cancel_futures=True)
        self._retired_pools.clear()

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
            if entry.status in _TERMINAL_TASK_STATUSES:
                return
            entry.status = "running"
            entry.worker_state = "running"
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
        isolation = str(run_context.get("subagent_worker_isolation") or "thread").strip()
        entry.worker_isolation = "process" if isolation == "process" else "thread"
        if entry.worker_isolation == "process":
            output, error = self._invoke_process_runner(entry, run_context)
        else:
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
                except Exception as e:  # noqa: BLE001
                    error = f"{type(e).__name__}: {e}"
            except Exception as e:  # noqa: BLE001
                error = f"{type(e).__name__}: {e}"

        with self._lock:
            if entry.status in {"cancelled", "timed_out"}:
                entry.late_result_ignored_at = _now()
                return
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
            entry.worker_state = "released"
            batch = self._batches[entry.batch_id]
            self._publish_task_update_locked(
                batch,
                entry,
                phase="failed" if entry.status == "failed" else entry.status,
                message=f"{entry.subagent_name} {entry.status}",
                result_preview=_preview(entry.result),
            )
            self._maybe_close_batch_locked(batch)

    def _invoke_process_runner(
        self,
        entry: _TaskEntry,
        run_context: dict[str, Any],
    ) -> tuple[str | None, str | None]:
        try:
            process, process_cancel, messages = spawn_process_runner(
                runner=self._runner,
                description=entry.description,
                subagent_name=entry.subagent_name,
                context=run_context,
            )
        except Exception as exc:  # noqa: BLE001 - isolation boundary fails closed
            return None, f"process_isolation_start_failed:{type(exc).__name__}: {exc}"

        with self._lock:
            entry.worker_process = process
            entry.process_cancel_event = process_cancel
            entry.process_messages = messages
            entry.worker_state = "process_running"

        output: str | None = None
        error: str | None = None
        emitter = run_context.get("emit_tool_event")
        try:
            while process.is_alive():
                if entry.cancel_event.is_set():
                    process_cancel.set()
                message = poll_process_message(messages)
                if message is None:
                    continue
                kind, payload = message
                if kind == "result":
                    output = str(payload or "")
                elif kind == "error":
                    error = str(payload or "process worker failed")
                elif kind == "tool_event" and callable(emitter) and isinstance(payload, dict):
                    emitter(**payload)
            process.join(timeout=0.1)
            for _ in range(4):
                message = poll_process_message(messages, timeout=0.01)
                if message is None:
                    break
                kind, payload = message
                if kind == "result":
                    output = str(payload or "")
                elif kind == "error":
                    error = str(payload or "process worker failed")
                elif kind == "tool_event" and callable(emitter) and isinstance(payload, dict):
                    emitter(**payload)
            if output is None and error is None and process.exitcode not in {0, None}:
                error = f"process_worker_exit:{process.exitcode}"
        finally:
            with self._lock:
                entry.worker_process = None
                entry.process_cancel_event = None
                entry.process_messages = None
            close_process_messages(messages)
        return output, error

    def _schedule_batch(self, batch_id: str, context: dict[str, Any]) -> None:
        while True:
            with self._lock:
                batch = self._batches.get(batch_id)
                if batch is None or batch.completed_at is not None:
                    return
                self._expire_tasks_locked(batch, context)
                if batch.completed_at is not None:
                    return
                ready = [
                    entry
                    for entry in batch.tasks.values()
                    if entry.status == "pending"
                    and entry.future is None
                    and _deps_terminal_success(batch, entry)
                ]
                blocked_failed = [
                    entry
                    for entry in batch.tasks.values()
                    if entry.status == "pending"
                    and any(
                        batch.tasks[dep].status
                        in {
                            "failed",
                            "cancelled",
                            "timed_out",
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
                if not ready and not blocked_failed:
                    self._fail_stalled_pending_tasks_locked(batch)
                if ready:
                    ready.sort(key=lambda e: (-e.priority, e.task_id))
                    for entry in ready:
                        try:
                            entry.submitted_at = _now()
                            entry.worker_generation = self._pool_generation
                            entry.worker_state = "submitted"
                            entry.future = self._pool.submit(
                                self._run_task,
                                entry,
                                context,
                            )
                        except RuntimeError:
                            return

            if not ready:
                time.sleep(0.01)

    def _expire_tasks_locked(
        self,
        batch: _BatchEntry,
        context: dict[str, Any],
    ) -> None:
        now = _now()
        policy = batch.timeout_policy or _timeout_policy(context)
        task_timeout_s = policy["task_timeout_s"]
        queue_timeout_s = policy["queue_timeout_s"]
        cancel_grace_s = policy["cancel_grace_s"]
        changed = False
        for entry in batch.tasks.values():
            phase = ""
            message = ""
            if (
                entry.status == "running"
                and entry.cancel_requested_at is not None
                and (now - entry.cancel_requested_at).total_seconds() >= cancel_grace_s
            ):
                entry.status = "cancelled"
                entry.error = "cancel_grace_exceeded"
                phase = "cancel_forced"
                message = f"{entry.subagent_name} cancelled after grace period"
            elif (
                entry.status == "running"
                and entry.started_at is not None
                and (now - entry.started_at).total_seconds() >= task_timeout_s
            ):
                entry.cancel_event.set()
                entry.status = "timed_out"
                entry.error = "runner_timeout"
                phase = "timed_out"
                message = f"{entry.subagent_name} exceeded the task timeout"
            elif (
                entry.status == "pending"
                and entry.future is not None
                and entry.submitted_at is not None
                and (now - entry.submitted_at).total_seconds() >= queue_timeout_s
            ):
                entry.cancel_event.set()
                entry.future.cancel()
                entry.status = "timed_out"
                entry.error = "queue_timeout"
                phase = "queue_timed_out"
                message = f"{entry.subagent_name} exceeded the dispatch queue timeout"
            if not phase:
                continue
            entry.completed_at = now
            if phase in {"timed_out", "cancel_forced"}:
                self._replace_stuck_worker_generation_locked(
                    batch,
                    entry,
                    reason=entry.error or phase,
                    now=now,
                )
            self._publish_task_update_locked(
                batch,
                entry,
                phase=phase,
                message=message,
            )
            changed = True
        if changed:
            self._maybe_close_batch_locked(batch)

    def _replace_stuck_worker_generation_locked(
        self,
        batch: _BatchEntry,
        entry: _TaskEntry,
        *,
        reason: str,
        now: datetime,
    ) -> None:
        """Quarantine a non-cooperative worker generation and restore capacity.

        Python cannot safely kill a running thread. The authoritative pool is
        therefore replaced without waiting, queued tasks are migrated, and
        late results from the retired generation are ignored because their
        task already has a terminal state.
        """

        generation = entry.worker_generation
        future = entry.future
        if generation is None or future is None or future.done():
            entry.worker_state = "released"
            return
        if entry.worker_process is not None:
            if entry.process_cancel_event is not None:
                entry.process_cancel_event.set()
            terminated = terminate_process(entry.worker_process)
            entry.worker_state = "process_terminated" if terminated else "process_kill_failed"
            entry.replacement_generation = generation
            batch.worker_replacements.append(
                {
                    "event": "process_worker_terminated",
                    "retired_generation": generation,
                    "replacement_generation": generation,
                    "created_replacement": False,
                    "trigger_task_id": entry.task_id,
                    "reason": reason,
                    "at": _iso(now),
                    "terminated": terminated,
                    "quarantined_task_ids": [entry.task_id],
                    "migrated_task_ids": [],
                }
            )
            return
        entry.worker_state = "quarantined"

        existing = next(
            (
                row
                for row in batch.worker_replacements
                if int(row.get("retired_generation", -1)) == generation
            ),
            None,
        )
        if existing is not None:
            quarantined = existing.setdefault("quarantined_task_ids", [])
            if entry.task_id not in quarantined:
                quarantined.append(entry.task_id)
            entry.replacement_generation = int(
                existing.get("replacement_generation", self._pool_generation)
            )
            return

        limit = int(batch.timeout_policy.get("worker_replacement_limit") or 0)
        if len(batch.worker_replacements) >= limit:
            entry.worker_state = "quarantined_limit_reached"
            batch.worker_replacements.append(
                {
                    "event": "replacement_limit_reached",
                    "retired_generation": generation,
                    "replacement_generation": self._pool_generation,
                    "trigger_task_id": entry.task_id,
                    "reason": reason,
                    "at": _iso(now),
                    "quarantined_task_ids": [entry.task_id],
                    "migrated_task_ids": [],
                }
            )
            return

        created_replacement = False
        if generation == self._pool_generation:
            retired_pool = self._pool
            self._pool_generation += 1
            self._pool = ThreadPoolExecutor(
                max_workers=self._max_concurrency,
                thread_name_prefix=f"parallel-agent-g{self._pool_generation}",
            )
            self._retired_pools[generation] = retired_pool
            retired_pool.shutdown(wait=False, cancel_futures=True)
            created_replacement = True

        replacement_generation = self._pool_generation
        entry.replacement_generation = replacement_generation
        migrated = self._migrate_queued_generation_locked(generation)
        batch.worker_replacements.append(
            {
                "event": "worker_generation_replaced",
                "retired_generation": generation,
                "replacement_generation": replacement_generation,
                "created_replacement": created_replacement,
                "trigger_task_id": entry.task_id,
                "reason": reason,
                "at": _iso(now),
                "quarantined_task_ids": [entry.task_id],
                "migrated_task_ids": migrated,
            }
        )

    def _migrate_queued_generation_locked(self, generation: int) -> list[str]:
        migrated: list[str] = []
        for current_batch in self._batches.values():
            for candidate in current_batch.tasks.values():
                if (
                    candidate.status != "pending"
                    or candidate.worker_generation != generation
                    or candidate.future is None
                ):
                    continue
                if not candidate.future.cancel():
                    continue
                candidate.future = None
                candidate.submitted_at = None
                candidate.worker_generation = None
                candidate.worker_state = "migrated"
                migrated.append(candidate.task_id)
        return migrated

    def _maybe_close_batch_locked(self, batch: _BatchEntry) -> None:
        if batch.completed_at is not None:
            return
        if any(t.status in ("pending", "running") for t in batch.tasks.values()):
            return
        batch.completed_at = _now()
        batch.aggregated_content = self._aggregate_locked(batch)
        total, completed, failed, cancelled = batch.counts()
        status = batch.derived_status()
        self._publish_stage_change_locked(
            batch,
            stage="final_report",
            status=status,
            progress=1.0,
            message="Agent results integrated",
        )
        ev = BatchStreamEvent(
            type="batch_complete",
            batch_id=batch.batch_id,
            lane="timeline",
            status=status,
            payload={
                "status": status,
                "total_tasks": total,
                "completed_tasks": completed,
                "failed_tasks": failed,
                "cancelled_tasks": cancelled,
                "completion_receipt": batch.completion_receipt(),
                "coordination_summary": _build_coordination_summary(batch),
            },
        )
        self._broadcast_locked(batch, ev)

    def _unrunnable_plan_issues(self, batch: _BatchEntry) -> list[str]:
        return [
            issue
            for issue in batch.validation_issues()
            if issue.startswith(_UNRUNNABLE_PLAN_ISSUE_PREFIXES)
        ]

    def _fail_unrunnable_plan_locked(self, batch: _BatchEntry) -> bool:
        issues = self._unrunnable_plan_issues(batch)
        if not issues:
            return False
        error = "invalid_work_plan:" + ";".join(issues)
        now = _now()
        for entry in batch.tasks.values():
            if entry.status in _TERMINAL_TASK_STATUSES:
                continue
            entry.cancel_event.set()
            entry.status = "failed"
            entry.error = error
            entry.started_at = entry.started_at or now
            entry.completed_at = now
            self._publish_task_update_locked(
                batch,
                entry,
                phase="invalid_work_plan",
                message=f"{entry.subagent_name} blocked by invalid work plan",
            )
        self._maybe_close_batch_locked(batch)
        return True

    def _fail_stalled_pending_tasks_locked(self, batch: _BatchEntry) -> bool:
        if batch.completed_at is not None:
            return False
        active = any(
            entry.status == "running"
            or (entry.status == "pending" and entry.future is not None and not entry.future.done())
            for entry in batch.tasks.values()
        )
        stalled = [
            entry
            for entry in batch.tasks.values()
            if entry.status == "pending" and entry.future is None
        ]
        if active or not stalled:
            return False

        issues = self._unrunnable_plan_issues(batch)
        error = "invalid_work_plan:" + ";".join(issues) if issues else "dependency_unresolvable"
        now = _now()
        for entry in stalled:
            entry.status = "failed"
            entry.error = error
            entry.started_at = entry.started_at or now
            entry.completed_at = now
            self._publish_task_update_locked(
                batch,
                entry,
                phase="dependency_unresolvable",
                message=f"{entry.subagent_name} dependency graph stalled",
            )
        self._maybe_close_batch_locked(batch)
        return True

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

    def _build_recovery_snapshot_locked(
        self,
        batch: _BatchEntry,
    ) -> BatchRecoverySnapshot:
        total, completed, failed, cancelled = batch.counts()
        run_state = converge_run_state([t.status for t in batch.tasks.values()])
        artifacts_by_task: dict[str, list[str]] = {task_id: [] for task_id in batch.tasks}
        event_types: dict[str, int] = {}
        first_sequence: int | None = None
        last_sequence: int | None = None
        for event in batch.event_log:
            event_types[event.type] = event_types.get(event.type, 0) + 1
            sequence = event.sequence or 0
            if sequence > 0:
                first_sequence = (
                    sequence if first_sequence is None else min(first_sequence, sequence)
                )
                last_sequence = sequence if last_sequence is None else max(last_sequence, sequence)
            if event.task_id and event.artifact_paths:
                bucket = artifacts_by_task.setdefault(event.task_id, [])
                for path in event.artifact_paths:
                    if path not in bucket:
                        bucket.append(path)

        all_artifacts: list[str] = []
        for paths in artifacts_by_task.values():
            for path in paths:
                if path not in all_artifacts:
                    all_artifacts.append(path)

        failed_task_ids = [
            entry.task_id
            for entry in batch.tasks.values()
            if entry.status in {"failed", "timed_out"}
        ]
        cancelled_task_ids = [
            entry.task_id for entry in batch.tasks.values() if entry.status == "cancelled"
        ]
        pending_task_ids = [
            entry.task_id for entry in batch.tasks.values() if entry.status == "pending"
        ]
        running_task_ids = [
            entry.task_id for entry in batch.tasks.values() if entry.status == "running"
        ]
        blocked_by_dependency = [
            entry.task_id for entry in batch.tasks.values() if entry.error == "dependency_failed"
        ]
        rerunnable_task_ids = [
            entry.task_id
            for entry in batch.tasks.values()
            if entry.status in {"failed", "cancelled", "timed_out", "pending"}
        ]

        return BatchRecoverySnapshot(
            batch_id=batch.batch_id,
            status=run_state.state,
            terminal=run_state.terminal,
            resume_available=bool(rerunnable_task_ids),
            created_at=_iso(batch.created_at),
            completed_at=_iso(batch.completed_at),
            task_count=total,
            completed_tasks=completed,
            failed_tasks=failed,
            cancelled_tasks=cancelled,
            running_tasks=sum(1 for entry in batch.tasks.values() if entry.status == "running"),
            pending_tasks=sum(1 for entry in batch.tasks.values() if entry.status == "pending"),
            tasks=[
                BatchRecoveryTask(
                    task_id=entry.task_id,
                    status=entry.status,
                    subagent_name=entry.subagent_name,
                    depends_on=list(entry.depends_on),
                    priority=entry.priority,
                    write_paths=list(entry.write_paths),
                    description_preview=_preview(entry.description, max_chars=180),
                    result_preview=_preview(entry.result, max_chars=260),
                    error=entry.error,
                    submitted_at=_iso(entry.submitted_at),
                    cancel_requested_at=_iso(entry.cancel_requested_at),
                    started_at=_iso(entry.started_at),
                    completed_at=_iso(entry.completed_at),
                    duration_seconds=entry.duration(),
                    artifact_paths=artifacts_by_task.get(entry.task_id, []),
                    work_contract=entry.work_contract,
                    route_decision=dict(entry.route_decision or {}),
                    worker_generation=entry.worker_generation,
                    worker_state=entry.worker_state,
                    replacement_generation=entry.replacement_generation,
                    late_result_ignored_at=_iso(entry.late_result_ignored_at),
                    worker_isolation=entry.worker_isolation,
                )
                for entry in batch.tasks.values()
            ],
            dag={task_id: list(entry.depends_on) for task_id, entry in batch.tasks.items()},
            plan=batch.plan,
            event_sequence={
                "event_count": len(batch.event_log),
                "first_sequence": first_sequence,
                "last_sequence": last_sequence,
                "next_after_sequence": last_sequence or 0,
                "types": event_types,
            },
            artifact_paths=all_artifacts,
            conflicts=list(batch.conflicts),
            completion_receipt=batch.completion_receipt(),
            file_write_observability=file_write_lease_snapshot(
                batch.runtime_session_metadata,
            ),
            coordination_summary=_build_coordination_summary(batch),
            worker_observability=_build_worker_observability(batch),
            recovery_hints={
                "rerunnable_task_ids": rerunnable_task_ids,
                "failed_task_ids": failed_task_ids,
                "cancelled_task_ids": cancelled_task_ids,
                "pending_task_ids": pending_task_ids,
                "running_task_ids": running_task_ids,
                "blocked_by_dependency": blocked_by_dependency,
                "checkpoint": {
                    "batch_id": batch.batch_id,
                    "after_sequence": last_sequence or 0,
                },
                "timeout_policy": dict(batch.timeout_policy),
            },
            safety={
                "raw_subagent_outputs_included": False,
                "event_payloads_included": False,
                "owner_id_included": False,
                "result_preview_max_chars": 260,
                "description_preview_max_chars": 180,
                "late_terminal_results_ignored": True,
                "stuck_worker_generations_replaced": True,
                "worker_replacement_limit": int(
                    batch.timeout_policy.get("worker_replacement_limit") or 0
                ),
            },
        )

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
                    if entry.work_contract is not None
                    else entry.task_id
                ),
                "depends_on": list(entry.depends_on),
                "owned_scope": (
                    list(entry.work_contract.owned_scope)
                    if entry.work_contract is not None
                    else [f"task:{entry.task_id}"]
                ),
                "write_paths": list(entry.write_paths),
                "worker_generation": entry.worker_generation,
                "worker_state": entry.worker_state,
                "replacement_generation": entry.replacement_generation,
                "worker_isolation": entry.worker_isolation,
                **(
                    {"subagent_route_decision": entry.route_decision}
                    if entry.route_decision is not None
                    else {}
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
        self,
        entry: _TaskEntry,
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
        self,
        batch: _BatchEntry,
        ev: BatchStreamEvent,
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
            batch.subscribers = [x for x in batch.subscribers if x not in dead]


def _build_worker_observability(batch: _BatchEntry) -> dict[str, object]:
    replacements = [dict(row) for row in batch.worker_replacements]
    quarantined = sorted(
        entry.task_id
        for entry in batch.tasks.values()
        if entry.worker_state.startswith("quarantined")
        or entry.worker_state in {"process_terminated", "process_kill_failed"}
    )
    late_results = sorted(
        entry.task_id for entry in batch.tasks.values() if entry.late_result_ignored_at is not None
    )
    migrated = sorted(
        {str(task_id) for row in replacements for task_id in row.get("migrated_task_ids", [])}
    )
    generations = [
        generation
        for entry in batch.tasks.values()
        for generation in (entry.worker_generation, entry.replacement_generation)
        if generation is not None
    ]
    return {
        "schema": "octopus.parallel_worker_observability.v1",
        "authoritative_generation": max(generations, default=0),
        "replacement_count": sum(
            1
            for row in replacements
            if row.get("event") in {"worker_generation_replaced", "process_worker_terminated"}
        ),
        "generation_replacement_count": sum(
            1 for row in replacements if row.get("event") == "worker_generation_replaced"
        ),
        "process_termination_count": sum(
            1 for row in replacements if row.get("event") == "process_worker_terminated"
        ),
        "replacement_limit_reached_count": sum(
            1 for row in replacements if row.get("event") == "replacement_limit_reached"
        ),
        "quarantined_task_count": len(quarantined),
        "migrated_task_count": len(migrated),
        "late_result_ignored_count": len(late_results),
        "quarantined_task_ids": quarantined,
        "migrated_task_ids": migrated,
        "late_result_ignored_task_ids": late_results,
        "replacement_limit": int(batch.timeout_policy.get("worker_replacement_limit") or 0),
        "replacements": replacements,
    }


def _task_row(entry: _TaskEntry) -> dict[str, object]:
    if entry.status == "completed" and entry.result:
        action = "use_result"
    elif entry.status in {"failed", "timed_out"}:
        action = "retry_task"
    elif entry.status == "cancelled" and entry.error == "dependency_failed":
        action = "retry_after_dependency"
    elif entry.status == "cancelled":
        action = "confirm_cancelled"
    else:
        action = "wait_for_task"
    return {
        "task_id": entry.task_id,
        "subagent_name": entry.subagent_name,
        "status": entry.status,
        "recommended_action": action,
        "result_chars": len(str(entry.result or "").strip()),
        "error": entry.error,
        "depends_on": list(entry.depends_on),
        "write_paths": list(entry.write_paths),
        "duration_seconds": entry.duration(),
        "worker_generation": entry.worker_generation,
        "worker_state": entry.worker_state,
        "replacement_generation": entry.replacement_generation,
        "late_result_ignored": entry.late_result_ignored_at is not None,
        "worker_isolation": entry.worker_isolation,
    }


def _primary_task_id(batch: _BatchEntry) -> str | None:
    for entry in batch.tasks.values():
        if entry.status == "completed" and str(entry.result or "").strip():
            return entry.task_id
    return None


def _coordination_next_action(
    *,
    receipt: dict[str, object],
    failed_task_ids: list[str],
    cancelled_task_ids: list[str],
    conflict_count: int,
    output_present: bool,
) -> str:
    if conflict_count > 0:
        return "review_file_write_conflicts"
    if failed_task_ids and output_present:
        return "use_completed_outputs_and_retry_failed_tasks"
    if failed_task_ids:
        return "retry_failed_tasks"
    if cancelled_task_ids and output_present:
        return "use_completed_outputs_and_requeue_cancelled_tasks"
    if cancelled_task_ids:
        return "requeue_cancelled_tasks"
    if receipt.get("ready") is True:
        return "use_aggregated_result"
    if output_present:
        return "review_partial_outputs"
    return "rerun_with_clearer_task_split"


def _build_coordination_summary(batch: _BatchEntry) -> dict[str, object]:
    """Machine-readable task-level arbitration for a parallel batch."""
    rows = [_task_row(entry) for entry in batch.tasks.values()]
    failed_task_ids = [
        str(row["task_id"]) for row in rows if row["status"] in {"failed", "timed_out"}
    ]
    cancelled_task_ids = [str(row["task_id"]) for row in rows if row["status"] == "cancelled"]
    dependency_blocked_task_ids = [
        entry.task_id for entry in batch.tasks.values() if entry.error == "dependency_failed"
    ]
    receipt = batch.completion_receipt()
    file_obs = file_write_lease_snapshot(batch.runtime_session_metadata)
    conflict_count = int(file_obs.get("conflict_count") or 0)
    primary_task_id = _primary_task_id(batch)
    output_present = bool(batch.aggregated_content)
    next_action = _coordination_next_action(
        receipt=receipt,
        failed_task_ids=failed_task_ids,
        cancelled_task_ids=cancelled_task_ids,
        conflict_count=conflict_count,
        output_present=output_present,
    )
    return {
        "schema": "octopus.parallel_batch_coordination.v1",
        "batch_id": batch.batch_id,
        "status": batch.derived_status(),
        "ready": bool(receipt.get("ready")),
        "primary_task_id": primary_task_id,
        "recommended_next_action": next_action,
        "completed_task_ids": [str(row["task_id"]) for row in rows if row["status"] == "completed"],
        "failed_task_ids": failed_task_ids,
        "cancelled_task_ids": cancelled_task_ids,
        "dependency_blocked_task_ids": dependency_blocked_task_ids,
        "conflict_count": conflict_count,
        "contract_issue_count": len(batch.validation_issues()),
        "contract_warning_count": len(batch.validation_warnings()),
        "output_present": output_present,
        "aggregation_strategy": batch.aggregation_strategy or "concat",
        "tasks": rows,
        "checkpoint": {
            "batch_id": batch.batch_id,
            "after_sequence": batch.event_sequence,
        },
    }
