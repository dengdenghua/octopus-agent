"""PHASE 1-2 turn bootstrap: entry guards + router / native-gate resolution.

Leaf of the prompt-assembly split. Re-exported by ``react_prompt_assembly.py``
so ``react_loop.py``'s ``from ...react_prompt_assembly import _resolve_turn_bootstrap``
keeps working. Never imports ``react_loop``.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from runtime.core.cerebrum.react_browser_iteration import (
    _browser_operation_requested,
    _ensure_browser_operation_skills,
)
from runtime.core.cerebrum.react_explicit_reads import (
    _explicit_no_tool_goal,
    _explicit_observed_read_sequence,
    _explicit_read_only_goal,
)
from runtime.core.cerebrum.react_guards import _explicit_source_paths

_logger = logging.getLogger(__name__)


@dataclass
class _TurnBootstrap:
    """Products of the PHASE 1-2 turn bootstrap (entry guards / gating)."""

    router: Any
    reasoning_effort: Any
    no_tool_turn: bool
    executor: Any
    tools_active: bool
    effective_model: str
    native_mode: bool
    strict_explicit_reads: bool
    ordered_result_handoffs: bool
    native_public_update_tool_specs: list
    native_evidence_update_tool_specs: list
    react_task_id: Any
    camouflage_suffix: str


def _resolve_turn_bootstrap(
    stack: Any,
    intent: Any,
    agent: Any,
    *,
    model: str | None,
    enable_tools: bool,
    reasoning_effort: str | None,
    approval_provider: Any,
    resume_task_id: Any,
) -> _TurnBootstrap | None:
    """Entry guards + router/native-gate resolution (PHASE 1-2).

    Moved verbatim from ``react_loop.stream_react_loop``. Returns
    ``None`` when the stack exposes no router (the original early
    ``return None``); the caller aborts the turn in that case.
    """
    router = getattr(getattr(stack, "planner", None), "router", None)
    if router is None:
        _logger.warning("react_loop: stack.planner.router 不可用,无法进入 ReAct")
        return None

    from runtime.platform.models.llm import normalize_reasoning_effort

    _reasoning_effort = normalize_reasoning_effort(reasoning_effort)

    # Planning mode used to disable tool execution outright (the
    # model produced a plan, the user approved, then a follow-up turn
    # re-ran with ``planning_mode=false``). That hard-stop confused
    # users — the UI shows nothing happening and ``Action: web_search``
    # falls through to the "(未执行观察) 本次 ReAct 未启用工具执行"
    # placeholder. Updated semantics (2026-05-31): planning_mode keeps
    # tool execution ON; the system prompt simply nudges the model to
    # write/update plan.md first before substantial tool work. The
    # ``exit_plan_mode`` skill flow is still available for explicit
    # human-in-the-loop approval, but auto-detection no longer strands
    # the turn in plan-only territory.
    _no_tool_turn = _explicit_no_tool_goal(
        str(getattr(intent, "normalized_goal", "") or getattr(intent, "raw", "") or "")
    )
    executor = getattr(stack, "executor", None) if enable_tools and not _no_tool_turn else None
    tools_active = executor is not None
    # Explicit Browser turns must register their dependency-gated local tools
    # before native ToolSpecs are frozen below.  Registering later only changes
    # the text catalog; function-calling models would still be unable to call
    # the browser tools and tend to fall back to desktop automation.
    if tools_active and _browser_operation_requested(intent.user_context):
        _ensure_browser_operation_skills(executor)

    # Resolve the model up-front (was computed later) so the native
    # tool-use gate can be decided before the system prompt is built.
    effective_model = (
        model
        if model and model not in ("octopus-agent", "")
        else getattr(stack.planner, "planner_model", None) or "auto"
    )

    # ── Native tool-use gate (Phase 0) ─────────────────────────────────
    # For tool-use-capable models, drive the loop via native ``tool_calls``
    # instead of the text ``Action: name({...})`` protocol — eliminating the
    # single biggest brittleness source (regex-parsing the action out of free
    # text). Gated by ``OCTOPUS_NATIVE_TOOLUSE`` (default off) AND the model's
    # advertised capability; otherwise the text protocol + its regex fallback
    # run byte-identically to before. Specs are built once per turn.
    from runtime.core.cerebrum.react_native import (
        build_loop_tool_specs,
        native_tool_use_active,
        require_public_update_on_tool_specs,
    )

    _native_mode = bool(tools_active) and native_tool_use_active(router, effective_model)
    _native_goal = getattr(intent, "normalized_goal", "") or getattr(intent, "raw", "") or ""
    _strict_explicit_reads = bool(
        _explicit_read_only_goal(_native_goal)
        and _explicit_source_paths(_native_goal)
        and not _browser_operation_requested(intent.user_context)
    )
    _ordered_result_handoffs = bool(
        len(_explicit_source_paths(_native_goal)) > 1
        and _explicit_observed_read_sequence(_native_goal)
    )
    _native_observed_read_sequence = bool(_strict_explicit_reads and _ordered_result_handoffs)
    _native_tool_specs = (
        build_loop_tool_specs(
            executor,
            agent=agent,
            goal=_native_goal,
            user_context=intent.user_context,
            strict_explicit_reads=_strict_explicit_reads,
        )
        if _native_mode
        else []
    )
    if _native_mode and not _native_tool_specs:
        # Spec build came back empty — nothing to call natively, so stay on
        # the proven text protocol rather than passing an empty tools list.
        _native_mode = False
    _native_public_update_tool_specs = (
        require_public_update_on_tool_specs(_native_tool_specs)
        if (
            _native_mode
            and bool(
                (intent.user_context or {}).get("realtime_public_orientation")
                or (intent.user_context or {}).get("realtime_public_narrative")
                or _native_observed_read_sequence
            )
        )
        else _native_tool_specs
    )
    _native_evidence_update_tool_specs = (
        require_public_update_on_tool_specs(
            _native_tool_specs,
            evidence_round=True,
        )
        if _native_public_update_tool_specs is not _native_tool_specs
        else _native_tool_specs
    )

    # Expose the live approval provider through the session so the
    # ``exit_plan_mode`` skill can issue an interactive approval
    # request without re-plumbing the param through every layer.
    try:
        from runtime.platform.process.session import current_session as _cs_for_provider

        _session_for_provider = _cs_for_provider()
        if (
            _session_for_provider is not None
            and _session_for_provider.metadata is not None
            and approval_provider is not None
        ):
            _session_for_provider.metadata["_approval_provider"] = approval_provider
    except (ImportError, AttributeError):  # noqa: BLE001 — session layer optional in tests
        pass

    # ── PHASE 2 · mode + budget detection ──────────────────────────────
    from runtime.platform.models import TaskId as _TaskId

    react_task_id: _TaskId = resume_task_id if resume_task_id is not None else _TaskId(uuid.uuid4())

    _camouflage_variant_name = "baseline"
    _camouflage_suffix = ""
    try:
        from runtime.safety.experiments.scheduler import (
            get_camouflage_scheduler,
        )

        _camouflage_variant_name, _camouflage_suffix = (
            get_camouflage_scheduler().assign_variant_suffix(str(react_task_id))
        )
    except ImportError:
        _logger.debug("camouflage scheduler not available", exc_info=True)
    return _TurnBootstrap(
        router=router,
        reasoning_effort=_reasoning_effort,
        no_tool_turn=_no_tool_turn,
        executor=executor,
        tools_active=tools_active,
        effective_model=effective_model,
        native_mode=_native_mode,
        strict_explicit_reads=_strict_explicit_reads,
        ordered_result_handoffs=_ordered_result_handoffs,
        native_public_update_tool_specs=_native_public_update_tool_specs,
        native_evidence_update_tool_specs=_native_evidence_update_tool_specs,
        react_task_id=react_task_id,
        camouflage_suffix=_camouflage_suffix,
    )
