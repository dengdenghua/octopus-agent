import contextvars
import json
import threading
import time
from types import SimpleNamespace

import runtime.sensing.gateway.tool_bridge as tool_bridge
from runtime.execution.suckers.agent_meta_skills import _todo_write
from runtime.execution.suckers.builtins import _list_cwd, _read_file
from runtime.execution.suckers.registry import Skill, SkillRegistry
from runtime.execution.suckers.write_skills import register_code_quality_skills
from runtime.execution.tool_engine.executor import ToolExecutor
from runtime.execution.tool_engine.tool_protocol import NormalizedToolCall
from runtime.platform.models import ParsedIntent
from runtime.platform.process.session import Session, session_scope
from runtime.safety.auth import TrustEngine
from runtime.sensing.gateway.tool_bridge import (
    _execute_tool_call,
    _native_public_checkpoint,
    _native_result_checkpoint,
    _reflection_checkpoint_message,
    build_anthropic_tool_specs,
    stream_agentic_fallback,
)
from runtime.sensing.model_router.models import (
    ModelResponse,
    ModelStreamEvent,
    ToolCall,
)


def _agent():
    return SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        soul="",
    )


def _stack(router=None):
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="list_cwd",
            description="List files in a directory.",
            affinity=["file", "io"],
            trusted_source="skill://public/list_cwd",
            handler=_list_cwd,
        ),
        verify_tests=False,
    )
    return SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )


def _stack_with_todo(router=None):
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="list_cwd",
            description="List files in a directory.",
            affinity=["file", "io"],
            trusted_source="skill://public/list_cwd",
            handler=_list_cwd,
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="todo_write",
            description="Record the live task checklist.",
            affinity=["meta", "plan", "ui"],
            trusted_source="skill://public/todo_write",
            handler=_todo_write,
        ),
        verify_tests=False,
    )
    return SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )


def test_native_public_checkpoint_keeps_only_safe_public_prose():
    assert (
        _native_public_checkpoint("Update: 我先核对消息桥接层，确认事件是否按顺序进入主对话。")
        == "我先核对消息桥接层，确认事件是否按顺序进入主对话。"
    )
    assert (
        _native_public_checkpoint("Phase 1: I’ll inspect the reducer and verify the stream order.")
        == "I’ll inspect the reducer and verify the stream order."
    )

    blocked = [
        'Action: read_file({"path":"runtime/protocol/items.py"})',
        "我正在调用 read_file 工具。",
        "运行 exec_shell: cat ~/.ssh/id_rsa",
        "token sk-test-should-not-render",
        '```json\n{"tool_use_id":"abc"}\n```',
        "const secret = process.env.API_KEY",
        "正在处理。",
    ]
    for candidate in blocked:
        assert _native_public_checkpoint(candidate) == ""


def test_native_result_checkpoint_uses_neutral_goal_language_for_sources():
    calls = [ToolCall(id="fetch", name="web_fetch", input={"url": "https://example.com"})]
    result_blocks = [
        {
            "content": json.dumps(
                {"title": "Kimi AI product update"},
                ensure_ascii=False,
            )
        }
    ]

    assert _native_result_checkpoint(
        calls,
        result_blocks,
        goal="Research Kimi and Codex streaming UX.",
    ) == (
        "I found usable evidence from “Kimi AI product update”; next I’ll "
        "synthesize what those sources support."
    )
    assert (
        _native_result_checkpoint(
            calls,
            result_blocks,
            goal="调研 Kimi 和 Codex 的流式交互。",
        )
        == "已拿到 《Kimi AI product update》 等可用资料；接下来基于这些证据继续收束判断。"
    )


def test_native_result_checkpoint_scrubs_unsafe_source_titles():
    calls = [ToolCall(id="fetch", name="web_fetch", input={"url": "https://example.com"})]
    result_blocks = [
        {
            "content": json.dumps(
                {"title": "read_file token sk-test-should-not-render"},
                ensure_ascii=False,
            )
        }
    ]

    checkpoint = _native_result_checkpoint(
        calls,
        result_blocks,
        goal="Research current docs.",
    )

    assert checkpoint == (
        "I read 1 webpage body entry; next I’ll synthesize what the text supports."
    )
    assert "read_file" not in checkpoint
    assert "sk-test" not in checkpoint


def _registry_with_task_chain() -> SkillRegistry:
    registry = SkillRegistry()
    for name in (
        "todo_write",
        "deep-research-swarm",
        "deep-research",
        "report-writing",
        "docx",
        "web_search",
    ):
        registry.register(
            Skill(
                name=name,
                description=f"Run {name}.",
                trusted_source=f"skill://public/{name}",
                handler=lambda **_kwargs: {},
            ),
            verify_tests=False,
        )
    return registry


def test_chat_mode_tool_specs_exclude_deep_task_chain():
    specs = build_anthropic_tool_specs(
        _registry_with_task_chain(),
        user_context={"mode": "chat"},
    )
    names = {spec.name for spec in specs}

    assert "todo_write" in names
    assert "web_search" in names
    assert "deep-research-swarm" not in names
    assert "deep-research" not in names
    assert "report-writing" not in names
    assert "docx" not in names


def test_research_mode_tool_specs_keep_deep_task_chain():
    specs = build_anthropic_tool_specs(
        _registry_with_task_chain(),
        user_context={"mode": "swarm"},
    )
    names = {spec.name for spec in specs}

    assert "deep-research-swarm" in names
    assert "report-writing" in names
    assert "docx" in names


def test_code_ui_regression_native_specs_hide_desktop_browser_tools():
    registry = SkillRegistry()
    for name in ("browser_navigate", "live_browser_navigate", "live_browser_state"):
        registry.register(
            Skill(
                name=name,
                description=f"Run {name}.",
                trusted_source=f"skill://public/{name}",
                handler=lambda **_kwargs: {},
            ),
            verify_tests=False,
        )

    specs = build_anthropic_tool_specs(
        registry,
        user_context={"mode": "code", "browser_regression_enabled": True},
    )
    names = {spec.name for spec in specs}

    assert "browser_navigate" in names
    assert not any(name.startswith("live_browser_") for name in names)


def test_allowlist_filter_failure_denies_all_skills(monkeypatch):
    """``filter_allowed_names`` is the agent's tool allow-list gate. If it
    raises, the agent must get NO tools, not the full unfiltered list —
    a broken/unexpected allow-list computation must fail closed."""
    import runtime.execution.misc.skill_policy as skill_policy

    def _boom(names, *, policy=None, agent=None):
        raise TypeError("boom")

    monkeypatch.setattr(skill_policy, "filter_allowed_names", _boom)

    specs = build_anthropic_tool_specs(
        _registry_with_task_chain(),
        agent=SimpleNamespace(agent_id="broken-agent"),
        user_context={"mode": "swarm"},
    )
    assert specs == []


def test_goal_activation_preserves_relevant_tools_after_cap():
    registry = SkillRegistry()
    for idx in range(20):
        registry.register(
            Skill(
                name=f"dummy_{idx}",
                description="Dummy tool.",
                trusted_source=f"skill://public/dummy_{idx}",
                handler=lambda **_kwargs: {},
            ),
            verify_tests=False,
        )
    for name in ("web_search", "fetch_url", "deep-research", "query_skill"):
        registry.register(
            Skill(
                name=name,
                description=f"Run {name}.",
                trusted_source=f"skill://public/{name}",
                handler=lambda **_kwargs: {},
            ),
            verify_tests=False,
        )

    specs = build_anthropic_tool_specs(
        registry,
        max_skills=3,
        goal="调研一个值得进入的细分赛道，输出竞品和风险",
    )
    names = {spec.name for spec in specs}

    assert "web_search" in names
    assert "fetch_url" in names
    assert "deep-research" in names
    assert "query_skill" in names


def test_ultracode_forces_orchestration_into_native_tool_specs() -> None:
    registry = SkillRegistry()
    for idx in range(10):
        registry.register(
            Skill(
                name=f"dummy_{idx}",
                description="Dummy tool.",
                trusted_source=f"skill://public/dummy_{idx}",
                handler=lambda **_kwargs: {},
            ),
            verify_tests=False,
        )
    registry.register(
        Skill(
            name="run_orchestration",
            description="Run deterministic multi-agent orchestration.",
            trusted_source="skill://public/run_orchestration",
            handler=lambda **_kwargs: {},
        ),
        verify_tests=False,
    )

    specs = build_anthropic_tool_specs(
        registry,
        max_skills=1,
        user_context={"mode": "code", "workflow_preset": "audit.ultracode"},
        goal="audit repository",
    )

    assert "run_orchestration" in {spec.name for spec in specs}


def test_personal_research_forces_research_workflow_into_native_tool_specs() -> None:
    registry = SkillRegistry()
    for idx in range(10):
        registry.register(
            Skill(
                name=f"dummy_{idx}",
                description="Dummy tool.",
                trusted_source=f"skill://public/dummy_{idx}",
                handler=lambda **_kwargs: {},
            ),
            verify_tests=False,
        )
    registry.register(
        Skill(
            name="deep-research",
            description="Load the deep research workflow.",
            trusted_source="skill://public/deep-research",
            handler=lambda **_kwargs: {},
        ),
        verify_tests=False,
    )

    specs = build_anthropic_tool_specs(
        registry,
        max_skills=1,
        user_context={"personal_mode": "research"},
        goal="summarize this topic",
    )

    assert "deep-research" in {spec.name for spec in specs}


def test_tool_result_allows_medium_outputs_without_truncating():
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="large_result",
            description="Return a medium sized result.",
            trusted_source="skill://public/large_result",
            handler=lambda **_kwargs: "x" * 5000,
        ),
        verify_tests=False,
    )
    stack = SimpleNamespace(
        executor=SimpleNamespace(registry=registry),
        planner=SimpleNamespace(router=None, planner_model="mock"),
    )

    rendered, is_error = _execute_tool_call(
        stack,
        ToolCall(id="tc_1", name="large_result", input={}),
    )

    assert is_error is False
    assert rendered == "x" * 5000


def test_execute_tool_call_accepts_normalized_call():
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="echo_args",
            description="Echo the provided args.",
            trusted_source="skill://public/echo_args",
            handler=lambda **kwargs: kwargs,
        ),
        verify_tests=False,
    )
    stack = SimpleNamespace(
        executor=SimpleNamespace(registry=registry),
        planner=SimpleNamespace(router=None, planner_model="mock"),
    )

    rendered, is_error = _execute_tool_call(
        stack,
        NormalizedToolCall(
            id="n-1",
            name="echo_args",
            arguments={"value": 7},
            origin="native",
        ),
    )

    assert not is_error
    assert json.loads(rendered) == {"value": 7}


def test_execute_tool_call_accepts_dict_call_shape():
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="echo_args",
            description="Echo the provided args.",
            trusted_source="skill://public/echo_args",
            handler=lambda **kwargs: kwargs,
        ),
        verify_tests=False,
    )
    stack = SimpleNamespace(
        executor=SimpleNamespace(registry=registry),
        planner=SimpleNamespace(router=None, planner_model="mock"),
    )

    rendered, is_error = _execute_tool_call(
        stack,
        {
            "tool_use_id": "dict-1",
            "tool": "echo_args",
            "arguments": {"value": 9},
        },
    )

    assert not is_error
    assert json.loads(rendered) == {"value": 9}


def test_reflection_checkpoint_is_structured_and_todo_limited():
    message = _reflection_checkpoint_message(10, 300)

    assert "<reflection-checkpoint iteration=10" in message
    assert "1. 已完成" in message
    assert "2. 还差" in message
    assert "3. 当前 plan 是否仍然合理" in message
    assert "4. 下一步动作" in message
    assert "本轮只允许思考或调用 `todo_write`" in message


def test_agentic_tool_call_uses_session_workspace_path(tmp_path):
    marker = tmp_path / "ONLY_TARGET.txt"
    marker.write_text("target", encoding="utf-8")
    stack = _stack()
    session = Session(
        agent=_agent(),
        thread_id="thread-1",
        metadata={
            "mode": "code",
            "workspace_path": str(tmp_path),
            "sandbox_mode": "sandbox",
        },
    )

    with session_scope(session):
        output, is_error = _execute_tool_call(
            stack,
            ToolCall(id="tool-1", name="list_cwd", input={"path": "."}),
        )

    assert not is_error
    data = json.loads(output)
    assert data["path"] == str(tmp_path.resolve())
    assert {item["name"] for item in data["items"]} == {"ONLY_TARGET.txt"}


def test_agentic_tool_call_injects_workspace_for_omitted_dot_path(tmp_path):
    marker = tmp_path / "ONLY_TARGET.txt"
    marker.write_text("target", encoding="utf-8")
    stack = _stack()
    session = Session(
        agent=_agent(),
        thread_id="thread-omitted-path",
        metadata={"mode": "code", "workspace_path": str(tmp_path)},
    )

    with session_scope(session):
        output, is_error = _execute_tool_call(
            stack,
            ToolCall(id="tool-omitted", name="list_cwd", input={}),
        )

    assert not is_error
    data = json.loads(output)
    assert data["path"] == str(tmp_path.resolve())
    assert {item["name"] for item in data["items"]} == {"ONLY_TARGET.txt"}


def test_agentic_stream_carries_scope_metadata_into_tool_thread(tmp_path):
    marker = tmp_path / "ONLY_TARGET.txt"
    marker.write_text("target", encoding="utf-8")

    class Router:
        def __init__(self):
            self.calls = 0

        def call_stream(self, _request):
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="tool-1",
                        name="list_cwd",
                        input={"path": "."},
                    ),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="", tool_calls=[]),
                )
                return
            yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="done"),
            )

    intent = ParsedIntent(
        raw="分析项目",
        intent_type="task",
        normalized_goal="分析项目",
        user_context={
            "conversation_id": "thread-1",
            "metadata": {
                "mode": "code",
                "workspace_path": str(tmp_path),
                "sandbox_mode": "sandbox",
            },
        },
    )

    events = list(stream_agentic_fallback(_stack(Router()), intent, _agent()))
    tool_end = next(event for event in events if event[0] == "tool_end")

    assert "ONLY_TARGET.txt" in tool_end[1]["output"]


def test_agentic_stream_rebinds_workspace_on_every_generator_resume(tmp_path):
    marker = tmp_path / "ONLY_TARGET.txt"
    marker.write_text("fresh-context-marker", encoding="utf-8")
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="read_file",
            description="Read one file.",
            affinity=["file", "io"],
            trusted_source="skill://public/read_file",
            handler=_read_file,
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.calls = 0

        def call_stream(self, _request):
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="read",
                        name="read_file",
                        input={"path": "ONLY_TARGET.txt"},
                    ),
                )
            else:
                yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(type="done", final=ModelResponse(text=""))

    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=Router(), planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="read the selected project file",
        intent_type="task",
        normalized_goal="read the selected project file",
        user_context={
            "conversation_id": "fresh-context-read",
            "metadata": {"mode": "code", "workspace_path": str(tmp_path)},
        },
    )
    stream = stream_agentic_fallback(stack, intent, _agent())
    events = []
    while True:
        try:
            # Mirrors realtime pumps that resume the same generator through a
            # fresh copied Context after each yielded protocol event.
            events.append(contextvars.Context().run(next, stream))
        except StopIteration:
            break

    tool_end = next(event for event in events if event[0] == "tool_end")
    assert tool_end[1]["is_error"] is False
    assert "fresh-con" in tool_end[1]["output"]


def test_registered_run_tests_gets_workspace_in_fresh_resume_context(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    registry = SkillRegistry()
    register_code_quality_skills(registry)

    class Router:
        def __init__(self):
            self.calls = 0

        def call_stream(self, _request):
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(id="tests", name="run_tests", input={}),
                )
            else:
                yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(type="done", final=ModelResponse(text=""))

    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=Router(), planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="run the focused tests",
        intent_type="task",
        normalized_goal="run the focused tests",
        user_context={
            "conversation_id": "fresh-context-tests",
            "metadata": {"mode": "code", "workspace_path": str(tmp_path)},
        },
    )
    quality_agent = SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        extra_skills=["run_tests"],
        soul="",
    )
    stream = stream_agentic_fallback(stack, intent, quality_agent)
    events = []
    while True:
        try:
            events.append(contextvars.Context().run(next, stream))
        except StopIteration:
            break

    tool_end = next(event for event in events if event[0] == "tool_end")
    assert tool_end[1]["is_error"] is False
    assert '"success": true' in tool_end[1]["output"]
    assert "missing cwd" not in tool_end[1]["output"]


def test_agentic_stream_asserts_todo_write_capability():
    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="done"),
            )

    router = Router()
    intent = ParsedIntent(
        raw="use todo_write",
        intent_type="task",
        normalized_goal="use todo_write",
        user_context={"conversation_id": "thread-1"},
    )

    events = list(stream_agentic_fallback(_stack_with_todo(router), intent, _agent()))

    assert any(event[0] == "done" for event in events)
    first_request = router.requests[0]
    system_text = "\n".join(
        msg.content
        for msg in first_request.messages
        if msg.role == "system" and isinstance(msg.content, str)
    )
    assert "You DO have a `todo_write` tool" in system_text
    assert "Do not say `todo_write` is unavailable" in system_text
    tool_names = [tool.name for tool in first_request.tools]
    assert "todo_write" in tool_names
    assert tool_names.count("todo_write") == 1
    # Naming an optional progress tool must advertise it without forcing a
    # tool round; enforcement now comes only from structured todo policies.
    assert first_request.require_tool_use is False


def test_agentic_stream_bootstraps_plan_before_workspace_tools() -> None:
    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            call_index = len(self.requests)
            if call_index == 1:
                call = ToolCall(
                    id="plan-start",
                    name="todo_write",
                    input={
                        "items": [
                            {"content": "Inspect workspace", "status": "in_progress"},
                            {"content": "Summarize findings", "status": "pending"},
                        ]
                    },
                )
            elif call_index == 2:
                call = ToolCall(id="inspect", name="list_cwd", input={"path": "."})
            elif call_index == 3:
                call = ToolCall(
                    id="plan-finish",
                    name="todo_write",
                    input={
                        "items": [
                            {"content": "Inspect workspace", "status": "completed"},
                            {"content": "Summarize findings", "status": "completed"},
                        ]
                    },
                )
            else:
                yield ModelStreamEvent(type="text_delta", delta="done")
                yield ModelStreamEvent(type="done", final=ModelResponse(text="done"))
                return
            yield ModelStreamEvent(type="tool_use", tool_call=call)
            yield ModelStreamEvent(type="done", final=ModelResponse(text="", tool_calls=[call]))

    router = Router()
    intent = ParsedIntent(
        raw="研究项目架构，核对关键模块并整理一份完整结论",
        intent_type="task",
        normalized_goal="研究项目架构，核对关键模块并整理一份完整结论",
        user_context={
            "conversation_id": "thread-plan-first",
            "todo_policy": "required",
        },
    )

    events = list(stream_agentic_fallback(_stack_with_todo(router), intent, _agent()))

    starts = [payload["name"] for kind, payload, _ in events if kind == "tool_start"]
    assert starts[:3] == ["todo_write", "list_cwd", "todo_write"]
    assert [tool.name for tool in router.requests[0].tools] == ["todo_write"]
    assert {tool.name for tool in router.requests[1].tools} >= {"todo_write", "list_cwd"}


def test_agentic_stream_executes_named_xml_fallback_without_leaking_markup():
    class Router:
        def __init__(self):
            self.calls = 0

        def call_stream(self, _request):
            self.calls += 1
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="text_delta",
                    delta=(
                        "starting\n<tool_calls>\n"
                        '<tool_call name="todo_write">\n'
                        '<tool_call name="todos">'
                        '[{"content":"fix","status":"in_progress"}]'
                        "</tool_call>\n</tool_calls>"
                    ),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="", tool_calls=[]),
                )
                return
            yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="done"))

    events = list(
        stream_agentic_fallback(
            _stack_with_todo(Router()),
            ParsedIntent(
                raw="use checklist",
                intent_type="task",
                normalized_goal="use checklist",
                user_context={"conversation_id": "thread-xml"},
            ),
            _agent(),
        )
    )

    assert any(event[0] == "tool_end" and event[1]["name"] == "todo_write" for event in events)
    visible = "".join(event[1] for event in events if event[0] == "text")
    assert visible == "done"
    assert "<tool_call" not in visible


def test_agentic_stream_fails_over_from_unavailable_provider(monkeypatch):
    class Router:
        def __init__(self):
            self.models = []

        def call_stream(self, request):
            self.models.append(request.model)
            if request.model == "unfunded-code-model":
                raise RuntimeError("http_402: insufficient_balance")
            yield ModelStreamEvent(type="text_delta", delta="recovered")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="recovered"))

    monkeypatch.setattr(
        tool_bridge,
        "_next_custom_model_fallback",
        lambda _current, _attempted: "fallback-code-model",
    )
    router = Router()

    events = list(
        stream_agentic_fallback(
            _stack(router),
            ParsedIntent(
                raw="inspect project",
                intent_type="task",
                normalized_goal="inspect project",
                user_context={"conversation_id": "thread-provider-failover"},
            ),
            _agent(),
            model="unfunded-code-model",
        )
    )

    assert router.models == ["unfunded-code-model", "fallback-code-model"]
    assert "".join(event[1] for event in events if event[0] == "text") == "recovered"


def test_agentic_stream_sticks_to_model_that_served_tool_round(tmp_path):
    class Router:
        def __init__(self):
            self.models = []

        def call_stream(self, request):
            self.models.append(request.model)
            if len(self.models) == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(id="list-1", name="list_cwd", input={"path": "."}),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="", model="healthy-model"),
                )
                return
            yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="done", model="healthy-model"),
            )

    router = Router()
    events = list(
        stream_agentic_fallback(
            _stack(router),
            ParsedIntent(
                raw="inspect project",
                intent_type="task",
                normalized_goal="inspect project",
                user_context={
                    "conversation_id": "thread-sticky-provider",
                    "mode": "code",
                    "workspace_path": str(tmp_path),
                },
            ),
            _agent(),
            model="unfunded-model",
        )
    )

    assert router.models == ["unfunded-model", "healthy-model"]
    assert any(event[0] == "tool_end" for event in events)


def test_agentic_stream_injects_relevant_memory_hub_records(tmp_path, monkeypatch):
    from runtime.memory import user_store

    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    user_store.add_fact(
        "Octopus deploys must use blue green rollout.",
        category="ops",
        source="manual",
        scope="project",
        project=str(tmp_path),
    )

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="done"),
            )

    router = Router()
    intent = ParsedIntent(
        raw="Plan Octopus rollout",
        intent_type="task",
        normalized_goal="Plan Octopus rollout",
        user_context={
            "conversation_id": "thread-1",
            "workspace_path": str(tmp_path),
        },
    )

    events = list(stream_agentic_fallback(_stack(router), intent, _agent()))

    assert any(event[0] == "done" for event in events)
    system_text = "\n".join(
        msg.content
        for msg in router.requests[0].messages
        if msg.role == "system" and isinstance(msg.content, str)
    )
    assert "RELEVANT LONG-TERM MEMORY" in system_text
    assert "blue green rollout" in system_text


def test_agentic_stream_injects_team_memory_hub_records(tmp_path, monkeypatch):
    monkeypatch.setenv("OCTOPUS_HOME", str(tmp_path / "home"))
    monkeypatch.chdir(tmp_path)
    team_core = tmp_path / "teams" / "Alpha-Team" / "team-core"
    team_core.mkdir(parents=True)
    (team_core / "MEMORY.md").write_text(
        "- Alpha team requires release captain reviews\n",
        encoding="utf-8",
    )

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="done"),
            )

    router = Router()
    intent = ParsedIntent(
        raw="Plan release captain rollout",
        intent_type="task",
        normalized_goal="Plan release captain rollout",
        user_context={
            "conversation_id": "thread-1",
            "workspace_path": str(tmp_path),
            "metadata": {"team_id": "Alpha Team"},
        },
    )

    events = list(stream_agentic_fallback(_stack(router), intent, _agent()))

    assert any(event[0] == "done" for event in events)
    system_text = "\n".join(
        msg.content
        for msg in router.requests[0].messages
        if msg.role == "system" and isinstance(msg.content, str)
    )
    assert "RELEVANT LONG-TERM MEMORY" in system_text
    assert "memory_md:team" in system_text
    assert "release captain reviews" in system_text


def test_agentic_stream_requires_todo_before_complex_final():
    class Router:
        def __init__(self):
            self.calls = 0
            self.requests = []

        def call_stream(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                yield ModelStreamEvent(type="text_delta", delta="premature")
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="premature"),
                )
                return
            if self.calls == 2:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="todo-1",
                        name="todo_write",
                        input={
                            "todos": [
                                {
                                    "text": "Confirm the task shape",
                                    "status": "completed",
                                },
                                {
                                    "text": "Run the requested checks",
                                    "status": "completed",
                                },
                            ],
                        },
                    ),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="", tool_calls=[]),
                )
                return
            yield ModelStreamEvent(type="text_delta", delta="final")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="final"),
            )

    router = Router()
    intent = ParsedIntent(
        raw="analyze the frontend and run tests",
        intent_type="task",
        normalized_goal="analyze the frontend and run tests",
        user_context={
            "conversation_id": "thread-1",
            "todo_policy": "required",
            "metadata": {"mode": "code"},
        },
    )

    events = list(stream_agentic_fallback(_stack_with_todo(router), intent, _agent()))

    assert router.calls == 3
    assert any(event[0] == "tool_start" and event[1]["name"] == "todo_write" for event in events)
    assert events[-1] == ("done", "", "final")

    second_request_text = "\n".join(
        str(msg.content) for msg in router.requests[1].messages if msg.role == "user"
    )
    assert "task checklist required" in second_request_text


def test_agentic_stream_requires_todo_update_after_tools(tmp_path):
    marker = tmp_path / "ONLY_TARGET.txt"
    marker.write_text("target", encoding="utf-8")

    class Router:
        def __init__(self):
            self.calls = 0
            self.requests = []

        def call_stream(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="todo-1",
                        name="todo_write",
                        input={
                            "todos": [
                                {
                                    "text": "Inspect the workspace",
                                    "status": "in_progress",
                                },
                            ],
                        },
                    ),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="", tool_calls=[]),
                )
                return
            if self.calls == 2:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="tool-1",
                        name="list_cwd",
                        input={"path": "."},
                    ),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="", tool_calls=[]),
                )
                return
            if self.calls == 3:
                yield ModelStreamEvent(type="text_delta", delta="premature")
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="premature"),
                )
                return
            if self.calls == 4:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="todo-2",
                        name="todo_write",
                        input={
                            "todos": [
                                {
                                    "text": "Inspect the workspace",
                                    "status": "completed",
                                },
                            ],
                        },
                    ),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="", tool_calls=[]),
                )
                return
            yield ModelStreamEvent(type="text_delta", delta="final")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="final"),
            )

    router = Router()
    intent = ParsedIntent(
        raw="inspect the project and summarize it",
        intent_type="task",
        normalized_goal="inspect the project and summarize it",
        user_context={
            "conversation_id": "thread-1",
            "todo_policy": "required",
            "metadata": {
                "mode": "code",
                "workspace_path": str(tmp_path),
                "sandbox_mode": "sandbox",
            },
        },
    )

    events = list(stream_agentic_fallback(_stack_with_todo(router), intent, _agent()))

    assert router.calls == 5
    todo_starts = [
        event for event in events if event[0] == "tool_start" and event[1]["name"] == "todo_write"
    ]
    assert len(todo_starts) == 2
    assert events[-1] == ("done", "", "final")

    fourth_request_text = "\n".join(
        str(msg.content) for msg in router.requests[3].messages if msg.role == "user"
    )
    assert "checklist update required" in fourth_request_text


def test_agentic_code_change_cannot_finalize_after_failed_verification():
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="edit_file",
            description="Edit source.",
            affinity=["file", "edit"],
            trusted_source="skill://public/edit_file",
            handler=lambda **_kwargs: {"ok": True},
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="run_tests",
            description="Run focused tests.",
            affinity=["quality", "test"],
            trusted_source="skill://public/run_tests",
            handler=lambda pass_now=False, **_kwargs: (
                {"ok": True} if pass_now else {"error": "one regression failed"}
            ),
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.calls = 0
            self.requests = []

        def call_stream(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="edit-1",
                        name="edit_file",
                        input={"path": "new_file.py"},
                    ),
                )
            elif self.calls == 2:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="test-1",
                        name="run_tests",
                        input={"pass_now": False},
                    ),
                )
            elif self.calls == 3:
                yield ModelStreamEvent(type="text_delta", delta="paused")
            elif self.calls == 4:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="test-2",
                        name="run_tests",
                        input={"pass_now": True},
                    ),
                )
            else:
                yield ModelStreamEvent(type="text_delta", delta="fixed and verified")
            yield ModelStreamEvent(type="done", final=ModelResponse(text=""))

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="fix the vulnerability and add regression tests",
        intent_type="task",
        normalized_goal="fix the vulnerability and add regression tests",
        user_context={"conversation_id": "code-guard", "metadata": {"mode": "code"}},
    )

    code_agent = SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        extra_skills=["edit_file", "run_tests"],
        soul="",
    )
    events = list(stream_agentic_fallback(stack, intent, code_agent))

    assert router.calls == 5
    assert "paused" not in "".join(event[1] for event in events if event[0] == "text")
    assert events[-1] == ("done", "", "fixed and verified")
    assert router.requests[0].require_tool_use is True
    assert router.requests[-1].require_tool_use is False
    retry_prompt = "\n".join(
        str(message.content) for message in router.requests[3].messages if message.role == "user"
    )
    assert "implementation not verified" in retry_prompt
    assert "latest verification failed" in retry_prompt.lower()


def test_agentic_code_change_does_not_treat_lint_as_behavior_verification():
    registry = SkillRegistry()
    for name, affinity in (
        ("edit_file", ["file", "edit"]),
        ("lint_check", ["quality", "lint"]),
        ("run_tests", ["quality", "test"]),
    ):
        registry.register(
            Skill(
                name=name,
                description=name,
                affinity=affinity,
                trusted_source=f"skill://public/{name}",
                handler=lambda **_kwargs: {"success": True, "exit_code": 0},
            ),
            verify_tests=False,
        )

    class Router:
        def __init__(self):
            self.calls = 0
            self.requests = []

        def call_stream(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                call = ToolCall(id="edit", name="edit_file", input={"path": "new.py"})
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            elif self.calls == 2:
                call = ToolCall(id="lint", name="lint_check", input={})
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            elif self.calls == 3:
                yield ModelStreamEvent(type="text_delta", delta="lint passed")
            elif self.calls == 4:
                call = ToolCall(id="tests", name="run_tests", input={})
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            else:
                yield ModelStreamEvent(type="text_delta", delta="verified")
            yield ModelStreamEvent(type="done", final=ModelResponse(text=""))

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="implement the cache behavior",
        intent_type="task",
        normalized_goal="implement the cache behavior",
        user_context={"conversation_id": "lint-is-not-tests", "metadata": {"mode": "code"}},
    )
    agent = SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        extra_skills=["edit_file", "lint_check", "run_tests"],
        soul="",
    )

    events = list(stream_agentic_fallback(stack, intent, agent))

    assert router.calls == 5
    assert router.requests[2].require_tool_use is True
    assert router.requests[-1].require_tool_use is False
    assert "lint passed" not in "".join(event[1] for event in events if event[0] == "text")
    assert events[-1] == ("done", "", "verified")


def test_agentic_double_green_converges_through_todo_without_redundant_probe():
    registry = SkillRegistry()
    for name, affinity in (
        ("todo_write", ["meta"]),
        ("edit_file", ["file", "edit"]),
        ("run_tests", ["quality", "test"]),
        ("lint_check", ["quality", "lint"]),
    ):
        registry.register(
            Skill(
                name=name,
                description=name,
                affinity=affinity,
                trusted_source=f"skill://public/{name}",
                handler=lambda **_kwargs: {"success": True, "exit_code": 0},
            ),
            verify_tests=False,
        )

    class Router:
        def __init__(self):
            self.calls = 0
            self.requests = []

        def call_stream(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                call = ToolCall(id="todo-start", name="todo_write", input={"items": []})
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            elif self.calls == 2:
                call = ToolCall(id="edit", name="edit_file", input={"path": "cache.py"})
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            elif self.calls == 3:
                call = ToolCall(id="tests", name="run_tests", input={})
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            elif self.calls == 4:
                call = ToolCall(id="lint", name="lint_check", input={})
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            elif self.calls == 5:
                allowed = [tool.name for tool in request.tools]
                if allowed == ["todo_write"]:
                    call = ToolCall(id="todo-done", name="todo_write", input={"items": []})
                else:  # Regression shape: the old loop allowed another test probe.
                    call = ToolCall(id="redundant-tests", name="run_tests", input={})
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            else:
                yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(type="done", final=ModelResponse(text=""))

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="implement and verify the cache behavior",
        intent_type="task",
        normalized_goal="implement and verify the cache behavior",
        user_context={
            "conversation_id": "green-convergence",
            "todo_policy": "required",
            "metadata": {"mode": "code"},
        },
    )
    agent = SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        extra_skills=["todo_write", "edit_file", "run_tests", "lint_check"],
        soul="",
    )

    events = list(stream_agentic_fallback(stack, intent, agent))

    started = [event[1]["name"] for event in events if event[0] == "tool_start"]
    assert started == ["todo_write", "edit_file", "run_tests", "lint_check", "todo_write"]
    assert [tool.name for tool in router.requests[4].tools] == ["todo_write"]
    assert router.requests[4].require_tool_use is True
    assert router.requests[5].tools == []
    assert router.requests[5].require_tool_use is False
    assert events[-1] == ("done", "", "done")


def test_agentic_concurrency_semantic_guard_forces_repair_before_verification():
    registry = SkillRegistry()
    for name, affinity in (
        ("write_text_file", ["file", "write"]),
        ("edit_file", ["file", "edit"]),
        ("run_tests", ["quality", "test"]),
        ("lint_check", ["quality", "lint"]),
    ):
        registry.register(
            Skill(
                name=name,
                description=name,
                affinity=affinity,
                trusted_source=f"skill://public/{name}",
                handler=lambda **_kwargs: {"success": True, "exit_code": 0},
            ),
            verify_tests=False,
        )

    bad = """\
pending = self._pending.get(key)
if pending is not None:
    event, result, exc = pending
    event.wait()
    finished = self._pending.get(key, pending)
    return finished[1]
event = threading.Event()
self._pending[key] = (event, None, None)
value = loader()
self._pending[key] = (event, value, None)
event.set()
del self._pending[key]
"""
    good = """\
pending = self._pending.get(key)
is_leader = pending is None
if is_leader:
    pending = Pending()
    self._pending[key] = pending
if not is_leader:
    pending.event.wait()
    return pending.result
value = loader()
pending.result = value
pending.event.set()
"""

    class Router:
        def __init__(self):
            self.calls = 0
            self.requests = []

        def call_stream(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                call = ToolCall(
                    id="bad-write",
                    name="write_text_file",
                    input={"path": "cache.py", "content": bad},
                )
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            elif self.calls == 2:
                call = ToolCall(
                    id="repair",
                    name="edit_file",
                    input={"path": "cache.py", "old_string": bad, "new_string": good},
                )
                yield ModelStreamEvent(type="tool_use", tool_call=call)
            elif self.calls == 3:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(id="tests", name="run_tests", input={}),
                )
            elif self.calls == 4:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(id="lint", name="lint_check", input={}),
                )
            else:
                yield ModelStreamEvent(type="text_delta", delta="fixed")
            yield ModelStreamEvent(type="done", final=ModelResponse(text=""))

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="implement the concurrent cache and verify it",
        intent_type="task",
        normalized_goal="implement the concurrent cache and verify it",
        user_context={"conversation_id": "semantic-repair", "metadata": {"mode": "code"}},
    )
    agent = SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        extra_skills=["write_text_file", "edit_file", "run_tests", "lint_check"],
        soul="",
    )

    events = list(stream_agentic_fallback(stack, intent, agent))

    repair_request = "\n".join(
        str(message.content) for message in router.requests[1].messages if message.role == "user"
    )
    assert "immutable pending tuple" in repair_request
    assert "concurrency semantic repair required" in repair_request
    assert router.requests[1].require_tool_use is True
    assert router.requests[-1].tools == []
    assert events[-1] == ("done", "", "fixed")


def test_agentic_code_change_cannot_finalize_without_any_mutation():
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="todo_write",
            description="Track work.",
            affinity=["meta"],
            trusted_source="skill://public/todo_write",
            handler=lambda **_kwargs: {"ok": True},
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="edit_file",
            description="Edit source.",
            affinity=["file", "edit"],
            trusted_source="skill://public/edit_file",
            handler=lambda **_kwargs: {"ok": True},
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="run_tests",
            description="Run tests.",
            affinity=["quality", "test"],
            trusted_source="skill://public/run_tests",
            handler=lambda **_kwargs: {"ok": True},
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.calls = 0
            self.requests = []

        def call_stream(self, request):
            self.calls += 1
            self.requests.append(request)
            if self.calls == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="todo-1",
                        name="todo_write",
                        input={"items": [{"content": "fix", "status": "in_progress"}]},
                    ),
                )
            elif self.calls == 2:
                # Provider emits an empty stop after planning.
                pass
            elif self.calls == 3:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="edit-1",
                        name="edit_file",
                        input={"path": "new_file.py"},
                    ),
                )
            elif self.calls == 4:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(id="test-1", name="run_tests", input={}),
                )
            elif self.calls == 5:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="todo-2",
                        name="todo_write",
                        input={"items": [{"content": "fix", "status": "completed"}]},
                    ),
                )
            else:
                yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(type="done", final=ModelResponse(text=""))

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    agent = SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        extra_skills=["todo_write", "edit_file", "run_tests"],
        soul="",
    )
    intent = ParsedIntent(
        raw="fix the vulnerability and run tests",
        intent_type="task",
        normalized_goal="fix the vulnerability and run tests",
        user_context={"conversation_id": "zero-mutation", "metadata": {"mode": "code"}},
    )

    events = list(stream_agentic_fallback(stack, intent, agent))

    assert router.calls == 6
    assert events[-1] == ("done", "", "done")
    retry_prompt = "\n".join(
        str(message.content) for message in router.requests[2].messages if message.role == "user"
    )
    assert "No successful source or regression-test mutation" in retry_prompt


def test_agentic_code_change_switches_model_after_two_no_action_stops(monkeypatch):
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="edit_file",
            description="Edit source.",
            affinity=["file", "edit"],
            trusted_source="skill://public/edit_file",
            handler=lambda **_kwargs: {"ok": True},
        ),
        verify_tests=False,
    )
    registry.register(
        Skill(
            name="run_tests",
            description="Run tests.",
            affinity=["quality", "test"],
            trusted_source="skill://public/run_tests",
            handler=lambda **_kwargs: {"ok": True},
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.models = []
            self.chat_calls = 0

        def call_stream(self, request):
            self.models.append(request.model)
            if request.model == "deepseek-v4-pro":
                yield ModelStreamEvent(type="text_delta", delta="paused")
            else:
                self.chat_calls += 1
                if self.chat_calls == 1:
                    yield ModelStreamEvent(
                        type="tool_use",
                        tool_call=ToolCall(
                            id="edit-chat",
                            name="edit_file",
                            input={"path": "new_file.py"},
                        ),
                    )
                elif self.chat_calls == 2:
                    yield ModelStreamEvent(
                        type="tool_use",
                        tool_call=ToolCall(id="tests-chat", name="run_tests", input={}),
                    )
                else:
                    yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(type="done", final=ModelResponse(text=""))

    monkeypatch.setattr(
        tool_bridge,
        "_next_custom_model_fallback",
        lambda _current, attempted: "deepseek-chat" if "deepseek-chat" not in attempted else None,
    )
    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    agent = SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        extra_skills=["edit_file", "run_tests"],
        soul="",
    )
    intent = ParsedIntent(
        raw="fix the vulnerability and run tests",
        intent_type="task",
        normalized_goal="fix the vulnerability and run tests",
        user_context={"conversation_id": "quality-fallback", "metadata": {"mode": "code"}},
    )

    events = list(
        stream_agentic_fallback(
            stack,
            intent,
            agent,
            model="deepseek-v4-pro",
        )
    )

    assert router.models == [
        "deepseek-v4-pro",
        "deepseek-v4-pro",
        "deepseek-chat",
        "deepseek-chat",
        "deepseek-chat",
    ]
    assert events[-1] == ("done", "", "done")


def test_agentic_code_prompt_asserts_real_tool_availability():
    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            yield ModelStreamEvent(type="text_delta", delta="blocked")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="blocked"))

    registry = SkillRegistry()
    for name in ("read_file", "edit_file", "run_tests"):
        registry.register(
            Skill(
                name=name,
                description=f"Use {name}.",
                affinity=["quality"] if name == "run_tests" else ["file"],
                trusted_source=f"skill://public/{name}",
                handler=lambda **_kwargs: {"ok": True},
            ),
            verify_tests=False,
        )
    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    agent = SimpleNamespace(
        agent_id="coder",
        capabilities={"code_mode_unlock": True},
        extra_skills=["read_file", "edit_file", "run_tests"],
        soul="",
    )
    intent = ParsedIntent(
        raw="fix the cache bug and run tests",
        intent_type="task",
        normalized_goal="fix the cache bug and run tests",
        user_context={"conversation_id": "tool-assertion", "metadata": {"mode": "code"}},
    )

    list(stream_agentic_fallback(stack, intent, agent, model="mock"))

    system_text = "\n".join(
        str(message.content) for message in router.requests[0].messages if message.role == "system"
    )
    assert "These tools are enabled in this turn" in system_text
    assert "`read_file`" in system_text
    assert "`edit_file`" in system_text
    assert "`run_tests`" in system_text
    assert "Do not claim tools are unavailable" in system_text


def test_agentic_stream_prompts_for_user_decision_at_round_cap(monkeypatch):
    monkeypatch.setattr(tool_bridge, "MAX_TOOL_ROUNDS", 2)

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            if request.tools:
                yield ModelStreamEvent(
                    type="text_delta",
                    delta="I will inspect first. ",
                )
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id=f"tool-{len(self.requests)}",
                        name="list_cwd",
                        input={"path": "."},
                    ),
                )
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text="", tool_calls=[]),
                )
                return
            yield ModelStreamEvent(
                type="text_delta",
                delta="Reached the work limit. Reply `继续` or `生成报告`.",
            )
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="Reached the work limit. Reply `继续` or `生成报告`.",
                ),
            )

    router = Router()
    intent = ParsedIntent(
        raw="write a research report",
        intent_type="task",
        normalized_goal="write a research report",
        user_context={"conversation_id": "thread-1"},
    )

    events = list(stream_agentic_fallback(_stack(router), intent, _agent()))

    assert len(router.requests) == 3
    assert router.requests[-1].tools == []
    assert any(
        "user decision required" in str(msg.content)
        and "Do not write the final report yet" in str(msg.content)
        for msg in router.requests[-1].messages
        if msg.role == "user"
    )
    assert events[-1] == (
        "done",
        "",
        "Reached the work limit. Reply `继续` or `生成报告`.",
    )


def test_narrow_remote_research_forces_final_after_soft_budget(monkeypatch):
    monkeypatch.setattr(tool_bridge, "NARROW_WEB_RESEARCH_ROUND_BUDGET", 2)

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            if request.tools:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id=f"web-{len(self.requests)}",
                        name="web_search",
                        input={"query": "Codex CLI interrupt official source"},
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(
                type="text_delta",
                delta="Press Esc to interrupt the current task. Source: OpenAI docs.",
            )
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="Press Esc to interrupt the current task. Source: OpenAI docs."
                ),
            )

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="web_search",
            description="Search the web.",
            trusted_source="skill://public/web_search",
            handler=lambda **_kwargs: {
                "title": "Codex CLI features",
                "url": "https://developers.openai.com/codex/cli/features",
            },
        ),
        verify_tests=False,
    )
    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    goal = (
        "Find one official source and answer in one sentence. "
        "Do not read local project files or execute local commands."
    )
    intent = ParsedIntent(
        raw=goal,
        intent_type="task",
        normalized_goal=goal,
        user_context={"conversation_id": "narrow-web-budget"},
    )

    web_agent = SimpleNamespace(
        agent_id="researcher",
        capabilities={"code_mode_unlock": True},
        extra_skills=["web_search"],
        soul="",
    )
    events = list(stream_agentic_fallback(stack, intent, web_agent))

    assert len(router.requests) == 3
    assert router.requests[0].tools
    assert router.requests[1].tools
    assert router.requests[2].tools == []
    assert any(
        "evidence budget reached" in str(message.content)
        for message in router.requests[2].messages
        if message.role == "user"
    )
    assert any(event[0] == "commentary_runtime" and "证据收集预算" in event[1] for event in events)
    assert events[-1] == (
        "done",
        "",
        "Press Esc to interrupt the current task. Source: OpenAI docs.",
    )


def test_native_tool_round_budget_preserves_more_room_for_long_work():
    narrow = tool_bridge._native_tool_round_budget(
        "Find one official source and give a brief conclusion",
        workspace_contract="no_local_access",
        code_change_task=False,
    )
    research = tool_bridge._native_tool_round_budget(
        "Research and compare eight reliable web sources",
        workspace_contract="no_local_access",
        code_change_task=False,
    )
    code = tool_bridge._native_tool_round_budget(
        "Implement the change and verify it",
        workspace_contract=None,
        code_change_task=True,
    )

    assert narrow < research < code < tool_bridge.MAX_TOOL_ROUNDS


def test_native_model_stream_deadline_recovers_from_silent_provider():
    release = threading.Event()

    class Router:
        def call_stream(self, _request):
            release.wait(timeout=2)
            yield ModelStreamEvent(type="done", final=ModelResponse(text="late"))

    started = time.monotonic()
    events = list(
        tool_bridge._iter_native_model_stream_with_deadline(
            Router(),
            object(),
            0.03,
        )
    )
    elapsed = time.monotonic() - started
    release.set()

    assert events == [tool_bridge._NATIVE_STREAM_DEADLINE]
    assert elapsed < 0.5


def test_native_model_stream_deadline_ignores_nonvisible_heartbeat_events():
    visible_chunks: list[str] = []

    class Router:
        def call_stream(self, _request):
            yield ModelStreamEvent(type="text_delta", delta="可见回答")
            for _ in range(100):
                time.sleep(0.005)
                yield ModelStreamEvent(type="thinking_delta", delta="internal")

    started = time.monotonic()
    events = []
    for event in tool_bridge._iter_native_model_stream_with_deadline(
        Router(),
        object(),
        0.03,
        visible_started=lambda: len(visible_chunks),
    ):
        events.append(event)
        if getattr(event, "type", "") == "text_delta":
            visible_chunks.append(event.delta)
    elapsed = time.monotonic() - started

    assert events[-1] is tool_bridge._NATIVE_STREAM_DEADLINE
    assert elapsed < 0.2


def test_native_convergence_retry_uses_shorter_timeout(monkeypatch):
    monkeypatch.setenv("OCTOPUS_NATIVE_MODEL_RECOVERY_TIMEOUT_S", "30")

    assert tool_bridge._native_model_recovery_timeout_s(120.0) == 30.0
    assert tool_bridge._native_model_recovery_timeout_s(12.0) == 12.0


def test_native_post_tool_round_uses_shorter_silence_timeout(monkeypatch):
    monkeypatch.setenv("OCTOPUS_NATIVE_POST_TOOL_TIMEOUT_S", "60")

    assert tool_bridge._native_post_tool_timeout_s(120.0) == 60.0
    assert tool_bridge._native_post_tool_timeout_s(15.0) == 15.0


def test_agentic_timeout_emits_public_recovery_then_forces_final(monkeypatch):
    monkeypatch.setattr(tool_bridge, "_native_model_round_timeout_s", lambda: 0.03)

    class Router:
        def call_stream(self, request):
            if request.tools:
                threading.Event().wait(timeout=1)
                return
            yield ModelStreamEvent(type="text_delta", delta="Final from saved evidence.")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="Final from saved evidence."),
            )

    intent = ParsedIntent(
        raw="research the interaction",
        intent_type="task",
        normalized_goal="research the interaction",
        user_context={"conversation_id": "timeout-thread"},
    )

    events = list(stream_agentic_fallback(_stack(Router()), intent, _agent()))

    commentary_index = next(i for i, event in enumerate(events) if event[0] == "commentary_runtime")
    text_index = next(i for i, event in enumerate(events) if event[0] == "text")
    assert commentary_index < text_index
    assert "超过单轮时限" in events[commentary_index][1]
    assert events[-1] == ("done", "", "Final from saved evidence.")


def test_agentic_timeout_replays_partial_draft_into_complete_recovery(monkeypatch):
    monkeypatch.setattr(tool_bridge, "_native_model_round_timeout_s", lambda: 0.03)

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            if request.tools:
                yield ModelStreamEvent(
                    type="text_delta",
                    delta="First verified point, but the answer is not complete",
                )
                threading.Event().wait(timeout=1)
                return
            assert request.messages[-2].role == "assistant"
            assert "First verified point" in request.messages[-2].content
            final = "First verified point. Second verified point."
            yield ModelStreamEvent(type="text_delta", delta=final)
            yield ModelStreamEvent(type="done", final=ModelResponse(text=final))

    router = Router()
    intent = ParsedIntent(
        raw="compare two verified points",
        intent_type="task",
        normalized_goal="compare two verified points",
        user_context={"conversation_id": "partial-timeout-thread"},
    )

    events = list(stream_agentic_fallback(_stack(router), intent, _agent()))

    text = "".join(event[1] for event in events if event[0] == "text")
    assert text == "First verified point. Second verified point."
    assert events[-1] == (
        "done",
        "",
        "First verified point. Second verified point.",
    )


def test_agentic_post_tool_stall_fails_over_for_final_synthesis(monkeypatch):
    monkeypatch.setattr(tool_bridge, "_native_model_round_timeout_s", lambda: 0.03)
    monkeypatch.setattr(
        tool_bridge,
        "_next_custom_model_fallback",
        lambda current, _attempted: "backup-model" if current != "backup-model" else None,
    )

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            if len(self.requests) == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="evidence-list",
                        name="list_cwd",
                        input={"path": "."},
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            if request.model != "backup-model":
                threading.Event().wait(timeout=1)
                return
            final = "Backup model completed the answer from saved evidence."
            yield ModelStreamEvent(type="text_delta", delta=final)
            yield ModelStreamEvent(type="done", final=ModelResponse(text=final))

    router = Router()
    intent = ParsedIntent(
        raw="inspect the directory and summarize once",
        intent_type="task",
        normalized_goal="inspect the directory and summarize once",
        user_context={"conversation_id": "post-tool-stall-failover-thread"},
    )

    events = list(stream_agentic_fallback(_stack(router), intent, _agent()))

    assert [event[0] for event in events].count("tool_start") == 1
    assert any(request.model == "backup-model" for request in router.requests)
    assert events[-1] == (
        "done",
        "",
        "Backup model completed the answer from saved evidence.",
    )


def test_agentic_repeated_timeout_is_terminal_error_not_answer_text(monkeypatch):
    monkeypatch.setattr(tool_bridge, "_native_model_round_timeout_s", lambda: 0.02)

    class Router:
        def call_stream(self, _request):
            threading.Event().wait(timeout=1)
            if False:
                yield ModelStreamEvent(type="text_delta", delta="unreachable")

    intent = ParsedIntent(
        raw="inspect two files",
        intent_type="task",
        normalized_goal="inspect two files",
        user_context={"conversation_id": "repeated-timeout-thread"},
    )

    events = list(stream_agentic_fallback(_stack(Router()), intent, _agent()))

    assert events[-1][0] == "error"
    assert events[-1][1]["kind"] == "model_stall"
    assert all(event[0] != "text" for event in events)


def test_agentic_tool_preamble_becomes_commentary_before_execution():
    class Router:
        def __init__(self):
            self.round = 0

        def call_stream(self, _request):
            self.round += 1
            if self.round == 1:
                yield ModelStreamEvent(
                    type="text_delta",
                    delta="I confirmed the scope; now I will inspect the directory.",
                )
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="tool-1",
                        name="list_cwd",
                        input={"path": "."},
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(type="text_delta", delta="Inspection complete.")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="Inspection complete."),
            )

    intent = ParsedIntent(
        raw="inspect the directory",
        intent_type="task",
        normalized_goal="inspect the directory",
        user_context={"conversation_id": "commentary-thread"},
    )

    events = list(stream_agentic_fallback(_stack(Router()), intent, _agent()))

    commentary_index = next(i for i, event in enumerate(events) if event[0] == "commentary")
    tool_index = next(i for i, event in enumerate(events) if event[0] == "tool_start")
    synthesis_index = next(
        i
        for i, event in enumerate(events)
        if event[0] == "commentary_runtime" and "收束成最终回答" in event[1]
    )
    text_index = next(i for i, event in enumerate(events) if event[0] == "text")
    assert commentary_index < tool_index
    assert tool_index < synthesis_index < text_index
    assert "confirmed the scope" in events[commentary_index][1]


def test_native_duplicate_calls_in_one_round_execute_once():
    execution = {"count": 0}

    def probe(path: str = "."):
        execution["count"] += 1
        return {"path": path, "ok": True}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="list_cwd",
            description="Read one stable target.",
            affinity=["file", "io"],
            trusted_source="skill://public/list_cwd",
            handler=probe,
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.round = 0

        def call_stream(self, _request):
            self.round += 1
            if self.round == 1:
                for call_id in ("duplicate-1", "duplicate-2"):
                    yield ModelStreamEvent(
                        type="tool_use",
                        tool_call=ToolCall(
                            id=call_id,
                            name="list_cwd",
                            input={"path": "same.txt"},
                        ),
                    )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(type="text_delta", delta="Duplicate collapsed.")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="Duplicate collapsed."),
            )

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="inspect one stable target",
        intent_type="task",
        normalized_goal="inspect one stable target",
        user_context={"conversation_id": "native-deduplicate-thread"},
    )

    events = list(stream_agentic_fallback(stack, intent, _agent()))

    assert execution["count"] == 1
    assert [event[0] for event in events].count("tool_start") == 1
    assert [event[0] for event in events].count("tool_end") == 1
    assert events[-1] == ("done", "", "Duplicate collapsed.")


def test_native_definitive_missing_read_is_not_retried():
    execution = {"count": 0}

    def missing_read(path: str, offset: int = 0):
        execution["count"] += 1
        return {"error": f"file not found: {path} at offset {offset}"}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="read_file",
            description="Read one project file.",
            affinity=["file", "io"],
            trusted_source="skill://public/read_file",
            handler=missing_read,
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            if request.tools:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id=f"missing-{len(self.requests)}",
                        name="read_file",
                        input={
                            "path": "missing.ts",
                            "offset": len(self.requests) * 100,
                        },
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(
                type="text_delta",
                delta="The requested file does not exist; I stopped retrying it.",
            )
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="The requested file does not exist; I stopped retrying it."
                ),
            )

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="read the requested project file",
        intent_type="task",
        normalized_goal="read the requested project file",
        user_context={"conversation_id": "native-missing-read-thread"},
    )

    events = list(stream_agentic_fallback(stack, intent, _agent()))

    assert execution["count"] == 1
    assert [event[0] for event in events].count("tool_start") == 1
    assert [event[0] for event in events].count("tool_end") == 1
    assert router.requests[-1].tools == []
    assert events[-1][0] == "done"


def test_native_identical_successful_read_is_reused_not_reexecuted():
    execution = {"count": 0}

    def list_once(path: str = "."):
        execution["count"] += 1
        return {"path": path, "entries": ["evidence.tsx"]}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="list_cwd",
            description="List one directory.",
            affinity=["file", "io"],
            trusted_source="skill://public/list_cwd",
            handler=list_once,
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            if request.tools:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id=f"same-success-{len(self.requests)}",
                        name="list_cwd",
                        input={"path": "frontend/src"},
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            final = "The existing directory result was reused."
            yield ModelStreamEvent(type="text_delta", delta=final)
            yield ModelStreamEvent(type="done", final=ModelResponse(text=final))

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="list the directory once and summarize it",
        intent_type="task",
        normalized_goal="list the directory once and summarize it",
        user_context={"conversation_id": "native-success-reuse-thread"},
    )

    events = list(stream_agentic_fallback(stack, intent, _agent()))

    assert execution["count"] == 1
    assert [event[0] for event in events].count("tool_start") == 1
    assert [event[0] for event in events].count("tool_end") == 1
    assert router.requests[-1].tools == []
    assert events[-1][0] == "done"


def test_quiet_realtime_tool_batch_gets_model_generated_public_update(
    tmp_path,
):
    (tmp_path / "evidence.txt").write_text("verified marker", encoding="utf-8")

    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            is_progress_request = any(
                "[PUBLIC ACTION UPDATE]" in str(message.content) for message in request.messages
            )
            if is_progress_request:
                update = "我先核对工作区目录和 evidence.txt，再根据实际内容整理结论。"
                yield ModelStreamEvent(type="text_delta", delta=update)
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text=update),
                )
                return
            if len(self.requests) == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="list-1",
                        name="list_cwd",
                        input={"path": "."},
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(type="text_delta", delta="最终结论已完成。")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="最终结论已完成。"),
            )

    router = Router()
    intent = ParsedIntent(
        raw="inspect the workspace and report",
        intent_type="task",
        normalized_goal="inspect the workspace and report",
        user_context={
            "conversation_id": "public-narrative-thread",
            "mode": "code",
            "workspace_path": str(tmp_path),
            "realtime_public_narrative": True,
        },
    )

    events = list(stream_agentic_fallback(_stack(router), intent, _agent()))

    tool_start_index = next(i for i, event in enumerate(events) if event[0] == "tool_start")
    tool_end_index = next(i for i, event in enumerate(events) if event[0] == "tool_end")
    commentary_index = next(i for i, event in enumerate(events) if event[0] == "commentary")
    text_index = next(i for i, event in enumerate(events) if event[0] == "text")
    assert commentary_index < tool_start_index < tool_end_index < text_index
    assert "evidence.txt" in events[commentary_index][1]
    assert [event[0] for event in events].count("commentary") == 1
    assert len(router.requests) == 3
    assert router.requests[1].tools == []
    assert router.requests[2].messages[-1].role == "user"
    assert isinstance(router.requests[2].messages[-1].content, list)


def test_fast_realtime_tool_batch_gets_evidence_progress_by_default(tmp_path):
    class Router:
        def __init__(self):
            self.requests = []

        def call_stream(self, request):
            self.requests.append(request)
            is_progress_request = any(
                "[PUBLIC ACTION UPDATE]" in str(message.content) for message in request.messages
            )
            if is_progress_request:
                update = "我先读取目录内容，确认哪些信息能够支撑最终结论。"
                yield ModelStreamEvent(type="text_delta", delta=update)
                yield ModelStreamEvent(type="done", final=ModelResponse(text=update))
                return
            if len(self.requests) == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="list-fast",
                        name="list_cwd",
                        input={"path": "."},
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(type="text_delta", delta="Fast result complete.")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="Fast result complete."),
            )

    router = Router()
    intent = ParsedIntent(
        raw="inspect quickly",
        intent_type="task",
        normalized_goal="inspect quickly",
        user_context={
            "conversation_id": "fast-public-narrative-thread",
            "mode": "code",
            "workspace_path": str(tmp_path),
            "realtime_public_narrative": True,
        },
    )

    events = list(stream_agentic_fallback(_stack(router), intent, _agent()))

    assert len(router.requests) == 3
    assert [event[0] for event in events].count("commentary") == 1
    commentary_index = next(i for i, event in enumerate(events) if event[0] == "commentary")
    tool_start_index = next(i for i, event in enumerate(events) if event[0] == "tool_start")
    assert commentary_index < tool_start_index
    assert events[-1] == ("done", "", "Fast result complete.")


def test_long_tool_classification_covers_commands_agents_and_browser():
    assert tool_bridge._batch_needs_live_public_narrative(
        [ToolCall(id="shell", name="exec_shell", input={"command": "pytest"})]
    )
    assert tool_bridge._batch_needs_live_public_narrative(
        [ToolCall(id="agent", name="call_agent", input={})]
    )
    assert tool_bridge._batch_needs_live_public_narrative(
        [ToolCall(id="browser", name="browser_click", input={})]
    )
    assert not tool_bridge._batch_needs_live_public_narrative(
        [ToolCall(id="read", name="read_file", input={"path": "README.md"})]
    )


def test_structured_public_update_is_removed_before_native_dispatch():
    calls, checkpoint = tool_bridge._native_calls_with_public_checkpoint(
        [
            ToolCall(
                id="read",
                name="read_file",
                input={
                    "path": "README.md",
                    "public_update": "**我先核对 README.md 的实际说明，再整理结论。**",
                },
            )
        ]
    )

    assert checkpoint == "我先核对 README.md 的实际说明，再整理结论。"
    assert calls[0].input == {"path": "README.md"}


def test_structured_evidence_update_is_joined_and_removed_before_dispatch():
    calls, checkpoint = tool_bridge._native_calls_with_public_checkpoint(
        [
            ToolCall(
                id="read",
                name="read_file",
                input={
                    "path": "reducer.ts",
                    "confirmed_fact": "items.py 采用统一的事件生命周期。",
                    "next_action": "接着核对 reducer.ts 的归并方式",
                },
            )
        ]
    )

    assert checkpoint == "items.py 采用统一的事件生命周期；接着核对 reducer.ts 的归并方式"
    assert calls[0].input == {"path": "reducer.ts"}


def test_likely_long_tool_gets_model_update_while_execution_is_open(
    tmp_path,
    monkeypatch,
):
    execution = {"count": 0}
    tool_started = [threading.Event(), threading.Event()]
    narration_started = [threading.Event(), threading.Event()]

    def inspect_directory(path: str = "."):
        batch_index = execution["count"]
        execution["count"] += 1
        tool_started[batch_index].set()
        assert narration_started[batch_index].wait(timeout=1)
        return {"path": path, "finding": "diagnostic completed"}

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="list_cwd",
            description="Inspect one directory.",
            affinity=["file", "io"],
            trusted_source="skill://public/list_cwd",
            handler=inspect_directory,
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.requests = []
            self.action_updates = 0

        def call_stream(self, request):
            self.requests.append(request)
            is_action_update = any(
                "[PUBLIC ACTION UPDATE]" in str(message.content) for message in request.messages
            )
            if is_action_update:
                batch_index = self.action_updates
                self.action_updates += 1
                narration_started[batch_index].set()
                update = (
                    "我正在核对一手资料的关键差异，结果会决定下一步是否继续扩展来源。"
                    if batch_index == 0
                    else "第一批目录证据已经拿到；我继续核对补充目录，确认结论是否稳定。"
                )
                yield ModelStreamEvent(type="text_delta", delta=update)
                yield ModelStreamEvent(
                    type="done",
                    final=ModelResponse(text=update),
                )
                return
            if len(self.requests) == 1:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="research-long",
                        name="list_cwd",
                        input={"path": "."},
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            if len(self.requests) == 3:
                yield ModelStreamEvent(
                    type="tool_use",
                    tool_call=ToolCall(
                        id="research-long-2",
                        name="list_cwd",
                        input={"path": "follow-up"},
                    ),
                )
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(type="text_delta", delta="调研结论已完成。")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(text="调研结论已完成。"),
            )

    router = Router()
    monkeypatch.setattr(
        tool_bridge,
        "_batch_needs_live_public_narrative",
        lambda _calls: True,
    )
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    intent = ParsedIntent(
        raw="run a long diagnostic command",
        intent_type="task",
        normalized_goal="run a long diagnostic command",
        user_context={
            "conversation_id": "live-public-narrative-thread",
            "mode": "code",
            "workspace_path": str(tmp_path),
            "auto_approve": True,
            "realtime_public_narrative": True,
        },
    )

    events = list(stream_agentic_fallback(stack, intent, _agent()))

    tool_start_indexes = [i for i, event in enumerate(events) if event[0] == "tool_start"]
    commentary_indexes = [i for i, event in enumerate(events) if event[0] == "commentary"]
    tool_end_indexes = [i for i, event in enumerate(events) if event[0] == "tool_end"]
    assert len(tool_start_indexes) == len(commentary_indexes) == len(tool_end_indexes) == 2
    assert all(
        commentary < start < end
        for start, commentary, end in zip(
            tool_start_indexes,
            commentary_indexes,
            tool_end_indexes,
            strict=True,
        )
    )
    assert execution["count"] == 2
    assert "一手资料" in events[commentary_indexes[0]][1]
    assert "第一批目录证据" in events[commentary_indexes[1]][1]
    assert len(router.requests) == 5
    assert router.requests[1].tools == []
    assert router.requests[3].tools == []


def test_native_result_checkpoint_extracts_real_source_titles():
    calls = [
        ToolCall(
            id="search-1",
            name="web_search",
            input={"query": "Codex interrupt interaction"},
        )
    ]
    blocks = [
        {
            "type": "tool_result",
            "tool_use_id": "search-1",
            "content": json.dumps(
                {
                    "results": [
                        {"title": "Codex CLI features and interaction"},
                        {"title": "Claude Code interactive mode"},
                    ]
                }
            ),
        }
    ]

    checkpoint = tool_bridge._native_result_checkpoint(calls, blocks)

    assert "“Codex CLI features and interaction”" in checkpoint
    assert "“Claude Code interactive mode”" in checkpoint
    assert "usable evidence" in checkpoint
    assert "真实工具结果" not in checkpoint


def test_native_result_checkpoint_keeps_ordered_local_reads_visible():
    calls = [
        ToolCall(
            id="read-1",
            name="read_file",
            input={"path": "runtime/protocol/items.py"},
        )
    ]
    blocks = [
        {
            "type": "tool_result",
            "tool_use_id": "read-1",
            "content": json.dumps(
                {
                    "path": "runtime/protocol/items.py",
                    "size": 21204,
                    "truncated": False,
                }
            ),
        }
    ]
    goal = (
        "依次读取第一批 runtime/protocol/items.py；第二批 frontend/src/core/realtime/reducer.ts。"
    )

    checkpoint = tool_bridge._native_result_checkpoint(calls, blocks, goal=goal)

    assert checkpoint == ("已完整取得 items.py 的 21,204 字节内容；接下来核对 reducer.ts。")


def test_ordered_read_handoffs_require_an_explicit_between_batch_request():
    assert tool_bridge._ordered_read_handoffs_requested(
        "依次读取第一批 a.py；第二批 b.ts。每一批结束后说出刚确认的事实。"
    )
    assert not tool_bridge._ordered_read_handoffs_requested("读取 a.py 和 b.ts，最后给我结论。")


def test_ordered_reads_emit_initial_orientation_and_each_result_once(tmp_path):
    (tmp_path / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "b.ts").write_text("export const b = 2\n", encoding="utf-8")

    registry = SkillRegistry()
    registry.register(
        Skill(
            name="read_file",
            description="Read one file.",
            affinity=["file", "io"],
            trusted_source="skill://public/read_file",
            handler=_read_file,
        ),
        verify_tests=False,
    )

    class Router:
        def __init__(self):
            self.main_round = 0
            self.evidence_round = 0

        def call_stream(self, request):
            is_evidence = any(
                "[PUBLIC PROGRESS UPDATE]" in str(message.content) for message in request.messages
            )
            if is_evidence:
                self.evidence_round += 1
                update = (
                    "已确认 a.py 定义了 A；接下来核对 b.ts。"
                    if self.evidence_round == 1
                    else "已确认 b.ts 导出了 b；两批证据已经齐全。"
                )
                yield ModelStreamEvent(type="text_delta", delta=update)
                yield ModelStreamEvent(type="done", final=ModelResponse(text=update))
                return
            self.main_round += 1
            if self.main_round == 1:
                call = ToolCall(
                    id="a",
                    name="read_file",
                    input={
                        "path": "a.py",
                        "public_update": "我先读取 a.py，确认第一条事实。",
                    },
                )
                yield ModelStreamEvent(type="tool_use", tool_call=call)
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            if self.main_round == 2:
                call = ToolCall(
                    id="b",
                    name="read_file",
                    input={
                        "path": "b.ts",
                        "confirmed_fact": "已确认 a.py 定义了 A。",
                        "next_action": "接下来核对 b.ts",
                    },
                )
                yield ModelStreamEvent(type="tool_use", tool_call=call)
                yield ModelStreamEvent(type="done", final=ModelResponse(text=""))
                return
            yield ModelStreamEvent(type="text_delta", delta="最终结论。")
            yield ModelStreamEvent(type="done", final=ModelResponse(text="最终结论。"))

    router = Router()
    stack = SimpleNamespace(
        executor=ToolExecutor(registry, TrustEngine()),
        planner=SimpleNamespace(router=router, planner_model="mock"),
    )
    goal = "依次读取第一批 a.py；第二批 b.ts。每一批结束后说出刚确认的事实。"
    intent = ParsedIntent(
        raw=goal,
        intent_type="task",
        normalized_goal=goal,
        user_context={
            "conversation_id": "ordered-read-handoffs",
            "mode": "code",
            "workspace_path": str(tmp_path),
            "realtime_public_narrative": True,
            "realtime_public_orientation": True,
        },
    )

    events = list(stream_agentic_fallback(stack, intent, _agent()))

    commentary = [event[1] for event in events if event[0] == "commentary"]
    assert commentary == [
        "我先读取 a.py，确认第一条事实。",
        "已确认 a.py 定义了 A；接下来核对 b.ts。",
        "已确认 b.ts 导出了 b；两批证据已经齐全。",
    ]
    assert [event[0] for event in events].count("tool_start") == 2
    assert events[-1] == ("done", "", "最终结论。")


def test_no_local_access_contract_removes_local_and_delegation_tools():
    specs = [
        SimpleNamespace(name="web_search"),
        SimpleNamespace(name="web_fetch"),
        SimpleNamespace(name="todo_write"),
        SimpleNamespace(name="list_cwd"),
        SimpleNamespace(name="read_file"),
        SimpleNamespace(name="exec_shell"),
        SimpleNamespace(name="call_agent"),
        SimpleNamespace(name="write_text_file"),
    ]

    filtered, contract = tool_bridge._filter_tool_specs_for_workspace_contract(
        specs,
        "只做网页调研，不要读取、修改或创建任何本地文件。",
    )

    assert contract == "no_local_access"
    assert {spec.name for spec in filtered} == {
        "web_search",
        "web_fetch",
        "todo_write",
    }


def test_read_only_contract_keeps_inspection_but_removes_mutation_tools():
    specs = [
        SimpleNamespace(name="list_cwd"),
        SimpleNamespace(name="read_file"),
        SimpleNamespace(name="web_search"),
        SimpleNamespace(name="edit_file"),
        SimpleNamespace(name="exec_shell"),
    ]

    filtered, contract = tool_bridge._filter_tool_specs_for_workspace_contract(
        specs,
        "只读分析当前仓库，不要修改任何文件。",
    )

    assert contract == "read_only"
    assert {spec.name for spec in filtered} == {
        "list_cwd",
        "read_file",
        "web_search",
    }
