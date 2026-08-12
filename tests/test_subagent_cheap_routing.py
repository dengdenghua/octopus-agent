"""Tests for cheap-model routing in the subagent dispatch lane.

The bridge accepts a ``use_cheap_model`` keyword that, when true and
no explicit ``model_name`` is pinned in context, injects a
project-wide cheap default into the merged context the runner sees.
``call_agent_parallel`` carries a per-spec ``cheap`` flag with role-
based defaults so research-style roles auto-route to the cheap tier
while architects / synthesizers stay on the parent's primary model.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.execution.subagents import bridge
from runtime.execution.suckers import delegation_skills

# ── Fixtures ────────────────────────────────────────────────


@pytest.fixture
def capture_runner(monkeypatch):
    """Install stubs that capture the context the dispatcher passes to
    the runner.

    Builtin roles like ``researcher`` / ``architect`` go through the
    ephemeral lane (``run_ephemeral_role`` / ``run_ephemeral_definition``)
    not the persistent ``_RUNNER`` path, so we stub the ephemeral runner
    too. Either path lands here and writes the context it observed.
    """
    captured: dict[str, Any] = {}

    def _runner(prompt, *, subagent_name, context):
        captured["prompt"] = prompt
        captured["subagent_name"] = subagent_name
        captured["context"] = dict(context or {})
        return "Final Answer: ok."

    def _ephemeral_runner(call):
        captured["prompt"] = call.user_prompt
        captured["subagent_name"] = call.role.id
        captured["context"] = dict(call.context or {})
        return "Final Answer: ok."

    from runtime.execution.suckers import ephemeral_agents

    orig_runner = bridge._RUNNER
    orig_eph = ephemeral_agents._EPHEMERAL_RUNNER
    bridge._RUNNER = _runner
    ephemeral_agents._EPHEMERAL_RUNNER = _ephemeral_runner
    try:
        yield captured
    finally:
        bridge._RUNNER = orig_runner
        ephemeral_agents._EPHEMERAL_RUNNER = orig_eph


@pytest.fixture(autouse=True)
def _clear_cheap_model_env(monkeypatch):
    """Ensure each test starts with a clean env override."""
    monkeypatch.delenv("OCTOPUS_SUBAGENT_CHEAP_MODEL", raising=False)


@pytest.fixture(autouse=True)
def _no_custom_models(monkeypatch):
    """Deterministic baseline: no custom_models.json present, so cheap
    routing resolves to ``None`` and the bridge leaves ``model_name``
    unset (the ephemeral runner then falls back to the planner/main
    model). A real custom_models.json on a dev box would otherwise inject
    a self-configured model and change the asserted defaults; tests that
    exercise the custom-models picker override this fixture per-test."""
    from runtime.platform.models import custom_model_flags

    monkeypatch.setattr(custom_model_flags, "read_custom_models", lambda: None)


def _install_custom_models(monkeypatch, data):
    from runtime.platform.models import custom_model_flags

    monkeypatch.setattr(custom_model_flags, "read_custom_models", lambda: data)


# ── _resolve_cheap_subagent_model ────────────────────────────


def test_resolve_returns_env_override_when_set(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_SUBAGENT_CHEAP_MODEL", "my-org-cheap-v2")
    assert bridge._resolve_cheap_subagent_model() == "my-org-cheap-v2"


def test_resolve_strips_whitespace_and_ignores_blank(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_SUBAGENT_CHEAP_MODEL", "   ")
    # Blank → falls through; no cheap config anywhere → None (runner
    # falls back to the planner model).
    assert bridge._resolve_cheap_subagent_model() is None


def test_resolve_returns_none_when_no_cheap_model_configured() -> None:
    # No env, no config, no custom models → None, never an invented
    # model id the operator may not have (which would only 404).
    assert bridge._resolve_cheap_subagent_model() is None


def test_resolve_picks_declared_cheap_over_agent_plan(monkeypatch) -> None:
    """Only entries the operator EXPLICITLY declared cheap (``tier: "economy"``)
    are candidates: the Agent-Plan endpoint is excluded (it 404s for any model
    id outside its allowlist) and the plain OpenAI-compatible ``deepseek``
    entry — no ``tier`` — is skipped even though its name contains ``flash``.
    Deterministic sorted pick = agnes."""
    _install_custom_models(
        monkeypatch,
        {
            "plan": {
                "id": "kimi-k3",
                "provider": "openai",
                "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
            },
            "deepseek": {
                "id": "deepseek-v4-flash",
                "provider": "openai",
                "base_url": "https://opencode.ai/zen/go/v1",
            },
            "agnes": {
                "id": "agnes-2.5-flash",
                "provider": "openai",
                "tier": "economy",
                "base_url": "https://apihub.agnes-ai.com/v1",
            },
        },
    )
    assert bridge._resolve_cheap_subagent_model() == "agnes-2.5-flash"


def test_resolve_ignores_openai_model_without_tier_declaration(monkeypatch) -> None:
    """The core contract: an OpenAI-compatible, non-Agent-Plan endpoint with
    no explicit ``tier: "economy"`` is NOT a cheap candidate — cheapness is a
    declaration, never guessed from a name or alphabetical order."""
    _install_custom_models(
        monkeypatch,
        {
            "flashy": {
                "id": "deepseek-v4-flash",
                "provider": "openai",
                "base_url": "https://opencode.ai/zen/go/v1",
            },
        },
    )
    assert bridge._resolve_cheap_subagent_model() is None


def test_resolve_ignores_balanced_and_performance_tier_for_cheap(
    monkeypatch,
) -> None:
    """The cheap slot is strictly ``economy``: entries tagged
    ``balanced`` or ``performance`` are NOT cheap candidates, even
    though they are legitimate cost tiers on the three-tier scale."""
    _install_custom_models(
        monkeypatch,
        {
            "deepseek": {
                "id": "deepseek-v4-flash",
                "provider": "openai",
                "tier": "balanced",
                "base_url": "https://opencode.ai/zen/go/v1",
            },
            "luna": {
                "id": "gpt-5.6-luna",
                "provider": "openai",
                "tier": "performance",
                "base_url": "https://opencode.ai/zen/go/v1",
            },
        },
    )
    assert bridge._resolve_cheap_subagent_model() is None


def test_resolve_picks_economy_over_balanced(monkeypatch) -> None:
    """When a catalog mixes ``economy`` and ``balanced`` entries, only
    the economy one is a cheap candidate — deterministic sorted pick."""
    _install_custom_models(
        monkeypatch,
        {
            "deepseek": {
                "id": "deepseek-v4-flash",
                "provider": "openai",
                "tier": "balanced",
                "base_url": "https://opencode.ai/zen/go/v1",
            },
            "agnes": {
                "id": "agnes-2.5-flash",
                "provider": "openai",
                "tier": "economy",
                "base_url": "https://apihub.agnes-ai.com/v1",
            },
        },
    )
    assert bridge._resolve_cheap_subagent_model() == "agnes-2.5-flash"


def test_resolve_tier_match_is_case_insensitive(monkeypatch) -> None:
    _install_custom_models(
        monkeypatch,
        {
            "agnes": {
                "id": "agnes-2.5-flash",
                "provider": "openai",
                "tier": "Economy",
                "base_url": "https://apihub.agnes-ai.com/v1",
            },
        },
    )
    assert bridge._resolve_cheap_subagent_model() == "agnes-2.5-flash"


def test_resolve_returns_none_when_only_agent_plan_endpoints(monkeypatch) -> None:
    """If every custom endpoint is a single-model Agent-Plan one, do not
    return any of them (every cheap call would 404) — return None so the
    runner falls back to the planner/main model instead."""
    _install_custom_models(
        monkeypatch,
        {
            "kimi": {
                "id": "kimi-k3",
                "provider": "openai",
                "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
            },
            "ark": {
                "id": "ark-code-latest",
                "provider": "openai",
                "base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
            },
        },
    )
    assert bridge._resolve_cheap_subagent_model() is None


def test_resolve_ignores_non_openai_provider(monkeypatch) -> None:
    """Non-OpenAI-compatible providers are not candidate cheap models."""
    _install_custom_models(
        monkeypatch,
        {
            "claude": {
                "id": "claude-sonnet",
                "provider": "anthropic",
                "base_url": "https://api.anthropic.com/v1",
            },
        },
    )
    assert bridge._resolve_cheap_subagent_model() is None


def test_resolve_returns_none_when_custom_models_empty(monkeypatch) -> None:
    _install_custom_models(monkeypatch, {})
    assert bridge._resolve_cheap_subagent_model() is None


def test_agent_plan_endpoint_marker() -> None:
    from runtime.execution.subagents._bridge_identity import _is_agent_plan_endpoint

    assert _is_agent_plan_endpoint("https://ark.cn-beijing.volces.com/api/plan/v3") is True
    assert _is_agent_plan_endpoint("https://ark.cn-beijing.volces.com/api/plan/v3/") is True
    assert _is_agent_plan_endpoint("https://opencode.ai/zen/go/v1") is False
    assert _is_agent_plan_endpoint("") is False


def test_call_subagent_uses_resolved_custom_model_when_cheap(
    monkeypatch,
    capture_runner,
) -> None:
    """With a generic custom endpoint configured, cheap-routed researcher
    runs land on it — not on the hard-coded glm-4-flash."""
    _install_custom_models(
        monkeypatch,
        {
            "deepseek": {
                "id": "deepseek-v4-flash",
                "provider": "openai",
                "tier": "economy",
                "base_url": "https://opencode.ai/zen/go/v1",
            },
        },
    )
    bridge.call_subagent(
        agent_id="researcher",
        prompt="dig into X",
        use_cheap_model=True,
    )
    assert capture_runner["context"].get("model_name") == "deepseek-v4-flash"


# ── call_subagent + use_cheap_model ──────────────────────────


def test_call_subagent_without_cheap_config_leaves_model_to_runner(
    capture_runner,
) -> None:
    """Cheap requested but nothing resolves → bridge does NOT invent a
    model id; ``model_name`` stays unset and the ephemeral runner falls
    back to the planner/main model (verified end-to-end in
    test_ephemeral_runner.py::TestDispatchModelOverrideEndToEnd)."""
    bridge.call_subagent(
        agent_id="researcher",
        prompt="dig into X",
        use_cheap_model=True,
    )
    assert capture_runner["context"].get("model_name") is None


def test_call_subagent_explicit_model_name_wins_over_cheap(capture_runner) -> None:
    bridge.call_subagent(
        agent_id="researcher",
        prompt="dig into X",
        context={"model_name": "explicit-x"},
        use_cheap_model=True,
    )
    # The caller pinned a model — cheap routing must NOT override it.
    assert capture_runner["context"].get("model_name") == "explicit-x"


def test_call_subagent_without_cheap_flag_does_not_inject(capture_runner) -> None:
    bridge.call_subagent(agent_id="researcher", prompt="dig into X")
    assert "model_name" not in capture_runner["context"]


def test_call_subagent_env_override_is_used_when_cheap(
    monkeypatch,
    capture_runner,
) -> None:
    monkeypatch.setenv("OCTOPUS_SUBAGENT_CHEAP_MODEL", "qwen-flash")
    bridge.call_subagent(
        agent_id="researcher",
        prompt="dig into X",
        use_cheap_model=True,
    )
    assert capture_runner["context"].get("model_name") == "qwen-flash"


# ── _call_agent_parallel role-based defaults ─────────────────


def test_parallel_researcher_defaults_to_cheap(monkeypatch, capture_runner) -> None:
    """A researcher spec with no explicit ``cheap`` flag auto-routes
    to the cheap model (here the resolved custom one)."""
    _install_custom_models(
        monkeypatch,
        {
            "deepseek": {
                "id": "deepseek-v4-flash",
                "provider": "openai",
                "tier": "economy",
                "base_url": "https://opencode.ai/zen/go/v1",
            },
        },
    )
    delegation_skills._call_agent_parallel(
        specs=[{"role": "researcher", "task": "find X"}],
        timeout_s=5,
    )
    assert capture_runner["context"].get("model_name") == "deepseek-v4-flash"


def test_parallel_explicit_cheap_false_disables_auto_route(capture_runner) -> None:
    """An explicit ``cheap: False`` on a researcher spec wins over the
    auto-cheap default."""
    delegation_skills._call_agent_parallel(
        specs=[{"role": "researcher", "task": "find X", "cheap": False}],
        timeout_s=5,
    )
    assert "model_name" not in capture_runner["context"]


def test_parallel_architect_defaults_to_primary(capture_runner) -> None:
    """``architect`` is a heavy-reasoning role and stays on the primary
    model unless the spec opts in explicitly."""
    delegation_skills._call_agent_parallel(
        specs=[{"role": "architect", "task": "design Y"}],
        timeout_s=5,
    )
    assert "model_name" not in capture_runner["context"]


def test_parallel_explicit_cheap_true_on_architect_routes_cheap(
    monkeypatch,
    capture_runner,
) -> None:
    """Explicit ``cheap: True`` overrides the architect default."""
    _install_custom_models(
        monkeypatch,
        {
            "deepseek": {
                "id": "deepseek-v4-flash",
                "provider": "openai",
                "tier": "economy",
                "base_url": "https://opencode.ai/zen/go/v1",
            },
        },
    )
    delegation_skills._call_agent_parallel(
        specs=[{"role": "architect", "task": "summarize Y", "cheap": True}],
        timeout_s=5,
    )
    assert capture_runner["context"].get("model_name") == "deepseek-v4-flash"


def test_role_defaults_helper_classification() -> None:
    # Research-style roles → cheap.
    assert delegation_skills._role_defaults_to_cheap("researcher") is True
    assert delegation_skills._role_defaults_to_cheap("fact_checker") is True
    assert delegation_skills._role_defaults_to_cheap("security-review") is True
    assert delegation_skills._role_defaults_to_cheap("verifier") is True
    assert delegation_skills._role_defaults_to_cheap("debugger") is True
    # Heavy-reasoning roles → primary.
    assert delegation_skills._role_defaults_to_cheap("architect") is False
    assert delegation_skills._role_defaults_to_cheap("synthesizer") is False
    assert delegation_skills._role_defaults_to_cheap("designer") is False
    assert delegation_skills._role_defaults_to_cheap("implementer") is False
    # Unknown roles default to NOT cheap so user-defined agents keep
    # using the primary model unless asked otherwise.
    assert delegation_skills._role_defaults_to_cheap("totally_made_up") is False
    assert delegation_skills._role_defaults_to_cheap("") is False


# ── team_runner role classification ──────────────────────────


def test_team_runner_role_classification() -> None:
    from runtime.safety.organization.team_runner import _role_uses_cheap_model
    from runtime.safety.organization.topology import Role

    # Heavy-reasoning roles → primary.
    assert _role_uses_cheap_model(Role.PLANNER) is False
    assert _role_uses_cheap_model(Role.GENERATOR) is False
    assert _role_uses_cheap_model(Role.SYNTHESIZER) is False
    # Research / review roles → cheap.
    assert _role_uses_cheap_model(Role.RESEARCHER) is True
    assert _role_uses_cheap_model(Role.CRITIC) is True
    assert _role_uses_cheap_model(Role.EVALUATOR) is True


def test_team_runner_passes_cheap_flag_per_role() -> None:
    """When TeamRunner invokes a researcher role through a custom
    role_caller, the caller receives ``use_cheap_model=True``."""
    from runtime.safety.organization.team_runner import TeamRunner
    from runtime.safety.organization.topology import (
        AgentSpec,
        CoordinationProtocol,
        Role,
        TeamTopology,
    )

    seen: list[tuple[Role, bool]] = []

    def caller(*, agent_id, prompt, context, timeout_seconds, use_cheap_model=False):
        # Use the team_role from context to classify (the bridge sets
        # this before calling).
        team_role = context.get("team_role", "")
        seen.append((team_role, use_cheap_model))
        return {"output": f"<{agent_id}>", "success": True}

    topo = TeamTopology(
        name="cheap-routing-smoke",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.GENERATOR: AgentSpec(agent_id="gen"),
            Role.RESEARCHER: AgentSpec(agent_id="res"),
            Role.SYNTHESIZER: AgentSpec(agent_id="syn"),
        },
    )
    runner = TeamRunner(role_caller=caller)
    runner.run(topo, "build something")
    role_to_cheap = {r: cheap for r, cheap in seen}
    assert role_to_cheap[str(Role.GENERATOR)] is False
    assert role_to_cheap[str(Role.SYNTHESIZER)] is False
    assert role_to_cheap[str(Role.RESEARCHER)] is True


def test_team_runner_legacy_caller_without_cheap_kwarg_still_works() -> None:
    """A custom role_caller written before cheap routing landed (no
    ``use_cheap_model`` kwarg) keeps working via the TypeError fallback
    path."""
    from runtime.safety.organization.team_runner import TeamRunner
    from runtime.safety.organization.topology import (
        AgentSpec,
        CoordinationProtocol,
        Role,
        TeamTopology,
    )

    def legacy_caller(*, agent_id, prompt, context, timeout_seconds):
        return {"output": f"<{agent_id}>", "success": True}

    topo = TeamTopology(
        name="legacy-caller-smoke",
        protocol=CoordinationProtocol.SEQUENTIAL,
        agents={
            Role.GENERATOR: AgentSpec(agent_id="gen"),
        },
    )
    runner = TeamRunner(role_caller=legacy_caller)
    result = runner.run(topo, "task")
    assert result.success is True
