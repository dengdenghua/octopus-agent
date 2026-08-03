"""Re-export hub for ``react_loop.py``.

The ReAct loop body (``react_loop.py``) orchestrates the phase state
machine by calling helpers that live in the per-phase satellite modules
(``react_parsing``, ``react_execution``, ``react_guards``, ``react_context``,
``react_checkpointing``, ``react_loop_controls``, ``react_parallel_dispatch``,
``react_terminal``, ``react_in_flight_nudges``, ...). Those helpers are also
re-exported through ``react_loop`` for backward compatibility with
``tests/test_react_loop.py`` and friends.

This module consolidates the *backward-compat re-export surface* only: the
names ``react_loop`` exposes in ``__all__`` that are **not** used by the loop
body itself. ``react_loop.py`` pulls them in with a single
``from ._react_loop_reexports import *`` (the body-only names stay as explicit
imports there so ruff's F405 never fires on them). Listing every name in
``__all__`` keeps ruff from treating the imports as unused.
"""

from __future__ import annotations

from runtime.core.cerebrum.react_browser_iteration import (
    _browser_operation_requested,
    _browser_task_iteration_limit,
    _code_task_iteration_limit,
    _ensure_browser_operation_skills,
    _narrow_research_iteration_limit,
)
from runtime.core.cerebrum.react_checkpointing import (
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
    _format_skill_catalog,
    _image_blocks_from_attachments,
    _looks_like_image_attachment,
)
from runtime.core.cerebrum.react_execution import (
    _background_task_info_from_observation,
    _beak_step_effective_success,
    _execute_action_via_beak,
    _format_background_task_heartbeat,
    _has_unrecovered_beak_failure,
    _is_scoped_artifact_write,
    _normalized_tool_call_from_react_action,
    _persist_react_trajectory,
    _react_completion_receipt,
    _reset_kg_throttle_for_tests,
    _skill_available_in_executor,
    _tool_event_extras_from_beak_step,
)
from runtime.core.cerebrum.react_explicit_reads import (
    _explicit_no_tool_goal,
    _explicit_read_only_goal,
    _recover_explicit_read_actions,
)
from runtime.core.cerebrum.react_final_answer_guards import (
    _final_answer_needs_pre_emit_guard,
    _guard_reason_for_user,
    _note_guard_impasse,
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
from runtime.core.cerebrum.react_loop_controls import (
    _CONTEXT_PRESSURE_NUDGE,
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
from runtime.core.cerebrum.react_model_deadlines import (
    _MODEL_STREAM_DEADLINE,
    _collect_model_stream_text_with_deadline,
    _finish_reason_is_length_limited,
    _iter_model_stream_with_deadline,
    _stage_model_timeout_s,
    _stage_update_timeout_fallback,
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
from runtime.core.cerebrum.react_public_updates import (
    _observed_read_fallback_update,
    _safe_public_update,
)
from runtime.core.cerebrum.react_quiet_evidence import (
    _quiet_evidence_targets,
)
from runtime.core.cerebrum.react_resume import (
    _build_resume_context_prompt,
    _compute_resume_state,
    _ResumeState,
)
from runtime.core.cerebrum.react_types import (
    _native_tool_calls_missing_required_args,
)
from runtime.core.cerebrum.todo_protocol import (
    _todo_completion_before_write_guard,
    _todo_prewrite_guard,
)

__all__ = [
    "_MODEL_STREAM_DEADLINE",
    "_CONTEXT_PRESSURE_NUDGE",
    "_ResumeState",
    "_background_task_info_from_observation",
    "_beak_step_effective_success",
    "_browser_operation_requested",
    "_browser_task_iteration_limit",
    "_build_code_agent_mode_prompt",
    "_build_code_context_prelude",
    "_build_personal_agent_mode_prompt",
    "_build_project_signals_prompt",
    "_build_resume_context_prompt",
    "_build_user_message_content",
    "_build_workflow_preset_prompt",
    "_checkpoint_interval",
    "_checkpoint_mirror",
    "_code_mode_completion_guard",
    "_code_task_iteration_limit",
    "_collect_model_stream_text_with_deadline",
    "_completion_phrase_without_todo_guard",
    "_compute_resume_state",
    "_disabled_guard_labels",
    "_disabled_guards_from_yaml",
    "_ensure_browser_operation_skills",
    "_escape_md_brackets",
    "_estimate_context_fullness",
    "_execute_action_via_beak",
    "_explicit_no_tool_goal",
    "_explicit_read_only_goal",
    "_explicit_source_paths",
    "_extract_final_answer",
    "_failed_verification_followup_guard",
    "_final_answer_needs_pre_emit_guard",
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
    "_safe_for_streamdown",
    "_safe_public_update",
    "_should_auto_checkpoint",
    "_skill_available_in_executor",
    "_stage_model_timeout_s",
    "_stage_update_timeout_fallback",
    "_summarize_observation",
    "_todo_completion_before_write_guard",
    "_todo_prewrite_guard",
    "_tool_event_extras_from_beak_step",
    "_unfinished_implementation_recovery_needed",
    "_unverified_write_followup_guard",
    "get_react_variant_stats",
    "pick_react_variant",
    "record_react_variant_result",
]
