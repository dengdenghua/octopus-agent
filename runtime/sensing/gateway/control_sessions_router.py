"""Unified control-session API."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from runtime.memory.control_sessions import ControlSessionStore

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


class ControlSessionBody(BaseModel):
    session_id: str | None = None
    owner_id: str = "agent"
    owner_label: str = "Agent"
    surface: str = "browser"
    target_id: str = "default"
    status: str = "idle"
    metadata: dict[str, Any] = Field(default_factory=dict)
    ttl_seconds: float | None = None
    takeover: bool = False


class ControlSessionStateBody(BaseModel):
    reason: str = ""
    owner_id: str | None = None
    owner_label: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ControlActionBody(BaseModel):
    action_id: str | None = None
    action_type: str = "action"
    descriptor: dict[str, Any] = Field(default_factory=dict)
    status: str = "queued"
    surface: str | None = None
    target_id: str | None = None
    ttl_seconds: float | None = None


class ControlActionUpdateBody(BaseModel):
    status: str
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""


class ControlEvidenceBody(BaseModel):
    evidence_id: str | None = None
    action_id: str = ""
    kind: str = "log"
    action: str = ""
    ok: bool | None = None
    summary: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: float | None = None


def create_control_sessions_router(
    *,
    store: ControlSessionStore | None = None,
    base_dir: Path | str | None = None,
) -> APIRouter:
    session_store = store or ControlSessionStore(base_dir=base_dir)
    router = APIRouter(prefix="/api/control-sessions", tags=["control-sessions"])

    def _bad_request(exc: ValueError) -> HTTPException:
        return HTTPException(400, str(exc))

    @router.get("")
    def list_sessions(
        surface: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        try:
            sessions = session_store.list_sessions(surface=surface, limit=limit)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"sessions": sessions, "count": len(sessions)}

    @router.post("")
    def create_or_takeover_session(body: ControlSessionBody) -> dict[str, Any]:
        try:
            session = session_store.upsert_session(
                session_id=body.session_id,
                owner_id=body.owner_id,
                owner_label=body.owner_label,
                surface=body.surface,
                target_id=body.target_id,
                status=body.status,
                metadata=body.metadata,
                ttl_seconds=body.ttl_seconds,
                takeover=body.takeover,
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"ok": True, "session": session}

    @router.get("/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        try:
            session = session_store.get_session(session_id)
        except ValueError as exc:
            raise _bad_request(exc) from exc
        if session is None:
            raise HTTPException(404, "control session not found")
        return {"session": session}

    @router.post("/{session_id}/actions")
    def append_action(session_id: str, body: ControlActionBody) -> dict[str, Any]:
        try:
            action = session_store.append_action(
                session_id,
                action_id=body.action_id,
                action_type=body.action_type,
                descriptor=body.descriptor,
                status=body.status,
                surface=body.surface,
                target_id=body.target_id,
                ttl_seconds=body.ttl_seconds,
            )
        except KeyError as exc:
            raise HTTPException(404, "control session not found") from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"ok": True, "action": action}

    @router.patch("/{session_id}/actions/{action_id}")
    def update_action(
        session_id: str,
        action_id: str,
        body: ControlActionUpdateBody,
    ) -> dict[str, Any]:
        try:
            action = session_store.update_action(
                session_id,
                action_id,
                status=body.status,
                result=body.result,
                error=body.error,
            )
        except KeyError as exc:
            raise HTTPException(404, "control action not found") from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"ok": True, "action": action}

    @router.post("/{session_id}/evidence")
    def append_evidence(session_id: str, body: ControlEvidenceBody) -> dict[str, Any]:
        try:
            evidence = session_store.append_evidence(
                session_id,
                evidence_id=body.evidence_id,
                action_id=body.action_id,
                kind=body.kind,
                action=body.action,
                ok=body.ok,
                summary=body.summary,
                detail=body.detail,
                created_at=body.created_at,
            )
        except KeyError as exc:
            raise HTTPException(404, "control session not found") from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"ok": True, "evidence": evidence}

    @router.get("/{session_id}/evidence/{evidence_id}/detail")
    def evidence_detail(session_id: str, evidence_id: str) -> dict[str, Any]:
        try:
            return session_store.evidence_detail(session_id, evidence_id)
        except KeyError as exc:
            raise HTTPException(404, "control evidence not found") from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc

    def _set_state(
        session_id: str,
        *,
        status: str,
        body: ControlSessionStateBody,
        takeover: bool = False,
    ) -> dict[str, Any]:
        try:
            session = session_store.set_session_state(
                session_id,
                status=status,
                reason=body.reason,
                owner_id=body.owner_id,
                owner_label=body.owner_label,
                metadata=body.metadata,
                takeover=takeover,
            )
        except KeyError as exc:
            raise HTTPException(404, "control session not found") from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"ok": True, "session": session}

    @router.post("/{session_id}/pause")
    def pause_session(
        session_id: str, body: ControlSessionStateBody | None = None
    ) -> dict[str, Any]:
        return _set_state(session_id, status="paused", body=body or ControlSessionStateBody())

    @router.post("/{session_id}/resume")
    def resume_session(
        session_id: str, body: ControlSessionStateBody | None = None
    ) -> dict[str, Any]:
        return _set_state(session_id, status="idle", body=body or ControlSessionStateBody())

    @router.post("/{session_id}/stop")
    def stop_session(
        session_id: str, body: ControlSessionStateBody | None = None
    ) -> dict[str, Any]:
        return _set_state(session_id, status="stopped", body=body or ControlSessionStateBody())

    @router.post("/{session_id}/takeover")
    def takeover_session(
        session_id: str,
        body: ControlSessionStateBody | None = None,
    ) -> dict[str, Any]:
        return _set_state(
            session_id,
            status="paused",
            body=body or ControlSessionStateBody(reason="user takeover"),
            takeover=True,
        )

    @router.get("/{session_id}/replay")
    def replay_session(
        session_id: str,
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> dict[str, Any]:
        try:
            return session_store.replay(session_id, limit=limit)
        except KeyError as exc:
            raise HTTPException(404, "control session not found") from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.get("/{session_id}/timeline")
    def replay_timeline(
        session_id: str,
        limit: int = Query(default=500, ge=1, le=5000),
        after: float = Query(default=0.0, ge=0.0),
        after_cursor: str = "",
    ) -> dict[str, Any]:
        try:
            return session_store.timeline(
                session_id,
                limit=limit,
                after=after,
                after_cursor=after_cursor,
            )
        except KeyError as exc:
            raise HTTPException(404, "control session not found") from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc

    @router.get("/{session_id}/events")
    def session_events(
        session_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        async def _gen():
            last = after
            try:
                if session_store.get_session(session_id) is None:
                    yield 'event: error\ndata: {"error":"control session not found"}\n\n'
                    return
            except ValueError as exc:
                yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"
                return
            for _ in range(120):
                if await request.is_disconnected():
                    break
                events = session_store.events_after(session_id, after=last, limit=100)
                for event in events:
                    last = int(event["seq"])
                    yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if not events:
                    yield f"event: heartbeat\ndata: {json.dumps({'after': last})}\n\n"
                await asyncio.sleep(1.0)

        return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)

    return router


__all__ = [
    "create_control_sessions_router",
]
