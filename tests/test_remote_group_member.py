import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from a2a.types import Message, Part, Role, StreamResponse, Task, TaskState

from runtime.execution.engines import ExecutionPhase
from runtime.memory.cowork.group import ContextGrant, GroupState, Member, MemberEvent
from runtime.memory.cowork.group_store import GroupStore
from runtime.memory.cowork.turn_plan import plan_turn
from runtime.memory.threads.event_log import EventLog
from runtime.platform.models import ParsedIntent
from runtime.protocol import Turn, TurnParams
from runtime.sensing.gateway import a2a_router
from runtime.sensing.gateway._team_stream_group_fanout import _drive_group_fanout
from runtime.sensing.gateway.realtime_execution import select_turn_execution
from runtime.sensing.gateway.realtime_turn_lifecycle import _inject_cowork_turn_plan
from runtime.sensing.gateway.remote_group_member import (
    call_remote_group_member,
    resolve_remote_mentions,
)

REMOTE = "a2a_workbuddy"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(a2a_router, "_REGISTRY_DIR", tmp_path / "a2a")
    monkeypatch.setattr(a2a_router, "_REGISTRY_FILE", tmp_path / "a2a" / "registry.json")
    a2a_router._save_registry(
        [{"agent_id": REMOTE, "name": "WorkBuddy", "base_url": "http://localhost:8321"}]
    )
    store = GroupStore(base_dir=tmp_path / "group")
    store.append(
        "room",
        MemberEvent(
            action="invite",
            actor="user",
            target_id=REMOTE,
            grant=ContextGrant(scope="from_join"),
            at_message=1,
        ),
    )
    runtime = SimpleNamespace(
        _cowork_group_store=store,
        _trace_store=None,
        _wrap_with_policy=lambda p: p,
        _drive_react=AsyncMock(side_effect=AssertionError("local fallback")),
    )
    turn = Turn(threadId="room", params=TurnParams(threadId="room"))
    return runtime, turn


@pytest.mark.parametrize("mode", ["chat", "cluster", "swarm"])
def test_remote_is_opt_in_even_for_broadcast(mode):
    state = GroupState(
        mode=mode,
        roster=[
            Member(REMOTE, "agent", "participant", 0, ContextGrant()),
            Member("local", "agent", "participant", 0, ContextGrant()),
        ],
    )
    assert REMOTE not in plan_turn(state, "hello").responders
    assert REMOTE not in plan_turn(state, "@all hello").responders
    assert plan_turn(state, f"@agent:{REMOTE} hello").responders == [REMOTE]
    state.roster[0].muted = True
    assert plan_turn(state, f"@agent:{REMOTE} hello").responders == []


def test_display_mention_and_grant_are_server_owned(setup):
    runtime, turn = setup
    intent = ParsedIntent(
        raw="@WorkBuddy help",
        normalized_goal="help",
        intent_type="task",
        user_context={
            "conversation_messages": [
                {"role": "user", "content": "PRIVATE"},
                {"role": "user", "content": "VISIBLE"},
            ]
        },
    )
    _inject_cowork_turn_plan(runtime, thread_id=turn.thread_id, text=intent.raw, intent=intent)
    ctx = intent.user_context
    assert ctx["cowork_responders"] == [REMOTE]
    assert ctx["agent_roster"][0]["display_name"] == "WorkBuddy"
    assert "PRIVATE" not in str(ctx["cowork_member_context_messages"])
    assert resolve_remote_mentions("email@WorkBuddy.com", [REMOTE]) == "email@WorkBuddy.com"
    assert resolve_remote_mentions("@WorkBuddy hello", []) == "@WorkBuddy hello"


def test_remote_route_never_requires_or_continues_local_model(setup):
    runtime, turn = setup
    intent = ParsedIntent(
        raw="help",
        normalized_goal="help",
        intent_type="task",
        user_context={"cowork_group": True, "cowork_responders": [REMOTE]},
    )
    route = asyncio.run(
        select_turn_execution(
            runtime,
            turn,
            None,
            intent,
            project_command=False,
            group_fanout=False,
            topology_id=None,
            codex_partner=False,
            reflection_fast_path=False,
        )
    )
    assert all(route.driver_for(phase) == "group_fanout" for phase in ExecutionPhase)


def install_client(monkeypatch, requests, *, pending=False):
    class Client:
        closed = False
        cancelled = False

        async def send_message(self, request):
            requests.append(request)
            task = Task(id="remote-task", context_id=request.message.context_id)
            task.status.state = TaskState.TASK_STATE_WORKING
            yield StreamResponse(task=task)
            if pending:
                await asyncio.sleep(30)

        async def get_task(self, request):
            task = Task(id=request.id)
            task.status.state = TaskState.TASK_STATE_COMPLETED
            task.history.append(Message(role=Role.ROLE_AGENT, parts=[Part(text="WORKBUDDY_REPLY")]))
            return task

        async def cancel_task(self, request):
            self.cancelled = True

        async def close(self):
            self.closed = True

    client = Client()
    monkeypatch.setattr("a2a.client.ClientFactory.create_from_url", AsyncMock(return_value=client))
    return client


def test_real_sdk_result_and_fresh_context_with_grant_recheck(setup, monkeypatch):
    runtime, turn = setup
    requests = []
    client = install_client(monkeypatch, requests)
    kwargs = dict(
        history=[{"content": "VISIBLE"}],
        authorization={
            "scope": "from_join",
            "from_msg": None,
            "to_msg": None,
            "joined_at_message": 1,
        },
    )
    first = asyncio.run(
        call_remote_group_member(runtime, turn, REMOTE, "@WorkBuddy help", **kwargs)
    )
    assert first["success"] and first["output"] == "WORKBUDDY_REPLY"
    assert "VISIBLE" in requests[0].message.parts[0].text
    kwargs["authorization"] = {}
    second = asyncio.run(
        call_remote_group_member(runtime, turn, REMOTE, "@WorkBuddy help", **kwargs)
    )
    assert second["success"] and client.closed
    assert "VISIBLE" not in requests[1].message.parts[0].text
    assert requests[0].message.context_id != requests[1].message.context_id


def test_timeout_cancels_remote_task(setup, monkeypatch):
    runtime, turn = setup
    client = install_client(monkeypatch, [], pending=True)
    result = asyncio.run(
        call_remote_group_member(runtime, turn, REMOTE, "@WorkBuddy help", timeout_s=0.03)
    )
    assert not result["success"]
    assert client.cancelled and client.closed


def test_group_stop_cancels_remote_task(setup, monkeypatch):
    runtime, turn = setup
    requests = []
    client = install_client(monkeypatch, requests, pending=True)
    result = asyncio.run(
        call_remote_group_member(
            runtime, turn, REMOTE, "@WorkBuddy help", should_cancel=lambda: bool(requests)
        )
    )
    assert result["cancelled"]
    assert client.cancelled and client.closed


@pytest.mark.parametrize("action", ["leave", "mute"])
def test_revoked_member_never_connects(setup, monkeypatch, action):
    runtime, turn = setup
    requests = []
    install_client(monkeypatch, requests)
    runtime._cowork_group_store.append(
        turn.thread_id, MemberEvent(action=action, actor="user", target_id=REMOTE)
    )
    result = asyncio.run(call_remote_group_member(runtime, turn, REMOTE, "@WorkBuddy help"))
    assert not result["success"] and not requests


@pytest.mark.parametrize("success", [True, False])
@pytest.mark.parametrize("mixed", [True, False])
def test_single_remote_fanout_has_attributed_reply_and_no_local_fallback(
    setup, tmp_path, monkeypatch, success, mixed
):
    runtime, turn = setup
    call = AsyncMock(
        return_value={
            "success": success,
            "output": "WORKBUDDY_REPLY" if success else "",
            "error": "offline",
        }
    )
    monkeypatch.setattr(
        "runtime.sensing.gateway.remote_group_member.call_remote_group_member", call
    )
    local_calls = []

    def local_call(**kwargs):
        local_calls.append(kwargs["agent_id"])
        return {"success": True, "output": "LOCAL_REPLY"}

    monkeypatch.setattr("runtime.execution.suckers.delegation_skills._call_agent", local_call)
    if mixed:
        runtime._cowork_group_store.append(
            turn.thread_id, MemberEvent(action="invite", actor="user", target_id="local")
        )
    log = EventLog(tmp_path / "events.jsonl")
    log.turn_started(turn.thread_id, turn)
    intent = ParsedIntent(
        raw="@WorkBuddy @agent:local help" if mixed else "@WorkBuddy help",
        normalized_goal="help",
        intent_type="task",
        user_context={},
    )
    _inject_cowork_turn_plan(runtime, thread_id=turn.thread_id, text=intent.raw, intent=intent)
    asyncio.run(
        _drive_group_fanout(
            runtime,
            turn,
            log,
            SimpleNamespace(notify=AsyncMock(), is_turn_interrupted=lambda _: False),
            intent,
            text=intent.raw,
        )
    )
    assert call.await_count == 1
    assert local_calls == (["local"] if mixed else [])
    runtime._drive_react.assert_not_called()
    replies = [
        item for item in turn.items if getattr(item, "agent_display_name", None) == "WorkBuddy"
    ]
    assert replies
    assert "WORKBUDDY_REPLY" in replies[-1].text if success else "未能回应" in replies[-1].text
