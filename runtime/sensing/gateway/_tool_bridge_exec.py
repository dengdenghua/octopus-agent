"""Tool execution + semantic error + XML recovery helpers.

Extracted from ``tool_bridge.py`` (the Claude-native agentic loop). This
satellite owns:

* ``_execute_tool_call`` — run one native ``tool_use`` via the executor
  (``execute_step`` path with scope/cwd injection, fallback to direct
  handler invocation for lightweight test doubles);
* ``_is_semantic_error`` — detect a skill that reported failure via its
  return value (``{"ok": False, ...}`` / ``{"error": ...}``);
* ``_recover_named_xml_tool_calls`` — recover explicit ``<tool_call>``
  envelopes from non-compliant providers.

The parent ``tool_bridge`` module re-exports every name here so existing
importers and tests are unchanged.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from runtime.execution.tool_engine import (
    NormalizedToolCall,
    normalize_step_tool_result,
    normalize_tool_call,
    normalize_tool_result,
    output_signals_error,
)
from runtime.execution.tool_engine.tool_output_pruner import TOOL_RESULT_PRUNE_ENABLED
from runtime.execution.tool_engine.tool_output_spill import TOOL_RESULT_SPILL_ENABLED
from runtime.sensing.model_router.models import ToolCall

from ._tool_bridge_policy import TOOL_OUTPUT_MAX_CHARS

_logger = logging.getLogger("octopus.agentic")


def _execute_tool_call(
    stack: Any,
    call: ToolCall | NormalizedToolCall | dict[str, Any],
) -> tuple[str, bool]:
    """Run one tool_use via the existing executor.

    Returns ``(output_text, is_error)``. The output is shaped for
    direct use as a ``tool_result`` ``content`` field — always a
    string, always bounded in length.
    """
    executor = getattr(stack, "executor", None)
    if executor is None:
        return ("(executor unavailable)", True)
    try:
        normalized = normalize_tool_call(call, origin="native")
    except ValueError as exc:
        return (f"(invalid tool call: {exc})", True)

    # Use execute_step when available so agentic tool calls get the
    # same scope/cwd injection, hooks, immunity, budget accounting,
    # and journal integration as planner/ReAct tool calls.
    try:
        registry = executor.registry
        if not registry.has(normalized.name):
            return (f"(skill not found: {normalized.name})", True)
        try:
            if not registry.is_enabled(normalized.name):
                return (f"(skill disabled: {normalized.name})", True)
        except (AttributeError, TypeError, ValueError):  # noqa: BLE001 — is_enabled check unsupported by this registry; proceed to get()
            pass
        skill = registry.get(normalized.name)
    except (AttributeError, TypeError, KeyError) as exc:
        return (f"(registry error: {exc})", True)

    if hasattr(executor, "execute_step"):
        try:
            from runtime.platform.models import (
                ArmId,
                Budget,
                BudgetLimits,
                SkillId,
                TaskId,
            )
            from runtime.platform.process.session import current_session

            task_id = TaskId(uuid4())
            session = current_session()
            step = executor.execute_step(
                0,
                f"agentic:{normalized.id}",
                SkillId(normalized.name),
                dict(normalized.arguments),
                caller="agentic",
                task_id=task_id,
                arm_id=ArmId("agentic"),
                budget=Budget(
                    task_id,
                    BudgetLimits(tokens=100_000, usd=10.0),
                ),
                actor=session.actor if session is not None else None,
            )
            output = step.result.output
            if step.result.status != "success":
                result = normalize_step_tool_result(
                    step,
                    origin="native",
                    max_chars=TOOL_OUTPUT_MAX_CHARS,
                    prune_middle=TOOL_RESULT_PRUNE_ENABLED,
                    spill_oversized=TOOL_RESULT_SPILL_ENABLED,
                    tool_name=normalized.name,
                )
                reason = step.result.error_type or step.result.status
                return (result.rendered or f"({reason})", True)
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            return (f"(skill error: {type(exc).__name__}: {exc})", True)
    else:
        # Fall back to direct handler invocation only for lightweight test
        # doubles that do not implement the executor contract.
        try:
            output = skill.handler(**normalized.arguments)
        except TypeError as exc:
            # Handler signature mismatch · surface the error so the
            # model can correct its arg names on the next round.
            return (f"(TypeError: {exc})", True)
        except (RuntimeError, ValueError, OSError) as exc:
            return (f"(skill error: {type(exc).__name__}: {exc})", True)

    # Detect semantic error: a skill that chose to report failure via
    # its return value (``{"ok": False, "error": "..."}`` or a bare
    # ``{"error": "..."}``) should flip ``is_error=True`` on the SSE
    # event so the frontend LiveToolTimeline marks the row red and
    # so ``tool_error_count`` in the per-turn score actually increments.
    # Without this, a skill that cleanly returns ``{"ok": False}``
    # looks identical to one that succeeded · observability blind spot
    # found in ``benchmarks/bench_b3_failure_injection.py``.
    result = normalize_tool_result(
        normalized,
        output,
        origin="native",
        max_chars=TOOL_OUTPUT_MAX_CHARS,
        prune_middle=TOOL_RESULT_PRUNE_ENABLED,
        spill_oversized=TOOL_RESULT_SPILL_ENABLED,
        tool_name=normalized.name,
    )
    return (result.rendered, result.is_error)


def _is_semantic_error(output: Any) -> bool:
    """Return True when a skill's output structurally signals failure.

    Recognized conventions (dict only · strings / lists / scalars are
    never semantic errors — they're just "output"):

      1. ``{"ok": False, ...}`` · explicit failure flag (most common)
      2. ``{"error": "non-empty string", ...}`` when ``ok`` is absent
         or falsy · some skills skip ``ok`` and only set ``error``
      3. ``{"status": "error"}`` or ``{"status": "failed"}`` · used by
         shell / git wrappers

    Conservative on purpose: a dict with ``{"ok": True, "error": ""}``
    is NOT an error (empty error field). A dict with ``{"ok": True}``
    AND an explicit non-empty ``error`` IS treated as error — rare
    but possible signal of a warning the skill wants to surface.
    """
    return output_signals_error(output)


def _recover_named_xml_tool_calls(
    text: str,
    *,
    allowed_names: set[str],
) -> list[ToolCall]:
    """Recover explicit XML tool envelopes from non-compliant providers.

    This intentionally requires a ``<tool_call...>`` marker and filters every
    recovered name through the already-published tool catalog.  Markdown code
    blocks and ordinary prose are never treated as executable calls here.
    """
    if "<tool_call" not in text.lower():
        return []
    from runtime.core.cerebrum.react_parsing import (
        _extract_tool_actions_from_loose_output,
        _parse_action,
    )

    recovered: list[ToolCall] = []
    for action in _extract_tool_actions_from_loose_output(text):
        parsed = _parse_action(action)
        if parsed is None or parsed[0] not in allowed_names:
            continue
        recovered.append(
            ToolCall(
                id=f"text-tool-{uuid4().hex}",
                name=parsed[0],
                input=parsed[1],
            )
        )
    return recovered
