from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.eval_harness import EvalCase
from benchmarks.system_run_seed import load_system_run_seed, merge_seed_reports


def _case() -> EvalCase:
    return EvalCase(
        id="coding.concurrent-cache",
        prompt="fixed prompt",
        grader=lambda _trajectory: True,
        metadata={
            "domain": "general_runtime_and_coding",
            "execution_mode": "real_provider",
            "outcome_grader": True,
            "isolated_state": True,
            "prompt_digest": "a" * 64,
            "rubric_digest": "b" * 64,
        },
    )


def _write_seed(root: Path, *, k: int = 3) -> Path:
    artifacts = []
    for index in range(k):
        payload = {
            "schema": "octopus.behavioral_trajectory.v1",
            "system_id": "octopus",
            "system_version": "octopus-local",
            "case_id": "coding.concurrent-cache",
            "trial_index": index,
            "prompt_sha256": "a" * 64,
            "trajectory": {
                "trial_id": f"trial-{index}",
                "case_id": "coding.concurrent-cache",
                "started_at": float(index + 1),
                "ended_at": float(index + 2),
                "error": None,
                "failure_category": None,
                "steps": [],
            },
            "verdict": {
                "passed": True,
                "score": 1.0,
                "reason": "passed",
                "rubric": {"grader": "fixture_tests"},
            },
        }
        content = json.dumps(payload, sort_keys=True).encode()
        artifact = root / f"artifact-{index}.json"
        artifact.write_bytes(content)
        artifacts.append({"path": artifact.name, "sha256": hashlib.sha256(content).hexdigest()})
    run = root / "run.json"
    run.write_text(
        json.dumps(
            {
                "schema": "octopus.behavioral_system_run.v1",
                "suite_id": "same-task-head-to-head-v1",
                "system_id": "octopus",
                "system": {
                    "version": "octopus-local",
                    "cases": [
                        {
                            "id": "coding.concurrent-cache",
                            "domain": "general_runtime_and_coding",
                            "execution_mode": "real_provider",
                            "outcome_grader": True,
                            "isolated_state": True,
                            "prompt_digest": "a" * 64,
                            "rubric_digest": "b" * 64,
                            "k": k,
                            "trajectory_count": k,
                            "passes": k,
                            "artifacts": artifacts,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    return run


def test_load_system_run_seed_reconstructs_verified_report(tmp_path: Path) -> None:
    report = load_system_run_seed(
        _write_seed(tmp_path),
        root=tmp_path,
        expected_system="octopus",
        expected_version="octopus-local",
        expected_suite_id="same-task-head-to-head-v1",
        expected_k=3,
        cases=[_case()],
    )

    assert len(report.cases) == 1
    assert report.cases[0].passes == 3
    assert report.cases[0].pass_pow_k == 1.0
    assert [trajectory.trial_id for trajectory in report.cases[0].trajectories] == [
        "trial-0",
        "trial-1",
        "trial-2",
    ]


def test_load_system_run_seed_rejects_tampered_artifact(tmp_path: Path) -> None:
    run = _write_seed(tmp_path)
    (tmp_path / "artifact-1.json").write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        load_system_run_seed(
            run,
            root=tmp_path,
            expected_system="octopus",
            expected_version="octopus-local",
            expected_suite_id="same-task-head-to-head-v1",
            expected_k=3,
            cases=[_case()],
        )


def test_load_system_run_seed_rejects_metadata_drift(tmp_path: Path) -> None:
    case = _case()
    case.metadata["rubric_digest"] = "c" * 64

    with pytest.raises(ValueError, match="rubric_digest"):
        load_system_run_seed(
            _write_seed(tmp_path),
            root=tmp_path,
            expected_system="octopus",
            expected_version="octopus-local",
            expected_suite_id="same-task-head-to-head-v1",
            expected_k=3,
            cases=[case],
        )


def test_merge_seed_reports_rejects_duplicate_cases(tmp_path: Path) -> None:
    report = load_system_run_seed(
        _write_seed(tmp_path),
        root=tmp_path,
        expected_system="octopus",
        expected_version="octopus-local",
        expected_suite_id="same-task-head-to-head-v1",
        expected_k=3,
        cases=[_case()],
    )

    with pytest.raises(ValueError, match="duplicate seeded/checkpoint case"):
        merge_seed_reports(report, report)
