from __future__ import annotations

import asyncio

from runtime.tentacle import (
    ActionSpec,
    ApprovalClass,
    DeviceManifest,
    MobileDevice,
    SafetySpec,
    TentaclePool,
    ValueConstraint,
    manifest_for,
)


def test_hard_argument_limits_are_machine_enforced() -> None:
    manifest = DeviceManifest(
        device_id="heater-01",
        kind="heater",
        platform="modbus",
        actions=(
            ActionSpec(
                name="set_temperature",
                arguments=(
                    ValueConstraint(
                        name="value", required=True, minimum=10, maximum=60, unit="celsius"
                    ),
                ),
                approval=ApprovalClass.OPERATOR,
            ),
        ),
    )

    assert manifest.validate_action("set_temperature", {"value": 35}) == []
    assert manifest.validate_action("set_temperature", {"value": 80}) == ["value must be <= 60"]
    assert manifest.validate_action("set_temperature", {}) == ["missing required argument: value"]


def test_forbidden_action_wins_over_declared_action() -> None:
    manifest = DeviceManifest(
        device_id="arm-01",
        kind="robot_arm",
        platform="ros2",
        actions=(ActionSpec(name="disable_interlock"),),
        safety=SafetySpec(forbidden_actions=("disable_interlock",)),
    )

    assert manifest.validate_action("disable_interlock", {}) == [
        "action is forbidden by driver safety policy: disable_interlock"
    ]


def test_legacy_tentacle_is_discoverable_without_protocol_break() -> None:
    class LegacyTentacle:
        tentacle_id = "legacy-1"
        tentacle_type = "iot"
        platform = "mqtt"
        capabilities = ["read_temperature"]
        meta = {"brand": "Echo"}

    manifest = manifest_for(LegacyTentacle())

    assert manifest.device_id == "legacy-1"
    assert manifest.vendor == "Echo"
    assert manifest.action("read_temperature") is not None


def test_pool_exposes_mobile_device_manifest() -> None:
    async def scenario() -> tuple[TentaclePool, MobileDevice]:
        pool = TentaclePool()
        device = MobileDevice("android-contract", {"brand": "Google", "model": "Pixel"})
        await device.connect()
        await pool.register(device)
        return pool, device

    pool, device = asyncio.run(scenario())

    manifest = pool.manifest("android-contract")

    assert manifest is not None
    assert manifest.contract_version == "1.0"
    assert manifest.vendor == "Google"
    assert manifest.model == "Pixel"
    assert len(manifest.actions) == len(device.capabilities)
