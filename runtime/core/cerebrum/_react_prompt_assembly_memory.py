"""Memory / identity / team-roster sections for the PHASE 3 assembly.

Leaf of the prompt-assembly split. Handles the agent soul, the constitution
summary, the team-roster section, the memory-hub recall block, and the
camouflage suffix. Never imports ``react_loop``.
"""

from __future__ import annotations

import logging

from runtime.core.cerebrum._react_prompt_assembly_state import _AssemblyState

_logger = logging.getLogger(__name__)


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
