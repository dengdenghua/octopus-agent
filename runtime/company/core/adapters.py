from __future__ import annotations

from typing import Any

from .models import ProjectTask


def project_task_to_team_task_payload(
    task: ProjectTask,
    *,
    room_id: str | None = None,
    sop_template: str = "",
) -> dict[str, Any]:
    """Map a Company ProjectTask into the existing team_tasks wire shape.

    The Company domain owns long-term planning fields. The team_tasks
    domain owns executable work units. Keeping this as a pure payload
    adapter lets either side evolve without import cycles or router calls.
    """
    return {
        "room_id": room_id or task.project_id,
        "title": task.title,
        "description": task.description,
        "sop_template": sop_template,
        "assignees": [
            {
                "kind": "agent" if assignee.kind == "agent" else "participant",
                "ref": assignee.ref,
            }
            for assignee in task.assignees
            if assignee.kind in {"agent", "participant"}
        ],
    }


__all__ = ["project_task_to_team_task_payload"]
