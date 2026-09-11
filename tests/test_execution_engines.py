"""Engine admission contracts: no overlapping effects or implicit fallback."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.execution.engines import (
    EngineId,
    ExecutionAdmissionError,
    ExecutionPhase,
    ExecutionRoute,
    ExecutionSupervisor,
    select_execution_route,
)


@pytest.mark.parametrize(
    ("signals", "engine", "driver"),
    [
        ({}, EngineId.OCTOPUS, "react"),
        ({"codex_partner": True}, EngineId.CODEX, "codex_app_server"),
        ({"reflection_fast_path": True}, EngineId.OCTOPUS, "reflection_fast_path"),
        ({"codex_partner": True, "reflection_fast_path": True}, EngineId.CODEX, "codex_app_server"),
        ({"topology_id": "team", "codex_partner": True}, EngineId.OCTOPUS, "swarm_mesh"),
        ({"group_fanout": True, "topology_id": "team"}, EngineId.OCTOPUS, "group_fanout"),
        ({"project_command": True, "group_fanout": True}, EngineId.OCTOPUS, "project_os"),
        ({"requested_engine": EngineId.CODEX}, EngineId.CODEX, "codex_app_server"),
        ({"requested_engine": EngineId.OCTOPUS, "codex_partner": True}, EngineId.OCTOPUS, "react"),
        ({"requested_engine": EngineId.OCTOPUS, "coding_task": True}, EngineId.OCTOPUS, "react"),
        ({"coding_task": True}, EngineId.CODEX, "codex_app_server"),
        ({"coordinated": True, "coding_task": True}, EngineId.OCTOPUS, "react"),
        ({"coordinated": True, "codex_partner": True}, EngineId.OCTOPUS, "react"),
        (
            {"requested_engine": EngineId.OCTOPUS, "reflection_fast_path": True},
            EngineId.OCTOPUS,
            "reflection_fast_path",
        ),
    ],
)
def test_host_orchestration_precedence(signals, engine, driver):
    route = select_execution_route(**signals)
    assert (route.engine, route.driver) == (engine, driver)


@pytest.mark.parametrize(
    "signal,driver",
    [
        ("project_command", "project_os"),
        ("group_fanout", "group_fanout"),
    ],
)
@pytest.mark.parametrize("engine", [EngineId.CODEX, EngineId.OPENCODE])
def test_explicit_engine_preserves_host_scheduler_precedence(signal, driver, engine):
    route = select_execution_route(requested_engine=engine, topology_id="team", **{signal: True})
    assert route.engine is engine
    assert route.driver_for(ExecutionPhase.PRIMARY) == driver
    assert route.driver_for(ExecutionPhase.REPAIR) == (
        "codex_app_server" if engine is EngineId.CODEX else "opencode_server"
    )


@pytest.mark.parametrize("engine", [EngineId.CODEX, EngineId.OPENCODE])
def test_topology_keeps_explicit_engine_for_planning_and_continuations(engine):
    route = select_execution_route(requested_engine=engine, topology_id="team")
    assert route.engine is engine
    assert route.driver_for(ExecutionPhase.PRIMARY) == "swarm_mesh"
    assert route.driver_for(ExecutionPhase.REPAIR) == (
        "codex_app_server" if engine is EngineId.CODEX else "opencode_server"
    )


def test_continuations_cannot_reselect_the_bound_engine():
    async def scenario():
        adapter = SimpleNamespace(engine=EngineId.CODEX, execute=AsyncMock())
        journal = AsyncMock()
        supervisor = ExecutionSupervisor(
            select_execution_route(codex_partner=True),
            adapter,
            is_interrupted=lambda: False,
            before_invoke=journal,
        )
        with pytest.raises(ExecutionAdmissionError):
            await supervisor.execute("too early", phase=ExecutionPhase.STEERING)
        await supervisor.execute("primary")
        with pytest.raises(ExecutionAdmissionError):
            await supervisor.execute("duplicate")
        for phase in (ExecutionPhase.STEERING, ExecutionPhase.VERIFICATION, ExecutionPhase.REPAIR):
            await supervisor.execute(phase.value, phase=phase)
            assert supervisor.route.driver_for(phase) == "codex_app_server"
        assert adapter.execute.await_count == journal.await_count == 4
        assert [call.args[1] for call in journal.await_args_list] == [1, 2, 3, 4]

    asyncio.run(scenario())


@pytest.mark.parametrize("failure_source", ["journal", "engine"])
def test_failure_seals_execution_without_retry(failure_source):
    async def scenario():
        adapter = SimpleNamespace(engine=EngineId.OCTOPUS, execute=AsyncMock())
        journal = AsyncMock()
        failing = journal if failure_source == "journal" else adapter.execute
        failing.side_effect = OSError("unavailable")
        supervisor = ExecutionSupervisor(
            select_execution_route(),
            adapter,
            is_interrupted=lambda: False,
            before_invoke=journal,
        )
        with pytest.raises(OSError, match="unavailable"):
            await supervisor.execute("task")
        with pytest.raises(ExecutionAdmissionError):
            await supervisor.execute("retry", phase=ExecutionPhase.REPAIR)
        assert adapter.execute.await_count == (0 if failure_source == "journal" else 1)

    asyncio.run(scenario())


@pytest.mark.parametrize("interrupt_during_journal", [False, True])
def test_stop_before_engine_start_admits_no_effects(interrupt_during_journal):
    async def scenario():
        interrupted = not interrupt_during_journal

        async def journal(*_args):
            nonlocal interrupted
            interrupted = True

        adapter = SimpleNamespace(engine=EngineId.OCTOPUS, execute=AsyncMock())
        supervisor = ExecutionSupervisor(
            select_execution_route(),
            adapter,
            is_interrupted=lambda: interrupted,
            before_invoke=journal,
        )
        with pytest.raises(asyncio.CancelledError):
            await supervisor.execute("task")
        with pytest.raises(ExecutionAdmissionError):
            await supervisor.execute("late", phase=ExecutionPhase.VERIFICATION)
        adapter.execute.assert_not_awaited()

    asyncio.run(scenario())


def test_overlapping_invocations_are_rejected_and_cancellation_propagates():
    async def scenario():
        entered = asyncio.Event()
        interrupted = asyncio.Event()

        async def driver(*_args):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                interrupted.set()

        supervisor = ExecutionSupervisor(
            select_execution_route(),
            SimpleNamespace(engine=EngineId.OCTOPUS, execute=driver),
            is_interrupted=lambda: False,
            before_invoke=AsyncMock(),
        )
        task = asyncio.create_task(supervisor.execute("primary"))
        await asyncio.wait_for(entered.wait(), timeout=1)
        with pytest.raises(ExecutionAdmissionError):
            await supervisor.execute("overlap", phase=ExecutionPhase.STEERING)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert interrupted.is_set()
        with pytest.raises(ExecutionAdmissionError):
            await supervisor.execute("after stop", phase=ExecutionPhase.VERIFICATION)

    asyncio.run(scenario())


def test_adapter_must_match_selected_engine():
    with pytest.raises(ValueError, match="does not match"):
        ExecutionSupervisor(
            ExecutionRoute(EngineId.CODEX, "codex_app_server", "explicit"),
            SimpleNamespace(engine=EngineId.OCTOPUS, execute=AsyncMock()),
            is_interrupted=lambda: False,
            before_invoke=AsyncMock(),
        )
