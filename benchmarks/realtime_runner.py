"""Realtime WebSocket adapter for the behavioral evaluation harness.

The adapter speaks the production JSON-RPC protocol rather than the retired
SSE endpoints. One connection and one new thread are used per trial so
``run_suite(..., k=3)`` has isolated transport state by default.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from websockets.asyncio.client import connect

ApprovalAction = Literal["accept", "decline"]
ApprovalResponder = Callable[[str, dict[str, Any]], dict[str, Any]]
EventObserver = Callable[[dict[str, Any]], None]
WorkspaceResolver = str | Path | Callable[[], str | Path]


@dataclass
class RealtimeTrialRunner:
    """Turn a production realtime session into eval-harness events."""

    url: str
    token: str | None = None
    approval_policy: str = "never"
    approval_action: ApprovalAction = "decline"
    approval_responder: ApprovalResponder | None = None
    model: str | None = None
    topology_id: str | None = None
    workspace: WorkspaceResolver | None = None
    context_overrides: dict[str, Any] | None = None
    sandbox_policy: dict[str, Any] | None = None
    timeout_seconds: float = 900.0
    event_observer: EventObserver | None = None

    def __call__(self, prompt: str):
        """Synchronous ``TrialRunner`` entry point used by ``run_suite``."""

        return iter(asyncio.run(self.run(prompt)))

    async def run(self, prompt: str) -> list[dict[str, Any]]:
        request_id = uuid.uuid4().hex
        thread_id = f"eval-{uuid.uuid4().hex}"
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else None
        workspace_root: Path | None = None
        if self.workspace is not None:
            workspace = self.workspace() if callable(self.workspace) else self.workspace
            workspace_root = Path(workspace).resolve()
            if not workspace_root.is_dir():
                raise ValueError(f"Octopus evaluation workspace does not exist: {workspace_root}")
        input_metadata: dict[str, Any] = {
            "source": "behavioral-eval",
            "isolatedTrial": True,
        }
        if workspace_root is not None:
            context: dict[str, Any] = {
                "mode": "code",
                "capability_mode": "code",
            }
            context.update(self.context_overrides or {})
            # A caller may select the appropriate work surface, but it cannot
            # weaken trial isolation or redirect the workspace.
            context["workspace_scope"] = "project"
            context["workspace_path"] = str(workspace_root)
            input_metadata["context"] = context
        params: dict[str, Any] = {
            "threadId": thread_id,
            "input": [
                {
                    "type": "text",
                    "text": prompt,
                    "metadata": input_metadata,
                }
            ],
            "approvalPolicy": self.approval_policy,
        }
        if self.model:
            params["model"] = self.model
        if self.topology_id:
            params["topologyId"] = self.topology_id
        if workspace_root is not None:
            params["cwd"] = str(workspace_root)
        if self.sandbox_policy is not None:
            params["sandboxPolicy"] = self.sandbox_policy
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "turn/start",
            "params": params,
        }
        events: list[dict[str, Any]] = []
        text_delta_seen = False
        started_at = time.monotonic()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                async with connect(
                    self.url,
                    additional_headers=headers,
                    open_timeout=min(self.timeout_seconds, 30.0),
                    close_timeout=5.0,
                    max_size=16 * 1024 * 1024,
                ) as websocket:
                    await websocket.send(json.dumps(request, ensure_ascii=False))
                    async for raw_message in websocket:
                        payload = json.loads(raw_message)
                        if not isinstance(payload, dict):
                            self._record(
                                events,
                                {"kind": "protocol_error", "error": "non-object message"},
                            )
                            continue
                        if "method" in payload and "id" in payload:
                            await websocket.send(
                                json.dumps(self._approval_response(payload), ensure_ascii=False)
                            )
                            self._record(
                                events,
                                {
                                    "kind": "approval_request",
                                    "method": str(payload.get("method") or ""),
                                    "params": payload.get("params") or {},
                                },
                            )
                            continue
                        if payload.get("id") == request_id:
                            if payload.get("error") is not None:
                                self._record(events, {"kind": "error", "error": payload["error"]})
                            else:
                                result = payload.get("result") or {}
                                turn = result.get("turn") if isinstance(result, dict) else None
                                if not text_delta_seen:
                                    self._record(events, *_final_text_events(turn))
                                self._record(events, {"kind": "turn_result", "turn": turn})
                            break
                        method = str(payload.get("method") or "")
                        params_value = payload.get("params")
                        notification_params = params_value if isinstance(params_value, dict) else {}
                        mapped = _notification_events(method, notification_params)
                        if any(row.get("kind") == "text_delta" for row in mapped):
                            text_delta_seen = True
                        self._record(events, *mapped)
        except TimeoutError:
            self._record(
                events,
                {
                    "kind": "error",
                    "error": {
                        "type": "timeout",
                        "message": f"turn exceeded {self.timeout_seconds:g}s",
                        "timeout_seconds": self.timeout_seconds,
                        "elapsed_seconds": round(time.monotonic() - started_at, 3),
                        "event_count_before_error": len(events),
                        "last_event_kind": events[-1]["kind"] if events else None,
                    },
                },
            )
        return events

    def _record(self, events: list[dict[str, Any]], *new_events: dict[str, Any]) -> None:
        for event in new_events:
            events.append(event)
            if self.event_observer is not None:
                self.event_observer(event)

    def _approval_response(self, request: dict[str, Any]) -> dict[str, Any]:
        method = str(request.get("method") or "")
        params = request.get("params")
        safe_params = params if isinstance(params, dict) else {}
        result = (
            self.approval_responder(method, safe_params)
            if self.approval_responder is not None
            else {"action": self.approval_action}
        )
        if not isinstance(result, dict):
            raise TypeError("approval_responder must return a JSON object")
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}


def _notification_events(method: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    if method == "item/agentMessage/delta":
        return [{"kind": "text_delta", "delta": str(params.get("delta") or "")}]
    if method == "item/reasoning/textDelta":
        return [{"kind": "reasoning_delta", "delta": str(params.get("delta") or "")}]
    if method == "item/commandExecution/outputDelta":
        return [
            {
                "kind": "tool_output",
                "item_id": params.get("itemId"),
                "delta": str(params.get("delta") or ""),
            }
        ]
    if method in {"item/started", "item/completed"}:
        item = params.get("item")
        if isinstance(item, dict):
            item_type = str(item.get("type") or "")
            if item_type in {"commandExecution", "mcpToolCall", "fileChange", "subagent"}:
                return [
                    {
                        "kind": "tool_start" if method == "item/started" else "tool_end",
                        "tool_name": _tool_name(item),
                        "item": item,
                    }
                ]
            if item_type == "error" and method == "item/completed":
                return [{"kind": "error", "error": item.get("errorInfo") or item}]
        return [{"kind": "item_event", "method": method, "item": item}]
    return [{"kind": "protocol_event", "method": method, "params": params}]


def _tool_name(item: dict[str, Any]) -> str:
    item_type = str(item.get("type") or "")
    if item_type == "mcpToolCall":
        return str(item.get("tool") or "mcp_tool")
    if item_type == "commandExecution":
        return "command_execution"
    if item_type == "fileChange":
        return "file_change"
    if item_type == "subagent":
        return "subagent"
    return item_type or "unknown"


def _final_text_events(turn: Any) -> list[dict[str, Any]]:
    if not isinstance(turn, dict):
        return []
    items = turn.get("items")
    if not isinstance(items, list):
        return []
    return [
        {"kind": "text_delta", "delta": str(item.get("text") or "")}
        for item in items
        if isinstance(item, dict)
        and item.get("type") == "agentMessage"
        and str(item.get("text") or "")
    ]


__all__ = [
    "ApprovalAction",
    "ApprovalResponder",
    "EventObserver",
    "RealtimeTrialRunner",
    "WorkspaceResolver",
]
