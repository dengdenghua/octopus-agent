"""PHASE 4/4.5 start events + agent auto-delegation short-circuit.

Leaf of the prompt-assembly split. Re-exported by ``react_prompt_assembly.py``
so ``react_loop.py``'s ``from ...react_prompt_assembly import _emit_turn_start_events``
keeps working. Never imports ``react_loop``.
"""

from __future__ import annotations

import logging
from collections.abc import Generator
from typing import Any

from runtime.core.cerebrum.react_execution import _skill_available_in_executor
from runtime.platform.models.llm import Message

_logger = logging.getLogger(__name__)


def _emit_turn_start_events(
    *,
    react_task_id: Any,
    thread_id: str,
    max_iterations: int,
    grounding_sources: Any,
    tools_active: bool,
    planning_mode: bool,
    intent: Any,
    executor: Any,
    stack: Any,
    messages: list,
) -> Generator[dict[str, Any], None, None]:
    """react_started / grounding / auto-delegation events (PHASE 4/4.5).

    Moved verbatim from ``react_loop.stream_react_loop``. Mutates
    ``messages`` in place when a successful auto-delegation injects its
    synthetic observation.
    """
    yield {
        "type": "react_started",
        "task_id": str(react_task_id),
        "thread_id": thread_id or None,
        "max_iterations": max_iterations,
    }

    # Surface the codebase docs/chunks we actually grounded this turn on, so
    # the UI can show a plain-language "consulted N project docs" chip. Faithful
    # by construction: these are the exact sources folded into the prompt above.
    if grounding_sources:
        yield {
            "type": "codebase_grounding",
            "sources": grounding_sources,
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
