"""Native tool-use path for the single-agent ReAct loop.

The default ReAct loop drives the model through a *text* protocol
(``Thought:`` / ``Action: name({...})`` / ``Observation:``) and recovers
the action with ~56 regexes in ``react_parsing.py``. That text layer is a
robustness floor for weak / local models (ollama, etc.) that cannot do
native function calling.

For models that *do* advertise ``supports_tool_use`` we can skip the text
round-trip entirely: pass the registered skills as native ``tools`` and
read the model's ``tool_calls`` straight off the response. This removes the
single biggest brittleness source — parsing the action out of free text.

The integration is deliberately surgical. Rather than rewrite the
2900-line dispatch section (an inline generator with approval / retry /
cancel / background-task / checkpoint behaviour), we *synthesise* the
loop's existing ``ReActStep.action`` / ``.actions`` strings from the native
``tool_calls`` and let the proven dispatch run unchanged. ``json.dumps`` of
the tool input round-trips losslessly through the dispatch's
``_parse_action`` (``json.loads``), so there is no regex involved on the
native path.

Gating (both must hold):

* ``OCTOPUS_NATIVE_TOOLUSE`` env flag is truthy. Default OFF — the native
  path stays opt-in until validated against a live tool-use API, so the
  out-of-the-box behaviour (and the whole test suite, which uses mock
  routers) is byte-identical to before.
* The router resolves a provider whose ``capabilities.supports_tool_use``
  is True for the effective model. Mock / weak routers report False and
  transparently keep the text protocol.
"""

from __future__ import annotations

import json
import os
from typing import Any

from runtime.core.cerebrum.react_types import ReActStep

_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def native_tool_use_flag_enabled() -> bool:
    """Read ``OCTOPUS_NATIVE_TOOLUSE`` fresh each call (operator can flip
    without a restart).

    Default ON: validated 2026-06 against a live function-calling API
    (structured tool_calls dispatched + correct answer end-to-end). The
    capability gate still applies, so only models advertising
    ``supports_tool_use`` actually take the native path; everything else
    transparently keeps the text protocol. Set ``OCTOPUS_NATIVE_TOOLUSE=0``
    (or false/no/off) to force the text protocol even on capable models.
    """
    raw = os.environ.get("OCTOPUS_NATIVE_TOOLUSE", "").strip().lower()
    return raw not in _FALSY


def model_supports_tool_use(router: Any, model: str) -> bool:
    """Whether ``router`` can serve ``model`` via native tool-use.

    Handles both router topologies defensively:

    * a direct provider router exposes ``capabilities.supports_tool_use``;
    * a ``ModelDispatchRouter`` resolves a per-model sub-router — we peek
      at the resolved sub-router's capabilities.

    Any uncertainty (missing attribute, resolve failure) returns False so
    the loop falls back to the text protocol — never the other way round.
    """
    if _caps_support(getattr(router, "capabilities", None)):
        return True
    resolve = getattr(router, "_resolve", None)
    if callable(resolve):
        try:
            sub = resolve(model)
        except Exception:  # noqa: BLE001 — resolution must never break gating
            return False
        if sub is not None and sub is not router:
            return _caps_support(getattr(sub, "capabilities", None))
    return False


def _caps_support(caps: Any) -> bool:
    return bool(caps is not None and getattr(caps, "supports_tool_use", False))


def native_tool_use_active(router: Any, model: str) -> bool:
    """Combined gate: flag on AND the resolved model advertises tool-use."""
    return native_tool_use_flag_enabled() and model_supports_tool_use(router, model)


def build_loop_tool_specs(
    executor: Any,
    *,
    agent: Any = None,
    goal: str = "",
    user_context: dict[str, Any] | None = None,
) -> list[Any]:
    """Build the native ``ToolSpec`` catalog from the loop's skill registry.

    Returns ``[]`` on any failure (missing registry, builder error) so a
    spec-build problem silently downgrades to the text protocol rather than
    aborting the turn.
    """
    registry = getattr(executor, "registry", None)
    if registry is None:
        return []
    try:
        from runtime.execution.tool_spec_builder import build_anthropic_tool_specs

        specs = build_anthropic_tool_specs(
            registry,
            agent=agent,
            goal=goal,
            user_context=user_context,
        )
        return list(specs or [])
    except Exception:  # noqa: BLE001 — spec build is best-effort; fall back to text
        return []


def step_from_tool_calls(
    tool_calls: list[Any],
    *,
    text: str = "",
    thinking: str = "",
    iteration: int = 0,
) -> ReActStep:
    """Synthesise a ``ReActStep`` from native ``tool_calls``.

    Each call becomes a ``name({json})`` action string — exactly the shape
    the dispatch's ``_parse_action`` already parses — so the existing
    single/parallel dispatch path runs unchanged. ``json.dumps`` →
    ``json.loads`` round-trips the args with no regex and no lossy
    formatting. The model's prose (``text``) is preserved as the step
    thought for observability; ``thinking`` is the extended-thinking trace.
    """
    actions: list[str] = []
    for call in tool_calls:
        name = str(getattr(call, "name", "") or "").strip()
        if not name:
            continue
        raw_input = getattr(call, "input", None)
        args = raw_input if isinstance(raw_input, dict) else {}
        try:
            arg_json = json.dumps(args, ensure_ascii=False)
        except (TypeError, ValueError):
            arg_json = "{}"
        actions.append(f"{name}({arg_json})")

    thought = (thinking or text or "").strip()
    return ReActStep(
        iteration=iteration,
        thought=thought,
        action="; ".join(actions),
        observation="",
        raw_llm_output=text or "",
        actions=actions,
        action_results=[],
    )


def trim_text_protocol_for_native(system_prompt: str) -> str:
    """Phase 1: drop the redundant text-protocol scaffolding for native mode.

    When tools are passed natively the model emits ``tool_use`` blocks and
    ignores the ``Action: name({...})`` *text* instructions (Anthropic
    prioritises ``tools`` over a competing text protocol). Those lines are
    then pure token overhead. We strip the worked ``Thought/Action/
    Observation`` example block and append a one-line native directive,
    leaving the rest of the prompt (role, policies, skills guidance) intact.

    Conservative: if the expected anchors are absent (prompt changed) the
    original string is returned unmodified.
    """
    marker = "Thought:"
    end_marker = "Observation:"
    start = system_prompt.find(marker)
    if start == -1:
        return system_prompt
    end = system_prompt.find(end_marker, start)
    if end == -1:
        return system_prompt
    # Cut from the first worked Thought/Action example through the line that
    # closes the Observation placeholder.
    line_end = system_prompt.find("\n", end)
    if line_end == -1:
        line_end = len(system_prompt)
    native_note = (
        "你已获得原生工具调用能力(tools)。直接调用所需工具即可,"
        "无需输出 Thought/Action/Observation 文本协议;完成后给出最终答案。"
    )
    return system_prompt[:start] + native_note + system_prompt[line_end:]
