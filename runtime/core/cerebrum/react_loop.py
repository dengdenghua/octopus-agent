from __future__ import annotations

import contextlib
import logging
import re
import time
import uuid
from collections.abc import Callable, Generator
from typing import TYPE_CHECKING, Any

from runtime.core.cerebrum.react_action_outcomes import (
    _action_batch_fingerprint,
    _deduplicate_actions,
    _per_action_outcomes,
    _retry_safe_affinity,
    _tool_call_succeeded,
)
from runtime.core.cerebrum.react_browser_iteration import (
    _browser_operation_requested,
    _browser_task_iteration_limit,
    _code_task_iteration_limit,
    _ensure_browser_operation_skills,
    _narrow_research_iteration_limit,
)
from runtime.core.cerebrum.react_checkpointing import (
    _auto_checkpoint_and_evaluate_step,
    _checkpoint_interval,
    _checkpoint_mirror,
    _mirror_checkpoint,
    _rehydrate_messages_from_steps,
    _reset_checkpoint_mirror_for_tests,
    _should_auto_checkpoint,
)
from runtime.core.cerebrum.react_context import (
    _build_code_agent_mode_prompt,
    _build_code_context_prelude,
    _build_personal_agent_mode_prompt,
    _build_project_signals_prompt,
    _build_user_message_content,
    _build_workflow_preset_prompt,
    _compress_context,
    _format_skill_catalog,
    _image_blocks_from_attachments,
    _looks_like_image_attachment,
    _serialize_messages_for_checkpoint,
    context_budget_tokens_for_model,
)
from runtime.core.cerebrum.react_convergence import (
    EvidenceConvergence,
)
from runtime.core.cerebrum.react_execution import (
    _background_task_info_from_observation,
    _beak_step_effective_success,
    _build_progress_summary,
    _build_research_progress_summary,
    _detect_phase,
    _execute_action_via_beak,
    _format_background_task_heartbeat,
    _has_unrecovered_beak_failure,
    _is_scoped_artifact_write,
    _normalized_tool_call_from_react_action,
    _persist_react_trajectory,
    _phase_6d_dispatch_and_observe,
    _react_completion_receipt,
    _reset_kg_throttle_for_tests,
    _skill_available_in_executor,
    _tool_event_extras_from_beak_step,
    _update_working_set,
)
from runtime.core.cerebrum.react_explicit_reads import (
    _explicit_no_tool_goal,
    _explicit_observed_read_sequence,
    _explicit_read_only_goal,
    _recover_explicit_read_actions,
)
from runtime.core.cerebrum.react_final_answer_guards import (
    _final_answer_needs_pre_emit_guard,
    _guard_reason_for_user,
    _note_guard_impasse,
    _phase_6e_guards_and_step_emit,
    _record_rejected_step,
    _unfinished_implementation_recovery_needed,
)
from runtime.core.cerebrum.react_guards import (
    _code_mode_completion_guard,
    _completion_phrase_without_todo_guard,
    _explicit_source_paths,
    _failed_verification_followup_guard,
    _goal_requests_code_mutation,
    _redundant_green_verification_guard,
    _unverified_write_followup_guard,
)
from runtime.core.cerebrum.react_in_flight_nudges import (
    _apply_in_flight_nudges,
)
from runtime.core.cerebrum.react_loop_controls import (
    _CONTEXT_PRESSURE_NUDGE,
    _cancel_pause_guard,
    _disabled_guard_labels,
    _disabled_guards_from_yaml,
    _estimate_context_fullness,
    _guard_hit_recorder,
    _long_task_budget_limits,
    _reset_disabled_set_for_tests,
    _reset_guard_telemetry_for_tests,
    _reset_react_variants_for_tests,
    get_react_variant_stats,
    pick_react_variant,
    record_react_variant_result,
)
from runtime.core.cerebrum.react_loop_state import (
    _LoopControl,
    _LoopState,
)
from runtime.core.cerebrum.react_model_deadlines import (
    _MODEL_STREAM_DEADLINE,
    _collect_model_stream_text_with_deadline,
    _finish_reason_is_length_limited,
    _iter_model_stream_with_deadline,
    _model_evidence_synthesis_timeout_s,
    _model_iteration_timeout_s,
    _model_post_tool_timeout_s,
    _model_recovery_timeout_s,
    _stage_update_timeout_fallback,
)
from runtime.core.cerebrum.react_model_stream import _phase_6b_model_stream
from runtime.core.cerebrum.react_parallel_dispatch import (
    _WRITE_TOOLS,
    _dispatch_parallel_actions,
)
from runtime.core.cerebrum.react_parsing import (
    _escape_md_brackets,
    _extract_final_answer,
    _is_format_violation,
    _looks_like_special_tool_envelope,
    _looks_like_unfinished_work,
    _parse_action,
    _parse_reasoning_action_fallback,
    _parse_step,
    _placeholder_observation,
    _safe_for_streamdown,
    _summarize_observation,
)
from runtime.core.cerebrum.react_phase_6c import (
    _phase_6c_parse_and_guard,
)
from runtime.core.cerebrum.react_prompt_assembly import _assemble_prompt_and_messages
from runtime.core.cerebrum.react_public_updates import (
    _initial_public_fallback_update,
    _observed_read_fallback_update,
    _runtime_fallback_public_update,
    _safe_public_update,
    _stream_public_evidence_narrative,
)
from runtime.core.cerebrum.react_quiet_evidence import (
    _quiet_evidence_checkpoint_due,
    _quiet_evidence_targets,
    _result_checkpoint_is_meaningful,
    _should_accumulate_quiet_evidence,
)
from runtime.core.cerebrum.react_resume import (
    _build_resume_context_prompt,
    _compute_resume_state,
    _ResumeState,
)
from runtime.core.cerebrum.react_terminal import (
    _finalize_react_turn,
)
from runtime.core.cerebrum.react_types import (
    REACT_OBSERVATION_FOLLOWUP,
    ReActResult,
    ReActStep,
    _native_tool_calls_missing_required_args,
)
from runtime.core.cerebrum.todo_protocol import (
    _todo_completion_before_write_guard,
    _todo_prewrite_guard,
)
from runtime.platform.config.builder import StackProtocol
from runtime.platform.models import ParsedIntent, Step, TaskId
from runtime.safety.approval.approval_gate import ApprovalProvider
from runtime.safety.validation.prompt_injection import (
    mark_injection_taint,
    reset_injection_taint,
    set_injection_gate_handled,
)
from runtime.sensing.model_router.rescue_policy import (
    next_custom_model_fallback,
)

if TYPE_CHECKING:
    from runtime.execution.agents.base import Agent

_logger = logging.getLogger(__name__)


# Re-exports for tests/test_react_loop.py and friends — the helpers live
# in react_parsing / react_execution / react_guards / react_context /
# react_checkpointing / react_loop_controls / react_parallel_dispatch /
# react_terminal / react_in_flight_nudges now, but tests (and the loop
# body below) reference them through this
# module. Listing them in __all__ keeps ruff from auto-removing the
# imports as "unused".
__all__ = [
    "_background_task_info_from_observation",
    "_beak_step_effective_success",
    "_build_code_agent_mode_prompt",
    "_build_code_context_prelude",
    "_build_personal_agent_mode_prompt",
    "_build_project_signals_prompt",
    "_build_resume_context_prompt",
    "_build_user_message_content",
    "_browser_task_iteration_limit",
    "_build_workflow_preset_prompt",
    "_checkpoint_interval",
    "_checkpoint_mirror",
    "_code_mode_completion_guard",
    "_code_task_iteration_limit",
    "_collect_model_stream_text_with_deadline",
    "_completion_phrase_without_todo_guard",
    "_CONTEXT_PRESSURE_NUDGE",
    "_disabled_guard_labels",
    "_disabled_guards_from_yaml",
    "_dispatch_parallel_actions",
    "_escape_md_brackets",
    "_estimate_context_fullness",
    "_execute_action_via_beak",
    "_extract_final_answer",
    "_failed_verification_followup_guard",
    "_final_answer_needs_pre_emit_guard",
    "_finalize_react_turn",
    "_finish_reason_is_length_limited",
    "_format_background_task_heartbeat",
    "_format_skill_catalog",
    "_goal_requests_code_mutation",
    "_guard_hit_recorder",
    "_guard_reason_for_user",
    "_has_unrecovered_beak_failure",
    "_image_blocks_from_attachments",
    "_is_format_violation",
    "_is_scoped_artifact_write",
    "_iter_model_stream_with_deadline",
    "_long_task_budget_limits",
    "_looks_like_image_attachment",
    "_looks_like_special_tool_envelope",
    "_looks_like_unfinished_work",
    "_mirror_checkpoint",
    "_narrow_research_iteration_limit",
    "_model_evidence_synthesis_timeout_s",
    "_model_post_tool_timeout_s",
    "_model_recovery_timeout_s",
    "_MODEL_STREAM_DEADLINE",
    "_native_tool_calls_missing_required_args",
    "_normalized_tool_call_from_react_action",
    "_note_guard_impasse",
    "_observed_read_fallback_update",
    "_parse_action",
    "_parse_reasoning_action_fallback",
    "_parse_step",
    "_persist_react_trajectory",
    "_placeholder_observation",
    "_quiet_evidence_targets",
    "_react_completion_receipt",
    "_record_rejected_step",
    "_recover_explicit_read_actions",
    "_redundant_green_verification_guard",
    "_rehydrate_messages_from_steps",
    "_reset_checkpoint_mirror_for_tests",
    "_reset_disabled_set_for_tests",
    "_reset_guard_telemetry_for_tests",
    "_reset_kg_throttle_for_tests",
    "_reset_react_variants_for_tests",
    "_ResumeState",
    "_runtime_fallback_public_update",
    "_safe_for_streamdown",
    "_safe_public_update",
    "_should_auto_checkpoint",
    "_skill_available_in_executor",
    "_stage_update_timeout_fallback",
    "_summarize_observation",
    "_todo_completion_before_write_guard",
    "_todo_prewrite_guard",
    "_tool_event_extras_from_beak_step",
    "_unfinished_implementation_recovery_needed",
    "_unverified_write_followup_guard",
    "_WRITE_TOOLS",
    "get_react_variant_stats",
    "pick_react_variant",
    "ReActResult",
    "ReActStep",
    "record_react_variant_result",
    "run_react_loop",
    "stream_react_loop",
]


def stream_react_loop(
    stack: StackProtocol,
    intent: ParsedIntent,
    agent: Agent | None,
    *,
    model: str | None = None,
    max_iterations: int = 30,
    temperature: float = 0.3,
    enable_tools: bool = True,
    resume_task_id: TaskId | None = None,
    thread_id: str = "",
    max_tokens_budget: int = 50000,
    max_usd_budget: float = 0.5,
    approval_provider: ApprovalProvider | None = None,
    output_chunk_sink: Callable[[str, str, str], None] | None = None,
    step_evaluator: Callable[[dict[str, Any]], float | None] | None = None,
    planning_mode: bool = False,
    reasoning_effort: str | None = None,
    steering_drain: Callable[[], list[str]] | None = None,
) -> Generator[dict[str, Any], None, ReActResult | None]:
    # ╔══════════════════════════════════════════════════════════════════╗
    # ║ stream_react_loop · navigation map (comment-only; do not split). ║
    # ║                                                                  ║
    # ║   PHASE 1 · entry guards / router resolution     (this section)  ║
    # ║   PHASE 2 · mode + budget detection              ~L611           ║
    # ║   PHASE 3 · system + volatile prompt assembly    ~L629           ║
    # ║   PHASE 4 · message bootstrap + start yield      ~L1370          ║
    # ║   PHASE 5 · pre-loop state init + resume         ~L1495          ║
    # ║   PHASE 6 · main iteration loop                  ~L1629          ║
    # ║       6a · cancel / pause guard                  ~L1630          ║
    # ║       6b · LLM call + Final-Answer anchor stream ~L1700          ║
    # ║       6c · parse step / format-violation         ~L1952          ║
    # ║       6d · action dispatch + observation         ~L2079          ║
    # ║       6e · nudges + guards + step yield          ~L2509          ║
    # ║       6f · auto-checkpoint + step evaluator      ~L2606          ║
    # ║       6g · housekeeping (msg append / continue)  ~L2698          ║
    # ║   PHASE 7 · post-loop terminal handling          ~L2884          ║
    # ║       (pause / cancel / forced max-iter convergence)             ║
    # ║   PHASE 8 · finalization + react_completed yield ~L2993          ║
    # ║                                                                  ║
    # ║ Why one big function: ~25 closure vars shared across phases +    ║
    # ║ interleaved yield points (this is a generator) + checkpoint/     ║
    # ║ resume coupling make phase extraction semantics-changing. The    ║
    # ║ side-effect-free pieces (guards, resume-state compute, final-    ║
    # ║ answer checks) are ALREADY extracted as module-level helpers     ║
    # ║ above; what remains is the coupled core, kept intact on purpose. ║
    # ╚══════════════════════════════════════════════════════════════════╝

    # ── PHASE 1 · entry guards / router resolution ─────────────────────
    router = getattr(getattr(stack, "planner", None), "router", None)
    if router is None:
        _logger.warning("react_loop: stack.planner.router 不可用,无法进入 ReAct")
        return None

    from runtime.platform.models.llm import (
        Message,
        normalize_reasoning_effort,
    )

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

    react_task_id: TaskId = resume_task_id if resume_task_id is not None else _TaskId(uuid.uuid4())

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

    # ── PHASE 3 · system + volatile prompt assembly ────────────────────
    _assembly = _assemble_prompt_and_messages(
        intent=intent,
        agent=agent,
        stack=stack,
        executor=executor,
        approval_provider=approval_provider,
        resume_task_id=resume_task_id,
        planning_mode=planning_mode,
        tools_active=tools_active,
        native_mode=_native_mode,
        no_tool_turn=_no_tool_turn,
        strict_explicit_reads=_strict_explicit_reads,
        camouflage_suffix=_camouflage_suffix,
        max_iterations=max_iterations,
        max_tokens_budget=max_tokens_budget,
        max_usd_budget=max_usd_budget,
    )
    messages = _assembly.messages
    max_iterations = _assembly.max_iterations
    _metadata = _assembly.metadata
    _effective_wp = _assembly.effective_wp
    _is_goal_mode = _assembly.is_goal_mode
    _is_code_mode = _assembly.is_code_mode
    _browser_operation_mode = _assembly.browser_operation_mode
    _todo_protocol_required = _assembly.todo_protocol_required
    _todo_protocol_visible = _assembly.todo_protocol_visible
    _file_inspection_tools_visible = _assembly.file_inspection_tools_visible
    _read_only_turn = _assembly.read_only_turn
    _observed_read_sequence = _assembly.observed_read_sequence
    _final_guard_grounded_source_paths = _assembly.final_guard_grounded_source_paths
    _guard_impasse_state = _assembly.guard_impasse_state
    _budget_auto_pause_enabled = _assembly.budget_auto_pause_enabled
    _budget_pause_threshold = _assembly.budget_pause_threshold
    _realtime_public_orientation_requested = _assembly.realtime_public_orientation_requested
    _grounding_sources = _assembly.grounding_sources
    _is_swarm_mode = _assembly.is_swarm_mode
    _is_research_mode = _assembly.is_research_mode
    _active_max_tokens_budget = _assembly.active_max_tokens_budget
    _active_max_usd_budget = _assembly.active_max_usd_budget

    # ── PHASE 4 · message bootstrap done; emit react_started ───────────
    yield {
        "type": "react_started",
        "task_id": str(react_task_id),
        "thread_id": thread_id or None,
        "max_iterations": max_iterations,
    }

    # Surface the codebase docs/chunks we actually grounded this turn on, so
    # the UI can show a plain-language "consulted N project docs" chip. Faithful
    # by construction: these are the exact sources folded into the prompt above.
    if _grounding_sources:
        yield {
            "type": "codebase_grounding",
            "sources": _grounding_sources,
        }

    # ── PHASE 4.5 · agent auto-delegation short-circuit ────────────────
    # When the user prompt has a single, unambiguous @agent: pin AND no
    # competing routing signals, we can save one full LLM round trip by
    # delegating directly. The plan only fires when ALL of these hold:
    #   - tools_active (delegation is a tool path)
    #   - not planning_mode (plan mode wants the model to think first)
    #   - the prompt passes plan_auto_delegation's heuristics
    #   - the executor's registry has the call_agent skill
    # On success, we inject the subagent's output as an Observation-style
    # user message so the next LLM turn synthesizes the final answer
    # against real evidence rather than re-planning the delegation.
    _auto_delegated = False
    if tools_active and not planning_mode:
        try:
            from runtime.core.cerebrum.agent_auto_delegate import (
                plan_auto_delegation,
            )

            _delegation_plan = plan_auto_delegation(
                intent.normalized_goal,
                registry=getattr(executor, "agent_registry", None)
                or getattr(stack, "agent_registry", None)
                or getattr(executor, "registry", None),
            )
        except (ImportError, AttributeError, TypeError):
            _delegation_plan = None
        if (
            _delegation_plan is not None
            and _delegation_plan.should_delegate
            and _skill_available_in_executor(executor, "call_agent")
        ):
            try:
                from runtime.execution.subagents.bridge import call_subagent

                _logger.info(
                    "react_loop auto-delegating to agent=%s reason=%s",
                    _delegation_plan.target_agent,
                    _delegation_plan.reason,
                )
                yield {
                    "type": "auto_delegation_started",
                    "target_agent": _delegation_plan.target_agent,
                    "reason": _delegation_plan.reason,
                }
                _delegate_result = call_subagent(
                    agent_id=_delegation_plan.target_agent or "",
                    prompt=_delegation_plan.cleaned_prompt,
                    context={
                        "thread_id": thread_id or "",
                        "source": "auto_delegation",
                        "parent_task_id": str(react_task_id),
                    },
                    timeout_s=120,
                )
                _delegate_output = str(
                    _delegate_result.get("output", "") or "",
                ).strip()
                _delegate_ok = bool(_delegate_result.get("success", False))
                if _delegate_ok and _delegate_output:
                    # Inject as a synthetic Observation so the model's
                    # next turn writes the Final Answer directly.
                    obs_block = (
                        "<auto-delegation-observation>\n"
                        f"Auto-delegated to @agent:{_delegation_plan.target_agent}.\n"
                        f"Reason: {_delegation_plan.reason}.\n"
                        f"Subagent output:\n\n{_delegate_output}\n"
                        "</auto-delegation-observation>\n\n"
                        "Use this as the primary evidence for your Final "
                        "Answer. Add your own synthesis or follow-up only "
                        "if the user's request demands more than the "
                        "subagent's output already covers."
                    )
                    messages.append(Message(role="user", content=obs_block))
                    _auto_delegated = True
                    yield {
                        "type": "auto_delegation_completed",
                        "target_agent": _delegation_plan.target_agent,
                        "output_length": len(_delegate_output),
                    }
                else:
                    err = str(_delegate_result.get("error", "") or "")
                    _logger.info(
                        "auto-delegation produced no usable output "
                        "(success=%s, error=%s) — falling back to model",
                        _delegate_ok,
                        err,
                    )
                    yield {
                        "type": "auto_delegation_skipped",
                        "target_agent": _delegation_plan.target_agent,
                        "reason": err or "no output",
                    }
            except (ImportError, AttributeError, TypeError, ValueError) as exc:
                _logger.debug(
                    "auto-delegation failed; falling back to model: %s",
                    exc,
                    exc_info=True,
                )
                yield {
                    "type": "auto_delegation_skipped",
                    "target_agent": getattr(
                        _delegation_plan,
                        "target_agent",
                        None,
                    ),
                    "reason": f"{type(exc).__name__}: {exc}",
                }

    # ── PHASE 5 · pre-loop state init + checkpoint resume ──────────────
    from runtime.core.cerebrum.pause_control import get_pause_controller

    _pause = get_pause_controller()
    _agent_id_for_pause = str(getattr(agent, "agent_id", "") or "")
    _pause.register_active(
        str(react_task_id),
        thread_id=thread_id or "",
        agent_id=_agent_id_for_pause,
        max_iterations=max_iterations,
        max_tokens=_active_max_tokens_budget,
        max_usd=_active_max_usd_budget,
    )

    steps: list[ReActStep] = []
    executed_beak_steps: list[Step] = []
    # Clear any prompt-injection taint from a prior turn in this context,
    # then INHERIT the spawning parent's taint when this loop is a subagent
    # spun up in a fresh thread/context (the taint contextvar doesn't cross
    # the thread-pool boundary, so the parent passes it explicitly via the
    # intent). Without this, delegating a risky action to a subagent would
    # wash the taint clean.
    reset_injection_taint()
    # Also clear the gate-handled flag. It is a per-thread contextvar that the
    # single-action approval gate sets True around execute() to tell the
    # executor chokepoint "this call was already reviewed". When a subagent is
    # spawned INLINE in the parent's thread (call_subagent with the default
    # timeout_seconds=None), it would otherwise inherit the parent's True and
    # the subagent's OWN risky tools (e.g. via its parallel path) would skip
    # the chokepoint without any approval round. A fresh loop has reviewed
    # nothing yet, so reset it like the taint.
    set_injection_gate_handled(False)
    _inherited_taint = intent.user_context.get("_inherited_injection_taint")
    if isinstance(_inherited_taint, str) and _inherited_taint not in ("", "none"):
        mark_injection_taint(_inherited_taint)
    final_answer: str | None = None
    final_answer_segments: list[str] = []
    final_answer_emitted = False
    terminated_reason = "max_iter"
    resume_from_iter = 0

    # Throughput sampler — chars/sec across all delta yields. We emit a
    # ``throughput`` event every ~500ms so the UI can show a live
    # tokens-per-second indicator without flooding the WebSocket. Chars
    # are a useful proxy: at the cost of being model-dependent, they
    # don't require a tokenizer in the hot path.
    _throughput_started_at = time.monotonic()
    _throughput_chars = 0
    _throughput_last_emit = _throughput_started_at
    _throughput_interval_s = 0.5

    _working_set: dict[str, dict[str, Any]] = {}
    _progress_summary = ""
    _current_phase = "understand"
    _known_background_tasks: dict[str, dict[str, Any]] = {}
    _resume_event: dict[str, Any] | None = None

    if resume_task_id is not None:
        try:
            _rs = _compute_resume_state(
                stack,
                intent,
                resume_task_id,
                base_messages=messages,
                base_working_set=_working_set,
                base_progress_summary=_progress_summary,
                base_current_phase=_current_phase,
                max_iterations=max_iterations,
            )
            if _rs is not None:
                resume_from_iter = _rs.resume_from_iter
                messages = _rs.messages
                steps = _rs.steps
                _working_set = _rs.working_set
                _progress_summary = _rs.progress_summary
                _current_phase = _rs.current_phase
                final_answer = _rs.final_answer
                terminated_reason = _rs.terminated_reason
                react_task_id = resume_task_id
                _resume_event = _rs.resume_event
        except (AttributeError, KeyError, TypeError, ValueError):
            _logger.debug("resume checkpoint loading failed", exc_info=True)

    if _resume_event is not None:
        yield _resume_event

    consecutive_format_violations = 0
    consecutive_llm_errors = 0
    _last_public_update_key = ""
    _result_handoff_ready = False
    _realtime_public_narrative = bool(intent.user_context.get("realtime_public_narrative"))
    _realtime_public_orientation = _realtime_public_orientation_requested
    _quiet_evidence_steps: list[ReActStep] = []
    _force_convergence_next = False
    _green_verification_convergence_active = False
    _green_convergence_todo_used = False
    _evidence_convergence_active: EvidenceConvergence | None = None
    # Persistent execution-state evidence. Recomputing green rounds from the
    # whole trajectory is useful as a fallback, but long turns can decorate
    # old observations with recovery nudges. Track clean verifier rounds at
    # the point tools actually finish so a red→fixed→green trajectory reaches
    # a stable terminal state instead of cycling through verify/todo forever.
    _saw_successful_code_write = False
    _clean_verification_rounds_after_write = 0
    _last_failed_action_fingerprint = ""
    _consecutive_same_failed_actions = 0
    _model_timeout_recoveries = 0
    # Allow two consecutive zero-anchor rounds before bailing. The
    # first violation is often a model warming up — it dumps a chunk
    # of plain markdown / JSON before remembering to use the
    # ``Action:`` anchor. Setting this to 1 used to terminate the
    # loop on the very first round, killing tool work that would have
    # happened on round 2. Two rounds tolerates the warmup but still
    # bails fast when the model genuinely cannot follow ReAct format.
    _format_violation_bail_at = 2
    _context_pressure_signaled: bool = False

    def _append_pending_live_steering() -> int:
        if steering_drain is None:
            return 0
        try:
            pending = steering_drain()
        except Exception:  # noqa: BLE001 — live steering must not break the turn
            _logger.warning("live steering poll failed", exc_info=True)
            return 0
        from runtime.core.cerebrum.live_steering import (
            append_live_steering_messages,
        )

        count = append_live_steering_messages(messages, pending)
        if count:
            _logger.info(
                "react_loop accepted %d priority user follow-up(s) at a safe boundary",
                count,
            )
        return count

    from runtime.platform.models.llm import (
        model_supports_thinking as _supports_thinking,
    )

    _resolved_model = effective_model
    if hasattr(router, "_resolve"):
        try:
            _sub = router._resolve(effective_model)
            if _sub is not router:
                _resolved_model = getattr(_sub, "default_model", None) or effective_model
        except (AttributeError, TypeError):  # noqa: BLE001 — subrouter doesn't expose default_model; fall back to effective_model
            pass
    _wants_thinking = _supports_thinking(_resolved_model)
    # Per-iteration ``max_tokens`` ceiling. Non-thinking models used to
    # cap at 2000 tokens, which is fine for a chatty back-and-forth but
    # truncates long-form generation mid-sentence — research reports
    # are typically 4-6k tokens of markdown and were getting cut at
    # ~2k char before the model could reach the conclusion. The model
    # then read the finish_reason as "length" and (without the
    # continuation logic below) decided the task was done, emitting a
    # short summary instead of resuming. 8k is enough for a single
    # report section; the continuation path catches anything longer.
    _max_tokens_per_iter = 4096 if _wants_thinking else 8000
    _attempted_models = {effective_model}
    _model_failovers = 0

    def _switch_react_model(next_model: str) -> None:
        """Retarget later rounds while preserving this turn's evidence."""

        nonlocal effective_model, _max_tokens_per_iter, _resolved_model, _wants_thinking
        effective_model = next_model
        _resolved_model = next_model
        if hasattr(router, "_resolve"):
            try:
                _subrouter = router._resolve(next_model)
                if _subrouter is not router:
                    _resolved_model = getattr(_subrouter, "default_model", None) or next_model
            except (AttributeError, TypeError):
                pass
        _wants_thinking = _supports_thinking(_resolved_model)
        _max_tokens_per_iter = 4096 if _wants_thinking else 8000

    def _try_react_model_failover(reason: str) -> str | None:
        nonlocal _model_failovers
        if _model_failovers >= 1:
            return None
        next_model = next_custom_model_fallback(
            effective_model,
            _attempted_models,
            require_tool_use=_native_mode,
        )
        if not next_model:
            return None
        previous_model = effective_model
        _switch_react_model(next_model)
        _attempted_models.add(next_model)
        _model_failovers += 1
        _logger.warning(
            "react_loop switching model %s -> %s after %s",
            previous_model,
            next_model,
            reason,
        )
        return next_model

    if resume_task_id is not None:
        _grant = _pause.consume_grant(str(resume_task_id))
        _extra_iters = int(_grant.get("extra_iterations") or 0)
        if _extra_iters > 0:
            max_iterations = max_iterations + _extra_iters
            _logger.info(
                "react_loop resume grant: +%d iterations for task %s (new max=%d)",
                _extra_iters,
                resume_task_id,
                max_iterations,
            )
        _pause.clear(str(resume_task_id))

    # Realtime reasoning providers may stream private thinking for minutes
    # before producing ordinary text or a tool call. The UI must not depend on
    # that hidden stream for its first conversational beat. Generate one
    # task-specific, model-authored sentence through the bounded,
    # thinking-disabled narrator before starting the expensive working call.
    # This is deliberately gateway-gated so batch/API callers keep their
    # existing request count and latency.
    if (
        bool((intent.user_context or {}).get("realtime_public_preface"))
        and _realtime_public_orientation
        and tools_active
        and not _no_tool_turn
        and resume_from_iter == 0
        and not steps
    ):
        try:
            _initial_public_update = yield from _stream_public_evidence_narrative(
                router,
                model=effective_model,
                goal=intent.normalized_goal,
                step=ReActStep(iteration=0),
                convergence=None,
                iteration=0,
                previous_key=_last_public_update_key,
                pending_action=True,
            )
        except Exception as exc:  # noqa: BLE001 — optional first-public-beat repair
            _logger.warning("initial public orientation failed: %s", exc)
            _initial_public_update = ""
        if not _initial_public_update:
            _initial_public_update = _initial_public_fallback_update(intent.normalized_goal)
            if _initial_public_update:
                yield {
                    "type": "commentary_delta",
                    "delta": _initial_public_update,
                    "progress_source": "runtime",
                    "public_status": True,
                    "start_new_segment": True,
                    "iteration": 0,
                }
        if _initial_public_update:
            _last_public_update_key = re.sub(r"\s+", " ", _initial_public_update).strip().casefold()

    # ── _LoopState assembly (Wave 2) ─────────────────────────────────
    # Reference-typed fields share objects with the locals above;
    # constant scalars are snapshotted here and per-iteration scalars
    # are synced at each extracted-phase call site (currently 6c).
    state = _LoopState(
        stack=stack,
        goal=intent.normalized_goal,
        executor=executor,
        react_task_id=react_task_id,
        pause_controller=_pause,
        effective_wp=_effective_wp,
        format_violation_bail_at=_format_violation_bail_at,
        final_guard_grounded_source_paths=_final_guard_grounded_source_paths,
        guard_impasse_state=_guard_impasse_state,
        intent=intent,
        agent=agent,
        thread_id=thread_id,
        approval_provider=approval_provider,
        output_chunk_sink=output_chunk_sink,
        router=router,
        metadata=_metadata,
        is_goal_mode=_is_goal_mode,
        observed_read_sequence=_observed_read_sequence,
        ordered_result_handoffs=_ordered_result_handoffs,
        realtime_public_orientation=_realtime_public_orientation,
        realtime_public_narrative=_realtime_public_narrative,
        is_code_mode=_is_code_mode,
        browser_operation_mode=_browser_operation_mode,
        todo_protocol_required=_todo_protocol_required,
        todo_protocol_visible=_todo_protocol_visible,
        file_inspection_tools_visible=_file_inspection_tools_visible,
        read_only_turn=_read_only_turn,
        no_tool_turn=_no_tool_turn,
        steps=steps,
        executed_beak_steps=executed_beak_steps,
        messages=messages,
        working_set=_working_set,
        effective_model=effective_model,
        current_phase=_current_phase,
        consecutive_same_failed_actions=_consecutive_same_failed_actions,
        last_failed_action_fingerprint=_last_failed_action_fingerprint,
        green_verification_convergence_active=_green_verification_convergence_active,
        green_convergence_todo_used=_green_convergence_todo_used,
        result_handoff_ready=_result_handoff_ready,
        last_public_update_key=_last_public_update_key,
        saw_successful_code_write=_saw_successful_code_write,
        clean_verification_rounds_after_write=_clean_verification_rounds_after_write,
        quiet_evidence_steps=_quiet_evidence_steps,
        native_mode=_native_mode,
        throughput_chars=_throughput_chars,
        temperature=temperature,
        max_tokens_per_iter=_max_tokens_per_iter,
        wants_thinking=_wants_thinking,
        reasoning_effort=_reasoning_effort,
        native_evidence_update_tool_specs=_native_evidence_update_tool_specs,
        native_public_update_tool_specs=_native_public_update_tool_specs,
        budget_auto_pause_enabled=_budget_auto_pause_enabled,
        budget_pause_threshold=_budget_pause_threshold,
        agent_id_for_pause=_agent_id_for_pause,
        throughput_started_at=_throughput_started_at,
        throughput_interval_s=_throughput_interval_s,
        throughput_last_emit=_throughput_last_emit,
        consecutive_llm_errors=consecutive_llm_errors,
        terminated_reason=terminated_reason,
        final_answer=final_answer,
        final_answer_emitted=final_answer_emitted,
    )

    for i in range(resume_from_iter, max_iterations):
        # ── PHASE 6a · cancel / pause guard ────────────────────────────
        _guard_terminated_reason = yield from _cancel_pause_guard(
            iteration=i,
            react_task_id=react_task_id,
            max_iterations=max_iterations,
            stack=stack,
            messages=messages,
            steps=steps,
            working_set=_working_set,
            progress_summary=_progress_summary,
            current_phase=_current_phase,
            pause_controller=_pause,
            append_pending_live_steering=_append_pending_live_steering,
        )
        if _guard_terminated_reason is not None:
            terminated_reason = _guard_terminated_reason
            break

        # ── PHASE 6b · LLM call + Final-Answer anchor stream ───────────
        state.native_mode = _native_mode
        state.evidence_convergence_active = _evidence_convergence_active
        state.effective_model = effective_model
        state.force_convergence_next = _force_convergence_next
        state.last_public_update_key = _last_public_update_key
        state.throughput_chars = _throughput_chars
        state.throughput_last_emit = _throughput_last_emit
        # final_stream_started / streamed_final_chars /
        # final_delta_emitted_this_iteration are reset unconditionally
        # inside the phase each iteration — write-only, no sync-in.
        state.terminated_reason = terminated_reason
        state.consecutive_llm_errors = consecutive_llm_errors
        state.model_failovers = _model_failovers

        def _try_failover_for_6b(reason: str) -> str | None:
            # Same closure bridge as _try_failover_for_6c: the loop's
            # failover closure reads ``_native_mode`` and bumps
            # ``_model_failovers`` via nonlocal; mirror both through
            # state so the phase observes the same values the inline
            # code used to see. ``next_custom_model_fallback`` keeps
            # resolving through the react_loop module global.
            nonlocal _native_mode
            _native_mode = state.native_mode
            _fallback = _try_react_model_failover(reason)
            state.model_failovers = _model_failovers  # noqa: B023 — called immediately, same iteration
            return _fallback

        _loop_ctrl = yield from _phase_6b_model_stream(
            state,
            i=i,
            model_iteration_timeout_s=_model_iteration_timeout_s,
            try_react_model_failover=_try_failover_for_6b,
        )
        _force_convergence_next = state.force_convergence_next
        _last_public_update_key = state.last_public_update_key
        _throughput_chars = state.throughput_chars
        _throughput_last_emit = state.throughput_last_emit
        _final_stream_started = state.final_stream_started
        _streamed_final_chars = state.streamed_final_chars
        _final_delta_emitted_this_iteration = state.final_delta_emitted_this_iteration
        terminated_reason = state.terminated_reason
        consecutive_llm_errors = state.consecutive_llm_errors
        _model_failovers = state.model_failovers
        resp = state.resp
        raw_text = state.raw_text
        _request_has_tool_evidence = state.request_has_tool_evidence
        _iteration_soft_timed_out = state.iteration_soft_timed_out
        _maybe_emit_throughput = state.maybe_emit_throughput
        if _loop_ctrl is _LoopControl.RETURN_NONE:
            return None
        if _loop_ctrl is _LoopControl.BREAK:
            break
        if _loop_ctrl is _LoopControl.NEXT_ITERATION:
            continue

        # ── PHASE 6c · parse step / format-violation check ─────────────
        # Sync per-iteration scalars into state; the phase pulls/pushes
        # them internally and the write-set is synced back below.
        state.native_mode = _native_mode
        state.evidence_convergence_active = _evidence_convergence_active
        state.model_timeout_recoveries = _model_timeout_recoveries
        state.model_failovers = _model_failovers
        state.final_stream_started = _final_stream_started
        state.force_convergence_next = _force_convergence_next
        state.tools_active = tools_active
        state.consecutive_format_violations = consecutive_format_violations
        state.throughput_chars = _throughput_chars
        state.final_answer = final_answer
        state.terminated_reason = terminated_reason
        state.final_answer_emitted = final_answer_emitted
        state.final_delta_emitted_this_iteration = _final_delta_emitted_this_iteration

        def _try_failover_for_6c(reason: str) -> str | None:
            # The failover closure reads the loop's ``_native_mode`` and
            # bumps ``_model_failovers`` via nonlocal; mirror both through
            # state so the phase observes the same values the inline code
            # used to see. ``next_custom_model_fallback`` keeps resolving
            # through the react_loop module global (tests patch it there).
            nonlocal _native_mode
            _native_mode = state.native_mode
            _fallback = _try_react_model_failover(reason)
            state.model_failovers = _model_failovers  # noqa: B023 — called immediately, same iteration
            return _fallback

        _loop_ctrl = yield from _phase_6c_parse_and_guard(
            state,
            resp=resp,
            raw_text=raw_text,
            i=i,
            request_has_tool_evidence=_request_has_tool_evidence,
            iteration_soft_timed_out=_iteration_soft_timed_out,
            try_react_model_failover=_try_failover_for_6c,
            maybe_emit_throughput=_maybe_emit_throughput,
        )
        _native_mode = state.native_mode
        _model_timeout_recoveries = state.model_timeout_recoveries
        _final_stream_started = state.final_stream_started
        _force_convergence_next = state.force_convergence_next
        consecutive_format_violations = state.consecutive_format_violations
        _throughput_chars = state.throughput_chars
        final_answer = state.final_answer
        terminated_reason = state.terminated_reason
        final_answer_emitted = state.final_answer_emitted
        _final_delta_emitted_this_iteration = state.final_delta_emitted_this_iteration
        step = state.step
        maybe_final = state.maybe_final
        text = state.text
        _length_limited = state.length_limited
        _length_limit_should_continue = state.length_limit_should_continue
        if _loop_ctrl is _LoopControl.RETURN_NONE:
            return None
        if _loop_ctrl is _LoopControl.BREAK:
            break
        # ── PHASE 6d · action dispatch + observation ───────────────────
        state.maybe_final = maybe_final
        state.terminated_reason = terminated_reason
        state.evidence_convergence_active = _evidence_convergence_active
        state.force_convergence_next = _force_convergence_next
        state.tools_active = tools_active
        state.effective_model = effective_model
        state.current_phase = _current_phase
        state.consecutive_same_failed_actions = _consecutive_same_failed_actions
        state.last_failed_action_fingerprint = _last_failed_action_fingerprint
        state.green_verification_convergence_active = _green_verification_convergence_active
        state.green_convergence_todo_used = _green_convergence_todo_used
        state.result_handoff_ready = _result_handoff_ready
        state.last_public_update_key = _last_public_update_key
        state.saw_successful_code_write = _saw_successful_code_write
        state.clean_verification_rounds_after_write = _clean_verification_rounds_after_write
        state.quiet_evidence_steps = _quiet_evidence_steps
        _loop_ctrl = yield from _phase_6d_dispatch_and_observe(
            state,
            i=i,
            dispatch_parallel_actions=_dispatch_parallel_actions,
            write_tools=_WRITE_TOOLS,
            result_checkpoint_is_meaningful=_result_checkpoint_is_meaningful,
            should_accumulate_quiet_evidence=_should_accumulate_quiet_evidence,
            quiet_evidence_checkpoint_due=_quiet_evidence_checkpoint_due,
            action_batch_fingerprint=_action_batch_fingerprint,
            deduplicate_actions=_deduplicate_actions,
            per_action_outcomes=_per_action_outcomes,
            retry_safe_affinity=_retry_safe_affinity,
            tool_call_succeeded=_tool_call_succeeded,
        )
        maybe_final = state.maybe_final
        terminated_reason = state.terminated_reason
        _evidence_convergence_active = state.evidence_convergence_active
        _force_convergence_next = state.force_convergence_next
        _consecutive_same_failed_actions = state.consecutive_same_failed_actions
        _last_failed_action_fingerprint = state.last_failed_action_fingerprint
        _green_verification_convergence_active = state.green_verification_convergence_active
        _green_convergence_todo_used = state.green_convergence_todo_used
        _result_handoff_ready = state.result_handoff_ready
        _last_public_update_key = state.last_public_update_key
        _saw_successful_code_write = state.saw_successful_code_write
        _clean_verification_rounds_after_write = state.clean_verification_rounds_after_write
        _quiet_evidence_steps = state.quiet_evidence_steps
        if _loop_ctrl is _LoopControl.RETURN_NONE:
            return None
        if _loop_ctrl is _LoopControl.BREAK:
            break
        if _loop_ctrl is _LoopControl.NEXT_ITERATION:
            continue

        # ── PHASE 6e · in-flight nudges ────────────────────────────────
        (
            _context_pressure_signaled,
            _green_verification_convergence_active,
            _force_convergence_next,
        ) = _apply_in_flight_nudges(
            steps=steps,
            step=step,
            i=i,
            known_background_tasks=_known_background_tasks,
            todo_protocol_required=_todo_protocol_required,
            todo_protocol_visible=_todo_protocol_visible,
            is_code_mode=_is_code_mode,
            messages=messages,
            effective_model=effective_model,
            context_pressure_signaled=_context_pressure_signaled,
            green_verification_convergence_active=_green_verification_convergence_active,
            force_convergence_next=_force_convergence_next,
        )

        # ── PHASE 6e · guards + step yield ────────────────────────────
        state.maybe_final = maybe_final
        state.final_stream_started = _final_stream_started
        state.force_convergence_next = _force_convergence_next
        state.final_delta_emitted_this_iteration = _final_delta_emitted_this_iteration
        state.green_verification_convergence_active = _green_verification_convergence_active
        state.green_convergence_todo_used = _green_convergence_todo_used
        state.clean_verification_rounds_after_write = _clean_verification_rounds_after_write
        state.final_answer = final_answer
        state.terminated_reason = terminated_reason
        state.evidence_convergence_active = _evidence_convergence_active
        state.tools_active = tools_active
        state.current_phase = _current_phase
        state.streamed_final_chars = _streamed_final_chars
        state.progress_summary = _progress_summary
        _loop_ctrl = yield from _phase_6e_guards_and_step_emit(
            state,
            i=i,
            append_pending_live_steering=_append_pending_live_steering,
            build_research_progress_summary=_build_research_progress_summary,
        )
        maybe_final = state.maybe_final
        _force_convergence_next = state.force_convergence_next
        _green_verification_convergence_active = state.green_verification_convergence_active
        _green_convergence_todo_used = state.green_convergence_todo_used
        _clean_verification_rounds_after_write = state.clean_verification_rounds_after_write
        final_answer = state.final_answer
        terminated_reason = state.terminated_reason
        _final_delta_emitted_this_iteration = state.final_delta_emitted_this_iteration
        _public_progress_summary = state.public_progress_summary
        if _loop_ctrl is _LoopControl.BREAK:
            break

        # ── PHASE 6f · auto-checkpoint + step evaluator ────────────────
        yield from _auto_checkpoint_and_evaluate_step(
            maybe_final=maybe_final,
            step=step,
            stack=stack,
            react_task_id=react_task_id,
            max_iterations=max_iterations,
            messages=messages,
            steps=steps,
            working_set=_working_set,
            progress_summary=_progress_summary,
            current_phase=_current_phase,
            public_progress_summary=_public_progress_summary,
            step_evaluator=step_evaluator,
        )

        steps.append(step)

        # ── PHASE 6g · housekeeping (msg append / continue / loop tail)
        # Mid-turn plan exit: model called exit_plan_mode and user approved.
        # Switch from "plan only" to "execute" without ending the turn.
        if planning_mode:
            try:
                from runtime.platform.process.session import current_session as _cs_plan

                _session_obj = _cs_plan()
            except (ImportError, AttributeError):  # noqa: BLE001
                _session_obj = None
            if (
                _session_obj is not None
                and _session_obj.metadata is not None
                and _session_obj.metadata.pop("_plan_mode_exit_approved", False)
            ):
                planning_mode = False
                enable_tools = True
                executor = getattr(stack, "executor", None)
                tools_active = executor is not None
                _logger.info(
                    "plan_mode exited mid-turn; continuing execution in same turn",
                )

        if _is_code_mode and step.action and step.action.lower() not in {"none", "n/a", ""}:
            _update_working_set(_working_set, step, _current_phase)
            _current_phase = _detect_phase(step, _current_phase)
            _progress_summary = _build_progress_summary(steps, _working_set, _current_phase)

        _has_real_observation = bool(step.observation and step.observation != "N/A")
        _has_response_tool_calls = bool(getattr(resp, "tool_calls", None))
        _length_limit_should_continue = _length_limited and not (
            _has_response_tool_calls or _has_real_observation
        )
        _checkpoint_has_final = maybe_final is not None and not _length_limit_should_continue
        if react_task_id is not None and _checkpoint_has_final:
            _ckpt_journal = getattr(stack, "journal", None)
            if _ckpt_journal is not None and hasattr(_ckpt_journal, "write_react_checkpoint"):
                try:
                    from runtime.platform.models import ArmId

                    _ckpt_journal.write_react_checkpoint(
                        react_task_id,
                        arm_id=ArmId("react_arm"),
                        iteration_completed=i + 1,
                        max_iterations=max_iterations,
                        messages_snapshot=_serialize_messages_for_checkpoint(messages),
                        steps_snapshot=[
                            {
                                "iteration": s.iteration,
                                "thought": s.thought,
                                "public_update": s.public_update,
                                "action": s.action,
                                "observation": s.observation,
                            }
                            for s in steps
                        ],
                        has_final_answer=_checkpoint_has_final,
                        final_answer=maybe_final if _checkpoint_has_final else "",
                        working_set_snapshot=list(_working_set.values()),
                        progress_summary=_progress_summary,
                        current_phase=_current_phase,
                    )
                except (OSError, TypeError):
                    _logger.debug("checkpoint write failed", exc_info=True)
        if maybe_final and _length_limit_should_continue:
            final_answer_segments.append(maybe_final)
            maybe_final = None

        if maybe_final:
            if final_answer_segments:
                final_answer = "".join(final_answer_segments + [maybe_final])
                final_answer_segments.clear()
            else:
                final_answer = maybe_final
            # A guarded long-task answer may have been intentionally buffered
            # until every completion gate passed.  Only suppress the final
            # emitter when this iteration actually yielded answer text.
            final_answer_emitted = _final_delta_emitted_this_iteration
            terminated_reason = "final_answer"
            break

        if (
            react_task_id is not None
            and max_iterations >= 15
            and (max_iterations - (i + 1)) <= 3
            and not _pause.is_pause_requested(str(react_task_id))
        ):
            remaining = max_iterations - (i + 1)
            _logger.info(
                "react_loop auto-pause at iter %d · task %s · %d left · "
                "will checkpoint next loop top",
                i + 1,
                react_task_id,
                remaining,
            )
            _pause.request_pause(
                task_id=str(react_task_id),
                reason="iteration_near_limit",
                requested_by="system",
                note=(
                    f"自动暂停 · 已跑 {i + 1}/{max_iterations} 轮 · "
                    f"剩余 {remaining} 轮 · 点继续并加预算可接续"
                ),
                thread_id=thread_id or "",
                agent_id=_agent_id_for_pause,
            )

        _assistant_content = text
        if _native_mode and not _assistant_content and step.action:
            # Native tool-use turns often carry no prose — record the
            # synthesised action so the history isn't an (API-invalid) empty
            # assistant message and the model can see what it just called.
            _assistant_content = step.action
        messages.append(Message(role="assistant", content=_assistant_content))
        # Length-limit continuation. When the upstream model truncated
        # its response (finish_reason=="length" / "max_tokens" / etc.)
        # the assistant message we just appended is mid-sentence — the
        # model itself doesn't know it stopped early, so on the NEXT
        # iteration it will either repeat work or give up and write a
        # short summary. Inject a user message asking it to continue
        # exactly where it left off so long-form generation (research
        # reports, code files, plans) can finish across multiple
        # iterations without the user seeing a half-finished doc.
        if _length_limit_should_continue:
            _code_action_recovery = _is_code_mode and not final_answer_segments
            if _code_action_recovery:
                _force_convergence_next = True
                _length_recovery_prompt = (
                    "Your previous code-task response hit the output limit before producing an "
                    "executable action. Do not continue or repeat the prose analysis. Extended "
                    "thinking is disabled for this recovery round. Emit exactly one concrete next "
                    "Action: skill_name({JSON}) now; prefer the required source/test mutation, or "
                    "the smallest targeted verifier if the implementation is already written."
                )
            else:
                _length_recovery_prompt = (
                    "Your previous response was cut off by the output "
                    "length limit. Continue exactly where it stopped — "
                    "do NOT repeat earlier text, do NOT restart the "
                    "report, do NOT switch to writing a summary or "
                    "calling todo_write. Resume from the exact "
                    "character you stopped at and finish every "
                    "remaining section."
                )
            messages.append(
                Message(
                    role="user",
                    content=_length_recovery_prompt,
                )
            )
            _logger.info(
                "react_loop iter %d · finish_reason=length, injecting continue prompt",
                i + 1,
            )
        elif step.observation and step.observation != "N/A":
            # TokenJuice: compress the observation before it enters
            # the message stream so the next LLM round sees a leaner
            # version. The full observation is preserved in
            # step.observation for journal / display / guards. Off
            # by default — opt in via OCTOPUS_TOKEN_JUICE=1.
            _obs_for_model = step.observation
            try:
                from runtime.core.cerebrum.token_juicer import (
                    is_enabled as _juice_enabled,
                )
                from runtime.core.cerebrum.token_juicer import (
                    juice as _juice,
                )

                if _observed_read_sequence or _juice_enabled():
                    _juiced, _stats = _juice(
                        step.observation,
                        max_chars=6000,
                    )
                    if _stats.passes:
                        _obs_for_model = _juiced
                        (_logger.info if _observed_read_sequence else _logger.debug)(
                            "token_juice iter %d · %d→%d chars (%.1f%% saved) passes=%s",
                            i + 1,
                            _stats.before,
                            _stats.after,
                            (1 - _stats.ratio) * 100,
                            ",".join(_stats.passes),
                        )
            except (ImportError, ValueError, TypeError):
                _logger.debug("token_juice unavailable", exc_info=True)
            messages.append(
                Message(
                    role="user",
                    content=(f"Observation: {_obs_for_model}\n\n{REACT_OBSERVATION_FOLLOWUP}"),
                )
            )

        messages = _compress_context(
            messages,
            max_tokens=context_budget_tokens_for_model(effective_model),
            router=router,
            model=effective_model,
            is_code_mode=_is_code_mode,
        )

        with contextlib.suppress(Exception):
            _pause.update_active_iteration(str(react_task_id), i + 1)

    # ── PHASE 7 · post-loop terminal handling ──────────────────────────
    # ── PHASE 8 · finalization + react_completed yield ─────────────────
    return (
        yield from _finalize_react_turn(
            terminated_reason=terminated_reason,
            final_answer=final_answer,
            i=locals().get("i", 0),
            react_task_id=react_task_id,
            pause_controller=_pause,
            messages=messages,
            is_code_mode=_is_code_mode,
            is_research_mode=_is_research_mode,
            is_swarm_mode=_is_swarm_mode,
            effective_model=effective_model,
            router=router,
            steps=steps,
            executed_beak_steps=executed_beak_steps,
            stack=stack,
            todo_protocol_required=_todo_protocol_required,
            todo_protocol_visible=_todo_protocol_visible,
            file_inspection_tools_visible=_file_inspection_tools_visible,
            tools_active=tools_active,
            goal=intent.normalized_goal,
            browser_operation_mode=_browser_operation_mode,
            final_guard_grounded_source_paths=_final_guard_grounded_source_paths,
            final_answer_emitted=final_answer_emitted,
            model_iteration_timeout_s=_model_iteration_timeout_s,
        )
    )


def run_react_loop(
    stack: StackProtocol,
    intent: ParsedIntent,
    agent: Agent | None,
    *,
    model: str | None = None,
    max_iterations: int = 30,
    temperature: float = 0.3,
    enable_tools: bool = True,
    resume_task_id: TaskId | None = None,
    thread_id: str | None = None,
    max_tokens_budget: int = 50000,
    max_usd_budget: float = 0.5,
    approval_provider: ApprovalProvider | None = None,
) -> ReActResult | None:
    gen = stream_react_loop(
        stack,
        intent,
        agent,
        model=model,
        max_iterations=max_iterations,
        temperature=temperature,
        enable_tools=enable_tools,
        resume_task_id=resume_task_id,
        thread_id=thread_id or "",
        max_tokens_budget=max_tokens_budget,
        max_usd_budget=max_usd_budget,
        approval_provider=approval_provider,
    )
    try:
        while True:
            next(gen)
    except StopIteration as stop:
        return stop.value  # type: ignore[no-any-return]
