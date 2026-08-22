"""Atomic-looking orchestration for creating a Project OS collaboration group.

The participating stores are deliberately independent, so this service uses a
strict saga: every successful write immediately registers its inverse and no
created identifier is returned until all projections agree.  The endpoint is
the single write boundary; legacy project/thread/cowork endpoints remain
available for compatibility.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import suppress
from typing import Any
from uuid import uuid4

from runtime.memory.cowork.session import link_room
from runtime.projectos.cowork_bridge import full_project_state
from runtime.sensing.gateway.thread_workspace import (
    MANAGED_WORKSPACE_DELETION_KEY,
    MANAGED_WORKSPACE_DELETION_MARKER,
    discard_staged_managed_workspace,
    ensure_managed_thread_workspace,
    stage_managed_workspace_deletion,
)

_LOG = logging.getLogger(__name__)


class ProjectGroupCreationService:
    """Create and compensate the durable surfaces of one project group."""

    def __init__(
        self,
        *,
        project_store: Any,
        group_store: Any,
        collaboration_store: Any,
        team_rooms_router: Any,
        thread_store: Any,
        workspace_root: Any = None,
        require_auth: bool = False,
    ) -> None:
        self.project_store = project_store
        self.group_store = group_store
        self.collaboration_store = collaboration_store
        self.team_rooms_router = team_rooms_router
        self.thread_store = thread_store
        self.workspace_root = workspace_root
        self.require_auth = require_auth

    def _require_wiring(self) -> None:
        required = {
            "thread creation": getattr(self.thread_store, "ensure_thread", None),
            "project binding": getattr(self.project_store, "bind_thread", None),
            "project compensation": getattr(self.project_store, "delete_project", None),
            "group roster": getattr(self.group_store, "replace_agent_roster", None),
            "group compensation": getattr(self.group_store, "delete_thread", None),
            "room creation": getattr(self.team_rooms_router, "create_team_from_payload", None),
            "room binding": getattr(self.team_rooms_router, "bind_team_thread", None),
            "room compensation": getattr(self.team_rooms_router, "delete_team_from_payload", None),
            "collaboration projection": getattr(self.collaboration_store, "upsert_room", None),
            "projection compensation": getattr(self.collaboration_store, "delete_room_by_id", None),
        }
        missing = [label for label, callback in required.items() if not callable(callback)]
        if missing:
            raise RuntimeError(f"project group creation is not wired: {', '.join(missing)}")

    def _delete_created_thread(self, thread_id: str) -> None:
        current = self.thread_store.get(thread_id)
        if current is None:
            return
        if not self.require_auth:
            delete = getattr(self.thread_store, "delete", None)
            if not callable(delete) or not delete(thread_id):
                raise RuntimeError("thread compensation failed")
            return

        raw_metadata = current.get("metadata") if isinstance(current, dict) else None
        metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        if metadata.get(MANAGED_WORKSPACE_DELETION_KEY) is None:
            update_if_unchanged = getattr(self.thread_store, "update_state_if_unchanged", None)
            if not callable(update_if_unchanged):
                raise RuntimeError("managed thread compensation is unavailable")
            update_if_unchanged(
                thread_id,
                current,
                metadata={
                    MANAGED_WORKSPACE_DELETION_KEY: MANAGED_WORKSPACE_DELETION_MARKER,
                },
                status="deleting",
            )
            current = self.thread_store.get(thread_id)
            raw_metadata = current.get("metadata") if isinstance(current, dict) else None
            metadata = dict(raw_metadata) if isinstance(raw_metadata, dict) else {}
        if metadata.get(MANAGED_WORKSPACE_DELETION_KEY) != MANAGED_WORKSPACE_DELETION_MARKER:
            raise RuntimeError("managed thread compensation conflicted")
        staged = stage_managed_workspace_deletion(
            self.workspace_root,
            thread_id=thread_id,
            metadata=metadata,
        )
        discard_staged_managed_workspace(staged)
        delete_if_unchanged = getattr(self.thread_store, "delete_if_unchanged", None)
        if not callable(delete_if_unchanged) or not delete_if_unchanged(thread_id, current):
            raise RuntimeError("managed thread compensation conflicted")

    def _delete_created_room(self, request: Any, room_id: str) -> None:
        try:
            self.team_rooms_router.delete_team_from_payload(request, room_id)
        except Exception as exc:
            # A create adapter can fail before inserting anything.  Its
            # pre-registered inverse is therefore allowed to observe 404.
            if getattr(exc, "status_code", None) == 404:
                return
            raise

    @staticmethod
    def _run_compensations(compensations: list[tuple[str, Callable[[], Any]]]) -> None:
        failures: list[str] = []
        for label, compensate in reversed(compensations):
            try:
                compensate()
            except Exception:  # noqa: BLE001 - continue cleaning independent stores
                failures.append(label)
                _LOG.exception("project group compensation failed: %s", label)
        if failures:
            raise RuntimeError("project group compensation failed: " + ", ".join(failures))

    def create(
        self,
        *,
        request: Any,
        name: str,
        goal: str,
        agents: list[dict[str, Any]],
        actor_id: str,
        tenant_id: str,
        plan_project: Callable[[], Any],
    ) -> dict[str, Any]:
        """Create every project-group surface or compensate all completed writes."""

        self._require_wiring()
        agent_ids = [str(agent["id"]) for agent in agents]
        mode = "cluster" if len(agent_ids) > 1 else "chat"
        primary_agent_id = agent_ids[0]
        compensations: list[tuple[str, Callable[[], Any]]] = []
        project: Any = None
        thread_id = ""
        room_id = ""
        try:
            project = plan_project()
            compensations.append(
                (
                    "project",
                    lambda: self.project_store.delete_project(project.id),
                )
            )

            metadata = {
                "mode": "code",
                "agent_name": primary_agent_id,
                "project_home": True,
                "project_id": project.id,
                "title": project.name,
            }
            if actor_id:
                metadata["owner_actor_id"] = actor_id
                metadata["tenant_id"] = tenant_id
            values = {
                "title": project.name,
                "agent_name": primary_agent_id,
                "project_id": project.id,
                "project_home": True,
            }
            # Pick the opaque id before the durable insert.  Registering the
            # inverse first also covers adapters that commit and then raise.
            thread_id = uuid4().hex
            compensations.append(("thread", lambda: self._delete_created_thread(thread_id)))
            thread = self.thread_store.ensure_thread(
                thread_id,
                metadata=metadata,
                values=values,
            )
            if str(thread.get("thread_id") or "") != thread_id:
                raise RuntimeError("thread store returned an invalid thread id")
            if self.require_auth:
                ensure_managed_thread_workspace(
                    self.workspace_root,
                    thread_id=thread_id,
                    actor_id=actor_id,
                    tenant_id=tenant_id,
                    store=self.thread_store,
                )

            self.project_store.bind_thread(thread_id, project.id)
            compensations.append(("group", lambda: self.group_store.delete_thread(thread_id)))
            _events, group_state = self.group_store.replace_agent_roster(
                thread_id,
                actor=actor_id or "system",
                agent_ids=agent_ids,
                mode=mode,
            )

            members = [
                {
                    "name": str(agent["id"]),
                    "display_name": str(agent.get("display_name") or agent["id"]),
                    "description": str(agent.get("description") or ""),
                    **({"avatar_url": agent["avatar_url"]} if agent.get("avatar_url") else {}),
                    **({"icon": agent["icon"]} if agent.get("icon") else {}),
                }
                for agent in agents
            ]
            room_id = f"collab-{thread_id}"
            compensations.append(
                (
                    "room",
                    lambda: self._delete_created_room(request, room_id),
                )
            )
            room = self.team_rooms_router.create_team_from_payload(
                request,
                {
                    "id": room_id,
                    "name": project.name,
                    "members": members,
                    "leaderId": primary_agent_id,
                },
            )
            returned_room_id = str((room or {}).get("id") or "")
            if returned_room_id != room_id:
                raise RuntimeError("team room creator returned an invalid id")
            room = self.team_rooms_router.bind_team_thread(request, room_id, thread_id)
            group_state = link_room(
                self.group_store,
                thread_id,
                room_id,
                actor=actor_id or "system",
            )

            compensations.append(
                (
                    "collaboration projection",
                    lambda: self.collaboration_store.delete_room_by_id(room_id),
                )
            )
            projected_room = self.collaboration_store.upsert_room(
                thread_id,
                {
                    **dict(room),
                    "metadata": {
                        "source": "projectos",
                        "project_id": project.id,
                        "tenant_id": tenant_id,
                        "thread_id": thread_id,
                    },
                },
            )
            project_state = full_project_state(self.project_store, project.id)
            if project_state is None:
                raise RuntimeError("created project state is unavailable")
        except Exception:
            try:
                self._run_compensations(compensations)
            except Exception as compensation_error:
                raise RuntimeError("project group creation and compensation failed") from (
                    compensation_error
                )
            raise

        # Keep only local references beyond the commit point.  A response
        # serialization failure must not trigger deletion of a committed group.
        with suppress(Exception):
            thread = self.thread_store.get(thread_id) or thread
        return {
            "project": project,
            "project_state": project_state,
            "thread": thread,
            "thread_id": thread_id,
            "room": projected_room,
            "group_state": group_state,
            "mode": mode,
        }


__all__ = ["ProjectGroupCreationService"]
