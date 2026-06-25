"""REC button (teach-repeat) now forges a reusable skill from the conversation's
real journal trajectory via the active single-demo forge — instead of the old
empty-template stub. The immune gate still quarantines dangerous macros.
"""

from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.execution.suckers import Skill, SkillRegistry
from runtime.memory.journal import InMemoryJournal
from runtime.platform.models import (
    ArmId,
    ExecutionResult,
    Step,
    TaskId,
    ToolCall,
    Trajectory,
    TrajectoryOutcome,
)
from runtime.sensing.gateway.teach_repeat_router import create_teach_repeat_router


def _client(thread_id: str, suckers: list[str]):
    journal = InMemoryJournal()
    registry = SkillRegistry()
    for name in set(suckers):
        registry.register(
            Skill(
                name=name,
                trusted_source=f"skill://public/{name}",
                handler=lambda **kw: {"ok": True},
            ),
            verify_tests=False,
        )
    steps = []
    for i, s in enumerate(suckers):
        call = ToolCall(caller="test", sucker_id=s, args={})
        steps.append(
            Step(
                step_id=i,
                node_id=f"n{i}",
                action=call,
                result=ExecutionResult(
                    call_id=call.call_id, status="success", output={"ok": True}
                ),
            )
        )
    # The trajectory react_loop would have written for this conversation.
    journal.write_trajectory(
        Trajectory(
            task_id=TaskId(uuid4()),
            thread_id=thread_id,
            arm_id=ArmId("react_arm"),
            strategy_id="react_loop",
            steps=steps,
            outcome=TrajectoryOutcome(success=True),
        )
    )
    app = FastAPI()
    app.include_router(create_teach_repeat_router(journal=journal, registry=registry))
    return TestClient(app), registry


def test_rec_stop_forges_skill_from_thread_trajectory():
    client, registry = _client("t1", ["list_cwd", "count_words"])
    client.post("/api/teach-repeat/record/start", json={"thread_id": "t1", "name": "demo"})
    resp = client.post(
        "/api/teach-repeat/record/stop", json={"thread_id": "t1", "use_llm": True}
    )
    data = resp.json()
    assert data["status"] == "promoted"
    assert len(data["forged"]) == 1
    assert registry.has(data["forged"][0])


def test_rec_stop_quarantines_dangerous_conversation():
    client, registry = _client("t2", ["list_cwd", "exec_shell"])
    client.post("/api/teach-repeat/record/start", json={"thread_id": "t2", "name": "demo"})
    resp = client.post("/api/teach-repeat/record/stop", json={"thread_id": "t2"})
    data = resp.json()
    assert data["status"] == "quarantined"
    assert data["forged"] == []


def test_rec_stop_no_trajectory_for_thread():
    client, _registry = _client("t3", ["list_cwd", "count_words"])
    client.post("/api/teach-repeat/record/start", json={"thread_id": "other", "name": "demo"})
    resp = client.post("/api/teach-repeat/record/stop", json={"thread_id": "other"})
    assert resp.json()["status"] == "no_successful_trajectory"
