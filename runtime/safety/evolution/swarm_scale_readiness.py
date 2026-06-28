from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.execution.parallel_agents import (
    DispatchTaskInput,
    ParallelAgentOrchestrator,
)
from runtime.platform.process.paths import project_root as default_project_root

_SCHEMA = "octopus.swarm_scale_readiness.v1"
_PROBE_SCHEMA = "octopus.swarm_scale_probe.v1"


@dataclass(frozen=True)
class SwarmScaleCapability:
    id: str
    title: str
    path: str
    required_terms: tuple[str, ...]
    weight: int = 1


@dataclass(frozen=True)
class SwarmScaleProbeConfig:
    task_count: int = 24
    max_concurrency: int = 6
    sleep_seconds: float = 0.35
    min_speedup: float = 2.0
    failing_task_index: int = 7
    timeout_seconds: float = 8.0


CAPABILITIES: tuple[SwarmScaleCapability, ...] = (
    SwarmScaleCapability(
        id="dag_task_planning",
        title="Dependency DAG task planning",
        path="runtime/execution/parallel_agents/helpers.py",
        required_terms=("build_plan", "BatchPhase", "parallel"),
        weight=2,
    ),
    SwarmScaleCapability(
        id="bounded_parallel_scheduler",
        title="Bounded parallel scheduler",
        path="runtime/execution/parallel_agents/orchestrator.py",
        required_terms=("ThreadPoolExecutor", "max_workers", "_schedule_batch"),
        weight=3,
    ),
    SwarmScaleCapability(
        id="context_and_contract_shards",
        title="Context shards and work contracts",
        path="runtime/execution/parallel_agents/helpers.py",
        required_terms=("WorkContract", "forbidden_scope", "success_criteria"),
        weight=2,
    ),
    SwarmScaleCapability(
        id="streaming_batch_observability",
        title="Streaming batch observability",
        path="runtime/sensing/gateway/parallel_agents_router.py",
        required_terms=("StreamingResponse", "after_sequence", "text/event-stream"),
        weight=2,
    ),
    SwarmScaleCapability(
        id="failure_isolation",
        title="Failure isolation",
        path="runtime/execution/parallel_agents/orchestrator.py",
        required_terms=("_maybe_close_batch_locked", "failed", "dependency_blocked"),
        weight=2,
    ),
    SwarmScaleCapability(
        id="owner_scoped_cancellation",
        title="Owner-scoped cancellation",
        path="runtime/execution/parallel_agents/ownership.py",
        required_terms=("cancel_all_for_owner", "owner_id", "visible to everyone"),
        weight=2,
    ),
)


def compute_swarm_scale_readiness(
    *,
    root: str | Path | None = None,
    include_probe: bool = True,
    probe_config: SwarmScaleProbeConfig | None = None,
) -> dict[str, Any]:
    base = Path(root) if root is not None else default_project_root(Path(__file__))
    capabilities = [_capability_status(base, capability) for capability in CAPABILITIES]
    probe = (
        run_swarm_scale_probe(probe_config or SwarmScaleProbeConfig())
        if include_probe else _skipped_probe()
    )
    capabilities.extend(_probe_capabilities(probe))

    total_weight = sum(int(item["weight"]) for item in capabilities)
    passed_weight = sum(int(item["weight"]) for item in capabilities if item["passed"])
    score = round(passed_weight / total_weight, 3) if total_weight else 0.0
    missing = [item for item in capabilities if not item["passed"]]
    return {
        "schema": _SCHEMA,
        "score": score,
        "ready": score >= 1.0 and not missing,
        "verdict": "pass" if score >= 1.0 and not missing else "review",
        "passed": len(capabilities) - len(missing),
        "total": len(capabilities),
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "capabilities": capabilities,
        "missing_count": len(missing),
        "probe": probe,
        "next_actions": _next_actions(missing),
        "calibration": {
            "schema": "octopus.swarm_scale_calibration.v1",
            "compares_to": {
                "claude_code": (
                    "custom subagents with isolated context and tool permissions"
                ),
                "kimi_agent_swarm": (
                    "large fan-out, parallel tool use, context sharding, and "
                    "critical-path optimization"
                ),
            },
            "octopus_edge": (
                "bounded local scheduling plus work contracts, owner-scoped "
                "cancellation, observable SSE timelines, and failure isolation"
            ),
        },
    }


def run_swarm_scale_probe(
    config: SwarmScaleProbeConfig | None = None,
) -> dict[str, Any]:
    cfg = config or SwarmScaleProbeConfig()
    task_count = max(2, int(cfg.task_count))
    max_concurrency = max(1, min(int(cfg.max_concurrency), task_count))
    failing_index = int(cfg.failing_task_index)
    if failing_index < 0 or failing_index >= task_count:
        failing_index = task_count - 1

    lock = threading.Lock()
    active = 0
    max_active = 0
    starts: dict[str, float] = {}
    finishes: dict[str, float] = {}

    def runner(
        description: str,
        *,
        subagent_name: str,
        context: dict[str, Any] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        nonlocal active, max_active
        task_id = str((context or {}).get("file_write_owner") or subagent_name)
        with lock:
            active += 1
            max_active = max(max_active, active)
            starts[task_id] = time.monotonic()
        try:
            deadline = time.monotonic() + max(0.0, cfg.sleep_seconds)
            while time.monotonic() < deadline:
                if cancel_event is not None and cancel_event.is_set():
                    return ""
                time.sleep(min(0.002, max(0.0, deadline - time.monotonic())))
            if description.startswith("fail:"):
                raise RuntimeError("intentional_swarm_probe_failure")
            return f"ok:{description}"
        finally:
            with lock:
                finishes[task_id] = time.monotonic()
                active -= 1

    orchestrator = ParallelAgentOrchestrator(
        max_concurrency=max_concurrency,
        task_runner=runner,
    )
    started = time.monotonic()
    try:
        tasks = [
            DispatchTaskInput(
                task_id=f"probe_{index:03d}",
                description=(
                    f"fail:probe-{index}"
                    if index == failing_index else f"probe-{index}"
                ),
                subagent_name=f"probe-agent-{index % max_concurrency}",
            )
            for index in range(task_count)
        ]
        batch = orchestrator.dispatch(tasks)
        final = _wait_for_terminal_batch(
            orchestrator,
            batch.batch_id,
            timeout_seconds=max(0.5, float(cfg.timeout_seconds)),
        )
    finally:
        orchestrator.shutdown(wait=False)

    wall_seconds = max(time.monotonic() - started, 0.000001)
    execution_window_seconds = wall_seconds
    if starts and finishes:
        execution_window_seconds = max(
            max(finishes.values()) - min(starts.values()),
            0.000001,
        )
    configured_serial_estimate = max(
        task_count * max(0.0, cfg.sleep_seconds),
        0.000001,
    )
    observed_serial_work = sum(
        max(finishes[task_id] - starts[task_id], 0.0)
        for task_id in starts.keys() & finishes.keys()
    )
    serial_estimate = max(
        configured_serial_estimate,
        observed_serial_work,
        0.000001,
    )
    critical_path_speedup = serial_estimate / execution_window_seconds
    result_statuses = (
        {item.task_id: item.status for item in final.results}
        if final is not None else {}
    )
    failed_tasks = (
        [item.task_id for item in final.results if item.status == "failed"]
        if final is not None else []
    )
    completed_tasks = (
        [item.task_id for item in final.results if item.status == "completed"]
        if final is not None else []
    )
    event_sequences = (
        [event.sequence for event in final.event_log if event.sequence is not None]
        if final is not None else []
    )
    contiguous_events = event_sequences == list(range(1, len(event_sequences) + 1))
    batch_complete_event = (
        any(event.type == "batch_complete" for event in final.event_log)
        if final is not None else False
    )
    terminal = (
        final is not None
        and final.completed_tasks + final.failed_tasks + final.cancelled_tasks
        == final.total_tasks
    )
    return {
        "schema": _PROBE_SCHEMA,
        "ok": bool(final is not None and terminal),
        "task_count": task_count,
        "max_concurrency": max_concurrency,
        "max_active": max_active,
        "bounded_concurrency": max_active <= max_concurrency,
        "wall_seconds": round(wall_seconds, 4),
        "execution_window_seconds": round(execution_window_seconds, 4),
        "configured_serial_estimate_seconds": round(configured_serial_estimate, 4),
        "observed_serial_work_seconds": round(observed_serial_work, 4),
        "serial_estimate_seconds": round(serial_estimate, 4),
        "critical_path_speedup": round(critical_path_speedup, 3),
        "critical_path_speedup_passed": critical_path_speedup >= cfg.min_speedup,
        "min_speedup": cfg.min_speedup,
        "failure_isolation": (
            len(failed_tasks) == 1
            and failed_tasks[0] == f"probe_{failing_index:03d}"
            and len(completed_tasks) == task_count - 1
        ),
        "failed_tasks": failed_tasks,
        "completed_count": len(completed_tasks),
        "terminal": terminal,
        "status": final.status if final is not None else "timeout",
        "result_statuses": result_statuses,
        "event_log_count": len(final.event_log) if final is not None else 0,
        "event_sequences_contiguous": contiguous_events,
        "batch_complete_event": batch_complete_event,
        "observability": contiguous_events and batch_complete_event,
        "started_count": len(starts),
        "finished_count": len(finishes),
        "batch_metrics": final.batch_metrics if final is not None else {},
        "batch_metrics_ready": _batch_metrics_ready(
            final.batch_metrics if final is not None else {},
        ),
    }


def _wait_for_terminal_batch(
    orchestrator: ParallelAgentOrchestrator,
    batch_id: str,
    *,
    timeout_seconds: float,
) -> Any | None:
    deadline = time.monotonic() + timeout_seconds
    final = None
    while time.monotonic() < deadline:
        final = orchestrator.get_batch(batch_id)
        if final is None:
            return None
        terminal_count = (
            final.completed_tasks + final.failed_tasks + final.cancelled_tasks
        )
        if terminal_count == final.total_tasks:
            return final
        time.sleep(0.005)
    return final


def _probe_capabilities(probe: dict[str, Any]) -> list[dict[str, Any]]:
    if probe.get("skipped"):
        return [
            _dynamic_capability(
                "swarm_probe",
                "Offline swarm-scale probe",
                False,
                "probe skipped",
                weight=5,
            )
        ]
    return [
        _dynamic_capability(
            "large_task_queue_probe",
            "Large bounded task queue probe",
            bool(probe.get("ok") and int(probe.get("task_count") or 0) >= 24),
            "dispatches a 24+ task batch to the bounded scheduler",
            weight=2,
        ),
        _dynamic_capability(
            "bounded_concurrency_probe",
            "Bounded concurrency probe",
            bool(probe.get("bounded_concurrency")),
            "max active workers never exceeds max_concurrency",
            weight=2,
        ),
        _dynamic_capability(
            "critical_path_speedup_probe",
            "Critical-path speedup probe",
            bool(probe.get("critical_path_speedup_passed")),
            "parallel wall time beats the serial estimate by the threshold",
            weight=3,
        ),
        _dynamic_capability(
            "failure_isolation_probe",
            "Failure isolation probe",
            bool(probe.get("failure_isolation")),
            "one failing child does not prevent sibling completion",
            weight=3,
        ),
        _dynamic_capability(
            "observable_timeline_probe",
            "Observable timeline probe",
            bool(probe.get("observability")),
            "event log has contiguous sequences and a batch_complete event",
            weight=2,
        ),
        _dynamic_capability(
            "batch_metrics_probe",
            "Batch metrics and critical path receipt probe",
            bool(probe.get("batch_metrics_ready")),
            "terminal batch exposes schema, speedup, failure isolation, and event continuity",
            weight=2,
        ),
    ]


def _dynamic_capability(
    capability_id: str,
    title: str,
    passed: bool,
    detail: str,
    *,
    weight: int,
) -> dict[str, Any]:
    return {
        "id": capability_id,
        "title": title,
        "path": None,
        "weight": weight,
        "exists": True,
        "passed": passed,
        "required_terms": [],
        "missing_terms": [] if passed else [detail],
        "detail": detail,
    }


def _capability_status(base: Path, capability: SwarmScaleCapability) -> dict[str, Any]:
    path = base / capability.path
    text = _read_text(path).lower() if path.exists() else ""
    missing_terms = [
        term for term in capability.required_terms
        if term.lower() not in text
    ]
    return {
        "id": capability.id,
        "title": capability.title,
        "path": capability.path,
        "weight": capability.weight,
        "exists": path.exists(),
        "passed": path.exists() and not missing_terms,
        "required_terms": list(capability.required_terms),
        "missing_terms": missing_terms,
    }


def _next_actions(missing: list[dict[str, Any]]) -> list[str]:
    actions: list[str] = []
    for item in missing:
        path = item.get("path")
        if path and not item["exists"]:
            actions.append(f"Add {path} for {item['title']}.")
        elif item["missing_terms"]:
            actions.append(
                f"Update {path or item['id']} with "
                f"{', '.join(item['missing_terms'])}."
            )
    return actions


def _skipped_probe() -> dict[str, Any]:
    return {
        "schema": _PROBE_SCHEMA,
        "ok": False,
        "skipped": True,
        "reason": "include_probe=False",
    }


def _batch_metrics_ready(metrics: dict[str, Any]) -> bool:
    return (
        metrics.get("schema") == "octopus.parallel_agent_batch_metrics.v1"
        and float(metrics.get("critical_path_speedup") or 0.0) >= 2.0
        and metrics.get("failure_isolation") is True
        and metrics.get("event_sequences_contiguous") is True
        and int(metrics.get("task_count") or 0) >= 24
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = [
    "CAPABILITIES",
    "SwarmScaleCapability",
    "SwarmScaleProbeConfig",
    "compute_swarm_scale_readiness",
    "run_swarm_scale_probe",
]
