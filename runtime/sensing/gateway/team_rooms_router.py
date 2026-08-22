"""Persistent team rooms API.

This is the backend foundation for cross-device Team mode and, later,
human collaboration rooms. It deliberately stores fixed AI team config
and human participants separately: AI team members drive agent routing;
participants represent real people who may join through invite links.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from threading import Lock
from typing import Any

from runtime.memory.cowork.team_invitation_store import TeamInvitationStore
from runtime.platform.process.paths import app_paths
from runtime.safety.auth.principal import CurrentPrincipal, resolve_principal

from ._team_rooms_access import TeamRoomAccess
from ._team_rooms_state import (
    _load_state,
    _room_payload,
    _save_state,
    _slug_id,
    _unique_team_id,
)
from ._team_rooms_state import (
    _room_storage_payload as _room_storage_payload,
)
from .team_invitations_router import (
    register_team_invitation_routes,
    scrub_legacy_room_invites,
)
from .team_rooms_models import (
    CreateTeamInviteRequest,
    CreateTeamRoomRequest,
    JoinInviteRequest,
    RejectTeamJoinRequest,
    TeamMemberWire,
    TeamParticipantWire,
    TeamRoomWire,
    UpdateDelegationRequest,
    UpdateSpeakerPolicyRequest,
    UpdateTeamJoinPolicyRequest,
    UpdateTeamParticipantRequest,
)
from .team_rooms_ws import TeamRoomWsContext, team_room_ws
from .team_speaker_policy import (
    _authorized_to_speak_for,
    _caller_is_team_admin,
    _initial_floor_state,
    _next_speaker,
    _normalize_participant_role,
    _normalize_participant_status,
    _normalize_speak_mode,
    _normalize_speaker_policy,
    _now,
    _participant_can_speak,
    _resolve_moderator,
)

_LOG = logging.getLogger("octopus.team_rooms")

try:
    from fastapi import APIRouter, HTTPException, Request, WebSocket

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    WebSocket = None  # type: ignore[assignment,misc]

from runtime.sensing._fastapi_guard import require_fastapi  # noqa: E402, I001 — after FASTAPI_AVAILABLE flag


def create_team_rooms_router(
    *,
    state_path: Path | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    reset_callback: Any = None,
    room_message_store: Any = None,
    room_projection: Callable[[dict[str, Any]], None] | None = None,
    room_delete_projection: Callable[[str], None] | None = None,
    room_message_projection: Callable[[str, dict[str, Any]], None] | None = None,
    room_message_provider: Callable[[str, int, int, str], list[dict[str, Any]]] | None = None,
    invitation_store: TeamInvitationStore | None = None,
    project_store: Any = None,
    twin_responder: (
        Callable[
            [TeamRoomWire, TeamParticipantWire, list[dict[str, Any]]],
            Awaitable[str | None],
        ]
        | None
    ) = None,
) -> Any:
    """Create `/api/teams/*` routes.

    ``twin_responder`` (optional) bridges the room to an agent runtime: when
    the turn-engine floor lands on a participant who bound a digital-twin
    agent, the WS handler calls it for a short line and emits it on that
    participant's behalf. Injected as a callback so this gateway module never
    imports the model/execution layer (it stays an import leaf). None
    disables twin speaking — the human/host paths are unaffected.
    """
    require_fastapi(__name__)

    router: Any = APIRouter(tags=["team-rooms"])
    path = state_path or (app_paths().data_dir / "team_rooms.json")
    lock = Lock()
    scrub_legacy_room_invites(path)

    def _legacy_tenant_for_owner(owner_id: str | None) -> str:
        owner = str(owner_id or "").strip()
        if not require_auth:
            return "local"
        identity = identity_store.get(owner) if identity_store is not None and owner else None
        tenant = str((getattr(identity, "metadata", None) or {}).get("tenant_id") or "").strip()
        return tenant or (f"legacy:{owner}" if owner else "local")

    teams: dict[str, TeamRoomWire] = _load_state(
        path,
        legacy_tenant_for_owner=_legacy_tenant_for_owner,
    )
    invite_store = invitation_store or TeamInvitationStore(
        path.parent / "team_invitations.db" if state_path is not None else None
    )
    project_store_holder: dict[str, Any] = {"store": project_store}
    live_sockets: dict[str, dict[str, WebSocket]] = {}
    socket_loops: dict[str, dict[str, asyncio.AbstractEventLoop]] = {}

    def _project_binding_for_room(team: TeamRoomWire) -> tuple[str | None, bool]:
        bound_store = project_store_holder.get("store")
        thread_id = str(team.thread_id or "").strip()
        resolver = getattr(bound_store, "project_for_thread", None)
        if not thread_id or not callable(resolver):
            return None, False
        try:
            project = resolver(thread_id)
        except Exception:  # noqa: BLE001 - policy resolution must fail closed
            _LOG.warning("project binding lookup failed for team %s", team.id, exc_info=True)
            return None, True
        if project is None:
            return None, False
        project_tenant = str(getattr(project, "tenant_id", "") or "").strip()
        if require_auth and project_tenant != team.tenant_id:
            return None, False
        if not require_auth and project_tenant and project_tenant not in {"local", team.tenant_id}:
            return None, False
        project_id = str(getattr(project, "id", "") or "").strip()
        return project_id or None, False

    def _project_id_for_room(team: TeamRoomWire) -> str | None:
        project_id, _lookup_failed = _project_binding_for_room(team)
        return project_id

    def _join_policy_for_room(team: TeamRoomWire) -> str:
        override = str(team.join_policy_override or "").strip()
        if override in {"direct_join", "apply_then_join"}:
            return override
        project_id, lookup_failed = _project_binding_for_room(team)
        return "apply_then_join" if project_id is not None or lookup_failed else "direct_join"

    def _public_room_payload(team: TeamRoomWire) -> dict[str, Any]:
        project_id, lookup_failed = _project_binding_for_room(team)
        override = str(team.join_policy_override or "").strip()
        join_policy = (
            override
            if override in {"direct_join", "apply_then_join"}
            else ("apply_then_join" if project_id is not None or lookup_failed else "direct_join")
        )
        return _room_payload(
            team,
            join_policy=join_policy,
            project_id=project_id,
        )

    def _principal(request: Any) -> CurrentPrincipal | None:
        state = getattr(request, "state", None)
        cached = getattr(state, "principal", None) if state is not None else None
        if isinstance(cached, CurrentPrincipal):
            return cached
        return resolve_principal(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _auth(request: Any) -> str | None:
        principal = _principal(request)
        return principal.actor_id if principal is not None else None

    def _tenant(request: Any) -> str:
        principal = _principal(request)
        return principal.tenant_id if principal is not None else "local"

    room_access = TeamRoomAccess(
        teams=teams,
        lock=lock,
        require_auth=require_auth,
        principal=_principal,
        tenant=_tenant,
        http_exception=HTTPException,
    )
    _list_room_members = room_access.list_room_members
    _get_room_participant = room_access.get_room_participant
    _can_access_room = room_access.can_access_room
    _require_member = room_access.require_member
    _require_owner = room_access.require_owner
    _require_invite_admin = room_access.require_invite_admin
    _require_room_editor = room_access.require_room_editor

    def _save() -> None:
        _save_state(path, teams)
        if room_projection is not None:
            for team in list(teams.values()):
                try:
                    room_projection(_public_room_payload(team))
                except Exception:  # noqa: BLE001 - projection must not block room writes
                    _LOG.warning("team room projection failed for %s", team.id, exc_info=True)

    def _project_room_delete(room_id: str) -> None:
        if room_delete_projection is None:
            return
        try:
            room_delete_projection(room_id)
        except Exception:  # noqa: BLE001 - projection must not block room deletion
            _LOG.warning("team room delete projection failed for %s", room_id, exc_info=True)

    def _reset_state() -> None:
        with lock:
            teams.clear()
            live_sockets.clear()
            invite_store.clear()
        if callable(reset_callback):
            reset_callback()

    def _create_team_for_actor(
        actor: str | None,
        tenant_id: str,
        body: CreateTeamRoomRequest,
    ) -> TeamRoomWire:
        name = body.name.strip()
        if not name:
            raise HTTPException(400, "name is required")
        members = [m for m in body.members if m.name.strip()]
        if not members:
            raise HTTPException(400, "members must include at least one agent")
        leader_id = body.leaderId or members[0].name
        if leader_id not in {m.name for m in members}:
            leader_id = members[0].name
        now = _now()
        team_id = _unique_team_id(body.id or _slug_id(name), teams)
        owner = actor or "local"
        team = TeamRoomWire(
            id=team_id,
            name=name,
            members=members,
            leaderId=leader_id,
            owner_id=owner,
            tenant_id=tenant_id,
            thread_id=(body.thread_id or "").strip() or None,
            created_at=now,
            updated_at=now,
            participants=[
                TeamParticipantWire(
                    id=f"owner-{owner}",
                    display_name=owner,
                    role="owner",
                    actor_id=actor,
                    joined_at=now,
                    last_seen_at=now,
                ),
            ],
        )
        with lock:
            teams[team.id] = team
            try:
                _save()
            except Exception:
                # Creation is an all-or-nothing boundary for callers such as
                # the project-group orchestrator.  Do not leave an in-memory
                # room that the durable snapshot rejected.
                if teams.get(team.id) is team:
                    teams.pop(team.id, None)
                raise
        return team

    def _create_team_from_payload(
        request: Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = CreateTeamRoomRequest.model_validate(payload)
        principal = _principal(request)
        actor = principal.actor_id if principal is not None else None
        tenant_id = principal.tenant_id if principal is not None else "local"
        return _public_room_payload(_create_team_for_actor(actor, tenant_id, body))

    def _bind_team_thread(
        request: Request,
        team_id: str,
        thread_id: str,
    ) -> dict[str, Any]:
        """Attach a legacy room to its canonical cowork thread exactly once.

        The public Team Room API deliberately cannot choose ``thread_id``.
        This internal bridge is called only by the owner-gated cowork ensure
        route, so invite links can recover the canonical destination for rooms
        created before server-owned thread bindings were persisted.
        """

        _require_invite_admin(request, team_id)
        canonical_thread_id = str(thread_id or "").strip()
        if not canonical_thread_id:
            raise HTTPException(400, "thread_id is required")
        with lock:
            current = teams.get(team_id)
            if current is None:
                raise HTTPException(404, f"team not found: {team_id}")
            existing_thread_id = str(current.thread_id or "").strip()
            if existing_thread_id and existing_thread_id != canonical_thread_id:
                raise HTTPException(409, "team room is already bound to another thread")
            if existing_thread_id == canonical_thread_id:
                return _public_room_payload(current)
            updated = current.model_copy(
                update={
                    "thread_id": canonical_thread_id,
                    "updated_at": _now(),
                }
            )
            teams[team_id] = updated
            try:
                _save()
            except Exception:
                teams[team_id] = current
                raise
            return _public_room_payload(updated)

    def _unbind_team_thread(
        request: Request,
        team_id: str,
        thread_id: str,
    ) -> dict[str, Any]:
        """Compensate a binding only while it still points at ``thread_id``."""

        _require_invite_admin(request, team_id)
        expected_thread_id = str(thread_id or "").strip()
        with lock:
            current = teams.get(team_id)
            if current is None:
                raise HTTPException(404, f"team not found: {team_id}")
            if str(current.thread_id or "").strip() != expected_thread_id:
                return _public_room_payload(current)
            updated = current.model_copy(update={"thread_id": None, "updated_at": _now()})
            teams[team_id] = updated
            try:
                _save()
            except Exception:
                teams[team_id] = current
                raise
            return _public_room_payload(updated)

    async def _update_team_from_payload(
        request: Request,
        team_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        _require_room_editor(request, team_id)
        body = CreateTeamRoomRequest.model_validate(payload)
        with lock:
            current = teams.get(team_id)
            if current is None:
                raise HTTPException(404, f"team not found: {team_id}")
            name = body.name.strip() or current.name
            members = [m for m in body.members if m.name.strip()] or current.members
            leader_id = body.leaderId or current.leaderId or members[0].name
            if leader_id not in {m.name for m in members}:
                leader_id = members[0].name
            updated = current.model_copy(
                update={
                    "name": name,
                    "members": members,
                    "leaderId": leader_id,
                    "updated_at": _now(),
                }
            )
            teams[team_id] = updated
            _save()
        await _broadcast_team_update(team_id, updated)
        return _public_room_payload(updated)

    def _presence_payload(team_id: str) -> dict[str, Any]:
        team = teams.get(team_id)
        participants = team.participants if team else []
        online_ids = set(live_sockets.get(team_id, {}).keys())
        return {
            "type": "presence",
            "team_id": team_id,
            "participants": [
                p.model_dump() for p in participants if p.status == "active" and p.id in online_ids
            ],
            "count": len(online_ids),
            "server_time": _now(),
        }

    async def _broadcast(
        team_id: str,
        payload: dict[str, Any],
        *,
        exclude: str | None = None,
    ) -> None:
        with lock:
            sockets = [
                (
                    participant_id,
                    socket,
                    socket_loops.get(team_id, {}).get(participant_id),
                )
                for participant_id, socket in live_sockets.get(team_id, {}).items()
            ]
        dead: list[str] = []
        current_loop = asyncio.get_running_loop()
        for participant_id, socket, owner_loop in sockets:
            if exclude and participant_id == exclude:
                continue
            try:
                if owner_loop is None or owner_loop is current_loop:
                    await socket.send_json(payload)
                elif owner_loop.is_closed():
                    dead.append(participant_id)
                else:
                    sent = asyncio.run_coroutine_threadsafe(socket.send_json(payload), owner_loop)
                    await asyncio.wrap_future(sent)
            except (ConnectionError, TimeoutError, OSError, RuntimeError):
                dead.append(participant_id)
        if dead:
            with lock:
                room = live_sockets.get(team_id)
                loops = socket_loops.get(team_id)
                if room:
                    for participant_id in dead:
                        room.pop(participant_id, None)
                        if loops:
                            loops.pop(participant_id, None)

    async def _broadcast_presence(team_id: str) -> None:
        with lock:
            payload = _presence_payload(team_id)
        await _broadcast(team_id, payload)

    async def _broadcast_team_update(team_id: str, team: TeamRoomWire) -> None:
        await _broadcast(
            team_id,
            {
                "type": "team:update",
                "team_id": team_id,
                "team": _public_room_payload(team),
                "server_time": _now(),
            },
        )

    async def _broadcast_floor(team_id: str, team: TeamRoomWire) -> None:
        """Push the current turn-engine floor state so clients can render
        whose turn it is and the raised-hands queue."""
        await _broadcast(
            team_id,
            {
                "type": "floor",
                "team_id": team_id,
                "speaker_policy": _normalize_speaker_policy(team.speaker_policy),
                "current_speaker_id": getattr(team, "current_speaker_id", None),
                "moderator_id": _resolve_moderator(team),
                "floor_requests": list(getattr(team, "floor_requests", []) or []),
                "server_time": _now(),
            },
        )

    def _active_participant(team_id: str, participant_id: str) -> TeamParticipantWire | None:
        team = teams.get(team_id)
        if team is None:
            return None
        participant = next((p for p in team.participants if p.id == participant_id), None)
        if participant is None or participant.status == "removed":
            return None
        return participant

    @router.get("/api/teams")
    def list_teams(request: Request) -> dict[str, Any]:
        principal = _principal(request)
        actor = principal.actor_id if principal is not None else None
        with lock:
            all_teams = sorted(
                teams.values(),
                key=lambda team: team.updated_at,
                reverse=True,
            )
            # When auth is disabled (single-user dev mode) or the
            # request has no resolvable actor, return everything —
            # backward-compat for unauthenticated dashboards.
            # When require_auth=True AND we resolved an actor, filter
            # to only teams where the caller is a member/owner. This
            # prevents cross-tenant team enumeration.
            if require_auth and principal is not None and actor:
                visible = [
                    team
                    for team in all_teams
                    if team.tenant_id == principal.tenant_id
                    and (
                        actor == getattr(team, "owner_id", None)
                        or any(
                            getattr(p, "actor_id", None) == actor and p.status != "removed"
                            for p in team.participants
                        )
                    )
                ]
            else:
                visible = list(all_teams)
            return {
                "teams": [_public_room_payload(team) for team in visible],
                "count": len(visible),
            }

    @router.post("/api/teams")
    def create_team(
        request: Request,
        body: CreateTeamRoomRequest,
    ) -> dict[str, Any]:
        principal = _principal(request)
        actor = principal.actor_id if principal is not None else None
        tenant_id = principal.tenant_id if principal is not None else "local"
        # Canonical thread binding is an internal cowork bridge concern. A
        # public room-create body must not point an invite at an arbitrary task.
        team = _create_team_for_actor(actor, tenant_id, body.model_copy(update={"thread_id": None}))
        return _public_room_payload(team)

    @router.get("/api/teams/{team_id}")
    def get_team(request: Request, team_id: str) -> dict[str, Any]:
        _require_member(request, team_id)
        with lock:
            team = teams.get(team_id)
            if team is None:
                raise HTTPException(404, f"team not found: {team_id}")
            return _public_room_payload(team)

    @router.put("/api/teams/{team_id}")
    def update_team(
        request: Request,
        team_id: str,
        body: CreateTeamRoomRequest,
    ) -> dict[str, Any]:
        _require_room_editor(request, team_id)
        with lock:
            current = teams.get(team_id)
            if current is None:
                raise HTTPException(404, f"team not found: {team_id}")
            name = body.name.strip() or current.name
            members = [m for m in body.members if m.name.strip()] or current.members
            leader_id = body.leaderId or current.leaderId or members[0].name
            if leader_id not in {m.name for m in members}:
                leader_id = members[0].name
            updated = current.model_copy(
                update={
                    "name": name,
                    "members": members,
                    "leaderId": leader_id,
                    "updated_at": _now(),
                }
            )
            teams[team_id] = updated
            _save()
            return _public_room_payload(updated)

    @router.delete("/api/teams/{team_id}")
    def delete_team(request: Request, team_id: str) -> dict[str, Any]:
        actor = _require_owner(request, team_id)
        with lock:
            existed = teams.get(team_id)
            if existed is not None:
                invite_store.revoke_room(
                    tenant_id=existed.tenant_id,
                    room_id=existed.id,
                    revoked_by=actor or "local",
                )
                teams.pop(team_id, None)
                _save()
                _project_room_delete(existed.id)
            return {"ok": True, "deleted": existed is not None, "team_id": team_id}

    def _bind_project_store(bound_store: Any) -> None:
        """Late-bind the ProjectStore created after this router at app boot."""

        project_store_holder["store"] = bound_store

    def _replace_team_agent_members(
        request: Any,
        team_id: str,
        members: list[Any],
        leader_id: str | None = None,
    ) -> dict[str, Any]:
        """Project a canonical GroupStore AI roster into a linked TeamRoom.

        Human participants, the canonical thread binding, governance fields,
        and join-policy override are untouched.  The owner/admin gate keeps
        this internal seam from becoming a roster privilege escalation.
        """

        _actor, tenant_id = _require_invite_admin(request, team_id)
        normalized: list[TeamMemberWire] = []
        seen: set[str] = set()
        for raw in members:
            try:
                item = (
                    raw if isinstance(raw, TeamMemberWire) else TeamMemberWire.model_validate(raw)
                )
            except (TypeError, ValueError) as exc:
                raise HTTPException(400, "invalid team agent member") from exc
            name = item.name.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            normalized.append(item.model_copy(update={"name": name}))
        with lock:
            current = teams.get(team_id)
            if current is None:
                raise HTTPException(404, f"team not found: {team_id}")
            if current.tenant_id != tenant_id:
                raise HTTPException(403, f"not a member of team {team_id}")
            candidate_leader: str | None = str(leader_id or current.leaderId or "").strip() or None
            names = {item.name for item in normalized}
            if candidate_leader not in names:
                candidate_leader = normalized[0].name if normalized else None
            updated = current.model_copy(
                update={
                    "members": normalized,
                    "leaderId": candidate_leader,
                    "updated_at": _now(),
                }
            )
            teams[team_id] = updated
            try:
                _save()
            except Exception:
                teams[team_id] = current
                raise
            return _public_room_payload(updated)

    router.broadcast = _broadcast
    router.create_team_from_payload = _create_team_from_payload
    router.delete_team_from_payload = delete_team
    router.bind_team_thread = _bind_team_thread
    router.unbind_team_thread = _unbind_team_thread
    router.update_team_from_payload = _update_team_from_payload
    router.list_room_members = _list_room_members
    router.get_room_participant = _get_room_participant
    router.can_access_room = _can_access_room
    router.bind_project_store = _bind_project_store
    router.replace_team_agent_members = _replace_team_agent_members
    router.join_policy_for_room = _join_policy_for_room
    router.reset_state = _reset_state

    @router.patch("/api/teams/{team_id}/participants/{participant_id}")
    async def update_participant(
        request: Request,
        team_id: str,
        participant_id: str,
        body: UpdateTeamParticipantRequest,
    ) -> dict[str, Any]:
        actor = _require_member(request, team_id)
        with lock:
            team = teams.get(team_id)
            if team is None:
                raise HTTPException(404, f"team not found: {team_id}")
            current = next((p for p in team.participants if p.id == participant_id), None)
            if current is None:
                raise HTTPException(404, f"participant not found: {participant_id}")
            next_role = (
                _normalize_participant_role(body.role)
                if body.role is not None
                else _normalize_participant_role(current.role)
            )
            next_status = _normalize_participant_status(body.status or current.status)
            next_muted = body.muted if body.muted is not None else bool(current.muted)
            # Authorization (only meaningful when auth is enforced — local
            # single-user mode has no distinct actors to protect against).
            # A plain member may edit only their OWN display_name; changing
            # any role/status/mute, or touching another member's entry, is
            # owner-only. This is the security boundary, not just UX — the
            # frontend's hidden controls are not a substitute. (Self-unmute
            # is privileged too, else a muted member could silence-bust.)
            if require_auth and actor is not None and not _caller_is_team_admin(team, actor):
                is_self = getattr(current, "actor_id", None) == actor
                changing_role = next_role != _normalize_participant_role(current.role)
                changing_status = next_status != _normalize_participant_status(current.status)
                changing_muted = next_muted != bool(current.muted)
                if changing_role or changing_status or changing_muted:
                    raise HTTPException(
                        403,
                        "only the team owner can change a participant's role, status, or mute",
                    )
                if not is_self:
                    raise HTTPException(403, "you can only update your own participant entry")
            if current.role == "owner" and (next_role != "owner" or next_status == "removed"):
                other_owners = [
                    p
                    for p in team.participants
                    if p.id != participant_id
                    and p.status != "removed"
                    and _normalize_participant_role(p.role) == "owner"
                ]
                if not other_owners:
                    raise HTTPException(400, "team must keep at least one owner")
            next_name = (
                body.display_name.strip()
                if body.display_name is not None and body.display_name.strip()
                else current.display_name
            )
            now = _now()
            updated_participant = current.model_copy(
                update={
                    "display_name": next_name,
                    "role": next_role,
                    "status": next_status,
                    "muted": next_muted,
                    "last_seen_at": now,
                }
            )
            participants = [
                updated_participant if p.id == participant_id else p for p in team.participants
            ]
            team = team.model_copy(
                update={
                    "participants": participants,
                    "updated_at": now,
                }
            )
            teams[team_id] = team
            if next_status == "removed":
                live_sockets.get(team_id, {}).pop(participant_id, None)
            _save()
        await _broadcast_team_update(team_id, team)
        await _broadcast_presence(team_id)
        return {"team": _public_room_payload(team), "participant": updated_participant.model_dump()}

    @router.patch("/api/teams/{team_id}/speaker-policy")
    async def update_speaker_policy(
        request: Request,
        team_id: str,
        body: UpdateSpeakerPolicyRequest,
    ) -> dict[str, Any]:
        # Whole-room governance is owner-only — a member must not be able
        # to silence the room or lift a lock the owner imposed.
        _require_owner(request, team_id)
        policy = _normalize_speaker_policy(body.speaker_policy)
        with lock:
            team = teams.get(team_id)
            if team is None:
                raise HTTPException(404, f"team not found: {team_id}")
            team = team.model_copy(
                update={
                    "speaker_policy": policy,
                    **_initial_floor_state(team, policy),
                    "updated_at": _now(),
                }
            )
            teams[team_id] = team
            _save()
        await _broadcast_team_update(team_id, team)
        return {"team": _public_room_payload(team), "speaker_policy": policy}

    @router.patch("/api/teams/{team_id}/participants/{participant_id}/delegation")
    async def update_delegation(
        request: Request,
        team_id: str,
        participant_id: str,
        body: UpdateDelegationRequest,
    ) -> dict[str, Any]:
        # SELF-ONLY opt-in. Unlike mute (owner-only), delegation is the
        # bound person's own choice — letting an admin bind a twin/host to
        # someone else would be impersonation. So the caller must BE the
        # participant. No-op gate under local single-user mode.
        actor = _require_member(request, team_id)
        mode = _normalize_speak_mode(body.speak_mode)
        twin = (body.twin_agent_id or "").strip() or None
        host = (body.host_id or "").strip() or None
        with lock:
            team = teams.get(team_id)
            if team is None:
                raise HTTPException(404, f"team not found: {team_id}")
            current = next((p for p in team.participants if p.id == participant_id), None)
            if current is None:
                raise HTTPException(404, f"participant not found: {participant_id}")
            if require_auth and actor is not None and getattr(current, "actor_id", None) != actor:
                raise HTTPException(
                    403, "only the participant themselves can set their speaking delegation"
                )
            if mode == "twin" and not twin:
                raise HTTPException(400, "twin mode requires twin_agent_id")
            if mode == "hosted" and not host:
                raise HTTPException(400, "hosted mode requires host_id")
            updated = current.model_copy(
                update={
                    "speak_mode": mode,
                    "twin_agent_id": twin if mode == "twin" else None,
                    "host_id": host if mode == "hosted" else None,
                    "last_seen_at": _now(),
                }
            )
            participants = [updated if p.id == participant_id else p for p in team.participants]
            team = team.model_copy(update={"participants": participants, "updated_at": _now()})
            teams[team_id] = team
            _save()
        await _broadcast_team_update(team_id, team)
        return {"team": _public_room_payload(team), "participant": updated.model_dump()}

    @router.delete("/api/teams/{team_id}/participants/{participant_id}")
    async def remove_participant(
        request: Request,
        team_id: str,
        participant_id: str,
    ) -> dict[str, Any]:
        actor = _require_member(request, team_id)
        socket: WebSocket | None = None
        socket_loop: asyncio.AbstractEventLoop | None = None
        with lock:
            team = teams.get(team_id)
            if team is None:
                raise HTTPException(404, f"team not found: {team_id}")
            current = next((p for p in team.participants if p.id == participant_id), None)
            if current is None:
                raise HTTPException(404, f"participant not found: {participant_id}")
            # A plain member may remove only themselves (leave the room);
            # kicking anyone else is owner-only. No-op under local
            # single-user mode where auth is not enforced.
            if (
                require_auth
                and actor is not None
                and not _caller_is_team_admin(team, actor)
                and getattr(current, "actor_id", None) != actor
            ):
                raise HTTPException(403, "only the team owner can remove other participants")
            if current.role == "owner":
                other_owners = [
                    p
                    for p in team.participants
                    if p.id != participant_id
                    and p.status != "removed"
                    and _normalize_participant_role(p.role) == "owner"
                ]
                if not other_owners:
                    raise HTTPException(400, "team must keep at least one owner")
            now = _now()
            participants = [
                p.model_copy(update={"status": "removed", "last_seen_at": now})
                if p.id == participant_id
                else p
                for p in team.participants
            ]
            team = team.model_copy(
                update={
                    "participants": participants,
                    "updated_at": now,
                }
            )
            teams[team_id] = team
            socket = live_sockets.get(team_id, {}).pop(participant_id, None)
            socket_loop = socket_loops.get(team_id, {}).pop(participant_id, None)
            _save()
        if socket is not None:
            with contextlib.suppress(Exception):
                current_loop = asyncio.get_running_loop()
                if socket_loop is None or socket_loop is current_loop:
                    await socket.close(code=4403)
                elif not socket_loop.is_closed():
                    closed = asyncio.run_coroutine_threadsafe(socket.close(code=4403), socket_loop)
                    await asyncio.wrap_future(closed)
        await _broadcast_team_update(team_id, team)
        await _broadcast_presence(team_id)
        return {"ok": True, "team": _public_room_payload(team), "participant_id": participant_id}

    register_team_invitation_routes(
        router=router,
        teams=teams,
        lock=lock,
        store=invite_store,
        require_auth=require_auth,
        principal_for=_principal,
        tenant_for=_tenant,
        require_admin=_require_invite_admin,
        require_member=_require_member,
        save_rooms=_save,
        room_payload=_public_room_payload,
        join_policy_for=_join_policy_for_room,
        project_id_for=_project_id_for_room,
    )
    if room_message_store is None:
        from runtime.memory.cowork.room_messages import RoomMessageStore

        room_message_store = RoomMessageStore(
            base_dir=(state_path.parent / "teamroom") if state_path else None,
        )

    _ws_ctx = TeamRoomWsContext(
        teams=teams,
        lock=lock,
        live_sockets=live_sockets,
        socket_loops=socket_loops,
        auth=_auth,
        save=_save,
        broadcast=_broadcast,
        broadcast_presence=_broadcast_presence,
        broadcast_floor=_broadcast_floor,
        active_participant=_active_participant,
        require_auth=require_auth,
        twin_responder=twin_responder,
        message_store=room_message_store,
        message_projection=room_message_projection,
    )

    @router.get("/api/teams/{team_id}/messages")
    def get_room_messages(
        request: Request,
        team_id: str,
        limit: int = 200,
        after_seq: int = 0,
        q: str = "",
    ) -> dict[str, Any]:
        """Durable room transcript — reconnect catch-up (``after_seq``) and
        search (``q``). Closes the gap where room chat was live-only / a 20-line
        in-memory ring."""
        _require_member(request, team_id)
        messages: list[dict[str, Any]] = []
        if room_message_provider is not None:
            try:
                messages = room_message_provider(team_id, limit, after_seq, q)
            except Exception:  # noqa: BLE001 - canonical transcript lookup is best-effort
                messages = []
        if not messages:
            if q.strip():
                messages = room_message_store.search(team_id, q, limit=limit)
            else:
                messages = room_message_store.history(team_id, limit=limit, after_seq=after_seq)
        return {"team_id": team_id, "messages": messages}

    @router.websocket("/api/teams/{team_id}/ws")
    async def team_room_ws_route(ws: WebSocket, team_id: str) -> None:
        """Realtime Team Room presence + event broadcast — see
        team_rooms_ws.team_room_ws (split out to keep this module small)."""
        await team_room_ws(_ws_ctx, ws, team_id)

    return router


__all__ = [
    "CreateTeamInviteRequest",
    "CreateTeamRoomRequest",
    "JoinInviteRequest",
    "RejectTeamJoinRequest",
    "TeamMemberWire",
    "TeamParticipantWire",
    "TeamRoomWire",
    "UpdateDelegationRequest",
    "UpdateTeamJoinPolicyRequest",
    "UpdateSpeakerPolicyRequest",
    "UpdateTeamParticipantRequest",
    "create_team_rooms_router",
    # Re-exported from team_speaker_policy so existing
    # ``from team_rooms_router import _participant_can_speak`` call sites
    # (the unit tests) keep working after the split.
    "_authorized_to_speak_for",
    "_next_speaker",
    "_participant_can_speak",
]
