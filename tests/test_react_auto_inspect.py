from runtime.core.cerebrum.react_auto_inspect import (
    _try_auto_project_inspection_salvage,
)
from runtime.core.cerebrum.react_types import ReActStep


def test_salvages_announce_only_project_inspection() -> None:
    step = _try_auto_project_inspection_salvage(
        "final-answer completeness guard",
        "让我先了解一下你们项目的现状，再给出针对性建议。",
        [],
        iteration=2,
        tools_active=True,
    )

    assert step is not None
    assert step.action == "list_cwd({})"
    assert step.actions == ["list_cwd({})"]


def test_does_not_turn_external_search_promise_into_project_listing() -> None:
    step = _try_auto_project_inspection_salvage(
        "final-answer completeness guard",
        "我先搜索官方新闻，再告诉你发布日期。",
        [],
        iteration=2,
        tools_active=True,
    )

    assert step is None


def test_salvage_runs_only_once() -> None:
    prior = ReActStep(iteration=1, action="list_cwd({})", observation="README.md")
    step = _try_auto_project_inspection_salvage(
        "final-answer completeness guard",
        "我继续检查项目文件。",
        [prior],
        iteration=2,
        tools_active=True,
    )

    assert step is None
