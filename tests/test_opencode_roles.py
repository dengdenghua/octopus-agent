"""External members inherit host authority without loading a native planner."""

import asyncio
import contextlib
import time
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from runtime.execution import opencode_roles as roles
from runtime.execution.parallel_agents.stack_runner import make_stack_subagent_runner
from runtime.execution.request import (
    ExecutionDeadlineExceeded,
    ExecutionRequest,
    ExecutionResources,
    ExecutionTask,
    current_execution_request,
    execution_request_scope,
)
from runtime.platform.process.scope import ExecutionScope
from runtime.platform.process.session import Session, current_session, session_scope


@pytest.fixture
def host(tmp_path, monkeypatch):
    agent = SimpleNamespace(
        agent_id="member",
        soul="A helpful member",
        arms=[],
        extra_skills=[],
        capabilities={"execution_backend": "opencode_server"},
    )
    task = ExecutionTask(
        task_id="parent-turn",
        thread_id="parent-thread",
        actor_id="alice",
        tenant_id="acme",
        goal="Original request",
        authorization_intent="Original human authorization",
        permissions=ExecutionScope(
            mode="ask",
            requested_mode="ask",
            readable_roots=(tmp_path,),
            writable_roots=(),
            network_policy="deny",
            shell_policy="deny",
        ),
        resources=ExecutionResources(1000, 1.0, time.monotonic() + 30),
        execution_engine="opencode",
        approval_provider=object(),
    )
    request = ExecutionRequest(task, task.goal)
    session = Session(
        actor="alice",
        agent=agent,
        thread_id=task.thread_id,
        turn_id=task.task_id,
        metadata={"tenant_id": "acme", "workspace_path": str(tmp_path)},
    )
    monkeypatch.setattr(
        roles.backend,
        "zen_catalog",
        lambda: {"opencode-zen": {"managed_by_plugin": "opencode-zen", "models": ["big-pickle"]}},
    )
    return SimpleNamespace(
        agent=agent,
        request=request,
        session=session,
        stack=SimpleNamespace(executor=SimpleNamespace(registry=None)),
    )


@pytest.mark.parametrize("cost", [0, 0.25, None])
def test_member_forwards_explicit_project_cost_receipt(host, monkeypatch, cost):
    seen = []

    async def stream(stack, agent, **kw):
        seen.append(kw["request"].task.task_id)
        yield {"type": "text_delta", "delta": "Delivery"}
        yield {"type": "react_completed", "success": True, "completion_receipt": {"cost": cost}}

    report = Mock()
    monkeypatch.setattr(roles, "stream_role", stream)
    with execution_request_scope(host.request), session_scope(host.session):
        roles.run_role_sync(host.stack, host.agent, "task", context={"record_project_usage": report}, interrupted=lambda: False)
    report.assert_called_once_with({"governance": {"root_id": seen[0], "cost_usd": cost}})


def test_member_uses_child_identity_and_preserves_authority(host, monkeypatch):
    seen = []

    async def stream(stack, agent, **kw):
        seen.append(kw)
        yield {"type": "text_delta", "delta": "Member answer"}
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr(roles, "stream_role", stream)
    with execution_request_scope(host.request), session_scope(host.session):
        for _ in range(2):
            assert (
                roles.run_role_sync(
                    host.stack,
                    host.agent,
                    "Assigned task",
                    context={
                        "actor": "mallory",
                        "tenant_id": "other",
                        "thread_id": "forged",
                        "direct_conversation_reply": True,
                    },
                    interrupted=lambda: False,
                )
                == "Member answer"
            )
        assert current_execution_request() is host.request
        assert current_session() is host.session
    first, second = seen
    task = first["request"].task
    assert task.parent_task_id == host.request.task.task_id
    assert task.task_id != second["request"].task.task_id
    assert task.actor_id == "alice" and task.tenant_id == "acme"
    assert task.permissions is host.request.task.permissions
    assert task.resources is host.request.task.resources
    assert task.approval_provider is host.request.task.approval_provider
    assert task.authorization_intent == "Original human authorization"
    assert first["session"].turn_id == task.task_id
    assert first["session"].thread_id == task.thread_id
    assert first["tool_free"] is True


@pytest.mark.parametrize(
    "events",
    [
        [],
        [{"type": "text_delta", "delta": "partial"}],
        [{"type": "react_completed", "success": True}],
    ],
)
def test_incomplete_member_is_failure(host, monkeypatch, events):
    async def stream(*args, **kwargs):
        for event in events:
            yield event

    monkeypatch.setattr(roles, "stream_role", stream)
    with (
        execution_request_scope(host.request),
        session_scope(host.session),
        pytest.raises(roles.backend.OpenCodeError, match="没有完成"),
    ):
        roles.run_role_sync(host.stack, host.agent, "task", context={}, interrupted=lambda: False)


def test_member_requires_host_context_and_worker_thread(host):
    with pytest.raises(roles.backend.OpenCodeError, match="缺少宿主"):
        roles.run_role_sync(host.stack, host.agent, "task", context={}, interrupted=lambda: False)

    async def run():
        with pytest.raises(RuntimeError, match="to_thread"):
            roles.run_role_sync(
                host.stack, host.agent, "task", context={}, interrupted=lambda: False
            )

    asyncio.run(run())


def test_member_cancellation_uses_worker_exception_contract(host, monkeypatch):
    from runtime.safety.approval.cancellation import OperationCancelled

    async def stream(*args, **kwargs):
        yield {"type": "text_delta", "delta": "partial"}
        raise asyncio.CancelledError()

    monkeypatch.setattr(roles, "stream_role", stream)
    with (
        execution_request_scope(host.request),
        session_scope(host.session),
        pytest.raises(OperationCancelled),
    ):
        roles.run_role_sync(host.stack, host.agent, "task", context={}, interrupted=lambda: False)


def test_dispatch_never_accesses_native_planner_even_for_chat(host, monkeypatch):
    class ExternalHost:
        @property
        def planner(self):
            raise AssertionError("native planner loaded")

        @property
        def runtime(self):
            raise AssertionError("native runtime loaded")

    run = Mock(return_value="external answer")
    monkeypatch.setattr(roles, "run_role_sync", run)
    registry = SimpleNamespace(has=lambda name: True, get=lambda name: host.agent)
    runner = make_stack_subagent_runner(ExternalHost(), agent_registry=registry)
    assert (
        runner("hi", subagent_name="member", context={"direct_conversation_reply": True})
        == "external answer"
    )
    assert run.call_args.kwargs["context"]["direct_conversation_reply"] is True


@pytest.mark.parametrize(
    "field,value",
    [
        ("actor_id", "mallory"),
        ("thread_id", "foreign"),
        ("task_id", "foreign"),
        ("execution_engine", "codex"),
    ],
)
def test_identity_mismatch_precedes_credential_access(host, monkeypatch, field, value):
    probe = Mock(side_effect=AssertionError("credentials accessed"))
    monkeypatch.setattr(roles.backend, "inspect_readiness", probe)
    request = replace(host.request, task=replace(host.request.task, **{field: value}))

    async def run():
        with pytest.raises(roles.backend.OpenCodeError, match="身份不一致"):
            async for _ in roles.stream_role(
                host.stack,
                host.agent,
                request=request,
                session=host.session,
                context={},
                model="big-pickle",
                text="task",
                tool_free=True,
                interrupted=lambda: False,
            ):
                pass

    asyncio.run(run())
    probe.assert_not_called()


@pytest.mark.parametrize("cancelled", [False, True])
def test_tool_free_stream_owns_lifetime_and_context(host, monkeypatch, tmp_path, cancelled):
    lifecycle = []
    monkeypatch.setattr(roles.backend, "inspect_readiness", lambda scope: {"available": True})
    monkeypatch.setattr(roles.backend, "state_directory", lambda scope, thread: tmp_path / thread)
    monkeypatch.setattr(roles.backend, "zen_key", lambda scope: "fixture")
    monkeypatch.setattr(roles.backend, "executable", lambda: "fixture")

    @contextlib.asynccontextmanager
    async def server(executable, root, key, model, web, *, host_mcp):
        assert web is False and host_mcp is None
        lifecycle.append("open")
        try:
            yield object()
        finally:
            lifecycle.append("close")

    async def session_for_thread(*args):
        return "external-session"

    async def stream(client, session_id, **kwargs):
        assert current_execution_request() is host.request
        active = current_session()
        assert active.agent is host.session.agent
        assert active.actor == host.session.actor
        assert active.thread_id == host.session.thread_id
        assert active.metadata == {
            **host.session.metadata,
            "model_name": "big-pickle",
            "_execution_task": host.request.task,
        }
        assert kwargs["tool_names"] == {}
        assert str(tmp_path) in kwargs["system"]
        assert "forged-root" not in kwargs["system"]
        try:
            yield {"type": "text_delta", "delta": "Hello"}
            if cancelled:
                yield {"type": "react_cancelled"}
                return
            yield {"type": "react_completed", "success": True}
        finally:
            lifecycle.append("stream-close")

    monkeypatch.setattr(roles.backend, "managed_server", server)
    monkeypatch.setattr(roles.backend, "session_for_thread", session_for_thread)
    monkeypatch.setattr(roles.backend, "stream_prompt", stream)

    async def run():
        return [
            event
            async for event in roles.stream_role(
                host.stack,
                host.agent,
                request=host.request,
                session=host.session,
                context={"workspace_path": "forged-root"},
                model="big-pickle",
                text="hi",
                tool_free=True,
                interrupted=lambda: False,
            )
        ]

    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(run())
    else:
        assert len(asyncio.run(run())) == 2
    assert lifecycle == ["open", "stream-close", "close"]
    assert not roles._states


@pytest.mark.parametrize("ending", ["success", "error", "cancel"])
@pytest.mark.parametrize("provider_kind", ["inherited", "same", "replacement"])
@pytest.mark.parametrize("direct_reply", [False, True])
def test_realtime_adapter_preserves_history_events_and_cleanup(
    host, monkeypatch, ending, provider_kind, direct_reply
):
    from unittest.mock import AsyncMock

    from runtime.protocol import Turn, TurnParams, TurnStatus
    from runtime.sensing.gateway import realtime_opencode_backend as realtime

    turn = Turn(
        threadId="parent-thread",
        params=TurnParams(
            threadId="parent-thread",
            owner_actor_id="alice",
            tenant_id="acme",
            executionEngine="opencode",
            model="auto",
        ),
    )
    request = replace(host.request, task=replace(host.request.task, task_id=turn.id))
    inherited_provider = request.task.approval_provider
    provider = {
        "inherited": None,
        "same": inherited_provider,
        "replacement": object(),
    }[provider_kind]
    session = replace(host.session, turn_id=turn.id)
    bridge = SimpleNamespace(flush=AsyncMock(), prose_status_for_turn=lambda status: "done")
    runtime = SimpleNamespace(
        _stack=host.stack,
        _make_bridge_state=Mock(return_value=bridge),
        _apply_react_event=AsyncMock(),
    )
    history = SimpleNamespace(
        prompt=lambda text, resumed: f"history:{resumed}:{text}", mark_delivered=Mock()
    )
    monkeypatch.setattr(realtime, "engine_history_for_turn", lambda *args: history)
    emitter = SimpleNamespace(
        notify=AsyncMock(), is_turn_interrupted=lambda turn_id: ending == "cancel"
    )

    async def stream(*args, **kwargs):
        assert kwargs["text"] == "history:True:hi"
        assert kwargs["fresh_text"] == "history:False:hi"
        task = kwargs["request"].task
        assert task.approval_provider is (inherited_provider if provider is None else provider)
        assert task.permissions is request.task.permissions
        assert task.resources is request.task.resources
        assert task.task_id == turn.id
        assert kwargs["tool_free"] is direct_reply
        yield {"type": "text_delta", "delta": "Hello"}
        if ending == "error":
            raise roles.backend.OpenCodeError("fixture failure")
        if ending == "cancel":
            raise asyncio.CancelledError()
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr(realtime, "stream_role", stream)

    async def run():
        with execution_request_scope(request), session_scope(session):
            call = realtime.drive_opencode(
                runtime,
                turn,
                object(),
                emitter,
                SimpleNamespace(user_context={"direct_conversation_reply": direct_reply}),
                host.agent,
                provider=provider,
                text="hi",
            )
            if ending == "cancel":
                with pytest.raises(asyncio.CancelledError):
                    await call
            else:
                await call
        assert not [task for task in asyncio.all_tasks() if task is not asyncio.current_task()]

    asyncio.run(run())
    assert history.mark_delivered.call_count == (1 if ending == "success" else 0)
    events = [call.args[-1]["type"] for call in runtime._apply_react_event.call_args_list]
    assert events == [
        "text_delta",
        {"success": "react_completed", "error": "react_error", "cancel": "react_cancelled"}[ending],
    ]
    bridge.flush.assert_awaited_once()
    if ending == "cancel":
        assert turn.status is TurnStatus.CANCELLED
    assert current_execution_request() is None
    assert request.task.approval_provider is inherited_provider


def test_state_lock_cancellation_does_not_leak_or_unlock_owner():
    async def run():
        async with roles._hold_state("same", lambda: False):
            with pytest.raises(asyncio.CancelledError):
                async with roles._hold_state("same", lambda: True):
                    pytest.fail("cancelled waiter entered")
            assert roles._states["same"].lock.locked()
            assert roles._states["same"].references == 1
        assert not roles._states

    asyncio.run(run())


def test_deadline_cancels_work_and_preserves_unrelated_timeout(host):
    async def run():
        request = replace(
            host.request,
            task=replace(
                host.request.task,
                resources=replace(host.request.task.resources, deadline=time.monotonic() + 0.03),
            ),
        )
        with pytest.raises(ExecutionDeadlineExceeded):
            async with roles._task_deadline(request), roles._hold_state("deadline", lambda: False):
                await asyncio.Event().wait()
        assert not roles._states
        with pytest.raises(TimeoutError, match="transport timeout") as exc:
            async with roles._task_deadline(host.request):
                raise TimeoutError("transport timeout")
        assert not isinstance(exc.value, ExecutionDeadlineExceeded)

    asyncio.run(run())


def test_tool_stream_uses_real_scoped_mcp_and_closes_it(tmp_path, monkeypatch):
    from tests.test_host_mcp import host as make_host
    from tests.test_host_mcp import rpc

    original, _, workspace = make_host(tmp_path)
    request = replace(
        original.request, task=replace(original.request.task, execution_engine="opencode")
    )
    connection_seen = []
    monkeypatch.setattr(roles.backend, "inspect_readiness", lambda scope: {"available": True})
    monkeypatch.setattr(roles.backend, "state_directory", lambda scope, thread: tmp_path / "state")
    monkeypatch.setattr(roles.backend, "zen_key", lambda scope: "fixture")
    monkeypatch.setattr(roles.backend, "executable", lambda: "fixture")

    @contextlib.asynccontextmanager
    async def server(executable, root, key, model, web, *, host_mcp):
        assert host_mcp is not None
        connection_seen.append(host_mcp)

        async def handle(req):
            assert req.url.path == "/mcp"
            return httpx.Response(200, json={"echo": {"status": "connected"}})

        async with httpx.AsyncClient(
            base_url="http://engine", transport=httpx.MockTransport(handle)
        ) as client:
            yield client

    async def session_for_thread(*args):
        return "fixture-session"

    async def stream(client, session_id, **kwargs):
        connection = connection_seen[0]
        headers = {
            "Authorization": f"Bearer {connection.token}",
            "Accept": "application/json, text/event-stream",
        }
        async with httpx.AsyncClient(
            base_url=connection.url, headers=headers, trust_env=False
        ) as mcp:
            await rpc(
                mcp,
                0,
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "role-test", "version": "1"},
                },
            )
            read = await rpc(
                mcp, 1, "tools/call", {"name": "read_file", "arguments": {"path": "note.txt"}}
            )
            assert not read["isError"] and "before" in str(read["content"])
            write = await rpc(
                mcp,
                2,
                "tools/call",
                {
                    "name": "write_text_file",
                    "arguments": {"path": "note.txt", "content": "unauthorized", "overwrite": True},
                },
            )
            assert write["isError"]
        assert "echo_read_file" in kwargs["tool_names"]
        yield {"type": "text_delta", "delta": "Read and checked permissions"}
        yield {"type": "react_completed", "success": True}

    monkeypatch.setattr(roles.backend, "managed_server", server)
    monkeypatch.setattr(roles.backend, "session_for_thread", session_for_thread)
    monkeypatch.setattr(roles.backend, "stream_prompt", stream)

    async def run():
        result = [
            event
            async for event in roles.stream_role(
                original.broker._stack,
                original.session.agent,
                request=request,
                session=original.session,
                context={},
                model="big-pickle",
                text="read",
                interrupted=lambda: False,
            )
        ]
        assert result[-1]["success"] is True
        async with httpx.AsyncClient(trust_env=False) as client:
            with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
                await client.post(connection_seen[0].url, timeout=1)

    asyncio.run(run())
    assert (workspace / "note.txt").read_text(encoding="utf-8") == "before"
    assert not roles._states
