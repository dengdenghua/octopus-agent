"""Tool timeout detection and policy guards.

Detects when tools frequently timeout and suggests policy adjustments or
alternative approaches. Part of DSH P1 guard family.

DSH feature parity: point P1 timeout-policy (2026-08-14).
"""

from __future__ import annotations

from typing import Any


def _extract_timeout_events(steps: list[Any]) -> list[tuple[str, bool]]:
    """Extract (tool_name, did_timeout) from trajectory steps.

    Accepts dict-style steps (unit-test fixtures) and ``ReActStep`` objects
    (production trajectory). Returns a list of all tool calls that completed,
    with a boolean indicating whether they timed out.
    """
    events: list[tuple[str, bool]] = []
    for step in steps:
        if isinstance(step, dict):
            action = str(step.get("action", "") or "")
            observation = step.get("observation")
            action_blocks = [action] if action else []
        else:
            action = getattr(step, "action", "") or ""
            observation = getattr(step, "observation", None)
            action_blocks = list(getattr(step, "actions", None) or ([action] if action else []))

        if not action_blocks or observation is None:
            continue

        obs_str = str(observation).lower()
        for action_text in action_blocks:
            # Parse tool name
            action_text = action_text.strip()
            if action_text.startswith("Action:"):
                action_text = action_text[7:].strip()

            paren_idx = action_text.find("(")
            if paren_idx == -1:
                continue

            tool_name = action_text[:paren_idx].strip()

            # Check if the observation indicates a timeout
            did_timeout = (
                "timed out" in obs_str
                or "timeout" in obs_str
                or "exceeded" in obs_str
                and "time" in obs_str
            )

            events.append((tool_name, did_timeout))

    return events


def _timeout_policy_guard(
    steps: list[dict[str, Any]],
    final_answer: str | None,
    *,
    threshold: int = 2,
    window: int = 5,
) -> str | None:
    """Guard against repeated tool timeouts.

    Fires when a tool has timed out ``threshold`` times within the last
    ``window`` steps, suggesting the timeout policy may need adjustment or
    the approach should change.

    Args:
        steps: ReAct trajectory steps
        final_answer: The proposed final answer (unused)
        threshold: Number of timeouts to trigger (default 2)
        window: Look-back window in steps (default 5)

    Returns:
        Reminder message if timeout pattern detected, None otherwise.
    """
    if not steps:
        return None

    events = _extract_timeout_events(steps)
    if len(events) < threshold:
        return None

    # Look at recent events within window
    recent = events[-window:]

    # Count timeouts per tool
    timeout_counts: dict[str, int] = {}
    for tool_name, did_timeout in recent:
        if did_timeout:
            timeout_counts[tool_name] = timeout_counts.get(tool_name, 0) + 1

    # Find tools that exceeded threshold
    problematic_tools = [
        (tool, count) for tool, count in timeout_counts.items() if count >= threshold
    ]

    if not problematic_tools:
        return None

    # Build message
    if len(problematic_tools) == 1:
        tool_name, count = problematic_tools[0]
        return (
            f"`{tool_name}` has timed out {count} times in the last {len(recent)} "
            f"steps. This suggests:\n"
            f"- The operation may be too expensive for the default timeout\n"
            f"- You may need to break the work into smaller chunks\n"
            f"- Consider using a different tool or approach\n"
            f"- If the tool supports timeout parameters, try increasing them\n\n"
            f"Continuing to retry the same operation will likely keep timing out."
        )
    tool_list = ", ".join(f"`{tool}` ({count}x)" for tool, count in problematic_tools)
    return (
        f"Multiple tools are timing out repeatedly: {tool_list}. "
        f"This suggests the current approach may not be viable. Consider:\n"
        f"- Breaking the work into smaller operations\n"
        f"- Using simpler or faster alternatives\n"
        f"- Checking if the environment or data is unusually large\n"
        f"- Asking the user if timeouts are expected for this task"
    )


def _consecutive_timeout_guard(
    steps: list[dict[str, Any]],
    final_answer: str | None,
    *,
    threshold: int = 2,
) -> str | None:
    """Guard against consecutive timeouts (stricter check).

    Fires when the last ``threshold`` tool calls all timed out, indicating
    the model is completely stuck.

    Args:
        steps: ReAct trajectory steps
        final_answer: The proposed final answer (unused)
        threshold: Number of consecutive timeouts to trigger (default 2)

    Returns:
        Urgent message if consecutive timeouts detected, None otherwise.
    """
    if not steps or len(steps) < threshold:
        return None

    events = _extract_timeout_events(steps)
    if len(events) < threshold:
        return None

    # Check last N events
    last_n = events[-threshold:]

    # All must be timeouts
    if not all(did_timeout for _, did_timeout in last_n):
        return None

    tool_names = [tool for tool, _ in last_n]
    if len(set(tool_names)) == 1:
        # Same tool
        return (
            f"The last {threshold} attempts to use `{tool_names[0]}` all timed out. "
            f"You MUST stop trying this tool and either:\n"
            f"- Use a completely different tool\n"
            f"- Break the task into much smaller pieces\n"
            f"- Ask the user for help or clarification\n\n"
            f"Continuing with the same tool is guaranteed to fail."
        )
    # Different tools
    unique_tools = list(set(tool_names))
    return (
        f"The last {threshold} tool calls all timed out (tried: "
        f"{', '.join(f'`{t}`' for t in unique_tools)}). The current approach "
        f"is completely blocked. You need to:\n"
        f"- Fundamentally reconsider your approach\n"
        f"- Ask the user if this environment has unusual constraints\n"
        f"- Consider if the task is feasible given the timeout limits\n\n"
        f"Do not continue with tools that keep timing out."
    )


__all__ = [
    "_timeout_policy_guard",
    "_consecutive_timeout_guard",
]
