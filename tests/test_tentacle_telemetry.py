from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from runtime.tentacle import Heartbeat
from runtime.tentacle.telemetry import FaultKind, TelemetryHub, classify_fault


def test_fault_taxonomy_distinguishes_physical_and_software_failures() -> None:
    assert classify_fault(-32011, "Device offline") == FaultKind.CONNECTIVITY
    assert classify_fault(-32004, "temperature exceeds safety limit") == FaultKind.SAFETY
    assert classify_fault(-1, "robot arm jammed") == FaultKind.PHYSICAL
    assert classify_fault(-1, "sensor calibration invalid") == FaultKind.SENSOR
    assert classify_fault(-1, "unexpected response") == FaultKind.SOFTWARE


def test_health_uses_heartbeat_failures_and_battery() -> None:
    hub = TelemetryHub()
    now = time.time()
    hub.record_heartbeat(
        Heartbeat(
            tentacle_id="device-1",
            ts=int(now * 1000),
            online=True,
            battery=5,
            is_charging=False,
        )
    )
    hub.record_receipt(
        SimpleNamespace(
            device_id="device-1",
            started_at=now - 0.1,
            finished_at=now,
            success=False,
            error_code=-1,
            error_message="motor jammed",
            action="move",
            receipt_id="receipt-1",
        )
    )

    health = hub.health("device-1")

    assert health["level"] == "unhealthy"
    assert health["score"] == 20
    assert hub.faults("device-1")[0]["kind"] == "physical"


def test_realtime_subscriber_receives_events() -> None:
    async def scenario() -> None:
        hub = TelemetryHub()
        queue = hub.subscribe(max_queue=2)
        hub.publish("procedure.updated", "device-1", {"status": "running"})
        event = await asyncio.wait_for(queue.get(), timeout=1)
        assert event["event"] == "procedure.updated"
        assert event["device_id"] == "device-1"
        hub.unsubscribe(queue)

    asyncio.run(scenario())
