"""Bounded, principal-scoped evidence from actual engine execution.

Configuration readiness is not a cloud health check. These observations are
diagnostics, never authorization or a guarantee that the next request succeeds.
No prompts, results, credentials or upstream error text are retained.
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any

_TTL = 300.0
_MAX_ENTRIES = 512
_lock = threading.Lock()
_records: OrderedDict[tuple[str, str, str, str], dict[str, Any]] = OrderedDict()
_ALIASES = {"opencode.websearch": "web_search", "opencode.webfetch": "web_fetch"}


def normalize_engine_event(event: dict[str, Any], engine: str) -> dict[str, Any]:
    if event.get("type") not in {"tool_start", "tool_end"}:
        return event
    native = str(event.get("tool_name") or "")
    if native not in _ALIASES and native not in {"web_search", "web_fetch"}:
        return event
    return {**event, "tool_name": _ALIASES.get(native, native), "execution_engine": engine,
            "native_tool_name": native}


def observe_engine_event(event: dict[str, Any], engine: str, model: str = "") -> dict[str, Any]:
    from runtime.execution.request import current_execution_request
    normalized = normalize_engine_event(event, engine)
    request = current_execution_request()
    if request is None or request.task.execution_engine != engine:
        return normalized
    capability = ""
    success = False
    if event.get("type") == "react_completed":
        capability, success = "chat", event.get("success") is True
    elif event.get("type") == "tool_end":
        if event.get("status") in {"cancelled", "rejected"}:
            return normalized
        capability = "web_search" if normalized.get("tool_name") == "web_search" else "tools"
        # Codex uses status, OpenCode additionally supplies a boolean.
        success = (event.get("success") is True if "success" in event
                   else event.get("status") == "success")
    if not capability:
        return normalized
    task = request.task
    receipt = event.get("completion_receipt") or {}
    resolved_model = str(receipt.get("model") or model)[:160]
    key = (task.tenant_id or "local", task.actor_id or "local", engine, capability)
    with _lock:
        _records[key] = {"state": "verified" if success else "failed", "model": resolved_model or None,
                         "checked_at": time.time(), "expires": time.monotonic() + _TTL}
        _records.move_to_end(key)
        while len(_records) > _MAX_ENTRIES:
            _records.popitem(last=False)
    return normalized


def engine_observations(scope: Any, engine: str) -> dict[str, Any]:
    tenant = getattr(scope, "tenant_id", None) or "local"
    actor = getattr(scope, "actor_id", None) or "local"
    now = time.monotonic()
    with _lock:
        result = {}
        for capability in ("chat", "web_search", "tools"):
            record = _records.get((tenant, actor, engine, capability))
            result[capability] = ({k: v for k, v in record.items() if k != "expires"}
                                  if record and record["expires"] > now else {"state": "untested"})
    return {"capability_checks": result, "check_ttl_seconds": int(_TTL), "checks_are_authorization": False}
