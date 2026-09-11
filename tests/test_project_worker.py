import asyncio
import time
from contextvars import ContextVar
from threading import Event

import pytest

from runtime.projectos.worker import run_project_worker
from runtime.safety.approval.cancellation import OperationCancelled, current_cancellation_token


def test_project_interrupt_reaches_running_worker_and_preserves_context():
    marker = ContextVar("project_worker_test")
    entered = Event()
    stopped = Event()

    def worker():
        assert marker.get() == "owner-context"
        entered.set()
        token = current_cancellation_token()
        deadline = time.monotonic() + 3
        try:
            while time.monotonic() < deadline:
                token.throw_if_cancelled()
                time.sleep(0.01)
            raise AssertionError("cancellation was not propagated")
        finally:
            stopped.set()

    async def case():
        marker.set("owner-context")
        with pytest.raises(OperationCancelled):
            await run_project_worker(worker, entered.is_set)
        assert stopped.is_set()

    asyncio.run(case())


def test_project_worker_returns_normally_without_interrupt():
    assert asyncio.run(run_project_worker(lambda: "done", lambda: False)) == "done"


def test_cancelled_project_does_not_dispatch_next_task(tmp_path):
    from runtime.projectos.engine import ProjectEngine
    from runtime.projectos.model import Milestone, Task
    from runtime.projectos.store import ProjectStore
    from runtime.safety.approval.cancellation import CancellationSource, scoped_cancellation

    source = CancellationSource()
    executed = []
    reviewed = []

    def execute(task, context):
        executed.append(task.id)
        source.cancel(reason="user stopped")
        return "partial output"

    engine = ProjectEngine(
        ProjectStore(tmp_path),
        generate_milestones=lambda _: [Milestone(id="M", name="M", goal="work")],
        decompose_tasks=lambda ms: [Task(id=f"T{i}", milestone_id=ms.id, type="research", goal="work") for i in (1, 2)],
        execute_task=execute,
        qa_task=lambda task, ms: reviewed.append(task.id) or {"approved": True},
    )
    project = engine.plan("P", "work")
    with scoped_cancellation(source.token), pytest.raises(OperationCancelled):
        engine.run(project.id)
    assert len(executed) == 1
    assert reviewed == []
    task = engine.store.get_task(executed[0])
    assert task.status == "pending"
    assert task.attempts == 1
    assert task.output == "partial output"
    assert task.qa_verdict["review_error"] is True
