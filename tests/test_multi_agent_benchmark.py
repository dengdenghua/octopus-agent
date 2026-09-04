from __future__ import annotations

from runtime.evals.multi_agent_benchmark import run_multi_agent_benchmark


def test_multi_agent_release_benchmark_passes(tmp_path) -> None:
    result = run_multi_agent_benchmark(workspace=tmp_path)

    assert result["passed"] is True, result
    assert all(result["checks"].values())
    assert result["metrics"]["context_reduction_ratio"] >= 0.60
    assert result["metrics"]["visible_duplicate_count"] == 0
    assert result["metrics"]["second_drain_due"] == 0

