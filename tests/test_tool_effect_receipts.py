from __future__ import annotations

import threading
import time
from uuid import uuid4

from runtime.execution.suckers import Skill, SkillRegistry
from runtime.execution.tool_engine import ToolExecutor
from runtime.execution.tool_engine.effect_receipts import args_fingerprint, effect_key
from runtime.memory.journal import InMemoryJournal, JSONLJournal, ToolEffectIntentEvent
from runtime.platform.models import ArmId, Budget, BudgetLimits, SkillId, TaskId
from runtime.safety.auth import TrustEngine


def _executor(journal, handler, *, affinity: list[str]) -> ToolExecutor:
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="durable_tool",
            description="test durable effects",
            affinity=affinity,
            trusted_source="skill://public/durable-tool",
            handler=handler,
        ),
    )
    return ToolExecutor(
        registry=registry,
        immunity=TrustEngine(trusted_sources=["skill://public/*"]),
        journal=journal,
    )


def _run(executor: ToolExecutor, task_id: TaskId, *, args=None):
    return executor.execute_step(
        step_id=1,
        node_id="react_n1",
        sucker_id=SkillId("durable_tool"),
        args=args or {"value": "x"},
        caller="react_loop",
        task_id=task_id,
        arm_id=ArmId("react_arm"),
        budget=Budget(task_id=task_id, limits=BudgetLimits(tokens=10_000, usd=1.0)),
    )


def test_committed_effect_replays_without_running_handler_again():
    journal = InMemoryJournal()
    calls = 0

    def _handler(value: str):
        nonlocal calls
        calls += 1
        return {"value": value, "calls": calls}

    task_id = TaskId(uuid4())
    first = _run(_executor(journal, _handler, affinity=["write"]), task_id)
    second = _run(_executor(journal, _handler, affinity=["write"]), task_id)

    assert first.success is True
    assert second.success is True
    assert calls == 1
    assert second.result.output == first.result.output
    assert "durable_effect_replay" in second.result.stderr_tags
    assert second.result.cost.tokens == 0
    assert second.result.cost.usd == 0


def test_dangling_side_effect_intent_fails_closed_after_restart():
    journal = InMemoryJournal()
    task_id = TaskId(uuid4())
    args = {"value": "x"}
    journal.write_tool_effect_intent(
        task_id,
        ArmId("react_arm"),
        effect_key=effect_key(task_id, 1, "durable_tool", args),
        call_id=str(uuid4()),
        step_id=1,
        node_id="react_n1",
        sucker_id="durable_tool",
        args_fingerprint=args_fingerprint(args),
        side_effecting=True,
    )
    calls = 0

    def _handler(value: str):
        nonlocal calls
        calls += 1
        return value

    result = _run(_executor(journal, _handler, affinity=["write"]), task_id, args=args)

    assert result.success is False
    assert result.result.error_type == "indeterminate_side_effect"
    assert result.result.output["retry_safe"] is False
    assert calls == 0


def test_dangling_read_only_intent_is_safe_to_retry():
    journal = InMemoryJournal()
    task_id = TaskId(uuid4())
    args = {"value": "x"}
    journal.write_tool_effect_intent(
        task_id,
        ArmId("react_arm"),
        effect_key=effect_key(task_id, 1, "durable_tool", args),
        call_id=str(uuid4()),
        step_id=1,
        node_id="react_n1",
        sucker_id="durable_tool",
        args_fingerprint=args_fingerprint(args),
        side_effecting=False,
    )
    calls = 0

    def _handler(value: str):
        nonlocal calls
        calls += 1
        return value

    result = _run(_executor(journal, _handler, affinity=["read"]), task_id, args=args)

    assert result.success is True
    assert calls == 1


def test_side_effecting_timeout_is_not_retried_inside_executor():
    calls = 0

    def _handler(value: str):
        nonlocal calls
        calls += 1
        raise TimeoutError(value)

    task_id = TaskId(uuid4())
    result = _run(
        _executor(InMemoryJournal(), _handler, affinity=["exec"]),
        task_id,
    )

    assert result.result.status == "timeout"
    assert calls == 1


def test_read_only_transient_failure_still_retries_once():
    calls = 0

    def _handler(value: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise TimeoutError(value)
        return value

    task_id = TaskId(uuid4())
    result = _run(
        _executor(InMemoryJournal(), _handler, affinity=["read"]),
        task_id,
    )

    assert result.success is True
    assert calls == 2
    assert "transient_retry:TimeoutError" in result.result.stderr_tags


def test_effect_intent_survives_jsonl_restart(tmp_path):
    path = tmp_path / "journal.jsonl"
    journal = JSONLJournal(path)
    task_id = TaskId(uuid4())
    args = {"value": "persisted"}
    journal.write_tool_effect_intent(
        task_id,
        ArmId("react_arm"),
        effect_key=effect_key(task_id, 1, "durable_tool", args),
        call_id=str(uuid4()),
        step_id=1,
        node_id="react_n1",
        sucker_id="durable_tool",
        args_fingerprint=args_fingerprint(args),
        side_effecting=True,
    )

    events = JSONLJournal(path).read_by_type("tool_effect_intent")

    assert len(events) == 1
    assert isinstance(events[0], ToolEffectIntentEvent)
    assert events[0].side_effecting is True


def test_committed_effect_replays_from_jsonl_after_process_restart(tmp_path):
    path = tmp_path / "journal.jsonl"
    task_id = TaskId(uuid4())
    calls = 0

    def _handler(value: str):
        nonlocal calls
        calls += 1
        return {"value": value, "calls": calls}

    first = _run(
        _executor(JSONLJournal(path), _handler, affinity=["write"]),
        task_id,
    )
    resumed = _run(
        _executor(JSONLJournal(path), _handler, affinity=["write"]),
        task_id,
    )

    assert first.success is True
    assert resumed.success is True
    assert calls == 1
    assert "durable_effect_replay" in resumed.result.stderr_tags


def test_concurrent_duplicate_delivery_waits_and_reuses_owner_result():
    journal = InMemoryJournal()
    task_id = TaskId(uuid4())
    started = threading.Event()
    release = threading.Event()
    calls = 0

    def _handler(value: str):
        nonlocal calls
        calls += 1
        started.set()
        assert release.wait(timeout=2)
        return {"value": value, "calls": calls}

    executor = _executor(journal, _handler, affinity=["write"])
    results = []

    def _invoke() -> None:
        results.append(_run(executor, task_id))

    owner = threading.Thread(target=_invoke)
    duplicate = threading.Thread(target=_invoke)
    owner.start()
    assert started.wait(timeout=1)
    duplicate.start()
    time.sleep(0.05)
    release.set()
    owner.join(timeout=2)
    duplicate.join(timeout=2)

    assert len(results) == 2
    assert calls == 1
    assert all(step.success for step in results)
    assert sum("durable_effect_replay" in step.result.stderr_tags for step in results) == 1
