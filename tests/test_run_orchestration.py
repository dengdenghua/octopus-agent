"""Deterministic orchestration loop (``run_orchestration``).

Fan out N workers per round, split + dedupe findings, loop until dry (or the
spawn budget runs out), optionally vote-verify each finding. The control flow
is code, so it's deterministic and unit-testable: the loop/dedup logic is
tested by mocking the two sub-skills; the budget gate is tested end-to-end
through the real ``_call_agent_parallel`` with a mocked ``call_subagent``.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest

from runtime.execution.suckers import delegation_budget as db
from runtime.execution.suckers import delegation_skills as ds


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


# ── pure helpers ─────────────────────────────────────────────────


def test_split_findings_strips_bullets_and_nulls():
    assert ds._split_findings("- a\n2. b\n\nNONE\n* c") == ["a", "b", "c"]
    assert ds._split_findings("nothing\nN/A") == []


def test_dedupe_findings_normalises_and_tracks_seen():
    seen: set[str] = set()
    assert ds._dedupe_findings(["A", "a ", "B"], seen) == ["A", "B"]
    assert ds._dedupe_findings(["B", "C"], seen) == ["C"]


# ── loop logic (sub-skills mocked) ───────────────────────────────


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


def test_two_rounds_collect_union(monkeypatch):
    monkeypatch.setattr(ds, "_call_agent_parallel", _fake_parallel_seq([["a\nb"], ["c"]]))
    r = ds._run_orchestration(goal="g", n=1, rounds=2, patience=2)
    assert r["collected"] == ["a", "b", "c"]
    assert r["rounds_run"] == 2
    assert r["stopped_reason"] == "rounds"


def test_dry_stop(monkeypatch):
    monkeypatch.setattr(ds, "_call_agent_parallel", _fake_parallel_seq([["a"], [], ["c"]]))
    r = ds._run_orchestration(goal="g", n=1, rounds=3, patience=0)
    assert r["collected"] == ["a"]
    assert r["rounds_run"] == 2
    assert r["stopped_reason"] == "dry"


def test_dedupe_across_rounds(monkeypatch):
    monkeypatch.setattr(
        ds, "_call_agent_parallel", _fake_parallel_seq([["a\nb"], ["a\nb"], ["c"]]),
    )
    r = ds._run_orchestration(goal="g", n=1, rounds=3, patience=1)
    assert r["collected"] == ["a", "b", "c"]
    assert r["fresh_per_round"] == [2, 0, 1]
    assert r["rounds_run"] == 3


def test_verify_drops_minority(monkeypatch):
    monkeypatch.setattr(
        ds, "_call_agent_parallel", _fake_parallel_seq([["keep-me\ndrop-me"]]),
    )

    def fake_vote(question: str = "", **_kw: Any) -> dict[str, Any]:
        verdict = "drop" if "drop-me" in question else "keep"
        return {"ok": True, "verdict": verdict}

    monkeypatch.setattr(ds, "_call_agent_vote", fake_vote)
    r = ds._run_orchestration(goal="g", n=1, rounds=1, verify=True)
    assert r["collected"] == ["keep-me", "drop-me"]
    assert r["confirmed"] == ["keep-me"]
    assert r["verified"] is True


def test_missing_goal_errors():
    r = ds._run_orchestration(goal="")
    assert r["ok"] is False
    assert "required" in (r["error"] or "")


# ── budget gate (real _call_agent_parallel, mocked call_subagent) ─


def test_budget_stops_the_loop(monkeypatch):
    counter = {"i": 0}
    lock = threading.Lock()

    def fake_cs(agent_id: str = "", prompt: str = "", **_kw: Any) -> dict[str, Any]:
        with lock:
            counter["i"] += 1
            i = counter["i"]
        return {"agent_id": agent_id, "output": f"finding-{i}", "success": True, "error": None}

    monkeypatch.setattr("runtime.execution.subagents.call_subagent", fake_cs)
    monkeypatch.setattr("runtime.execution.subagents.bridge.call_subagent", fake_cs)

    # max_spawns=4, n=3: round1 charges 3 (room), round2 charges 3 (3<4 room),
    # round3 has no room → budget-stop. Every finding is unique so it never
    # dry-stops first.
    r = ds._run_orchestration(goal="g", n=3, rounds=5, patience=3, max_spawns=4)
    assert r["stopped_reason"] == "budget"
    assert r["rounds_run"] == 2
    assert r["budget_used"] >= 4
