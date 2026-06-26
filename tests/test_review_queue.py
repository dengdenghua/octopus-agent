from __future__ import annotations

import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.platform.io.atomic import _cross_process_lock


def _review(task_id: str = "turn-1") -> dict:
    return {
        "schema": "octopus.task_run_review.v1",
        "task_id": task_id,
        "thread_id": "thread-1",
        "turn_id": task_id,
        "agent_id": "agent-a",
        "status": "failed",
        "learning_candidates": [
            {
                "kind": "failure_pattern",
                "priority": "P0",
                "memory_bucket": "experience",
                "title": "Tool failure pattern: exec_shell",
                "text": "Add preflight validation before retrying exec_shell.",
            }
        ],
        "backlog_candidates": [
            {
                "priority": "P1",
                "experiment": "Create deterministic replay case",
                "hypothesis": "A replay case prevents repeating this failure.",
                "minimal_implementation": "Convert replay.steps into a fixture.",
                "validation_metric": "Replay passes before prompt changes land.",
            }
        ],
    }


def _execution_policy(tmp_path: Path, backend: str) -> dict:
    return {
        "schema": "octopus.execution_policy.v1",
        "sandbox_requested": True,
        "workspace": str(tmp_path),
        "cwd": str(tmp_path),
        "backend": backend,
        "hard": backend != "direct",
        "allow_network": False,
        "env_mode": "allowlist",
        "process_group": True,
        "process_tree_kill": True,
        "timeout_s": 60,
        "raw_output": "not copied",
    }


def _review_with_execution_policy(
    tmp_path: Path,
    *,
    backend: str = "seatbelt",
    task_id: str = "turn-1",
) -> dict:
    policy = _execution_policy(tmp_path, backend)
    return {
        **_review(task_id),
        "replay": {
            "schema": "octopus.task_run_replay.v1",
            "case_id": "task-run:abc",
            "fingerprint": "abc",
            "replayable": True,
            "step_count": 1,
            "steps": [{"kind": "verifier_result", "execution_policies": [policy]}],
        },
        "findings": [
            {
                "type": "tool_error",
                "evidence": {"execution_policies": [policy]},
            }
        ],
        "resume": {
            "available": True,
            "latest_checkpoint": {
                "id": "loop-run:1",
                "state": {
                    "last_verifier": {"execution_policies": [policy]},
                    "recent_tool_calls": [{"execution_policies": [policy]}],
                },
                "integrity": {
                    "resume_safe": True,
                    "continue_from_iteration": 2,
                },
            },
        },
    }


def test_review_queue_adds_review_candidates(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")

    result = queue.add_from_task_run_review(
        _review(),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )
    rows = queue.items()

    assert result["created"] == 2
    assert result["updated"] == 0
    assert rows["total"] == 2
    assert {item["target_bucket"] for item in rows["items"]} == {
        "experience",
        "experiment_backlog",
    }
    assert all(item["status"] == "pending" for item in rows["items"])
    assert rows["items"][0]["priority"] == "P0"


def test_review_queue_deduplicates_without_overwriting(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")

    queue.add_from_task_run_review(
        _review("turn-1"),
        now=datetime(2026, 6, 7, 1, 0, tzinfo=UTC),
    )
    result = queue.add_from_task_run_review(
        _review("turn-2"),
        now=datetime(2026, 6, 8, 1, 0, tzinfo=UTC),
    )
    rows = queue.items()["items"]

    assert result["created"] == 0
    assert result["updated"] == 2
    assert len(rows) == 2
    assert all(item["occurrences"] == 2 for item in rows)
    assert all(item["created_at"].startswith("2026-06-07") for item in rows)
    assert all(item["last_seen_at"].startswith("2026-06-08") for item in rows)
    assert all(item["source_task_ids"] == ["turn-1", "turn-2"] for item in rows)


def test_review_queue_carries_deduplicated_execution_policy_evidence(
    tmp_path: Path,
) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add_from_task_run_review(_review_with_execution_policy(tmp_path))
    item = queue.items(target_bucket="experience")["items"][0]

    policies = item["metadata"]["execution_policies"]
    assert len(policies) == 1
    assert policies[0]["backend"] == "seatbelt"
    assert policies[0]["process_tree_kill"] is True
    assert "raw_output" not in policies[0]


def test_review_queue_merges_execution_policy_evidence_on_dedup(
    tmp_path: Path,
) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")

    queue.add_from_task_run_review(
        _review_with_execution_policy(tmp_path, backend="seatbelt", task_id="turn-seatbelt")
    )
    queue.add_from_task_run_review(
        _review_with_execution_policy(tmp_path, backend="direct", task_id="turn-direct")
    )

    item = queue.items(target_bucket="experience")["items"][0]
    policies = item["metadata"]["execution_policies"]
    assert item["occurrences"] == 2
    assert {policy["backend"] for policy in policies} == {"seatbelt", "direct"}


def test_review_queue_decisions_change_status(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add_from_task_run_review(_review())
    item_id = queue.items(target_bucket="experience")["items"][0]["id"]

    result = queue.decide(
        item_id,
        action="promoted",
        reason="This should become a guardrail.",
        promoted_to="rule_candidate",
        now=datetime(2026, 6, 7, 2, 0, tzinfo=UTC),
    )

    item = result["item"]
    assert item["status"] == "promoted"
    assert item["promoted_to"] == "rule_candidate"
    assert item["decision_reason"] == "This should become a guardrail."
    assert item["decided_at"].startswith("2026-06-07T02:00:00")
    assert queue.summary()["pending_count"] == 1
    assert queue.summary()["by_status"] == {"pending": 1, "promoted": 1}


def test_review_queue_filters_and_rejects_bad_decisions(tmp_path: Path) -> None:
    queue = ReviewQueue(tmp_path / "review_queue.json")
    queue.add_from_task_run_review(_review())
    item_id = queue.items(priority="P1")["items"][0]["id"]

    queue.decide(item_id, action="rejected", reason="Not worth running.")

    assert queue.items(status="pending")["total"] == 1
    assert queue.items(status="rejected")["total"] == 1
    assert queue.items(source_task_id="turn-1")["total"] == 2
    with pytest.raises(ValueError):
        queue.decide(item_id, action="unknown")
    with pytest.raises(KeyError):
        queue.decide("missing", action="archived")


def test_review_queue_write_lock_serializes_cross_process_writers(tmp_path: Path) -> None:
    path = tmp_path / "review_queue.json"
    started = tmp_path / "child-started"
    done = tmp_path / "child-done"
    script = f"""
from pathlib import Path
from runtime.memory.learning.review_queue import ReviewQueue

Path({str(started)!r}).write_text("started", encoding="utf-8")
ReviewQueue({str(path)!r}).upsert_item(
    source="child",
    source_kind="test",
    candidate_kind="test",
    priority="P1",
    target_bucket="experience",
    title="Child write",
    text="Cross-process write should wait for the store lock.",
)
Path({str(done)!r}).write_text("done", encoding="utf-8")
"""

    with _cross_process_lock(path.parent / f"{path.name}.rw"):
        child = subprocess.Popen([sys.executable, "-c", script])
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert started.exists()
        time.sleep(0.2)
        assert done.exists() is False
        assert child.poll() is None

    child.wait(timeout=5)
    assert child.returncode == 0
    assert done.exists()
    assert ReviewQueue(path).items()["total"] == 1
