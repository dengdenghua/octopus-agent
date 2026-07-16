from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from runtime.safety.evolution.behavioral_surpass_evidence import (
    ALLOWED_EXECUTION_MODES,
    BUNDLE_SCHEMA,
    REQUIRED_DOMAINS,
    compute_behavioral_surpass_evidence,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _write_valid_bundle(root: Path, now: datetime) -> Path:
    artifact_root = root / "benchmarks" / "results" / "artifacts"
    artifact_root.mkdir(parents=True)
    systems: dict[str, object] = {}
    for system_id in ("octopus", "codex"):
        cases = []
        for domain in REQUIRED_DOMAINS:
            for case_index in range(2):
                case_id = f"{domain}-{case_index}"
                artifacts = []
                for trial_index in range(3):
                    relative = (
                        Path("benchmarks")
                        / "results"
                        / "artifacts"
                        / f"{system_id}-{case_id}-{trial_index}.json"
                    )
                    content = json.dumps(
                        {
                            "schema": "octopus.behavioral_trajectory.v1",
                            "system_id": system_id,
                            "system_version": f"{system_id}-test",
                            "case_id": case_id,
                            "trial_index": trial_index,
                            "prompt_sha256": _digest(f"prompt:{case_id}"),
                            "trajectory": {
                                "trial_id": f"{system_id}-{case_id}-{trial_index}",
                                "case_id": case_id,
                                "steps": [{"kind": "text_delta", "payload": {"delta": "ok"}}],
                            },
                            "verdict": {
                                "passed": True,
                                "score": 1.0,
                                "reason": "passed",
                            },
                        },
                        sort_keys=True,
                    )
                    (root / relative).write_text(content, encoding="utf-8")
                    artifacts.append({"path": str(relative), "sha256": _digest(content)})
                cases.append(
                    {
                        "id": case_id,
                        "domain": domain,
                        "k": 3,
                        "passes": 3,
                        "trajectory_count": 3,
                        "outcome_grader": True,
                        "isolated_state": True,
                        "execution_mode": sorted(ALLOWED_EXECUTION_MODES[domain])[0],
                        "rubric_digest": _digest(f"rubric:{case_id}"),
                        "prompt_digest": _digest(f"prompt:{case_id}"),
                        "artifacts": artifacts,
                    }
                )
        systems[system_id] = {"version": f"{system_id}-test", "cases": cases}
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "suite_id": "same-task-head-to-head-v1",
        "runner_version": "test-runner-v1",
        "source_revision": "abc123",
        "generated_at": now.isoformat(),
        "systems": systems,
    }
    path = root / "benchmarks" / "results" / "behavioral-surpass-latest.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write(path: Path, payload: dict[str, object]) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_missing_bundle_never_claims_surpassed(tmp_path: Path) -> None:
    report = compute_behavioral_surpass_evidence(root=tmp_path)

    assert report["ready"] is False
    assert report["verdict"] == "missing_behavioral_evidence"
    assert next(row for row in report["checks"] if row["id"] == "bundle_present")["passed"] is False


def test_valid_fresh_same_task_bundle_certifies_behavior(tmp_path: Path) -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    _write_valid_bundle(tmp_path, now)

    report = compute_behavioral_surpass_evidence(root=tmp_path, now=now)

    assert report["ready"] is True
    assert report["verdict"] == "surpassed"
    assert report["systems"]["octopus"]["aggregate_pass_pow_k"] == 1.0
    assert report["systems"]["codex"]["aggregate_pass_pow_k"] == 1.0
    assert len(report["domains"]) == len(REQUIRED_DOMAINS)
    assert all(row["ready"] for row in report["domains"])
    assert all(row["passed"] for row in report["checks"])


def test_stale_bundle_is_not_release_evidence(tmp_path: Path) -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    _write_valid_bundle(tmp_path, now - timedelta(days=31))

    report = compute_behavioral_surpass_evidence(root=tmp_path, now=now)

    assert report["ready"] is False
    assert report["verdict"] == "stale_behavioral_evidence"


def test_different_rubric_is_not_a_head_to_head_comparison(tmp_path: Path) -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    path = _write_valid_bundle(tmp_path, now)
    bundle = _load(path)
    systems = bundle["systems"]
    assert isinstance(systems, dict)
    codex = systems["codex"]
    assert isinstance(codex, dict)
    cases = codex["cases"]
    assert isinstance(cases, list)
    cases[0]["rubric_digest"] = _digest("different-rubric")
    _write(path, bundle)

    report = compute_behavioral_surpass_evidence(root=tmp_path, now=now)

    assert report["ready"] is False
    assert next(row for row in report["checks"] if row["id"] == "same_cases")["passed"] is False


def test_different_prompt_is_not_a_head_to_head_comparison(tmp_path: Path) -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    path = _write_valid_bundle(tmp_path, now)
    bundle = _load(path)
    systems = bundle["systems"]
    assert isinstance(systems, dict)
    codex = systems["codex"]
    assert isinstance(codex, dict)
    cases = codex["cases"]
    assert isinstance(cases, list)
    cases[0]["prompt_digest"] = _digest("different-prompt")
    _write(path, bundle)

    report = compute_behavioral_surpass_evidence(root=tmp_path, now=now)

    assert report["ready"] is False
    assert next(row for row in report["checks"] if row["id"] == "same_cases")["passed"] is False


def test_tampered_trajectory_artifact_fails_digest_gate(tmp_path: Path) -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    path = _write_valid_bundle(tmp_path, now)
    bundle = _load(path)
    systems = bundle["systems"]
    assert isinstance(systems, dict)
    octopus = systems["octopus"]
    assert isinstance(octopus, dict)
    cases = octopus["cases"]
    assert isinstance(cases, list)
    artifact = cases[0]["artifacts"][0]
    (tmp_path / artifact["path"]).write_text("tampered", encoding="utf-8")

    report = compute_behavioral_surpass_evidence(root=tmp_path, now=now)

    assert report["ready"] is False
    assert (
        next(row for row in report["checks"] if row["id"] == "artifacts_verified")["passed"]
        is False
    )
    assert any("digest mismatch" in error for error in report["errors"])


def test_reused_trajectory_does_not_count_as_repeated_trials(tmp_path: Path) -> None:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    path = _write_valid_bundle(tmp_path, now)
    bundle = _load(path)
    systems = bundle["systems"]
    assert isinstance(systems, dict)
    octopus = systems["octopus"]
    assert isinstance(octopus, dict)
    cases = octopus["cases"]
    assert isinstance(cases, list)
    cases[0]["artifacts"][1] = dict(cases[0]["artifacts"][0])
    _write(path, bundle)

    report = compute_behavioral_surpass_evidence(root=tmp_path, now=now)

    assert report["ready"] is False
    assert (
        next(row for row in report["checks"] if row["id"] == "artifacts_verified")["passed"]
        is False
    )
    assert any("reuses trajectory artifact paths" in error for error in report["errors"])
