"""Tests for the Mix virtual model (octopus-mix · mixture-of-agents)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from runtime.platform.models import ParsedIntent
from runtime.sensing.gateway.openai_gateway import mix


@pytest.fixture(autouse=True)
def _isolated_mix_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the Mix preset at a scratch path for every test in this file.

    The preset lives in the developer's own ``~/.octopus/mix_config.json`` and
    takes precedence over the environment by design, so without this a machine
    with a real preset made these tests assert against whatever models the
    developer happened to have configured — a test that passes or fails based
    on the home directory is not a test.
    """
    monkeypatch.setattr(mix, "_config_path", lambda: tmp_path / "mix_config.json")


@pytest.fixture(autouse=True)
def _no_custom_models(monkeypatch: pytest.MonkeyPatch) -> None:
    """Deterministic baseline: no custom_models.json, so tag-inferred pools
    resolve to empty and Mix keeps the planner-default behaviour. A real
    catalog on a dev box would otherwise inject tier-tagged models into the
    inferred pool and change the asserted defaults. Tests that exercise the
    tag inference override this fixture per-test."""
    from runtime.platform.models import custom_model_flags

    monkeypatch.setattr(custom_model_flags, "read_custom_models", lambda: None)


def _install_custom_models(monkeypatch: pytest.MonkeyPatch, data: dict[str, Any]) -> None:
    from runtime.platform.models import custom_model_flags

    monkeypatch.setattr(custom_model_flags, "read_custom_models", lambda: data)


def _intent(goal: str = "What is 2+2?") -> ParsedIntent:
    return ParsedIntent(
        raw=goal,
        intent_type="task",
        normalized_goal=goal,
        user_context={"conversation_messages": [{"role": "user", "content": goal}]},
    )


def _envelope(content: str) -> dict[str, Any]:
    return {
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "octopus": {},
    }


def test_is_mix_model() -> None:
    assert mix.is_mix_model("octopus-mix")
    assert mix.is_mix_model("octopus-mix:fast")
    assert mix.is_mix_model("OCTOPUS-MIX")
    assert not mix.is_mix_model("octopus-agent")
    assert not mix.is_mix_model("gpt-5.5")
    assert not mix.is_mix_model(None)


def test_mix_model_ids_advertises_virtual_model() -> None:
    assert "octopus-mix" in mix.mix_model_ids()


def test_proposer_specs_default_count(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_MIX_PROPOSERS", raising=False)
    monkeypatch.delenv("OCTOPUS_MIX_N", raising=False)
    specs = mix._proposer_specs("octopus-mix")
    assert len(specs) == 3
    # default pool → planner-default model ("") with distinct lenses
    assert all(model == "" for model, _ in specs)
    assert len({lens for _, lens in specs}) == 3


def test_proposer_specs_from_env_pool(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_MIX_PROPOSERS", "m1, m2 , m3")
    specs = mix._proposer_specs("octopus-mix")
    assert [model for model, _ in specs] == ["m1", "m2", "m3"]


def test_run_mix_chat_injects_drafts_and_annotates(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_MIX_PROPOSERS", raising=False)
    monkeypatch.delenv("OCTOPUS_MIX_N", raising=False)

    def fake_proposer(stack, intent, agent, model=None, **_kwargs):  # noqa: ANN001
        # echo the injected lens so the three drafts are distinct + non-empty
        lens = intent.user_context["conversation_messages"][0]["content"]
        return (f"draft::{lens[:18]}", {})

    monkeypatch.setattr(mix, "_direct_llm_fallback_with_usage", fake_proposer)

    captured: dict[str, Any] = {}

    def fake_run_chat(stack, intent, model, default_arm, *, optimizer=None, actor=None, agent=None):  # noqa: ANN001
        captured["intent"] = intent
        captured["model"] = model
        return _envelope("final synthesized answer")

    out = mix.run_mix_chat(
        object(),
        _intent(),
        "octopus-mix",
        "code_arm",
        actor="u1",
        agent=None,
        run_chat=fake_run_chat,
    )

    meta = out["octopus"]["mix"]
    assert meta["drafts_used"] == 3
    assert meta["proposers"] == 3
    assert meta["degraded"] is False
    assert out["model"] == "octopus-mix"

    # aggregator saw the drafts as a trailing system message + structured copy
    convo = captured["intent"].user_context["conversation_messages"]
    assert convo[-1]["role"] == "system"
    assert "Draft 1" in convo[-1]["content"]
    assert len(captured["intent"].user_context["mix_proposals"]) == 3


def test_run_mix_chat_degrades_when_all_proposers_fail(monkeypatch) -> None:
    monkeypatch.delenv("OCTOPUS_MIX_PROPOSERS", raising=False)
    monkeypatch.setattr(
        mix,
        "_direct_llm_fallback_with_usage",
        lambda *a, **k: (None, {}),
    )

    captured: dict[str, Any] = {}

    def fake_run_chat(stack, intent, model, default_arm, *, optimizer=None, actor=None, agent=None):  # noqa: ANN001
        captured["intent"] = intent
        return _envelope("plain single-model answer")

    out = mix.run_mix_chat(
        object(),
        _intent(),
        "octopus-mix",
        "code_arm",
        actor=None,
        agent=None,
        run_chat=fake_run_chat,
    )

    meta = out["octopus"]["mix"]
    assert meta["degraded"] is True
    assert meta["drafts_used"] == 0
    # degraded path runs the ORIGINAL intent — no drafts injected
    assert "mix_proposals" not in (captured["intent"].user_context or {})


def test_mix_sse_frames_emit_valid_openai_stream() -> None:
    frames = list(mix.mix_sse_frames(_envelope("hello world"), "octopus-mix"))
    joined = "".join(frames)
    assert '"role": "assistant"' in joined
    assert "hello world" in joined
    assert '"finish_reason": "stop"' in joined
    assert '"model": "octopus-mix"' in joined
    assert joined.rstrip().endswith("[DONE]")


def test_mix_config_roundtrip_and_priority(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mix, "_config_path", lambda: tmp_path / "mix_config.json")
    # save validates: trims blanks, caps count at _MAX_PROPOSERS
    saved = mix.save_mix_config({"proposers": ["a", " ", "b"], "aggregator": "agg", "n": 99})
    assert saved["proposers"] == ["a", "b"]
    assert saved["aggregator"] == "agg"
    assert saved["n"] == mix._MAX_PROPOSERS
    # load round-trips
    assert mix.load_mix_config()["proposers"] == ["a", "b"]
    # config WINS over env
    monkeypatch.setenv("OCTOPUS_MIX_PROPOSERS", "x,y,z")
    monkeypatch.setenv("OCTOPUS_MIX_AGGREGATOR", "env-agg")
    assert mix._proposer_pool() == ["a", "b"]
    assert mix._aggregator_model() == "agg"


def test_mix_config_missing_falls_back_to_env(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(mix, "_config_path", lambda: tmp_path / "absent.json")
    monkeypatch.setenv("OCTOPUS_MIX_PROPOSERS", "x,y")
    assert mix._proposer_pool() == ["x", "y"]


# ── Cost-tier inferred pool (economy/balanced → proposers, performance → aggregator) ──


def test_proposer_pool_infers_economy_then_balanced_from_tags(monkeypatch) -> None:
    """With no explicit pool, Mix drafts on the cheap tier: economy entries
    first, then balanced — performance stays out of the draft stage."""
    _install_custom_models(
        monkeypatch,
        {
            "perf": {"id": "kimi-k3", "tier": "performance"},
            "econ": {"id": "agnes-2.5-flash", "tier": "economy"},
            "mid": {"id": "deepseek-v4-flash", "tier": "balanced"},
        },
    )
    assert mix._proposer_pool() == ["agnes-2.5-flash", "deepseek-v4-flash"]


def test_proposer_pool_excludes_performance_from_drafts(monkeypatch) -> None:
    """A catalog with only performance-tagged models yields NO inferred
    proposers — the draft stage never wastes the expensive tier."""
    _install_custom_models(
        monkeypatch,
        {
            "kimi": {"id": "kimi-k3", "tier": "performance"},
            "ark": {"id": "ark-code-latest", "tier": "performance"},
        },
    )
    assert mix._proposer_pool() == []


def test_proposer_pool_empty_when_no_tags_declared(monkeypatch) -> None:
    """Untagged entries carry no cost signal → not eligible for the pool."""
    _install_custom_models(
        monkeypatch,
        {"untagged": {"id": "some-model", "base_url": "https://x"}},
    )
    assert mix._proposer_pool() == []


def test_proposer_pool_caps_at_max_proposers(monkeypatch) -> None:
    economy = {f"e{i}": {"id": f"econ-{i}", "tier": "economy"} for i in range(10)}
    _install_custom_models(monkeypatch, economy)
    assert len(mix._proposer_pool()) == mix._MAX_PROPOSERS


def test_aggregator_infers_performance_then_balanced(monkeypatch) -> None:
    """The aggregator prefers the strong performance tier, deterministic
    sorted pick across multiple performance-tagged entries."""
    _install_custom_models(
        monkeypatch,
        {
            "econ": {"id": "agnes-2.5-flash", "tier": "economy"},
            "mid": {"id": "deepseek-v4-flash", "tier": "balanced"},
            "perf1": {"id": "kimi-k3", "tier": "performance"},
            "perf2": {"id": "ark-code-latest", "tier": "performance"},
        },
    )
    assert mix._aggregator_model() == "ark-code-latest"


def test_aggregator_falls_back_to_balanced_without_performance(monkeypatch) -> None:
    _install_custom_models(
        monkeypatch,
        {
            "econ": {"id": "agnes-2.5-flash", "tier": "economy"},
            "mid": {"id": "deepseek-v4-flash", "tier": "balanced"},
        },
    )
    assert mix._aggregator_model() == "deepseek-v4-flash"


def test_aggregator_empty_without_performance_or_balanced(monkeypatch) -> None:
    """Economy-only catalog → aggregator stays on the planner default."""
    _install_custom_models(
        monkeypatch,
        {"econ": {"id": "agnes-2.5-flash", "tier": "economy"}},
    )
    assert mix._aggregator_model() == ""


def test_explicit_config_and_env_beat_tag_inference(tmp_path, monkeypatch) -> None:
    """Declared pools/aggregator always win over tag inference — the tags are
    a fallback for an operator who never configured Mix, never an override."""
    _install_custom_models(
        monkeypatch,
        {"econ": {"id": "agnes-2.5-flash", "tier": "economy"}},
    )
    # env wins over tags
    monkeypatch.setenv("OCTOPUS_MIX_PROPOSERS", "env-pool")
    monkeypatch.setenv("OCTOPUS_MIX_AGGREGATOR", "env-agg")
    assert mix._proposer_pool() == ["env-pool"]
    assert mix._aggregator_model() == "env-agg"
    # preset config wins over env + tags
    monkeypatch.setattr(mix, "_config_path", lambda: tmp_path / "mix_config.json")
    mix.save_mix_config({"proposers": ["cfg-pool"], "aggregator": "cfg-agg"})
    assert mix._proposer_pool() == ["cfg-pool"]
    assert mix._aggregator_model() == "cfg-agg"


def test_proposer_specs_uses_tagged_pool(monkeypatch) -> None:
    """End-to-end: the inferred pool becomes the actual proposer model list,
    each with a distinct reasoning lens."""
    monkeypatch.delenv("OCTOPUS_MIX_PROPOSERS", raising=False)
    monkeypatch.delenv("OCTOPUS_MIX_N", raising=False)
    _install_custom_models(
        monkeypatch,
        {
            "econ": {"id": "agnes-2.5-flash", "tier": "economy"},
            "mid": {"id": "deepseek-v4-flash", "tier": "balanced"},
        },
    )
    specs = mix._proposer_specs("octopus-mix")
    assert [m for m, _ in specs] == ["agnes-2.5-flash", "deepseek-v4-flash"]
    assert len({lens for _, lens in specs}) == 2  # distinct lenses


def test_run_mix_chat_uses_tagged_proposers_and_aggregator(monkeypatch) -> None:
    """The tagged pool flows through a real run_mix_chat: drafts come from the
    cheap tier and the aggregator is the performance model."""
    monkeypatch.delenv("OCTOPUS_MIX_PROPOSERS", raising=False)
    _install_custom_models(
        monkeypatch,
        {
            "econ": {"id": "agnes-2.5-flash", "tier": "economy"},
            "mid": {"id": "deepseek-v4-flash", "tier": "balanced"},
            "perf": {"id": "kimi-k3", "tier": "performance"},
        },
    )

    seen_proposers: list[str] = []

    def fake_proposer(stack, intent, agent, model=None, **_kwargs):  # noqa: ANN001
        seen_proposers.append(model)
        return (f"draft-from-{model}", {})

    monkeypatch.setattr(mix, "_direct_llm_fallback_with_usage", fake_proposer)

    captured: dict[str, Any] = {}

    def fake_run_chat(stack, intent, model, default_arm, *, optimizer=None, actor=None, agent=None):  # noqa: ANN001
        captured["model"] = model
        return _envelope("synthesized")

    mix.run_mix_chat(
        object(),
        _intent(),
        "octopus-mix",
        "code_arm",
        actor="u1",
        agent=None,
        run_chat=fake_run_chat,
    )

    assert seen_proposers == ["agnes-2.5-flash", "deepseek-v4-flash"]
    assert captured["model"] == "kimi-k3"


def test_proposer_calls_pass_max_tokens_cap(monkeypatch) -> None:
    """Proposers are draft-only advisors with no tool access — they must
    not get the ~131K-token ceiling a full agentic turn gets."""
    monkeypatch.delenv("OCTOPUS_MIX_PROPOSERS", raising=False)
    monkeypatch.delenv("OCTOPUS_MIX_N", raising=False)

    seen_caps: list[Any] = []

    def fake_proposer(stack, intent, agent, model=None, max_tokens_cap=None, **_kw):  # noqa: ANN001
        seen_caps.append(max_tokens_cap)
        return ("draft", {})

    monkeypatch.setattr(mix, "_direct_llm_fallback_with_usage", fake_proposer)

    mix.run_mix_chat(
        object(),
        _intent(),
        "octopus-mix",
        "code_arm",
        actor="u1",
        agent=None,
        run_chat=lambda *a, **k: _envelope("final"),  # noqa: ARG005
    )

    assert len(seen_caps) == 3
    assert all(cap == mix._PROPOSER_MAX_TOKENS for cap in seen_caps)
    assert mix._PROPOSER_MAX_TOKENS < 131072  # meaningfully smaller than a full-turn budget


def test_run_mix_chat_bounds_total_wait_on_a_hung_proposer(monkeypatch) -> None:
    """A single hung proposer must not block the whole mix request for the
    model SDK's own (much longer) default timeout — the total stage-1 wait
    is capped, and the hung proposer's draft is simply dropped."""
    import time as _time

    monkeypatch.delenv("OCTOPUS_MIX_PROPOSERS", raising=False)
    monkeypatch.delenv("OCTOPUS_MIX_N", raising=False)
    monkeypatch.setattr(mix, "_PROPOSER_TIMEOUT_SECONDS", 0.2)

    def fake_proposer(stack, intent, agent, model=None, **_kw):  # noqa: ANN001
        lens = intent.user_context["conversation_messages"][0]["content"]
        if "correctness" in lens:  # the first lens — make exactly one hang
            _time.sleep(5.0)
            return ("late-draft", {})
        return (f"draft::{lens[:10]}", {})

    monkeypatch.setattr(mix, "_direct_llm_fallback_with_usage", fake_proposer)

    started = _time.monotonic()
    out = mix.run_mix_chat(
        object(),
        _intent(),
        "octopus-mix",
        "code_arm",
        actor="u1",
        agent=None,
        run_chat=lambda *a, **k: _envelope("final"),  # noqa: ARG005
    )
    elapsed = _time.monotonic() - started

    assert elapsed < 2.0  # bounded by the 0.2s timeout, not the 5s sleep
    meta = out["octopus"]["mix"]
    assert meta["drafts_used"] == 2  # the hung proposer's draft was dropped
    assert meta["proposers"] == 3
