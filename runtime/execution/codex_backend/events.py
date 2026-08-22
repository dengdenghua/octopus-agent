"""Translate Codex App Server notifications into Octopus execution events.

The Codex protocol intentionally evolves faster than Octopus' public realtime
wire model.  This module is the anti-corruption layer between them: only the
small, stable semantic subset used by the Octopus execution backend crosses
this boundary.  Unknown notifications are ignored instead of leaking upstream
protocol objects into durable Octopus history.

The returned dictionaries use the same event vocabulary as the native ReAct
bridge (``text_delta``, ``tool_start``, ``tool_end`` ...).  That lets the
gateway reuse one item/journal reducer for native and Codex execution rather
than maintaining two subtly different UI protocols.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .types import JsonObject, Notification

_MAX_PREVIEW_CHARS = 8_000
_MAX_ERROR_CHARS = 4_000


@dataclass(slots=True)
class CodexEventState:
    """Small per-turn deduplication state for the notification projection."""

    streamed_agent_items: set[str] = field(default_factory=set)
    streamed_reasoning_items: set[str] = field(default_factory=set)
    started_tool_items: set[str] = field(default_factory=set)


def _text(value: Any, *, limit: int = _MAX_PREVIEW_CHARS) -> str:
    if isinstance(value, str):
        rendered = value
    elif value is None:
        return ""
    else:
        try:
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except (TypeError, ValueError):
            rendered = str(value)
    if len(rendered) <= limit:
        return rendered
    return rendered[: max(0, limit - 14)].rstrip() + "\n…(truncated)"


def _status(value: Any) -> str:
    current = str(value or "").strip().casefold()
    if current in {"declined", "rejected"}:
        return "rejected"
    if current in {"cancelled", "canceled", "interrupted", "aborted"}:
        return "cancelled"
    if current in {"failed", "error"}:
        return "error"
    return "success"


def _tool_name(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return "exec_shell"
    if item_type == "fileChange":
        return "apply_patch"
    if item_type == "mcpToolCall":
        server = str(item.get("server") or "mcp").strip().replace("/", "_")
        tool = str(item.get("tool") or "tool").strip().replace("/", "_")
        return f"mcp__{server}__{tool}"
    if item_type == "dynamicToolCall":
        namespace = str(item.get("namespace") or "dynamic").strip().replace("/", "_")
        tool = str(item.get("tool") or "tool").strip().replace("/", "_")
        return f"{namespace}__{tool}"
    if item_type in {"collabAgentToolCall", "subAgentActivity"}:
        return "call_subagent"
    return {
        "webSearch": "web_search",
        "imageView": "view_image",
        "imageGeneration": "image_generate",
        "sleep": "sleep",
    }.get(item_type, "")


def _tool_input(item: dict[str, Any]) -> dict[str, Any]:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return {
            "command": _text(item.get("command")),
            "cwd": _text(item.get("cwd")),
            "actions": item.get("commandActions")
            if isinstance(item.get("commandActions"), list)
            else [],
            "process_id": _text(item.get("processId")),
        }
    if item_type == "fileChange":
        return {
            "changes": item.get("changes") if isinstance(item.get("changes"), list) else [],
        }
    if item_type in {"mcpToolCall", "dynamicToolCall"}:
        return {
            "arguments": item.get("arguments"),
            "server": item.get("server"),
            "tool": item.get("tool"),
        }
    if item_type == "collabAgentToolCall":
        return {
            "tool": item.get("tool"),
            "prompt": _text(item.get("prompt")),
            "model": item.get("model"),
            "receiver_thread_ids": item.get("receiverThreadIds"),
        }
    if item_type == "subAgentActivity":
        return {
            "agent_path": item.get("agentPath"),
            "agent_thread_id": item.get("agentThreadId"),
            "kind": item.get("kind"),
        }
    if item_type == "webSearch":
        return {"query": _text(item.get("query")), "action": item.get("action")}
    if item_type == "imageView":
        return {"path": _text(item.get("path"))}
    return {"item_type": item_type}


def _file_changes(item: dict[str, Any]) -> list[dict[str, Any]]:
    raw_changes = item.get("changes")
    if not isinstance(raw_changes, list):
        return []
    changes: list[dict[str, Any]] = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            continue
        path = raw.get("path")
        diff = raw.get("diff")
        kind = raw.get("kind")
        if not isinstance(path, str) or not path.strip():
            continue
        kind_name = kind.get("type") if isinstance(kind, dict) else kind
        op = {"add": "create", "delete": "delete", "update": "update"}.get(
            str(kind_name or "").casefold(),
            "update",
        )
        changes.append(
            {
                "path": path,
                "op": op,
                "diff": diff if isinstance(diff, str) else None,
            }
        )
    return changes


def _tool_output(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "")
    if item_type == "commandExecution":
        return _text(item.get("aggregatedOutput"))
    if item_type == "mcpToolCall":
        return _text(item.get("error") or item.get("result"))
    if item_type == "dynamicToolCall":
        return _text(item.get("contentItems"))
    if item_type == "collabAgentToolCall":
        return _text(item.get("agentsStates"))
    return ""


def _turn_status(turn: Any) -> tuple[bool, str]:
    value = turn if isinstance(turn, dict) else {}
    raw = str(value.get("status") or "completed").strip()
    normalized = raw.casefold()
    return normalized in {"completed", "complete", "success", "succeeded"}, raw


def translate_notification(
    notification: Notification,
    state: CodexEventState,
) -> list[dict[str, Any]]:
    """Project one App Server notification onto native Octopus events.

    Every returned event is bounded and JSON-compatible.  An empty list means
    the notification is valid but has no public Octopus projection.
    """

    method = notification.method
    params: JsonObject = notification.params

    if method == "item/agentMessage/delta":
        delta = _text(params.get("delta"))
        item_id = str(params.get("itemId") or "")
        if item_id:
            state.streamed_agent_items.add(item_id)
        return [{"type": "text_delta", "delta": delta}] if delta else []

    if method in {"item/reasoning/textDelta", "item/reasoning/summaryTextDelta"}:
        delta = _text(params.get("delta"))
        item_id = str(params.get("itemId") or "")
        if item_id:
            state.streamed_reasoning_items.add(item_id)
        return [{"type": "thinking_delta", "delta": delta}] if delta else []

    if method == "item/plan/delta":
        delta = _text(params.get("delta"))
        return (
            [
                {
                    "type": "commentary_delta",
                    "delta": delta,
                    "public_status": True,
                    "start_new_segment": False,
                }
            ]
            if delta
            else []
        )

    if method in {
        "item/commandExecution/outputDelta",
        "item/fileChange/outputDelta",
        "item/process/outputDelta",
    }:
        item_id = str(params.get("itemId") or "")
        delta = _text(params.get("delta"))
        if item_id and delta:
            return [{"type": "tool_output_delta", "tool_call_id": item_id, "delta": delta}]
        return []

    if method in {"item/started", "item/completed"}:
        raw_item = params.get("item")
        item = raw_item if isinstance(raw_item, dict) else {}
        item_id = str(item.get("id") or "")
        item_type = str(item.get("type") or "")

        if item_type == "agentMessage" and method == "item/completed":
            events: list[dict[str, Any]] = []
            text = _text(item.get("text"))
            if text and item_id not in state.streamed_agent_items:
                events.append({"type": "text_delta", "delta": text})
            events.append({"type": "react_step_complete"})
            return events

        if item_type == "reasoning" and method == "item/completed":
            events = []
            if item_id not in state.streamed_reasoning_items:
                pieces: list[str] = []
                for key in ("summary", "content"):
                    value = item.get(key)
                    if isinstance(value, list):
                        pieces.extend(str(part) for part in value if part)
                rendered = _text("\n".join(pieces))
                if rendered:
                    events.append({"type": "thinking_delta", "delta": rendered})
            events.append({"type": "react_step_complete"})
            return events

        if item_type == "plan" and method == "item/completed":
            text = _text(item.get("text"))
            if not text:
                return []
            return [
                {
                    "type": "commentary_delta",
                    "delta": text,
                    "public_status": True,
                    "start_new_segment": True,
                },
                {"type": "react_step_complete"},
            ]

        tool_name = _tool_name(item)
        if not tool_name or not item_id:
            return []
        if method == "item/started":
            if item_id in state.started_tool_items:
                return []
            state.started_tool_items.add(item_id)
            return [
                {
                    "type": "tool_start",
                    "tool_name": tool_name,
                    "tool_call_id": item_id,
                    "input_preview": _tool_input(item),
                    "public_description": _text(item.get("description"), limit=80),
                }
            ]

        # Some protocol items may be delivered completed without a matching
        # live start after resume.  Synthesize the start so the native reducer
        # can close a real item instead of silently dropping the completion.
        events = []
        if item_id not in state.started_tool_items:
            state.started_tool_items.add(item_id)
            events.append(
                {
                    "type": "tool_start",
                    "tool_name": tool_name,
                    "tool_call_id": item_id,
                    "input_preview": _tool_input(item),
                }
            )
        completed: dict[str, Any] = {
            "type": "tool_end",
            "tool_name": tool_name,
            "tool_call_id": item_id,
            "status": _status(item.get("status")),
            "output_preview": _tool_output(item),
            "duration_ms": item.get("durationMs"),
        }
        if isinstance(item.get("exitCode"), int):
            completed["exit_code"] = item["exitCode"]
        if item_type == "fileChange":
            completed["file_changes"] = _file_changes(item)
        events.append(completed)
        return events

    if method == "thread/tokenUsage/updated":
        usage = params.get("tokenUsage")
        return [{"type": "throughput", "usage": usage if isinstance(usage, dict) else {}}]

    if method == "turn/completed":
        success, status = _turn_status(params.get("turn"))
        turn = params.get("turn")
        turn_obj = turn if isinstance(turn, dict) else {}
        if status.casefold() in {"interrupted", "cancelled", "canceled"}:
            return [
                {
                    "type": "react_cancelled",
                    "reason": _text(turn_obj.get("error") or status, limit=_MAX_ERROR_CHARS),
                }
            ]
        return [
            {
                "type": "react_completed",
                "success": success,
                "terminated_reason": status,
                "completion_receipt": {
                    "message": _text(turn_obj.get("error"), limit=_MAX_ERROR_CHARS),
                    "codex_status": status,
                },
            }
        ]

    if method == "error":
        if params.get("willRetry") is True:
            # App Server can report a transient failure while its own retry
            # loop is still active. Failing the public turn here would race
            # and mask a later successful retry.
            return [
                {
                    "type": "commentary_delta",
                    "delta": "Codex 遇到暂时性错误，正在自动重试。",
                    "public_status": True,
                    "start_new_segment": True,
                }
            ]
        detail = params.get("error") or params.get("message") or params
        return [
            {
                "type": "react_error",
                "kind": "codex_app_server_error",
                "message": _text(detail, limit=_MAX_ERROR_CHARS) or "Codex App Server error",
            }
        ]

    return []


__all__ = ["CodexEventState", "translate_notification"]
