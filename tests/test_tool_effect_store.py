from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from runtime.execution.suckers import Skill, SkillRegistry
from runtime.execution.tool_engine import ToolExecutor
from runtime.execution.tool_engine.effect_receipts import ToolEffectReceiptIndex
from runtime.execution.tool_engine.effect_store import SQLiteEffectStore
from runtime.memory.journal import InMemoryJournal, StepEvent
from runtime.platform.models import ArmId, Budget, BudgetLimits, SkillId, TaskId
from runtime.safety.auth import TrustEngine


def _executor_with_shared_store(
    store_path: str | Path,
    handler,
    *,
    lease_ttl_s: float = 0.3,
    wait_timeout_s: float = 4.0,
    journal: InMemoryJournal | None = None,
) -> ToolExecutor:
    journal = journal if journal is not None else InMemoryJournal()
    registry = SkillRegistry()
    registry.register(
        Skill(
            name="shared_effect_tool",
            description="cross-process effect test",
            affinity=["write"],
            trusted_source="skill://public/shared-effect-tool",
            handler=handler,
        )
    )
    executor = ToolExecutor(
        registry=registry,
        immunity=TrustEngine(trusted_sources=["skill://public/*"]),
        journal=journal,
    )
    executor._effect_receipts = ToolEffectReceiptIndex(  # noqa: SLF001
        journal,
        store=SQLiteEffectStore(store_path),
        lease_ttl_s=lease_ttl_s,
        wait_timeout_s=wait_timeout_s,
        poll_interval_s=0.02,
    )
    executor._effect_receipts_journal = journal  # noqa: SLF001
    return executor


class _FailingStepJournal(InMemoryJournal):
    def write(self, event) -> None:
        if isinstance(event, StepEvent):
            raise OSError("simulated process loss before journal append")
        super().write(event)


def _run_shared(executor: ToolExecutor, task_id: TaskId):
    return executor.execute_step(
        step_id=1,
        node_id="react_n1",
        sucker_id=SkillId("shared_effect_tool"),
        args={"value": "one"},
        caller="react_loop",
        task_id=task_id,
        arm_id=ArmId("react_arm"),
        budget=Budget(
            task_id=task_id,
            limits=BudgetLimits(tokens=10_000, usd=1.0),
        ),
    )


def _competing_worker(
    store_path: str,
    effect_path: str,
    task_id: str,
    gate,
    queue,
) -> None:
    def _handler(value: str):
        with Path(effect_path).open("a", encoding="utf-8") as stream:
            stream.write(f"{os.getpid()}:{value}\n")
            stream.flush()
            os.fsync(stream.fileno())
        # Longer than the lease: the heartbeat must retain ownership.
        time.sleep(0.8)
        return {"value": value, "owner": os.getpid()}

    executor = _executor_with_shared_store(store_path, _handler)
    gate.wait(timeout=3)
    step = _run_shared(executor, TaskId(UUID(task_id)))
    queue.put(
        {
            "success": step.success,
            "replayed": "durable_effect_replay" in step.result.stderr_tags,
            "output": step.result.output,
        }
    )


def _crashing_worker(
    store_path: str,
    effect_path: str,
    task_id: str,
    entered,
) -> None:
    def _handler(value: str):
        with Path(effect_path).open("a", encoding="utf-8") as stream:
            stream.write(f"crashed:{value}\n")
            stream.flush()
            os.fsync(stream.fileno())
        entered.set()
        os._exit(23)

    executor = _executor_with_shared_store(
        store_path,
        _handler,
        lease_ttl_s=0.2,
        wait_timeout_s=1.0,
    )
    _run_shared(executor, TaskId(UUID(task_id)))


def test_expired_unstarted_claim_can_be_safely_taken_over(tmp_path: Path) -> None:
    store = SQLiteEffectStore(tmp_path / "effects.sqlite3")
    first = store.claim(
        effect_key="effect:test",
        task_id="task",
        step_id=1,
        sucker_id="tool",
        args_fingerprint="args",
        side_effecting=True,
        holder_id="worker-a",
        lease_ttl_s=0.05,
        observed_durable_intent=False,
    )
    assert first.kind == "execute"

    time.sleep(0.08)
    takeover = store.claim(
        effect_key="effect:test",
        task_id="task",
        step_id=1,
        sucker_id="tool",
        args_fingerprint="args",
        side_effecting=True,
        holder_id="worker-b",
        lease_ttl_s=1,
        observed_durable_intent=False,
    )

    assert takeover.kind == "execute"
    assert takeover.fencing_token > first.fencing_token


def test_expired_started_side_effect_is_never_taken_over(tmp_path: Path) -> None:
    store = SQLiteEffectStore(tmp_path / "effects.sqlite3")
    first = store.claim(
        effect_key="effect:test",
        task_id="task",
        step_id=1,
        sucker_id="tool",
        args_fingerprint="args",
        side_effecting=True,
        holder_id="worker-a",
        lease_ttl_s=0.05,
        observed_durable_intent=False,
    )
    assert store.mark_started(
        effect_key="effect:test",
        holder_id="worker-a",
        fencing_token=first.fencing_token,
        call_id="call-a",
        lease_ttl_s=0.05,
    )

    time.sleep(0.08)
    takeover = store.claim(
        effect_key="effect:test",
        task_id="task",
        step_id=1,
        sucker_id="tool",
        args_fingerprint="args",
        side_effecting=True,
        holder_id="worker-b",
        lease_ttl_s=1,
        observed_durable_intent=False,
    )

    assert takeover.kind == "indeterminate"


def test_two_processes_execute_one_side_effect_and_share_result(tmp_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    store_path = str(tmp_path / "effects.sqlite3")
    effect_path = str(tmp_path / "effect.log")
    task_id = str(uuid4())
    gate = ctx.Event()
    queue = ctx.Queue()
    workers = [
        ctx.Process(
            target=_competing_worker,
            args=(store_path, effect_path, task_id, gate, queue),
        )
        for _ in range(2)
    ]
    for worker in workers:
        worker.start()
    gate.set()
    for worker in workers:
        worker.join(timeout=8)

    assert all(worker.exitcode == 0 for worker in workers)
    results = [queue.get(timeout=1) for _ in workers]
    assert all(result["success"] for result in results)
    assert sum(result["replayed"] for result in results) == 1
    assert len((tmp_path / "effect.log").read_text(encoding="utf-8").splitlines()) == 1


def test_process_crash_after_handler_entry_fails_closed_without_repeating(
    tmp_path: Path,
) -> None:
    ctx = multiprocessing.get_context("spawn")
    store_path = str(tmp_path / "effects.sqlite3")
    effect_path = str(tmp_path / "effect.log")
    task_id = str(uuid4())
    entered = ctx.Event()
    worker = ctx.Process(
        target=_crashing_worker,
        args=(store_path, effect_path, task_id, entered),
    )
    worker.start()
    assert entered.wait(timeout=4)
    worker.join(timeout=4)
    assert worker.exitcode == 23
    time.sleep(0.25)

    calls = 0

    def _must_not_run(value: str):
        nonlocal calls
        calls += 1
        return value

    executor = _executor_with_shared_store(
        store_path,
        _must_not_run,
        lease_ttl_s=0.2,
        wait_timeout_s=1.0,
    )
    step = _run_shared(executor, TaskId(UUID(task_id)))

    assert step.success is False
    assert step.result.error_type == "indeterminate_side_effect"
    assert step.result.output["retry_safe"] is False
    assert calls == 0
    assert (tmp_path / "effect.log").read_text(encoding="utf-8").splitlines() == ["crashed:one"]


def test_committed_receipt_survives_failure_before_journal_step_append(
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "effects.sqlite3"
    task_id = TaskId(uuid4())
    calls = 0

    def _handler(value: str):
        nonlocal calls
        calls += 1
        return {"value": value, "calls": calls}

    first = _executor_with_shared_store(
        store_path,
        _handler,
        journal=_FailingStepJournal(),
    )
    with pytest.raises(OSError, match="before journal append"):
        _run_shared(first, task_id)

    resumed = _executor_with_shared_store(store_path, _handler)
    step = _run_shared(resumed, task_id)

    assert step.success is True
    assert calls == 1
    assert "durable_effect_replay" in step.result.stderr_tags


def test_server_wires_shared_store_even_when_main_journal_is_in_memory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path))

    from runtime.platform.config import AgentConfig, build_from_config
    from runtime.platform.ui import create_app

    stack = build_from_config(AgentConfig(enable_web_skills=False))
    assert isinstance(stack.journal, InMemoryJournal)

    create_app(
        journal=stack.journal,
        registry=stack.registry,
        stack=stack,
        tentacle_enabled=False,
    )

    assert (
        stack.executor._effect_store_path
        == (  # noqa: SLF001
            tmp_path / "tool_effects.sqlite3"
        ).resolve()
    )
