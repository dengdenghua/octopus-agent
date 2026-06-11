"""Implementation note."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from runtime.execution.tool_engine import ToolExecutor
from runtime.execution.suckers import Skill, SkillRegistry
from runtime.execution.suckers.builtins import _read_file
from runtime.execution.suckers.write_skills import _write_text_file
from runtime.memory.journal import InMemoryJournal
from runtime.platform.models import (
    ArmId,
    Budget,
    BudgetLimits,
    CostEntry,
    SkillId,
    TaskId,
)
from runtime.platform.process.session import Session, session_scope
from runtime.safety.auth import TrustEngine


@pytest.fixture
def registry() -> SkillRegistry:
    r = SkillRegistry()
    r.register(
        Skill(
            name="echo",
            description="returns its argument",
            affinity=["demo"],
            trusted_source="skill://public/echo",
            handler=lambda **kw: kw.get("msg", ""),
        )
    )
    r.register(
        Skill(
            name="add",
            description="adds a+b",
            affinity=["math"],
            trusted_source="skill://public/add",
            handler=lambda a, b, **kw: a + b,
        )
    )
    r.register(
        Skill(
            name="boom",
            description="always raises",
            affinity=["demo"],
            trusted_source="skill://public/boom",
            handler=lambda **kw: (_ for _ in ()).throw(ValueError("boom!")),
        )
    )
    return r


@pytest.fixture
def immunity() -> TrustEngine:
    return TrustEngine(trusted_sources=["skill://public/*"])


@pytest.fixture
def journal() -> InMemoryJournal:
    return InMemoryJournal()


@pytest.fixture
def budget() -> Budget:
    return Budget(task_id=TaskId(uuid4()), limits=BudgetLimits(tokens=10_000, usd=1.0))


@pytest.fixture
def executor(registry, immunity, journal) -> ToolExecutor:
    return ToolExecutor(registry=registry, immunity=immunity, journal=journal)


class TestHappyPath:
    def test_echo_success(self, executor, journal, budget):
        step = executor.execute_step(
            step_id=0,
            node_id="n0",
            sucker_id=SkillId("echo"),
            args={"msg": "hello"},
            caller="arms/code_arm",
            task_id=budget.task_id,
            arm_id=ArmId("code_arm"),
            budget=budget,
        )
        assert step.success
        assert step.result.status == "success"
        assert step.immune_verdict == "allow"
        # Implementation note.
        assert len(journal) >= 3

    def test_output_captured(self, executor, budget):
        step = executor.execute_step(
            step_id=0,
            node_id="n0",
            sucker_id=SkillId("add"),
            args={"a": 2, "b": 3},
            caller="arms/code_arm",
            task_id=budget.task_id,
            arm_id=ArmId("code_arm"),
            budget=budget,
        )
        assert step.success
        assert step.result.output == 5


class TestHandlerException:
    def test_handler_raises_marked_failed(self, executor, budget, journal):
        step = executor.execute_step(
            step_id=0,
            node_id="n0",
            sucker_id=SkillId("boom"),
            args={},
            caller="arms/code_arm",
            task_id=budget.task_id,
            arm_id=ArmId("code_arm"),
            budget=budget,
        )
        assert not step.success
        assert step.result.status == "failed"
        assert step.result.error_type == "ValueError"

    def test_transient_handler_error_retries_once(self, registry, immunity, journal, budget):
        calls = {"count": 0}

        def flaky(**kw):
            calls["count"] += 1
            if calls["count"] == 1:
                raise TimeoutError("temporary timeout")
            return {"ok": True}

        registry.register(
            Skill(
                name="flaky",
                description="fails once",
                affinity=["demo"],
                trusted_source="skill://public/flaky",
                handler=flaky,
            )
        )
        exe = ToolExecutor(registry, immunity, journal)

        step = exe.execute_step(
            step_id=0,
            node_id="n0",
            sucker_id=SkillId("flaky"),
            args={},
            caller="arms/code_arm",
            task_id=budget.task_id,
            arm_id=ArmId("code_arm"),
            budget=budget,
        )

        assert step.success
        assert calls["count"] == 2
        assert step.result.stderr_tags == ["transient_retry:TimeoutError"]

    def test_permanent_handler_error_does_not_retry(self, registry, immunity, journal, budget):
        calls = {"count": 0}

        def invalid(**kw):
            calls["count"] += 1
            raise ValueError("bad input")

        registry.register(
            Skill(
                name="invalid",
                description="always invalid",
                affinity=["demo"],
                trusted_source="skill://public/invalid",
                handler=invalid,
            )
        )
        exe = ToolExecutor(registry, immunity, journal)

        step = exe.execute_step(
            step_id=0,
            node_id="n0",
            sucker_id=SkillId("invalid"),
            args={},
            caller="arms/code_arm",
            task_id=budget.task_id,
            arm_id=ArmId("code_arm"),
            budget=budget,
        )

        assert not step.success
        assert calls["count"] == 1
        assert step.result.error_type == "ValueError"


class TestImmunityReject:
    def test_untrusted_source_rejected(self, registry, journal, budget):
        """Implementation note."""
        strict_immunity = TrustEngine(
            trusted_sources=[],       # Implementation note.
            self_whitelist=[],        # Implementation note.
            unknown_policy="reject",
        )
        exe = ToolExecutor(registry, strict_immunity, journal)
        step = exe.execute_step(
            step_id=0,
            node_id="n0",
            sucker_id=SkillId("echo"),
            args={"msg": "x"},
            caller="external-agent",    # Implementation note.
            task_id=budget.task_id,
            arm_id=ArmId("some_arm"),
            budget=budget,
        )
        assert step.result.status == "immune_reject"
        # Implementation note.
        assert budget.tokens_spent == 0


class TestBudgetEnforcement:
    def test_insufficient_budget_circuit_broken(self, registry, immunity, journal):
        """Implementation note."""
        tiny = Budget(task_id=TaskId(uuid4()), limits=BudgetLimits(tokens=10, usd=0.0001))
        exe = ToolExecutor(registry, immunity, journal)
        step = exe.execute_step(
            step_id=0,
            node_id="n0",
            sucker_id=SkillId("echo"),
            args={"msg": "x"},
            caller="arms/code_arm",
            task_id=tiny.task_id,
            arm_id=ArmId("code_arm"),
            budget=tiny,
            predicted_cost=CostEntry(tokens_in=500, tokens_out=0, usd=0.01),  # Implementation note.
        )
        assert step.result.status == "circuit_broken"
        # Implementation note.
        assert tiny.status == "exceeded"
        # Implementation note.
        squirts = journal.read_by_type("budget_squirt")
        assert len(squirts) >= 1


class TestReadBeforeWriteGuard:
    def test_existing_file_write_requires_read_in_same_session(self, tmp_path):
        target = tmp_path / "target.txt"
        target.write_text("old", encoding="utf-8")
        reg = SkillRegistry()
        reg.register(
            Skill(
                name="read_file",
                description="Read a file.",
                affinity=["file", "read"],
                trusted_source="skill://public/read_file",
                handler=_read_file,
            ),
            verify_tests=False,
        )
        reg.register(
            Skill(
                name="write_text_file",
                description="Write a file.",
                affinity=["file", "write"],
                trusted_source="skill://public/write_text_file",
                handler=_write_text_file,
            ),
            verify_tests=False,
        )
        exe = ToolExecutor(reg, TrustEngine(trusted_sources=["skill://public/*"]))
        budget = Budget(
            task_id=TaskId(uuid4()),
            limits=BudgetLimits(tokens=10_000, usd=1.0),
        )

        agent = SimpleNamespace(
            agent_id="coder",
            capabilities={"code_mode_unlock": True},
        )
        with session_scope(Session(
            agent=agent,
            metadata={"mode": "code", "workspace_path": str(tmp_path)},
        )):
            blocked = exe.execute_step(
                step_id=0,
                node_id="write",
                sucker_id=SkillId("write_text_file"),
                args={"path": str(target), "content": "new", "overwrite": True},
                caller="test",
                task_id=budget.task_id,
                arm_id=ArmId("test"),
                budget=budget,
            )

            assert blocked.result.status == "failed"
            assert "must read_file" in blocked.result.stderr_tags[-1]
            assert target.read_text(encoding="utf-8") == "old"

            read = exe.execute_step(
                step_id=1,
                node_id="read",
                sucker_id=SkillId("read_file"),
                args={"path": str(target)},
                caller="test",
                task_id=budget.task_id,
                arm_id=ArmId("test"),
                budget=budget,
            )
            assert read.success

            written = exe.execute_step(
                step_id=2,
                node_id="write",
                sucker_id=SkillId("write_text_file"),
                args={"path": str(target), "content": "new", "overwrite": True},
                caller="test",
                task_id=budget.task_id,
                arm_id=ArmId("test"),
                budget=budget,
            )

        assert written.success
        assert target.read_text(encoding="utf-8") == "new"
