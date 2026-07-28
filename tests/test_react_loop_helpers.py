"""Unit tests for small pure helpers extracted out of ``stream_react_loop``.

``_finish_reason_is_length_limited`` (PHASE 6c) and ``_tool_call_succeeded``
(PHASE 6d) used to be inlined and duplicated inside the loop body; pulling them
out makes their contracts testable in isolation.
"""

from types import SimpleNamespace

import pytest

from runtime.core.cerebrum import react_action_outcomes
from runtime.core.cerebrum.react_loop import (
    _explicit_no_tool_goal,
    _finish_reason_is_length_limited,
    _has_unrecovered_beak_failure,
    _tool_call_succeeded,
)


@pytest.mark.parametrize(
    "goal",
    [
        "Do not use tools; answer directly.",
        "Reply without any tools.",
        "不要使用工具，只回答结果。",
        "直接回复，不用工具。",
    ],
)
def test_explicit_no_tool_goal(goal):
    assert _explicit_no_tool_goal(goal) is True


@pytest.mark.parametrize(
    "goal",
    [
        "Use the browser tool to verify this.",
        "只读分析两个文件，不要修改。",
        "直接回答后继续执行测试。",
    ],
)
def test_non_no_tool_goal(goal):
    assert _explicit_no_tool_goal(goal) is False


@pytest.mark.parametrize(
    "reason",
    [
        "length",
        "max_tokens",
        "max_output_tokens",
        "output_limit",
        "token_limit",
        "LENGTH",
        "  Max_Tokens  ",
    ],
)
def test_length_limited_finish_reasons(reason):
    assert _finish_reason_is_length_limited(reason) is True


@pytest.mark.parametrize("reason", ["stop", "end_turn", "", None, "tool_use"])
def test_non_length_limited_finish_reasons(reason):
    assert _finish_reason_is_length_limited(reason) is False


def test_tool_success_plain_observation():
    assert _tool_call_succeeded("all good", None) is True


def test_tool_success_none_observation():
    assert _tool_call_succeeded(None, None) is True


@pytest.mark.parametrize("obs", ["(工具失败) boom", "(工具执行异常) trace"])
def test_tool_failure_prefixed_observation(obs):
    assert _tool_call_succeeded(obs, None) is False


def test_beak_step_verdict_overrides_observation(monkeypatch):
    # A successful beak step wins even over a failure-prefixed observation.
    monkeypatch.setattr(react_action_outcomes, "_beak_step_effective_success", lambda s: True)
    assert _tool_call_succeeded("(工具失败) boom", object()) is True
    # A failed beak step overrides a clean-looking observation.
    monkeypatch.setattr(react_action_outcomes, "_beak_step_effective_success", lambda s: False)
    assert _tool_call_succeeded("looks fine", object()) is False


def _beak_step(name: str, *, status: str = "success") -> SimpleNamespace:
    return SimpleNamespace(
        action=SimpleNamespace(name=name),
        result=SimpleNamespace(status=status, output={}),
    )


def test_substantive_success_recovers_an_earlier_tool_failure():
    steps = [
        _beak_step("browser_navigate", status="failed"),
        _beak_step("exec_shell"),
    ]

    assert not _has_unrecovered_beak_failure(steps)


def test_bookkeeping_success_does_not_hide_an_unrecovered_tool_failure():
    steps = [
        _beak_step("browser_navigate", status="failed"),
        _beak_step("todo_write"),
    ]

    assert _has_unrecovered_beak_failure(steps)
