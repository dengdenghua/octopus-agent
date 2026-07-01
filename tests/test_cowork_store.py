"""Tests for runtime.memory.cowork.store."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from runtime.memory.cowork import CoworkStore, Task
from runtime.memory.cowork.store import (
    PHASE_COMPLETE,
    PHASE_FAILED,
    PHASE_PLAN,
    PHASE_SYNTHESIZE,
    PHASE_WORK,
)

# ─── Fixtures ───────────────────────────────────────────────


@pytest.fixture
def store(tmp_path: Path) -> CoworkStore:
    return CoworkStore(base_dir=tmp_path / "cowork")


def _sample_tasks() -> list[Task]:
    return [
        Task(id="t1", title="Research", description="Find papers"),
        Task(id="t2", title="Draft", description="Write outline"),
    ]


# ─── 1. create_plan writes plan.json atomically ─────────────


def test_create_plan_writes_plan_json_atomically(store: CoworkStore, tmp_path: Path) -> None:
    plan = store.create_plan(
        session_id="sess-1",
        created_by="agent-A",
        tasks=_sample_tasks(),
    )

    assert plan.session_id == "sess-1"
    assert plan.created_by == "agent-A"
    assert plan.phase == PHASE_PLAN
    assert len(plan.tasks) == 2

    # Look up the on-disk file via the store's own session-hash logic
    plan_path = store._plan_path("sess-1")
    assert plan_path.exists()
    # No leftover temp file from atomic_write_json next to it.
    siblings = list(plan_path.parent.iterdir())
    tmp_siblings = [p for p in siblings if p.name.startswith(f".{plan_path.name}.tmp-")]
    assert tmp_siblings == [], f"orphan temp files: {tmp_siblings}"

    # Round-trip via read_plan recovers the same payload.
    re_read = store.read_plan("sess-1")
    assert re_read is not None
    assert re_read.session_id == "sess-1"
    assert {t.id for t in re_read.tasks} == {"t1", "t2"}


def test_create_plan_rejects_unsafe_task_id(store: CoworkStore, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid task_id"):
        store.create_plan(
            session_id="sess-unsafe-task",
            created_by="agent-A",
            tasks=[{"id": "../escape", "title": "bad"}],
        )

    assert not (tmp_path / "escape.json").exists()


# ─── 2. read_plan returns None for unknown session ──────────


def test_read_plan_returns_none_for_unknown_session(
    store: CoworkStore,
) -> None:
    assert store.read_plan("never-created") is None


# ─── 3. Invalid phase transition raises ValueError ──────────


def test_invalid_phase_transition_raises(store: CoworkStore) -> None:
    store.create_plan(
        session_id="sess-3",
        created_by="agent-A",
        tasks=_sample_tasks(),
    )
    # plan → work is fine
    store.advance_phase("sess-3", PHASE_WORK)
    # work → plan must fail (going backwards)
    with pytest.raises(ValueError):
        store.advance_phase("sess-3", PHASE_PLAN)

    # Shortcut to a terminal state then verify nothing escapes it.
    store.advance_phase("sess-3", PHASE_FAILED)
    with pytest.raises(ValueError):
        store.advance_phase("sess-3", PHASE_PLAN)
    with pytest.raises(ValueError):
        store.advance_phase("sess-3", PHASE_WORK)

    # Fresh session, walk to complete and check complete → plan fails.
    store.create_plan(
        session_id="sess-3b",
        created_by="agent-A",
        tasks=_sample_tasks(),
    )
    store.advance_phase("sess-3b", PHASE_WORK)
    store.advance_phase("sess-3b", PHASE_SYNTHESIZE)
    store.write_artifact("sess-3b", "__final__", "agent-A", {"summary": "done"})
    store.advance_phase("sess-3b", PHASE_COMPLETE)
    with pytest.raises(ValueError):
        store.advance_phase("sess-3b", PHASE_PLAN)


def test_stale_synthesis_fails_with_diagnostic_artifact(store: CoworkStore) -> None:
    store.create_plan(
        session_id="sess-stale-synth",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    store.advance_phase("sess-stale-synth", PHASE_WORK)
    store.advance_phase("sess-stale-synth", PHASE_SYNTHESIZE)

    assert (
        store.fail_stale_synthesis(
            "sess-stale-synth",
            max_age_seconds=0,
            reason="test synth timeout",
        )
        is True
    )

    plan = store.read_plan("sess-stale-synth")
    assert plan is not None
    assert plan.phase == PHASE_FAILED
    final = store.read_artifacts("sess-stale-synth")["__final__"]
    assert final["agent_id"] == "system"
    assert final["output"]["reason"] == "test synth timeout"


def test_stale_synthesis_is_not_failed_when_final_exists(store: CoworkStore) -> None:
    store.create_plan(
        session_id="sess-final-exists",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    store.advance_phase("sess-final-exists", PHASE_WORK)
    store.advance_phase("sess-final-exists", PHASE_SYNTHESIZE)
    store.write_artifact("sess-final-exists", "__final__", "agent-A", {"summary": "done"})

    assert store.fail_stale_synthesis("sess-final-exists", max_age_seconds=0) is False
    plan = store.read_plan("sess-final-exists")
    assert plan is not None
    assert plan.phase == PHASE_SYNTHESIZE


# ─── 4. claim_task: same task only succeeds once ────────────


def test_claim_task_returns_true_only_once(store: CoworkStore) -> None:
    store.create_plan(
        session_id="sess-4",
        created_by="agent-A",
        tasks=_sample_tasks(),
    )
    # First claim wins.
    assert store.claim_task("sess-4", "t1", "agent-A") is True
    # Second claim, even from a different agent, is rejected.
    assert store.claim_task("sess-4", "t1", "agent-B") is False
    # Same agent re-claiming also returns False (idempotent at bool).
    assert store.claim_task("sess-4", "t1", "agent-A") is False


# ─── 5. Concurrent claim: exactly one winner ────────────────


def test_concurrent_claim_exactly_one_winner(store: CoworkStore) -> None:
    store.create_plan(
        session_id="sess-5",
        created_by="coord",
        tasks=_sample_tasks(),
    )

    # Use a barrier so all 4 threads attempt to claim at very nearly
    # the same instant. Without the barrier the GIL may serialize
    # them so trivially that the test no longer exercises the
    # race condition we care about.
    barrier = threading.Barrier(4)
    results: list[bool] = []
    results_lock = threading.Lock()

    def claimant(agent_id: str) -> None:
        barrier.wait()
        won = store.claim_task("sess-5", "t1", agent_id)
        with results_lock:
            results.append(won)

    threads = [threading.Thread(target=claimant, args=(f"agent-{i}",)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert sum(1 for r in results if r is True) == 1, results
    assert sum(1 for r in results if r is False) == 3, results

    # Assignments file is well-formed and shows exactly one entry.
    assigns = store.read_assignments("sess-5")
    assert "t1" in assigns
    assert assigns["t1"].agent_id.startswith("agent-")


# ─── 6. write_artifact creates file + updates assignment ────


def test_write_artifact_creates_file_and_updates_assignment(
    store: CoworkStore,
) -> None:
    store.create_plan(
        session_id="sess-6",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    assert store.claim_task("sess-6", "t1", "agent-A") is True

    artifact_path = store.write_artifact(
        session_id="sess-6",
        task_id="t1",
        agent_id="agent-A",
        output={"finding": "42"},
    )

    assert artifact_path.exists()
    assert artifact_path.name == "t1.json"

    # Assignment now reflects done + artifact_ref pointing at the
    # relative path under the session dir.
    assigns = store.read_assignments("sess-6")
    a = assigns["t1"]
    assert a.status == "done"
    assert a.artifact_ref == "artifacts/t1.json"
    assert a.completed_at is not None


def test_write_artifact_rejects_unsafe_task_id(store: CoworkStore, tmp_path: Path) -> None:
    store.create_plan(
        session_id="sess-artifact-unsafe",
        created_by="coord",
        tasks=_sample_tasks(),
    )

    with pytest.raises(ValueError, match="invalid task_id"):
        store.write_artifact("sess-artifact-unsafe", "../escape", "agent-A", {"bad": True})

    assert not (store._artifacts_dir("sess-artifact-unsafe").parent / "escape.json").exists()
    assert not (tmp_path / "escape.json").exists()


def test_write_artifact_rejects_symlinked_artifacts_dir(store: CoworkStore, tmp_path: Path) -> None:
    store.create_plan(
        session_id="sess-artifact-symlink",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    outside = tmp_path / "outside-artifacts"
    outside.mkdir()
    artifacts = store._artifacts_dir("sess-artifact-symlink")
    artifacts.parent.mkdir(parents=True, exist_ok=True)
    try:
        artifacts.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    with pytest.raises(ValueError, match="escapes cowork session directory"):
        store.write_artifact("sess-artifact-symlink", "t1", "agent-A", {"bad": True})

    assert not (outside / "t1.json").exists()


def test_assignment_terminal_status_is_not_overwritten_by_late_failure(
    store: CoworkStore,
) -> None:
    store.create_plan(
        session_id="sess-terminal-done",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    assert store.claim_task("sess-terminal-done", "t1", "agent-A") is True
    assert store.update_assignment_status("sess-terminal-done", "t1", "done") is True
    done = store.read_assignments("sess-terminal-done")["t1"]

    assert store.update_assignment_status("sess-terminal-done", "t1", "failed") is False

    stored = store.read_assignments("sess-terminal-done")["t1"]
    assert stored.status == "done"
    assert stored.completed_at == done.completed_at


def test_assignment_terminal_failure_is_not_overwritten_by_late_success(
    store: CoworkStore,
) -> None:
    store.create_plan(
        session_id="sess-terminal-failed",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    assert store.claim_task("sess-terminal-failed", "t1", "agent-A") is True
    assert store.update_assignment_status("sess-terminal-failed", "t1", "failed") is True
    failed = store.read_assignments("sess-terminal-failed")["t1"]

    assert (
        store.update_assignment_status(
            "sess-terminal-failed",
            "t1",
            "done",
            artifact_ref="artifacts/t1.json",
        )
        is False
    )

    stored = store.read_assignments("sess-terminal-failed")["t1"]
    assert stored.status == "failed"
    assert stored.artifact_ref is None
    assert stored.completed_at == failed.completed_at


def test_assignment_done_status_allows_idempotent_artifact_ref_backfill(
    store: CoworkStore,
) -> None:
    store.create_plan(
        session_id="sess-terminal-backfill",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    assert store.claim_task("sess-terminal-backfill", "t1", "agent-A") is True
    assert store.update_assignment_status("sess-terminal-backfill", "t1", "done") is True
    done = store.read_assignments("sess-terminal-backfill")["t1"]

    assert (
        store.update_assignment_status(
            "sess-terminal-backfill",
            "t1",
            "done",
            artifact_ref="artifacts/t1.json",
        )
        is True
    )

    stored = store.read_assignments("sess-terminal-backfill")["t1"]
    assert stored.status == "done"
    assert stored.artifact_ref == "artifacts/t1.json"
    assert stored.completed_at == done.completed_at


# ─── 7. read_artifacts returns all artifacts for a session ──


def test_read_artifacts_returns_all_for_session(
    store: CoworkStore,
) -> None:
    store.create_plan(
        session_id="sess-7",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    store.claim_task("sess-7", "t1", "agent-A")
    store.claim_task("sess-7", "t2", "agent-B")

    store.write_artifact("sess-7", "t1", "agent-A", {"k": "v1"})
    store.write_artifact("sess-7", "t2", "agent-B", {"k": "v2"})

    arts = store.read_artifacts("sess-7")
    assert set(arts.keys()) == {"t1", "t2"}
    assert arts["t1"]["output"] == {"k": "v1"}
    assert arts["t2"]["output"] == {"k": "v2"}
    assert arts["t1"]["agent_id"] == "agent-A"
    assert arts["t2"]["agent_id"] == "agent-B"


def test_read_artifacts_ignores_symlinked_artifacts_dir(store: CoworkStore, tmp_path: Path) -> None:
    store.create_plan(
        session_id="sess-read-artifact-symlink",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    outside = tmp_path / "outside-read"
    outside.mkdir()
    (outside / "t1.json").write_text(
        '{"task_id":"t1","agent_id":"external","output":{"leak":true}}',
        encoding="utf-8",
    )
    artifacts = store._artifacts_dir("sess-read-artifact-symlink")
    artifacts.parent.mkdir(parents=True, exist_ok=True)
    try:
        artifacts.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")

    assert store.read_artifacts("sess-read-artifact-symlink") == {}


# ─── 8. Sessions are isolated ───────────────────────────────


def test_sessions_are_isolated(store: CoworkStore) -> None:
    store.create_plan(
        session_id="sess-A",
        created_by="coord",
        tasks=[Task(id="ta", title="only-A")],
    )
    store.create_plan(
        session_id="sess-B",
        created_by="coord",
        tasks=[Task(id="tb", title="only-B")],
    )

    plan_a = store.read_plan("sess-A")
    plan_b = store.read_plan("sess-B")
    assert plan_a is not None and plan_b is not None
    assert {t.id for t in plan_a.tasks} == {"ta"}
    assert {t.id for t in plan_b.tasks} == {"tb"}

    # Claim in A, B's slot stays empty.
    store.claim_task("sess-A", "ta", "agent-A")
    assert "ta" in store.read_assignments("sess-A")
    assert store.read_assignments("sess-B") == {}

    # Artifact in A, B's artifact dir stays empty.
    store.write_artifact("sess-A", "ta", "agent-A", {"v": 1})
    assert "ta" in store.read_artifacts("sess-A")
    assert store.read_artifacts("sess-B") == {}


# ─── 9. advance_phase(work) fails when plan has 0 tasks ─────


def test_advance_to_work_fails_with_zero_tasks(store: CoworkStore) -> None:
    store.create_plan(
        session_id="sess-9",
        created_by="coord",
        tasks=[],  # empty
    )
    with pytest.raises(ValueError, match="0 tasks"):
        store.advance_phase("sess-9", PHASE_WORK)


# ─── 10. list_sessions returns all stored session IDs ───────


def test_list_sessions_returns_all_stored(store: CoworkStore) -> None:
    assert store.list_sessions() == []

    store.create_plan(
        session_id="alpha",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    store.create_plan(
        session_id="beta",
        created_by="coord",
        tasks=_sample_tasks(),
    )
    store.create_plan(
        session_id="gamma",
        created_by="coord",
        tasks=_sample_tasks(),
    )

    assert store.list_sessions() == ["alpha", "beta", "gamma"]
