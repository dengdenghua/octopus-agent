"""ADR-010 · swarm resource-contention wiring.

The BoidsArbitrator was complete but had no production caller — the swarm
pre-splits subgraphs per_node, so there was no runtime contention to
arbitrate. ADR-010 wires it at the dispatch boundary (`_run_one`) for
assignments that declare ``exclusive_resources``. These pin the claim →
serialise-on-lose → release loop, and that the default (no declared
resources) is a strict no-op so existing flows are unchanged.
"""

from __future__ import annotations

import threading
import time

from runtime.execution.arms.base import ArmPool
from runtime.execution.swarm.runtime import SwarmRuntime
from runtime.platform.models import ArmId
from runtime.safety.chromatophores.boids import BoidsArbitrator, ResourceClaim


def _rt(*, boids: BoidsArbitrator | None) -> SwarmRuntime:
    return SwarmRuntime(arm_pool=ArmPool([]), boids=boids, max_workers=2)


def _holds(rt: SwarmRuntime, uri: str) -> bool:
    return any(c.resource_uri == uri for c in rt._boids.active_claims())  # noqa: SLF001


# --------------------------------------------------------------------------- #
# No-op guarantees (backward compatibility)                                   #
# --------------------------------------------------------------------------- #


def test_no_declared_resources_is_noop():
    rt = _rt(boids=BoidsArbitrator())
    assert rt._claim_resources(ArmId("a"), []) == []  # noqa: SLF001
    assert rt._boids.active_claims() == []  # noqa: SLF001


def test_no_arbitrator_is_noop():
    rt = _rt(boids=None)
    # Even with declared resources, no arbitrator ⇒ nothing claimed.
    assert rt._claim_resources(ArmId("a"), ["device:x"]) == []  # noqa: SLF001


# --------------------------------------------------------------------------- #
# Claim / release round-trip                                                  #
# --------------------------------------------------------------------------- #


def test_claim_then_release_roundtrip():
    rt = _rt(boids=BoidsArbitrator())
    held = rt._claim_resources(ArmId("a"), ["device:desktop"])  # noqa: SLF001
    assert held == ["device:desktop"]
    assert _holds(rt, "device:desktop")
    rt._release_resources(ArmId("a"), held)  # noqa: SLF001
    assert not _holds(rt, "device:desktop")


def test_readonly_resources_coexist():
    rt = _rt(boids=BoidsArbitrator())
    a = rt._claim_resources(ArmId("a"), ["file:/data.csv:read"])  # noqa: SLF001
    b = rt._claim_resources(ArmId("b"), ["file:/data.csv:read"])  # noqa: SLF001
    assert a == ["file:/data.csv:read"]
    assert b == ["file:/data.csv:read"]  # readonly ⇒ both coexist


# --------------------------------------------------------------------------- #
# Serialisation on contention                                                 #
# --------------------------------------------------------------------------- #


def test_claim_waits_until_holder_releases():
    rt = _rt(boids=BoidsArbitrator())
    # Arm A holds the resource up front.
    rt._boids.arbitrate(  # noqa: SLF001
        ResourceClaim(arm_id=ArmId("A"), resource_uri="device:desktop", ttl_ms=600_000)
    )
    released_at: list[float] = []

    def _release_soon() -> None:
        time.sleep(0.1)
        rt._boids.release(ArmId("A"), "device:desktop")  # noqa: SLF001
        released_at.append(time.monotonic())

    worker = threading.Thread(target=_release_soon)
    worker.start()
    start = time.monotonic()
    held = rt._claim_resources(ArmId("B"), ["device:desktop"])  # noqa: SLF001 — blocks
    acquired_at = time.monotonic()
    worker.join()

    assert held == ["device:desktop"]  # B did eventually acquire it
    assert acquired_at - start >= 0.09  # …and only after waiting for the release
    assert released_at and acquired_at >= released_at[0]


def test_contention_timeout_degrades_without_deadlock():
    rt = _rt(boids=BoidsArbitrator())
    rt._CLAIM_TIMEOUT_S = 0.1  # don't make the test wait the full 30s  # noqa: SLF001
    # A holds it and never releases.
    rt._boids.arbitrate(  # noqa: SLF001
        ResourceClaim(arm_id=ArmId("A"), resource_uri="device:desktop", ttl_ms=600_000)
    )
    # B can't acquire within the timeout → degrades: proceeds holding nothing,
    # rather than blocking the pool forever.
    held = rt._claim_resources(ArmId("B"), ["device:desktop"])  # noqa: SLF001
    assert held == []
