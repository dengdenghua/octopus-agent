from __future__ import annotations

import json

import pytest

from benchmarks.behavioral_suite import load_behavioral_suite
from benchmarks.eval_harness import Verdict, run_suite


def test_load_behavioral_suite_binds_outcome_grader(tmp_path) -> None:
    manifest = tmp_path / "suite.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "octopus.behavioral_surpass_suite.v1",
                "suite_id": "test-suite",
                "cases": [
                    {
                        "id": "exact",
                        "domain": "general_runtime_and_coding",
                        "execution_mode": "real_provider",
                        "prompt": "say hello",
                        "rubric": {"grader": "exact_text", "expected": "hello"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    cases = load_behavioral_suite(
        manifest,
        grader_factories={
            "exact_text": lambda rubric: (
                lambda trajectory: Verdict(
                    passed=trajectory.last_text() == rubric["expected"],
                    score=1.0 if trajectory.last_text() == rubric["expected"] else 0.0,
                    reason="exact text",
                    rubric=rubric,
                )
            )
        },
    )
    report = run_suite(
        cases,
        runner=lambda _prompt: iter([{"kind": "text_delta", "delta": "hello"}]),
        k=3,
    )

    assert report.aggregate_pass_pow_k == 1.0
    assert cases[0].metadata["outcome_grader"] is True
    assert len(cases[0].metadata["rubric_digest"]) == 64


def test_load_behavioral_suite_refuses_missing_grader(tmp_path) -> None:
    manifest = tmp_path / "suite.json"
    manifest.write_text(
        json.dumps(
            {
                "schema": "octopus.behavioral_surpass_suite.v1",
                "suite_id": "test-suite",
                "cases": [
                    {
                        "id": "ungraded",
                        "domain": "general_runtime_and_coding",
                        "execution_mode": "real_provider",
                        "prompt": "do work",
                        "rubric": {"grader": "missing"},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="no grader factory"):
        load_behavioral_suite(manifest, grader_factories={})
