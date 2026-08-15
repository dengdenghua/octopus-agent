"""Tests for running a sub-agent through the MAIN react loop."""

from dataclasses import dataclass

from runtime.execution.subagents.react_drive import (
    build_subagent_intent,
    run_subagent_react_loop,
)


@dataclass
class _FakeResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = "stop"


class _ScriptedRouter:
    def __init__(self, scripts: list[str]) -> None:
        self.scripts = list(scripts)
        self.calls = 0

    def call(self, req):  # noqa: ARG002
        text = self.scripts[self.calls]
        self.calls += 1
        return _FakeResponse(text=text)

    def call_stream(self, req):
        from runtime.sensing.model_router.models import (
            CostEntry,
            ModelResponse,
            ModelStreamEvent,
        )

        resp = self.call(req)
        if resp.text:
            yield ModelStreamEvent(type="text_delta", delta=resp.text)
        yield ModelStreamEvent(
            type="done",
            final=ModelResponse(
                text=resp.text,
                model="test-model",
                input_tokens=0,
                output_tokens=0,
                finish_reason="stop",
                cost=CostEntry(),
            ),
        )


class _FakePlanner:
    def __init__(self, router) -> None:
        self.router = router
        self.planner_model = "test-model"


class _FakeStack:
    def __init__(self, router) -> None:
        self.planner = _FakePlanner(router)


class _CaptureEmitter:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(dict(event))


def test_build_subagent_intent_carries_role_and_allowlist() -> None:
    intent = build_subagent_intent(
        "investigate",
        role_id="researcher",
        model="m1",
        thread_id="child-1",
        conversation_messages=[{"role": "user", "content": "prior"}],
        tool_allowlist=["web_search"],
        metadata={"workspace_path": "/ws"},
    )
    assert intent.raw == "investigate"
    assert intent.normalized_goal == "investigate"
    assert intent.user_context["model_name"] == "m1"
    assert intent.user_context["thread_id"] == "child-1"
    assert intent.user_context["tool_allowlist"] == ["web_search"]
    assert intent.user_context["conversation_messages"] == [
        {"role": "user", "content": "prior"},
    ]
    assert intent.user_context["auto_approve"] is True


def test_run_subagent_react_loop_streams_text_and_concludes() -> None:
    router = _ScriptedRouter(["Final Answer: 找到答案了"])
    stack = _FakeStack(router)
    emitter = _CaptureEmitter()

    # Bind a session carrying the coordination root so the typed bus receives
    # the conclusion event (mirrors the parent-turn session scoping).
    from runtime.platform.process.session import Session, _current_session

    sess = Session(
        thread_id="child-1",
        conversation_id="child-1",
        metadata={"root_thread_id": "root-1", "thread_id": "child-1"},
    )
    token = _current_session.set(sess)
    try:
        result = run_subagent_react_loop(
            stack,
            prompt="去调研一下",
            role_id="researcher",
            model="test-model",
            thread_id="child-1",
            session_id="sess-1",
            emitter=emitter,
        )
    finally:
        _current_session.reset(token)

    assert result is not None
    assert result.success
    assert result.final_answer == "找到答案了"

    deltas = [e for e in emitter.events if e.get("type") == "sub_text_delta"]
    assert deltas, "expected streamed text deltas on the emitter"
    # The react loop strips the "Final Answer:" marker before streaming the
    # final prose, so the streamed text equals the final answer itself.
    assert "".join(e["delta"] for e in deltas) == "找到答案了"

    from runtime.execution.subagents.event_bus import get_bus

    bus = get_bus("root-1")
    assert bus is not None
    kinds = [e.get("type") for e in bus.replay() if isinstance(e, dict)]
    assert "sub_concluded" in kinds
    concluded = [e for e in bus.replay() if e.get("type") == "sub_concluded"][-1]
    assert concluded["payload"].get("role") == "researcher"
    assert concluded["payload"].get("ok") is True


def test_run_subagent_react_loop_emits_failed_on_react_error(
    monkeypatch,
) -> None:
    import runtime.execution.subagents.react_drive as react_drive

    def _erroring_loop(stack, intent, agent, **kwargs):
        yield {"type": "react_error", "message": "upstream boom"}
        return None

    monkeypatch.setattr(react_drive, "stream_react_loop", _erroring_loop)

    from runtime.platform.process.session import Session, _current_session

    sess = Session(
        thread_id="child-2",
        conversation_id="child-2",
        metadata={"root_thread_id": "root-2", "thread_id": "child-2"},
    )
    token = _current_session.set(sess)
    try:
        run_subagent_react_loop(
            _FakeStack(None),
            prompt="试试",
            role_id="explorer",
            model="test-model",
            thread_id="child-2",
        )
    finally:
        _current_session.reset(token)

    from runtime.execution.subagents.event_bus import get_bus

    bus = get_bus("root-2")
    kinds = [e.get("type") for e in bus.replay() if isinstance(e, dict)]
    assert "sub_failed" in kinds
    failed = [e for e in bus.replay() if e.get("type") == "sub_failed"][-1]
    assert failed["payload"].get("ok") is False
    assert "upstream boom" in failed["payload"].get("error", "")


def test_runner_uses_react_loop_when_opted_in() -> None:
    from runtime.execution.suckers.ephemeral_agents import (
        BUILTIN_ROLES,
        EphemeralCall,
    )
    from runtime.execution.suckers.ephemeral_runner import make_llm_ephemeral_runner

    class _Router:
        default_model = "test-model"

        def call(self, req):
            return _FakeResponse(text="react-loop answer")

        def call_stream(self, req):
            from runtime.sensing.model_router.models import (
                CostEntry,
                ModelResponse,
                ModelStreamEvent,
            )

            yield ModelStreamEvent(type="text_delta", delta="react-loop answer")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="react-loop answer",
                    model="test-model",
                    finish_reason="stop",
                    cost=CostEntry(),
                ),
            )

    router = _Router()
    runner = make_llm_ephemeral_runner(
        router,
        registry=None,
        default_model="test-model",
    )
    call = EphemeralCall(
        role=BUILTIN_ROLES["reviewer"],
        user_prompt="review the diff",
        composed_system_prompt="reviewer persona",
        caller_thread_id="t-1",
        caller_agent_id="coder",
        context={
            "react_loop_subagent": True,
            "react_stack": _FakeStack(router),
        },
    )
    assert runner(call) == "react-loop answer"


def test_runner_keeps_mini_loop_when_react_not_opted_in() -> None:
    from runtime.execution.suckers.ephemeral_agents import (
        BUILTIN_ROLES,
        EphemeralCall,
    )
    from runtime.execution.suckers.ephemeral_runner import make_llm_ephemeral_runner

    class _Router:
        default_model = "test-model"

        def call(self, req):
            return _FakeResponse(text="mini-loop answer")

        def call_stream(self, req):
            from runtime.sensing.model_router.models import (
                CostEntry,
                ModelResponse,
                ModelStreamEvent,
            )

            yield ModelStreamEvent(type="text_delta", delta="mini-loop answer")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="mini-loop answer",
                    model="test-model",
                    finish_reason="stop",
                    cost=CostEntry(),
                ),
            )

    runner = make_llm_ephemeral_runner(
        _Router(),
        registry=None,
        default_model="test-model",
    )
    call = EphemeralCall(
        role=BUILTIN_ROLES["reviewer"],
        user_prompt="review",
        composed_system_prompt="reviewer persona",
        caller_thread_id="t-1",
        caller_agent_id="coder",
        context={},  # no react opt-in -> mini-loop single-shot
    )
    assert runner(call) == "mini-loop answer"


def test_react_loop_carries_role_persona_to_the_model() -> None:
    """The react-loop path must keep the role persona/context the mini-loop
    injected via ``composed_system_prompt`` (role + caller history + memory),
    otherwise the child loses its role after the flip to the main loop."""
    from runtime.execution.suckers.ephemeral_agents import (
        BUILTIN_ROLES,
        EphemeralCall,
    )
    from runtime.execution.suckers.ephemeral_runner import make_llm_ephemeral_runner

    class _CapturingRouter:
        def __init__(self):
            self.default_model = "test-model"
            self.requests: list = []

        def call(self, req):
            self.requests.append(req)
            return _FakeResponse(text="done")

        def call_stream(self, req):
            from runtime.sensing.model_router.models import (
                CostEntry,
                ModelResponse,
                ModelStreamEvent,
            )

            self.requests.append(req)
            yield ModelStreamEvent(type="text_delta", delta="done")
            yield ModelStreamEvent(
                type="done",
                final=ModelResponse(
                    text="done",
                    model="test-model",
                    finish_reason="stop",
                    cost=CostEntry(),
                ),
            )

    router = _CapturingRouter()
    runner = make_llm_ephemeral_runner(
        router,
        registry=None,
        default_model="test-model",
    )
    persona = "ROLE_SYSTEM: reviewer scans diffs for bugs"
    call = EphemeralCall(
        role=BUILTIN_ROLES["reviewer"],
        user_prompt="check this diff",
        composed_system_prompt=persona,
        caller_thread_id="t-1",
        caller_agent_id="coder",
        context={
            "react_loop_subagent": True,
            "react_stack": _FakeStack(router),
        },
    )
    assert runner(call) == "done"
    assert router.requests, "expected the react loop to call the model"
    joined = "\n".join(
        str(m.content)
        for req in router.requests
        for m in getattr(req, "messages", [])
    )
    assert persona in joined
    assert "check this diff" in joined
