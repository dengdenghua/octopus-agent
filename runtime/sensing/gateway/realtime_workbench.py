"""Workbench snapshot + workspace-focus helpers for the realtime runtime.

Pure presentation logic split out of ``realtime_cerebrum.py``: translate
todo previews and tool items into ``AgentPhaseSnapshot`` /
``WorkbenchSnapshotV2`` / ``WorkspaceFocus`` payloads the frontend
renders as the workbench. No I/O, no runtime state.
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any, Literal

from runtime.protocol import (
    AgentPhaseSnapshot,
    CommandExecutionItem,
    FileChangeItem,
    TurnStatus,
    WorkbenchSnapshotV2,
    WorkspaceFocus,
)


def _phases_from_todo_preview(
    preview: Any,
    *,
    active_item_id: str | None = None,
) -> list[AgentPhaseSnapshot] | None:
    data = _coerce_preview_record(preview)
    if data is None:
        return None
    raw = data.get("items") or data.get("todos") or data.get("plan")
    if not isinstance(raw, list) or len(raw) < 2:
        return None
    parsed: list[tuple[str, str]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        title = _first_string(
            entry,
            ("activeForm", "active_form", "content", "text", "title", "task"),
        )
        if not title:
            continue
        parsed.append((title, _todo_phase_status(entry.get("status"))))
    if len(parsed) < 2:
        return None
    total = len(parsed)
    return [
        AgentPhaseSnapshot(
            id=f"todo-phase:{index}",
            index=index + 1,
            total=total,
            title=_phase_title(title),
            status=status,  # type: ignore[arg-type]
            active_item_id=active_item_id if status == "running" else None,
        )
        for index, (title, status) in enumerate(parsed)
    ]


def _phases_with_active_item(
    phases: list[AgentPhaseSnapshot],
    workspace_focus: WorkspaceFocus | None,
) -> list[AgentPhaseSnapshot]:
    if workspace_focus is None:
        return list(phases)
    return [
        phase.model_copy(update={"active_item_id": workspace_focus.item_id})
        if phase.status == "running"
        else phase
        for phase in phases
    ]


def _terminal_workbench_phases(
    phases: list[AgentPhaseSnapshot],
    terminal_status: TurnStatus,
) -> list[AgentPhaseSnapshot]:
    if terminal_status == TurnStatus.COMPLETED:
        return [
            phase.model_copy(update={"status": "done", "active_item_id": None})
            if phase.status in {"pending", "running", "waiting_approval"}
            else phase.model_copy(update={"active_item_id": None})
            for phase in phases
        ]
    if terminal_status == TurnStatus.FAILED:
        marked = False
        terminal_phases: list[AgentPhaseSnapshot] = []
        for phase in phases:
            if phase.status == "done":
                terminal_phases.append(phase.model_copy(update={"active_item_id": None}))
                continue
            if not marked:
                marked = True
                terminal_phases.append(
                    phase.model_copy(update={"status": "error", "active_item_id": None})
                )
                continue
            terminal_phases.append(phase.model_copy(update={"active_item_id": None}))
        return terminal_phases
    if terminal_status == TurnStatus.INTERRUPTED:
        return [
            phase.model_copy(update={"active_item_id": None})
            if phase.status != "running"
            else phase.model_copy(update={"status": "waiting_approval", "active_item_id": None})
            for phase in phases
        ]
    return list(phases)


def _workbench_snapshot(
    *,
    version: int,
    phases: list[AgentPhaseSnapshot],
    workspace_focus: WorkspaceFocus | None,
) -> WorkbenchSnapshotV2:
    current_phase = _current_workbench_phase(phases)
    current_item_id = (
        workspace_focus.item_id
        if workspace_focus is not None
        else current_phase.active_item_id
        if current_phase is not None
        else None
    )
    return WorkbenchSnapshotV2(
        version=version,
        status=_workbench_status(phases),
        phases=phases,
        current_phase_id=current_phase.id if current_phase is not None else None,
        current_item_id=current_item_id,
        workspace_focus=workspace_focus,
    )


def _workbench_status(
    phases: list[AgentPhaseSnapshot],
) -> Literal["pending", "running", "done", "error", "waiting_approval"]:
    if any(phase.status == "error" for phase in phases):
        return "error"
    if any(phase.status == "waiting_approval" for phase in phases):
        return "waiting_approval"
    if any(phase.status == "running" for phase in phases):
        return "running"
    if phases and all(phase.status == "done" for phase in phases):
        return "done"
    return "pending" if phases else "running"


def _current_workbench_phase(
    phases: list[AgentPhaseSnapshot],
) -> AgentPhaseSnapshot | None:
    for status in ("running", "waiting_approval", "error", "pending"):
        for phase in phases:
            if phase.status == status:
                return phase
    return phases[-1] if phases else None


def _coerce_preview_record(preview: Any) -> dict[str, Any] | None:
    if isinstance(preview, dict):
        return preview
    if isinstance(preview, str) and preview.strip():
        with contextlib.suppress(json.JSONDecodeError):
            parsed = json.loads(preview)
            if isinstance(parsed, dict):
                return parsed
    return None


def _todo_phase_status(value: Any) -> str:
    if value in ("completed", "done"):
        return "done"
    if value in ("in_progress", "running"):
        return "running"
    if value in ("blocked", "waiting_approval"):
        return "waiting_approval"
    if value in ("error", "failed"):
        return "error"
    return "pending"


def _phase_title(title: str) -> str:
    clean = re.sub(r"\s+", " ", title).strip()
    without_machine_prefix = re.sub(
        r"^(?:phase|阶段|step|步骤)\s*[\d一二三四五六七八九十]+(?:\.\d+)?\s*[:：.)、-]?\s*",
        "",
        clean,
        flags=re.IGNORECASE,
    ).strip()
    return without_machine_prefix or clean or "进行中"


def _workspace_focus_for_tool(item: CommandExecutionItem) -> WorkspaceFocus:
    preview = _coerce_preview_record(item.input_preview) or {}
    name = item.command or "tool"
    target = _first_string(
        preview,
        (
            "command",
            "cmd",
            "path",
            "file_path",
            "filepath",
            "url",
            "query",
            "pattern",
            "cwd",
        ),
    )
    lower = name.lower()
    if name == "todo_write":
        view = "trace"
        title = "Updating plan"
    elif re.search(r"shell|bash|terminal|cmd|exec|python|powershell|cli", lower):
        view = "terminal"
        title = f"Running {name}"
    elif re.search(r"browser|url|web|fetch|screenshot", lower):
        view = "browser"
        title = f"Browsing with {name}"
    elif re.search(r"edit|write|replace|patch|diff|create|delete|artifact", lower):
        view = "diff"
        title = f"Editing with {name}"
    else:
        view = "trace"
        title = name.replace("_", " ")
    return WorkspaceFocus(
        item_id=item.id,
        view=view,  # type: ignore[arg-type]
        title=title,
        subtitle=target or None,
    )


def _workspace_focus_for_file_change(item: FileChangeItem) -> WorkspaceFocus:
    first_path = item.changes[0].path if item.changes else ""
    title = f"Editing {first_path}" if first_path else "File changes"
    return WorkspaceFocus(
        item_id=item.id,
        view="diff",
        title=title,
        subtitle=first_path or None,
    )


def _first_string(record: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""
