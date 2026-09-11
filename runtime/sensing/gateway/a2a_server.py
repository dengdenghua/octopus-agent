"""Official A2A v1 inbound server mounted on the Octopus runtime."""

from __future__ import annotations

import asyncio
import os
import uuid
from pathlib import Path
from typing import Any


def mount_a2a_server(
    app: Any,
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    data_dir: Path | str,
    role_id: str = "general",
    role_name: str | None = None,
    public_prefix: str = "",
) -> Any:
    """Mount official Agent Card, JSON-RPC and REST A2A endpoints.

    The public Agent Card is served at the well-known path. Calls execute in a
    deliberately isolated, read-only subagent context and official Task objects
    persist across process restarts.
    """

    from a2a.auth.user import User
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.context import ServerCallContext
    from a2a.server.events import EventQueue
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes.agent_card_routes import create_agent_card_routes
    from a2a.server.routes.common import ServerCallContextBuilder
    from a2a.server.routes.fastapi_routes import add_a2a_routes_to_fastapi
    from a2a.server.routes.jsonrpc_routes import create_jsonrpc_routes
    from a2a.server.routes.rest_routes import create_rest_routes
    from a2a.types import (
        AgentCapabilities,
        AgentCard,
        AgentInterface,
        AgentSkill,
        Message,
        Part,
        Role,
        Task,
        TaskState,
    )
    from starlette.routing import Mount

    from runtime.memory.a2a_inbound_task_store import A2ASqliteTaskStore

    class _A2AUser(User):
        def __init__(self, actor_id: str) -> None:
            self._actor_id = actor_id

        @property
        def is_authenticated(self) -> bool:
            return bool(self._actor_id)

        @property
        def user_name(self) -> str:
            return self._actor_id or "local-a2a"

    class _ContextBuilder(ServerCallContextBuilder):
        def build(self, request: Any) -> ServerCallContext:
            from runtime.adapters.web_auth import _resolve_actor

            actor = _resolve_actor(
                request,
                identity_store,
                require_auth,
                jwt_secret=jwt_secret,
                jwt_issuer=jwt_issuer,
                jwt_audience=jwt_audience,
            )
            actor_id = str(actor or "local-a2a")
            return ServerCallContext(
                user=_A2AUser(actor_id),
                tenant=actor_id,
                state={"headers": dict(request.headers)},
            )

    class _OctopusExecutor(AgentExecutor):
        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            from runtime.execution.suckers.delegation_skills import _allowed_agent_ids, _call_agent

            text = context.get_user_input().strip()
            if public_prefix and role_id not in _allowed_agent_ids():
                output = "Published role is unavailable on the receiving host."
                success = False
            elif not text:
                output = "A2A request contained no text input."
                success = False
            else:
                from runtime.sensing.gateway.inbound_role_execution import execute_role

                result = await asyncio.to_thread(
                    execute_role,
                    _call_agent,
                    role_id=role_id,
                    prompt=text,
                    data_dir=data_dir,
                    actor_id=context.call_context.user.user_name if context.call_context else None,
                )
                output = str(result.get("output") or result.get("error") or "").strip()
                success = bool(result.get("success")) and bool(output)
                if not output:
                    output = "Octopus agent returned no response."
            reply = Message(
                message_id=f"msg-{uuid.uuid4().hex}",
                task_id=str(context.task_id or ""),
                context_id=str(context.context_id or ""),
                role=Role.ROLE_AGENT,
                parts=[Part(text=output)],
            )
            task = Task(
                id=str(context.task_id or f"task-{uuid.uuid4().hex}"),
                context_id=str(context.context_id or f"context-{uuid.uuid4().hex}"),
            )
            if context.message is not None:
                task.history.append(context.message)
            task.history.append(reply)
            task.status.state = (
                TaskState.TASK_STATE_COMPLETED if success else TaskState.TASK_STATE_FAILED
            )
            task.status.message.CopyFrom(reply)
            task.status.timestamp.GetCurrentTime()
            await event_queue.enqueue_event(task)

        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            task = Task(
                id=str(context.task_id or ""),
                context_id=str(context.context_id or ""),
            )
            if context.current_task is not None:
                task.CopyFrom(context.current_task)
            task.status.state = TaskState.TASK_STATE_CANCELED
            task.status.timestamp.GetCurrentTime()
            await event_queue.enqueue_event(task)

    public_base = (
        os.getenv("OCTOPUS_A2A_PUBLIC_URL", "http://localhost:8310").rstrip("/") + public_prefix
    )
    rpc_path = "/api/a2a/rpc"
    card = AgentCard(
        name=role_name or "Echo Multi-Agent Workspace",
        description=(
            "Delegate to this Echo role. The receiving role owns execution and model selection. "
            "Remote callers submit tasks, not engine settings."
        ),
        version="1.0.0",
        supported_interfaces=[
            AgentInterface(
                url=public_base + rpc_path,
                protocol_binding="JSONRPC",
                protocol_version="1.0",
            )
        ],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="multi-agent-collaboration",
                name="Multi-agent collaboration",
                description="Delegate a bounded task to an isolated Octopus specialist.",
                tags=["collaboration", "research", "coding", "analysis"],
                input_modes=["text/plain"],
                output_modes=["text/plain"],
            )
        ],
    )
    store = A2ASqliteTaskStore(Path(data_dir) / "a2a")
    handler = DefaultRequestHandler(
        agent_executor=_OctopusExecutor(),
        task_store=store,
        agent_card=card,
    )
    context_builder = _ContextBuilder()
    rest_prefix = "/api/a2a/server"
    rest_routes = create_rest_routes(
        handler,
        context_builder=context_builder,
        enable_v0_3_compat=True,
        path_prefix=rest_prefix,
    )
    # a2a-sdk also emits a catch-all ``Mount('/{tenant}')`` regardless of
    # ``path_prefix``.  On a shared FastAPI application that mount captures
    # every later top-level route (for example ``/api/teach-repeat``) before
    # its authentication dependencies can run.  Keep the official direct
    # endpoints and scope the optional tenant form under the A2A namespace.
    rest_routes = [route for route in rest_routes if not isinstance(route, Mount)]
    tenant_children = [
        route
        for route in create_rest_routes(
            handler,
            context_builder=context_builder,
            enable_v0_3_compat=True,
        )
        if not isinstance(route, Mount)
    ]
    rest_routes.append(Mount(path=f"{rest_prefix}/{{tenant}}", routes=tenant_children))

    add_a2a_routes_to_fastapi(
        app,
        agent_card_routes=create_agent_card_routes(card),
        jsonrpc_routes=create_jsonrpc_routes(
            handler,
            rpc_url=rpc_path,
            context_builder=context_builder,
            enable_v0_3_compat=True,
        ),
        rest_routes=rest_routes,
    )
    app.router.add_event_handler("shutdown", handler.aclose)
    app.state.a2a_server_handler = handler
    app.state.a2a_server_task_store = store
    if not public_prefix:
        from runtime.sensing.gateway.published_roles import mount_published_roles

        mount_published_roles(
            app,
            data_dir=Path(data_dir),
            identity_store=identity_store,
            require_auth=require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
    return handler


__all__ = ["mount_a2a_server"]
