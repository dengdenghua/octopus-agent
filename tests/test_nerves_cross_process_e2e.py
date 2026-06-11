"""End-to-end cross-process test for ``RedisEventBus``.

This is the test the project evaluation flagged as missing — proof that
``Nerves`` actually works across worker processes, not just in-process.

It spawns two real OS processes:
  * Process A — RedisEventBus subscriber listening for SkillRegistered
  * Process B — RedisEventBus publisher emitting one SkillRegistered

If subscriber receives the event within ``TIMEOUT`` seconds, the
cross-process claim is validated. If not, the bus is in-process only.

Skip behavior
-------------
This test is gated on a real Redis being reachable. If REDIS_URL is unset
or the connection probe fails, the test skips. CI must provide Redis via
``services: redis:`` for this to run.

Locally, set ``REDIS_URL=redis://localhost:6379/0`` after starting Redis.
"""
from __future__ import annotations

import contextlib
import multiprocessing as mp
import os
import time
from typing import Any

import pytest

pytestmark = pytest.mark.integration


def _redis_reachable(url: str) -> bool:
    """Probe Redis with a 1s timeout. Returns False on any failure."""
    try:
        import redis
    except ImportError:
        return False
    try:
        client = redis.from_url(url, socket_connect_timeout=1)
        return bool(client.ping())
    except Exception:  # noqa: BLE001
        return False


def _publisher_proc(
    redis_url: str,
    stream_key: str,
    skill_name: str,
    barrier_key: str,
) -> None:
    """Run in process B: wait for subscriber to be ready, then publish one
    SkillRegistered event."""
    import redis as redis_sync

    from runtime.core.nerves import SkillRegistered
    from runtime.core.nerves.redis_bus import RedisEventBus

    # Wait for subscriber to signal readiness via a regular Redis key.
    sync_client = redis_sync.from_url(redis_url)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if sync_client.get(barrier_key):
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("subscriber readiness barrier timeout")

    bus = RedisEventBus(
        redis_url=redis_url,
        stream_key=stream_key,
        consumer_group="publisher-grp",
        consumer_name="pub-0",
    )
    bus.publish(
        SkillRegistered(
            skill_name=skill_name,
            trusted_source="cross-process-e2e",
        )
    )
    # Small grace period so the async publish lands before this proc exits.
    time.sleep(0.5)


def _subscriber_proc(
    redis_url: str,
    stream_key: str,
    barrier_key: str,
    result_queue: Any,
) -> None:
    """Run in process A: subscribe, signal readiness, push received event
    name back through the queue, exit."""
    import redis as redis_sync

    from runtime.core.nerves import SkillRegistered
    from runtime.core.nerves.redis_bus import RedisEventBus

    received: list[str] = []

    def _handler(event: SkillRegistered) -> None:
        received.append(event.skill_name)

    bus = RedisEventBus(
        redis_url=redis_url,
        stream_key=stream_key,
        consumer_group="subscriber-grp",
        consumer_name="sub-0",
    )
    bus.subscribe(SkillRegistered, _handler)
    bus.start()

    # Signal that we're listening — publisher will only emit after this.
    sync_client = redis_sync.from_url(redis_url)
    sync_client.set(barrier_key, "1", ex=60)

    # Drain up to 8 seconds.
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline and not received:
        time.sleep(0.1)

    result_queue.put(list(received))


@pytest.mark.timeout(45)
def test_redis_event_bus_crosses_process_boundary() -> None:
    """A SkillRegistered emitted in proc B reaches a subscriber in proc A.

    This is the integration that takes ``Nerves`` from "in-process abstract"
    to "real distributed event bus". Without this passing, claims of
    multi-worker support are unverified.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    if not _redis_reachable(redis_url):
        pytest.skip(
            f"Redis not reachable at {redis_url}; "
            "set REDIS_URL or start a local Redis daemon. "
            "CI runs this via services: redis: in the workflow."
        )

    # Unique stream/barrier per run so parallel CI doesn't cross-pollute.
    run_id = f"{os.getpid()}-{int(time.time())}"
    stream_key = f"octopus:nerves:e2e-test:{run_id}"
    barrier_key = f"octopus:nerves:e2e-barrier:{run_id}"
    skill_name = f"e2e-skill-{run_id}"

    # spawn (not fork) so the child has a clean event-loop state on every OS.
    ctx = mp.get_context("spawn")
    result_queue: Any = ctx.Queue()

    sub = ctx.Process(
        target=_subscriber_proc,
        args=(redis_url, stream_key, barrier_key, result_queue),
        name="redis-bus-subscriber",
    )
    sub.start()

    pub = ctx.Process(
        target=_publisher_proc,
        args=(redis_url, stream_key, skill_name, barrier_key),
        name="redis-bus-publisher",
    )
    pub.start()

    # Cleanup: ensure both procs join even on assertion failure.
    try:
        pub.join(timeout=20)
        sub.join(timeout=20)

        assert pub.exitcode == 0, f"publisher proc died (exit {pub.exitcode})"
        assert sub.exitcode == 0, f"subscriber proc died (exit {sub.exitcode})"

        received = result_queue.get(timeout=5)
        assert skill_name in received, (
            f"subscriber in process A did not receive event from process B. "
            f"Got: {received}. This means RedisEventBus does NOT cross "
            f"process boundaries — Nerves is still in-process-only."
        )
    finally:
        for proc in (pub, sub):
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2)

        # Best-effort cleanup of test stream + barrier from Redis.
        with contextlib.suppress(Exception):
            import redis as redis_sync

            client = redis_sync.from_url(redis_url)
            client.delete(stream_key, barrier_key)


@pytest.mark.timeout(60)
def test_redis_event_bus_two_subscribers_two_processes() -> None:
    """Two subscriber processes both receive every published event.

    This validates the fan-out pattern: each subscriber proc is its own
    Redis consumer group, so the same stream message reaches both. If the
    bus accidentally used a shared group, only one would get each event.
    """
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    if not _redis_reachable(redis_url):
        pytest.skip(f"Redis not reachable at {redis_url}")

    run_id = f"{os.getpid()}-{int(time.time())}"
    stream_key = f"octopus:nerves:e2e-fanout:{run_id}"

    ctx = mp.get_context("spawn")
    q1: Any = ctx.Queue()
    q2: Any = ctx.Queue()
    barrier1 = f"octopus:nerves:fanout-barrier-1:{run_id}"
    barrier2 = f"octopus:nerves:fanout-barrier-2:{run_id}"

    skill_name = f"fanout-{run_id}"

    sub1 = ctx.Process(
        target=_subscriber_proc, args=(redis_url, stream_key, barrier1, q1)
    )
    sub2 = ctx.Process(
        target=_subscriber_proc, args=(redis_url, stream_key, barrier2, q2)
    )
    sub1.start()
    sub2.start()

    # Wait for BOTH subscribers ready before publishing.
    import redis as redis_sync

    client = redis_sync.from_url(redis_url)
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        if client.get(barrier1) and client.get(barrier2):
            break
        time.sleep(0.1)

    pub = ctx.Process(
        target=_publisher_proc,
        args=(redis_url, stream_key, skill_name, barrier1),
    )
    pub.start()

    try:
        pub.join(timeout=20)
        sub1.join(timeout=20)
        sub2.join(timeout=20)

        r1 = q1.get(timeout=5)
        r2 = q2.get(timeout=5)
        # Note: with separate consumer groups, both should see the event.
        # If your impl uses one shared group, this will fail and that's
        # the bug to fix.
        assert skill_name in r1, f"subscriber 1 missed event: {r1}"
        assert skill_name in r2, f"subscriber 2 missed event: {r2}"
    finally:
        for proc in (pub, sub1, sub2):
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2)
        with contextlib.suppress(Exception):
            client.delete(stream_key, barrier1, barrier2)
