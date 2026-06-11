from runtime.core.cerebrum.thinking_mode import (
    build_thinking_plan,
    render_thinking_guidance,
    update_thinking_plan_status,
)


def test_thinking_plan_flags_fresh_research_needs() -> None:
    plan = build_thinking_plan(
        "做一个 NAS 市场调研，看看最新价格和竞品",
        mode="react",
    )

    payload = plan.to_dict()
    assert payload["mode"] == "react"
    assert payload["needs_search"] is True
    assert payload["suggest_deep_research"] is True
    assert payload["steps"][0]["status"] == "in_progress"
    assert any("source" in risk.lower() for risk in payload["risks"])


def test_thinking_guidance_is_visible_scaffold_not_hidden_cot() -> None:
    plan = build_thinking_plan("Compare two options", mode="thinking")
    guidance = render_thinking_guidance(plan)

    assert "structured thinking mode" in guidance
    assert "Do not reveal hidden chain-of-thought" in guidance
    assert "virtual, ephemeral" in guidance
    assert "Frame the ask" in guidance


def test_thinking_plan_progress_advances_and_completes() -> None:
    plan = build_thinking_plan("Compare two options", mode="react").to_dict()

    progressed = update_thinking_plan_status(plan, iteration=2)

    assert progressed is not None
    assert progressed["progress"] > 0
    assert progressed["steps"][0]["status"] == "completed"
    assert progressed["steps"][1]["status"] == "completed"
    assert progressed["steps"][2]["status"] == "in_progress"

    completed = update_thinking_plan_status(progressed, final=True)
    assert completed is not None
    assert completed["progress"] == 1.0
    assert {step["status"] for step in completed["steps"]} == {"completed"}
