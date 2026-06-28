"""Tests for the Mix virtual model (octopus-mix · mixture-of-agents)."""

from __future__ import annotations

from typing import Any

from runtime.platform.models import ParsedIntent
from runtime.sensing.gateway.openai_gateway import mix


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

    def fake_proposer(stack, intent, agent, model=None):  # noqa: ANN001
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
        object(), _intent(), "octopus-mix", "code_arm",
        actor="u1", agent=None, run_chat=fake_run_chat,
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
        mix, "_direct_llm_fallback_with_usage",
        lambda *a, **k: (None, {}),
    )

    captured: dict[str, Any] = {}

    def fake_run_chat(stack, intent, model, default_arm, *, optimizer=None, actor=None, agent=None):  # noqa: ANN001
        captured["intent"] = intent
        return _envelope("plain single-model answer")

    out = mix.run_mix_chat(
        object(), _intent(), "octopus-mix", "code_arm",
        actor=None, agent=None, run_chat=fake_run_chat,
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
