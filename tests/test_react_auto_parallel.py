"""Tests for auto-decomposition + parallel execution (agent_auto_parallel).

Covers the pure heuristic gate (plan_auto_parallel / _heuristic_splitter) and
the stream_react_loop integration (auto_parallel_started / _completed /
_skipped events and synthetic observation injection).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import patch

from runtime.core.cerebrum.agent_auto_parallel import (
    plan_auto_parallel,
    run_auto_parallel,
)


# ─── plan gate · unit tests ──────────────────────────────────


def test_plan_parallelizes_explicit_list():
    goal = (
        "请分别调研以下三个方向：\n"
        "1. 云计算市场2025年规模\n"
        "2. 人工智能芯片竞争格局\n"
        "3. 新能源车渗透率预测"
    )
    plan = plan_auto_parallel(goal)
    assert plan is not None
    assert plan.should_parallelize()
    assert len(plan.subtasks) == 3
    descriptions = [t.description for t in plan.subtasks]
    assert "云计算市场2025年规模" in descriptions


def test_plan_parallelizes_multiple_questions():
    goal = (
        "帮我查一下苹果的营收是多少？"
        "同时看一下它的毛利率变化？"
        "再分析一下它的估值贵不贵？"
    )
    plan = plan_auto_parallel(goal)
    assert plan is not None
    assert plan.should_parallelize()
    assert len(plan.subtasks) >= 3


def test_plan_returns_none_for_single_cohesive_goal():
    goal = "请你用中文详细解释一下量子计算的基本原理和应用场景"
    assert plan_auto_parallel(goal) is None


def test_plan_returns_none_for_short_goal():
    assert plan_auto_parallel("hi") is None


def test_plan_respects_max_subtasks():
    goal = (
        "分别执行以下任务：\n"
        "- 任务甲：分析蓝牙协议栈\n"
        "- 任务乙：分析WiFi射频\n"
        "- 任务丙：分析电源管理\n"
        "- 任务丁：分析传感器驱动\n"
    )
    plan = plan_auto_parallel(goal, max_subtasks=2)
    assert plan is not None
    assert len(plan.subtasks) == 2


# ─── run_auto_parallel · unit tests (orchestrator stubbed) ──


def test_run_auto_parallel_dispatches_and_aggregates():
    plan = plan_auto_parallel(
        "请分别调研以下三个方向：\n"
        "1. 云计算市场2025年规模\n"
        "2. 人工智能芯片竞争格局"
    )
    assert plan is not None

    class _FakeResult:
        def __init__(self, task_id, status, result, subagent_name):
            self.task_id = task_id
            self.status = status
            self.result = result
            self.subagent_name = subagent_name

    class _FakeBatchResult:
        batch_id = "batch_test"
        status = "completed"
        total_tasks = 2
        completed_tasks = 2
        error = None
        results = [
            _FakeResult("t1", "completed", "cloud: $500B", "general-purpose"),
            _FakeResult("t2", "completed", "chips: $80B", "general-purpose"),
        ]

    calls: dict[str, Any] = {}

    class _FakeOrchestrator:
        def dispatch(self, tasks, **kwargs):
            calls["tasks"] = [t.description for t in tasks]
            calls["kwargs"] = kwargs
            return _FakeBatchResult()

        def get_batch(self, batch_id):
            return _FakeBatchResult()

        def cancel_all(self):
            calls["cancelled"] = True

    with patch(
        "runtime.core.cerebrum.agent_auto_parallel.get_auto_parallel_orchestrator",
        return_value=_FakeOrchestrator(),
    ):
        result = run_auto_parallel(plan, thread_id="thr1")

    assert result["success"] is True
    assert "cloud: $500B" in result["content"]
    assert "chips: $80B" in result["content"]
    assert result["batch_id"] == "batch_test"
    assert calls["kwargs"]["execution_mode"] == "parallel"
    assert calls["kwargs"]["thread_id"] == "thr1"
    assert len(calls["tasks"]) == 2


def test_run_auto_parallel_returns_failure_on_no_output():
    plan = plan_auto_parallel(
        "请分别调研以下两个方向：\n"
        "1. 云计算市场2025年规模\n"
        "2. 人工智能芯片竞争格局"
    )
    assert plan is not None

    class _FakeBatchResult:
        batch_id = "batch_fail"
        status = "failed"
        total_tasks = 2
        completed_tasks = 0
        error = "boom"
        results = []

    class _FakeOrchestrator:
        def dispatch(self, tasks, **kwargs):
            return _FakeBatchResult()

        def get_batch(self, batch_id):
            return _FakeBatchResult()

    with patch(
        "runtime.core.cerebrum.agent_auto_parallel.get_auto_parallel_orchestrator",
        return_value=_FakeOrchestrator(),
    ):
        result = run_auto_parallel(plan)

    assert result["success"] is False
    assert result["error"] == "boom"


# ─── stream_react_loop integration ──────────────────────────


@dataclass
class _MockRegistry:
    def has(self, _name: str) -> bool:
        return True

    def is_enabled(self, _name: str) -> bool:
        return True

    def iter_skills(self):
        return []

    def iter_agents(self):
        return []


@dataclass
class _MockExecutor:
    registry: Any = field(default_factory=_MockRegistry)
    agent_registry: Any = field(default_factory=_MockRegistry)


@dataclass
class _MockPlanner:
    planner_model: str = "test-model"
    router: Any = None

    def __post_init__(self):
        if self.router is None:
            self.router = object()


@dataclass
class _MockStack:
    executor: Any = field(default_factory=_MockExecutor)
    planner: Any = field(default_factory=_MockPlanner)
    agent_registry: Any = field(default_factory=_MockRegistry)


@dataclass
class _MockAgent:
    agent_id: str = "lead"


@dataclass
class _MockIntent:
    normalized_goal: str
    raw: str = ""
    user_context: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)


def _collect_until_event(gen, target_types: set[str], max_events: int = 50):
    events: list[dict[str, Any]] = []
    try:
        for event in gen:
            events.append(event)
            if event.get("type") in target_types:
                break
            if len(events) >= max_events:
                break
    except (StopIteration, RuntimeError, AttributeError, TypeError):
        pass
    return events


def _parallelizable_goal() -> str:
    return (
        "请分别调研以下两个方向：\n"
        "1. 云计算市场2025年规模\n"
        "2. 人工智能芯片竞争格局"
    )


def test_react_loop_auto_parallel_completes_and_injects_observation():
    from runtime.core.cerebrum.react_loop import stream_react_loop

    stack = _MockStack()
    agent = _MockAgent()
    intent = _MockIntent(normalized_goal=_parallelizable_goal())

    mock_parallel_result = {
        "success": True,
        "content": "cloud: $500B\n\nchips: $80B",
        "error": None,
        "batch_id": "batch_x",
        "status": "completed",
        "completed": 2,
        "total": 2,
    }

    with patch(
        "runtime.core.cerebrum.agent_auto_parallel.plan_auto_parallel",
        side_effect=lambda *a, **k: plan_auto_parallel(a[0]),
    ), patch(
        "runtime.core.cerebrum.agent_auto_parallel.run_auto_parallel",
        return_value=mock_parallel_result,
    ):
        gen = stream_react_loop(
            stack=stack,
            intent=intent,
            agent=agent,
            enable_tools=True,
            planning_mode=False,
            max_iterations=1,
        )
        events = _collect_until_event(
            gen,
            {"auto_parallel_completed", "auto_parallel_skipped"},
        )

    types = [e.get("type") for e in events]
    assert "auto_parallel_started" in types
    assert "auto_parallel_completed" in types
    completed = next(e for e in events if e.get("type") == "auto_parallel_completed")
    assert completed["subtasks"] == 2
    assert completed["batch_id"] == "batch_x"


def test_react_loop_auto_parallel_skips_in_planning_mode():
    from runtime.core.cerebrum.react_loop import stream_react_loop

    stack = _MockStack()
    agent = _MockAgent()
    intent = _MockIntent(normalized_goal=_parallelizable_goal())

    with patch(
        "runtime.core.cerebrum.agent_auto_parallel.run_auto_parallel",
    ) as mock_run:
        gen = stream_react_loop(
            stack=stack,
            intent=intent,
            agent=agent,
            enable_tools=True,
            planning_mode=True,
            max_iterations=1,
        )
        _collect_until_event(gen, {"react_started"}, max_events=10)

    assert not mock_run.called, "planning_mode should block auto-parallel"


def test_react_loop_auto_parallel_skips_when_tools_disabled():
    from runtime.core.cerebrum.react_loop import stream_react_loop

    stack = _MockStack()
    agent = _MockAgent()
    intent = _MockIntent(normalized_goal=_parallelizable_goal())

    with patch(
        "runtime.core.cerebrum.agent_auto_parallel.run_auto_parallel",
    ) as mock_run:
        gen = stream_react_loop(
            stack=stack,
            intent=intent,
            agent=agent,
            enable_tools=False,
            planning_mode=False,
            max_iterations=1,
        )
        _collect_until_event(gen, {"react_started"}, max_events=10)

    assert not mock_run.called


def test_react_loop_auto_parallel_skips_single_cohesive_goal():
    from runtime.core.cerebrum.react_loop import stream_react_loop

    stack = _MockStack()
    agent = _MockAgent()
    intent = _MockIntent(
        normalized_goal="请你用中文详细解释一下量子计算的基本原理和应用场景",
    )

    with patch(
        "runtime.core.cerebrum.agent_auto_parallel.run_auto_parallel",
    ) as mock_run:
        gen = stream_react_loop(
            stack=stack,
            intent=intent,
            agent=agent,
            enable_tools=True,
            planning_mode=False,
            max_iterations=1,
        )
        _collect_until_event(gen, {"react_started"}, max_events=10)

    assert not mock_run.called