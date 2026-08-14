"""Best-effort journal mirrors for long-running orchestration activity.

Workflow runs and background jobs outlive any single streaming connection;
writing their lifecycle rows into the journal keeps the durable timeline
(``/api/journal/timeline``) reconstructable from the log alone — the dsh
session-log invariant applied to the settlement bridge. Writing is always
best-effort: a missing journal, an absent session, or a write failure never
breaks the run.

Callers may supply explicit attribution (captured at start time for jobs
that settle outside any turn); otherwise the ambient ``journal_context`` and
the active session's metadata are used.
"""

from __future__ import annotations

from typing import Any

from runtime.platform.process.session import current_session

from ._journal_models import (
    JobChangeEvent,
    WorkflowEndEvent,
    WorkflowProgressEvent,
    WorkflowStartEvent,
)
from .journal_context import current_agent_id, current_conversation_id


def _resolve_journal() -> Any | None:
    session = current_session()
    if session is None:
        return None
    metadata = getattr(session, "metadata", None) or {}
    journal = metadata.get("journal")
    if journal is not None:
        return journal
    stack = metadata.get("stack")
    if stack is not None:
        return getattr(stack, "journal", None)
    return None


def _ambient_task_id() -> Any | None:
    session = current_session()
    if session is None:
        return None
    return (getattr(session, "metadata", None) or {}).get("task_id")


def capture_attribution() -> dict[str, Any]:
    """Snapshot the ambient journal attribution for later writes (jobs that
    settle after the turn, worker-thread observers)."""
    return {
        "task_id": _ambient_task_id(),
        "agent_id": current_agent_id(),
        "conversation_id": current_conversation_id(),
    }


def _write(
    event_factory: Any,
    *,
    task_id: Any = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    journal = _resolve_journal()
    if journal is None:
        return False
    try:
        journal.write(
            event_factory(
                task_id=task_id if task_id is not None else _ambient_task_id(),
                agent_id=(
                    agent_id if agent_id is not None else current_agent_id()
                ),
                conversation_id=(
                    conversation_id
                    if conversation_id is not None
                    else current_conversation_id()
                ),
            )
        )
        return True
    except Exception:  # noqa: BLE001 — journaling is best-effort
        return False


def write_workflow_start(
    *,
    run_id: str,
    name: str,
    description: str = "",
    task_id: Any = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    """Journal a workflow run start (dsh workflow ``on_start``)."""
    return _write(
        lambda **kw: WorkflowStartEvent(
            run_id=run_id, name=name, description=description, **kw
        ),
        task_id=task_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )


def write_workflow_progress(
    *,
    run_id: str,
    kind: str,
    text: str = "",
    agent_seq: int = 0,
    agent_label: str = "",
    task_id: Any = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    """Journal one workflow narration row (phase / log / agent lifecycle)."""
    return _write(
        lambda **kw: WorkflowProgressEvent(
            run_id=run_id,
            kind=kind,
            text=text,
            agent_seq=agent_seq,
            agent_label=agent_label,
            **kw,
        ),
        task_id=task_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )


def write_workflow_end(
    *,
    run_id: str,
    stop_reason: str,
    agents_started: int = 0,
    error: str = "",
    task_id: Any = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    """Journal a workflow run settlement (dsh workflow ``on_end``)."""
    return _write(
        lambda **kw: WorkflowEndEvent(
            run_id=run_id,
            stop_reason=stop_reason,
            agents_started=agents_started,
            error=error,
            **kw,
        ),
        task_id=task_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )


def write_job_change(
    *,
    job_id: str,
    kind: str,
    label: str,
    status: str,
    detail: str = "",
    task_id: Any = None,
    agent_id: str | None = None,
    conversation_id: str | None = None,
) -> bool:
    """Journal one background-job lifecycle transition (dsh ``tool-jobs``)."""
    return _write(
        lambda **kw: JobChangeEvent(
            job_id=job_id,
            kind=kind,
            label=label,
            status=status,
            detail=detail,
            **kw,
        ),
        task_id=task_id,
        agent_id=agent_id,
        conversation_id=conversation_id,
    )


__all__ = [
    "capture_attribution",
    "write_job_change",
    "write_workflow_end",
    "write_workflow_progress",
    "write_workflow_start",
]
