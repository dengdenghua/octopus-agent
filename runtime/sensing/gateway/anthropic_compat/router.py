"""Anthropic Managed Agents REST + SSE router.

Exposes the ``/v1/sessions`` surface so the official ``anthropic``
Python/TS SDK (``client.beta.sessions.*``) can connect to
octopus-agent as a self-hosted backend.

Required beta header: ``anthropic-beta: managed-agents-2026-04-01``
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import StreamingResponse

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = object  # type: ignore[assignment, misc]
    StreamingResponse = None  # type: ignore[assignment, misc]

from .event_adapter import turn_completed_event, turn_started_event
from .models import (
    CreateSessionRequest,
    SendEventsRequest,
    SessionStatus,
)
from .session_manager import SessionManager

_logger = logging.getLogger(__name__)

_BETA_HEADER = "managed-agents-2026-04-01"


def create_anthropic_compat_router(
    *,
    stack: Any,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    agent_registry: Any = None,
) -> Any:
    """Build the ``/v1/sessions`` FastAPI router."""
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi required for anthropic compat layer")

    router = APIRouter(tags=["anthropic-compat"])
    manager = SessionManager()

    # ── Auth helper ──────────────────────────────────────────

    def _auth(request: Request) -> str | None:
        # Verify beta header presence.
        beta = request.headers.get("anthropic-beta") or ""
        if _BETA_HEADER not in beta:
            raise HTTPException(
                400,
                f"missing required header: anthropic-beta: {_BETA_HEADER}",
            )
        try:
            from runtime.sensing.gateway.openai_gateway import _resolve_actor

            return _resolve_actor(
                request, identity_store, require_auth,
                jwt_secret=jwt_secret,
                jwt_issuer=jwt_issuer,
                jwt_audience=jwt_audience,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            if require_auth:
                raise HTTPException(401, "auth required") from exc
            return None

    # ── POST /v1/sessions ────────────────────────────────────

    @router.post("/v1/sessions")
    async def create_session(request: Request) -> dict[str, Any]:
        actor = _auth(request)
        try:
            body = CreateSessionRequest.model_validate(await request.json())
        except Exception as exc:
            raise HTTPException(400, f"invalid body: {exc}") from exc
        agent_id = body.agent if isinstance(body.agent, str) else (
            body.agent.get("id") if isinstance(body.agent, dict) else None
        )
        state = await manager.create(
            agent_id=agent_id,
            title=body.title,
            actor=actor,
        )
        return manager.to_response(state).model_dump(mode="json")

    # ── GET /v1/sessions/{id} ────────────────────────────────

    @router.get("/v1/sessions/{session_id}")
    async def get_session(session_id: str, request: Request) -> dict[str, Any]:
        _auth(request)
        state = await manager.get(session_id)
        if state is None:
            raise HTTPException(404, "session not found")
        return manager.to_response(state).model_dump(mode="json")

    # ── GET /v1/sessions ─────────────────────────────────────

    @router.get("/v1/sessions")
    async def list_sessions(request: Request) -> list[dict[str, Any]]:
        actor = _auth(request)
        states = await manager.list_sessions(actor=actor)
        return [manager.to_response(s).model_dump(mode="json") for s in states[:50]]

    # ── POST /v1/sessions/{id}/events ────────────────────────

    @router.post("/v1/sessions/{session_id}/events")
    async def send_events(session_id: str, request: Request) -> dict[str, Any]:
        actor = _auth(request)
        state = await manager.get(session_id)
        if state is None:
            raise HTTPException(404, "session not found")
        try:
            body = SendEventsRequest.model_validate(await request.json())
        except Exception as exc:
            raise HTTPException(400, f"invalid body: {exc}") from exc

        for raw_event in body.events:
            event_type = raw_event.get("type", "")
            if event_type == "user.message":
                # Extract text from content blocks.
                content_blocks = raw_event.get("content") or []
                text_parts = [
                    b.get("text", "")
                    for b in content_blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                text = "\n".join(t for t in text_parts if t)
                if not text:
                    continue
                # Fire a turn via CerebrumRuntime.
                asyncio.create_task(
                    _run_turn(session_id, state, text, actor),
                )
            elif event_type == "user.interrupt":
                # TODO: wire to turn interrupt
                pass
            elif event_type == "user.tool_confirmation":
                # TODO: wire to approval resolution
                pass
            elif event_type == "user.custom_tool_result":
                # TODO: wire to custom tool result
                pass
            else:
                _logger.debug("anthropic compat: unknown event type %s", event_type)

        return {"ok": True}

    # ── GET /v1/sessions/{id}/events/stream ──────────────────

    @router.get("/v1/sessions/{session_id}/events/stream")
    async def stream_events(session_id: str, request: Request) -> Any:
        _auth(request)
        state = await manager.get(session_id)
        if state is None:
            raise HTTPException(404, "session not found")
        queue = await manager.subscribe(session_id)
        if queue is None:
            raise HTTPException(404, "session not found")

        async def _sse_generator():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30.0)
                    except TimeoutError:
                        # Keepalive comment.
                        yield ": keepalive\n\n"
                        continue
                    if event is None:
                        break
                    payload = event.model_dump(mode="json")
                    yield f"data: {json.dumps(payload)}\n\n"
            finally:
                await manager.unsubscribe(session_id, queue)

        return StreamingResponse(
            _sse_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    # ── GET /v1/sessions/{id}/events ─────────────────────────

    @router.get("/v1/sessions/{session_id}/events")
    async def list_events(session_id: str, request: Request) -> list[dict[str, Any]]:
        _auth(request)
        state = await manager.get(session_id)
        if state is None:
            raise HTTPException(404, "session not found")
        return [e.model_dump(mode="json") for e in state.history[-200:]]

    # ── Internal: run a turn ─────────────────────────────────

    async def _run_turn(
        session_id: str,
        state: Any,
        text: str,
        actor: str | None,
    ) -> None:
        """Drive a ReAct turn and publish events to SSE subscribers."""
        await manager.set_status(session_id, SessionStatus.RUNNING)
        await manager.publish(session_id, turn_started_event())

        try:
            from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime

            runtime: CerebrumRuntime | None = getattr(stack, "_realtime_runtime", None)
            if runtime is None:
                # Fallback: build a minimal CerebrumRuntime from the stack.
                runtime = CerebrumRuntime(stack=stack)

            # Build TurnParams-compatible dict.
            params = {
                "threadId": state.thread_id,
                "input": [{"type": "text", "text": text, "metadata": {}}],
                "approvalPolicy": "on-request",
            }
            if state.agent_id:
                params["input"][0]["metadata"] = {"agent_id": state.agent_id}

            # Create a lightweight emitter that adapts events and publishes.
            class _SseEmitter:
                async def notify(self, method, params_dict):
                    # Map realtime protocol events to Anthropic events.
                    # The realtime cerebrum emits item/* events; we need
                    # to intercept at a lower level. For MVP, we drive
                    # the turn via start_turn and capture the Turn result.
                    pass

                async def request_approval(self, method, params_dict, *, timeout=None):
                    # For MVP, auto-approve (the approval flow needs
                    # the full bidirectional channel which SSE doesn't
                    # natively support — the client must POST back a
                    # user.tool_confirmation event).
                    return {"action": "accept"}

                def is_turn_interrupted(self, turn_id):
                    return False

                def register_turn(self, turn_id):
                    pass

                def unregister_turn(self, turn_id):
                    pass

            emitter = _SseEmitter()
            await runtime.start_turn(params, emitter)

            # After turn completes, publish completion event.
            await manager.publish(session_id, turn_completed_event())

        except Exception as exc:
            _logger.exception("anthropic compat: turn failed")
            from .models import SessionErrorEvent

            await manager.publish(
                session_id,
                SessionErrorEvent(error={"message": str(exc)}),
            )
        finally:
            await manager.set_status(session_id, SessionStatus.IDLE)

    return router
