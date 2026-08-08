from __future__ import annotations

from runtime.core.cerebrum.capability_router import (
    activate_capabilities,
    order_skill_names,
)


class _FakeRegistry:
    def __init__(self, names: list[str]):
        self._names = set(names)

    def has(self, name: str) -> bool:
        return name in self._names

    def is_enabled(self, name: str) -> bool:  # noqa: ARG002
        return True


def test_research_goal_activates_research_tools() -> None:
    reg = _FakeRegistry(
        [
            "web_search",
            "fetch_url",
            "deep-research",
            "report-writing",
            "query_skill",
        ]
    )

    activation = activate_capabilities(
        "调研一个值得进入的细分赛道，输出竞品格局和风险",
        registry=reg,
    )

    assert "research" in activation.labels
    assert "web_search" in activation.priority_skills
    assert "deep-research" in activation.priority_skills
    assert "query_skill" in activation.priority_skills
    assert activation.render_prompt()


def test_order_skill_names_keeps_edge_distance_relevant_tools_first() -> None:
    names = [
        "filler_a",
        "filler_b",
        "web_search",
        "deep-research",
        "query_skill",
    ]
    activation = activate_capabilities(
        "market research with sources",
        registry=_FakeRegistry(names),
    )

    ordered = order_skill_names(names, activation=activation)

    assert ordered[:3] == ["query_skill", "web_search", "deep-research"]


def test_code_ui_regression_excludes_desktop_bridge_from_activation() -> None:
    names = [
        "live_browser_navigate",
        "live_browser_type",
        "browser_navigate",
        "browser_state",
        "browser_type",
        "browser_click",
        "browser_extract",
        "browser_wait",
    ]
    activation = activate_capabilities(
        "verify the frontend regression at localhost",
        user_context={
            "mode": "code",
            "browser_regression_enabled": True,
            "browser_regression_preview_url": "http://127.0.0.1:4321/index.html",
        },
        registry=_FakeRegistry(names),
    )

    assert "code-ui-regression" in activation.labels
    assert activation.priority_skills[:6] == (
        "browser_navigate",
        "browser_state",
        "browser_type",
        "browser_click",
        "browser_extract",
        "browser_wait",
    )
    assert not any(name.startswith("live_browser_") for name in activation.priority_skills)
