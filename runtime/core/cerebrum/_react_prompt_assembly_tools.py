"""Tool / capability / skill-catalog sections for the PHASE 3 assembly.

Leaf of the prompt-assembly split. Handles capability activation, pinned
plugin auto-load + mention-history side effects, the skill catalog, todo
protocol guidance, and the PLAN-FIRST / CODEX PLAN lock blocks. Never imports
``react_loop``.
"""

from __future__ import annotations

import logging

from runtime.core.cerebrum._react_prompt_assembly_state import _AssemblyState
from runtime.core.cerebrum.react_browser_iteration import _ensure_browser_operation_skills
from runtime.core.cerebrum.react_context import _format_skill_catalog
from runtime.core.cerebrum.react_native import STRICT_EXPLICIT_READ_TOOL_NAMES
from runtime.core.cerebrum.react_types import REACT_NO_TOOLS_NOTE
from runtime.core.cerebrum.todo_protocol import render_todo_protocol_guidance

_logger = logging.getLogger(__name__)


def _assemble_tool_sections(state: _AssemblyState) -> None:
    """Capability activation, plugin side effects, skill catalog, plan lock."""
    if state.tools_active:
        assert state.executor is not None
        if state.browser_operation_mode:
            _ensure_browser_operation_skills(state.executor)
        try:
            from runtime.core.cerebrum.capability_router import (
                activate_capabilities,
            )

            _capability_activation = activate_capabilities(
                state.intent.normalized_goal,
                user_context=state.user_context,
                registry=state.executor.registry,
            )
            _capability_activation_prompt = _capability_activation.render_prompt()
        except (ImportError, AttributeError, TypeError, ValueError):
            _logger.debug(
                "capability activation prompt unavailable",
                exc_info=True,
            )
            _capability_activation_prompt = ""
            _capability_activation = None
        state.capability_activation = _capability_activation
        if _capability_activation_prompt:
            state.volatile_parts.append(_capability_activation_prompt)

        # Side effects of mention parsing:
        #   1. Auto-load pinned plugins so the model can use them this turn.
        #   2. Persist mention history for cross-thread autocomplete ranking.
        # Both are best-effort; failures don't block the turn.
        if _capability_activation is not None:
            _codex_handled_plugins: set[str] = set()
            try:
                if _capability_activation.pinned_plugins:
                    try:
                        from runtime.execution.suckers.codex_plugin_skills import (
                            load_codex_plugin_skills,
                        )

                        codex_report = load_codex_plugin_skills(
                            state.executor.registry,
                            _capability_activation.pinned_plugins,
                        )
                        _codex_handled_plugins.update(
                            plugin_id.lower() for plugin_id in codex_report.handled_plugin_ids
                        )
                        codex_obs = codex_report.render_observation()
                        if codex_obs:
                            state.volatile_parts.append(
                                f"<codex-plugin-injection>\n{codex_obs}\n</codex-plugin-injection>",
                            )
                    except (ImportError, AttributeError, TypeError, ValueError):
                        _logger.debug(
                            "codex plugin skill injection failed",
                            exc_info=True,
                        )

                    from runtime.core.cerebrum.plugin_auto_load import (
                        auto_load_pinned_plugins,
                    )

                    legacy_plugins = tuple(
                        plugin_id
                        for plugin_id in _capability_activation.pinned_plugins
                        if plugin_id.lower() not in _codex_handled_plugins
                    )
                    if legacy_plugins:
                        plugin_report = auto_load_pinned_plugins(legacy_plugins)
                        obs = plugin_report.render_observation()
                        if obs:
                            state.volatile_parts.append(
                                f"<plugin-activation>\n{obs}\n</plugin-activation>",
                            )
            except (ImportError, AttributeError, TypeError):
                _logger.debug(
                    "plugin auto-load failed",
                    exc_info=True,
                )

            try:
                import time as _time

                from runtime.memory.users.mention_history import (
                    get_mention_history_store,
                )

                actor = (
                    str(
                        state.user_context.get("user_id")
                        or state.user_context.get("actor")
                        or "anonymous"
                    )
                    if isinstance(state.user_context, dict)
                    else "anonymous"
                )
                store = get_mention_history_store()
                ts = _time.time()
                items: list[tuple[str, str]] = []
                for ident in _capability_activation.pinned_plugins:
                    items.append(("plugin", ident))
                for ident in _capability_activation.pinned_skills:
                    items.append(("skill", ident))
                for ident in _capability_activation.pinned_agents:
                    items.append(("agent", ident))
                for ident in _capability_activation.pinned_packs:
                    items.append(("pack", ident))
                if items:
                    store.record_batch(actor, items, ts=ts)
            except (ImportError, AttributeError, OSError, TypeError):
                _logger.debug(
                    "mention history record failed",
                    exc_info=True,
                )

        catalog = _format_skill_catalog(
            state.executor.registry,
            agent=state.agent,
            user_context=state.user_context,
            goal=state.intent.normalized_goal,
            include_names=(STRICT_EXPLICIT_READ_TOOL_NAMES if state.strict_explicit_reads else None),
        )
        if catalog:
            state.file_inspection_tools_visible = "  - read_file:" in catalog
            state.todo_protocol_visible = "  - todo_write:" in catalog
            state.system_parts.append(catalog)
            if state.todo_protocol_visible:
                state.system_parts.append(
                    render_todo_protocol_guidance(
                        required=state.todo_protocol_required,
                        mode=state.todo_protocol_mode,
                    )
                )
    else:
        state.system_parts.append(REACT_NO_TOOLS_NOTE)
    if state.planning_mode and state.is_codex_composer_plan_or_spec:
        state.system_parts.append(
            "CODEX PLAN/SPEC LOCK — This turn is a composer-applied "
            "Plan/Spec mode. Use tools only for read-only context gathering "
            "when necessary. Do not write files, run side-effecting commands, "
            "create artifacts, or continue into implementation by default. "
            "The Final Answer should be the requested plan/specification and "
            "acceptance criteria, not executed changes.",
        )
    elif state.planning_mode:
        # New semantics (2026-05-31): "plan first, then execute" — not
        # "plan only and stop". Long tasks benefit from a written plan before
        # tool work, but the user should NOT have to send a second turn to
        # actually run the plan. Old prompt forced the model to halt after
        # planning; updated prompt nudges it to write plan.md, then keep going
        # with real tool calls.
        state.system_parts.append(
            "PLAN-FIRST MODE — Before substantial tool work, write or "
            "update a brief ``plan.md`` (or todo_write entries) outlining "
            "the goal, the steps you'll take, and what the deliverable "
            "looks like. After the plan is recorded, **continue executing "
            "the plan in the same turn** using real tools (web_search, "
            "fetch_url, write_text_file, etc.). Do NOT stop after the "
            "plan — the user expects the work, not just an outline. The "
            "Final Answer must include the integrated result, not the "
            "plan alone.",
        )
