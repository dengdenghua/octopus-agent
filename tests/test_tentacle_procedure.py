from __future__ import annotations

import asyncio
from pathlib import Path

from runtime.tentacle import (
    ActionSpec,
    DeviceActionExecutor,
    DeviceManifest,
    MobileDevice,
    Procedure,
    ProcedureCheckpointStore,
    ProcedureExecutor,
    ProcedureStatus,
    ProcedureStep,
    RetryPolicy,
    SafetySpec,
    TentaclePool,
    ToolCall,
    ToolResult,
)


class ProcedureDevice(MobileDevice):
    def __init__(self, device_id: str, *, failures: int = 0) -> None:
        super().__init__(device_id)
        self._capabilities = ["move", "stop"]
        self.failures = failures
        self.executed: list[str] = []

    @property
    def manifest(self) -> DeviceManifest:
        return DeviceManifest(
            device_id=self.tentacle_id,
            kind="robot",
            platform="test",
            actions=(
                ActionSpec(name="move", idempotent=True),
                ActionSpec(name="stop", idempotent=True),
            ),
            safety=SafetySpec(emergency_stop_action="stop", fail_safe_state="stopped"),
        )

    async def execute(self, call: ToolCall) -> ToolResult:
        self.executed.append(call.tool)
        if call.tool == "move" and self.failures > 0:
            self.failures -= 1
            return ToolResult.fail(call.call_id, -1, "temporary fault")
        return ToolResult.ok(call.call_id, {"action": call.tool})


def _executor(tmp_path: Path) -> tuple[TentaclePool, ProcedureExecutor]:
    pool = TentaclePool()
    guarded = DeviceActionExecutor(pool)
    return pool, ProcedureExecutor(guarded, ProcedureCheckpointStore(tmp_path))


def test_procedure_retries_idempotent_step_and_restores_checkpoint(tmp_path: Path) -> None:
    async def scenario() -> None:
        pool, executor = _executor(tmp_path)
        device = ProcedureDevice("robot-1", failures=1)
        await device.connect()
        await pool.register(device)
        procedure = Procedure(
            procedure_id="proc-1",
            device_id=device.tentacle_id,
            steps=(ProcedureStep("move-1", "move", {"distance": 5}, RetryPolicy(max_attempts=2)),),
        )

        result = await executor.run(procedure, device)
        restored = executor.checkpoint_store.load("proc-1")  # type: ignore[union-attr]

        assert result.status == ProcedureStatus.SUCCEEDED
        assert result.current_step == 1
        assert result.attempts == {"move-1": 2}
        assert device.executed == ["move", "move"]
        assert len(result.receipt_ids) == 2
        assert restored is not None
        assert restored.status == ProcedureStatus.SUCCEEDED
        assert restored.current_step == 1

    asyncio.run(scenario())


def test_paused_procedure_resumes_from_current_step(tmp_path: Path) -> None:
    async def scenario() -> None:
        pool, executor = _executor(tmp_path)
        device = ProcedureDevice("robot-2")
        await device.connect()
        await pool.register(device)
        procedure = Procedure(
            procedure_id="proc-2",
            device_id=device.tentacle_id,
            steps=(ProcedureStep("move-1", "move"),),
        )
        executor.pause(procedure)
        await executor.run(procedure, device)
        assert device.executed == []
        executor.resume(procedure)
        await executor.run(procedure, device)
        assert procedure.status == ProcedureStatus.SUCCEEDED
        assert device.executed == ["move"]

    asyncio.run(scenario())


def test_emergency_stop_uses_declared_driver_action(tmp_path: Path) -> None:
    async def scenario() -> None:
        pool, executor = _executor(tmp_path)
        device = ProcedureDevice("robot-3")
        await device.connect()
        await pool.register(device)
        procedure = Procedure("proc-3", device.tentacle_id, (ProcedureStep("move-1", "move"),))
        assert await pool.acquire_lock(
            device.tentacle_id, "procedure:proc-3", procedure.procedure_id
        )

        await executor.emergency_stop(procedure, device)

        assert procedure.status == ProcedureStatus.EMERGENCY_STOPPED
        assert device.executed == ["stop"]
        assert procedure.receipt_ids == ["device-proc-3:emergency-stop"]
        assert pool.lock_holder(device.tentacle_id) is None

    asyncio.run(scenario())


def test_checkpoint_store_rejects_path_traversal(tmp_path: Path) -> None:
    store = ProcedureCheckpointStore(tmp_path)
    try:
        store.path_for("../escape")
    except ValueError as exc:
        assert "unsafe" in str(exc)
    else:
        raise AssertionError("unsafe procedure id accepted")


def test_invalid_later_step_prevents_any_physical_execution(tmp_path: Path) -> None:
    async def scenario() -> None:
        pool, executor = _executor(tmp_path)
        device = ProcedureDevice("robot-4")
        await device.connect()
        await pool.register(device)
        procedure = Procedure(
            "proc-4",
            device.tentacle_id,
            (
                ProcedureStep("move-1", "move"),
                ProcedureStep("unknown-2", "undeclared_action"),
            ),
        )

        await executor.run(procedure, device)

        assert procedure.status == ProcedureStatus.FAILED
        assert "not declared" in (procedure.error or "")
        assert device.executed == []

    asyncio.run(scenario())


def test_driver_version_change_pauses_checkpointed_procedure(tmp_path: Path) -> None:
    async def scenario() -> None:
        pool, executor = _executor(tmp_path)
        device = ProcedureDevice("robot-5")
        await device.connect()
        await pool.register(device)
        procedure = Procedure(
            "proc-5",
            device.tentacle_id,
            (ProcedureStep("move-1", "move"),),
            expected_contract_version="1.0",
            expected_driver_version="older-driver",
        )

        await executor.run(procedure, device)

        assert procedure.status == ProcedureStatus.PAUSED
        assert "version changed" in (procedure.error or "")
        assert device.executed == []

    asyncio.run(scenario())
