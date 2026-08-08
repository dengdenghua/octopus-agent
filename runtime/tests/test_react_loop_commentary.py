"""Tests for model-authored public commentary.

Missing ``Update:`` checkpoints intentionally stay silent instead of
manufacturing repeated runtime prose. The frontend activity pulse and concrete
tool rows keep the turn visibly alive until a truthful model-authored update is
available.
"""

from __future__ import annotations

from runtime.core.cerebrum.react_loop import (
    stream_react_loop,
)
from tests.test_react_loop import (
    _build_stack_with_executor,
    _drain,
    _intent,
    _ScriptedRouter,
)


def test_missing_public_update_does_not_manufacture_commentary() -> None:
    """A missing checkpoint yields tool activity without canned assistant prose."""
    router = _ScriptedRouter(
        [
            'Thought: inspect source\nAction: echo({"text": "evidence"})',
            "Final Answer: evidence verified",
        ]
    )
    stack = _build_stack_with_executor(router)
    intent = _intent("inspect source")
    intent.user_context["mode"] = "react"

    events, result = _drain(stream_react_loop(stack, intent, agent=None, max_iterations=3))

    assert result is not None and result.final_answer == "evidence verified"
    commentary = [event for event in events if event["type"] == "commentary_delta"]
    assert commentary == []
    assert result.steps[0].public_update == ""


def test_model_supplied_update_is_not_replaced_by_runtime_fallback() -> None:
    """When the model DOES supply ``Update:``, the runtime fallback must not fire."""
    router = _ScriptedRouter(
        [
            (
                "Thought: inspect source\n"
                "Update: 已定位到证据源，下一步核对内容。\n"
                'Action: echo({"text": "evidence"})'
            ),
            "Final Answer: evidence verified",
        ]
    )
    stack = _build_stack_with_executor(router)
    intent = _intent("inspect source")
    intent.user_context["mode"] = "react"

    events, result = _drain(stream_react_loop(stack, intent, agent=None, max_iterations=3))

    assert result is not None and result.final_answer == "evidence verified"
    commentary = [event for event in events if event["type"] == "commentary_delta"]
    assert len(commentary) == 1
    # Model-supplied updates carry progress_source="model", not "runtime".
    assert commentary[0]["progress_source"] == "model"
    assert commentary[0]["delta"] == "已定位到证据源，下一步核对内容。"
