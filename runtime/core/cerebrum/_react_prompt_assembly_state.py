"""Shared mutable assembly state for the PHASE 3 prompt-assembly split,
plus the final ``messages`` composition and the memory / identity /
team-roster sections.

Leaf module — contains the ``_AssemblyState`` dataclass, ``_assemble_messages``,
and ``_assemble_memory_sections``. Imported by the ``_react_prompt_assembly_*``
submodules and the orchestrator in ``react_prompt_assembly.py``. Never imports
any react_* sibling, so there is no import cycle.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from runtime.core.cerebrum.react_context import (
    _build_code_context_prelude,
    _build_user_message_content,
)
from runtime.core.cerebrum.stable_prompt import render_volatile_as_user_message
from runtime.platform.models.llm import Message

_logger = logging.getLogger(__name__)


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
    effective_goal: str = ""

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


def _assemble_memory_sections(state: _AssemblyState) -> None:
    """Soul / constitution / team roster / memory recall / camouflage."""
    if state.agent is not None and getattr(state.agent, "soul", None):
        try:
            from runtime.execution.agents.loader import compose_runtime_soul

            runtime_soul = compose_runtime_soul(state.agent)
        except (ImportError, AttributeError):
            _logger.debug("compose_runtime_soul not available", exc_info=True)
            runtime_soul = state.agent.soul
        if runtime_soul:
            state.system_parts.insert(0, runtime_soul)
    try:
        from runtime.safety.validation import get_constitution_summary

        _constitution = get_constitution_summary()
    except ImportError:
        _logger.debug("constitution module not available", exc_info=True)
        _constitution = ""
    if _constitution:
        state.system_parts.append(_constitution)
    try:
        from runtime.core.cerebrum.llm_planner import (
            _render_team_roster_section,
        )

        _team_block = _render_team_roster_section(state.user_context or {})
    except (ImportError, AttributeError):
        _logger.debug("team roster rendering not available", exc_info=True)
        _team_block = ""
    if _team_block:
        state.system_parts.append(_team_block)

    try:
        from runtime.memory.runtime_state.hub import (
            MemoryHub,
            MemoryQuery,
            format_records_for_prompt,
        )

        _agent_id_for_memory = (
            str(getattr(state.agent, "agent_id", "") or "") if state.agent is not None else None
        )
        _project_for_memory = (
            str(state.wp).strip() if isinstance(state.wp, str) and str(state.wp).strip() else None
        )
        _team_id_for_memory = state.user_context.get("team_id") or state.metadata.get("team_id")
        _team_id_for_memory = (
            str(_team_id_for_memory).strip()
            if isinstance(_team_id_for_memory, str) and str(_team_id_for_memory).strip()
            else None
        )
        _memory_block = format_records_for_prompt(
            MemoryHub(
                repo_root=_project_for_memory,
                planner=getattr(state.stack, "planner", None),
            ).retrieve(
                MemoryQuery(
                    text=state.intent.normalized_goal,
                    agent_id=_agent_id_for_memory,
                    project=_project_for_memory,
                    team_id=_team_id_for_memory,
                    limit=8,
                )
            ),
        )
    except Exception:
        _logger.debug("memory hub prompt injection failed", exc_info=True)
        _memory_block = ""
    if _memory_block:
        # Volatile: changes per-turn with the recall query result.
        state.volatile_parts.append(_memory_block)

    if state.camouflage_suffix:
        # Volatile: A/B variant rotates per-turn.
        state.volatile_parts.append(state.camouflage_suffix)


def _assemble_messages(state: _AssemblyState) -> None:
    """Compose the initial ``messages`` list from the assembled parts."""
    _volatile_text = "\n\n".join(state.volatile_parts).strip() if state.volatile_parts else ""
    messages: list[Message] = [
        Message(role="system", content="\n\n".join(state.system_parts)),
    ]
    if _volatile_text:
        messages.append(
            Message(
                role="user",
                content=render_volatile_as_user_message(_volatile_text),
            ),
        )
    _uc = state.user_context
    conv_history = _uc.get("conversation_messages")
    if isinstance(conv_history, list) and conv_history:
        profile_mems = _uc.get("profile_memories")
        if isinstance(profile_mems, list) and profile_mems:
            try:
                from runtime.memory.users.profile import render_profile_memories

                mem_block = render_profile_memories(profile_mems)
            except (ImportError, AttributeError, TypeError):
                mem_block = ""
            if mem_block:
                messages.append(Message(role="system", content=mem_block))
        for item in conv_history[:-1]:
            if not isinstance(item, dict):
                continue
            role = item.get("role")
            content = item.get("content")
            if role not in ("user", "assistant", "system"):
                continue
            if (
                isinstance(content, str)
                and content.strip()
                or isinstance(content, list)
                and content
            ):
                messages.append(Message(role=role, content=content))
    _current_goal = str(state.intent.normalized_goal or state.intent.raw or "").strip()
    if state.effective_goal and state.effective_goal != _current_goal:
        messages.append(
            Message(
                role="system",
                content=(
                    "<active-execution-contract>\n"
                    "The earlier execution request is still unfinished. The latest user "
                    "message steers that same task and does not replace its completion "
                    "requirements. Continue the work now; do not merely announce another "
                    "future action.\n"
                    f"Effective goal:\n{state.effective_goal}\n"
                    "</active-execution-contract>"
                ),
            )
        )
    _no_startup_code_context_modes = {
        "chat",
        "conversation",
        "inspiration",
        "brainstorm",
        "discuss",
    }
    _startup_code_context_allowed = (
        state.is_code_mode
        and state.mode_value not in _no_startup_code_context_modes
        and state.capability_mode_value not in _no_startup_code_context_modes
    )
    if (
        _startup_code_context_allowed
        and isinstance(state.effective_wp, str)
        and state.effective_wp.strip()
        and state.resume_task_id is None
    ):
        startup_context = _build_code_context_prelude(
            state.effective_wp.strip(),
            state.effective_goal or str(state.intent.normalized_goal or state.intent.raw or ""),
        )
        if startup_context:
            messages.append(Message(role="user", content=startup_context))
    messages.append(
        Message(
            role="user",
            content=_build_user_message_content(
                state.intent.normalized_goal,
                state.user_context.get("attachments", []),
            ),
        ),
    )
    if state.user_context.get("live_steering"):
        from runtime.core.cerebrum.live_steering import (
            insert_live_steering_protocol,
        )

        insert_live_steering_protocol(messages)
    state.messages = messages
