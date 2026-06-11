from __future__ import annotations

from runtime.memory.journal import InMemoryJournal
from runtime.platform.models import (
    ArmId,
    ExecutionResult,
    Step,
    ToolCall,
    Trajectory,
    TrajectoryOutcome,
)
from runtime.sensing.gateway.openai_gateway_router import synthesize_reply
from runtime.sensing.model_router.models import MockModelRouter


def _web_search_trajectory() -> Trajectory:
    call = ToolCall(
        caller="arms/research",
        sucker_id="web_search",
        args={"query": "NAS market research", "max_results": 2},
    )
    step = Step(
        step_id=0,
        node_id="n0",
        action=call,
        result=ExecutionResult(
            call_id=call.call_id,
            status="success",
            output={
                "query": "NAS market research",
                "backend": "test",
                "results": [
                    {
                        "title": "Synology NAS product line",
                        "url": "https://www.synology.com/",
                        "snippet": "Official NAS product and storage platform information.",
                    },
                    {
                        "title": "QNAP NAS overview",
                        "url": "https://www.qnap.com/",
                        "snippet": "Official NAS hardware and software product overview.",
                    },
                ],
            },
        ),
    )
    return Trajectory(
        task_id=call.call_id,
        arm_id=ArmId("research_arm"),
        steps=[step],
        outcome=TrajectoryOutcome(success=True),
    )


def test_research_synthesis_falls_back_to_complete_report_when_llm_returns_plan_json():
    class Planner:
        planner_model = "mock/report"
        router = MockModelRouter(response='{"reasoning":"still planning","nodes":[]}')

    class Stack:
        planner = Planner()
        journal = InMemoryJournal()

    report = synthesize_reply(
        Stack(),
        goal="NAS market research report",
        trajectory=_web_search_trajectory(),
        user_context={"metadata": {"mode": "deep"}},
    )

    assert report.startswith("# NAS market research report 深度研究报告")
    assert "## 执行摘要" in report
    assert "## 调研范围与方法" in report
    assert "## 证据与来源" in report
    assert "## 结论与建议" in report
    assert "Synology NAS product line" in report
    assert "https://www.synology.com/" in report
    assert '"nodes"' not in report
    assert not report.lstrip().startswith("✓")
