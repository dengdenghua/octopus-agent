"""Message checkpoint (de)serialization helpers.

Extracted from ``react_context.py``. Pure helpers — no behaviour change.
"""

from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger(__name__)


def _serialize_messages_for_checkpoint(messages: list) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for m in messages:
        entry: dict[str, Any] = {"role": getattr(m, "role", "")}
        content = getattr(m, "content", "")
        if isinstance(content, list):
            entry["content"] = content
        else:
            entry["content"] = str(content) if content else ""
        tool_calls = getattr(m, "tool_calls", None)
        if tool_calls:
            entry["tool_calls"] = [
                {"id": tc.id, "name": tc.name, "input": tc.input} for tc in tool_calls
            ]
        tool_call_id = getattr(m, "tool_call_id", None)
        if tool_call_id:
            entry["tool_call_id"] = tool_call_id
        name = getattr(m, "name", None)
        if name:
            entry["name"] = name
        result.append(entry)
    return result


def _restore_messages_from_checkpoint(snapshot: list[dict[str, Any]]) -> list:
    from runtime.platform.models.llm import Message, ToolCall

    result: list[Message] = []
    for m in snapshot:
        if not isinstance(m, dict) or not m.get("role"):
            continue
        content = m.get("content", "")
        if not content:
            continue
        msg = Message(role=m["role"], content=content)
        tool_calls_data = m.get("tool_calls")
        if tool_calls_data and isinstance(tool_calls_data, list):
            try:
                tcs = tuple(
                    ToolCall(id=tc["id"], name=tc["name"], input=tc.get("input", {}))
                    for tc in tool_calls_data
                    if isinstance(tc, dict) and tc.get("id") and tc.get("name")
                )
                if tcs:
                    msg = msg.model_copy(update={"tool_calls": tcs})
            except (TypeError, ValueError) as exc:
                _logger.debug("tool_calls restore skipped: %s", exc)
        result.append(msg)
    return result
