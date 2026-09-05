"""Runtime wiring for cowork background tasks.

This module turns the cowork data model into a live service: one shared group
store, one shared async-task store, and a runner that dispatches tasks through
the existing subagent bridge. The HTTP router can use the same stores, so
``POST /api/cowork/*/tasks`` feeds the background runner instead of a separate
queue instance.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from runtime.memory.cowork.async_runner import AsyncWorkRunner
from runtime.memory.cowork.async_work import AsyncTask, AsyncWorkStore
from runtime.memory.cowork.collaboration_store import CollaborationStore
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.nominate import CompetenceStore

_LOG = logging.getLogger("octopus.cowork.runtime")


def _positive_env_int(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


def _nonnegative_env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass
class CoworkRuntime:
    group_store: GroupStore
    async_store: AsyncWorkStore
    collaboration_store: CollaborationStore
    runner: AsyncWorkRunner | None = None
    runner_enabled: bool = False
    runner_reason: str = "disabled"
    thread_store: Any | None = None
    collector_retention: dict[str, Any] | None = None

    def start(self, *, poll_seconds: float = 5.0) -> None:
        if self.runner is not None:
            self.runner.start(poll_seconds=poll_seconds)

    def stop(self, timeout: float = 5.0) -> None:
        if self.runner is not None:
            self.runner.stop(timeout=timeout)

    def status(self, thread_id: str | None = None) -> dict[str, Any]:
        runner_status = self.runner.status() if self.runner is not None else None
        return {
            "runner_enabled": self.runner_enabled,
            "runner_reason": self.runner_reason,
            "runner_status": runner_status,
            "task_counts": self.async_store.counts(thread_id),
            "queue_health": (
                self.async_store.queue_health(thread_id) if thread_id is not None else None
            ),
            "collector_retention": self.collector_retention,
        }


def create_cowork_runtime(
    *,
    base_dir: Any = None,
    thread_store: Any = None,
    enable_runner: bool = True,
) -> CoworkRuntime:
    """Build the shared cowork runtime used by app wiring and tests."""
    group_store = GroupStore(base_dir=base_dir)
    async_store = AsyncWorkStore(
        base_dir=group_store.base_dir,
        group_store=group_store,
        max_active_per_thread=_positive_env_int(
            "OCTOPUS_COWORK_QUEUE_PER_THREAD_LIMIT",
            512,
        ),
        max_active_total=_positive_env_int("OCTOPUS_COWORK_QUEUE_TOTAL_LIMIT", 4096),
    )
    collaboration_store = CollaborationStore(base_dir=group_store.base_dir)
    retention_result: dict[str, Any] = {"archived": 0, "run_ids": []}
    try:
        retention_result = collaboration_store.apply_collaboration_collector_retention(
            ttl_seconds=_nonnegative_env_int(
                "OCTOPUS_COWORK_COLLECTOR_RETENTION_SECONDS",
                90 * 24 * 60 * 60,
            ),
            max_collectors_per_session=_nonnegative_env_int(
                "OCTOPUS_COWORK_COLLECTOR_RETENTION_COUNT",
                1000,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - retention must not block startup
        retention_result = {
            "archived": 0,
            "run_ids": [],
            "error": f"{type(exc).__name__}: {exc}",
        }
        _LOG.warning("cowork collector retention failed: %s", exc, exc_info=True)
    runner: AsyncWorkRunner | None = None
    runner_enabled, runner_reason = _subagent_execution_available()
    if enable_runner and runner_enabled:
        runner = AsyncWorkRunner(
            async_store,
            group_store,
            lambda task, context: _execute_subagent_task(
                task,
                context,
                collaboration_store=collaboration_store,
            ),
            competence=CompetenceStore(base_dir=group_store.base_dir),
            history_provider=_history_provider(thread_store),
            completion_observer=_collector_completion_observer(collaboration_store),
            max_concurrency=_positive_env_int(
                "OCTOPUS_COWORK_RUNNER_MAX_CONCURRENCY",
                4,
            ),
            max_tasks_per_tick=_positive_env_int(
                "OCTOPUS_COWORK_RUNNER_MAX_TASKS_PER_TICK",
                64,
            ),
        )
    elif not enable_runner:
        runner_reason = "runner disabled by app configuration"
    return CoworkRuntime(
        group_store=group_store,
        async_store=async_store,
        collaboration_store=collaboration_store,
        runner=runner,
        runner_enabled=runner is not None,
        runner_reason=runner_reason,
        thread_store=thread_store,
        collector_retention=retention_result,
    )


def _subagent_execution_available() -> tuple[bool, str]:
    try:
        from runtime.execution.subagents import get_sub_agent_runner
        from runtime.execution.suckers.ephemeral_agents import (
            get_ephemeral_role_runner,
        )

        if get_sub_agent_runner() is not None:
            return True, "persistent subagent runner configured"
        runner = get_ephemeral_role_runner()
        if getattr(runner, "__name__", "") != "_null_ephemeral_runner":
            return True, "ephemeral subagent runner configured"
        return False, "subagent runner not configured"
    except Exception as exc:  # noqa: BLE001
        return False, f"subagent runner probe failed: {type(exc).__name__}: {exc}"


def _history_provider(thread_store: Any):
    def _history(thread_id: str) -> list[Any]:
        if thread_store is None:
            return []
        get_state = getattr(thread_store, "get_state", None)
        if not callable(get_state):
            return []
        try:
            state = get_state(thread_id)
        except Exception as exc:  # noqa: BLE001
            _LOG.debug("cowork history lookup failed for %s: %s", thread_id, exc)
            return []
        values = state.get("values") if isinstance(state, dict) else None
        messages = values.get("messages") if isinstance(values, dict) else None
        return messages if isinstance(messages, list) else []

    return _history


def _execute_subagent_task(
    task: AsyncTask,
    context: dict[str, Any],
    *,
    collaboration_store: CollaborationStore | None = None,
) -> str:
    from runtime.execution.subagents import call_subagent

    binding = (
        collaboration_store.collaboration_collector_retry_task(task.task_id)
        if collaboration_store is not None
        else None
    )
    steering_cursor = 0

    def drain_steering() -> list[str]:
        nonlocal steering_cursor
        if collaboration_store is None or binding is None:
            return []
        rows = collaboration_store.collaboration_collector_steering(
            str(binding["run_id"]),
            child_id=str(binding["child_id"]),
            generation=int(binding["generation"]),
            after_seq=steering_cursor,
        )
        if rows:
            steering_cursor = max(int(row.get("seq") or 0) for row in rows)
        return [str(row.get("text") or "").strip() for row in rows if row.get("text")]

    corrections = drain_steering()
    base_prompt = task.prompt
    prompt = base_prompt
    if corrections:
        prompt += (
            "\n\n<user-steering>Apply these newer user corrections before completing:\n"
            + "\n".join(f"- {text}" for text in corrections)
            + "\n</user-steering>"
        )
    result: dict[str, Any] = {}
    continuation_id: str | None = None
    for restart in range(3):
        result = call_subagent(
            task.assignee,
            prompt,
            context={
                "thread_id": task.thread_id,
                "parent_task_id": task.task_id,
                "source": "cowork_async_task",
                "cowork": context,
                "steering_drain": drain_steering,
            },
            timeout_s=900,
            timeout_seconds=900.0,
            continue_session_id=continuation_id,
        )
        arrived_during_call = drain_steering()
        if not arrived_during_call:
            break
        corrections.extend(arrived_during_call)
        prompt = base_prompt + (
            "\n\n<user-steering>Apply these newer user corrections before completing:\n"
            + "\n".join(f"- {text}" for text in corrections)
            + "\n</user-steering>"
        )
        continuation_id = str(result.get("session_id") or "").strip() or None
        if restart == 2:
            raise RuntimeError("member steering restart limit exceeded; retry the member")
    if not result.get("success"):
        raise RuntimeError(str(result.get("error") or "subagent failed"))
    output = result.get("output")
    if output is None:
        parsed = result.get("parsed")
        if parsed is not None:
            output = parsed
    return str(output or "")


def _collector_completion_observer(collaboration_store: CollaborationStore):
    """Project a retry task's terminal outcome back into its collector lane."""

    def observe(task: AsyncTask, success: bool, result: str) -> None:
        binding = collaboration_store.collaboration_collector_retry_task(task.task_id)
        if binding is None:
            return
        collaboration_store.record_collaboration_collector_result(
            binding["run_id"],
            child_id=binding["child_id"],
            status="success" if success else "failed",
            result={
                "task_id": task.task_id,
                "agent_id": task.assignee,
                "reply": result[:60_000] if success else "",
                "error": "" if success else result[:4_000],
                "source": "cowork_async_retry",
            },
            expected_generation=int(binding["generation"]),
        )

    return observe


__all__ = ["CoworkRuntime", "create_cowork_runtime"]
