"""Persistent team tasks API.

A team task is the unit of "work" inside a team room — distinct from
chat messages or the AI roster. Each task represents a goal the team
(humans + agents) is collaborating on, optionally driven by a SOP /
meta-skill workflow.

This router intentionally mirrors ``team_rooms_router`` in shape:
JSON-on-disk persistence, a Lock-guarded in-memory dict, the same auth
hook, and matching field naming so the frontend can reuse client
patterns. WebSocket presence + invite are NOT included — task lifecycle
events will be broadcast through the existing team-room WS in a later
patch (P3) when TeamRunner is wired in.

Schema notes:
- ``room_id`` ties each task to exactly one team room. Listing scopes
  by room_id; cross-room queries are not supported by design.
- ``sop_template`` is the meta-skill name (matches a YAML in
  ``meta_skills/``); empty means "freeform task without a workflow".
- ``assignees`` is a list of {kind: "agent"|"participant", ref: name|id}
  so a task can be assigned to AI roster members AND human participants
  uniformly. The runner side will fan out per-kind in P3.
- ``status`` is the lifecycle: pending → running → done|failed|cancelled.
  No automatic transitions in M0 — explicit PATCH only. P3 will hook
  TeamRunner callbacks to drive these.
- ``produced_artifacts`` placeholder for future runner output (final
  text, file paths, etc.) — empty in M0.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import re
import threading
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from runtime.platform.process.paths import app_paths
from runtime.safety.approval.cancellation import CancellationSource, scoped_cancellation
from runtime.safety.organization import (
    AgentSpec,
    CoordinationProtocol,
    Role,
    TeamTopology,
)

_LOG = logging.getLogger("octopus.team_tasks")

TeamEventBroadcaster = Callable[[str, dict[str, Any]], Awaitable[None] | None]
RunnerFactory = Callable[..., Any]
RoomMembershipResolver = Callable[[str], list[str]]

# Bounds resource exhaustion via /run. Each running task spawns a
# daemon thread with a 15-min timeout; without this cap a single
# authenticated user could fan out unbounded threads.
_MAX_CONCURRENT_RUNS = 16

# sop_template flows into a filesystem lookup (load_meta_skill →
# meta_skills_dir / f"{name}.yaml"). Restrict to a flat slug to
# defend against path traversal in depth, even though the dir
# helper is itself confined.
_SOP_TEMPLATE_PATTERN = re.compile(r"^[a-zA-Z0-9_.-]+$")

try:
    from fastapi import APIRouter, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]


# ── Wire models ─────────────────────────────────────────────────────


class TaskAssigneeWire(BaseModel):
    """Who the task is assigned to. Polymorphic so a task can target
    AI roster members AND human participants in the same field."""

    model_config = ConfigDict(extra="ignore")

    kind: str  # "agent" | "participant"
    ref: str  # agent name (for kind=agent) or participant id (for kind=participant)


class TeamTaskWire(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    room_id: str
    title: str
    description: str = ""
    sop_template: str = ""  # empty = freeform; otherwise meta-skill name
    status: str = "pending"  # pending | running | done | failed | cancelled
    assignees: list[TaskAssigneeWire] = Field(default_factory=list)
    created_by: str | None = None  # actor / participant id
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None
    produced_artifacts: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreateTeamTaskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    room_id: str
    title: str
    description: str = ""
    sop_template: str = ""
    assignees: list[TaskAssigneeWire] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateTeamTaskRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    description: str | None = None
    status: str | None = None
    assignees: list[TaskAssigneeWire] | None = None
    sop_template: str | None = None


# ── Router factory ──────────────────────────────────────────────────


def create_team_tasks_router(
    *,
    state_path: Path | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    reset_callback: Any = None,
    team_event_broadcaster: TeamEventBroadcaster | None = None,
    runner_factory: RunnerFactory | None = None,
    room_membership_resolver: RoomMembershipResolver | None = None,
    max_concurrent_runs: int = _MAX_CONCURRENT_RUNS,
) -> Any:
    """Create ``/api/team-tasks/*`` routes.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ team_tasks_router.py · navigation map (1074 lines).                ║
    ║                                                                    ║
    ║   §1 Pydantic wires + state schemas              ~L1-138           ║
    ║   §2 create_team_tasks_router(...) factory       ~L139             ║
    ║       §2.1 _auth + _resolve_room_member helpers  ~L160-400         ║
    ║       §2.2 GET /api/team-tasks (list)             ~L410             ║
    ║       §2.3 POST /api/team-tasks (create)          ~L427             ║
    ║       §2.4 GET /api/team-tasks/{id}               ~L463             ║
    ║       §2.5 POST /api/team-tasks/{id}/run          ~L475             ║
    ║       §2.6 PATCH /api/team-tasks/{id}             ~L542             ║
    ║       §2.7 DELETE /api/team-tasks/{id}            ~L590             ║
    ║   §3 background runner + event broadcasting     ~L600-end          ║
    ╚════════════════════════════════════════════════════════════════════╝

    Mirrors the signature of ``create_team_rooms_router`` so the host
    app can wire both with the same identity / auth knobs.

    ``room_membership_resolver`` returns the list of actor ids allowed
    to act on a given room. When ``require_auth`` is true and the
    resolver is provided, every per-task endpoint enforces membership.
    When ``require_auth`` is false (single-user dev mode) the check is
    skipped — matching the existing _auth() bypass behavior.
    """
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["team-tasks"])
    path = state_path or (app_paths().data_dir / "team_tasks.json")
    lock = Lock()
    tasks: dict[str, TeamTaskWire] = _load_state(path)
    running: dict[str, CancellationSource] = {}

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

    def _require_member(actor: str | None, room_id: str) -> None:
        """Reject requests where the authenticated actor is not a
        member of ``room_id``. No-op when auth is disabled or no
        resolver is wired (legacy / single-user mode).
        """
        if not require_auth or room_membership_resolver is None:
            return
        if not actor:
            raise HTTPException(401, "authentication required")
        try:
            members = room_membership_resolver(room_id) or []
        except (KeyError, ValueError, RuntimeError):
            members = []
        if actor not in members:
            raise HTTPException(403, "actor is not a member of this room")

    def _validate_sop_template(value: str) -> str:
        """Normalize and reject sop_template values that could escape
        the meta_skills directory. Empty string means freeform task."""
        normalized = (value or "").strip()
        if not normalized:
            return ""
        if not _SOP_TEMPLATE_PATTERN.fullmatch(normalized):
            raise HTTPException(
                400,
                "sop_template must match [a-zA-Z0-9_.-]+ "
                "(no slashes, no traversal)",
            )
        return normalized

    def _save() -> None:
        _save_state(path, tasks)

    async def _broadcast_task_event(room_id: str, payload: dict[str, Any]) -> None:
        if team_event_broadcaster is None:
            return
        result = team_event_broadcaster(room_id, payload)
        if result is not None:
            await result

    def _broadcast_from_worker(
        loop: asyncio.AbstractEventLoop | None,
        room_id: str,
        payload: dict[str, Any],
    ) -> None:
        if team_event_broadcaster is None:
            return
        try:
            if loop is not None and loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    _broadcast_task_event(room_id, payload),
                    loop,
                ).result(timeout=5.0)
            else:
                asyncio.run(_broadcast_task_event(room_id, payload))
        except (RuntimeError, TimeoutError, OSError):
            _LOG.debug("team task broadcast failed", exc_info=True)

    def _task_payload(
        task: TeamTaskWire,
        *,
        event: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "task:progress",
            "team_id": task.room_id,
            "room_id": task.room_id,
            "task_id": task.id,
            "task": task.model_dump(),
            "event": event,
            "server_time": _now(),
            **(extra or {}),
        }

    def _persist_task(
        task_id: str,
        updates: dict[str, Any],
    ) -> TeamTaskWire | None:
        with lock:
            current = tasks.get(task_id)
            if current is None:
                return None
            updated = current.model_copy(update={"updated_at": _now(), **updates})
            tasks[task_id] = updated
            _save()
            return updated

    def _runner_instance(event_emitter: Callable[[dict[str, Any]], None]) -> Any:
        if runner_factory is None:
            from runtime.safety.organization.team_runner import TeamRunner

            return TeamRunner(timeout_seconds=900, event_emitter=event_emitter)
        try:
            return runner_factory(timeout_seconds=900, event_emitter=event_emitter)
        except TypeError:
            return runner_factory()

    def _run_task_worker(
        task: TeamTaskWire,
        prepared: dict[str, Any],
        source: CancellationSource,
        loop: asyncio.AbstractEventLoop | None,
    ) -> None:
        topology = prepared["topology"]
        completed_roles: set[str] = set()
        total_roles = max(1, len(getattr(topology, "agents", {}) or {}))

        def _current_task() -> TeamTaskWire:
            with lock:
                return tasks.get(task.id) or task

        def _emit_runner_event(event: dict[str, Any]) -> None:
            event_type = str(event.get("type") or "runner_event")
            role = str(event.get("role") or "")
            if event_type == "team_role_end" and role:
                completed_roles.add(role)
            status = str(event.get("status") or "")
            _broadcast_from_worker(
                loop,
                task.room_id,
                _task_payload(
                    _current_task(),
                    event="role_completed"
                    if event_type == "team_role_end"
                    else event_type,
                    extra={
                        "runner_event": event,
                        "role": role or None,
                        "role_status": status or None,
                        "completed_roles": len(completed_roles),
                        "total_roles": total_roles,
                        "progress": min(1.0, len(completed_roles) / total_roles),
                    },
                ),
            )

        result: Any = None
        try:
            # ── Mobile route ────────────────────────────────────
            # If the task is assigned to connected phones (ref
            # ``mobile_*``), dispatch the goal to each device and
            # await its result — the phone runs the device action
            # via octopus-mobile and reports back. A phone is a
            # remote team member, reached over HTTP.
            mobile_members = _mobile_members(task)
            if mobile_members:
                from runtime.execution.agents.mobile_device import get_mobile_registry

                registry = get_mobile_registry()
                records: list[dict[str, Any]] = []
                for device in mobile_members:
                    sub_id = f"{task.id}:{device['agent_id']}"
                    if not registry.dispatch(device["device_id"], sub_id, prepared["task_input"]):
                        records.append(
                            {**device, "ok": False, "output": "", "error": "device not connected"}
                        )
                        continue
                    res = registry.await_result(sub_id, timeout=240.0)
                    if res is None:
                        records.append(
                            {**device, "ok": False, "output": "", "error": "device timed out"}
                        )
                    else:
                        records.append(
                            {
                                **device,
                                "ok": bool(res.get("ok")),
                                "output": res.get("output", ""),
                                "error": res.get("error"),
                            }
                        )
                succeeded = sum(1 for r in records if r.get("ok"))
                final_status = (
                    "cancelled"
                    if source.is_cancelled
                    else ("done" if succeeded else "failed")
                )
                metadata = {
                    **dict(task.metadata),
                    "runner": {
                        "engine": "mobile",
                        "devices": len(records),
                        "succeeded": succeeded,
                    },
                }
                if final_status == "failed":
                    metadata["error"] = "no connected device completed the task"
                updates = {
                    "status": final_status,
                    "completed_at": _now(),
                    "metadata": metadata,
                }
                if final_status == "done":
                    updates["produced_artifacts"] = _mobile_artifacts(records)
                updated = _persist_task(task.id, updates)
                if updated is not None:
                    _broadcast_from_worker(
                        loop,
                        updated.room_id,
                        _task_payload(updated, event=f"run_{final_status}"),
                    )
                return

            # ── CLI-team route ──────────────────────────────────
            # If the task is assigned to local coding-agent CLIs
            # (Claude Code / Codex / …, ref ``local_*``), run them
            # through the diff-first CLI engine — each in its own
            # worktree with the shared blackboard — instead of the
            # role topology. The CLIs use their own subscriptions.
            cli_members = _local_cli_members(task)
            if cli_members:
                import os as _os

                from runtime.execution.agents.cli_team import run_cli_team

                with scoped_cancellation(source.token):
                    cli_result = run_cli_team(
                        prepared["task_input"],
                        cli_members,
                        repo_root=_os.getcwd(),
                        turn_id=task.id,
                    )
                final_status = (
                    "cancelled"
                    if source.is_cancelled
                    else ("done" if cli_result.get("ok") else "failed")
                )
                metadata = {
                    **dict(task.metadata),
                    "runner": {
                        "engine": "cli_team",
                        "members": cli_result.get("count", 0),
                        "succeeded": cli_result.get("succeeded", 0),
                        "note": cli_result.get("note"),
                    },
                }
                if final_status == "failed":
                    metadata["error"] = (
                        cli_result.get("error") or "cli_team reported no successful member"
                    )
                updates = {
                    "status": final_status,
                    "completed_at": _now(),
                    "metadata": metadata,
                }
                if final_status == "done":
                    updates["produced_artifacts"] = _cli_team_artifacts(cli_result)
                updated = _persist_task(task.id, updates)
                if updated is not None:
                    _broadcast_from_worker(
                        loop,
                        updated.room_id,
                        _task_payload(updated, event=f"run_{final_status}"),
                    )
                return
            runner = _runner_instance(_emit_runner_event)
            with scoped_cancellation(source.token):
                result = runner.run(
                    topology,
                    prepared["task_input"],
                    context=prepared["context"],
                )
            final_status = "cancelled" if source.is_cancelled else (
                "done" if _runner_result_success(result) else "failed"
            )
            metadata = {
                **dict(task.metadata),
                "runner": _runner_metadata(result, prepared),
            }
            if final_status == "failed":
                metadata["error"] = (
                    _runner_result_error(result) or "TeamRunner reported failure"
                )
            updates: dict[str, Any] = {
                "status": final_status,
                "completed_at": _now(),
                "metadata": metadata,
            }
            if final_status == "done":
                updates["produced_artifacts"] = _runner_artifacts(result, prepared)
            updated = _persist_task(task.id, updates)
            if updated is not None:
                _broadcast_from_worker(
                    loop,
                    updated.room_id,
                    _task_payload(updated, event=f"run_{final_status}"),
                )
        except Exception as exc:  # noqa: BLE001
            _LOG.exception("team task runner failed for %s", task.id)
            updated = _persist_task(
                task.id,
                {
                    "status": "failed",
                    "completed_at": _now(),
                    "metadata": {
                        **dict(task.metadata),
                        "error": f"{type(exc).__name__}: {exc}",
                        "runner": {
                            "topology": getattr(topology, "name", ""),
                            "meta_skill": prepared.get("meta_skill"),
                        },
                    },
                },
            )
            if updated is not None:
                _broadcast_from_worker(
                    loop,
                    updated.room_id,
                    _task_payload(
                        updated,
                        event="run_failed",
                        extra={"error": f"{type(exc).__name__}: {exc}"},
                    ),
                )
        finally:
            with lock:
                running.pop(task.id, None)
                # Safety net: if the task is still "running" after the
                # worker exits (e.g. BaseException bypassed the except
                # clause), mark it "failed" so it never gets stuck.
                current = tasks.get(task.id)
                if current is not None and current.status == "running":
                    tasks[task.id] = current.model_copy(update={
                        "status": "failed",
                        "completed_at": _now(),
                        "metadata": {
                            **dict(current.metadata),
                            "error": "worker exited without setting terminal status",
                        },
                    })
                    _save()

    def _reset_state() -> None:
        with lock:
            for source in running.values():
                source.cancel(reason="team task router reset")
            running.clear()
            tasks.clear()
        if callable(reset_callback):
            reset_callback()

    async def _create_task_for_actor(
        actor: str | None,
        body: CreateTeamTaskRequest,
    ) -> TeamTaskWire:
        title = body.title.strip()
        if not title:
            raise HTTPException(400, "title is required")
        room_id = body.room_id.strip()
        if not room_id:
            raise HTTPException(400, "room_id is required")
        _require_member(actor, room_id)
        sop_template = _validate_sop_template(body.sop_template)
        now = _now()
        task = TeamTaskWire(
            id=f"task-{uuid4().hex[:12]}",
            room_id=room_id,
            title=title,
            description=body.description.strip(),
            sop_template=sop_template,
            status="pending",
            assignees=list(body.assignees),
            created_by=actor,
            created_at=now,
            updated_at=now,
            metadata=dict(body.metadata),
        )
        with lock:
            tasks[task.id] = task
            _save()
        await _broadcast_task_event(
            task.room_id,
            _task_payload(task, event="task_created"),
        )
        return task

    async def _run_task_for_actor(
        actor: str | None,
        task_id: str,
    ) -> TeamTaskWire:
        with lock:
            current = tasks.get(task_id)
            if current is None:
                raise HTTPException(404, f"task not found: {task_id}")
            if current.status == "running":
                return current
            room_id = current.room_id
        _require_member(actor, room_id)
        try:
            prepared = _prepare_team_run(current)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        now = _now()
        source = CancellationSource()
        metadata = {
            **dict(current.metadata),
            "runner": {
                "status": "running",
                "meta_skill": prepared.get("meta_skill"),
                "topology": prepared["topology"].name,
                "topology_fingerprint": prepared["topology"].fingerprint,
                "task_graph": prepared.get("task_graph"),
            },
        }
        with lock:
            # Concurrency cap checked inside lock — closing TOCTOU window
            # where two requests could both pass the check before either
            # inserts into running{}.
            if len(running) >= max_concurrent_runs:
                raise HTTPException(
                    429,
                    f"too many concurrent runs ({len(running)}/{max_concurrent_runs})",
                )
            latest = tasks.get(task_id)
            if latest is None:
                raise HTTPException(404, f"task not found: {task_id}")
            if latest.status == "running":
                return latest
            updated = latest.model_copy(update={
                "status": "running",
                "started_at": now,
                "completed_at": None,
                "updated_at": now,
                "metadata": metadata,
            })
            tasks[task_id] = updated
            running[task_id] = source
            _save()

        await _broadcast_task_event(
            updated.room_id,
            _task_payload(updated, event="run_started"),
        )
        loop = asyncio.get_running_loop()
        thread = threading.Thread(
            target=_run_task_worker,
            args=(updated, prepared, source, loop),
            name=f"team-task-run-{task_id}",
            daemon=True,
        )
        thread.start()
        return updated

    async def _create_task_from_payload(
        request: Request,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        body = CreateTeamTaskRequest.model_validate(payload)
        return (await _create_task_for_actor(_auth(request), body)).model_dump()

    async def _run_task_from_request(
        request: Request,
        task_id: str,
    ) -> dict[str, Any]:
        return (await _run_task_for_actor(_auth(request), task_id)).model_dump()

    @router.get("/api/team-tasks")
    def list_tasks(request: Request, room_id: str | None = None) -> dict[str, Any]:
        """List tasks. ``room_id`` query param scopes to one room
        (omit to list all — useful for admin/debug, not the typical
        UI flow)."""
        actor = _auth(request)
        with lock:
            items = list(tasks.values())
        if room_id:
            _require_member(actor, room_id)
            items = [t for t in items if t.room_id == room_id]
        items.sort(key=lambda t: t.updated_at, reverse=True)
        return {
            "tasks": [t.model_dump() for t in items],
            "count": len(items),
        }

    @router.post("/api/team-tasks")
    async def create_task(
        request: Request,
        body: CreateTeamTaskRequest,
    ) -> dict[str, Any]:
        task = await _create_task_for_actor(_auth(request), body)
        return task.model_dump()

    @router.get("/api/team-tasks/{task_id}")
    def get_task(request: Request, task_id: str) -> dict[str, Any]:
        actor = _auth(request)
        with lock:
            task = tasks.get(task_id)
            if task is None:
                raise HTTPException(404, f"task not found: {task_id}")
            payload = task.model_dump()
            room_id = task.room_id
        _require_member(actor, room_id)
        return payload

    @router.post("/api/team-tasks/{task_id}/run")
    async def run_task(request: Request, task_id: str) -> dict[str, Any]:
        updated = await _run_task_for_actor(_auth(request), task_id)
        return updated.model_dump()

    @router.patch("/api/team-tasks/{task_id}")
    async def update_task(
        request: Request,
        task_id: str,
        body: UpdateTeamTaskRequest,
    ) -> dict[str, Any]:
        actor = _auth(request)
        with lock:
            current = tasks.get(task_id)
            if current is None:
                raise HTTPException(404, f"task not found: {task_id}")
            _require_member(actor, current.room_id)
            updates: dict[str, Any] = {"updated_at": _now()}
            if body.title is not None:
                title = body.title.strip()
                if not title:
                    raise HTTPException(400, "title cannot be empty")
                updates["title"] = title
            if body.description is not None:
                updates["description"] = body.description.strip()
            if body.sop_template is not None:
                updates["sop_template"] = _validate_sop_template(body.sop_template)
            if body.assignees is not None:
                updates["assignees"] = list(body.assignees)
            if body.status is not None:
                next_status = _normalize_status(body.status)
                updates["status"] = next_status
                # Stamp lifecycle timestamps when crossing the boundary.
                # Re-running a done task is allowed (status → running
                # again resets started_at), but completed_at only sets
                # when a task transitions INTO a terminal state.
                if next_status == "running" and current.status != "running":
                    updates["started_at"] = _now()
                if next_status in {"done", "failed", "cancelled"}:
                    updates["completed_at"] = _now()
                if next_status == "cancelled":
                    source = running.get(task_id)
                    if source is not None:
                        source.cancel(reason="team task cancelled")
            updated = current.model_copy(update=updates)
            tasks[task_id] = updated
            _save()
        await _broadcast_task_event(
            updated.room_id,
            _task_payload(updated, event="task_updated"),
        )
        return updated.model_dump()

    @router.delete("/api/team-tasks/{task_id}")
    async def delete_task(request: Request, task_id: str) -> dict[str, Any]:
        actor = _auth(request)
        with lock:
            existing = tasks.get(task_id)
            if existing is None:
                raise HTTPException(404, f"task not found: {task_id}")
            _require_member(actor, existing.room_id)
            existed = tasks.pop(task_id, None)
            source = running.pop(task_id, None)
            if source is not None:
                source.cancel(reason="team task deleted")
            if existed is not None:
                _save()
        if existed is not None:
            await _broadcast_task_event(
                existed.room_id,
                _task_payload(
                    existed,
                    event="task_deleted",
                    extra={"deleted": True},
                ),
            )
        return {"ok": True, "deleted": existed is not None, "task_id": task_id}

    router.reset_state = _reset_state
    router.create_task_from_payload = _create_task_from_payload
    router.run_task_from_request = _run_task_from_request
    return router


# ── helpers ─────────────────────────────────────────────────────────


_RUNNER_ROLE_ORDER: tuple[Role, ...] = (
    Role.PLANNER,
    Role.RESEARCHER,
    Role.GENERATOR,
    Role.CRITIC,
    Role.SYNTHESIZER,
    Role.EVALUATOR,
)

_DEFAULT_AGENT_BY_ROLE: dict[Role, str] = {
    Role.PLANNER: "planner",
    Role.RESEARCHER: "researcher",
    Role.GENERATOR: "implementer",
    Role.CRITIC: "reviewer",
    Role.SYNTHESIZER: "synthesizer",
    Role.EVALUATOR: "evaluator",
}

_ROLE_KEYWORDS: dict[Role, tuple[str, ...]] = {
    Role.PLANNER: (
        "plan",
        "planner",
        "scope",
        "outline",
        "decompose",
        "breakdown",
        "requirements",
        "ask_user",
        "question",
        "clarify",
        "roadmap",
    ),
    Role.RESEARCHER: (
        "research",
        "search",
        "fetch",
        "source",
        "market",
        "data",
        "news",
        "trend",
        "competitor",
        "collect",
        "investigate",
        "crawl",
        "web",
    ),
    Role.CRITIC: (
        "critic",
        "review",
        "audit",
        "risk",
        "verify",
        "check",
        "compliance",
        "safety",
        "vulnerability",
        "postmortem",
    ),
    Role.EVALUATOR: (
        "evaluate",
        "evaluator",
        "score",
        "quality",
        "test",
        "benchmark",
        "validator",
        "rank",
        "rubric",
    ),
    Role.SYNTHESIZER: (
        "synth",
        "synthesize",
        "summarize",
        "report",
        "brief",
        "memo",
        "final",
        "deliver",
        "write",
        "compose",
        "export",
        "publish",
    ),
    Role.GENERATOR: (
        "generate",
        "generator",
        "build",
        "implement",
        "draft",
        "create",
        "code",
        "produce",
        "make",
    ),
}


def _prepare_team_run(task: TeamTaskWire) -> dict[str, Any]:
    from runtime.memory.skills_lib.meta_skill import (
        compile_to_task_graph,
        load_meta_skill,
        match_meta_skill,
    )

    task_input = _task_input_text(task)
    meta = None
    explicit_template = task.sop_template.strip()
    if explicit_template:
        meta = load_meta_skill(explicit_template)
        if meta is None:
            raise ValueError(f"meta-skill not found: {explicit_template}")
    else:
        meta = match_meta_skill(task_input)

    task_graph: dict[str, Any] | None = None
    if meta is not None:
        graph = compile_to_task_graph(meta, user_input=_task_user_input(task))
        task_graph = _task_graph_summary(graph)
        topology = _topology_from_task_graph(task, meta, graph)
    else:
        topology = _fallback_topology(task)

    context = {
        "room_id": task.room_id,
        "team_id": task.room_id,
        "team_task_id": task.id,
        "team_task": task.model_dump(),
        "meta_skill": getattr(meta, "name", None),
        "task_graph": task_graph,
    }
    return {
        "task_input": task_input,
        "context": context,
        "meta_skill": getattr(meta, "name", None),
        "task_graph": task_graph,
        "topology": topology,
    }


def _task_input_text(task: TeamTaskWire) -> str:
    lines = [task.title.strip()]
    if task.description.strip():
        lines.extend(["", task.description.strip()])
    if task.sop_template.strip():
        lines.extend(["", f"SOP template: {task.sop_template.strip()}"])
    output_contract = _task_output_contract_text(task)
    if output_contract:
        lines.extend(["", output_contract])
    return "\n".join(lines).strip()


def _task_output_contract_text(task: TeamTaskWire) -> str | None:
    contract = task.metadata.get("output_contract")
    if not isinstance(contract, dict):
        return None
    name = str(contract.get("name") or "output_contract").strip()
    lines = [f"Output contract: {name}"]
    instructions = contract.get("instructions")
    if isinstance(instructions, list):
        for instruction in instructions:
            text = str(instruction or "").strip()
            if text:
                lines.append(f"- {text}")
    schema = contract.get("schema")
    if isinstance(schema, dict) and schema:
        lines.extend([
            "- JSON schema shape:",
            json.dumps(schema, ensure_ascii=False, indent=2),
        ])
    return "\n".join(lines)


def _task_user_input(task: TeamTaskWire) -> dict[str, Any]:
    text = _task_input_text(task)
    return {
        "task": text,
        "title": task.title,
        "description": task.description,
        "topic": task.title,
        "target": task.title,
        "goal": task.title,
        "purpose": task.description or task.title,
        "seed": text,
        "room_id": task.room_id,
        "task_id": task.id,
        "assignees": [a.model_dump() for a in task.assignees],
    }


def _topology_from_task_graph(
    task: TeamTaskWire,
    meta: Any,
    graph: Any,
) -> TeamTopology:
    node_roles: list[dict[str, str]] = []
    roles: list[Role] = []
    for node in getattr(graph, "nodes", []) or []:
        role = _role_for_graph_node(node)
        node_roles.append({
            "node_id": str(getattr(node, "node_id", "")),
            "skill_ref": str(getattr(node, "skill_ref", "") or ""),
            "role": str(role),
        })
        if role not in roles:
            roles.append(role)

    if not any(role in roles for role in (Role.PLANNER, Role.GENERATOR)):
        roles.insert(0, Role.PLANNER)
    if not any(role in roles for role in (
        Role.SYNTHESIZER,
        Role.GENERATOR,
        Role.EVALUATOR,
    )):
        roles.append(Role.SYNTHESIZER)

    roles = _ordered_unique_roles(roles)
    topology_name = _slugify(
        f"task-{getattr(meta, 'name', None) or task.title}",
        fallback=f"team-task-{task.id}",
    )
    return TeamTopology(
        name=topology_name,
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents=_agents_for_roles(task, roles),
        task_bucket=str(getattr(graph, "task_type", "") or "team-task"),
        metadata={
            "source": "team_tasks_router",
            "team_task_id": task.id,
            "room_id": task.room_id,
            "meta_skill": getattr(meta, "name", None),
            "node_role_projection": node_roles,
        },
    )


def _fallback_topology(task: TeamTaskWire) -> TeamTopology:
    roles = [Role.PLANNER, Role.SYNTHESIZER]
    return TeamTopology(
        name=_slugify(f"task-{task.title}", fallback=f"team-task-{task.id}"),
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents=_agents_for_roles(task, roles),
        task_bucket="team-task:freeform",
        metadata={
            "source": "team_tasks_router",
            "team_task_id": task.id,
            "room_id": task.room_id,
            "meta_skill": None,
            "fallback": True,
        },
    )


def _role_for_graph_node(node: Any) -> Role:
    haystack = " ".join(
        str(part or "").lower()
        for part in (
            getattr(node, "node_id", ""),
            getattr(node, "skill_ref", ""),
            getattr(node, "kind", ""),
        )
    )
    for role in (
        Role.PLANNER,
        Role.RESEARCHER,
        Role.CRITIC,
        Role.EVALUATOR,
        Role.SYNTHESIZER,
        Role.GENERATOR,
    ):
        if any(keyword in haystack for keyword in _ROLE_KEYWORDS[role]):
            return role
    if str(getattr(node, "kind", "") or "") == "validator":
        return Role.EVALUATOR
    if str(getattr(node, "kind", "") or "") == "merger":
        return Role.SYNTHESIZER
    return Role.GENERATOR


def _ordered_unique_roles(roles: list[Role]) -> list[Role]:
    role_set = set(roles)
    return [role for role in _RUNNER_ROLE_ORDER if role in role_set]


def _agents_for_roles(
    task: TeamTaskWire,
    roles: list[Role],
) -> dict[Role, AgentSpec]:
    agent_refs = [
        assignee.ref.strip()
        for assignee in task.assignees
        if assignee.kind.strip().lower() == "agent" and assignee.ref.strip()
    ]
    role_specific_refs: dict[Role, str] = {}
    generic_refs: list[str] = []
    for ref in agent_refs:
        matched_role = _role_for_agent_ref(ref)
        if matched_role is None:
            generic_refs.append(ref)
        else:
            role_specific_refs[matched_role] = ref
    out: dict[Role, AgentSpec] = {}
    for index, role in enumerate(roles):
        if role in role_specific_refs:
            agent_id = role_specific_refs[role]
        elif generic_refs:
            agent_id = generic_refs[index % len(generic_refs)]
        else:
            agent_id = _DEFAULT_AGENT_BY_ROLE[role]
        out[role] = AgentSpec(
            agent_id=agent_id,
            system_addendum=_system_addendum_for_role(task, role),
        )
    return out


def _role_for_agent_ref(ref: str) -> Role | None:
    normalized = ref.strip().lower()
    for role, default_agent_id in _DEFAULT_AGENT_BY_ROLE.items():
        if normalized in {str(role).lower(), default_agent_id.lower()}:
            return role
    return None


def _system_addendum_for_role(task: TeamTaskWire, role: Role) -> str | None:
    if role != Role.SYNTHESIZER:
        return None
    contract = task.metadata.get("output_contract")
    if not isinstance(contract, dict):
        return None
    name = str(contract.get("name") or "output_contract").strip()
    schema = contract.get("schema")
    schema_text = (
        json.dumps(schema, ensure_ascii=False, indent=2)
        if isinstance(schema, dict) and schema
        else "{}"
    )
    return "\n".join([
        f"You are the final synthesizer for output contract `{name}`.",
        "Return a useful concise summary, then include exactly one fenced json block.",
        "The fenced json block must be parseable JSON and must match this shape:",
        schema_text,
        "Use empty arrays when there is no concrete supported item.",
        "Do not stop at a plan; convert concrete role outputs into the JSON fields.",
    ])


def _slugify(value: str, *, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-_")
    return (slug or fallback)[:80]


def _task_graph_summary(graph: Any) -> dict[str, Any]:
    nodes = []
    for node in getattr(graph, "nodes", []) or []:
        nodes.append({
            "node_id": str(getattr(node, "node_id", "")),
            "kind": str(getattr(node, "kind", "") or ""),
            "skill_ref": str(getattr(node, "skill_ref", "") or ""),
            "timeout_ms": getattr(node, "timeout_ms", None),
            "failure_retry": getattr(node, "failure_retry", None),
        })
    edges = []
    for edge in getattr(graph, "edges", []) or []:
        edges.append({
            "from_node": str(getattr(edge, "from_node", "")),
            "to_node": str(getattr(edge, "to_node", "")),
            "kind": str(getattr(edge, "kind", "") or ""),
            "condition": getattr(edge, "condition", None),
        })
    return {
        "task_type": str(getattr(graph, "task_type", "") or ""),
        "strategy": str(getattr(graph, "strategy", "") or ""),
        "nodes": nodes,
        "edges": edges,
        "budget": _jsonable(getattr(graph, "budget", None)),
    }


def _runner_result_success(result: Any) -> bool:
    return bool(_result_value(result, "success", False))


def _runner_result_error(result: Any) -> str | None:
    error = _result_value(result, "error", None)
    if error is None:
        return None
    text = str(error).strip()
    return text or None


def _runner_metadata(result: Any, prepared: dict[str, Any]) -> dict[str, Any]:
    topology = prepared["topology"]
    return {
        "status": "done" if _runner_result_success(result) else "failed",
        "meta_skill": prepared.get("meta_skill"),
        "task_graph": prepared.get("task_graph"),
        "topology": topology.to_dict(),
        "topology_name": _result_value(result, "topology_name", topology.name),
        "topology_fingerprint": _result_value(
            result,
            "topology_fingerprint",
            topology.fingerprint,
        ),
        "task_bucket": _result_value(result, "task_bucket", topology.task_bucket),
        "iterations": _result_value(result, "iterations", None),
        "total_duration_ms": _result_value(result, "total_duration_ms", None),
        "quality_score": _result_value(result, "quality_score", None),
        "error": _runner_result_error(result),
        "role_outputs": _jsonable(_result_value(result, "role_outputs", [])),
    }


def _mobile_members(task: TeamTaskWire) -> list[dict[str, Any]]:
    """The connected phones assigned to this task — the ``mobile_*`` agent
    assignees that the device registry confirms are registered. Empty → the
    task takes the normal (CLI / role-topology) path."""
    from runtime.execution.agents.mobile_device import mobile_members_from_assignees

    refs = [
        a.ref.strip()
        for a in task.assignees
        if a.kind.strip().lower() == "agent" and a.ref.strip().startswith("mobile_")
    ]
    return mobile_members_from_assignees(refs)


def _mobile_artifacts(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One artifact per phone carrying its run output, so the team room can
    review what each device did."""
    artifacts: list[dict[str, Any]] = []
    for rec in records or []:
        agent_id = str(rec.get("agent_id") or "mobile")
        artifacts.append(
            {
                "id": f"artifact-{uuid4().hex[:12]}",
                "type": "mobile_run",
                "title": f"{rec.get('name') or agent_id} · {'完成' if rec.get('ok') else '未完成'}",
                "content": str(rec.get("output") or rec.get("error") or ""),
                "agent_id": agent_id,
                "device_id": str(rec.get("device_id") or ""),
                "ok": bool(rec.get("ok")),
                "error": rec.get("error"),
                "created_at": _now(),
            }
        )
    return artifacts


def _local_cli_members(task: TeamTaskWire) -> list[dict[str, str]]:
    """The locally-installed coding-agent CLIs assigned to this task — the
    ``local_*`` agent assignees that :func:`select_cli_members` confirms are
    runnable here. Empty → the task takes the normal role-topology path."""
    from runtime.execution.agents.cli_team import select_cli_members

    refs = [
        a.ref.strip()
        for a in task.assignees
        if a.kind.strip().lower() == "agent" and a.ref.strip().startswith("local_")
    ]
    return select_cli_members(refs)


def _cli_team_artifacts(cli_result: dict[str, Any]) -> list[dict[str, Any]]:
    """One artifact per CLI member carrying its diff + output, so the team room
    can review each candidate. Diffs are NOT merged (diff-first by design)."""
    artifacts: list[dict[str, Any]] = []
    for member in cli_result.get("members", []) or []:
        if not isinstance(member, dict):
            continue
        agent_id = str(member.get("agent_id") or "agent")
        artifacts.append(
            {
                "id": f"artifact-{uuid4().hex[:12]}",
                "type": "cli_team_diff",
                "title": f"{agent_id} · {'diff' if member.get('diff') else 'no changes'}",
                "content": str(member.get("diff") or member.get("output") or ""),
                "agent_id": agent_id,
                "partner_id": str(member.get("partner_id") or ""),
                "ok": bool(member.get("ok")),
                "files": _jsonable(member.get("files", [])),
                "error": member.get("error"),
                "created_at": _now(),
            }
        )
    return artifacts


def _runner_artifacts(result: Any, prepared: dict[str, Any]) -> list[dict[str, Any]]:
    final_output = str(_result_value(result, "final_output", "") or "")
    if not final_output.strip():
        return []
    topology = prepared["topology"]
    return [{
        "id": f"artifact-{uuid4().hex[:12]}",
        "type": "team_runner_output",
        "title": "TeamRunner final output",
        "content": final_output,
        "meta_skill": prepared.get("meta_skill"),
        "topology": topology.name,
        "topology_fingerprint": topology.fingerprint,
        "role_outputs": _jsonable(_result_value(result, "role_outputs", [])),
        "created_at": _now(),
    }]


def _result_value(result: Any, key: str, default: Any = None) -> Any:
    if isinstance(result, dict):
        return result.get(key, default)
    try:
        return getattr(result, key)
    except Exception:  # noqa: BLE001
        return default


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (Role, CoordinationProtocol)):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except TypeError:
            return _jsonable(value.model_dump())
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    return str(value)


def _now() -> str:
    return datetime.now(UTC).isoformat()


_VALID_STATUSES = {"pending", "running", "done", "failed", "cancelled"}


def _normalize_status(status: str | None) -> str:
    normalized = (status or "pending").strip().lower()
    if normalized not in _VALID_STATUSES:
        raise HTTPException(
            400,
            f"invalid status {status!r}; expected one of {sorted(_VALID_STATUSES)}",
        )
    return normalized


def _load_state(path: Path) -> dict[str, TeamTaskWire]:
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _LOG.warning("failed to load team tasks from %s: %s", path, exc)
        return {}
    items = raw.get("tasks") if isinstance(raw, dict) else raw
    if not isinstance(items, list):
        return {}
    out: dict[str, TeamTaskWire] = {}
    for item in items:
        if not isinstance(item, dict):
            _LOG.warning("skipping non-dict task entry: %s", type(item).__name__)
            continue
        try:
            task = TeamTaskWire.model_validate(item)
        except (ValueError, TypeError) as exc:
            _LOG.warning("skipping invalid task entry (id=%s): %s", item.get("id"), exc)
            continue
        out[task.id] = task
    return out


def _save_state(path: Path, tasks: dict[str, TeamTaskWire]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "tasks": [t.model_dump() for t in tasks.values()],
        "updated_at": _now(),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    tmp.replace(path)


__all__ = ["create_team_tasks_router"]
