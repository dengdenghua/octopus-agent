from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
GITHUB_JOB_TIMEOUT_LIMIT_MINUTES = 360


def _ci_jobs() -> dict[str, Any]:
    workflow = yaml.safe_load((WORKFLOWS_DIR / "ci.yml").read_text(encoding="utf-8"))
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict)
    return jobs


def _steps_by_name(job: dict[str, Any]) -> dict[str, dict[str, Any]]:
    steps = job.get("steps")
    assert isinstance(steps, list)
    return {
        str(step["name"]): step
        for step in steps
        if isinstance(step, dict) and isinstance(step.get("name"), str)
    }


def _workflow_jobs() -> list[tuple[Path, str, dict[str, Any]]]:
    jobs: list[tuple[Path, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS_DIR.glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert isinstance(workflow, dict), f"{path} must contain a workflow mapping"
        raw_jobs = workflow.get("jobs")
        assert isinstance(raw_jobs, dict), f"{path} must define jobs"
        for name, raw_job in raw_jobs.items():
            assert isinstance(raw_job, dict), f"{path}: job {name!r} must be a mapping"
            jobs.append((path, str(name), raw_job))
    return jobs


def test_job_timeouts_fit_github_actions_schema() -> None:
    violations: list[str] = []
    for path, name, job in _workflow_jobs():
        timeout = job.get("timeout-minutes")
        if timeout is None:
            continue
        if not isinstance(timeout, int) or not 1 <= timeout <= GITHUB_JOB_TIMEOUT_LIMIT_MINUTES:
            violations.append(f"{path.relative_to(REPO_ROOT)}:{name}={timeout!r}")

    assert not violations, (
        "GitHub rejects jobs whose timeout-minutes is outside 1..360: " + ", ".join(violations)
    )


def test_job_environment_avoids_step_only_runner_context() -> None:
    violations: list[str] = []
    for path, name, job in _workflow_jobs():
        env = job.get("env") or {}
        assert isinstance(env, dict), f"{path}: job {name!r} env must be a mapping"
        for key, value in env.items():
            if "${{ runner." in str(value):
                violations.append(f"{path.relative_to(REPO_ROOT)}:{name}.env.{key}")

    assert not violations, (
        "runner context is unavailable in jobs.<job_id>.env; initialize these values "
        "inside a step via RUNNER_TEMP: " + ", ".join(violations)
    )


def test_ci_runs_the_complete_suite_once_and_keeps_python_312_compatibility() -> None:
    jobs = _ci_jobs()
    lint_job = jobs["lint-and-test"]
    steps = _steps_by_name(lint_job)

    full = steps["pytest (full suite with coverage)"]
    assert full["if"] == "always() && matrix.python-version == '3.11.9'"
    assert "--cov=runtime" in full["run"]
    assert "--cov=tools" not in full["run"]
    assert "--cov-fail-under=77.5" in full["run"]

    collection = steps["pytest collection compatibility (Python 3.12)"]
    assert collection["if"] == "always() && matrix.python-version == '3.12.11'"
    assert collection["run"] == "pytest --collect-only -q"

    smoke = steps["pytest compatibility smoke (Python 3.12)"]
    assert smoke["if"] == "always() && matrix.python-version == '3.12.11'"
    for representative in (
        "tests/test_config.py",
        "tests/test_cli_smoke.py",
        "tests/test_golden_path_e2e.py",
        "tests/test_react_core_path_e2e.py",
        "tests/test_openapi_snapshot.py",
    ):
        assert representative in smoke["run"]

    pytest_steps = [
        step
        for step in lint_job["steps"]
        if isinstance(step, dict) and str(step.get("run", "")).lstrip().startswith("pytest ")
    ]
    assert len(pytest_steps) == 3


def test_ci_cross_platform_lane_is_focused_on_portability_contracts() -> None:
    jobs = _ci_jobs()
    step = _steps_by_name(jobs["pytest-cross-platform"])["pytest (cross-platform subset)"]
    command = step["run"]

    assert "-m " not in command
    for portability_contract in (
        "tests/test_platform_paths.py",
        "tests/test_path_guard.py",
        "tests/test_docs_encoding.py",
        "tests/test_subprocess_backend.py",
        "tests/test_event_log_multiprocess.py",
        "tests/test_desktop_config_packaging.py",
    ):
        assert portability_contract in command
