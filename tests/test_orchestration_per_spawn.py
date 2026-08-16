"""``run_orchestration`` must exercise the per-spawn knobs its callee offers.

``_call_agent_parallel`` accepts a heterogeneous spec list — per-spec prompt,
``cheap`` model tier, tool grants, context — but ``run_orchestration`` used to
send N byte-identical finder specs differing only in ``agent_id``, and pinned
the closing synthesizer to ``roles[0]``. With the default roster that is
``researcher``, which ``_role_defaults_to_cheap`` routes to the CHEAP model, so
the most reasoning-heavy step of the run used the weakest model.

These tests pin the spec SHAPE at the boundary, which is where the regression
would reappear: the fan-out is only as diverse as the specs handed downstream.
"""

from __future__ import annotations

from typing import Any

from runtime.execution.suckers import delegation_skills as ds
from runtime.execution.suckers._delegation_skills_common import (
    _NON_CHEAP_ROLES,
    _role_defaults_to_cheap,
)
from runtime.execution.suckers._delegation_skills_orchestration import (
    _ROLE_LENS,
    _finder_spec,
    _synthesis_spec,
)


def _capture_specs(monkeypatch: Any, output: str = "alpha") -> dict[str, Any]:
    """Record every spec batch handed to ``_call_agent_parallel``."""
    seen: dict[str, Any] = {"batches": []}

    def fake(specs: Any = None, **_kw: Any) -> dict[str, Any]:
        batch = list(specs or [])
        seen["batches"].append(batch)
        prompt = str((batch or [{}])[0].get("prompt", ""))
        if "CONFIRMED FINDINGS" in prompt:
            return {"ok": True, "successes": [{"output": "synth"}], "success_count": 1}
        return {
            "ok": True,
            "successes": [{"output": output, "agent_id": "researcher"}],
            "success_count": 1,
        }

    monkeypatch.setattr(ds, "_call_agent_parallel", fake)
    return seen


# ── per-role lens: the fan-out must not be N identical searches ────


def test_each_role_gets_a_distinct_lens_directive(monkeypatch: Any) -> None:
    seen = _capture_specs(monkeypatch)
    ds._run_orchestration(
        goal="g", agent_id=["researcher", "debugger", "architect"], n=3, rounds=1, max_spawns=20
    )
    prompts = [s["prompt"] for s in seen["batches"][0]]
    assert len(set(prompts)) == 3, "workers received identical prompts — no lens split"
    for role, prompt in zip(["researcher", "debugger", "architect"], prompts, strict=True):
        assert f"YOUR LENS ({role})" in prompt
        assert _ROLE_LENS[role] in prompt


def test_lens_tells_the_worker_not_to_cover_everything(monkeypatch: Any) -> None:
    """Without this the narrow lens reads as a suggestion and workers overlap."""
    seen = _capture_specs(monkeypatch)
    ds._run_orchestration(goal="g", agent_id=["explorer"], n=1, rounds=1, max_spawns=20)
    assert "do not try to cover everything yourself" in seen["batches"][0][0]["prompt"].lower()


def test_unknown_role_omits_the_lens_block_rather_than_inventing_one() -> None:
    spec = _finder_spec("some-custom-role", "g", [])
    assert "YOUR LENS" not in spec["prompt"]
    assert "GOAL:\ng" in spec["prompt"]


def test_finder_spec_keeps_the_structured_output_schema() -> None:
    """The schema is what makes findings survive multi-line prose."""
    spec = _finder_spec("researcher", "g", [])
    assert spec["output_schema"]["required"] == ["findings"]


def test_finder_spec_leaves_cheap_unset_so_the_roster_picks_the_tier() -> None:
    """Pinning ``cheap`` here would defeat per-role model routing downstream."""
    assert "cheap" not in _finder_spec("architect", "g", [])


def test_already_seen_findings_still_reach_every_lens(monkeypatch: Any) -> None:
    seen = _capture_specs(monkeypatch, output="beta")
    ds._run_orchestration(
        goal="g", agent_id=["researcher", "debugger"], n=2, rounds=2, max_spawns=20
    )
    second_round = seen["batches"][1]
    for spec in second_round:
        assert "beta" in spec["prompt"], "round-2 worker not told what round 1 found"


# ── synthesizer: the heavy step must not run on the cheap model ────


def test_synthesizer_is_pinned_to_the_synthesizer_role() -> None:
    assert _synthesis_spec("g", ["a"])["agent_id"] == "synthesizer"


def test_synthesizer_role_keeps_the_primary_model() -> None:
    """The actual defect: ``roles[0]`` defaulted to a cheap-routed role."""
    assert "synthesizer" in _NON_CHEAP_ROLES
    assert _role_defaults_to_cheap("synthesizer") is False
    # The old behaviour, kept as the contrast that motivates the pin.
    assert _role_defaults_to_cheap("researcher") is True


def test_synthesis_spawn_does_not_inherit_roles_zero(monkeypatch: Any) -> None:
    seen = _capture_specs(monkeypatch)
    ds._run_orchestration(
        goal="g", agent_id=["researcher"], n=1, rounds=1, synthesize=True, max_spawns=20
    )
    synth = [b[0] for b in seen["batches"] if "CONFIRMED FINDINGS" in str(b[0].get("prompt", ""))]
    assert len(synth) == 1
    assert synth[0]["agent_id"] == "synthesizer"


def test_synthesizer_carries_no_finder_schema() -> None:
    """It returns prose, not a findings array; a schema would reject it."""
    assert "output_schema" not in _synthesis_spec("g", ["a"])


# ── spawn accounting: the count nobody was pinning ────────────────


def test_spawn_count_matches_n_times_rounds(monkeypatch: Any) -> None:
    """No test previously asserted how many spawns a run actually issues."""
    seen = _capture_specs(monkeypatch, output="fresh-1")
    r = ds._run_orchestration(goal="g", agent_id=["researcher"], n=3, rounds=1, max_spawns=20)
    assert sum(len(b) for b in seen["batches"]) == 3
    assert r["rounds_run"] == 1


def test_budget_ceiling_stops_the_round_loop(monkeypatch: Any) -> None:
    """The envelope is charged per spec INSIDE the real ``_call_agent_parallel``,
    so a fake that skips ``try_charge`` would never exhaust it. Charge like the
    real callee does, then assert the loop stops instead of running all rounds.
    """
    from runtime.execution.suckers.delegation_budget import current_orchestration_budget

    batches: list[int] = []

    def fake(specs: Any = None, **_kw: Any) -> dict[str, Any]:
        batch = list(specs or [])
        budget = current_orchestration_budget()
        spawned = [s for s in batch if budget is None or budget.try_charge()]
        batches.append(len(spawned))
        return {
            "ok": True,
            "successes": [
                {"output": f"finding-{len(batches)}-{i}", "agent_id": "researcher"}
                for i, _ in enumerate(spawned)
            ],
            "success_count": len(spawned),
        }

    monkeypatch.setattr(ds, "_call_agent_parallel", fake)
    r = ds._run_orchestration(goal="g", agent_id=["researcher"], n=2, rounds=5, max_spawns=2)
    assert sum(batches) == 2, f"charged more than the ceiling: {batches}"
    assert r["rounds_run"] < 5, "ran every round despite an exhausted envelope"
    assert r["stopped_reason"] == "budget"
    assert r["budget_used"] == 2
