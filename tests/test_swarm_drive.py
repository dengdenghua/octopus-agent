"""run_swarm — the reusable mesh-swarm entry + its on_signal mesh tap."""
from __future__ import annotations

from typing import Any

from runtime.execution.swarm import drive
from runtime.safety.chromatophores import SignalBus


def test_run_swarm_runs_and_taps_mesh_signals(monkeypatch) -> None:
    captured: list[Any] = []

    class _FakeSwarm:
        def __init__(self, *, arm_pool, signal_bus, boids, journal, max_workers):
            self._bus = signal_bus
            self.kw = (arm_pool, journal, max_workers)

        def run(self, graph, budget, *, split_strategy):
            # the swarm publishes Arm-to-Arm mesh chatter during a run
            self._bus.publish(
                "arm.handoff", {"from": "code_arm", "to": "text_arm"}, publisher="swarm",
            )
            return f"result:{graph}:{split_strategy}"

    monkeypatch.setattr(drive, "SwarmRuntime", _FakeSwarm)
    bus = SignalBus()
    result = drive.run_swarm(
        "graph-X", "budget",
        arm_pool="pool", signal_bus=bus, max_workers=2,
        split_strategy="topo_layers",
        on_signal=captured.append,
    )
    assert result == "result:graph-X:topo_layers"
    assert len(captured) == 1               # the live mesh signal was tapped
    assert captured[0].topic == "arm.handoff"
    assert captured[0].payload == {"from": "code_arm", "to": "text_arm"}


def test_run_swarm_without_on_signal(monkeypatch) -> None:
    class _FakeSwarm:
        def __init__(self, **_kw):
            pass

        def run(self, graph, budget, *, split_strategy):
            return "ok"

    monkeypatch.setattr(drive, "SwarmRuntime", _FakeSwarm)
    assert drive.run_swarm("g", "b", arm_pool="p", signal_bus=SignalBus()) == "ok"
