"""audit.ultracode orchestration bus — grant, scrub, and progress streaming.

Three wires make the preset real end to end:
1. ``ultracode_token_budget()`` — the SERVER-side spawn-budget grant.
2. ``_apply_orchestration_grant`` — the gateway scrubs any client-supplied
   ``orchestration_token_budget`` (spawn-budget escalation) and grants the
   server value only for the ``audit.ultracode`` preset.
3. ``orchestration_progress_scope`` — ``run_orchestration`` phase lines
   stream to the client as thinking deltas instead of one opaque blob.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.execution.suckers import delegation_budget as db
from runtime.execution.suckers import delegation_skills as ds
from runtime.sensing.gateway.realtime_react_stream import _apply_orchestration_grant


@pytest.fixture(autouse=True)
def _reset_budget_state():
    from runtime.execution.subagents.bridge import (
        set_sub_agent_runner,
        set_subagent_registry,
    )

    db._TURN_DELEGATIONS.clear()
    db._TURN_FAILED_FINGERPRINTS.clear()
    set_sub_agent_runner(None)
    set_subagent_registry(None)
    yield
    db._TURN_DELEGATIONS.clear()
    db._TURN_FAILED_FINGERPRINTS.clear()
    set_sub_agent_runner(None)
    set_subagent_registry(None)


# ── ultracode_token_budget resolution chain ──────────────────────


def test_ultracode_budget_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCTOPUS_ULTRACODE_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("OCTOPUS_ORCH_TOKEN_BUDGET", raising=False)
    assert db.ultracode_token_budget() == db.ULTRACODE_TOKEN_BUDGET_DEFAULT


def test_ultracode_budget_operator_env_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCTOPUS_ULTRACODE_TOKEN_BUDGET", raising=False)
    monkeypatch.setenv("OCTOPUS_ORCH_TOKEN_BUDGET", "77000")
    assert db.ultracode_token_budget() == 77000


def test_ultracode_budget_preset_env_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OCTOPUS_ULTRACODE_TOKEN_BUDGET", "550000")
    monkeypatch.setenv("OCTOPUS_ORCH_TOKEN_BUDGET", "77000")
    assert db.ultracode_token_budget() == 550000


def test_ultracode_budget_invalid_env_falls_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_ULTRACODE_TOKEN_BUDGET", "not-a-number")
    monkeypatch.delenv("OCTOPUS_ORCH_TOKEN_BUDGET", raising=False)
    assert db.ultracode_token_budget() == db.ULTRACODE_TOKEN_BUDGET_DEFAULT


# ── gateway grant + client scrub ─────────────────────────────────


def test_grant_scrubs_client_supplied_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    # A client smuggling the trusted key is a spawn-budget escalation —
    # it must vanish even when no preset is active.
    meta: dict[str, Any] = {"orchestration_token_budget": 10_000_000}
    _apply_orchestration_grant(meta)
    assert "orchestration_token_budget" not in meta


def test_grant_applied_for_ultracode_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OCTOPUS_ULTRACODE_TOKEN_BUDGET", raising=False)
    monkeypatch.delenv("OCTOPUS_ORCH_TOKEN_BUDGET", raising=False)
    meta: dict[str, Any] = {
        "workflow_preset": "audit.ultracode",
        # client tries to pick its own number — the server value wins
        "orchestration_token_budget": 10_000_000,
    }
    _apply_orchestration_grant(meta)
    assert meta["orchestration_token_budget"] == db.ULTRACODE_TOKEN_BUDGET_DEFAULT


def test_no_grant_for_other_presets() -> None:
    meta: dict[str, Any] = {"workflow_preset": "codex.plan"}
    _apply_orchestration_grant(meta)
    assert "orchestration_token_budget" not in meta


# ── progress streaming ───────────────────────────────────────────


def _fake_parallel_seq(rounds_outputs: list[list[str]]):
    calls = {"i": 0}

    def fake(specs: Any = None, **_kw: Any) -> dict[str, Any]:
        idx = calls["i"]
        calls["i"] += 1
        outs = rounds_outputs[idx] if idx < len(rounds_outputs) else []
        return {
            "ok": True,
            "successes": [{"output": o, "agent_id": "researcher"} for o in outs],
            "failures": [],
            "success_count": len(outs),
        }

    return fake


def test_progress_lines_stream_through_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds, "_call_agent_parallel", _fake_parallel_seq([["a\nb"], ["c"]]))
    lines: list[str] = []
    with ds.orchestration_progress_scope(lines.append):
        result = ds._run_orchestration(goal="g", n=1, rounds=2, patience=2, verify=False)
    assert result["ok"] is True
    joined = "\n".join(lines)
    assert "[orchestration] start" in joined
    assert "round 1/2" in joined
    assert "round 2/2" in joined
    assert "[orchestration] done" in joined


def test_no_emitter_outside_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds, "_call_agent_parallel", _fake_parallel_seq([["a"]]))
    # No scope installed — must run exactly as before, no error, no leak.
    result = ds._run_orchestration(goal="g", n=1, rounds=1, patience=0, verify=False)
    assert result["ok"] is True


def test_emitter_exception_never_breaks_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ds, "_call_agent_parallel", _fake_parallel_seq([["a"]]))

    def _boom(_line: str) -> None:
        raise RuntimeError("emitter crashed")

    with ds.orchestration_progress_scope(_boom):
        result = ds._run_orchestration(goal="g", n=1, rounds=1, patience=0, verify=False)
    assert result["ok"] is True
