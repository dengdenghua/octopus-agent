"""Build an engine-neutral execution trace from durable trace-store rows.

The realtime bridge deliberately stores small lifecycle events instead of
provider-specific protocol objects.  This module is the read-side contract
for evaluators, replay tools and the learning pipeline: Codex and Native
produce the same trace shape even when their inner loops differ.
"""

from __future__ import annotations

from typing import Any

_START_EVENTS = frozenset({"TOOL_CALL_START", "TOOL_START", "SUB_TOOL_START"})
_END_EVENTS = frozenset({"TOOL_CALL_END", "TOOL_CALL_FINISH", "TOOL_END", "SUB_TOOL_END"})
_TERMINAL_EVENTS = frozenset(
    {
        "TASK_RUN_FINISHED",
        "TASK_RUN_COMPLETED",
        "TASK_RUN_FAILED",
        "TASK_RUN_CANCELLED",
        "TASK_RUN_INTERRUPTED",
        "REACT_COMPLETED",
        "REACT_ERROR",
        "REACT_CANCELLED",
    }
)


def _event_key(value: Any) -> str:
    return str(value or "").strip().replace("-", "_").upper()


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload")
    return value if isinstance(value, dict) else {}


def _call_id(row: dict[str, Any], payload: dict[str, Any]) -> str:
    for value in (
        row.get("item_id"),
        payload.get("tool_call_id"),
        payload.get("tool_use_id"),
        payload.get("call_id"),
        payload.get("id"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    # An id is still required for an orphaned provider event.  The row id is
    # durable and unique within the store, unlike an inferred tool name.
    return f"event:{row.get('id')}"


def _tool_name(payload: dict[str, Any]) -> str:
    for key in ("tool", "tool_name", "name"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def _status(payload: dict[str, Any], *, default: str) -> str:
    value = str(payload.get("status") or "").strip().lower()
    if value in {"success", "completed", "complete", "ok"}:
        return "completed"
    if value in {"error", "failed", "failure", "rejected"}:
        return "failed"
    if value in {"cancelled", "canceled", "interrupted", "paused"}:
        return "cancelled"
    return default


def build_execution_trace(
    events: list[dict[str, Any]],
    *,
    thread_id: str | None = None,
    turn_id: str | None = None,
    task_id: str | None = None,
    agent_id: str | None = None,
) -> dict[str, Any]:
    """Return a bounded, deterministic ``octopus.execution_trace.v1`` view."""

    ordered = sorted(events, key=lambda row: (str(row.get("ts") or ""), int(row.get("id") or 0)))
    engine = ""
    model = ""
    steps: dict[str, dict[str, Any]] = {}
    terminal: dict[str, Any] | None = None
    orphan_ends = 0

    for row in ordered:
        kind = _event_key(row.get("event_type"))
        payload = _payload(row)
        engine = engine or str(payload.get("engine") or "").strip().lower()
        model = model or str(payload.get("model") or "").strip()
        if kind in _START_EVENTS:
            call_id = _call_id(row, payload)
            step = steps.get(call_id)
            if step is None:
                step = {
                    "sequence": len(steps),
                    "call_id": call_id,
                    "tool": _tool_name(payload),
                    "input": payload.get("input", payload.get("input_preview")),
                    "output": None,
                    "status": "running",
                    "started_at": row.get("ts"),
                    "ended_at": None,
                    "duration_ms": None,
                    "event_ids": [],
                }
                steps[call_id] = step
            step["event_ids"].append(row.get("id"))
            continue
        if kind in _END_EVENTS:
            call_id = _call_id(row, payload)
            step = steps.get(call_id)
            if step is None:
                orphan_ends += 1
                step = {
                    "sequence": len(steps),
                    "call_id": call_id,
                    "tool": _tool_name(payload),
                    "input": None,
                    "output": None,
                    "status": "unknown",
                    "started_at": None,
                    "ended_at": None,
                    "duration_ms": None,
                    "event_ids": [],
                }
                steps[call_id] = step
            step["tool"] = _tool_name(payload)
            step["output"] = payload.get("output", payload.get("output_preview"))
            step["status"] = _status(payload, default="completed")
            step["ended_at"] = row.get("ts")
            duration = payload.get("duration_ms")
            step["duration_ms"] = duration if isinstance(duration, int) else None
            step["event_ids"].append(row.get("id"))
            continue
        if kind in _TERMINAL_EVENTS:
            raw_status = str(payload.get("status") or "").strip().lower()
            if kind == "REACT_COMPLETED":
                raw_status = "completed" if payload.get("success") is not False else "failed"
            if kind in {"REACT_ERROR", "TASK_RUN_FAILED"}:
                raw_status = "failed"
            if kind in {"REACT_CANCELLED", "TASK_RUN_CANCELLED", "TASK_RUN_INTERRUPTED"}:
                raw_status = "cancelled"
            terminal = {
                "status": raw_status or "completed",
                "reason": payload.get("reason")
                or payload.get("terminated_reason")
                or payload.get("outcome_reason")
                or payload.get("message"),
                "event_id": row.get("id"),
                "ts": row.get("ts"),
            }

    trace_steps = list(steps.values())
    orphan_starts = sum(1 for step in trace_steps if step["status"] == "running")
    terminal = terminal or {"status": "running", "reason": None, "event_id": None, "ts": None}
    return {
        "schema": "octopus.execution_trace.v1",
        "trace_id": f"turn:{turn_id}" if turn_id else None,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "task_id": task_id,
        "agent_id": agent_id,
        "engine": engine or "unknown",
        "model": model or None,
        "steps": trace_steps,
        "outcome": terminal,
        "integrity": {
            "event_count": len(ordered),
            "tool_start_count": sum(
                1 for row in ordered if _event_key(row.get("event_type")) in _START_EVENTS
            ),
            "tool_end_count": sum(
                1 for row in ordered if _event_key(row.get("event_type")) in _END_EVENTS
            ),
            "orphan_start_count": orphan_starts,
            "orphan_end_count": orphan_ends,
            "has_terminal": terminal["status"] != "running",
            "complete": terminal["status"] != "running" and orphan_starts == 0 and orphan_ends == 0,
        },
    }


__all__ = ["build_execution_trace"]
