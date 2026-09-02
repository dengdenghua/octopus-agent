from __future__ import annotations

import asyncio
import time

from runtime.tentacle import (
    ActionGrant,
    ActionSpec,
    ApprovalClass,
    ApprovalEnvelope,
    DeviceActionExecutor,
    DeviceManifest,
    MobileDevice,
    TentaclePool,
    ToolCall,
    ValueConstraint,
)


def test_renewable_lease_keeps_identity_and_extends_expiry() -> None:
    async def scenario() -> None:
        pool = TentaclePool()
        device = MobileDevice("phone-lease")
        await device.connect()
        await pool.register(device)
        assert await pool.acquire_lock(device.tentacle_id, "arm-a", "task-a", timeout_s=1)
        lease = pool.lock_holder(device.tentacle_id)
        assert lease is not None
        lease_id = lease.lease_id
        assert await pool.renew_lock(device.tentacle_id, "arm-a", timeout_s=10)
        assert pool.lock_holder(device.tentacle_id).lease_id == lease_id  # type: ignore[union-attr]
        assert pool.lock_holder(device.tentacle_id).expires_in_s > 9  # type: ignore[union-attr]
        assert not await pool.renew_lock(device.tentacle_id, "arm-b")

    asyncio.run(scenario())


def test_approval_envelope_enforces_narrower_range() -> None:
    class Heater(MobileDevice):
        @property
        def manifest(self) -> DeviceManifest:
            return DeviceManifest(
                device_id=self.tentacle_id,
                kind="heater",
                platform="modbus",
                actions=(
                    ActionSpec(
                        name="set_temperature",
                        arguments=(
                            ValueConstraint("value", required=True, minimum=10, maximum=60),
                        ),
                        approval=ApprovalClass.OPERATOR,
                    ),
                ),
            )

    async def scenario() -> None:
        pool = TentaclePool()
        device = Heater("heater-1")
        device._capabilities = ["set_temperature"]
        await device.connect()
        await pool.register(device)
        executor = DeviceActionExecutor(pool)
        envelope = ApprovalEnvelope(
            envelope_id="grant-1",
            actor_id="operator-1",
            device_id=device.tentacle_id,
            grants=(
                ActionGrant(
                    "set_temperature",
                    (ValueConstraint("value", required=True, minimum=20, maximum=35),),
                ),
            ),
            expires_at=time.time() + 60,
        )

        allowed = await executor.execute_sequence(
            device,
            [ToolCall("call-ok", device.tentacle_id, "set_temperature", {"value": 30})],
            owner="operator-1",
            task_id="task-1",
            envelope=envelope,
        )
        denied = await executor.execute_sequence(
            device,
            [ToolCall("call-denied", device.tentacle_id, "set_temperature", {"value": 40})],
            owner="operator-1",
            task_id="task-2",
            envelope=envelope,
        )

        assert allowed[0].success
        assert not denied[0].success
        assert "requires operator approval envelope" in (denied[0].error_message or "")
        receipts = executor.ledger.list(device_id=device.tentacle_id)
        assert [receipt.call_id for receipt in receipts] == ["call-denied", "call-ok"]
        assert receipts[-1].before is not None
        assert receipts[-1].after is not None
        assert allowed[0].extra["execution_receipt_id"] == "device-call-ok"

    asyncio.run(scenario())
