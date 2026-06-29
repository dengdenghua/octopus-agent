"""Security regression tests for parallel_agents_router ownership enforcement.

These pin the ownership model added to ParallelAgentOrchestrator. Before
this fix, any authenticated user could read, cancel, or stream any other
user's batches/tasks. The orchestrator now stamps ``owner_id`` on each
batch, and endpoints enforce caller-owns-batch checks.

See parallel_agents_router.py ``_require_batch_owner`` + orchestrator.py
``_BatchEntry.owner_id``.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.execution.parallel_agents.orchestrator import (  # noqa: E402
    ParallelAgentOrchestrator,
)
from runtime.safety.auth.identity import Identity, IdentityStore  # noqa: E402
from runtime.sensing.gateway.parallel_agents_router import (  # noqa: E402
    create_parallel_agents_router,
)


def _build_app(
    task_runner: Callable[..., str] | None = None,
) -> tuple[TestClient, dict[str, str]]:
    """Build app with require_auth=True + 3 identities (alice, bob, carol).

    ``task_runner`` is forwarded to the orchestrator; when ``None`` the
    orchestrator falls back to its stub runner (unchanged behavior).
    Tests that need deterministic task timing — e.g. cancellation —
    inject a controllable runner here.
    """
    store = IdentityStore()
    keys: dict[str, str] = {}
    for actor in ("alice", "bob", "carol"):
        api_key = f"sk-test-{actor}"
        store.add(Identity(actor_id=actor), api_key_plaintext=api_key)
        keys[actor] = api_key

    orchestrator = ParallelAgentOrchestrator(task_runner=task_runner)
    app = FastAPI()
    app.include_router(
        create_parallel_agents_router(
            orchestrator=orchestrator,
            identity_store=store,
            require_auth=True,
        )
    )
    client = TestClient(app)
    # Expose orchestrator so tests can directly check internal state
    client.orchestrator = orchestrator  # type: ignore[attr-defined]
    return client, keys


def _bearer(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}"}


def _dispatch_batch(
    client: TestClient,
    keys: dict[str, str],
    owner: str,
) -> str:
    """Dispatch a trivial batch and return batch_id."""
    resp = client.post(
        "/api/agents/parallel/dispatch",
        json={
            "tasks": [{"description": f"task by {owner}", "subagent_name": "general-purpose"}],
        },
        headers=_bearer(keys[owner]),
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()["batch_id"]


def _task_statuses(
    orch: ParallelAgentOrchestrator,
    batch_id: str,
) -> list[str]:
    """Current per-task statuses for a batch, via the public read API."""
    batch = orch.get_batch(batch_id)
    return [t.status for t in batch.results] if batch is not None else []


def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout: float = 3.0,
    interval: float = 0.01,
) -> bool:
    """Poll ``predicate`` until it is truthy or ``timeout`` elapses.

    Returns the final value so callers can ``assert`` on it. Used to wait
    out the *asynchronous*, cooperative cancellation path (cancel_all sets
    a cancel_event; the runner thread converges the task to a terminal
    state shortly after).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return bool(predicate())


# ── dispatch stamps owner_id ────────────────────────────────────────


def test_dispatch_stamps_owner() -> None:
    """The orchestrator batch entry should have owner_id == actor."""
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")
    orch: ParallelAgentOrchestrator = client.orchestrator  # type: ignore[attr-defined]
    owner = orch.get_batch_owner(batch_id)
    assert owner == "alice"


# ── get_batch: only owner can read ─────────────────────────────────


def test_get_batch_blocks_non_owner() -> None:
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")

    # bob can't read alice's batch
    resp = client.get(
        f"/api/agents/parallel/batch/{batch_id}",
        headers=_bearer(keys["bob"]),
    )
    assert resp.status_code == 403
    assert "not the owner" in resp.json()["detail"]


def test_get_batch_allows_owner() -> None:
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")

    resp = client.get(
        f"/api/agents/parallel/batch/{batch_id}",
        headers=_bearer(keys["alice"]),
    )
    assert resp.status_code == 200
    assert resp.json()["batch_id"] == batch_id


def test_recovery_snapshot_blocks_non_owner() -> None:
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")

    resp = client.get(
        f"/api/agents/parallel/batch/{batch_id}/recovery-snapshot",
        headers=_bearer(keys["bob"]),
    )
    assert resp.status_code == 403
    assert "not the owner" in resp.json()["detail"]


def test_recovery_snapshot_allows_owner() -> None:
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")

    resp = client.get(
        f"/api/agents/parallel/batch/{batch_id}/recovery-snapshot",
        headers=_bearer(keys["alice"]),
    )
    assert resp.status_code == 200
    assert resp.json()["batch_id"] == batch_id
    assert resp.json()["safety"]["owner_id_included"] is False


# ── cancel_task: only owner can cancel ─────────────────────────────


def test_cancel_task_blocks_non_owner() -> None:
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")
    batch = client.get(
        f"/api/agents/parallel/batch/{batch_id}",
        headers=_bearer(keys["alice"]),
    ).json()
    task_id = batch["results"][0]["task_id"]

    # bob tries to cancel alice's task
    resp = client.post(
        f"/api/agents/parallel/cancel/{task_id}",
        headers=_bearer(keys["bob"]),
    )
    assert resp.status_code == 403


def test_cancel_task_allows_owner() -> None:
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")
    batch = client.get(
        f"/api/agents/parallel/batch/{batch_id}",
        headers=_bearer(keys["alice"]),
    ).json()
    task_id = batch["results"][0]["task_id"]

    resp = client.post(
        f"/api/agents/parallel/cancel/{task_id}",
        headers=_bearer(keys["alice"]),
    )
    # Might be 200 if still pending, or 404 if already running/done —
    # both are fine, we just need to confirm alice wasn't 403'd.
    assert resp.status_code in (200, 404)


# ── cancel_all: only cancels caller's own batches ──────────────────


def test_cancel_all_scoped_to_caller() -> None:
    """cancel_all cancels ONLY the caller's batches; others' are untouched.

    Timing is made deterministic with a cooperative *blocking* runner:
    every task parks in ``running`` until its ``cancel_event`` fires, so

      * bob's task travels the running→cancelled path and lands on exactly
        ``cancelled`` (it can never race to ``completed``), and
      * alice's task stays ``running`` — proving bob's cancel_all did not
        bleed across the ownership boundary.

    This pins the real product behavior: cancel_all cooperatively aborts
    the *caller's* running tasks and is scoped per owner. The previous
    version asserted a terminal status without waiting for the async
    cancel to land, which raced the still-running task → deterministic
    red. Note that running tasks are cancelled *cooperatively* (the runner
    must honor ``cancel_event``); cancel_all does not force-kill threads.
    """
    stop = threading.Event()

    def blocking_runner(
        description: str,
        *,
        subagent_name: str,
        context: object = None,
        cancel_event: object = None,
    ) -> str:
        # Park until cancelled (cooperative) — never self-complete, so a
        # task is only ever ``cancelled``, never racing to ``completed``.
        # ``stop`` is the teardown escape hatch (see finally) so alice's
        # never-cancelled task can drain instead of spinning forever.
        while True:
            if cancel_event is not None and cancel_event.is_set():
                return ""
            if stop.is_set():
                return "drained"
            time.sleep(0.005)

    client, keys = _build_app(task_runner=blocking_runner)
    orch: ParallelAgentOrchestrator = client.orchestrator  # type: ignore[attr-defined]
    try:
        alice_batch = _dispatch_batch(client, keys, "alice")
        bob_batch = _dispatch_batch(client, keys, "bob")

        # Ensure bob's task is actually RUNNING before cancel, so we
        # exercise the cooperative running→cancelled path (not just the
        # trivial pending→cancelled one).
        assert _wait_until(
            lambda: "running" in _task_statuses(orch, bob_batch)
        ), "bob's task never reached running"

        # bob calls cancel_all.
        resp = client.post(
            "/api/agents/parallel/cancel-all",
            headers=_bearer(keys["bob"]),
        )
        assert resp.status_code == 200

        # bob's task converges to terminal once the cooperative cancel
        # lands (async — hence the wait).
        assert _wait_until(
            lambda: all(
                s in ("cancelled", "completed", "failed", "timed_out")
                for s in _task_statuses(orch, bob_batch)
            )
        ), "bob's batch never reached terminal after cancel_all"

        bob_view = client.get(
            f"/api/agents/parallel/batch/{bob_batch}",
            headers=_bearer(keys["bob"]),
        ).json()
        assert bob_view["results"], "expected at least one task in bob's batch"
        # STRONG assertion: cancel_all actually CANCELLED — not the vacuous
        # "any terminal state". The blocking runner can only terminate via
        # cancel, so every task must be exactly ``cancelled``.
        for task in bob_view["results"]:
            assert task["status"] == "cancelled", task

        # ── SCOPING (the security property this file exists to pin) ──
        # alice's batch is untouched by bob's cancel_all: readable AND no
        # task of hers was cancelled.
        resp = client.get(
            f"/api/agents/parallel/batch/{alice_batch}",
            headers=_bearer(keys["alice"]),
        )
        assert resp.status_code == 200
        alice_view = resp.json()
        assert alice_view["results"], "expected at least one task in alice's batch"
        for task in alice_view["results"]:
            assert task["status"] != "cancelled", task
    finally:
        # Release alice's parked task and tear the pool down so no worker
        # thread spins past the test.
        stop.set()
        orch.shutdown(wait=False)


# ── stream: only owner can subscribe ───────────────────────────────


def test_stream_blocks_non_owner() -> None:
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")

    # bob tries to stream alice's batch
    resp = client.get(
        f"/api/agents/parallel/stream/{batch_id}",
        headers=_bearer(keys["bob"]),
    )
    assert resp.status_code == 403


# ── unauthenticated callers are blocked ────────────────────────────


def test_no_auth_token_returns_401() -> None:
    client, keys = _build_app()
    batch_id = _dispatch_batch(client, keys, "alice")

    resp = client.get(f"/api/agents/parallel/batch/{batch_id}")
    assert resp.status_code == 401


# ── status is intentionally actor-agnostic ─────────────────────────


def test_status_is_actor_agnostic() -> None:
    """``GET /api/agents/parallel/status`` returns aggregate counts
    across all users. Intentionally actor-agnostic — pinned here so
    a future audit doesn't accidentally lock it down."""
    client, keys = _build_app()
    _dispatch_batch(client, keys, "alice")
    _dispatch_batch(client, keys, "bob")

    # carol (who owns no batches) can still see aggregate status
    resp = client.get(
        "/api/agents/parallel/status",
        headers=_bearer(keys["carol"]),
    )
    assert resp.status_code == 200
    assert resp.json()["active_count"] >= 0  # aggregate, not per-user


# ── single-user dev mode: require_auth=False bypasses checks ───────


def test_dev_mode_bypasses_ownership_checks() -> None:
    """When require_auth=False, ownership checks are skipped."""
    orchestrator = ParallelAgentOrchestrator()
    app = FastAPI()
    app.include_router(
        create_parallel_agents_router(
            orchestrator=orchestrator,
            require_auth=False,
        )
    )
    client = TestClient(app)

    # No auth header — should still work in dev mode
    resp = client.post(
        "/api/agents/parallel/dispatch",
        json={
            "tasks": [{"description": "dev task", "subagent_name": "general-purpose"}],
        },
    )
    assert resp.status_code == 200
    batch_id = resp.json()["batch_id"]

    # Anyone can read it in dev mode
    resp = client.get(f"/api/agents/parallel/batch/{batch_id}")
    assert resp.status_code == 200


# ── legacy unowned batches are visible to everyone ─────────────────


def test_legacy_unowned_batches_visible_to_all() -> None:
    """Batches with owner_id=None (created before ownership tracking
    was added, or manually set) are visible to everyone. This ensures
    backward compat with existing state."""
    client, keys = _build_app()
    orch: ParallelAgentOrchestrator = client.orchestrator  # type: ignore[attr-defined]

    # Directly dispatch a batch with owner_id=None (legacy mode)
    result = orch.dispatch(
        [{"description": "legacy task", "subagent_name": "general-purpose"}],
        owner_id=None,
    )
    batch_id = result.batch_id

    # alice can read it
    resp = client.get(
        f"/api/agents/parallel/batch/{batch_id}",
        headers=_bearer(keys["alice"]),
    )
    assert resp.status_code == 200

    # bob can also read it
    resp = client.get(
        f"/api/agents/parallel/batch/{batch_id}",
        headers=_bearer(keys["bob"]),
    )
    assert resp.status_code == 200
