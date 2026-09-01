from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
GITHUB_JOB_TIMEOUT_LIMIT_MINUTES = 360


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
