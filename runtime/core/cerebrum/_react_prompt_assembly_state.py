"""Shared mutable assembly state for the PHASE 3 prompt-assembly split.

Leaf module — contains only the dataclass. Imported by the
``_react_prompt_assembly_*`` submodules and the orchestrator in
``react_prompt_assembly.py``. Never imports any react_* sibling, so there is
no import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class _AssemblyState:
    """Everything the PHASE 3 assembly helpers read / write.

    ``system_parts`` / ``volatile_parts`` are the two shared buffers the
    section helpers append to; every scalar that must survive to the final
    ``_PromptAssembly`` is stored as a field so the orchestrator can read it
    back after each helper runs.
    """

    # ── inputs (set by the orchestrator) ────────────────────────────────
    intent: Any
    agent: Any
    stack: Any
    executor: Any
    approval_provider: Any
    resume_task_id: Any
    planning_mode: bool
    tools_active: bool
    native_mode: bool
    no_tool_turn: bool
    strict_explicit_reads: bool
    camouflage_suffix: str
    max_iterations: int
    max_tokens_budget: Any
    max_usd_budget: Any

    # ── derived inputs ──────────────────────────────────────────────────
    user_context: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    # ── shared buffers ──────────────────────────────────────────────────
    system_parts: list = field(default_factory=list)
    volatile_parts: list = field(default_factory=list)

    # ── early / mode resolution ─────────────────────────────────────────
    work_mode: Any = None
    wp: Any = None
    effective_wp: Any = None
    resume_context_prompt: str = ""
    is_goal_mode: bool = False
    is_code_mode: bool = False
    read_only_turn: bool = False
    observed_read_sequence: bool = False
    observed_read_groups: tuple = ()
    grounding_sources: list = field(default_factory=list)
    grounded_source_paths: frozenset = frozenset()
    final_guard_grounded_source_paths: frozenset = frozenset()
    browser_operation_mode: bool = False
    chrome_operation_mode: bool = False
    guard_impasse_state: dict = field(default_factory=dict)
    realtime_public_orientation_requested: bool = False
    mode_value: Any = None
    capability_mode_value: Any = None
    agent_mode_value: Any = None
    workflow_preset_value: Any = None
    codex_mode_value: Any = None
    completion_policy_value: Any = None
    is_codex_composer_plan_or_spec: bool = False
    mode_contract_value: Any = None
    personal_mode_value: Any = None
    project_signals: Any = None
    is_swarm_mode: bool = False
    is_research_mode: bool = False
    active_max_tokens_budget: Any = None
    active_max_usd_budget: Any = None
    budget_pause_threshold: float = 0.0
    budget_auto_pause_enabled: bool = False
    todo_protocol_mode: Any = None
    todo_protocol_required: bool = False
    todo_protocol_visible: bool = False
    goal_for_mode: str = ""
    browser_regression_enabled: bool = False
    browser_regression_preview_url: Any = None

    # ── tool / capability sections ──────────────────────────────────────
    file_inspection_tools_visible: bool = False
    capability_activation: Any = None

    # ── final messages ──────────────────────────────────────────────────
    messages: list = field(default_factory=list)
