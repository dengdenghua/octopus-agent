"""Opt-in, budget-driven orchestration depth — default behaviour preserved.

`run_orchestration`'s spawn budget was a fixed `n*rounds` estimate hard-capped
at 48, which throttles a deep verify+synth run (natural usage ~121). This adds
an OPT-IN lever: a trusted token budget (set in session metadata by the
bus/operator) scales the spawn ceiling up to a higher deep-mode cap. With no
budget the conservative `n*rounds`/48 default is unchanged. Both policy helpers
are pure, so this is verified without spawning agents.
"""
from __future__ import annotations

from runtime.execution.suckers.delegation_budget import (
    max_spawns_for_token_budget,
    operator_orchestration_token_budget,
)
from runtime.execution.suckers.delegation_skills import (
    _ORCH_MAX_SPAWNS_CEILING,
    _resolve_max_spawns,
)


class TestMaxSpawnsForTokenBudget:
    def test_missing_or_nonpositive_budget_falls_to_floor(self) -> None:
        assert max_spawns_for_token_budget(None) == 2
        assert max_spawns_for_token_budget(0) == 2
        assert max_spawns_for_token_budget(-5) == 2
        assert max_spawns_for_token_budget("bad") == 2

    def test_budget_scales_linearly_between_floor_and_ceiling(self) -> None:
        # 8000 tokens/spawn default → 400k buys 50 spawns
        assert max_spawns_for_token_budget(400_000) == 50
        assert max_spawns_for_token_budget(16_000) == 2  # 2 spawns, == floor

    def test_huge_budget_is_clamped_to_ceiling(self) -> None:
        assert max_spawns_for_token_budget(10_000_000) == 256
        assert max_spawns_for_token_budget(10_000_000, ceiling=100) == 100


class TestResolveMaxSpawns:
    def test_default_no_budget_keeps_48_cap(self) -> None:
        # deep verify+synth naturally wants ~121 but stays capped at 48
        got = _resolve_max_spawns(None, n=6, rounds=5, verify=True, synthesize=True)
        assert got == _ORCH_MAX_SPAWNS_CEILING == 48

    def test_default_small_run_uses_n_rounds(self) -> None:
        got = _resolve_max_spawns(None, n=3, rounds=2, verify=False, synthesize=False)
        assert got == 6  # n*rounds, no verify/synth

    def test_token_budget_opt_in_scales_past_48(self) -> None:
        got = _resolve_max_spawns(
            None, n=3, rounds=2, verify=True, synthesize=True, token_budget=400_000
        )
        assert got == 50  # budget-driven, above the default 48 throttle

    def test_explicit_max_spawns_wins_over_budget(self) -> None:
        got = _resolve_max_spawns(
            10, n=3, rounds=2, verify=True, synthesize=True, token_budget=400_000
        )
        assert got == 10  # explicit wins; budget ignored

    def test_explicit_still_capped_at_48(self) -> None:
        assert _resolve_max_spawns(100, n=3, rounds=2, verify=False, synthesize=False) == 48

    def test_budget_never_below_n(self) -> None:
        # tiny budget (→ floor 2) must still allow at least n per round
        got = _resolve_max_spawns(
            None, n=5, rounds=2, verify=False, synthesize=False, token_budget=8_000
        )
        assert got == 5


class TestOperatorEnvBudget:
    _ENV = "OCTOPUS_ORCH_TOKEN_BUDGET"

    def test_unset_is_none(self, monkeypatch) -> None:
        monkeypatch.delenv(self._ENV, raising=False)
        assert operator_orchestration_token_budget() is None

    def test_set_positive_returns_value(self, monkeypatch) -> None:
        monkeypatch.setenv(self._ENV, "400000")
        assert operator_orchestration_token_budget() == 400_000

    def test_invalid_or_nonpositive_is_none(self, monkeypatch) -> None:
        for bad in ("", "  ", "abc", "0", "-100"):
            monkeypatch.setenv(self._ENV, bad)
            assert operator_orchestration_token_budget() is None

    def test_operator_env_drives_resolve_max_spawns(self, monkeypatch) -> None:
        # the operator switch, fed through the resolver, lifts above the 48 cap
        monkeypatch.setenv(self._ENV, "400000")
        budget = operator_orchestration_token_budget()
        got = _resolve_max_spawns(
            None, n=3, rounds=2, verify=True, synthesize=True, token_budget=budget
        )
        assert got == 50 > _ORCH_MAX_SPAWNS_CEILING
