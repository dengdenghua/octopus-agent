from __future__ import annotations

from runtime.evals.multi_agent_benchmark import run_multi_agent_benchmark


def test_multi_agent_release_benchmark_passes(tmp_path) -> None:
    result = run_multi_agent_benchmark(workspace=tmp_path)

    assert result["passed"] is True, result
    assert all(result["checks"].values())
    assert result["metrics"]["context_reduction_ratio"] >= 0.60
    assert result["metrics"]["visible_duplicate_count"] == 0
    assert result["metrics"]["second_drain_due"] == 0
    assert result["metrics"]["member_incremental_context"] == 1.0
    assert result["metrics"]["persistent_member_projection"] == 1.0
    assert result["metrics"]["member_session_serialization"] == 1.0
    assert result["metrics"]["pluggable_context_engine"] == 1.0
    assert result["metrics"]["versioned_context_engine_lifecycle"] == 1.0
    assert result["metrics"]["continuation_prompt_ordering"] == 1.0
    assert result["metrics"]["hybrid_context_diversity"] == 1.0
    assert result["metrics"]["adaptive_long_horizon_recall"] == 1.0
    assert result["metrics"]["transactional_context_lifecycle"] == 1.0
    assert result["metrics"]["durable_session_compaction"] == 1.0
    assert result["metrics"]["summary_grant_context"] == 1.0
    assert result["metrics"]["stale_goal_resurrection_guard"] == 1.0
    assert result["metrics"]["incremental_context_tokens_avoided"] > 0
