"""Shared per-turn state for the ReAct main-loop phases (Wave 2).

``_LoopState`` is the minimal skeleton covering exactly what PHASE 6c
reads or writes today — no speculative fields for 6b/6d/6e yet; they
join as those phases are extracted. Reference-typed fields (``steps``,
``executed_beak_steps``, ``guard_impasse_state``) are shared with the
main loop and mutated in place; scalar fields are synced local→state
before a phase call and state→local after it, so the loop body stays
the single source of truth between phase extractions.

Depends only on react_types / platform-level types; must never import
react_loop.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any

from runtime.core.cerebrum.react_types import ReActStep


class _LoopControl(enum.Enum):
    """Control signal returned by extracted phase generators."""

    CONTINUE = "continue"  # proceed to the next phase / iteration
    NEXT_ITERATION = "next_iteration"  # skip remaining phases; next loop iteration
    BREAK = "break"  # exit the iteration loop; state carries terminated_reason/final_answer
    RETURN_NONE = "return_none"  # abort the turn; persist/unregister already done


@dataclass
class _LoopState:
    """Minimal per-turn state shared between stream_react_loop and phases."""

    # ── cfg · turn-level wiring (assembled once, read-only in 6c) ──
    stack: Any = None
    goal: str = ""
    executor: Any = None
    react_task_id: Any = None
    pause_controller: Any = None
    effective_wp: Any = None
    format_violation_bail_at: int = 2
    final_guard_grounded_source_paths: Any = None
    guard_impasse_state: dict = field(default_factory=dict)
    intent: Any = None
    agent: Any = None
    thread_id: str = ""
    approval_provider: Any = None
    output_chunk_sink: Any = None
    router: Any = None
    metadata: dict = field(default_factory=dict)
    is_goal_mode: bool = False
    observed_read_sequence: bool = False
    ordered_result_handoffs: bool = False
    realtime_public_orientation: bool = False
    realtime_public_narrative: bool = False
    # ── mode · turn flags (read-only in 6c) ──
    is_code_mode: bool = False
    browser_operation_mode: bool = False
    todo_protocol_required: bool = False
    todo_protocol_visible: bool = False
    file_inspection_tools_visible: bool = False
    read_only_turn: bool = False
    no_tool_turn: bool = False
    # ── convo · shared references (mutated in place, never re-synced) ──
    steps: list = field(default_factory=list)
    executed_beak_steps: list = field(default_factory=list)
    messages: list = field(default_factory=list)
    working_set: dict = field(default_factory=dict)
    # ── per-iteration synced scalars (synced in before 6c) ──
    tools_active: bool = False
    effective_model: str = ""
    current_phase: str = ""
    evidence_convergence_active: Any = None
    native_mode: bool = False
    model_failovers: int = 0
    model_timeout_recoveries: int = 0
    consecutive_format_violations: int = 0
    throughput_chars: int = 0
    final_stream_started: bool = False
    force_convergence_next: bool = False
    consecutive_same_failed_actions: int = 0
    last_failed_action_fingerprint: str = ""
    green_verification_convergence_active: bool = False
    green_convergence_todo_used: bool = False
    result_handoff_ready: bool = False
    last_public_update_key: str = ""
    saw_successful_code_write: bool = False
    clean_verification_rounds_after_write: int = 0
    quiet_evidence_steps: list = field(default_factory=list)
    # ── emit · terminal accumulators (synced in/out) ──
    final_answer: str | None = None
    terminated_reason: str = "max_iter"
    final_answer_emitted: bool = False
    final_delta_emitted_this_iteration: bool = False
    # ── parse · 6c outputs consumed by 6d–6g (synced out only) ──
    step: ReActStep | None = None
    maybe_final: str | None = None
    text: str = ""
    length_limited: bool = False
    length_limit_should_continue: bool = False
