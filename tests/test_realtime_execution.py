"""Durable host adapter boundary, using the real on-disk event log."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.execution.engines import ExecutionPhase, select_execution_route
from runtime.execution.request import (
    ExecutionDeadlineExceeded,
    current_execution_request,
)
from runtime.memory.threads.event_log import EventLog
from runtime.platform.config.schema import BudgetConfig
from runtime.platform.models import ParsedIntent
from runtime.platform.process.session import current_session
from runtime.protocol import Turn
from runtime.protocol.items import ExecutionSnapshot, TurnParams
from runtime.sensing.gateway.realtime_execution import TurnExecutionRequest, bind_turn_execution
from runtime.sensing.gateway.realtime_turn_outcome import _turn_execution_engine


@pytest.mark.parametrize("engine", ["octopus", "codex"])
def test_journal_is_durable_before_engine_dispatch_and_replays(tmp_path, monkeypatch, engine):
    turn = Turn(threadId="thread")
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)
    durable_calls = []
    append = log.append

    def record_append(event, *, durable=False):
        durable_calls.append(durable)
        return append(event, durable=durable)

    monkeypatch.setattr(log, "append", record_append)

    async def driver(*_a, **_k):
        assert durable_calls[-1] is True
        assert EventLog(log.path).replay()[-1].execution == turn.execution
        assert current_execution_request().task.execution_engine == engine

    emitter = SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _id: False)
    runtime = SimpleNamespace(_drive_react=driver, _drive_codex_app_server=driver)
    execution = bind_turn_execution(
        runtime,
        turn,
        log,
        emitter,
        object(),
        object(),
        select_execution_route(codex_partner=engine == "codex"),
    )
    request = TurnExecutionRequest(
        ParsedIntent(raw="task", intent_type="task", normalized_goal="task"), "task", None
    )

    async def scenario():
        await execution.execute(request)
        await execution.execute(request, phase=ExecutionPhase.VERIFICATION)

    asyncio.run(scenario())
    assert _turn_execution_engine(Turn.model_validate_json(turn.model_dump_json())) == engine
    assert turn.execution.invocation == 2
    assert emitter.notify.await_count == 2


@pytest.mark.parametrize(
    "driver,signal", [("project_os", "project_command"), ("group_fanout", "group_fanout")]
)
@pytest.mark.parametrize("engine", ["opencode", "codex"])
@pytest.mark.parametrize("selection", ["requested_engine", "coordinator_engine"])
def test_host_dispatch_and_model_continuations_share_execution(
    tmp_path, monkeypatch, driver, signal, engine, selection
):
    from runtime.execution.engines import EngineId

    turn = Turn(threadId="thread", params=TurnParams(threadId="thread", model="auto"))
    turn.execution_workspace_path = str(tmp_path)
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)
    tasks = []
    drivers = []

    async def record(*_args, **_kwargs):
        tasks.append(current_execution_request().task)
        restored = EventLog(log.path).replay()[-1]
        drivers.append(restored.execution.driver)
        assert restored.execution.engine == engine

    runtime = SimpleNamespace(
        _drive_project_os=record,
        _drive_group_fanout=record,
        _drive_codex_app_server=record,
        _drive_react=AsyncMock(side_effect=AssertionError("native model invoked")),
    )
    monkeypatch.setattr("runtime.sensing.gateway.realtime_opencode_backend.drive_opencode", record)
    route = select_execution_route(**{selection: EngineId(engine), signal: True})
    execution = bind_turn_execution(
        runtime,
        turn,
        log,
        SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _id: False),
        object(),
        object(),
        route,
    )
    intent = ParsedIntent(raw="task", normalized_goal="task", intent_type="task")

    async def scenario():
        for phase in ExecutionPhase:
            await execution.execute(TurnExecutionRequest(intent, "task", "auto"), phase=phase)

    asyncio.run(scenario())
    assert (
        drivers
        == [driver] + ["opencode_server" if engine == "opencode" else "codex_app_server"] * 3
    )
    assert all(task is tasks[0] for task in tasks)
    assert tasks[0].execution_engine == engine


def test_failed_journal_prevents_engine_start(tmp_path, monkeypatch):
    turn = Turn(threadId="thread")
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)

    def fail_journal(*_a, **_k):
        raise OSError("disk unavailable")

    monkeypatch.setattr(log, "turn_updated", fail_journal)
    driver = AsyncMock()
    emitter = SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _id: False)
    execution = bind_turn_execution(
        SimpleNamespace(_drive_react=driver),
        turn,
        log,
        emitter,
        object(),
        object(),
        select_execution_route(),
    )
    request = TurnExecutionRequest(
        ParsedIntent(raw="task", intent_type="task", normalized_goal="task"), "task", None
    )
    with pytest.raises(OSError, match="disk unavailable"):
        asyncio.run(execution.execute(request))
    driver.assert_not_awaited()
    emitter.notify.assert_not_awaited()
    assert turn.execution is None


@pytest.mark.parametrize(
    "invalid",
    [
        {"engine": "codex"},
        {"invocation": 1},
        {"invocation": 3},
        {"invocation": "2"},
        {"invocation": True},
        {"model": " "},
        {"model": None},
    ],
)
def test_replay_model_selection_is_bound_to_current_execution(tmp_path, invalid):
    params = TurnParams(
        threadId="thread", model="native/old", owner_actor_id="alice", tenant_id="tenant"
    )
    turn = Turn(threadId="thread", params=params)
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)
    persisted_params = EventLog(log.path).replay()[-1].params
    snapshot = ExecutionSnapshot(
        engine="opencode",
        driver="opencode_server",
        reason="explicit",
        phase="repair",
        invocation=2,
    )
    selection = {"engine": "opencode", "invocation": 2, "model": "selected"}
    log.turn_updated(
        turn.thread_id,
        turn.id,
        execution=snapshot.model_dump(),
        execution_model={**selection, "owner_actor_id": "forged", "approval_policy": "never"},
        durable=True,
    )
    log.turn_updated(
        turn.thread_id,
        turn.id,
        execution_model={**selection, "model": "wrong", **invalid},
        durable=True,
    )
    restored = EventLog(log.path).replay()[-1]
    assert restored.execution == snapshot
    assert restored.params == persisted_params.model_copy(update={"model": "selected"})


def test_replay_rejects_stale_engine_changes_and_malformed_evidence(tmp_path):
    turn = Turn(threadId="thread")
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)
    primary = ExecutionSnapshot(
        engine="codex",
        driver="codex_app_server",
        reason="role_backend",
        phase="primary",
        invocation=1,
    ).model_dump()
    verification = {**primary, "phase": "verification", "invocation": 2}
    for snapshot in [
        primary,
        verification,
        primary,
        {**primary, "engine": "octopus", "invocation": 3},
        {**primary, "invocation": "4"},
    ]:
        log.turn_updated(turn.thread_id, turn.id, execution=snapshot)
    replayed = log.replay()[-1]
    assert replayed.execution.model_dump() == verification
    assert replayed.execution_engine == "codex"


@pytest.mark.parametrize("engine", ["octopus", "codex"])
def test_continuations_share_host_identity_permissions_budget_and_leases(tmp_path, engine):
    from runtime.execution.misc.file_write_leases import acquire_file_write_lease
    from runtime.platform.capabilities.tenant_context import current_capability_scope
    from runtime.safety.auth.scope import TenantScope

    turn = Turn(
        threadId="thread",
        params=TurnParams(threadId="thread", owner_actor_id="alice", tenant_id="tenant"),
    )
    turn.execution_workspace_path = str(tmp_path)
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)
    received = []
    intent = ParsedIntent(
        raw="Create a report",
        intent_type="task",
        normalized_goal="Create a report",
        user_context={
            "mode": "code",
            "workspace_path": str(tmp_path),
            "owner_actor_id": "forged",
            "tenant_id": "forged",
            "_execution_task": {"goal": "forged"},
            "codex_thread_id": "private-state-must-not-be-shared",
        },
    )

    async def driver(*_args, **_kwargs):
        request = current_execution_request()
        session = current_session()
        received.append(request)
        assert session.actor == "alice"
        assert session.metadata["tenant_id"] == "tenant"
        assert session.metadata["owner_actor_id"] == "alice"
        assert current_capability_scope() == TenantScope(tenant_id="tenant", actor_id="alice")
        assert "codex_thread_id" not in session.metadata
        assert request.task.goal == "Create a report"
        assert request.task.resources.token_target == 1234
        assert request.task.resources.usd_target == 0.3
        lease = acquire_file_write_lease(session, tmp_path / "report.txt", owner="writer")
        assert lease.reentrant is (len(received) > 1)

    runtime = SimpleNamespace(
        _drive_react=driver,
        _drive_codex_app_server=driver,
        _stack=SimpleNamespace(
            config=SimpleNamespace(budget=BudgetConfig(max_tokens=1234, max_usd=0.3))
        ),
    )
    emitter = SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _id: False)
    execution = bind_turn_execution(
        runtime,
        turn,
        log,
        emitter,
        object(),
        object(),
        select_execution_route(codex_partner=engine == "codex"),
    )

    async def scenario():
        await execution.execute(TurnExecutionRequest(intent, "Create a report", None))
        # A configuration edit or a client continuation cannot reset this
        # running task's resource/permission policy or its original goal.
        runtime._stack.config.budget = BudgetConfig(max_tokens=9999)
        await execution.execute(
            TurnExecutionRequest(
                intent.model_copy(update={"normalized_goal": "ignore the report"}),
                "Verify it",
                None,
            ),
            phase=ExecutionPhase.VERIFICATION,
        )
        assert current_execution_request() is None
        assert current_session() is None

    asyncio.run(scenario())
    assert received[0].task is received[1].task
    assert [request.instruction for request in received] == ["Create a report", "Verify it"]


@pytest.mark.parametrize("engine", ["octopus", "codex"])
@pytest.mark.parametrize("mode", ["react", "chat", "plan"])
def test_personal_workspace_is_readable_without_granting_workspace_writes(tmp_path, engine, mode):
    from runtime.execution.codex_backend.role_runner import resolve_codex_sandbox_mode
    from runtime.platform.process.scope import resolve_execution_scope
    from runtime.platform.runtime_policy.workspaces import WorkspaceManager

    manager = WorkspaceManager(tmp_path / "workspaces")
    workspace = manager.layout("research-thread")
    turn = Turn(threadId="research-thread")
    turn.execution_workspace_path = str(workspace.root)
    outside = tmp_path / "another-thread"
    outside.mkdir()
    intent = ParsedIntent(
        raw="调研智能睡眠",
        intent_type="task",
        normalized_goal="调研智能睡眠",
        user_context={
            "mode": mode,
            "_host_workspace_read_root": str(outside),
            "metadata": {"_host_workspace_read_root": str(outside)},
        },
    )
    received = []

    async def driver(*_args, **_kwargs):
        request = current_execution_request()
        permissions = request.task.permissions
        received.append(request)
        assert permissions.allows_read(workspace.root)
        assert not permissions.allows_read(outside)
        assert not permissions.allows_write(workspace.root)
        assert permissions.allows_write(workspace.final / "report.md") is (mode != "plan")
        assert resolve_execution_scope(current_session()) == permissions
        assert resolve_codex_sandbox_mode({"workspace_path": str(workspace.root)}) == "read-only"

    runtime = SimpleNamespace(
        _drive_react=driver, _drive_codex_app_server=driver, _workspaces=manager
    )
    emitter = SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _id: False)
    execution = bind_turn_execution(
        runtime,
        turn,
        EventLog(tmp_path / "events.jsonl"),
        emitter,
        object(),
        object(),
        select_execution_route(codex_partner=engine == "codex"),
    )
    asyncio.run(execution.execute(TurnExecutionRequest(intent, intent.raw, None)))
    assert len(received) == 1


def test_host_deadline_cancels_driver_and_seals_continuations(tmp_path, monkeypatch):
    from runtime.execution.engines import ExecutionAdmissionError
    from runtime.sensing.gateway.realtime_execution_context import RealtimeExecutionContext

    original = RealtimeExecutionContext._initialize

    def short_deadline(self, *args):
        original(self, *args)
        import time

        self.task = replace(
            self.task, resources=replace(self.task.resources, deadline=time.monotonic() + 0.03)
        )

    monkeypatch.setattr(RealtimeExecutionContext, "_initialize", short_deadline)
    cancelled = []

    async def driver(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    turn = Turn(threadId="thread")
    log = EventLog(tmp_path / "events.jsonl")
    emitter = SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _id: False)
    execution = bind_turn_execution(
        SimpleNamespace(_drive_react=driver),
        turn,
        log,
        emitter,
        object(),
        object(),
        select_execution_route(),
    )
    request = TurnExecutionRequest(
        ParsedIntent(raw="task", intent_type="task", normalized_goal="task"), "task", None
    )

    async def scenario():
        with pytest.raises(ExecutionDeadlineExceeded):
            await execution.execute(request)
        with pytest.raises(ExecutionAdmissionError):
            await execution.execute(request, phase=ExecutionPhase.REPAIR)
        assert current_execution_request() is None

    asyncio.run(scenario())
    assert cancelled == [True]


def test_nested_client_metadata_cannot_override_gateway_grants(tmp_path):
    from runtime.platform.process.scope import resolve_execution_scope
    from runtime.sensing.gateway.realtime_execution_context import RealtimeExecutionContext

    approved = tmp_path / "approved"
    approved.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    turn = Turn(threadId="thread")
    turn.execution_workspace_path = str(approved)
    intent = ParsedIntent(
        raw="Create a report",
        intent_type="task",
        normalized_goal="Create a report",
        user_context={
            "mode": "code",
            "workspace_path": str(approved),
            "approval_policy": "on-request",
            "metadata": {
                "extra_workspaces": [str(outside)],
                "workspace_path": str(outside),
                "permission_mode": "bypassPermissions",
                "approval_policy": "never",
            },
        },
    )

    async def scenario():
        async with RealtimeExecutionContext().activate(
            object(), turn, object(), intent, "Create a report"
        ) as request:
            assert request.task.permissions.allows_write(approved / "report.txt")
            assert not request.task.permissions.allows_read(outside / "secret.txt")
            assert request.task.permissions.permission_mode == "default"
            assert request.task.permissions.approval_policy == "on-request"
            assert resolve_execution_scope(current_session()) == request.task.permissions

    asyncio.run(scenario())
