"""Thread-group API: WeChat-style membership + mode + shared blackboard.

A thread *is* the group (1:1 = the N=2 case), so these endpoints hang off the
thread id. In shared/authenticated deployments every read and write is bound to
the server-owned thread principal; local no-auth mode keeps the original
single-user behaviour. Mutations are attributed to the resolved actor.

Path is ``/api/cowork/*`` to avoid colliding with ``/api/groups/*`` (which is the
static AgentGroupRegistry of agent-team *templates*, a different concept).
"""

from __future__ import annotations

import asyncio
import inspect
from contextlib import suppress
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from runtime.memory.cowork.group import (
    ContextGrant,
    MemberEvent,
    responders,
)
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.threads.event_log import validate_thread_id


class GrantBody(BaseModel):
    scope: str = "all"  # all | from_join | range | summary
    from_msg: int | None = None
    to_msg: int | None = None


class InviteBody(BaseModel):
    target_id: str = Field(min_length=1)
    kind: str = "agent"  # agent | human
    role: str = "participant"  # participant | observer
    grant: GrantBody = Field(default_factory=GrantBody)
    at_message: int | None = None


class ModeBody(BaseModel):
    mode: str  # chat | cluster | swarm | project


class BoardBody(BaseModel):
    key: str = Field(min_length=1)
    value: Any = None


class AssignBody(BaseModel):
    assignee: str = Field(min_length=1)
    prompt: str = Field(min_length=1)


class CompleteBody(BaseModel):
    result: str = ""
    blackboard_key: str | None = None


class BreakoutBody(BaseModel):
    child_thread: str = Field(min_length=1)
    members: list[dict] = Field(default_factory=list)
    grant: dict | None = None
    at_message: int | None = None


class MergeBody(BaseModel):
    summary: str = ""


class ReadBody(BaseModel):
    member_id: str = Field(min_length=1)
    seq: int | None = None  # default: mark read up to the current event head


class HeartbeatBody(BaseModel):
    member_id: str = Field(min_length=1)


class LinkRoomBody(BaseModel):
    room_id: str = Field(min_length=1)


class RoomMessageBody(BaseModel):
    text: str = Field(min_length=1)
    participant_id: str = ""
    display_name: str = ""


class EnsureRoomBody(BaseModel):
    id: str | None = None
    name: str = ""
    members: list[dict[str, Any]] = Field(default_factory=list)
    leaderId: str | None = None  # noqa: N815 - team room wire uses camelCase
    mode: str | None = None


class CollabTaskBody(BaseModel):
    title: str = Field(min_length=1)
    description: str = ""
    sop_template: str = ""
    assignees: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    run: bool = False
    room: EnsureRoomBody | None = None


def create_cowork_group_router(
    *,
    store: GroupStore | None = None,
    async_store: Any = None,
    collaboration_store: Any = None,
    room_message_store: Any = None,
    team_rooms_state_path: Any = None,
    team_tasks_state_path: Any = None,
    team_rooms_router: Any = None,
    team_tasks_router: Any = None,
    runtime: Any = None,
    project_store: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create the ``/api/cowork/*`` thread-group router."""
    group_store = store or GroupStore()

    def _ensure_project_for_thread(thread_id: str, request: Request) -> str | None:
        """Bind a Project OS project to the thread if none exists yet.

        Fails soft: a project-mode switch must never fail the whole request
        just because planning is unavailable."""
        try:
            from runtime.projectos.cowork_bridge import ensure_project_for_thread
            from runtime.projectos.store import ProjectStore

            name = ""
            thread_store = getattr(runtime, "thread_store", None)
            get_state = getattr(thread_store, "get_state", None)
            if callable(get_state):
                try:
                    st = get_state(thread_id)
                    values = st.get("values") if isinstance(st, dict) else None
                    title = values.get("title") if isinstance(values, dict) else None
                    if isinstance(title, str) and title.strip():
                        name = title.strip()
                except Exception:  # noqa: BLE001
                    name = ""
            store = project_store if project_store is not None else ProjectStore()
            return ensure_project_for_thread(
                store,
                group_store,
                thread_id,
                name=name,
                goal=name,
            )
        except Exception as exc:  # noqa: BLE001
            _logger = __import__("logging").getLogger("octopus.cowork")
            _logger.warning("project-mode auto-bind failed for %s: %s", thread_id, exc)
            return None

    def _require_thread_path(thread_id: str) -> None:
        try:
            validate_thread_id(thread_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def _collaboration_store():
        if collaboration_store is not None:
            return collaboration_store
        from runtime.memory.cowork.collaboration_store import CollaborationStore

        return CollaborationStore(base_dir=group_store.base_dir)

    def _async_store():
        if async_store is not None:
            return async_store
        from runtime.memory.cowork.async_work import AsyncWorkStore

        return AsyncWorkStore(base_dir=group_store.base_dir, group_store=group_store)

    _presence_holder: dict[str, Any] = {}

    def _presence_store():
        store = _presence_holder.get("v")
        if store is None:
            from runtime.memory.cowork.presence import PresenceStore

            store = PresenceStore(base_dir=group_store.base_dir)
            _presence_holder["v"] = store
        return store

    _room_msg_holder: dict[str, Any] = {}

    def _room_message_store():
        if room_message_store is not None:
            return room_message_store
        store = _room_msg_holder.get("v")
        if store is None:
            from runtime.memory.cowork.room_messages import RoomMessageStore

            # Default teamroom dir — shared with the team_rooms router's store,
            # so a linked room's transcript is the same one it persists.
            store = RoomMessageStore()
            _room_msg_holder["v"] = store
        return store

    def _room_participants(room_id: str) -> list[dict[str, Any]]:
        """Read a linked room's participant config from the team_rooms store
        (read-only bridge — the team_rooms router owns the file)."""
        canonical = _collaboration_store().room_by_id(room_id)
        if canonical is not None:
            participants = canonical.get("participants")
            return participants if isinstance(participants, list) else []

        from pathlib import Path

        from runtime.platform.process.paths import app_paths
        from runtime.sensing.gateway.team_rooms_router import _load_state

        path = team_rooms_state_path or (app_paths().data_dir / "team_rooms.json")
        room = _load_state(Path(path)).get(room_id)
        if room is None:
            return []
        return [p.model_dump() for p in room.participants]

    def _room_tasks(room_id: str) -> list[dict[str, Any]]:
        """Read a linked room's team tasks from the team_tasks store (read-only
        bridge — the team_tasks router owns the file). This is the third source
        of truth Codex flagged; folding it in makes the session view cover the
        room's *work*, not just its roster + transcript."""
        canonical = _collaboration_store().tasks_for_room(room_id)
        if canonical:
            return canonical

        from pathlib import Path

        from runtime.platform.process.paths import app_paths
        from runtime.sensing.gateway.team_tasks_router import _load_state as _load_tasks

        path = team_tasks_state_path or (app_paths().data_dir / "team_tasks.json")
        tasks = _load_tasks(Path(path))
        return [t.model_dump() for t in tasks.values() if t.room_id == room_id]

    def _room_messages(thread_id: str, room_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        canonical = _collaboration_store().messages_for_session(thread_id, limit=limit)
        if canonical:
            return canonical
        try:
            return _room_message_store().history(room_id, limit=limit)
        except Exception:  # noqa: BLE001 — linked-room transcript is best-effort
            return []

    class _SessionMessageSearch:
        def __init__(self, thread_id: str) -> None:
            self.thread_id = thread_id

        def search(self, room_id: str, query: str, *, limit: int = 50) -> list[dict[str, Any]]:
            canonical = _collaboration_store().search_messages(self.thread_id, query, limit=limit)
            if canonical:
                return canonical
            return _room_message_store().search(room_id, query, limit=limit)

    def _room_snapshot(room_id: str) -> dict[str, Any] | None:
        canonical = _collaboration_store().room_by_id(room_id)
        if canonical is not None:
            return canonical

        from pathlib import Path

        from runtime.platform.process.paths import app_paths
        from runtime.sensing.gateway.team_rooms_router import _load_state

        path = team_rooms_state_path or (app_paths().data_dir / "team_rooms.json")
        room = _load_state(Path(path)).get(room_id)
        return room.model_dump() if room is not None else None

    def _session_payload(thread_id: str) -> dict[str, Any]:
        from runtime.memory.cowork.session import resolve_session

        session = resolve_session(
            group_store,
            thread_id,
            async_store=_async_store(),
            presence_store=_presence_store(),
            room_message_store=None,
            room_messages_provider=lambda room_id: _room_messages(thread_id, room_id),
            room_participants_provider=_room_participants,
            room_tasks_provider=_room_tasks,
        )
        return session.to_dict()

    def _room_members_from_group(thread_id: str) -> list[dict[str, Any]]:
        state = group_store.state(thread_id)
        return [
            {
                "name": member.id,
                "display_name": member.id,
                "description": "",
            }
            for member in state.roster
            if member.kind == "agent" and member.role == "participant" and not member.muted
        ]

    async def _maybe_await(value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    def _principal(request: Request) -> Any:
        cached = getattr(getattr(request, "state", None), "cowork_principal", None)
        if cached is not None:
            return cached

        from runtime.safety.auth.principal import resolve_principal

        principal = resolve_principal(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
        if principal is not None:
            request.state.cowork_principal = principal
        return principal

    def _require_owned_thread(thread_id: str, request: Request) -> dict[str, Any] | None:
        """Bind authenticated cowork state to the canonical managed thread."""

        if not require_auth:
            return None
        principal = _principal(request)
        if principal is None:  # resolve_principal is fail-closed in auth mode
            raise HTTPException(401, "authentication required")

        thread_store = getattr(runtime, "thread_store", None)
        if thread_store is None:
            raise HTTPException(503, "thread state unavailable")
        getter = getattr(thread_store, "get", None)
        if not callable(getter):
            getter = getattr(thread_store, "get_state", None)
        if not callable(getter):
            raise HTTPException(503, "thread state unavailable")
        try:
            thread = getter(thread_id)
        except KeyError:
            thread = None
        except Exception as exc:  # noqa: BLE001 - adapter failures are service failures
            raise HTTPException(503, "thread state unavailable") from exc
        if not isinstance(thread, dict):
            raise HTTPException(404, "thread not found")

        raw_metadata = thread.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        owner = str(metadata.get("owner_actor_id") or "").strip()
        tenant = str(metadata.get("tenant_id") or "").strip()
        if owner != principal.actor_id or tenant != principal.tenant_id:
            # Hide both existence and ownership from a cross-tenant caller.
            raise HTTPException(404, "thread not found")
        request.state.cowork_thread = thread
        return thread

    def _require_room_member(room_id: str, request: Request) -> None:
        """Preserve Team Room membership when a cowork route projects room data."""

        if not require_auth:
            return
        principal = _principal(request)
        if principal is None:
            raise HTTPException(401, "authentication required")

        room = _room_snapshot(room_id)
        if room is None:
            raise HTTPException(404, "team room not found")
        member_lister = getattr(team_rooms_router, "list_room_members", None)
        if callable(member_lister):
            allowed = {str(actor) for actor in member_lister(room_id) if str(actor)}
        else:
            allowed = {str(room.get("owner_id") or "").strip()}
            raw_participants = room.get("participants")
            participants = raw_participants if isinstance(raw_participants, list) else []
            allowed.update(
                str(participant.get("actor_id") or "").strip()
                for participant in participants
                if isinstance(participant, dict) and participant.get("status") != "removed"
            )
            allowed.discard("")
        if principal.actor_id not in allowed:
            raise HTTPException(403, "not a member of the linked team room")

    async def _ensure_room(
        thread_id: str,
        body: EnsureRoomBody,
        request: Request,
    ) -> tuple[dict[str, Any], bool]:
        """Ensure the collaboration session has one persistent room.

        This is the write-side half of the unified path: a thread remains the
        canonical session, while the former Team Room becomes the session's
        persistent surface for humans, invite links, room tasks, and WS.
        """
        from runtime.memory.cowork.session import link_room

        state = group_store.state(thread_id)
        if state.room_id:
            _require_room_member(state.room_id, request)
            room = (await asyncio.to_thread(_room_snapshot, state.room_id)) or {"id": state.room_id}
            await asyncio.to_thread(_collaboration_store().upsert_room, thread_id, dict(room))
            return room, False

        creator = getattr(team_rooms_router, "create_team_from_payload", None)
        if not callable(creator):
            raise HTTPException(501, "collab room creation is not wired")

        members = [m for m in body.members if str(m.get("name") or "").strip()]
        if not members:
            members = await asyncio.to_thread(_room_members_from_group, thread_id)
        if not members:
            raise HTTPException(
                400,
                "collab room needs at least one agent member; invite a collaborator first",
            )

        leader_id = body.leaderId or str(members[0].get("name") or "")
        if leader_id not in {str(m.get("name") or "") for m in members}:
            leader_id = str(members[0].get("name") or "")
        payload = {
            "id": body.id or f"collab-{thread_id}",
            "name": body.name.strip() or f"Collaboration · {thread_id}",
            "members": members,
            "leaderId": leader_id,
        }
        room = await _maybe_await(creator(request, payload))
        room_id = str((room or {}).get("id") or "")
        if not room_id:
            raise HTTPException(502, "team room creator returned no id")
        room = await asyncio.to_thread(_collaboration_store().upsert_room, thread_id, dict(room))
        await asyncio.to_thread(link_room, group_store, thread_id, room_id, actor=_actor(request))
        if body.mode:
            if body.mode not in ("chat", "cluster", "swarm", "project"):
                raise HTTPException(400, "mode must be chat | cluster | swarm | project")
            await asyncio.to_thread(
                group_store.append,
                thread_id,
                MemberEvent(action="mode", actor=_actor(request), mode=body.mode),  # type: ignore[arg-type]
            )
        return room, True

    def _actor(request: Request) -> str:
        principal = _principal(request)
        return str(getattr(principal, "actor_id", "") or "user")

    def _auth_dep(request: Request) -> None:
        _actor(request)  # enforces 401 when require_auth and no/invalid token

    def _thread_access_dep(thread_id: str, request: Request) -> None:
        _require_thread_path(thread_id)
        _require_owned_thread(thread_id, request)

    router = APIRouter(tags=["cowork"], dependencies=[Depends(_thread_access_dep)])

    @router.get("/api/cowork/{thread_id}")
    def get_group(thread_id: str, until_seq: int | None = None) -> dict[str, Any]:
        """Folded group state (roster + mode), the shared blackboard, the raw
        membership timeline, and who would respond this turn under the mode.
        ``until_seq`` replays the group as it was at that event (time-travel)."""
        state = group_store.state(thread_id, until_seq=until_seq)
        return {
            "thread_id": thread_id,
            "state": state.to_dict(),
            "blackboard": group_store.blackboard_snapshot(thread_id),
            "events": [e.to_dict() for e in group_store.events(thread_id)],
            "responders": responders(state),
        }

    @router.get("/api/collab/{thread_id}")
    def get_session(thread_id: str, request: Request) -> dict[str, Any]:
        """Unified collaboration session — one read over roster/mode/room link,
        shared blackboard, async tasks, and presence (instead of stitching the
        per-surface endpoints). The cowork thread is the canonical session; a
        Team Room is its optional linked surface."""
        room_id = getattr(group_store.state(thread_id), "room_id", None)
        if room_id:
            _require_room_member(room_id, request)
        return _session_payload(thread_id)

    @router.post("/api/collab/{thread_id}/room", dependencies=[Depends(_auth_dep)])
    async def ensure_session_room(
        thread_id: str,
        body: EnsureRoomBody,
        request: Request,
    ) -> dict[str, Any]:
        """Create/link the session's persistent room.

        This is the canonical replacement for "go create a Team elsewhere":
        the user stays in one collaboration thread, and persistence/invites/tasks
        become properties of that same session.
        """
        room, created = await _ensure_room(thread_id, body, request)
        return {
            "ok": True,
            "created": created,
            "room": room,
            "session": await asyncio.to_thread(_session_payload, thread_id),
        }

    @router.get("/api/collab/{thread_id}/tasks")
    def list_session_tasks(thread_id: str, request: Request) -> dict[str, Any]:
        """List heavyweight room tasks through the canonical session path."""
        room_id = getattr(group_store.state(thread_id), "room_id", None)
        if room_id:
            _require_room_member(room_id, request)
        tasks = _collaboration_store().tasks_for_session(thread_id)
        if not tasks and room_id:
            tasks = _room_tasks(room_id)
        return {
            "thread_id": thread_id,
            "room_id": room_id,
            "tasks": tasks,
            "count": len(tasks),
        }

    @router.post("/api/collab/{thread_id}/tasks", dependencies=[Depends(_auth_dep)])
    async def create_session_task(
        thread_id: str,
        body: CollabTaskBody,
        request: Request,
    ) -> dict[str, Any]:
        """Create a heavyweight task through the collaboration session.

        The underlying TeamTask store is still reused for compatibility, but the
        caller no longer has to choose a separate Team surface first.
        """
        creator = getattr(team_tasks_router, "create_task_from_payload", None)
        if not callable(creator):
            raise HTTPException(501, "collab task creation is not wired")
        room_body = body.room or EnsureRoomBody()
        room, _created = await _ensure_room(thread_id, room_body, request)
        room_id = str(room.get("id") or getattr(group_store.state(thread_id), "room_id", "") or "")
        if not room_id:
            raise HTTPException(409, "collab session has no linked room")
        metadata = {
            **body.metadata,
            "collab_session_id": thread_id,
            "source": "collab_session",
        }
        task = await _maybe_await(
            creator(
                request,
                {
                    "room_id": room_id,
                    "title": body.title,
                    "description": body.description,
                    "sop_template": body.sop_template,
                    "assignees": body.assignees,
                    "metadata": metadata,
                },
            )
        )
        if body.run:
            runner = getattr(team_tasks_router, "run_task_from_request", None)
            if callable(runner):
                task = await _maybe_await(runner(request, task["id"]))
        task = await asyncio.to_thread(_collaboration_store().upsert_task, thread_id, dict(task))
        return {
            "ok": True,
            "room_id": room_id,
            "task": task,
            "session": await asyncio.to_thread(_session_payload, thread_id),
        }

    @router.post("/api/collab/{thread_id}/link-room", dependencies=[Depends(_auth_dep)])
    def link_session_room(
        thread_id: str,
        body: LinkRoomBody,
        request: Request,
    ) -> dict[str, Any]:
        """Link a Team Room to this session (event-sourced) so the two surfaces
        stop drifting as separate sources of truth."""
        from runtime.memory.cowork.session import link_room

        _require_room_member(body.room_id, request)
        state = link_room(group_store, thread_id, body.room_id, actor=_actor(request))
        room = _room_snapshot(body.room_id) or {"id": body.room_id}
        _collaboration_store().upsert_room(thread_id, room)
        return {"ok": True, "state": state.to_dict(), "session": _session_payload(thread_id)}

    @router.post("/api/collab/{thread_id}/room-message", dependencies=[Depends(_auth_dep)])
    def post_room_message(
        thread_id: str,
        body: RoomMessageBody,
        request: Request,
    ) -> dict[str, Any]:
        """Write a line into the session's linked Team Room transcript.

        The write side of the unified session: where ``get_session`` /search read
        the linked room transcript, this lets the cowork thread *post* into it
        through the same session — so an agent or summary in the group lands in
        the room surface instead of a separate write path. 409 if no room is
        linked (link it first via ``/link-room``)."""
        room_id = getattr(group_store.state(thread_id), "room_id", None)
        if not room_id:
            raise HTTPException(409, "no room linked to this session — link one first")
        _require_room_member(room_id, request)
        seq = _collaboration_store().append_message(
            thread_id,
            room_id=room_id,
            text=body.text,
            participant_id=body.participant_id,
            display_name=body.display_name,
        )
        with suppress(Exception):  # legacy transcript projection is best-effort
            _room_message_store().append(
                room_id,
                text=body.text,
                participant_id=body.participant_id,
                display_name=body.display_name,
            )
        return {"ok": True, "room_id": room_id, "seq": seq}

    @router.get("/api/cowork/{thread_id}/nominate")
    def nominate_turn(thread_id: str, text: str = "", threshold: float = 0.5) -> dict[str, Any]:
        """Self-nomination gate: of the participant agents, who is relevant enough
        to speak for ``text`` — so a swarm doesn't pile on every turn."""
        from runtime.memory.cowork.nominate import gate

        state = group_store.state(thread_id)
        participants = [
            (m.id, m.id)
            for m in state.roster
            if m.kind == "agent" and m.role == "participant" and not m.muted
        ]
        return {"nominated": gate(participants, text, threshold=threshold)}

    @router.get("/api/cowork/{thread_id}/search")
    def search(
        thread_id: str,
        request: Request,
        q: str = "",
        limit: int = 20,
        kinds: str = "",
        until_seq: int | None = None,
    ) -> dict[str, Any]:
        """Replayable, session-wide search across the shared blackboard, async
        tasks, the membership/mode event log, and (when a room is linked) the
        room transcript + team tasks. ``kinds`` is a comma-separated subset of
        ``blackboard,task,event,room_message,room_task`` (default all);
        ``until_seq`` bounds the event scan to a past point (time-travel)."""
        from runtime.memory.cowork.search import search_group

        room_id = getattr(group_store.state(thread_id), "room_id", None)
        if room_id:
            _require_room_member(room_id, request)
        kind_filter = tuple(k.strip() for k in kinds.split(",") if k.strip()) or None
        hits = search_group(
            group_store,
            thread_id,
            q,
            limit=max(1, min(100, limit)),
            kinds=kind_filter,
            until_seq=until_seq,
            async_store=_async_store(),
            room_message_store=_SessionMessageSearch(thread_id),
            room_task_provider=_room_tasks,
        )
        return {"thread_id": thread_id, "query": q, "hits": [h.to_dict() for h in hits]}

    @router.get("/api/cowork/{thread_id}/presence")
    def presence(thread_id: str, online_window_s: int = 60) -> dict[str, Any]:
        """Per-member presence + unread for the thread's roster. Unread counts
        group events past each member's read marker (floored at their join)."""
        from runtime.memory.cowork.presence import group_presence

        members = group_presence(
            group_store,
            _presence_store(),
            thread_id,
            online_window_s=max(1, online_window_s),
        )
        return {"thread_id": thread_id, "members": [m.to_dict() for m in members]}

    @router.post("/api/cowork/{thread_id}/read", dependencies=[Depends(_auth_dep)])
    def mark_read(thread_id: str, body: ReadBody) -> dict[str, Any]:
        """Mark ``member_id`` caught up to ``seq`` (default: the current event
        head). The marker is monotonic — it never rewinds."""
        seq = body.seq
        if seq is None:
            events = group_store.events(thread_id)
            seq = max((e.seq for e in events), default=0)
        _presence_store().mark_read(thread_id, body.member_id, int(seq))
        return {"ok": True, **_presence_store().get(thread_id, body.member_id)}

    @router.post("/api/cowork/{thread_id}/heartbeat", dependencies=[Depends(_auth_dep)])
    def heartbeat(thread_id: str, body: HeartbeatBody) -> dict[str, Any]:
        """Presence ping — refresh ``member_id``'s online status."""
        _presence_store().heartbeat(thread_id, body.member_id)
        return {"ok": True, **_presence_store().get(thread_id, body.member_id)}

    @router.get("/api/cowork/{thread_id}/catchup/{member_id}")
    def catchup(thread_id: str, member_id: str) -> dict[str, Any]:
        """Catch-up brief for a member (roster + shared board + grant scope). The
        realtime layer fills in recent messages via build_catchup in-process."""
        from runtime.memory.cowork.catchup import build_catchup

        cu = build_catchup(
            group_store.state(thread_id),
            member_id,
            messages=[],
            blackboard=group_store.blackboard_snapshot(thread_id),
        )
        if cu is None:
            raise HTTPException(404, "member not in group")
        return {**cu.to_dict(), "render": cu.render()}

    @router.get("/api/cowork/{thread_id}/tasks")
    def list_tasks(thread_id: str) -> dict[str, Any]:
        """Background tasks in this thread (async coworkers)."""
        return {"tasks": [t.to_dict() for t in _async_store().list(thread_id)]}

    @router.get("/api/cowork/{thread_id}/tasks/summary")
    def tasks_summary(thread_id: str) -> dict[str, Any]:
        """Small operational summary for async cowork task badges/health."""
        store = _async_store()
        if runtime is not None and hasattr(runtime, "status"):
            status = runtime.status(thread_id)
        else:
            status = {
                "runner_enabled": False,
                "runner_reason": "runtime not attached",
                "task_counts": store.counts(thread_id),
            }
        return {"thread_id": thread_id, **status}

    @router.get("/api/cowork/{thread_id}/health")
    def health(thread_id: str) -> dict[str, Any]:
        """Unified operational health for a collaboration thread — one call for
        an ops panel: runner state, task queue + failure reasons, presence,
        mode/roster, and recent events. Read-only (like presence/search)."""
        from runtime.memory.cowork.presence import group_presence

        async_store = _async_store()
        tasks = async_store.list(thread_id)
        failures = [
            {"task_id": t.task_id, "assignee": t.assignee, "error": t.result or ""}
            for t in tasks
            if getattr(t, "status", "") == "failed"
        ][:10]
        if runtime is not None and hasattr(runtime, "status"):
            rstatus = runtime.status(thread_id)
            runner = {
                "enabled": bool(rstatus.get("runner_enabled")),
                "reason": rstatus.get("runner_reason") or "",
                "status": rstatus.get("runner_status"),
            }
        else:
            runner = {"enabled": False, "reason": "runtime not attached", "status": None}

        state = group_store.state(thread_id)
        members = group_presence(group_store, _presence_store(), thread_id)
        events = group_store.events(thread_id)
        return {
            "thread_id": thread_id,
            "mode": state.mode,
            "roster_size": len(state.roster),
            "runner": runner,
            "tasks": {
                "counts": async_store.counts(thread_id),
                "failures": failures,
            },
            "presence": {
                "members": len(members),
                "online": sum(1 for m in members if m.online),
                "unread": sum(m.unread for m in members),
            },
            "recent_events": [e.to_dict() for e in events[-10:]],
        }

    @router.post("/api/cowork/{thread_id}/tasks", dependencies=[Depends(_auth_dep)])
    def assign_task(thread_id: str, body: AssignBody, request: Request) -> dict[str, Any]:
        """Give a member a task to work in the background; result lands on the
        shared blackboard when complete."""
        task = _async_store().assign(thread_id, body.assignee, body.prompt, actor=_actor(request))
        return {"ok": True, "task": task.to_dict()}

    @router.post(
        "/api/cowork/{thread_id}/tasks/{task_id}/complete", dependencies=[Depends(_auth_dep)]
    )
    def complete_task(thread_id: str, task_id: str, body: CompleteBody) -> dict[str, Any]:
        """A runner reports a background task done — posts the result to the board."""
        async_store = _async_store()
        task = async_store.get(task_id)
        if task is None or task.thread_id != thread_id:
            raise HTTPException(404, "task not found")
        if task.status == "pending":
            async_store.claim(task_id)
        ok = async_store.complete(task_id, body.result, blackboard_key=body.blackboard_key)
        if not ok:
            raise HTTPException(409, "task is not claimable")
        return {"ok": True, "blackboard": group_store.blackboard_snapshot(thread_id)}

    @router.post("/api/cowork/{thread_id}/breakout", dependencies=[Depends(_auth_dep)])
    def breakout_fork(thread_id: str, body: BreakoutBody, request: Request) -> dict[str, Any]:
        """Spin off a focused side-thread with a subset of members + a grant."""
        from runtime.memory.cowork.breakout import fork
        from runtime.memory.cowork.group import ContextGrant

        _require_thread_path(body.child_thread)
        # Authenticated child threads must already have been created through
        # the canonical thread/realtime flow, which provisions server-owned
        # workspace metadata. Cowork must not mint an unmanaged parallel id.
        _require_owned_thread(body.child_thread, request)
        res = fork(
            group_store,
            thread_id,
            body.child_thread,
            actor=_actor(request),
            members=body.members,
            grant=ContextGrant.from_dict(body.grant),
            at_message=body.at_message,
        )
        return {"ok": True, **res}

    @router.post(
        "/api/cowork/{thread_id}/breakout/{child_thread}/merge", dependencies=[Depends(_auth_dep)]
    )
    def breakout_merge(
        thread_id: str, child_thread: str, body: MergeBody, request: Request
    ) -> dict[str, Any]:
        """Merge a breakout's conclusion back onto the parent's blackboard."""
        from runtime.memory.cowork.breakout import merge_back

        _require_thread_path(child_thread)
        _require_owned_thread(child_thread, request)
        res = merge_back(
            group_store, child_thread, thread_id, actor=_actor(request), summary=body.summary
        )
        return {"ok": True, **res, "blackboard": group_store.blackboard_snapshot(thread_id)}

    @router.get("/api/cowork/{thread_id}/plan")
    def plan(thread_id: str, text: str = "") -> dict[str, Any]:
        """Given a draft message, who would act this turn and how (mode →
        single / cluster / swarm), honouring @agent mentions. The realtime
        driver reads this to dispatch without a manual mode switch."""
        from runtime.memory.cowork.turn_plan import plan_turn_for_thread

        return plan_turn_for_thread(group_store, thread_id, text).to_dict()

    @router.get("/api/cowork/{thread_id}/view/{member_id}")
    def member_view(thread_id: str, member_id: str, max_message: int = 0) -> dict[str, Any]:
        """The history slice ``member_id`` is allowed to see at ``max_message``
        (their context grant resolved). The context assembler uses this to bound
        what reaches the agent's prompt — the enforcement half of the privacy seam."""
        from runtime.memory.cowork.context_view import resolve_view

        view = resolve_view(group_store.state(thread_id), member_id, max_message)
        if view is None:
            raise HTTPException(404, "member not in group")
        return view.to_dict()

    @router.post("/api/cowork/{thread_id}/members", dependencies=[Depends(_auth_dep)])
    def invite_member(thread_id: str, body: InviteBody, request: Request) -> dict[str, Any]:
        """Pull a member (agent or human) into the thread, with a context grant."""
        ev = MemberEvent(
            action="invite",
            actor=_actor(request),
            target_id=body.target_id,
            target_kind="human" if body.kind == "human" else "agent",
            role="observer" if body.role == "observer" else "participant",
            grant=ContextGrant.from_dict(body.grant.model_dump()),
            at_message=body.at_message,
        )
        group_store.append(thread_id, ev)
        return {"ok": True, "state": group_store.state(thread_id).to_dict()}

    @router.delete("/api/cowork/{thread_id}/members/{member_id}", dependencies=[Depends(_auth_dep)])
    def remove_member(thread_id: str, member_id: str, request: Request) -> dict[str, Any]:
        """Remove a member. Their past blackboard writes stay (attributed)."""
        group_store.append(
            thread_id,
            MemberEvent(action="leave", actor=_actor(request), target_id=member_id),
        )
        return {"ok": True, "state": group_store.state(thread_id).to_dict()}

    @router.post("/api/cowork/{thread_id}/mode", dependencies=[Depends(_auth_dep)])
    def set_mode(thread_id: str, body: ModeBody, request: Request) -> dict[str, Any]:
        """Switch the collaboration mode (chat/cluster/swarm/project) —
        non-destructive. 'project' runs the milestone-driven Project OS over the
        group. Entering project mode also ensures a real Project OS project is
        bound to the thread (created deterministically if missing) so the
        workbench 项目 tab has something to render; execution itself stays
        user-triggered via Run/Tick."""
        if body.mode not in ("chat", "cluster", "swarm", "project"):
            raise HTTPException(400, "mode must be chat | cluster | swarm | project")
        group_store.append(
            thread_id,
            MemberEvent(action="mode", actor=_actor(request), mode=body.mode),  # type: ignore[arg-type]
        )
        bound_project_id: str | None = None
        if body.mode == "project":
            bound_project_id = _ensure_project_for_thread(thread_id, request)
        state = group_store.state(thread_id).to_dict()
        if bound_project_id is not None:
            state["bound_project_id"] = bound_project_id
        return {"ok": True, "state": state}

    @router.post("/api/cowork/{thread_id}/blackboard", dependencies=[Depends(_auth_dep)])
    def write_board(thread_id: str, body: BoardBody, request: Request) -> dict[str, Any]:
        """Write a key to the group's shared blackboard, attributed to the actor."""
        board = group_store.blackboard(thread_id)
        board.write(body.key, body.value, writer=_actor(request))
        return {"ok": True, "blackboard": group_store.blackboard_snapshot(thread_id)}

    return router
