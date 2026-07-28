"""Tests for the forced runtime fallback commentary.

When the model omits the ``Update:`` protocol checkpoint, the runtime
must still emit a deterministic commentary item so the conversation
keeps a visible beat and the realtime bridge can bind protocol fields
(phase_id / progress_sequence / timeline_sequence).
"""

from __future__ import annotations

from runtime.core.cerebrum.react_loop import (
    ReActStep,
    _runtime_fallback_public_update,
    stream_react_loop,
)
from tests.test_react_loop import (
    _build_stack_with_executor,
    _drain,
    _intent,
    _ScriptedRouter,
)

# ── _runtime_fallback_public_update: deterministic fallback text ──


def test_runtime_fallback_public_update_with_file_target() -> None:
    """The fallback names the action's non-sensitive file target."""
    step = ReActStep(
        iteration=1,
        thought="inspect",
        action='read_file({"path": "src/app.py"})',
    )
    update = _runtime_fallback_public_update(goal="inspect app", step=step)
    assert "app.py" in update


def test_runtime_fallback_public_update_without_target() -> None:
    """When no target is available, a generic beat is still produced."""
    step = ReActStep(
        iteration=1,
        thought="inspect",
        action='echo({"text": "evidence"})',
    )
    update = _runtime_fallback_public_update(goal="inspect", step=step)
    assert update  # non-empty generic message


def test_runtime_fallback_public_update_cjk_goal() -> None:
    """CJK goals produce CJK fallback text."""
    step = ReActStep(
        iteration=1,
        thought="检查",
        action='read_file({"path": "src/app.py"})',
    )
    update = _runtime_fallback_public_update(goal="检查应用逻辑", step=step)
    assert "正在处理" in update
    assert "app.py" in update


def test_runtime_fallback_public_update_empty_action() -> None:
    """An empty action still yields a non-empty generic beat."""
    step = ReActStep(iteration=1, thought="", action="")
    update = _runtime_fallback_public_update(goal="do work", step=step)
    assert update


# ── stream_react_loop: forced fallback when model omits Update: ──


def test_missing_public_update_forces_runtime_fallback_commentary() -> None:
    """When the model omits ``Update:``, a runtime commentary_delta is emitted.

    The delta carries ``progress_source="runtime"`` and ``public_evidence=True``
    so the realtime gateway forwards it (generic runtime prose is otherwise
    dropped) and the bridge can bind phase_id/progress_sequence/timeline_sequence.
    """
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
    assert len(commentary) == 1
    assert commentary[0]["progress_source"] == "runtime"
    assert commentary[0]["public_evidence"] is True
    assert commentary[0]["delta"]  # non-empty deterministic fallback
    assert commentary[0]["iteration"] == 1
    # The fallback is recorded on the step so later iterations can dedup.
    assert result.steps[0].public_update == commentary[0]["delta"]


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
