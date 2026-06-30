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


def create_cowork_group_router(
    *,
    store: GroupStore | None = None,
    async_store: Any = None,
    runtime: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create the ``/api/cowork/*`` thread-group router."""
    group_store = store or GroupStore()

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

    @router.get("/api/cowork/{thread_id}/nominate")
    def nominate_turn(thread_id: str, text: str = "", threshold: float = 0.5) -> dict[str, Any]:
        """Self-nomination gate: of the participant agents, who is relevant enough
        to speak for ``text`` — so a swarm doesn't pile on every turn."""
        from runtime.memory.cowork.nominate import gate

        state = group_store.state(thread_id)
        participants = [
            (m.id, m.id) for m in state.roster
            if m.kind == "agent" and m.role == "participant" and not m.muted
        ]
        return {"nominated": gate(participants, text, threshold=threshold)}

    @router.get("/api/cowork/{thread_id}/search")
    def search(
        thread_id: str,
        q: str = "",
        limit: int = 20,
        kinds: str = "",
        until_seq: int | None = None,
    ) -> dict[str, Any]:
        """Replayable group search across the shared blackboard, async tasks,
        and the membership/mode event log. ``kinds`` is a comma-separated
        subset of ``blackboard,task,event`` (default all); ``until_seq`` bounds
        the event scan to a past point (time-travel)."""
        from runtime.memory.cowork.search import search_group

        kind_filter = tuple(k.strip() for k in kinds.split(",") if k.strip()) or None
        hits = search_group(
            group_store,
            thread_id,
            q,
            limit=max(1, min(100, limit)),
            kinds=kind_filter,
            until_seq=until_seq,
            async_store=_async_store(),
        )
        return {"thread_id": thread_id, "query": q, "hits": [h.to_dict() for h in hits]}

    @router.get("/api/cowork/{thread_id}/presence")
    def presence(thread_id: str, online_window_s: int = 60) -> dict[str, Any]:
        """Per-member presence + unread for the thread's roster. Unread counts
        group events past each member's read marker (floored at their join)."""
        from runtime.memory.cowork.presence import group_presence

        members = group_presence(
            group_store, _presence_store(), thread_id,
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
            group_store.state(thread_id), member_id, messages=[],
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
        ok = _async_store().complete(task_id, body.result, blackboard_key=body.blackboard_key)
        if not ok:
            raise HTTPException(404, "task not found")
        return {"ok": True, "blackboard": group_store.blackboard_snapshot(thread_id)}

    @router.post("/api/cowork/{thread_id}/breakout", dependencies=[Depends(_auth_dep)])
    def breakout_fork(thread_id: str, body: BreakoutBody, request: Request) -> dict[str, Any]:
        """Spin off a focused side-thread with a subset of members + a grant."""
        from runtime.memory.cowork.breakout import fork
        from runtime.memory.cowork.group import ContextGrant

        res = fork(
            group_store, thread_id, body.child_thread, actor=_actor(request),
            members=body.members, grant=ContextGrant.from_dict(body.grant),
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

        res = merge_back(group_store, child_thread, thread_id, actor=_actor(request),
                         summary=body.summary)
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
        """Switch the collaboration mode (chat/cluster/swarm/project) —
        non-destructive. 'project' runs the milestone-driven Project OS over the
        group; there is no separate project entity."""
        if body.mode not in ("chat", "cluster", "swarm", "project"):
            raise HTTPException(400, "mode must be chat | cluster | swarm | project")
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
