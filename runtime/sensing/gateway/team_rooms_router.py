"""Persistent team rooms API.

This is the backend foundation for cross-device Team mode and, later,
human collaboration rooms. It deliberately stores fixed AI team config
and human participants separately: AI team members drive agent routing;
participants represent real people who may join through invite links.
"""

from __future__ import annotations

import contextlib
import json
import re
import secrets
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from runtime.platform.process.paths import app_paths

try:
    from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]
    WebSocket = None  # type: ignore[assignment,misc]
    WebSocketDisconnect = None  # type: ignore[assignment,misc]


class TeamMemberWire(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    display_name: str | None = None
    description: str = ""
    icon: str | None = None
    avatar_url: str | None = None
    model: str | None = None
    tool_groups: list[str] | None = None


class TeamParticipantWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    display_name: str
    role: str = "guest"
    actor_id: str | None = None
    joined_at: str
    last_seen_at: str | None = None
    status: str = "active"
    # Governance: an admin-imposed per-member mute. Applies on top of any
    # room ``speaker_policy`` — a muted member cannot broadcast messages
    # regardless of the policy. Only the team owner can set it.
    muted: bool = False


class TeamRoomWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    members: list[TeamMemberWire] = Field(default_factory=list)
    leaderId: str | None = None  # noqa: N815 — frontend wire field uses camelCase
    owner_id: str | None = None
    created_at: str
    updated_at: str
    participants: list[TeamParticipantWire] = Field(default_factory=list)
    invite_token: str | None = None
    invite_role: str = "member"
    invite_created_at: str | None = None
    # Governance: who may speak in the room. ``free`` = anyone not
    # individually muted; ``admin_only`` = only the owner/admins (a
    # whole-room mute). Turn-based modes (moderated/round_robin/roll_call)
    # are reserved for the speaker-turn engine and are not enforced yet.
    speaker_policy: str = "free"


class CreateTeamRoomRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    name: str
    members: list[TeamMemberWire] = Field(default_factory=list)
    leaderId: str | None = None  # noqa: N815 — frontend wire field uses camelCase


class JoinInviteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_name: str | None = None
    participant_id: str | None = None


class CreateTeamInviteRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    role: str = "member"


class UpdateTeamParticipantRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    display_name: str | None = None
    role: str | None = None
    status: str | None = None
    muted: bool | None = None


class UpdateSpeakerPolicyRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    speaker_policy: str


def create_team_rooms_router(
    *,
    state_path: Path | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    reset_callback: Any = None,
) -> Any:
    """Create `/api/teams/*` routes."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["team-rooms"])
    path = state_path or (app_paths().data_dir / "team_rooms.json")
    lock = Lock()
    teams: dict[str, TeamRoomWire] = _load_state(path)
    live_sockets: dict[str, dict[str, WebSocket]] = {}

    def _auth(request: Any) -> str | None:
        from .openai_gateway_router import _resolve_actor

        return _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _save() -> None:
        _save_state(path, teams)

    def _reset_state() -> None:
        with lock:
            teams.clear()
            live_sockets.clear()
        if callable(reset_callback):
            reset_callback()

    def _create_team_for_actor(
        actor: str | None,
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
            _save()
        return team

    def _create_team_from_payload(
        request: Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = CreateTeamRoomRequest.model_validate(payload)
        return _create_team_for_actor(_auth(request), body).model_dump()

    async def _update_team_from_payload(
        request: Request,
        team_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        _require_member(request, team_id)
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
            updated = current.model_copy(update={
                "name": name,
                "members": members,
                "leaderId": leader_id,
                "updated_at": _now(),
            })
            teams[team_id] = updated
            _save()
        await _broadcast_team_update(team_id, updated)
        return updated.model_dump()

    def _presence_payload(team_id: str) -> dict[str, Any]:
        team = teams.get(team_id)
        participants = team.participants if team else []
        online_ids = set(live_sockets.get(team_id, {}).keys())
        return {
            "type": "presence",
            "team_id": team_id,
            "participants": [
                p.model_dump()
                for p in participants
                if p.status == "active" and p.id in online_ids
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
        sockets = list(live_sockets.get(team_id, {}).items())
        dead: list[str] = []
        for participant_id, socket in sockets:
            if exclude and participant_id == exclude:
                continue
            try:
                await socket.send_json(payload)
            except (ConnectionError, TimeoutError, OSError):
                dead.append(participant_id)
        if dead:
            with lock:
                room = live_sockets.get(team_id)
                if room:
                    for participant_id in dead:
                        room.pop(participant_id, None)

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
                "team": team.model_dump(),
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
        actor = _auth(request)
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
            if require_auth and actor:
                visible = [
                    team for team in all_teams
                    if actor == getattr(team, "owner_id", None)
                    or any(
                        getattr(p, "actor_id", None) == actor
                        and p.status == "active"
                        for p in team.participants
                    )
                ]
            else:
                visible = list(all_teams)
            return {
                "teams": [team.model_dump() for team in visible],
                "count": len(visible),
            }

    @router.post("/api/teams")
    def create_team(
        request: Request,
        body: CreateTeamRoomRequest,
    ) -> dict[str, Any]:
        team = _create_team_for_actor(_auth(request), body)
        return team.model_dump()

    @router.get("/api/teams/{team_id}")
    def get_team(request: Request, team_id: str) -> dict[str, Any]:
        _require_member(request, team_id)
        with lock:
            team = teams.get(team_id)
            if team is None:
                raise HTTPException(404, f"team not found: {team_id}")
            return team.model_dump()

    @router.put("/api/teams/{team_id}")
    def update_team(
        request: Request,
        team_id: str,
        body: CreateTeamRoomRequest,
    ) -> dict[str, Any]:
        _require_member(request, team_id)
        with lock:
            current = teams.get(team_id)
            if current is None:
                raise HTTPException(404, f"team not found: {team_id}")
            name = body.name.strip() or current.name
            members = [m for m in body.members if m.name.strip()] or current.members
            leader_id = body.leaderId or current.leaderId or members[0].name
            if leader_id not in {m.name for m in members}:
                leader_id = members[0].name
            updated = current.model_copy(update={
                "name": name,
                "members": members,
                "leaderId": leader_id,
                "updated_at": _now(),
            })
            teams[team_id] = updated
            _save()
            return updated.model_dump()

    @router.delete("/api/teams/{team_id}")
    def delete_team(request: Request, team_id: str) -> dict[str, Any]:
        _require_owner(request, team_id)
        with lock:
            existed = teams.pop(team_id, None)
            if existed is not None:
                _save()
            return {"ok": True, "deleted": existed is not None, "team_id": team_id}

    def _list_room_members(team_id: str) -> list[str]:
        """Return actor ids allowed to operate on ``team_id``. Used by
        sibling routers (e.g. team_tasks) to enforce membership."""
        with lock:
            team = teams.get(team_id)
            if team is None:
                return []
            actors: list[str] = []
            owner = getattr(team, "owner_id", None)
            if owner:
                actors.append(owner)
            for participant in team.participants:
                if participant.status != "active":
                    continue
                actor_id = getattr(participant, "actor_id", None) or participant.id
                if actor_id and actor_id not in actors:
                    actors.append(actor_id)
            return actors

    def _require_member(request: Any, team_id: str) -> str | None:
        """Enforce team membership. Returns actor_id if authorized.

        No-op when ``require_auth`` is off (single-user dev mode):
        ``_auth`` returns None, the room may have no actor binding, and
        we don't want to break local dev. When ``require_auth=True``
        AND we have an actor, the membership check is enforced.

        Safe to call from both inside and outside lock contexts —
        ``_list_room_members`` takes the lock internally.
        """
        actor = _auth(request)
        if not require_auth:
            return actor
        if not actor:
            raise HTTPException(401, "authentication required")
        allowed = _list_room_members(team_id)
        if actor not in allowed:
            raise HTTPException(403, f"not a member of team {team_id}")
        return actor

    def _require_owner(request: Any, team_id: str) -> str | None:
        """Enforce ownership (stricter than membership).
        Used for destructive operations like DELETE.
        """
        actor = _auth(request)
        if not require_auth:
            return actor
        if not actor:
            raise HTTPException(401, "authentication required")
        with lock:
            team = teams.get(team_id)
            if team is None:
                raise HTTPException(404, f"team not found: {team_id}")
            owner = getattr(team, "owner_id", None)
            if actor != owner:
                raise HTTPException(403, "only the team owner can delete the team")
        return actor

    def _caller_is_team_admin(team: Any, actor: str | None) -> bool:
        """True if ``actor`` is the team owner — either the recorded
        ``owner_id`` or an active participant whose role is ``owner``.
        Used to gate participant role/status mutations and the removal
        of *other* members. Returns False for unauthenticated callers."""
        if not actor:
            return False
        if actor == getattr(team, "owner_id", None):
            return True
        for p in getattr(team, "participants", []):
            if (
                getattr(p, "actor_id", None) == actor
                and getattr(p, "status", None) != "removed"
                and _normalize_participant_role(p.role) == "owner"
            ):
                return True
        return False

    router.broadcast = _broadcast
    router.create_team_from_payload = _create_team_from_payload
    router.update_team_from_payload = _update_team_from_payload
    router.list_room_members = _list_room_members
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
                    p for p in team.participants
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
            updated_participant = current.model_copy(update={
                "display_name": next_name,
                "role": next_role,
                "status": next_status,
                "muted": next_muted,
                "last_seen_at": now,
            })
            participants = [
                updated_participant if p.id == participant_id else p
                for p in team.participants
            ]
            team = team.model_copy(update={
                "participants": participants,
                "updated_at": now,
            })
            teams[team_id] = team
            if next_status == "removed":
                live_sockets.get(team_id, {}).pop(participant_id, None)
            _save()
        await _broadcast_team_update(team_id, team)
        await _broadcast_presence(team_id)
        return {"team": team.model_dump(), "participant": updated_participant.model_dump()}

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
            team = team.model_copy(update={"speaker_policy": policy, "updated_at": _now()})
            teams[team_id] = team
            _save()
        await _broadcast_team_update(team_id, team)
        return {"team": team.model_dump(), "speaker_policy": policy}

    @router.delete("/api/teams/{team_id}/participants/{participant_id}")
    async def remove_participant(
        request: Request,
        team_id: str,
        participant_id: str,
    ) -> dict[str, Any]:
        actor = _require_member(request, team_id)
        socket: WebSocket | None = None
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
                    p for p in team.participants
                    if p.id != participant_id
                    and p.status != "removed"
                    and _normalize_participant_role(p.role) == "owner"
                ]
                if not other_owners:
                    raise HTTPException(400, "team must keep at least one owner")
            now = _now()
            participants = [
                p.model_copy(update={"status": "removed", "last_seen_at": now})
                if p.id == participant_id else p
                for p in team.participants
            ]
            team = team.model_copy(update={
                "participants": participants,
                "updated_at": now,
            })
            teams[team_id] = team
            socket = live_sockets.get(team_id, {}).pop(participant_id, None)
            _save()
        if socket is not None:
            with contextlib.suppress(Exception):
                await socket.close(code=4403)
        await _broadcast_team_update(team_id, team)
        await _broadcast_presence(team_id)
        return {"ok": True, "team": team.model_dump(), "participant_id": participant_id}

    @router.post("/api/teams/{team_id}/invite")
    def create_invite(
        request: Request,
        team_id: str,
        body: CreateTeamInviteRequest | None = None,
    ) -> dict[str, Any]:
        _require_member(request, team_id)
        with lock:
            team = teams.get(team_id)
            if team is None:
                raise HTTPException(404, f"team not found: {team_id}")
            token = team.invite_token or secrets.token_urlsafe(24)
            invite_role = _normalize_participant_role(body.role if body else None)
            team = team.model_copy(update={
                "invite_token": token,
                "invite_role": invite_role,
                "invite_created_at": team.invite_created_at or _now(),
                "updated_at": _now(),
            })
            teams[team_id] = team
            _save()
            return {
                "team_id": team_id,
                "invite_token": token,
                "invite_role": invite_role,
                "invite_path": f"/workspace/team/join?token={token}",
                "invite_hash_path": f"/#/workspace/team/join?token={token}",
            }

    @router.get("/api/team-invites/{token}")
    def inspect_invite(request: Request, token: str) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic — anyone with an invite token may preview
        with lock:
            team = _team_by_invite(teams, token)
            if team is None:
                raise HTTPException(404, "invite not found")
            return {"team": team.model_dump()}

    @router.post("/api/team-invites/{token}/join")
    def join_invite(
        request: Request,
        token: str,
        body: JoinInviteRequest,
    ) -> dict[str, Any]:
        actor = _auth(request)
        with lock:
            team = _team_by_invite(teams, token)
            if team is None:
                raise HTTPException(404, "invite not found")
            now = _now()
            participant_id = (
                body.participant_id
                or (f"actor-{actor}" if actor else f"guest-{uuid4().hex[:10]}")
            )
            display_name = body.display_name or actor or "Guest"
            participants = [
                p for p in team.participants
                if p.id != participant_id
            ]
            participant = TeamParticipantWire(
                id=participant_id,
                display_name=display_name,
                role=_normalize_participant_role(team.invite_role),
                actor_id=actor,
                joined_at=now,
                last_seen_at=now,
            )
            participants.append(participant)
            team = team.model_copy(update={
                "participants": participants,
                "updated_at": now,
            })
            teams[team.id] = team
            _save()
            return {
                "team": team.model_dump(),
                "participant": participant.model_dump(),
            }

    @router.websocket("/api/teams/{team_id}/ws")
    async def team_room_ws(ws: WebSocket, team_id: str) -> None:
        """Realtime Team Room presence and lightweight event broadcast."""
        actor: str | None = None
        auth_error: str | None = None
        try:
            actor = _auth(ws)
        except Exception as exc:
            auth_error = str(getattr(exc, "detail", None) or exc or "unauthorized")

        await ws.accept()
        if auth_error is not None:
            await ws.send_json({"type": "error", "message": auth_error})
            await ws.close(code=4401)
            return

        participant_id = (
            ws.query_params.get("participant_id")
            or f"guest-{uuid4().hex[:10]}"
        )
        display_name = ws.query_params.get("display_name") or "Guest"
        thread_id = (ws.query_params.get("thread_id") or "").strip() or None
        now = _now()
        ready_payload: dict[str, Any] | None = None
        reject_reason: str | None = None
        with lock:
            team = teams.get(team_id)
            if team is not None:
                existing = next(
                    (p for p in team.participants if p.id == participant_id),
                    None,
                )
                if existing and existing.status == "removed":
                    reject_reason = "participant removed"
                elif (
                    existing is not None
                    and existing.actor_id
                    and actor is not None
                    and existing.actor_id != actor
                ):
                    reject_reason = "participant actor mismatch"
                else:
                    participants = [
                        p for p in team.participants
                        if p.id != participant_id
                    ]
                    participant = TeamParticipantWire(
                        id=participant_id,
                        display_name=display_name,
                        role=_normalize_participant_role(existing.role if existing else "viewer"),
                        actor_id=existing.actor_id if existing and existing.actor_id else actor,
                        joined_at=existing.joined_at if existing else now,
                        last_seen_at=now,
                        status="active",
                        # Preserve an admin-imposed mute across reconnects —
                        # otherwise a muted member could silence-bust by
                        # simply dropping and re-opening the socket.
                        muted=bool(existing.muted) if existing else False,
                    )
                    participants.append(participant)
                    team = team.model_copy(update={
                        "participants": participants,
                        "updated_at": now,
                    })
                    teams[team_id] = team
                    live_sockets.setdefault(team_id, {})[participant_id] = ws
                    _save()
                    ready_payload = {
                        "type": "ready",
                        "team": team.model_dump(),
                        "participant": participant.model_dump(),
                        "server_time": now,
                    }

        if ready_payload is None:
            await ws.send_json({"type": "error", "message": reject_reason or "team not found"})
            await ws.close(code=4403 if reject_reason else 4404)
            return

        await ws.send_json(ready_payload)
        await _broadcast_presence(team_id)

        try:
            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")
                with lock:
                    active_participant = _active_participant(team_id, participant_id)
                    current_team = teams.get(team_id)
                if active_participant is None:
                    await ws.send_json({"type": "error", "message": "participant removed"})
                    await ws.close(code=4403)
                    return
                if msg_type in {"ping", "presence:ping"}:
                    with lock:
                        current = teams.get(team_id)
                        if current is not None:
                            seen = _now()
                            participants = [
                                p.model_copy(update={
                                    "last_seen_at": seen,
                                    "status": "active",
                                })
                                if p.id == participant_id else p
                                for p in current.participants
                            ]
                            teams[team_id] = current.model_copy(update={
                                "participants": participants,
                                "updated_at": seen,
                            })
                            _save()
                    await ws.send_json({"type": "pong", "server_time": _now()})
                    await _broadcast_presence(team_id)
                elif msg_type == "cursor":
                    msg_thread_id = str(msg.get("thread_id") or thread_id or "").strip() or None
                    await _broadcast(
                        team_id,
                        {
                            "type": "cursor",
                            "team_id": team_id,
                            "thread_id": msg_thread_id,
                            "participant_id": participant_id,
                            "position": msg.get("position"),
                            "server_time": _now(),
                        },
                        exclude=participant_id,
                    )
                elif msg_type == "message":
                    text = str(msg.get("text") or "").strip()
                    if not text:
                        continue
                    # Speech chokepoint: enforce the per-member mute and the
                    # room speaker policy before the message reaches anyone.
                    # Reuses the snapshot taken under the lock at the top of
                    # this iteration — no second acquisition (a second lock in
                    # this hot path deadlocks the two-socket portal in tests).
                    if current_team is None:
                        allowed, reason = False, "participant removed"
                    else:
                        allowed, reason = _participant_can_speak(current_team, active_participant)
                    if not allowed:
                        await ws.send_json(
                            {"type": "error", "code": "speech_denied", "message": reason}
                        )
                        continue
                    msg_thread_id = str(msg.get("thread_id") or thread_id or "").strip() or None
                    await _broadcast(
                        team_id,
                        {
                            "type": "message",
                            "team_id": team_id,
                            "thread_id": msg_thread_id,
                            "message_id": f"room-msg-{uuid4().hex}",
                            "participant_id": participant_id,
                            "display_name": display_name,
                            "text": text[:4000],
                            "created_at": _now(),
                        },
                    )
                elif msg_type == "thread:update":
                    msg_thread_id = str(msg.get("thread_id") or thread_id or "").strip() or None
                    if not msg_thread_id:
                        continue
                    await _broadcast(
                        team_id,
                        {
                            "type": "thread:update",
                            "team_id": team_id,
                            "thread_id": msg_thread_id,
                            "participant_id": participant_id,
                            "display_name": display_name,
                            "reason": str(msg.get("reason") or "updated")[:80],
                            "created_at": _now(),
                        },
                    )
        except WebSocketDisconnect:  # noqa: BLE001 — WS closed normally during send; cleanup proceeds
            pass
        except (ConnectionError, TimeoutError, OSError):  # noqa: BLE001 — WS send failed; cleanup proceeds
            pass
        finally:
            with lock:
                room = live_sockets.get(team_id)
                if room and room.get(participant_id) is ws:
                    room.pop(participant_id, None)
                current = teams.get(team_id)
                if current is not None:
                    left_at = _now()
                    participants = [
                        p.model_copy(update={
                            "last_seen_at": left_at,
                            "status": "offline",
                        })
                        if p.id == participant_id else p
                        for p in current.participants
                    ]
                    teams[team_id] = current.model_copy(update={
                        "participants": participants,
                        "updated_at": left_at,
                    })
                    _save()
            await _broadcast_presence(team_id)

    return router


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _slug_id(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return f"team-{slug or uuid4().hex[:8]}"


def _unique_team_id(candidate: str, teams: dict[str, TeamRoomWire]) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_-]+", "-", candidate.strip()).strip("-")
    clean = clean or f"team-{uuid4().hex[:8]}"
    if clean not in teams:
        return clean
    return f"{clean}-{uuid4().hex[:6]}"


def _normalize_participant_role(role: str | None) -> str:
    normalized = (role or "member").strip().lower()
    aliases = {
        "admin": "owner",
        "viewer": "viewer",
        "read_only": "viewer",
        "readonly": "viewer",
        "guest": "viewer",
        "collaborator": "member",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in {"owner", "member", "viewer"}:
        return "member"
    return normalized


def _normalize_participant_status(status: str | None) -> str:
    normalized = (status or "active").strip().lower()
    if normalized not in {"active", "offline", "removed"}:
        return "active"
    return normalized


# Speaker policies the room can currently *enforce*. Turn-based modes
# (moderated/round_robin/roll_call) are intentionally absent until the
# speaker-turn engine lands — persisting a mode we don't enforce would be
# a lie to the operator. Unknown values fall back to the open default.
_SPEAKER_POLICIES = {"free", "admin_only"}


def _normalize_speaker_policy(value: str | None) -> str:
    normalized = (value or "free").strip().lower()
    aliases = {
        "open": "free",
        "all": "free",
        "everyone": "free",
        "admins_only": "admin_only",
        "admin": "admin_only",
        "owner_only": "admin_only",
        "muted": "admin_only",
        "locked": "admin_only",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in _SPEAKER_POLICIES:
        return "free"
    return normalized


def _participant_is_admin(team: TeamRoomWire, participant: TeamParticipantWire) -> bool:
    """An admin is an owner-role participant, or the recorded room owner."""
    if _normalize_participant_role(participant.role) == "owner":
        return True
    actor_id = getattr(participant, "actor_id", None)
    return bool(actor_id) and actor_id == getattr(team, "owner_id", None)


def _participant_can_speak(
    team: TeamRoomWire, participant: TeamParticipantWire
) -> tuple[bool, str | None]:
    """Resolve whether ``participant`` may broadcast a message right now.
    Returns ``(allowed, reason)`` — ``reason`` is a human-facing string
    when denied. This is the room's single speech chokepoint."""
    if getattr(participant, "muted", False):
        return False, "you have been muted by an admin"
    policy = _normalize_speaker_policy(getattr(team, "speaker_policy", "free"))
    if policy == "admin_only" and not _participant_is_admin(team, participant):
        return False, "only admins can speak while the room is in admin-only mode"
    return True, None


def _team_by_invite(
    teams: dict[str, TeamRoomWire],
    token: str,
) -> TeamRoomWire | None:
    for team in teams.values():
        if team.invite_token == token:
            return team
    return None


def _load_state(path: Path) -> dict[str, TeamRoomWire]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    items = raw.get("teams") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return {}
    out: dict[str, TeamRoomWire] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            team = TeamRoomWire.model_validate(item)
        except (ValueError, TypeError):
            continue
        out[team.id] = team
    return out


def _save_state(path: Path, teams: dict[str, TeamRoomWire]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "teams": [team.model_dump() for team in teams.values()],
        "updated_at": _now(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


__all__ = ["create_team_rooms_router"]
