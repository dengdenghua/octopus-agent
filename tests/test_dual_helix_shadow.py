import asyncio
from pathlib import Path

import pytest

from runtime.safety.evolution.dual_helix_policy import decide_shadow_trigger
from runtime.safety.evolution.dual_helix_shadow import (
    DualHelixShadowService,
    materialize_shadow_snapshot,
    parse_shadow_review,
)


def test_snapshot_is_bounded_and_excludes_credentials_and_dependencies(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "app.py").write_text("print('ok')", encoding="utf-8")
    (source / ".env").write_text("SECRET=never-copy", encoding="utf-8")
    (source / "node_modules").mkdir()
    (source / "node_modules" / "large.js").write_text("ignored", encoding="utf-8")

    snapshot = materialize_shadow_snapshot(source, tmp_path / "shadow")

    assert (snapshot / "app.py").exists()
    assert not (snapshot / ".env").exists()
    assert not (snapshot / "node_modules").exists()


@pytest.mark.asyncio
async def test_opt_in_shadow_run_uses_opposite_engine_on_isolated_snapshot(
    tmp_path: Path,
) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "main.py").write_text("value = 1", encoding="utf-8")
    calls: list[tuple[str, Path, str]] = []

    async def codex_runner(goal: str, workspace: Path, output: str) -> str:
        calls.append((goal, workspace, output))
        assert workspace != source
        assert (workspace / "main.py").exists()
        return "PASS: verified in read-only snapshot"

    service = DualHelixShadowService(
        tmp_path / "state.json",
        tmp_path / "snapshots",
        allowed_workspace_root=source,
        codex_runner=codex_runner,
        native_runner=codex_runner,
    )
    with pytest.raises(PermissionError):
        service.queue(
            goal="review task",
            primary_engine="octopus",
            primary_output="done",
        )

    service.set_enabled(True)
    queued = service.queue(
        goal="review task",
        primary_engine="octopus",
        primary_output="done",
        source_thread_id="thread-1",
        source_message_id="answer-1",
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        row = next(item for item in service.status()["runs"] if item["run_id"] == queued["run_id"])
        if row["status"] in {"completed", "failed"}:
            break

    assert row["status"] == "completed"
    assert row["shadow_engine"] == "codex"
    assert row["source_thread_id"] == "thread-1"
    assert row["source_message_id"] == "answer-1"
    assert row["result"].startswith("PASS")
    assert row["verdict"] == "pass"
    assert row["hard_gates"] == {"legacy_review_verdict": True}
    assert len(calls) == 1


def test_rejects_workspace_outside_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    allowed.mkdir()
    outside.mkdir()
    service = DualHelixShadowService(
        tmp_path / "state.json",
        tmp_path / "snapshots",
        allowed_workspace_root=allowed,
    )
    service.set_enabled(True)
    with pytest.raises(ValueError, match="outside"):
        service.queue(
            goal="review",
            primary_engine="codex",
            primary_output="",
            workspace_path=str(outside),
        )


def test_structured_shadow_review_cannot_pass_with_a_failed_hard_gate() -> None:
    review = parse_shadow_review(
        '{"verdict":"pass","hard_gates":{"correctness":true,"safety":false},'
        '"evidence":["unsafe write"],"recommendations":["remove write"]}'
    )
    assert review["verdict"] == "fail"
    assert review["hard_gates"]["safety"] is False


def test_structured_shadow_review_accepts_fenced_json() -> None:
    review = parse_shadow_review(
        "```json\n"
        '{"verdict":"pass","hard_gates":{"correctness":true,"verification":true},'
        '"evidence":["tests passed"],"recommendations":[]}\n'
        "```"
    )
    assert review["verdict"] == "pass"
    assert review["evidence"] == ["tests passed"]


def test_shadow_policy_is_disabled_and_risk_gated() -> None:
    assert decide_shadow_trigger(auto_enabled=False, risk_level="critical").to_wire() == {
        "should_trigger": False,
        "reason": "disabled",
        "signals": [],
    }
    decision = decide_shadow_trigger(
        auto_enabled=True,
        risk_level="high",
        failure_count=2,
        confidence=0.4,
    )
    assert decision.should_trigger is True
    assert decision.reason == "high_risk"
    assert decision.signals == ("high_risk", "repeated_failure", "low_confidence")
    assert decide_shadow_trigger(auto_enabled=True, risk_level="medium").reason == "ordinary_task"


@pytest.mark.asyncio
async def test_automatic_shadow_requires_flag_and_risk_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from runtime.platform import feature_flags

    source = tmp_path / "workspace"
    source.mkdir()
    service = DualHelixShadowService(
        tmp_path / "state.json",
        tmp_path / "snapshots",
        allowed_workspace_root=source,
        codex_runner=lambda *_args: _shadow_runner(),
        native_runner=lambda *_args: _shadow_runner(),
    )
    service.set_enabled(True)

    monkeypatch.setattr(feature_flags, "is_on", lambda _name: False)
    with pytest.raises(PermissionError, match="automatic shadow trigger denied: disabled"):
        service.queue(
            goal="ordinary task",
            primary_engine="octopus",
            primary_output="done",
            automatic=True,
        )

    monkeypatch.setattr(feature_flags, "is_on", lambda _name: True)
    queued = service.queue(
        goal="repeated failure task",
        primary_engine="octopus",
        primary_output="done",
        automatic=True,
        failure_count=2,
    )
    assert queued["trigger"] == "repeated_failure"
    assert queued["trigger_signals"] == ["repeated_failure"]


async def _shadow_runner() -> str:
    return '{"verdict":"pass","hard_gates":{"correctness":true}}'
