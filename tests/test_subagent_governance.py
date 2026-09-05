from __future__ import annotations

import sqlite3
from pathlib import Path

from runtime.execution.subagents.governance import SubagentGovernanceStore


def test_usage_is_idempotent_and_survives_store_restart(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "governance.db"
    monkeypatch.setenv("OCTOPUS_MAX_SUBAGENT_TOKENS_PER_ROOT", "100")
    monkeypatch.setenv("OCTOPUS_MAX_SUBAGENT_COST_USD_PER_ROOT", "5")
    first = SubagentGovernanceStore(path)

    row = first.record_usage(
        "turn-1",
        usage_id="call-1",
        session_id="session-1",
        task_id="task-1",
        iteration=1,
        model="test",
        input_tokens=40,
        output_tokens=10,
        cost_usd=0.25,
    )
    duplicate = first.record_usage(
        "turn-1",
        usage_id="call-1",
        input_tokens=40,
        output_tokens=10,
        cost_usd=0.25,
    )
    restarted = SubagentGovernanceStore(path).snapshot("turn-1")

    assert row["usage_recorded"] is True
    assert duplicate["usage_recorded"] is False
    assert restarted["tokens_used"] == 50
    assert restarted["cost_usd"] == 0.25
    assert restarted["breaker"] == "open"


def test_actual_usage_trips_root_breaker_and_refuses_future_spawn(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OCTOPUS_MAX_SUBAGENT_TOKENS_PER_ROOT", "60")
    monkeypatch.setenv("OCTOPUS_MAX_SUBAGENT_COST_USD_PER_ROOT", "5")
    store = SubagentGovernanceStore(tmp_path / "governance.db")

    snapshot = store.record_usage(
        "turn-1",
        usage_id="provider-call-1",
        input_tokens=55,
        output_tokens=10,
        cost_usd=0.1,
    )

    assert snapshot["tokens_used"] == 65
    assert snapshot["breaker"] == "tripped"
    assert snapshot["trip_reason"] == "token_limit"
    assert (
        store.acquire("turn-1", depth=1, global_limit=64, root_limit=16, owner_id="worker-2")
        is None
    )
    # The circuit is isolated to one root; a later human turn is unaffected.
    assert store.acquire("turn-2", depth=1, global_limit=64, root_limit=16, owner_id="worker-2")


def test_durable_leases_enforce_cross_worker_subtree_limit(tmp_path: Path) -> None:
    path = tmp_path / "governance.db"
    worker_a = SubagentGovernanceStore(path)
    worker_b = SubagentGovernanceStore(path)

    lease = worker_a.acquire("turn-1", depth=1, global_limit=10, root_limit=1, owner_id="worker-a")

    assert lease is not None
    assert (
        worker_b.acquire("turn-1", depth=2, global_limit=10, root_limit=1, owner_id="worker-b")
        is None
    )
    assert worker_a.release(str(lease["lease_id"])) is True
    assert worker_b.acquire("turn-1", depth=2, global_limit=10, root_limit=1, owner_id="worker-b")


def test_expired_process_lease_recovers_after_restart(tmp_path: Path) -> None:
    path = tmp_path / "governance.db"
    first = SubagentGovernanceStore(path)
    lease = first.acquire("turn-1", depth=1, global_limit=1, root_limit=1, owner_id="dead-worker")
    assert lease is not None
    with sqlite3.connect(path) as conn:
        conn.execute(
            "UPDATE subagent_governance_leases SET expires_at=? WHERE lease_id=?",
            ("2000-01-01T00:00:00+00:00", lease["lease_id"]),
        )
    restarted = SubagentGovernanceStore(path)
    recovered = restarted.acquire(
        "turn-2", depth=1, global_limit=1, root_limit=1, owner_id="new-worker"
    )
    assert recovered is not None


def test_cost_can_trip_breaker_when_token_volume_is_small(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_MAX_SUBAGENT_TOKENS_PER_ROOT", "100000")
    monkeypatch.setenv("OCTOPUS_MAX_SUBAGENT_COST_USD_PER_ROOT", "0.5")
    store = SubagentGovernanceStore(tmp_path / "governance.db")

    snapshot = store.record_usage(
        "turn-1",
        usage_id="expensive-call",
        input_tokens=1,
        output_tokens=1,
        cost_usd=0.75,
    )

    assert snapshot["breaker"] == "tripped"
    assert snapshot["trip_reason"] == "cost_limit"
