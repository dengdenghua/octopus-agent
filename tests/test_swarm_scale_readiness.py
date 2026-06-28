from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.swarm_scale_readiness import (
    SwarmScaleProbeConfig,
    compute_swarm_scale_readiness,
    run_swarm_scale_probe,
)


def test_swarm_scale_probe_proves_bounded_speedup_and_failure_isolation() -> None:
    report = run_swarm_scale_probe(
        SwarmScaleProbeConfig(
            task_count=24,
            max_concurrency=6,
            sleep_seconds=0.35,
            min_speedup=2.0,
            failing_task_index=5,
        )
    )

    assert report["schema"] == "octopus.swarm_scale_probe.v1"
    assert report["ok"] is True
    assert report["task_count"] == 24
    assert report["max_active"] <= 6
    assert report["bounded_concurrency"] is True
    assert report["execution_window_seconds"] <= report["wall_seconds"]
    assert report["critical_path_speedup"] >= 2.0
    assert report["critical_path_speedup_passed"] is True
    assert report["failure_isolation"] is True
    assert report["failed_tasks"] == ["probe_005"]
    assert report["completed_count"] == 23
    assert report["observability"] is True
    assert report["event_sequences_contiguous"] is True
    assert report["batch_complete_event"] is True
    assert report["batch_metrics_ready"] is True
    assert report["batch_metrics"]["schema"] == "octopus.parallel_agent_batch_metrics.v1"
    assert report["batch_metrics"]["critical_path_speedup"] >= 2.0
    assert report["batch_metrics"]["failure_isolation"] is True


def test_swarm_scale_readiness_passes_current_repo() -> None:
    report = compute_swarm_scale_readiness(
        probe_config=SwarmScaleProbeConfig(
            task_count=24,
            max_concurrency=6,
            sleep_seconds=0.35,
            min_speedup=2.0,
        )
    )

    assert report["schema"] == "octopus.swarm_scale_readiness.v1"
    assert report["ready"] is True
    assert report["verdict"] == "pass"
    assert report["score"] == 1.0
    assert report["passed"] == report["total"]
    assert report["next_actions"] == []
    assert {
        item["id"] for item in report["capabilities"] if item["passed"]
    } >= {
        "dag_task_planning",
        "bounded_parallel_scheduler",
        "context_and_contract_shards",
        "streaming_batch_observability",
        "failure_isolation",
        "owner_scoped_cancellation",
        "large_task_queue_probe",
        "bounded_concurrency_probe",
        "critical_path_speedup_probe",
        "failure_isolation_probe",
        "observable_timeline_probe",
        "batch_metrics_probe",
    }


def test_swarm_scale_readiness_reports_missing_static_evidence(
    tmp_path: Path,
) -> None:
    report = compute_swarm_scale_readiness(root=tmp_path, include_probe=False)

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert report["score"] == 0.0
    assert report["missing_count"] == report["total"]
    assert report["next_actions"][0].startswith(
        "Add runtime/execution/parallel_agents/helpers.py"
    )
