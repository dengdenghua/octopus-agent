"""Per-turn quality scoring + auto-evolution tick helpers.

Extracted from ``tool_bridge.py`` (the Claude-native agentic loop). This
satellite owns the zero-cost heuristic that feeds the SOUL self-evolution
feedback loop: ``_record_score_safe`` writes a best-effort per-turn score
(never raises into the caller), and ``_auto_evolve_tick_safe`` runs the
periodic auto-regression check that auto-reverts a bad lesson.

The parent ``tool_bridge`` module re-exports every name here so existing
importers and tests are unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from datetime import datetime
from threading import Lock
from typing import Any

from runtime.platform.models import ArmId, CostEntry, ParsedIntent, TaskId

from ._tool_bridge_policy import MAX_TOOL_ROUNDS

_logger = logging.getLogger("octopus.agentic")
_NATIVE_TRAJECTORY_FINALIZE_LOCK = Lock()


def _one_scope_value(events: Sequence[Any], field: str) -> str | None:
    """Return one exact non-empty envelope value, rejecting mixed scopes."""

    values = {text for event in events if (text := str(getattr(event, field, None) or "").strip())}
    if len(values) > 1:
        raise ValueError(f"native trajectory spans multiple {field} values")
    return next(iter(values), None)


def _persist_native_trajectory_safe(
    *,
    stack: Any,
    agent: Any,
    intent: ParsedIntent,
    task_id: TaskId,
    success: bool,
    disposition: str,
    step_failures: Mapping[int, str] | None = None,
    step_attempts: Mapping[int, Any] | None = None,
    model_cost: CostEntry | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    _prepared_event_cache: dict[str, Any] | None = None,
    _persistence_state: dict[str, bool] | None = None,
) -> bool:
    """Aggregate one native tool-loop turn into a learnable trajectory.

    Native tool calls already cross :class:`ToolExecutor`, which writes an
    exact ``StepEvent`` for every invocation. Historically each invocation
    received a fresh task id, so regeneration could not recover the ordered
    multi-step turn and saw no terminal trajectory. The caller now supplies
    one task id for the whole turn; this helper gathers those executor
    receipts and appends the terminal aggregate.

    The write is best-effort and idempotent for a task id. Learning must never
    make the user-facing response fail, and a resumed/finalized generator must
    not append the same trajectory twice.
    """

    try:
        from runtime.memory.journal import StepEvent, TrajectoryEvent
        from runtime.platform.models import Trajectory, TrajectoryOutcome

        if _persistence_state is not None:
            _persistence_state["durable"] = False

        journal = getattr(stack, "journal", None) or getattr(
            getattr(stack, "executor", None),
            "journal",
            None,
        )
        if (
            journal is None
            or not hasattr(journal, "read_by_task")
            or not hasattr(journal, "write_trajectory_once")
        ):
            return False

        # Personal/confidential turns are useful to the active conversation but
        # must never become process-global regeneration material.
        if getattr(intent, "privacy", "internal") in {"personal", "confidential"}:
            return False

        prepared_event = (
            _prepared_event_cache.get("event") if _prepared_event_cache is not None else None
        )
        if isinstance(prepared_event, TrajectoryEvent):
            inserted = bool(journal.write_trajectory_once(prepared_event))
            if _persistence_state is not None:
                # False is the durable idempotent "already committed" result;
                # transaction/conflict failures raise and are handled below.
                _persistence_state["durable"] = True
            return inserted

        failures = {
            int(key): str(value or "native_tool_error")
            for key, value in (step_failures or {}).items()
        }
        attempts = {int(key): value for key, value in (step_attempts or {}).items()}
        with _NATIVE_TRAJECTORY_FINALIZE_LOCK:
            events = list(journal.read_by_task(task_id))
            step_events = [event for event in events if isinstance(event, StepEvent)]

            step_ids = [event.step.step_id for event in step_events]
            if len(step_ids) != len(set(step_ids)):
                raise ValueError("native trajectory contains duplicate step ids")

            steps = []
            for event in step_events:
                step = event.step
                failure_type = failures.get(step.step_id)
                # Some handlers historically returned ``{ok: false}`` after the
                # executor had already journalled a successful Step. Preserve the
                # bridge's canonical result in the learnable aggregate so the UI,
                # failure miner and SkillForge do not disagree about the attempt.
                if failure_type and (step.success or failure_type == "cancelled"):
                    error_type = (
                        "cancelled"
                        if failure_type == "cancelled"
                        else step.result.error_type or failure_type
                    )
                    stderr_tags = list(step.result.stderr_tags)
                    if failure_type not in stderr_tags:
                        stderr_tags.append(failure_type)
                    result = step.result.model_copy(
                        update={
                            "status": "failed",
                            "error_type": error_type,
                            "stderr_tags": stderr_tags,
                        }
                    )
                    step = step.model_copy(update={"result": result})
                steps.append(step)

            # Registry/preflight denials and execution-before-start
            # cancellations intentionally never cross ToolExecutor, so there
            # is no StepEvent to aggregate.  Preserve each such attempt as a
            # bounded synthetic failed Step in the terminal trajectory rather
            # than dropping an all-negative turn from the audit/learning set.
            from runtime.platform.models import ExecutionResult, SkillId, Step
            from runtime.platform.models import ToolCall as ExecutionToolCall

            recorded_step_ids = {step.step_id for step in steps}
            for step_id, failure_type in failures.items():
                if step_id in recorded_step_ids:
                    continue
                attempt = attempts.get(step_id)
                if attempt is None:
                    continue
                name = str(
                    getattr(attempt, "name", None)
                    or getattr(attempt, "tool", None)
                    or getattr(attempt, "sucker_id", None)
                    or "invalid_native_tool"
                )
                raw_args = getattr(attempt, "input", None)
                if raw_args is None:
                    raw_args = getattr(attempt, "arguments", None)
                if raw_args is None:
                    raw_args = getattr(attempt, "args", None)
                args = dict(raw_args) if isinstance(raw_args, Mapping) else {}
                provider_call_id = str(
                    getattr(attempt, "id", None) or getattr(attempt, "call_id", None) or step_id
                )
                action = ExecutionToolCall(
                    caller="agentic",
                    sucker_id=SkillId(name),
                    args=args,
                )
                steps.append(
                    Step(
                        step_id=step_id,
                        node_id=f"agentic:{provider_call_id}",
                        action=action,
                        result=ExecutionResult(
                            call_id=action.call_id,
                            status="failed",
                            output={"error": failure_type},
                            error_type=failure_type,
                            stderr_tags=["native_bridge_preflight", failure_type],
                            trusted_execution=False,
                            execution_source="native_bridge_preflight",
                        ),
                    )
                )
            if not steps:
                return False
            steps.sort(key=lambda step: step.step_id)

            total_cost = model_cost or CostEntry()
            for step in steps:
                total_cost = total_cost + step.result.cost

            from runtime.platform.process.session import current_session

            session = current_session()
            context = intent.user_context or {}
            session_metadata = getattr(session, "metadata", None) or {}

            # Executor StepEvent envelopes are the authoritative source. The
            # active server-owned Session and intent values are compatibility
            # fallbacks for direct/CLI callers that do not bind journal_context.
            thread_id = (
                _one_scope_value(step_events, "conversation_id")
                or str(
                    getattr(session, "thread_id", None)
                    or getattr(session, "conversation_id", None)
                    or context.get("thread_id")
                    or context.get("conversation_id")
                    or ""
                ).strip()
                or None
            )
            agent_id = (
                _one_scope_value(step_events, "agent_id")
                or str(
                    getattr(session, "agent_id", None) or getattr(agent, "agent_id", None) or ""
                ).strip()
                or None
            )
            tenant_id = (
                _one_scope_value(step_events, "tenant_id")
                or str(session_metadata.get("tenant_id") or context.get("tenant_id") or "").strip()
                or None
            )
            owner_actor_id = (
                _one_scope_value(step_events, "owner_actor_id")
                or str(
                    session_metadata.get("owner_actor_id") or context.get("owner_actor_id") or ""
                ).strip()
                or None
            )
            actor = (
                _one_scope_value(step_events, "actor")
                or str(getattr(session, "actor", None) or owner_actor_id or "").strip()
                or None
            )

            degraded = bool(failures) or any(not step.success for step in steps)
            terminal_disposition = disposition
            if success and degraded and disposition == "completed":
                terminal_disposition = "completed_with_warning"

            arm_id = ArmId("agentic")
            trajectory = Trajectory(
                task_id=task_id,
                thread_id=thread_id,
                arm_id=arm_id,
                strategy_id="native_tool_loop",
                steps=steps,
                outcome=TrajectoryOutcome(
                    success=success,
                    cost=total_cost,
                    degraded=degraded,
                    disposition=terminal_disposition,
                ),
                started_at=started_at or min(step.action.ts for step in steps),
                completed_at=completed_at or max(step.ts for step in steps),
            )
            prepared_event = TrajectoryEvent(
                task_id=task_id,
                arm_id=arm_id,
                actor=actor,
                tenant_id=tenant_id,
                owner_actor_id=owner_actor_id,
                agent_id=agent_id,
                conversation_id=thread_id,
                trajectory=trajectory,
            )
            if _prepared_event_cache is not None:
                _prepared_event_cache["event"] = prepared_event

        # Never hold the process-wide preparation lock across the durable
        # write: StreamingJournal invokes subscribers after commit, and a
        # subscriber is allowed to perform idempotent re-entrant persistence.
        inserted = bool(journal.write_trajectory_once(prepared_event))
        if _persistence_state is not None:
            _persistence_state["durable"] = True
        return inserted
    except Exception:  # noqa: BLE001 — learning telemetry must never break the reply
        _logger.debug("native trajectory persist skipped", exc_info=True)
        return False


def _record_score_safe(
    *,
    agent: Any,
    intent: ParsedIntent,
    has_final_reply: bool,
    tool_error_count: int,
    rounds_used: int,
    duration_ms: int,
    interrupted: bool = False,
) -> None:
    """Best-effort score record · never raises into the caller.

    Uses the heuristic ``score_turn_outcome`` so this function
    itself doesn't make any LLM calls — zero token cost.
    """
    try:
        from runtime.platform.process.session import current_session
        from runtime.safety.recovery.tenant_scope import (
            trusted_scope_from_session,
            trusted_scope_from_user_context,
        )

        agent_id = getattr(agent, "agent_id", "") if agent else ""
        if not agent_id:
            return
        thread_id = (
            getattr(intent, "thread_id", None) or getattr(intent, "conversation_id", None) or ""
        )
        # The private context marker is stamped by the transport boundary.
        # The active Session is the trusted compatibility carrier for OpenAI,
        # CLI and worker paths that do not expose that marker to the intent.
        scope = trusted_scope_from_user_context(intent.user_context)
        if scope is None:
            scope = trusted_scope_from_session(current_session())
        _record_engine_neutral_score_safe(
            agent_id=agent_id,
            has_final_reply=has_final_reply,
            tool_error_count=tool_error_count,
            rounds_used=rounds_used,
            interrupted=interrupted,
            duration_ms=duration_ms,
            thread_id=thread_id,
            turn_id=str(getattr(current_session(), "turn_id", None) or ""),
            scope=scope,
        )
    except (ImportError, AttributeError, OSError, ValueError):  # noqa: BLE001 — scoring is observability; failure must never block reply
        # Scoring is observability · a failure must NEVER affect
        # the user's reply. Swallow + move on.
        pass


def _record_engine_neutral_score_safe(
    *,
    agent_id: str,
    has_final_reply: bool,
    tool_error_count: int = 0,
    rounds_used: int = 0,
    duration_ms: int = 0,
    interrupted: bool = False,
    thread_id: str = "",
    turn_id: str = "",
    scope: Any = None,
) -> None:
    """Persist one score for *any* execution provider.

    The native ReAct loop used to own both scoring and the auto-evolution
    tick.  That made Codex turns invisible to learning even though they pass
    through the same realtime lifecycle.  Keeping this small, provider
    neutral writer here lets native and Codex share the exact same heuristic,
    idempotent turn id and tenant scope without importing either execution
    loop into the learning package.
    """

    try:
        from runtime.memory.learning.turn_scoring import (
            record_turn_score,
            score_turn_outcome,
        )

        if not agent_id:
            return
        score, reason = score_turn_outcome(
            has_final_reply=has_final_reply,
            tool_error_count=tool_error_count,
            rounds_used=rounds_used,
            rounds_max=MAX_TOOL_ROUNDS,
            interrupted=interrupted,
            duration_ms=duration_ms,
        )
        record_turn_score(
            agent_id=agent_id,
            score=score,
            reason=reason,
            rounds=rounds_used,
            duration_ms=duration_ms,
            thread_id=thread_id,
            turn_id=turn_id,
            scope=scope,
        )
        # Auto-evolution tick · every 5 turns run the zero-cost regression
        # heuristic; a provider must not get a free pass simply because its
        # execution loop lives outside the native bridge.
        _auto_evolve_tick_safe(agent_id, scope=scope)
    except (ImportError, AttributeError, OSError, ValueError):  # noqa: BLE001
        # Learning is observability. A broken score file or optional module
        # must never turn a successful user task into a failed one.
        pass


def _record_codex_turn_score_safe(*, turn: Any, agent: Any = None) -> None:
    """Feed a completed Codex turn into the shared learning score stream.

    Codex owns the inner tool loop, so it cannot provide Native's round
    counter or ``StepEvent`` list.  The public realtime items are still a
    durable, provider-neutral receipt: final answer presence, failed tool
    items, lifecycle status and wall time are enough for the same coarse
    quality signal. Fine-grained trajectories are handled separately by the
    execution trace store.
    """

    try:
        from datetime import UTC, datetime

        from runtime.platform.process.session import current_session
        from runtime.protocol import AgentMessageItem
        from runtime.safety.auth.scope import TenantScope
        from runtime.safety.recovery.tenant_scope import trusted_scope_from_session
        from runtime.sensing.gateway.realtime_turn_input import _agent_id_from_params

        params = getattr(turn, "params", None)
        agent_id = str(
            getattr(agent, "agent_id", None)
            or getattr(turn, "execution_agent_id", None)
            or (_agent_id_from_params(params) if params is not None else "")
            or ""
        ).strip()
        if not agent_id:
            return

        items = list(getattr(turn, "items", None) or [])
        final_reply = any(
            isinstance(item, AgentMessageItem)
            and str(getattr(item, "message_kind", "answer") or "answer") == "answer"
            and bool(str(getattr(item, "text", "") or "").strip())
            and str(getattr(getattr(item, "status", None), "value", getattr(item, "status", "")))
            in {"completed", "complete"}
            for item in items
        )
        tool_types = {"commandExecution", "fileChange", "mcpToolCall", "subagent"}
        tool_error_count = sum(
            1
            for item in items
            if str(getattr(getattr(item, "type", None), "value", getattr(item, "type", "")))
            in tool_types
            and str(getattr(getattr(item, "status", None), "value", getattr(item, "status", "")))
            in {"failed", "error"}
        )
        status = str(
            getattr(getattr(turn, "status", None), "value", getattr(turn, "status", ""))
            or ""
        ).lower()
        interrupted = status in {"cancelled", "canceled", "interrupted", "paused"}
        started_at = getattr(turn, "started_at", None)
        completed_at = getattr(turn, "completed_at", None) or datetime.now(UTC)
        duration_ms = 0
        if started_at is not None:
            try:
                duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
            except (TypeError, ValueError):
                duration_ms = 0

        scope = trusted_scope_from_session(current_session())
        if scope is None and params is not None:
            tenant_id = str(getattr(params, "tenant_id", None) or "").strip()
            owner_actor_id = str(getattr(params, "owner_actor_id", None) or "").strip()
            if bool(tenant_id) != bool(owner_actor_id):
                # A partial private identity is an integrity failure. Do not
                # fall back to the unscoped score file.
                return
            if tenant_id and owner_actor_id:
                scope = TenantScope(tenant_id=tenant_id, actor_id=owner_actor_id)

        thread_id = str(getattr(turn, "thread_id", None) or "")
        tool_rounds = sum(
            1
            for item in items
            if str(
                getattr(getattr(item, "type", None), "value", getattr(item, "type", ""))
            )
            in tool_types
        )
        _record_engine_neutral_score_safe(
            agent_id=agent_id,
            has_final_reply=final_reply,
            tool_error_count=tool_error_count,
            rounds_used=max(1, tool_rounds),
            duration_ms=duration_ms,
            interrupted=interrupted,
            thread_id=thread_id,
            turn_id=str(getattr(turn, "id", None) or ""),
            scope=scope,
        )
    except (ImportError, AttributeError, OSError, TypeError, ValueError):  # noqa: BLE001
        _logger.debug("codex turn score skipped", exc_info=True)


def _auto_evolve_tick_safe(
    agent_id: str,
    *,
    every: int = 5,
    min_total: int = 15,
    scope: Any = None,
) -> None:
    """Every ``every`` turns, run an auto-regression check.

    Fail-closed: any exception is swallowed · this is behind the
    user's reply and must never affect it. Cost is ~2ms file read
    + the ``analyze_soul_impact`` pure math; only LLM cost if
    ``_auto_regression_check`` escalates (it doesn't — it's
    heuristic-only).

    Args:
        every: how often to tick. Default 5 = every 5 turns.
        min_total: minimum total scores before ticking at all.
            Default 15 = 10 baseline + 5 post-change minimum.
    """
    try:
        from runtime.memory.learning.turn_scoring import read_recent_scores

        scores = read_recent_scores(
            agent_id,
            limit=max(min_total * 2, 40),
            scope=scope,
        )
        if len(scores) < min_total or len(scores) % every != 0:
            return
        # Import lazily so this tick stays optional (skill module
        # can fail to load without breaking the scoring path).
        from pathlib import Path

        # Temporarily set _agent_core_dir since we're outside a
        # Session context (the skill uses it internally).
        import runtime.execution.suckers.memory_skills as _m
        from runtime.execution.suckers.memory_skills import _auto_regression_check

        original = _m._agent_core_dir
        _m._agent_core_dir = lambda: Path("agents") / agent_id / "agent-core"
        try:
            res = _auto_regression_check(
                window=20,
                drop_threshold=0.2,
                min_samples=5,
                dry_run=False,
                _scope=scope,
            )
            action = res.get("action")
            if action == "reverted":
                _logger.info(
                    "auto-evolve tick · agent=%s reverted SOUL (delta=%s)",
                    agent_id,
                    (res.get("analysis") or {}).get("delta"),
                )
        finally:
            _m._agent_core_dir = original
    except (ImportError, AttributeError, OSError):  # noqa: BLE001 — agent_core_dir reset best-effort
        pass
