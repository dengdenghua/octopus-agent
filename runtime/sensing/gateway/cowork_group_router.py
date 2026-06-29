"""Thread-group API: WeChat-style membership + mode + shared blackboard.

A thread *is* the group (1:1 = the N=2 case), so these endpoints hang off the
thread id. Reads (the folded roster + blackboard) are public; mutations (pull
someone in / out, switch mode, write the shared board) are auth-gated and
attributed to the resolved actor — the same actor model the other routers use.

Path is ``/api/cowork/*`` to avoid colliding with ``/api/groups/*`` (which is the
static AgentGroupRegistry of agent-team *templates*, a different concept).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from runtime.memory.cowork.group import (
    ContextGrant,
    MemberEvent,
    responders,
)
from runtime.memory.cowork.group_store import GroupStore


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
    mode: str  # chat | cluster | swarm


class BoardBody(BaseModel):
    key: str = Field(min_length=1)
    value: Any = None


def create_cowork_group_router(
    *,
    store: GroupStore | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create the ``/api/cowork/*`` thread-group router."""
    group_store = store or GroupStore()

    def _actor(request: Request) -> str:
        from runtime.adapters.web_auth import _resolve_actor

        actor = _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
        return actor or "user"

    def _auth_dep(request: Request) -> None:
        _actor(request)  # enforces 401 when require_auth and no/invalid token

    router = APIRouter(tags=["cowork"])

    @router.get("/api/cowork/{thread_id}")
    def get_group(thread_id: str) -> dict[str, Any]:
        """Folded group state (roster + mode), the shared blackboard, the raw
        membership timeline, and who would respond this turn under the mode."""
        state = group_store.state(thread_id)
        return {
            "thread_id": thread_id,
            "state": state.to_dict(),
            "blackboard": group_store.blackboard_snapshot(thread_id),
            "events": [e.to_dict() for e in group_store.events(thread_id)],
            "responders": responders(state),
        }

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

    @router.delete(
        "/api/cowork/{thread_id}/members/{member_id}", dependencies=[Depends(_auth_dep)]
    )
    def remove_member(thread_id: str, member_id: str, request: Request) -> dict[str, Any]:
        """Remove a member. Their past blackboard writes stay (attributed)."""
        group_store.append(
            thread_id,
            MemberEvent(action="leave", actor=_actor(request), target_id=member_id),
        )
        return {"ok": True, "state": group_store.state(thread_id).to_dict()}

    @router.post("/api/cowork/{thread_id}/mode", dependencies=[Depends(_auth_dep)])
    def set_mode(thread_id: str, body: ModeBody, request: Request) -> dict[str, Any]:
        """Switch the collaboration mode (chat/cluster/swarm) — non-destructive."""
        if body.mode not in ("chat", "cluster", "swarm"):
            raise HTTPException(400, "mode must be chat | cluster | swarm")
        group_store.append(
            thread_id,
            MemberEvent(action="mode", actor=_actor(request), mode=body.mode),  # type: ignore[arg-type]
        )
        return {"ok": True, "state": group_store.state(thread_id).to_dict()}

    @router.post("/api/cowork/{thread_id}/blackboard", dependencies=[Depends(_auth_dep)])
    def write_board(thread_id: str, body: BoardBody, request: Request) -> dict[str, Any]:
        """Write a key to the group's shared blackboard, attributed to the actor."""
        board = group_store.blackboard(thread_id)
        board.write(body.key, body.value, writer=_actor(request))
        return {"ok": True, "blackboard": group_store.blackboard_snapshot(thread_id)}

    return router
