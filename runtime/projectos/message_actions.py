"""Turn collaboration-room messages into authoritative Project OS objects.

The chat transcript is the coordination timeline, not a second project store.
Every action in this module writes Project OS first and only then enriches the
source message / collaboration read projection.  Deterministic action, task,
event, and system-card ids make retries safe for browser/network clients.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import Any

from runtime.memory.cowork.ids import optional_cowork_id, require_cowork_id
from runtime.projectos.cowork_bridge import project_task_to_collaboration
from runtime.projectos.model import ROLE_FOR_TASK, Task

_ACTION_ALIASES = {
    "link_milestone": "link_milestone",
    "create_item": "create_item",
    "create_task": "create_item",
    "create_project_task": "create_item",
    "record_decision": "record_decision",
    "publish_artifact": "publish_artifact",
}
_TASK_TYPES = frozenset({"design", "code", "research", "analysis", "review"})
_PRIORITIES = frozenset({"P0", "P1", "P2", "P3"})


class MessageProjectActionError(ValueError):
    """Expected API error raised while applying a message action."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = int(status_code)
        self.detail = detail


def _stable_id(prefix: str, *parts: Any) -> str:
    payload = json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}-{digest}"


def _source(message: dict[str, Any], *, thread_id: str, room_id: str) -> dict[str, Any]:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    return {
        "schema": "octopus.projectos.message_source.v1",
        "thread_id": thread_id,
        "room_id": room_id,
        "message_seq": int(message.get("seq") or 0),
        "source_message_id": str(metadata.get("source_message_id") or ""),
        "participant_id": str(message.get("participant_id") or ""),
        "display_name": str(message.get("display_name") or ""),
        "text": str(message.get("text") or ""),
    }


def _bound_project(project_store: Any, thread_id: str, requested_id: str) -> Any:
    project = project_store.project_for_thread(thread_id)
    if project is None:
        raise MessageProjectActionError(
            409,
            "collaboration session is not bound to a Project OS project",
        )
    if requested_id and requested_id != project.id:
        raise MessageProjectActionError(409, "requested project is not bound to this session")
    return project


def _project_milestone(project_store: Any, project: Any, milestone_id: str) -> Any:
    safe_id = optional_cowork_id(milestone_id, label="milestone_id")
    if not safe_id:
        raise MessageProjectActionError(400, "milestone_id is required for this action")
    milestone = project_store.get_milestone(safe_id)
    if milestone is None or safe_id not in set(project.milestone_ids):
        raise MessageProjectActionError(404, "milestone not found in the bound project")
    return milestone


def _event_once(
    project_store: Any,
    project_id: str,
    *,
    event_id: str,
    kind: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    existing = project_store.get_event(event_id)
    if existing is not None:
        if existing.get("project_id") != project_id or existing.get("kind") != kind:
            raise MessageProjectActionError(409, "project action id is already in use")
        return existing, False
    try:
        return (
            project_store.append_event(
                project_id,
                kind=kind,
                payload=payload,
                event_id=event_id,
            ),
            True,
        )
    except sqlite3.IntegrityError:
        # A concurrent retry may have won the unique event-id race.
        existing = project_store.get_event(event_id)
        if existing is not None and existing.get("project_id") == project_id:
            return existing, False
        raise


def _action_receipt(
    *,
    action_id: str,
    action: str,
    project_id: str,
    target: dict[str, Any],
    event_id: str,
) -> dict[str, Any]:
    return {
        "id": action_id,
        "action": action,
        "project_id": project_id,
        "target": target,
        "event_id": event_id,
        "applied_at": datetime.now(UTC).isoformat(),
    }


def _entity_ref(kind: str, entity_id: str, project_id: str, **extra: Any) -> dict[str, Any]:
    normalized_extra = {
        key: (str(value)[:256] if key == "label" else value)
        for key, value in extra.items()
        if value not in (None, "")
    }
    return {
        "kind": kind,
        "id": require_cowork_id(entity_id, label=f"{kind} id"),
        "project_id": project_id,
        **normalized_extra,
    }


def _existing_receipt(message: dict[str, Any], action_id: str) -> dict[str, Any] | None:
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    actions = metadata.get("project_actions")
    if not isinstance(actions, list):
        return None
    return next(
        (
            dict(item)
            for item in actions
            if isinstance(item, dict) and str(item.get("id") or "") == action_id
        ),
        None,
    )


def apply_message_project_action(
    project_store: Any,
    collaboration_store: Any,
    *,
    thread_id: str,
    room_id: str,
    message: dict[str, Any],
    body: dict[str, Any],
    actor: str,
) -> dict[str, Any]:
    """Apply one idempotent message action and return its structured receipt."""

    raw_action = str(body.get("action") or "").strip().lower()
    action = _ACTION_ALIASES.get(raw_action)
    if action is None:
        raise MessageProjectActionError(
            400,
            "action must be link_milestone | create_item | record_decision | publish_artifact",
        )
    project = _bound_project(
        project_store,
        thread_id,
        str(body.get("project_id") or "").strip(),
    )
    source = _source(message, thread_id=thread_id, room_id=room_id)
    action_seed = str(body.get("action_id") or "").strip() or {
        key: value
        for key, value in body.items()
        if key not in {"action_id", "run"} and value not in (None, "", [], {})
    }
    action_id = _stable_id("MA", thread_id, source["message_seq"], action, action_seed)
    existing_receipt = _existing_receipt(message, action_id)
    if existing_receipt is not None:
        card = collaboration_store.message_by_source_id(
            thread_id,
            f"project-action:{action_id}",
        )
        return {
            "ok": True,
            "replayed": True,
            "created": False,
            "action_id": action_id,
            "action": action,
            "project_id": project.id,
            "target": existing_receipt.get("target") or {},
            "receipt": existing_receipt,
            "source_message": message,
            "system_card_message": card,
        }

    milestone = None
    if action in {"link_milestone", "create_item"}:
        milestone = _project_milestone(
            project_store,
            project,
            str(body.get("milestone_id") or ""),
        )

    task = None
    event: dict[str, Any]
    created = False
    if action == "create_item":
        if project.status in {"done", "failed"}:
            raise MessageProjectActionError(409, "cannot add an item to a terminal project")
        if milestone.status in {"done", "failed"}:
            raise MessageProjectActionError(409, "cannot add an item to a terminal milestone")
        task_type = str(body.get("task_type") or "analysis").strip().lower()
        if task_type not in _TASK_TYPES:
            raise MessageProjectActionError(400, "invalid task_type")
        priority = str(body.get("priority") or "P2").strip().upper()
        if priority not in _PRIORITIES:
            raise MessageProjectActionError(400, "priority must be P0 | P1 | P2 | P3")
        title = str(body.get("title") or source["text"]).strip()
        if not title:
            raise MessageProjectActionError(400, "title is required for create_item")
        task_id = optional_cowork_id(body.get("item_id"), label="item_id") or _stable_id(
            "PT",
            action_id,
        )
        dependencies = [
            require_cowork_id(item, label="depends_on task id")
            for item in (body.get("depends_on") or [])
        ]
        known_task_ids = {item.id for item in project_store.tasks_for_milestone(milestone.id)}
        if any(item not in known_task_ids for item in dependencies):
            raise MessageProjectActionError(400, "depends_on contains a task outside the milestone")
        assigned_role = optional_cowork_id(
            body.get("assigned_role") or ROLE_FOR_TASK.get(task_type, "engineer"),
            label="assigned_role",
        )
        assigned_agent = optional_cowork_id(
            body.get("assigned_agent"),
            label="assigned_agent",
        )
        try:
            estimate = max(0.0, float(body.get("estimate") or 0))
        except (TypeError, ValueError) as exc:
            raise MessageProjectActionError(400, "estimate must be a non-negative number") from exc
        candidate = Task(
            id=task_id,
            milestone_id=milestone.id,
            type=task_type,  # type: ignore[arg-type]
            goal=title,
            assigned_role=assigned_role or ROLE_FOR_TASK.get(task_type, "engineer"),
            assigned_agent=assigned_agent,
            priority=priority,
            estimate=estimate,
            due_at=str(body.get("due_at") or "").strip(),
            acceptance_criteria=[
                str(item).strip()
                for item in (body.get("acceptance_criteria") or [])
                if str(item).strip()
            ],
            depends_on=dependencies,
            input={
                "description": str(body.get("description") or "").strip(),
                "source_message": source,
            },
        )
        try:
            task, created = project_store.add_task_to_milestone(project.id, candidate)
        except PermissionError as exc:
            raise MessageProjectActionError(404, "project not found") from exc
        except ValueError as exc:
            raise MessageProjectActionError(409, str(exc)) from exc
        if not created:
            existing_source = (
                task.input.get("source_message") if isinstance(task.input, dict) else None
            )
            if existing_source != source:
                raise MessageProjectActionError(409, "item_id already belongs to another source")
        target = _entity_ref(
            "task",
            task.id,
            project.id,
            milestone_id=milestone.id,
            task_id=task.id,
            label=task.goal,
        )
        event_id = _stable_id("EV-MA", action_id)
        event, event_created = _event_once(
            project_store,
            project.id,
            event_id=event_id,
            kind="project.task_created_from_message",
            payload={
                "actor": actor,
                "milestone_id": milestone.id,
                "task": task.to_dict(),
                "source_message": source,
            },
        )
        created = created or event_created
        project_task_to_collaboration(
            collaboration_store,
            session_id=thread_id,
            room_id=room_id,
            project_id=project.id,
            milestone_id=milestone.id,
            task=task,
            tenant_id=str(project.tenant_id or ""),
        )
        card_title = f"已创建事项 · {task.goal}"
        card_summary = str(body.get("description") or source["text"]).strip()
        card_status = task.status
    elif action == "link_milestone":
        target = _entity_ref(
            "milestone",
            milestone.id,
            project.id,
            milestone_id=milestone.id,
            label=milestone.name,
        )
        event_id = _stable_id("EV-MA", action_id)
        event, created = _event_once(
            project_store,
            project.id,
            event_id=event_id,
            kind="project.message_linked",
            payload={
                "actor": actor,
                "milestone_id": milestone.id,
                "source_message": source,
            },
        )
        card_title = f"已关联里程碑 · {milestone.name}"
        card_summary = source["text"]
        card_status = milestone.status
    elif action == "record_decision":
        decision = str(body.get("decision") or body.get("title") or "").strip()
        if not decision:
            raise MessageProjectActionError(400, "decision is required for record_decision")
        event_id = _stable_id("EV-MA", action_id)
        event, created = _event_once(
            project_store,
            project.id,
            event_id=event_id,
            kind="project.decision_recorded",
            payload={
                "actor": actor,
                "decision": decision,
                "rationale": str(body.get("rationale") or "").strip(),
                "source_message": source,
            },
        )
        target = _entity_ref("decision", event["id"], project.id, label=decision[:256])
        card_title = "已记录项目决策"
        card_summary = decision
        card_status = "recorded"
    else:  # publish_artifact
        artifact = dict(body.get("artifact") or {})
        if not artifact or not any(
            str(artifact.get(key) or "").strip() for key in ("id", "title", "name", "path", "url")
        ):
            raise MessageProjectActionError(
                400,
                "artifact needs at least one of id, title, name, path, or url",
            )
        artifact_id = optional_cowork_id(artifact.get("id"), label="artifact id") or _stable_id(
            "ART",
            action_id,
        )
        artifact["id"] = artifact_id
        artifact_name = (
            artifact.get("name")
            or artifact.get("title")
            or artifact.get("path")
            or artifact.get("url")
            or artifact_id
        )
        artifact["name"] = artifact_name
        artifact["title"] = artifact.get("title") or artifact_name
        event_id = _stable_id("EV-MA", action_id)
        event, created = _event_once(
            project_store,
            project.id,
            event_id=event_id,
            kind="project.artifact_published",
            payload={
                "actor": actor,
                "artifact": artifact,
                "source_message": source,
            },
        )
        target = _entity_ref(
            "artifact",
            artifact_id,
            project.id,
            label=str(artifact.get("title") or artifact_id)[:256],
        )
        card_title = f"已发布资料 · {artifact.get('title') or artifact_id}"
        card_summary = str(artifact.get("summary") or artifact.get("path") or "")
        card_status = "published"

    project_ref = _entity_ref("project", project.id, project.id, label=project.name)
    card_title = str(card_title).strip()[:512]
    card_summary = str(card_summary).strip()[:4096]
    receipt = _action_receipt(
        action_id=action_id,
        action=action,
        project_id=project.id,
        target=target,
        event_id=event["id"],
    )
    source_message = collaboration_store.update_message_metadata(
        thread_id,
        int(message["seq"]),
        {
            "entity_refs": [project_ref, target],
            "project_actions": [receipt],
        },
    )
    card_metadata = {
        "source_message_id": f"project-action:{action_id}",
        "message_type": "system_card",
        "entity_refs": [project_ref, target],
        "system_card": {
            "schema": "octopus.project.system_card.v1",
            "type": action,
            "title": card_title,
            "summary": card_summary,
            "status": card_status,
            "project_id": project.id,
            "target": target,
            "source_message_seq": source["message_seq"],
        },
    }
    card_seq = collaboration_store.append_message(
        thread_id,
        room_id=room_id,
        text=card_title,
        participant_id="project-os",
        display_name="Project OS",
        metadata=card_metadata,
    )
    card_message = collaboration_store.message_for_session(thread_id, card_seq)
    return {
        "ok": True,
        "replayed": False,
        "created": bool(created),
        "action_id": action_id,
        "action": action,
        "project_id": project.id,
        "milestone_id": milestone.id if milestone is not None else None,
        "target": target,
        "receipt": receipt,
        "event": event,
        "task": task.to_dict() if task is not None else None,
        "source_message": source_message,
        "system_card_message": card_message,
    }


__all__ = [
    "MessageProjectActionError",
    "apply_message_project_action",
]
