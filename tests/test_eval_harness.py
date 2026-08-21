"""Tests for benchmarks/eval_harness.py."""

from __future__ import annotations

import hashlib
import json

import pytest

from benchmarks.eval_harness import (
    CaseResult,
    EvalCase,
    SuiteReport,
    Trajectory,
    Verdict,
    resumable_report,
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


def test_trajectory_tool_names_unwraps_octopus_command_execution() -> None:
    trajectory = Trajectory(trial_id="t", case_id="case")
    trajectory.append(
        "tool_start",
        tool_name="command_execution",
        item={"type": "commandExecution", "command": "browser_navigate"},
    )
    trajectory.append(
        "tool_start",
        tool_name="command_execution",
        item={"type": "command_execution", "command": "python -m pytest"},
    )

    assert trajectory.tool_names() == ["browser_navigate", "command_execution"]


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


def test_infrastructure_error_is_not_eligible_for_behavioral_evidence(tmp_path) -> None:
    case = EvalCase(
        id="provider-down",
        prompt="go",
        grader=lambda _trajectory: True,
        metadata={
            "domain": "general_runtime_and_coding",
            "execution_mode": "real_provider",
            "outcome_grader": True,
            "isolated_state": True,
            "rubric_digest": hashlib.sha256(b"rubric").hexdigest(),
        },
    )
    result = run_case(
        case,
        runner=lambda _prompt: iter(
            [
                {
                    "kind": "infrastructure_error",
                    "error": {
                        "type": "infrastructure",
                        "category": "provider_unavailable",
                    },
                }
            ]
        ),
        k=1,
    )
    report = SuiteReport(cases=[result])

    assert result.has_infrastructure_failure is True
    with pytest.raises(ValueError, match="cannot score infrastructure failures"):
        write_behavioral_system_evidence(
            report,
            [case],
            root=tmp_path,
            system_id="octopus",
            version="test",
        )


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
    restored = SuiteReport.from_dict(data)
    assert restored.cases[0].passes == 2
    assert restored.cases[0].trajectories[0].last_text() == "hello"


def test_run_suite_by_case_resumes_only_complete_cases() -> None:
    cases = [
        EvalCase(id="first", prompt="one", grader=lambda trajectory: bool(trajectory.last_text())),
        EvalCase(id="second", prompt="two", grader=lambda trajectory: bool(trajectory.last_text())),
    ]
    initial = run_suite_by_case(cases[:1], runner_factory=lambda _case: _mock_runner_echo, k=2)
    created: list[str] = []
    checkpoints: list[int] = []

    def runner_factory(case: EvalCase):
        created.append(case.id)
        return _mock_runner_echo

    report = run_suite_by_case(
        cases,
        runner_factory=runner_factory,
        k=2,
        initial_report=initial,
        case_complete=lambda current: checkpoints.append(len(current.cases)),
    )

    assert [result.case_id for result in report.cases] == ["first", "second"]
    assert created == ["second"]
    assert checkpoints == [2, 2]


def test_run_suite_by_case_resumes_partial_case_trials() -> None:
    case = EvalCase(
        id="partial",
        prompt="one",
        grader=lambda trajectory: bool(trajectory.last_text()),
    )
    partial = run_case(case, runner=_mock_runner_echo, k=1)
    partial.k = 3
    checkpoints: list[int] = []

    report = run_suite_by_case(
        [case],
        runner_factory=lambda _case: _mock_runner_echo,
        k=3,
        initial_report=SuiteReport(cases=[partial]),
        case_complete=lambda current: checkpoints.append(len(current.cases[0].trajectories)),
    )

    assert report.cases[0].passes == 3
    assert len(report.cases[0].trajectories) == 3
    assert checkpoints == [2, 3]


def test_run_suite_by_case_rejects_incomplete_checkpoint() -> None:
    initial = SuiteReport(
        cases=[CaseResult(case_id="first", k=2, passes=0)],
    )
    case = EvalCase(id="first", prompt="one", grader=lambda _trajectory: True)

    with pytest.raises(ValueError, match="non-resumable checkpoint case"):
        run_suite_by_case(
            [case],
            runner_factory=lambda _case: _mock_runner_echo,
            k=2,
            initial_report=initial,
        )


def test_resumable_report_keeps_healthy_trials_before_infrastructure_failure() -> None:
    healthy = Trajectory(trial_id="case.0", case_id="case")
    healthy.ended_at = healthy.started_at + 1
    failed = Trajectory(
        trial_id="case.1",
        case_id="case",
        error="transport failed",
        failure_category="infrastructure",
    )
    failed.ended_at = failed.started_at + 1
    report = SuiteReport(
        cases=[
            CaseResult(
                case_id="case",
                k=3,
                passes=1,
                trajectories=[healthy, failed],
                verdicts=[Verdict(passed=True), Verdict(passed=False)],
            )
        ]
    )

    resumable = resumable_report(report)

    assert len(resumable.cases) == 1
    assert resumable.cases[0].passes == 1
    assert [trial.trial_id for trial in resumable.cases[0].trajectories] == ["case.0"]
    assert resumable.infrastructure_failures == []


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
    provenance = {
        "schema": "octopus.behavioral_system_provenance.v1",
        "system_id": "octopus",
        "model": {"expected": "approved-model", "requested": "approved-model"},
        "config": {"expected_sha256": "a" * 64, "observed_sha256": "a" * 64},
    }

    system = write_behavioral_system_evidence(
        report,
        [case],
        root=tmp_path,
        system_id="octopus",
        version="test-version",
        provenance=provenance,
    )

    assert system["version"] == "test-version"
    assert system["provenance"] == provenance
    assert len(system["provenance_sha256"]) == 64
    assert system["cases"][0]["passes"] == 3
    assert system["cases"][0]["trajectory_count"] == 3
    assert system["cases"][0]["prompt_digest"] == hashlib.sha256(b"hello").hexdigest()
    artifacts = system["cases"][0]["artifacts"]
    assert len(artifacts) == 3
    for artifact in artifacts:
        content = (tmp_path / artifact["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == artifact["sha256"]
        assert json.loads(content)["system_provenance_sha256"] == system["provenance_sha256"]

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
    assert bundle["schema"] == "octopus.behavioral_surpass_bundle.v2"
    assert bundle["suite_manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert bundle["systems"]["octopus"]["cases"][0]["rubric_digest"] == rubric_digest


def test_trajectory_runtime_ms_positive() -> None:
    t = Trajectory(trial_id="t", case_id="c")
    import time as _time

    _time.sleep(0.01)
    t.ended_at = _time.time()
    assert t.runtime_ms() >= 10.0
