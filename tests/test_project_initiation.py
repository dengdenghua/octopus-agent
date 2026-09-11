import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runtime.memory.cowork.group_store import GroupStore
from runtime.protocol import Turn
from runtime.sensing.gateway._realtime_cerebrum_project_os import _parse_project_os_control
from runtime.sensing.gateway.realtime_project_initiation import initiate_project


class Threads:
    def __init__(self):
        self.thread = {"metadata": {}}

    def get(self, _id):
        return deepcopy(self.thread)

    def update_state(self, _id, *, metadata):
        self.thread["metadata"].update(deepcopy(metadata))

    def update_state_if_unchanged(self, _id, expected, *, metadata):
        if self.thread != expected:
            return None
        self.update_state(_id, metadata=metadata)
        return deepcopy(self.thread)


def test_review_command_requires_one_proposal_id():
    assert _parse_project_os_control("/project review draft1") == {"type": "review", "proposal_id": "draft1"}
    assert _parse_project_os_control("/project review") == {"type": "help"}
    assert _parse_project_os_control("/project review draft1 changed-scope") == {"type": "help"}


def test_single_step_command_keeps_the_approval_path_and_one_tick_limit():
    from runtime.projectos.cowork_bridge import _project_action_specs

    assert _parse_project_os_control("/project tick") == {"type": "run", "goal": "", "max_ticks": 1}
    assert _parse_project_os_control("/project tick extra") == {"type": "help"}
    specs = {spec["action"]: spec for spec in _project_action_specs("P", "running")}
    assert specs["run"]["realtime_command"] == "/project run"
    assert specs["tick"]["realtime_command"] == "/project tick"


@pytest.mark.parametrize("cap", [None, 0, 2])
def test_proposal_displays_actual_cumulative_cap_not_model_budget_text(tmp_path, cap):
    from runtime.projectos.initiation import ProjectProposal

    _, _, _, proposal = setup(tmp_path)
    proposal.update(ai_budget_usd=cap, budget="旧说明：单次2美元")
    rendered = ProjectProposal.model_validate(proposal).render({})
    if cap is None:
        assert "AI 执行费用上限：尚未设置" in rendered
    else:
        assert f"AI 执行费用上限：${cap}" in rendered
        assert "按本项目所有阶段、所有成员累计计算；不是单次调用额度" in rendered


def test_expired_proposal_reopens_without_model_rewrite_or_auto_approval(tmp_path):
    runtime, emitter, kwargs, proposal = setup(tmp_path, action="decline")
    runtime._thread_store.thread["metadata"]["project_initiation"] = {
        "id": "saved", "status": "approval_expired", "leader_id": "general",
        "goal": "original goal", "proposal": deepcopy(proposal),
    }
    kwargs.update(review_id="saved", prepare=None)
    result = asyncio.run(initiate_project(runtime, Turn(threadId="thread"), None, emitter, **kwargs))
    assert result is None
    emitter.request_approval.assert_awaited_once()
    assert runtime._cowork_group_store.state("thread").roster == []
    saved = runtime._thread_store.thread["metadata"]["project_initiation"]
    assert saved["goal"] == "original goal"
    assert saved["proposal"]["scope"] == proposal["scope"]
    assert saved["id"] != "saved"


@pytest.mark.parametrize("change", ["id", "leader_id", "status"])
def test_stale_review_does_not_open_approval_or_replace_saved_proposal(tmp_path, change):
    runtime, emitter, kwargs, proposal = setup(tmp_path)
    saved = {"id": "saved", "status": "approval_expired", "leader_id": "general", "proposal": proposal}
    saved[change] = "changed"
    runtime._thread_store.thread["metadata"]["project_initiation"] = deepcopy(saved)
    kwargs.update(review_id="saved", prepare=None)
    assert asyncio.run(initiate_project(runtime, Turn(threadId="thread"), None, emitter, **kwargs)) is None
    emitter.request_approval.assert_not_awaited()
    assert runtime._thread_store.thread["metadata"]["project_initiation"] == saved


@pytest.mark.parametrize("stage", ["planning", "timeout", "approve_write"])
def test_old_initiation_cannot_overwrite_newer_proposal(tmp_path, stage):
    runtime, emitter, kwargs, proposal = setup(tmp_path)
    newer = {"id": "newer", "status": "pending_approval", "proposal": {"name": "new scope"}}

    def replace():
        runtime._thread_store.update_state("thread", metadata={"project_initiation": newer})

    if stage == "planning":
        def prepare(**_):
            replace()
            return proposal
        kwargs["prepare"] = prepare
    elif stage == "timeout":
        async def timeout(*_, **__):
            replace()
            raise TimeoutError()
        emitter.request_approval.side_effect = timeout
    else:
        original = runtime._thread_store.update_state_if_unchanged

        def race(thread_id, expected, *, metadata):
            if metadata["project_initiation"]["status"] == "approved":
                replace()
            return original(thread_id, expected, metadata=metadata)
        runtime._thread_store.update_state_if_unchanged = race
    assert asyncio.run(initiate_project(runtime, Turn(threadId="thread"), None, emitter, **kwargs)) is None
    assert runtime._thread_store.thread["metadata"]["project_initiation"] == newer
    assert not runtime._cowork_group_store.state("thread").roster
    if stage == "planning":
        emitter.request_approval.assert_not_awaited()


def setup(tmp_path, action="accept", questions=None):
    agents = [
        SimpleNamespace(agent_id=id, display_name=id, description=id) for id in ("general", "coder")
    ]
    runtime = SimpleNamespace(
        _thread_store=Threads(),
        _cowork_group_store=GroupStore(tmp_path),
        _agent_registry=SimpleNamespace(
            all_agents=lambda: agents, has=lambda id: id in {"general", "coder"}
        ),
        _emit_agent_message=AsyncMock(),
    )
    proposal = {
        "name": "发布",
        "scope": "新品发布准备",
        "milestones": ["需求验收", "开发验收"],
        "budget": "仅估算 AI 用量，不授权支付；上限另行审批",
        "staffing": [
            {
                "role": "产品经理",
                "count": 1,
                "responsibilities": "规划与验收",
                "agent_id": "general",
            },
            {"role": "开发与测试", "count": 1, "responsibilities": "开发测试", "agent_id": "coder"},
        ],
        "questions": questions or [],
    }

    async def approve(*args, **kwargs):
        assert runtime._cowork_group_store.state("thread").roster == []
        assert "预算" in args[1]["argsPreview"]
        return {"action": action}

    emitter = SimpleNamespace(
        request_approval=AsyncMock(side_effect=approve), is_turn_interrupted=lambda _: False
    )
    kwargs = dict(
        thread_id="thread",
        goal="发布新品",
        owner_id="",
        tenant_id="",
        leader=agents[0],
        prepare=lambda **_: deepcopy(proposal),
    )
    return runtime, emitter, kwargs, proposal


@pytest.mark.parametrize("action", ["accept", "decline"])
def test_empty_roster_prepares_and_only_approval_adds_members(tmp_path, action):
    runtime, emitter, kwargs, _ = setup(tmp_path, action)
    result = asyncio.run(
        initiate_project(runtime, Turn(threadId="thread"), None, emitter, **kwargs)
    )
    ids = {m.id for m in runtime._cowork_group_store.state("thread").roster}
    assert ids == ({"general", "coder"} if action == "accept" else set())
    assert (result is not None) == (action == "accept")


@pytest.mark.parametrize("failure", ["questions", "timeout", "stale", "invalid_agent"])
def test_incomplete_or_unapproved_proposal_never_recruits(tmp_path, failure):
    runtime, emitter, kwargs, proposal = setup(
        tmp_path, questions=["预算上限？"] if failure == "questions" else []
    )
    if failure == "timeout":
        emitter.request_approval.side_effect = TimeoutError()
    elif failure == "stale":

        async def stale(*a, **kw):
            runtime._thread_store.update_state(
                "thread", metadata={"project_initiation": {"id": "new"}}
            )
            return {"action": "accept"}

        emitter.request_approval.side_effect = stale
    elif failure == "invalid_agent":
        proposal["staffing"][1]["agent_id"] = "not-installed"
    assert (
        asyncio.run(initiate_project(runtime, Turn(threadId="thread"), None, emitter, **kwargs))
        is None
    )
    assert not runtime._cowork_group_store.state("thread").roster
    if failure in {"questions", "invalid_agent"}:
        emitter.request_approval.assert_not_awaited()


def test_copied_project_prefix_does_not_become_goal():
    assert _parse_project_os_control("/project run /project run 发布新品") == {
        "type": "run",
        "goal": "发布新品",
    }


def test_simple_task_does_not_create_team(tmp_path):
    runtime, emitter, kwargs, proposal = setup(tmp_path)
    proposal["sizing"] = "task"
    assert (
        asyncio.run(initiate_project(runtime, Turn(threadId="thread"), None, emitter, **kwargs))
        is None
    )
    emitter.request_approval.assert_not_awaited()
    assert not runtime._cowork_group_store.state("thread").roster


def test_human_requirement_is_not_invited_as_agent(tmp_path):
    runtime, emitter, kwargs, proposal = setup(tmp_path)
    proposal["staffing"].append(
        {"role": "验收负责人", "count": 1, "responsibilities": "确认成果", "kind": "human"}
    )
    assert (
        asyncio.run(initiate_project(runtime, Turn(threadId="thread"), None, emitter, **kwargs))
        is not None
    )
    assert {m.id for m in runtime._cowork_group_store.state("thread").roster} == {
        "general",
        "coder",
    }


def test_gateway_approval_creates_plan_without_running_tasks(tmp_path, monkeypatch):
    from runtime.platform.models import ParsedIntent
    from runtime.sensing.gateway._realtime_cerebrum_project_os import _drive_project_os

    runtime, emitter, kwargs, _ = setup(tmp_path)
    runtime._project_store = SimpleNamespace(project_for_thread=lambda _: None)
    runtime._project_os_hooks = {"prepare_initiation": kwargs["prepare"]}
    calls = []

    def plan(*args, **kw):
        calls.append(kw)
        assert {m.id for m in runtime._cowork_group_store.state("thread").roster} == {
            "general",
            "coder",
        }
        return {"ok": False, "message": "plan recorded"}

    monkeypatch.setattr("runtime.projectos.cowork_bridge.run_project_from_group", plan)
    asyncio.run(
        _drive_project_os(
            runtime,
            Turn(threadId="thread"),
            None,
            emitter,
            ParsedIntent(raw="/project run 发布", normalized_goal="发布", intent_type="task"),
            thread_id="thread",
            text="/project run 发布",
            leader=kwargs["leader"],
        )
    )
    assert len(calls) == 1
    assert calls[0]["run"] is False
    assert "预算" in calls[0]["goal"]


def test_proposal_uses_selected_turn_model(tmp_path):
    from runtime.protocol import TurnParams

    runtime, emitter, kwargs, proposal = setup(tmp_path)
    seen = {}

    def prepare(**values):
        seen.update(values)
        return proposal

    kwargs["prepare"] = prepare
    asyncio.run(initiate_project(
        runtime, Turn(threadId="thread", params=TurnParams(threadId="thread", model="chosen-model")),
        None, emitter, **kwargs,
    ))
    assert seen["model"] == "chosen-model"


def test_provider_failure_is_not_reported_as_bad_staffing(tmp_path):
    from runtime.platform.models.provider_errors import ModelProviderHTTPError

    runtime, emitter, kwargs, _ = setup(tmp_path)

    def prepare(**_):
        raise ModelProviderHTTPError("private provider diagnostic", status_code=401)

    kwargs["prepare"] = prepare
    result = asyncio.run(initiate_project(runtime, Turn(threadId="thread"), None, emitter, **kwargs))
    assert result is None
    assert runtime._thread_store.thread["metadata"]["project_initiation"]["status"] == "model_unavailable"
    assert runtime._cowork_group_store.state("thread").roster == []
    emitter.request_approval.assert_not_called()
    message = runtime._emit_agent_message.call_args.args[-1]
    assert "HTTP 401" in message
    assert "人员配置不完整" not in message
    assert "private provider diagnostic" not in message
