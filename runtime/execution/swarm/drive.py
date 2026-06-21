"""Reusable entry point to the boids/SignalBus mesh swarm.

``SwarmRuntime`` — the mesh swarm with boids arbitration and Arm-to-Arm
``SignalBus`` chatter — was wired only inside the ``octopus run`` CLI, so the
project's most distinctive biomimetic capability was unreachable from any
other surface. This factors the boids + swarm construction into one callable
that any surface (a serve bridge, a skill) can drive, and surfaces the mesh's
live coordination via an ``on_signal`` callback so a streaming caller can show
the Arm-to-Arm chatter as it happens.

The caller owns the ``SignalBus`` and ``ArmPool`` (the arms must be built with
the same bus — that shared bus IS the mesh substrate — and which arms exist is
the caller's decision); this wires boids + ``SwarmRuntime`` + the signal tap
on top.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.execution.swarm import SwarmRuntime
from runtime.safety.chromatophores import BoidsArbitrator


def run_swarm(
    graph: Any,
    budget: Any,
    *,
    arm_pool: Any,
    signal_bus: Any,
    journal: Any = None,
    max_workers: int = 4,
    split_strategy: str = "per_node",
    on_signal: Callable[[Any], None] | None = None,
) -> Any:
    """Drive ``graph`` through the mesh swarm and return its ``SwarmResult``.

    ``arm_pool`` must have been built with ``signal_bus`` so arms and swarm
    share one bus (= the mesh). ``on_signal`` receives every ``SignalEvent``
    the swarm publishes — the live Arm-to-Arm mesh coordination.
    """
    if on_signal is not None:
        signal_bus.subscribe("*", on_signal)
    swarm = SwarmRuntime(
        arm_pool=arm_pool,
        signal_bus=signal_bus,
        boids=BoidsArbitrator(signal_bus=signal_bus),
        journal=journal,
        max_workers=max_workers,
    )
    return swarm.run(graph, budget, split_strategy=split_strategy)
