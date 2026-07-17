"""Tests for benchmarks/eval_harness.py."""

from __future__ import annotations

import hashlib
import json

from benchmarks.eval_harness import (
    EvalCase,
    Trajectory,
    Verdict,
    run_case,
    run_suite,
    run_suite_by_case,
    write_behavioral_bundle,
    write_behavioral_system_evidence,
)


def _mock_runner_echo(prompt: str):
    """Yield a single text_delta echoing the prompt."""
    yield {"kind": "text_delta", "delta": prompt}


def _mock_runner_with_tool(prompt: str):
    yield {"kind": "tool_start", "tool_name": "list_files"}
    yield {"kind": "tool_end", "tool_name": "list_files", "status": "success"}
    yield {"kind": "text_delta", "delta": "done"}


def _mock_runner_flaky(prompt: str):
    """Succeed half the time (uses a counter on a func attribute)."""
    n = getattr(_mock_runner_flaky, "_n", 0)
    _mock_runner_flaky._n = n + 1
    if n % 2 == 0:
        yield {"kind": "text_delta", "delta": "ok"}
    else:
        yield {"kind": "text_delta", "delta": "fail"}


def test_run_case_passes_when_grader_returns_true() -> None:
    case = EvalCase(
        id="echo",
        prompt="hello",
        grader=lambda t: "hello" in t.last_text(),
    )
    result = run_case(case, runner=_mock_runner_echo, k=3)
    assert result.passes == 3
    assert result.pass_at_k == 1.0
    assert result.pass_pow_k == 1.0
    assert result.avg_score == 1.0


def test_run_case_partial_credit() -> None:
    case = EvalCase(
        id="partial",
        prompt="x",
        grader=lambda t: Verdict(passed=False, score=0.5, reason="halfway"),
    )
    result = run_case(case, runner=_mock_runner_echo, k=2)
    assert result.passes == 0
    assert result.avg_score == 0.5


def test_trajectory_tool_names() -> None:
    case = EvalCase(
        id="tool",
        prompt="x",
        grader=lambda t: "list_files" in t.tool_names(),
    )
    result = run_case(case, runner=_mock_runner_with_tool, k=1)
    assert result.passes == 1


def test_pass_at_k_vs_pow_k_diverge_on_flaky() -> None:
    _mock_runner_flaky._n = 0  # reset counter
    case = EvalCase(
        id="flaky",
        prompt="x",
        grader=lambda t: t.last_text() == "ok",
    )
    result = run_case(case, runner=_mock_runner_flaky, k=4)
    # 2 of 4 pass under the modulo — pass@k should hit 1.0, pass^k 0.0
    assert result.passes == 2
    assert result.pass_at_k == 1.0
    assert result.pass_pow_k == 0.0


def test_suite_aggregates() -> None:
    cases = [
        EvalCase(id="a", prompt="hello", grader=lambda t: "hello" in t.last_text()),
        EvalCase(id="b", prompt="world", grader=lambda t: "world" in t.last_text()),
        EvalCase(id="c", prompt="x", grader=lambda t: False),
    ]
    report = run_suite(cases, runner=_mock_runner_echo, k=2)
    assert len(report.cases) == 3
    # 2 of 3 cases all-pass → 2/3
    assert abs(report.aggregate_pass_pow_k - 2 / 3) < 1e-9
    summary = report.summary()
    assert "pass@k" in summary
    assert "pass^k" in summary


def test_suite_can_select_a_runner_per_case() -> None:
    cases = [
        EvalCase(id="a", prompt="ignored", grader=lambda t: t.last_text() == "a"),
        EvalCase(id="b", prompt="ignored", grader=lambda t: t.last_text() == "b"),
    ]

    report = run_suite_by_case(
        cases,
        runner_factory=lambda case: (
            lambda _prompt: iter([{"kind": "text_delta", "delta": case.id}])
        ),
        k=3,
    )

    assert report.aggregate_pass_pow_k == 1.0
    assert [result.passes for result in report.cases] == [3, 3]


def test_setup_failure_recorded() -> None:
    def bad_setup() -> None:
        raise RuntimeError("env broken")

    case = EvalCase(
        id="bad",
        prompt="x",
        setup=bad_setup,
        grader=lambda t: True,
    )
    result = run_case(case, runner=_mock_runner_echo, k=1)
    assert result.passes == 0
    assert "setup failed" in (result.trajectories[0].error or "")


def test_grader_observes_state_before_teardown() -> None:
    state = {"value": "missing"}
    case = EvalCase(
        id="lifecycle",
        prompt="x",
        setup=lambda: state.update(value="ready"),
        grader=lambda _trajectory: state["value"] == "ready",
        teardown=lambda: state.update(value="removed"),
    )

    result = run_case(case, runner=_mock_runner_echo, k=1)

    assert result.passes == 1
    assert state["value"] == "removed"


def test_grader_exception_becomes_failed_trajectory() -> None:
    def broken_grader(_trajectory):
        raise RuntimeError("verifier unavailable")

    result = run_case(
        EvalCase(id="grader-error", prompt="x", grader=broken_grader),
        runner=_mock_runner_echo,
        k=1,
    )

    assert result.passes == 0
    assert result.verdicts[0].reason == "grader raised: verifier unavailable"
    assert result.trajectories[0].error == "grader raised: verifier unavailable"


def test_runner_exception_captured() -> None:
    def bad_runner(prompt: str):
        yield {"kind": "text_delta", "delta": "starting"}
        raise RuntimeError("blew up")

    case = EvalCase(id="boom", prompt="x", grader=lambda t: not t.error)
    result = run_case(case, runner=bad_runner, k=1)
    assert result.passes == 0
    assert "blew up" in (result.trajectories[0].error or "")
    assert "blew up" in result.verdicts[0].reason


def test_runner_error_event_fails_with_structured_reason() -> None:
    case = EvalCase(id="error-event", prompt="go", grader=lambda _traj: True)

    result = run_case(
        case,
        runner=lambda _prompt: iter(
            [{"kind": "error", "error": {"type": "timeout", "timeout_seconds": 30}}]
        ),
        k=1,
    )

    assert result.passes == 0
    assert result.trajectories[0].error is not None
    assert '"type": "timeout"' in result.verdicts[0].reason


def test_report_serialises_to_json(tmp_path) -> None:
    case = EvalCase(id="x", prompt="hello", grader=lambda t: True)
    report = run_suite([case], runner=_mock_runner_echo, k=2)
    out = tmp_path / "report.json"
    report.write_json(out)
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert '"pass_at_k"' in text
    assert '"aggregate_pass_at_k"' in text
    data = json.loads(text)
    assert data["cases"][0]["trajectories"][0]["steps"][0] == {
        "kind": "text_delta",
        "payload": {"delta": "hello"},
        "ts": data["cases"][0]["trajectories"][0]["steps"][0]["ts"],
    }


def test_writes_digest_verified_behavioral_system_evidence(tmp_path) -> None:
    rubric_digest = hashlib.sha256(b"exact output rubric").hexdigest()
    case = EvalCase(
        id="general.echo",
        prompt="hello",
        grader=lambda trajectory: Verdict(
            passed=trajectory.last_text() == "hello",
            score=1.0,
            reason="exact output",
            rubric={"expected": "hello"},
        ),
        metadata={
            "domain": "general_runtime_and_coding",
            "execution_mode": "real_provider",
            "outcome_grader": True,
            "isolated_state": True,
            "rubric_digest": rubric_digest,
        },
    )
    report = run_suite([case], runner=_mock_runner_echo, k=3)

    system = write_behavioral_system_evidence(
        report,
        [case],
        root=tmp_path,
        system_id="octopus",
        version="test-version",
    )

    assert system["version"] == "test-version"
    assert system["cases"][0]["passes"] == 3
    assert system["cases"][0]["trajectory_count"] == 3
    assert system["cases"][0]["prompt_digest"] == hashlib.sha256(b"hello").hexdigest()
    artifacts = system["cases"][0]["artifacts"]
    assert len(artifacts) == 3
    for artifact in artifacts:
        content = (tmp_path / artifact["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"]

    bundle_path = tmp_path / "benchmarks" / "results" / "bundle.json"
    manifest_path = tmp_path / "benchmarks" / "behavioral-surpass-suite.json"
    manifest_path.write_text(
        json.dumps({"suite_id": "same-task-v1", "cases": []}),
        encoding="utf-8",
    )
    write_behavioral_bundle(
        path=bundle_path,
        suite_manifest_path=manifest_path,
        suite_id="same-task-v1",
        runner_version="test-runner",
        source_revision="abc123",
        generated_at="2026-07-17T00:00:00+00:00",
        systems={"octopus": system, "codex": system},
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    assert bundle["schema"] == "octopus.behavioral_surpass_bundle.v1"
    assert bundle["suite_manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert bundle["systems"]["octopus"]["cases"][0]["rubric_digest"] == rubric_digest


def test_trajectory_runtime_ms_positive() -> None:
    t = Trajectory(trial_id="t", case_id="c")
    import time as _time

    _time.sleep(0.01)
    t.ended_at = _time.time()
    assert t.runtime_ms() >= 10.0
