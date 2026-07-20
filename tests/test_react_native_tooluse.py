"""Native tool-use path for the single-agent ReAct loop.

Covers the gate, the tool_calls→step synthesis, the Phase-1 prompt trim,
and the end-to-end loop wiring: when native mode is active the loop must
pass ``tools=`` to the model and drive itself off the structured
``tool_calls`` instead of regex-parsing the action out of text. When the
flag is off (the default) the loop must behave byte-identically — no tools
passed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from runtime.core.cerebrum.react_native import (
    build_loop_tool_specs,
    native_tool_use_active,
    native_tool_use_flag_enabled,
    require_public_update_on_tool_specs,
    step_from_tool_calls,
    trim_text_protocol_for_native,
)
from runtime.execution.suckers import Skill, SkillRegistry
from runtime.platform.models import ParsedIntent
from runtime.platform.models.llm import ToolCall, ToolSpec
from runtime.sensing.model_router.models import (
    CostEntry,
    ModelResponse,
    ModelStreamEvent,
)

# ── unit: gate ───────────────────────────────────────────────────────


def test_flag_on_by_default(monkeypatch) -> None:
    # Default ON (validated against a live API). Only an explicit falsy
    # value forces the text protocol.
    monkeypatch.delenv("OCTOPUS_NATIVE_TOOLUSE", raising=False)
    assert native_tool_use_flag_enabled() is True
    monkeypatch.setenv("OCTOPUS_NATIVE_TOOLUSE", "0")
    assert native_tool_use_flag_enabled() is False


def test_gate_requires_capability_and_respects_escape_hatch(monkeypatch) -> None:
    class _Caps:
        supports_tool_use = True

    class _Router:
        capabilities = _Caps()

    monkeypatch.delenv("OCTOPUS_NATIVE_TOOLUSE", raising=False)
    assert native_tool_use_active(_Router(), "m") is True  # default on + capable
    monkeypatch.setenv("OCTOPUS_NATIVE_TOOLUSE", "0")
    assert native_tool_use_active(_Router(), "m") is False  # escape hatch forces off
    monkeypatch.setenv("OCTOPUS_NATIVE_TOOLUSE", "1")
    assert native_tool_use_active(_Router(), "m") is True

    class _NoCap:
        pass

    monkeypatch.delenv("OCTOPUS_NATIVE_TOOLUSE", raising=False)
    assert native_tool_use_active(_NoCap(), "m") is False  # capability gate still holds


def test_gate_resolves_dispatch_subrouter(monkeypatch) -> None:
    monkeypatch.setenv("OCTOPUS_NATIVE_TOOLUSE", "1")

    class _Caps:
        supports_tool_use = True

    class _Sub:
        capabilities = _Caps()

    class _Dispatch:
        def _resolve(self, _model: str) -> Any:
            return _Sub()

    assert native_tool_use_active(_Dispatch(), "claude") is True


def test_browser_surface_keeps_late_registered_browser_tools_in_native_specs() -> None:
    registry = SkillRegistry()
    for index in range(60):
        registry.register(
            Skill(
                name=f"dummy_{index}",
                trusted_source=f"skill://test/dummy_{index}",
                handler=lambda **_kw: {},
            ),
            verify_tests=False,
        )
    for name in ("browser_navigate", "browser_state", "browser_type", "browser_click"):
        registry.register(
            Skill(
                name=name,
                affinity=["browser"],
                trusted_source=f"skill://test/{name}",
                handler=lambda **_kw: {},
            ),
            verify_tests=False,
        )

    specs = build_loop_tool_specs(
        SimpleNamespace(registry=registry),
        goal="operate the UI",
        user_context={"browser_surface": "browser", "runtime_surfaces": ["browser"]},
    )

    names = {spec.name for spec in specs}
    assert {"browser_navigate", "browser_state", "browser_type", "browser_click"} <= names


# ── unit: tool_calls → step synthesis ────────────────────────────────


def test_step_from_tool_calls_single() -> None:
    step = step_from_tool_calls(
        [ToolCall(id="a", name="read_file", input={"path": "x.py"})],
        text="reading",
        iteration=2,
    )
    assert step.actions == ['read_file({"path": "x.py"})']
    assert step.action == 'read_file({"path": "x.py"})'
    assert step.thought == ""
    assert step.public_update == "reading"


def test_native_tool_schema_requires_model_authored_public_update() -> None:
    original = ToolSpec(
        name="read_file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )

    augmented = require_public_update_on_tool_specs([original])[0]

    assert augmented.input_schema["required"] == ["path", "public_update"]
    assert augmented.input_schema["properties"]["public_update"]["type"] == "string"
    assert augmented.input_schema["properties"]["public_update"]["maxLength"] == 420
    assert "later rounds" in augmented.input_schema["properties"]["public_update"]["description"]
    assert "public_update" not in original.input_schema["properties"]


def test_structured_public_update_is_displayed_but_not_sent_to_tool() -> None:
    step = step_from_tool_calls(
        [
            ToolCall(
                id="a",
                name="read_file",
                input={
                    "path": "x.py",
                    "public_update": "我先核对 x.py 的实际定义，再给出结论。",
                },
            )
        ],
        iteration=1,
    )

    assert step.public_update == "我先核对 x.py 的实际定义，再给出结论。"
    assert step.action == 'read_file({"path": "x.py"})'


def test_step_from_tool_calls_parallel() -> None:
    step = step_from_tool_calls(
        [
            ToolCall(id="a", name="read_file", input={"path": "x.py"}),
            ToolCall(id="b", name="web_search", input={"q": "octopus"}),
        ],
        iteration=1,
    )
    assert len(step.actions) == 2
    assert step.action.count(";") == 1  # joined for the parallel dispatch


def test_step_from_tool_calls_skips_nameless() -> None:
    step = step_from_tool_calls(
        [ToolCall(id="a", name="", input={})],
        iteration=1,
    )
    assert step.actions == []


# ── unit: Phase-1 prompt trim ────────────────────────────────────────


def test_trim_text_protocol_drops_scaffold() -> None:
    prompt = (
        "你是助手。\nThought: 当前思考\nAction: skill({})\n"
        "Observation: <由系统填入>\n后续政策说明。"
    )
    trimmed = trim_text_protocol_for_native(prompt)
    assert "Action: skill" not in trimmed
    assert "你是助手。" in trimmed
    assert "后续政策说明。" in trimmed
    assert "原生工具调用" in trimmed


def test_trim_is_noop_when_anchors_absent() -> None:
    prompt = "无任何 ReAct 锚点的提示。"
    assert trim_text_protocol_for_native(prompt) == prompt


# ── integration: loop wiring ─────────────────────────────────────────


@dataclass
class _Reg:
    # has → False keeps the dispatch off the executor entirely: we only
    # assert the native wiring (tools passed + tool_calls consumed), not
    # real skill execution (covered by the existing dispatch tests).
    def has(self, _name: str) -> bool:
        return False

    def is_enabled(self, _name: str) -> bool:
        return True

    def iter_skills(self) -> list[Any]:
        return []

    def iter_agents(self) -> list[Any]:
        return []


@dataclass
class _Exec:
    registry: Any = field(default_factory=_Reg)
    agent_registry: Any = field(default_factory=_Reg)


class _Caps:
    supports_tool_use = True


class _Router:
    """Turn-scripted router. Each turn is ``(text, tool_calls)``."""

    def __init__(self, turns: list[tuple[str, list[ToolCall]]]) -> None:
        self.turns = turns
        self.calls = 0
        self.requests: list[Any] = []
        self.capabilities = _Caps()

    def call(self, req: Any) -> ModelResponse:
        self.requests.append(req)
        text, calls = self.turns[min(self.calls, len(self.turns) - 1)]
        self.calls += 1
        return ModelResponse(
            text=text,
            model="test-model",
            tool_calls=list(calls),
            finish_reason="stop",
            cost=CostEntry(),
        )

    def call_stream(self, req: Any):
        resp = self.call(req)
        if resp.text:
            yield ModelStreamEvent(type="text_delta", delta=resp.text)
        yield ModelStreamEvent(type="done", final=resp)


class _Planner:
    def __init__(self, router: _Router) -> None:
        self.router = router
        self.planner_model = "test-model"


class _Stack:
    def __init__(self, router: _Router) -> None:
        self.planner = _Planner(router)
        self.executor = _Exec()


def _intent(goal: str = "读取配置文件") -> ParsedIntent:
    return ParsedIntent(
        raw=goal,
        intent_type="task",
        normalized_goal=goal,
        user_context={},
    )


def test_native_mode_passes_tools_and_consumes_tool_calls() -> None:
    from runtime.core.cerebrum.react_loop import run_react_loop

    router = _Router(
        [
            ("", [ToolCall(id="t1", name="read_file", input={"path": "config.yaml"})]),
            ("Final Answer: 已读取配置。", []),
        ]
    )
    fake_spec = ToolSpec(name="read_file", description="read a file")
    with (
        patch(
            "runtime.core.cerebrum.react_native.native_tool_use_active",
            return_value=True,
        ),
        patch(
            "runtime.core.cerebrum.react_native.build_loop_tool_specs",
            return_value=[fake_spec],
        ),
    ):
        result = run_react_loop(
            _Stack(router),
            _intent(),
            agent=None,
            max_iterations=5,
        )

    # Native turn passed a non-empty tools list to the model.
    assert any(getattr(r, "tools", None) for r in router.requests), "native mode must pass tools="
    # The loop consumed the tool_calls (turn 1) and continued to the final
    # answer (turn 2) — i.e. it drove off the structured calls, not text.
    assert router.calls >= 2
    # The empty-prose tool-use turn was recorded in history as the
    # synthesised action, not an (API-invalid) empty assistant message.
    turn2_messages = router.requests[1].messages
    assert any(
        getattr(m, "role", "") == "assistant" and "read_file" in str(getattr(m, "content", ""))
        for m in turn2_messages
    ), "turn-1 tool call should appear in the assistant history"
    assert result is not None
    assert "已读取配置" in (result.final_answer or "")


def test_every_native_tool_round_requires_a_fresh_public_update() -> None:
    from runtime.core.cerebrum.react_loop import stream_react_loop

    router = _Router(
        [
            (
                "",
                [
                    ToolCall(
                        id="t1",
                        name="read_file",
                        input={
                            "path": "backend.py",
                            "public_update": "我先核对后端事件定义，确认时间线的源字段。",
                        },
                    )
                ],
            ),
            (
                "",
                [
                    ToolCall(
                        id="t2",
                        name="read_file",
                        input={
                            "path": "frontend.ts",
                            "public_update": "后端字段已经确认；我再核对前端映射，确定两端是否逐项对应。",
                        },
                    )
                ],
            ),
            ("Final Answer: 两端字段逐项对应。", []),
        ]
    )
    fake_spec = ToolSpec(
        name="read_file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    intent = _intent("只读比较后端事件与前端映射")
    intent.user_context.update(
        {
            "realtime_public_narrative": True,
            "realtime_public_orientation": True,
        }
    )

    with (
        patch(
            "runtime.core.cerebrum.react_native.native_tool_use_active",
            return_value=True,
        ),
        patch(
            "runtime.core.cerebrum.react_native.build_loop_tool_specs",
            return_value=[fake_spec],
        ),
    ):
        stream = stream_react_loop(
            _Stack(router),
            intent,
            agent=None,
            max_iterations=5,
        )
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(next(stream))
            except StopIteration as stop:
                result = stop.value
                break

    tool_requests = [request for request in router.requests if request.tools]
    assert len(tool_requests) >= 2
    assert all(
        "public_update" in request.tools[0].input_schema.get("required", [])
        for request in tool_requests[:2]
    )
    assert result is not None
    assert [step.public_update for step in result.steps[:2]] == [
        "我先核对后端事件定义，确认时间线的源字段。",
        "后端字段已经确认；我再核对前端映射，确定两端是否逐项对应。",
    ]
    model_updates = [
        event
        for event in events
        if event.get("type") == "commentary_delta"
        and event.get("progress_source") == "model"
    ]
    assert [event["delta"] for event in model_updates] == [
        "我先核对后端事件定义，确认时间线的源字段。",
        "后端字段已经确认；我再核对前端映射，确定两端是否逐项对应。",
    ]


def test_native_provider_omission_gets_private_safe_public_repair() -> None:
    from runtime.core.cerebrum.react_loop import stream_react_loop

    orientation = "我先核对配置文件的实际内容，确认最终结论所需的依据。"
    router = _Router(
        [
            (
                "",
                [
                    ToolCall(
                        id="t1",
                        name="read_file",
                        input={"path": "config.yaml"},
                    )
                ],
            ),
            (orientation, []),
            ("Final Answer: 配置依据已经确认。", []),
        ]
    )
    fake_spec = ToolSpec(
        name="read_file",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    )
    intent = _intent("只读核对 config.yaml 并说明结论")
    intent.user_context.update(
        {
            "realtime_public_narrative": True,
            "realtime_public_orientation": True,
        }
    )

    with (
        patch(
            "runtime.core.cerebrum.react_native.native_tool_use_active",
            return_value=True,
        ),
        patch(
            "runtime.core.cerebrum.react_native.build_loop_tool_specs",
            return_value=[fake_spec],
        ),
    ):
        stream = stream_react_loop(_Stack(router), intent, agent=None, max_iterations=4)
        events: list[dict[str, Any]] = []
        while True:
            try:
                events.append(next(stream))
            except StopIteration as stop:
                result = stop.value
                break

    assert result is not None and result.final_answer == "配置依据已经确认。"
    assert result.steps[0].public_update == orientation
    repair_request = router.requests[1]
    assert repair_request.tools == []
    assert repair_request.enable_thinking is False
    repair_input = "\n".join(str(message.content) for message in repair_request.messages)
    assert "config.yaml" in repair_input
    assert "read_file" not in repair_input
    model_updates = [
        event["delta"]
        for event in events
        if event.get("type") == "commentary_delta"
        and event.get("progress_source") == "model"
    ]
    assert "".join(model_updates) == orientation


def test_escape_hatch_forces_text_mode(monkeypatch) -> None:
    from runtime.core.cerebrum.react_loop import run_react_loop

    # Capable router, but OCTOPUS_NATIVE_TOOLUSE=0 forces the text protocol:
    # no native tools= must be passed even though the model could do them.
    monkeypatch.setenv("OCTOPUS_NATIVE_TOOLUSE", "0")
    router = _Router([("Final Answer: 你好。", [])])
    result = run_react_loop(_Stack(router), _intent("你好"), agent=None)
    assert router.requests
    assert all(not getattr(r, "tools", None) for r in router.requests), (
        "forced text mode must not pass tools="
    )
    assert result is not None
