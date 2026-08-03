"""Progress and SSE-stream endpoints for the observability router.

Pure structural extraction from ``_observability_router_factory.py`` (no logic
changes). Builder that registers ``/api/progress`` and the SSE feeds
(``/api/stream``, ``/api/preview/stream``, ``/api/files/stream``) onto the
router. The ``TaskProgressTracker`` is built here per router instance, as in
the original factory.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.sensing._fastapi_guard import require_fastapi

from ._observability_helpers import (
    _SSE_HEADERS,
    HTTPException,
    StreamingResponse,
    _safe_put,
    _serialize_file_rollback_event,
    _snapshot_to_dict,
)
from ._observability_state import ObservabilityContext


def register_progress_stream_endpoints(router: Any, ctx: ObservabilityContext) -> None:
    """Register the progress + SSE stream endpoints."""
    require_fastapi(__name__)

    journal = ctx.journal

    # Progress tracker owns incremental O(N_tasks) snapshots · build
    # once per app, not per request.
    from runtime.memory.journal import TaskProgressTracker

    progress_tracker = TaskProgressTracker(journal)

    # ─── /api/progress ──────────────────────────────────────
    @router.get("/api/progress")
    def api_progress(
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if task_id is not None:
            snap = progress_tracker.get(task_id)
            if snap is None:
                raise HTTPException(
                    404,
                    f"no events for task_id={task_id!r}",
                )
            return _snapshot_to_dict(snap)

        snaps = progress_tracker.snapshots
        return {
            "count": progress_tracker.count(),
            "running": progress_tracker.running_count(),
            "tasks": [_snapshot_to_dict(s) for s in snaps[:50]],
        }

    def _event_base_payload(event: Any) -> dict[str, Any]:
        return {
            "event_type": event.event_type,
            "ts": event.ts.isoformat(),
            "task_id": (str(event.task_id) if event.task_id else None),
            "arm_id": event.arm_id,
        }

    def _enrich_event_payload(event: Any) -> dict[str, Any]:
        from runtime.memory.journal import (
            BrowserArtifactEvent,
            FileOpEvent,
            FileRollbackEvent,
            PreviewRefreshEvent,
            SubToolEndEvent,
            SubToolStartEvent,
        )

        payload = _event_base_payload(event)
        if isinstance(event, FileOpEvent):
            payload.update(
                {
                    "path": event.path,
                    "action": event.action,
                    "bytes_delta": event.bytes_delta,
                    "old_size": event.old_size,
                    "new_size": event.new_size,
                    "sucker_id": event.sucker_id,
                    "diff": event.diff,
                }
            )
        elif isinstance(event, FileRollbackEvent):
            payload.update(_serialize_file_rollback_event(event))
        elif isinstance(event, PreviewRefreshEvent):
            payload.update(
                {
                    "target": event.target,
                    "trigger_path": event.trigger_path,
                    "reason": event.reason,
                }
            )
        elif isinstance(event, SubToolStartEvent):
            payload.update(
                {
                    "role_id": event.role_id,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "iteration": event.iteration,
                    "args_preview": event.args_preview,
                    "parent_tool_use_id": event.parent_tool_use_id,
                }
            )
        elif isinstance(event, SubToolEndEvent):
            payload.update(
                {
                    "role_id": event.role_id,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "iteration": event.iteration,
                    "is_error": event.is_error,
                    "duration_ms": event.duration_ms,
                    "output_preview": event.output_preview,
                    "parent_tool_use_id": event.parent_tool_use_id,
                }
            )
        elif isinstance(event, BrowserArtifactEvent):
            payload.update(
                {
                    "kind": event.kind,
                    "url": event.url,
                    "filename": event.filename,
                    "caption": event.caption,
                    "mime_type": event.mime_type,
                    "width": event.width,
                    "height": event.height,
                    "thread_id": event.thread_id,
                }
            )
        return payload

    # ─── /api/stream (SSE) ──────────────────────────────────
    @router.get("/api/stream")
    def api_stream() -> Any:
        import queue as _queue

        q: _queue.Queue[Any] = _queue.Queue(maxsize=500)
        unsubscribe = journal.subscribe(
            lambda event: _safe_put(q, event),
        )

        def _gen():
            try:
                yield f": connected · {len(journal)} events so far\n\n"
                while True:
                    try:
                        event = q.get(timeout=15.0)
                    except _queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    payload = _enrich_event_payload(event)
                    yield f"data: {json.dumps(payload)}\n\n"
            finally:
                unsubscribe()

        return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)

    @router.get("/api/preview/stream")
    def api_preview_stream() -> Any:
        import queue as _queue

        q: _queue.Queue[Any] = _queue.Queue(maxsize=200)

        def _only_preview(event: Any) -> None:
            if getattr(event, "event_type", "") == "preview_refresh":
                _safe_put(q, event)

        unsubscribe = journal.subscribe(_only_preview)

        def _gen():
            try:
                try:
                    from runtime.memory.journal import PreviewRefreshEvent

                    recent = [e for e in journal.read_all() if isinstance(e, PreviewRefreshEvent)][
                        -5:
                    ]
                    for ev in recent:
                        payload = _enrich_event_payload(ev)
                        yield (f"event: preview_refresh\ndata: {json.dumps(payload)}\n\n")
                except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
                    pass

                yield ": connected\n\n"
                while True:
                    try:
                        event = q.get(timeout=15.0)
                    except _queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    payload = _enrich_event_payload(event)
                    yield (f"event: preview_refresh\ndata: {json.dumps(payload)}\n\n")
            finally:
                unsubscribe()

        return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)

    @router.get("/api/files/stream")
    def api_files_stream() -> Any:
        import queue as _queue

        q: _queue.Queue[Any] = _queue.Queue(maxsize=500)

        def _only_file_op(event: Any) -> None:
            if getattr(event, "event_type", "") == "file_op":
                _safe_put(q, event)

        unsubscribe = journal.subscribe(_only_file_op)

        def _gen():
            try:
                try:
                    from runtime.memory.journal import FileOpEvent

                    recent = [e for e in journal.read_all() if isinstance(e, FileOpEvent)][-20:]
                    for ev in recent:
                        payload = _enrich_event_payload(ev)
                        yield (f"event: file_op\ndata: {json.dumps(payload)}\n\n")
                except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
                    pass

                yield ": connected\n\n"
                while True:
                    try:
                        event = q.get(timeout=15.0)
                    except _queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    payload = _enrich_event_payload(event)
                    yield (f"event: file_op\ndata: {json.dumps(payload)}\n\n")
            finally:
                unsubscribe()

        return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)


__all__ = ["register_progress_stream_endpoints"]
