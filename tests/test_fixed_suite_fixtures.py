from __future__ import annotations

from pathlib import Path

from benchmarks.eval_harness import Trajectory, run_suite_by_case
from benchmarks.fixed_suite_fixtures import (
    _trajectory_requirement,
    prepare_coding_fixture_suite,
    prepare_fixture_suite,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_coding_fixed_suite_is_executable_and_fails_on_starters(tmp_path) -> None:
    prepared = prepare_coding_fixture_suite(
        repo_root=REPO_ROOT,
        runs_root=tmp_path / "runs",
    )

    report = run_suite_by_case(
        prepared.cases,
        runner_factory=lambda _case: (
            lambda _prompt: iter([{"kind": "text_delta", "delta": "no changes"}])
        ),
        k=1,
    )

    assert {case.id for case in prepared.cases} == {
        "coding.concurrent-cache",
        "coding.path-boundary",
    }
    assert report.aggregate_pass_pow_k == 0.0
    assert all(result.verdicts[0].reason for result in report.cases)
    assert all(not any(path.iterdir()) for path in (tmp_path / "runs").iterdir())


def test_all_implemented_fixed_fixtures_fail_closed_on_starters(tmp_path) -> None:
    prepared = prepare_fixture_suite(
        repo_root=REPO_ROOT,
        runs_root=tmp_path / "all-runs",
    )

    report = run_suite_by_case(
        prepared.cases,
        runner_factory=lambda _case: (
            lambda _prompt: iter([{"kind": "text_delta", "delta": "no changes"}])
        ),
        k=1,
    )

    assert len(prepared.cases) == 14
    assert report.aggregate_pass_pow_k == 0.0
    assert all(result.passes == 0 for result in report.cases)


def test_sensitive_cases_require_behavioral_trajectory_evidence() -> None:
    parallel = Trajectory(trial_id="parallel", case_id="multiagent.parallel-evidence")
    assert _trajectory_requirement("multiagent.parallel-evidence", parallel)
    for _ in range(3):
        parallel.append("tool_start", tool_name="subagent")
    # The outcome grader, rather than an Octopus-specific bb_* tool name,
    # validates the shared workspace handoff for cross-client comparisons.
    assert _trajectory_requirement("multiagent.parallel-evidence", parallel) is None

    denied = Trajectory(trial_id="denied", case_id="security.denied-destructive-action")
    assert _trajectory_requirement("security.denied-destructive-action", denied)
    denied.append(
        "approval_request",
        method="item/commandExecution/requestApproval",
    )
    assert _trajectory_requirement("security.denied-destructive-action", denied) is None

    resume = Trajectory(trial_id="resume", case_id="memory.context-reset-resume")
    resume.append("phase_start", phase_index=1)
    assert _trajectory_requirement("memory.context-reset-resume", resume)
    resume.append("phase_start", phase_index=2)
    assert _trajectory_requirement("memory.context-reset-resume", resume) is None


def test_browser_cases_require_real_ui_tool_trajectories() -> None:
    crud = Trajectory(trial_id="crud", case_id="browser.dynamic-crud")
    assert _trajectory_requirement("browser.dynamic-crud", crud)
    crud.append("tool_start", tool_name="browser_navigate")
    # Select controls can be changed through click semantics; two explicit
    # type actions plus four clicks are still a real UI trajectory.
    for _ in range(2):
        crud.append("tool_start", tool_name="browser_type")
    for _ in range(4):
        crud.append("tool_start", tool_name="browser_click")
    crud.append("tool_start", tool_name="browser_get")
    assert _trajectory_requirement("browser.dynamic-crud", crud) is None

    editor = Trajectory(trial_id="editor", case_id="browser.rich-editor-upload")
    assert _trajectory_requirement("browser.rich-editor-upload", editor)
    editor.append("tool_start", tool_name="browser_navigate")
    editor.append("tool_start", tool_name="browser_type")
    editor.append("tool_start", tool_name="live_browser_type")
    editor.append("tool_start", tool_name="browser_upload")
    editor.append("tool_start", tool_name="browser_click")
    editor.append("tool_start", tool_name="browser_wait")
    assert _trajectory_requirement("browser.rich-editor-upload", editor) is None
