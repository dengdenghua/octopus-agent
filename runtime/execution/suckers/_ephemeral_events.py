"""Event emission helpers for ephemeral sub-agent runs.

Split out from ``ephemeral_runner.py`` to keep that module under the
god-file line cap. Pure structural move — no behavior changes.

Contains:
    * ``_safe_ctx_emit`` — fire-and-forget wrapper around a caller-supplied
      event emitter (silently no-ops on ``None`` / exceptions).
    * ``_emit_sub_tool_event`` — best-effort push of a sub-agent tool
      event (start/end) to the active stream queue AND the genome journal.
    * ``_emit_subagent_lifecycle_event`` — best-effort push of a sub-agent
      lifecycle event (spawned/finished) to the genome journal.
"""

from __future__ import annotations

import contextlib
from typing import Any

__all__ = [
    "_emit_sub_tool_event",
    "_emit_subagent_lifecycle_event",
    "_safe_ctx_emit",
]


def _safe_ctx_emit(emitter: Any, event: dict) -> None:
    """Fire-and-forget call to a caller-supplied event emitter.

    Silently no-ops when ``emitter`` is ``None`` or raises. The runner
    must never crash because of a buggy emitter callback.
    """
    if emitter is None:
        return
    with contextlib.suppress(Exception):
        emitter(event)


def _emit_sub_tool_event(
    kind: str,
    *,
    role_id: str,
    tool_call: Any,
    iteration: int,
    output: str | None = None,
    is_error: bool = False,
    duration_ms: int | None = None,
) -> None:
    """Best-effort push of a sub-agent tool event to the active stream
    queue so the frontend LiveToolTimeline can nest it under the
    parent's ``call_agent_parallel`` / ``call_agent`` tool_use row.

    Wiring:
        * ``tool_bridge.stream_agentic_fallback`` stashes the stream
          queue on ``session.metadata["sub_tool_event_queue"]``
          AND the currently-running parent tool_use id on
          ``session.metadata["_active_parent_tool_use_id"]`` before
          invoking each handler.
        * Inside the sub-agent handler → ephemeral runner → here:
          we look up both and push a ``(kind, payload, None)`` tuple.
        * The active realtime bridge drains the tuple and emits the
          corresponding tool event.

    Silently no-ops when:
        * No session is bound (unit tests calling the runner directly)
        * No queue was stashed (older bootstrap paths)
        * Queue put fails (full / closed)

    The sub-agent keeps running regardless · losing telemetry beats
    deadlocking the worker thread.
    """
    try:
        from runtime.platform.process.session import current_session

        sess = current_session()
    except (ImportError, TypeError, AttributeError, OSError):  # noqa: BLE001
        return
    if sess is None:
        return
    meta = getattr(sess, "metadata", None) or {}
    if not isinstance(meta, dict):
        return
    q = meta.get("sub_tool_event_queue")
    parent_id = meta.get("_active_parent_tool_use_id") or ""
    payload: dict[str, Any] = {
        "id": getattr(tool_call, "id", "") or "",
        "name": getattr(tool_call, "name", "") or "",
        "input": getattr(tool_call, "input", {}) or {},
        "iteration": iteration,
        "parent_tool_use_id": parent_id,
        "sub_agent_role": role_id,
    }
    if kind == "sub_tool_end":
        # Truncate output preview · same 200-char cap as parent
        # loop's tool_end event so the SSE frame stays small.
        if output is not None:
            payload["output"] = str(output)[:200]
        payload["is_error"] = bool(is_error)
        payload["status"] = "error" if is_error else "success"
        if duration_ms is not None:
            payload["duration_ms"] = int(duration_ms)
    if q is not None:
        with contextlib.suppress(Exception):
            q.put_nowait((kind, payload, None))

    # ── Mirror to journal as well ───────────────────────────
    # The above queue path requires the SSE pump to have stashed a
    # queue in session.metadata — which only the agentic-fallback
    # code path does. Most production turns route through the
    # OpenAI-gateway worker which subscribes to the journal
    # instead. Writing a JournalEvent here surfaces sub-tool
    # progress on BOTH paths uniformly.
    journal = meta.get("journal")
    if journal is None:
        try:
            stack = meta.get("stack")
            if stack is not None:
                journal = getattr(stack, "journal", None)
        except (AttributeError, TypeError):  # noqa: BLE001
            journal = None
    if journal is None:
        return
    try:
        from runtime.memory.journal import (
            SubToolEndEvent,
            SubToolStartEvent,
        )

        task_id_obj = meta.get("task_id")
        if kind == "sub_tool_start":
            ev = SubToolStartEvent(
                task_id=task_id_obj,
                role_id=role_id,
                tool_call_id=str(getattr(tool_call, "id", "") or ""),
                tool_name=str(getattr(tool_call, "name", "") or ""),
                iteration=int(iteration),
                args_preview=str(payload.get("input") or "")[:200],
                parent_tool_use_id=parent_id or None,
            )
        else:
            ev = SubToolEndEvent(
                task_id=task_id_obj,
                role_id=role_id,
                tool_call_id=str(getattr(tool_call, "id", "") or ""),
                tool_name=str(getattr(tool_call, "name", "") or ""),
                iteration=int(iteration),
                is_error=bool(is_error),
                duration_ms=int(duration_ms or 0),
                output_preview=(output or "")[:200] if output else "",
                parent_tool_use_id=parent_id or None,
            )
        journal.write(ev)
    except (OSError, TypeError, ValueError):  # noqa: BLE001
        # Mirroring is best-effort; never break the runner.
        pass


def _emit_subagent_lifecycle_event(
    kind: str,
    payload: dict[str, Any] | None,
) -> None:
    """Best-effort push of a sub-agent lifecycle event to the genome
    journal so the realtime gateway / observability panel can render
    a sub-agent tile from the moment the agent spawns instead of
    waiting for its first ``sub_tool_*`` event.

    ``kind`` is ``"subagent_spawned"`` or ``"subagent_finished"``.
    ``payload`` mirrors the dict the bridge fires through its
    ``event_emitter`` (codename, avatar, role, prompt_preview, ok,
    duration_s, iteration_count, files_touched, error, status).

    Convention
    ----------
    Reuses the existing ``SubToolStartEvent`` / ``SubToolEndEvent``
    journal-event shape — same wire used by ``_emit_sub_tool_event``
    above — but stamps the ``tool_name`` with one of the
    ``ItemMarker`` magic strings (``__subagent_spawned__`` /
    ``__subagent_finished__``). Subscribers that don't care about
    lifecycle simply ignore the marker; the realtime gateway uses it
    to synthesise an ``McpToolCallItem`` the frontend's
    ``mcpItemToLiveEvent`` recognises and renders as a lifecycle tile.

    Silently no-ops when no session / journal is bound, so unit tests
    calling the bridge directly stay green. Empty / malformed
    payloads are tolerated — the helper coerces missing fields to
    safe defaults rather than raising.
    """
    import json as _json

    from runtime.protocol.items import ItemMarker

    payload = payload or {}
    try:
        from runtime.platform.process.session import current_session

        sess = current_session()
    except (ImportError, TypeError, AttributeError, OSError):  # noqa: BLE001
        return
    if sess is None:
        return
    meta = getattr(sess, "metadata", None) or {}
    if not isinstance(meta, dict):
        return
    journal = meta.get("journal")
    if journal is None:
        try:
            stack = meta.get("stack")
            if stack is not None:
                journal = getattr(stack, "journal", None)
        except (AttributeError, TypeError):  # noqa: BLE001
            journal = None
    if journal is None:
        return

    role_id = str(payload.get("role") or payload.get("agent_id") or "")
    parent_id = meta.get("_active_parent_tool_use_id") or None
    task_id_obj = meta.get("task_id")
    try:
        args_preview = _json.dumps(
            {
                "codename": payload.get("codename"),
                "avatar": payload.get("avatar"),
                "role": payload.get("role"),
                "agent_id": payload.get("agent_id"),
                "prompt_preview": payload.get("prompt_preview"),
                "use_cheap_model": payload.get("use_cheap_model"),
                "started_at": payload.get("started_at"),
            },
            ensure_ascii=False,
            default=str,
        )[:1000]
    except (TypeError, ValueError):
        args_preview = ""

    try:
        from runtime.memory.journal import (
            SubToolEndEvent,
            SubToolStartEvent,
        )

        if kind == "subagent_spawned":
            ev = SubToolStartEvent(
                task_id=task_id_obj,
                role_id=role_id,
                tool_call_id=str(payload.get("agent_id") or ""),
                tool_name=ItemMarker.SUBAGENT_SPAWNED.value,
                iteration=0,
                args_preview=args_preview,
                parent_tool_use_id=parent_id,
            )
        elif kind == "subagent_finished":
            try:
                output_preview = _json.dumps(
                    {
                        "codename": payload.get("codename"),
                        "avatar": payload.get("avatar"),
                        "role": payload.get("role"),
                        "agent_id": payload.get("agent_id"),
                        "ok": payload.get("ok"),
                        "duration_s": payload.get("duration_s"),
                        "iteration_count": payload.get("iteration_count"),
                        "files_touched": payload.get("files_touched"),
                        "error": payload.get("error"),
                        "status": payload.get("status"),
                    },
                    ensure_ascii=False,
                    default=str,
                )[:1000]
            except (TypeError, ValueError):
                output_preview = ""
            ok = bool(payload.get("ok", True))
            duration_s = payload.get("duration_s") or 0
            try:
                duration_ms = int(float(duration_s) * 1000)
            except (TypeError, ValueError):
                duration_ms = 0
            ev = SubToolEndEvent(
                task_id=task_id_obj,
                role_id=role_id,
                tool_call_id=str(payload.get("agent_id") or ""),
                tool_name=ItemMarker.SUBAGENT_FINISHED.value,
                iteration=int(payload.get("iteration_count") or 0),
                is_error=not ok,
                duration_ms=duration_ms,
                output_preview=output_preview,
                parent_tool_use_id=parent_id,
            )
        else:
            return
        journal.write(ev)
    except (OSError, TypeError, ValueError):  # noqa: BLE001
        # Lifecycle mirroring is best-effort; never break the run.
        pass
