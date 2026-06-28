from __future__ import annotations

from pathlib import Path

from runtime.safety.evolution.repo_context_readiness import (
    compute_repo_context_readiness,
    run_repo_context_probe,
)


def test_repo_context_probe_covers_identifier_cjk_and_sources() -> None:
    report = run_repo_context_probe()

    assert report["schema"] == "octopus.repo_context_probe.v1"
    assert report["ok"] is True
    assert report["english_identifier_retrieval"] is True
    assert report["cjk_bigram_retrieval"] is True
    assert report["source_sink_fidelity"] is True
    assert report["dirty_worktree_awareness"] is True
    assert report["dirty_worktree_probe"]["schema"] == "octopus.repo_dirty_worktree_probe.v1"
    assert report["dirty_worktree_probe"]["protected_user_changes"] is True
    assert report["dirty_worktree_probe"]["staged_count"] >= 1
    assert report["dirty_worktree_probe"]["unstaged_count"] >= 1
    assert report["dirty_worktree_probe"]["untracked_count"] >= 1
    assert report["english_sources"] == [
        {"kind": "doc", "title": "Tool engine execution", "path": "tool-engine.md"}
    ]
    assert report["chinese_sources"] == [
        {"kind": "doc", "title": "Resume keyword optimizer", "path": "resume-cn.md"}
    ]


def test_repo_context_readiness_passes_current_repo() -> None:
    report = compute_repo_context_readiness()

    assert report["schema"] == "octopus.repo_context_readiness.v1"
    assert report["ready"] is True
    assert report["verdict"] == "pass"
    assert report["score"] == 1.0
    assert report["passed"] == report["total"]
    assert report["next_actions"] == []
    assert {
        item["id"] for item in report["capabilities"] if item["passed"]
    } >= {
        "hybrid_wiki_retrieval",
        "shared_codebase_grounding",
        "react_loop_grounding",
        "planner_grounding",
        "working_set_resume",
        "memory_quality_recall",
        "english_identifier_probe",
        "cjk_bigram_probe",
        "source_sink_probe",
        "dirty_worktree_probe",
    }


def test_repo_context_readiness_reports_missing_static_evidence(
    tmp_path: Path,
) -> None:
    report = compute_repo_context_readiness(root=tmp_path, include_probe=False)

    assert report["ready"] is False
    assert report["verdict"] == "review"
    assert report["score"] == 0.0
    assert report["missing_count"] == report["total"]
    assert report["next_actions"][0].startswith(
        "Add runtime/memory/hemolymph/repo_context.py"
    )
