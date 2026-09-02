"""Cross-layer regression for guard-rejected realtime answer drafts."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.core.cerebrum.react_loop import (
    _reset_guard_telemetry_for_tests,
    stream_react_loop,
)
from runtime.execution.suckers import Skill
from runtime.sensing.gateway.realtime_cerebrum import _ReactBridgeState
from runtime.sensing.gateway.realtime_react_stream import _apply_react_event
from tests.test_delta_coalescing import (
    _make_turn,
    _StubEmitter,
    _StubLog,
    _StubRuntime,
)
from tests.test_react_loop import (
    _build_stack_with_executor,
    _drain,
    _intent,
    _ScriptedRouter,
)


def _register_web_search(stack: Any, *, url: str) -> None:
    stack.executor.registry.register(
        Skill(
            name="web_search",
            description="Search an external source.",
            trusted_source="builtin://web_search",
            handler=lambda q="": {
                "query": q,
                "results": [
                    {
                        "title": "Octopus realtime architecture",
                        "url": url,
                        "snippet": "Explicit phases and causal progress sequence.",
                    }
                ],
            },
        ),
        verify_tests=False,
    )


def test_first_research_candidate_is_withheld_before_any_tool_runs(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("OCTOPUS_DISABLE_GUARD_TELEMETRY", "1")
    _reset_guard_telemetry_for_tests()
    rejected = "UNPUBLISHED_DRAFT：调研结论：事件流采用显式阶段，主要风险已经确认。"
    accepted = (
        "最终报告：事件流使用显式阶段，"
        "来源见[官方说明](https://observed.example/report)。"
    )
    router = _ScriptedRouter(
        [
            f"Final Answer: {rejected}",
            (
                "Thought: fetch the requested primary source\n"
                'Action: web_search({"q":"Octopus realtime architecture"})'
            ),
            f"Final Answer: {accepted}",
        ]
    )
    stack = _build_stack_with_executor(router)
    _register_web_search(stack, url="https://observed.example/report")
    intent = _intent("调研 Octopus realtime 架构并给出有来源的结论")
    intent.user_context["mode"] = "react"

    events, result = _drain(stream_react_loop(stack, intent, agent=None, max_iterations=4))

    assert result is not None and result.success
    assert result.final_answer == accepted
    assert "".join(
        event["delta"] for event in events if event["type"] == "text_delta"
    ) == accepted
    assert rejected not in str(events)
    assert any("inspection-evidence guard" in step.observation for step in result.steps)


@pytest.mark.parametrize(
    ("action_block", "expected_tool_names"),
    [
        ('Action: echo({"text":"done"})', {"echo"}),
        (
            "Action:\n"
            'echo({"text":"done"})\n'
            'web_search({"q":"Octopus realtime architecture"})',
            {"echo", "web_search"},
        ),
    ],
    ids=["single-non-fetch", "multi-action-with-fetch"],
)
def test_same_response_pending_actions_keep_final_candidate_private(
    monkeypatch: Any,
    action_block: str,
    expected_tool_names: set[str],
) -> None:
    monkeypatch.setenv("OCTOPUS_DISABLE_GUARD_TELEMETRY", "1")
    _reset_guard_telemetry_for_tests()
    rejected = (
        "UNPUBLISHED_DRAFT：事件流使用显式阶段，"
        "来源见[未抓取说明](https://not-fetched.example/report)。"
    )
    accepted = "最终报告：操作已经执行，提前生成的候选未作为结果发布。"
    if "web_search" in expected_tool_names:
        accepted += " 来源见[官方说明](https://observed.example/report)。"
    router = _ScriptedRouter(
        [
            (
                "Thought: execute the pending action before answering\n"
                f"{action_block}\n"
                f"Final Answer: {rejected}"
            ),
            f"Final Answer: {accepted}",
        ]
    )
    stack = _build_stack_with_executor(router)
    _register_web_search(stack, url="https://observed.example/report")
    # Deliberately not an explicit lookup goal: any real pending Action makes
    # the adjacent Final Answer premature, including multi-action blocks where
    # a fetch call is not the first item.
    intent = _intent("解释 Octopus realtime 架构并给出结论")
    intent.user_context["mode"] = "react"

    events, result = _drain(stream_react_loop(stack, intent, agent=None, max_iterations=3))

    assert result is not None and result.success
    assert result.final_answer == accepted
    assert "".join(
        event["delta"] for event in events if event["type"] == "text_delta"
    ) == accepted
    assert rejected not in str(events)
    started_tools = {
        str(event.get("tool_name"))
        for event in events
        if event["type"] == "tool_start"
    }
    assert expected_tool_names <= started_tools


@pytest.mark.asyncio
async def test_guard_rejected_report_never_becomes_realtime_agent_message(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("OCTOPUS_DISABLE_GUARD_TELEMETRY", "1")
    _reset_guard_telemetry_for_tests()
    rejected = (
        "UNPUBLISHED_DRAFT：这是校验前候选报告，"
        "引用了[未抓取来源](https://not-fetched.example/report)。"
    )
    accepted = (
        "最终报告：事件流使用显式阶段，"
        "来源见[官方说明](https://observed.example/report)。"
    )
    router = _ScriptedRouter(
        [
            (
                "Thought: fetch the primary source before answering\n"
                'Action: web_search({"q":"Octopus realtime architecture"})'
            ),
            f"Final Answer: {rejected}",
            f"Final Answer: {accepted}",
        ]
    )
    stack = _build_stack_with_executor(router)
    _register_web_search(stack, url="https://observed.example/report")
    intent = _intent("调研 Octopus realtime 架构并给出有来源的结论")
    intent.user_context["mode"] = "react"

    events, result = _drain(stream_react_loop(stack, intent, agent=None, max_iterations=4))

    assert result is not None and result.success
    assert result.final_answer == accepted
    assert any(
        event["type"] == "react_step_complete"
        and "[citation-grounding guard]" in str(event.get("observation") or "")
        for event in events
    )
    assert "".join(
        event["delta"] for event in events if event["type"] == "text_delta"
    ) == accepted

    turn = _make_turn()
    state = _ReactBridgeState()
    emitter = _StubEmitter()
    log = _StubLog()
    runtime = _StubRuntime()
    for event in events:
        # Visibility snapshots have their own direct EventLog event-id path;
        # this regression exercises answer publication, not catalog routing.
        if event["type"] == "visibility":
            continue
        await _apply_react_event(
            runtime,  # type: ignore[arg-type]
            turn,
            log,  # type: ignore[arg-type]
            emitter,  # type: ignore[arg-type]
            state,
            event,
        )

    answers = [
        item
        for item in turn.items
        if item.type == "agentMessage" and item.message_kind == "answer"
    ]
    assert len(answers) == 1
    assert answers[0].text == accepted
    assert answers[0].status.value == "completed"
    completed_answers = [
        params["item"]
        for method, params in emitter.notified
        if method.endswith("item/completed")
        and params.get("item", {}).get("type") == "agentMessage"
        and params.get("item", {}).get("messageKind") == "answer"
    ]
    assert len(completed_answers) == 1
    assert completed_answers[0]["text"] == accepted
    assert "UNPUBLISHED_DRAFT" not in str(emitter.notified)


@pytest.mark.parametrize("anchored", [True, False], ids=["anchored", "zero-anchor"])
def test_length_limited_research_segments_are_guarded_and_published_atomically(
    monkeypatch: Any,
    anchored: bool,
) -> None:
    monkeypatch.setenv("OCTOPUS_DISABLE_GUARD_TELEMETRY", "1")
    _reset_guard_telemetry_for_tests()
    prefix = "Final Answer: " if anchored else ""
    first_segment = "UNPUBLISHED_DRAFT：候选报告引用了[错误来源]("
    rejected_tail = (
        "https://not-fetched.example/report), 并以"
        "[官方说明](https://observed.example/report)作为补充，"
        "结论是事件流使用显式阶段。"
    )
    accepted = (
        "最终报告：事件流使用显式阶段，"
        "来源见[官方说明](https://observed.example/report)。"
    )
    router = _ScriptedRouter(
        [
            (
                "Thought: fetch the primary source before answering\n"
                'Action: web_search({"q":"Octopus realtime architecture"})'
            ),
            f"{prefix}{first_segment}",
            f"{prefix}{rejected_tail}",
            f"{prefix}{accepted}",
        ],
        finish_reasons=["stop", "length", "stop", "stop"],
    )
    stack = _build_stack_with_executor(router)
    _register_web_search(stack, url="https://observed.example/report")
    intent = _intent("调研 Octopus realtime 架构并给出有来源的结论")
    intent.user_context["mode"] = "react"

    events, result = _drain(stream_react_loop(stack, intent, agent=None, max_iterations=5))

    assert result is not None and result.success
    assert result.final_answer == accepted
    assert router.calls == 4
    assert any(
        event["type"] == "react_step_complete"
        and "[citation-grounding guard]" in str(event.get("observation") or "")
        for event in events
    )
    visible_answer = "".join(
        event["delta"] for event in events if event["type"] == "text_delta"
    )
    assert visible_answer == accepted
    assert "UNPUBLISHED_DRAFT" not in visible_answer
