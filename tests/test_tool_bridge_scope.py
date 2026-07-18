import contextvars
import json
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
    assert any(tool.name == "todo_write" for tool in first_request.tools)


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
        str(message.content)
        for message in router.requests[3].messages
        if message.role == "user"
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
        str(message.content)
        for message in router.requests[2].messages
        if message.role == "user"
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
        lambda _current, attempted: (
            "deepseek-chat" if "deepseek-chat" not in attempted else None
        ),
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
        str(message.content)
        for message in router.requests[0].messages
        if message.role == "system"
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
