"""Project OS: model DAG, store round-trips, and the milestone-driven engine."""

from __future__ import annotations

from runtime.projectos.engine import ProjectEngine
from runtime.projectos.model import Milestone, Project, Task, ready_tasks
from runtime.projectos.store import ProjectStore


# ── model ────────────────────────────────────────────────────────────────────
def test_ready_tasks_respects_dag() -> None:
    t1 = Task(id="T1", milestone_id="M", type="design", goal="a")
    t2 = Task(id="T2", milestone_id="M", type="code", goal="b", depends_on=["T1"])
    # T2 blocked until T1 done
    assert [t.id for t in ready_tasks([t1, t2])] == ["T1"]
    t1.status = "done"
    assert [t.id for t in ready_tasks([t1, t2])] == ["T2"]


def test_roundtrips() -> None:
    p = Project(id="P1", name="x", goal="g", milestone_ids=["M1"])
    assert Project.from_dict(p.to_dict()).milestone_ids == ["M1"]
    m = Milestone(id="M1", name="n", goal="g", spec={"power": "<5W"},
                  success_criteria=["works"], dependencies=["M0"])
    assert Milestone.from_dict(m.to_dict()).spec == {"power": "<5W"}
    t = Task(id="T1", milestone_id="M1", type="research", goal="g", depends_on=["T0"])
    assert Task.from_dict(t.to_dict()).depends_on == ["T0"]


# ── store ────────────────────────────────────────────────────────────────────
def test_store_roundtrip(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    s.save_project(Project(id="P1", name="x", goal="g"))
    s.save_milestone("P1", Milestone(id="M1", name="m", goal="g"))
    s.save_task(Task(id="T1", milestone_id="M1", type="code", goal="g"))
    assert s.get_project("P1").goal == "g"
    assert [m.id for m in s.milestones_for("P1")] == ["M1"]
    assert [t.id for t in s.tasks_for_milestone("M1")] == ["T1"]


def test_store_binds_thread_to_project(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    s.save_project(Project(id="P1", name="x", goal="g"))
    s.bind_thread("thread-1", "P1")
    assert s.project_for_thread("thread-1").id == "P1"
    assert s.project_for_thread("missing") is None


def test_store_project_events_roundtrip_and_limit(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    s.save_project(Project(id="P1", name="x", goal="g"))
    s.append_event("P1", kind="project.recover", payload={"n": 1}, created_at=1.0)
    s.append_event("P1", kind="task.intervention", payload={"n": 2}, created_at=2.0)
    s.append_event("P2", kind="task.intervention", payload={"n": 3}, created_at=3.0)

    events = s.events_for_project("P1")
    assert [event["kind"] for event in events] == ["project.recover", "task.intervention"]
    assert [event["payload"]["n"] for event in events] == [1, 2]
    assert [event["payload"]["n"] for event in s.events_for_project("P1", limit=1)] == [2]


def test_store_task_terminal_status_is_immutable_by_default(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    original = Task(id="T1", milestone_id="M1", type="code", goal="g")
    original.status = "done"
    original.output = "accepted"
    s.save_task(original)

    stale_failure = Task(id="T1", milestone_id="M1", type="code", goal="g")
    stale_failure.status = "failed"
    stale_failure.output = "late failure"
    returned = s.save_task(stale_failure)

    assert returned.status == "done"
    assert returned.output == "accepted"
    stored = s.get_task("T1")
    assert stored.status == "done"
    assert stored.output == "accepted"


def test_store_task_terminal_status_can_be_reopened_explicitly(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    original = Task(id="T1", milestone_id="M1", type="code", goal="g")
    original.status = "failed"
    original.output = "bad"
    original.attempts = 2
    s.save_task(original)

    recovered = Task(id="T1", milestone_id="M1", type="code", goal="g")
    recovered.status = "pending"
    recovered.output = None
    recovered.attempts = 0
    returned = s.save_task(recovered, allow_terminal_rewrite=True)

    assert returned.status == "pending"
    assert returned.output is None
    assert returned.attempts == 0
    assert s.get_task("T1").status == "pending"


def test_store_project_terminal_status_is_immutable_by_default(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    original = Project(id="P1", name="x", goal="g", status="done")
    s.save_project(original)

    stale = Project(id="P1", name="x", goal="g", status="blocked", current_ms="MS1")
    returned = s.save_project(stale)

    assert returned.status == "done"
    assert returned.current_ms is None
    assert s.get_project("P1").status == "done"


def test_store_project_terminal_status_can_be_reopened_explicitly(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    original = Project(id="P1", name="x", goal="g", status="done")
    s.save_project(original)

    reopened = Project(id="P1", name="x", goal="g", status="running", current_ms="MS1")
    returned = s.save_project(reopened, allow_terminal_rewrite=True)

    assert returned.status == "running"
    assert returned.current_ms == "MS1"
    assert s.get_project("P1").status == "running"


def test_store_milestone_terminal_status_is_immutable_by_default(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    original = Milestone(id="MS1", name="m", goal="g", status="done")
    s.save_milestone("P1", original)

    stale = Milestone(id="MS1", name="m", goal="g", status="blocked")
    returned = s.save_milestone("P1", stale)

    assert returned.status == "done"
    assert s.get_milestone("MS1").status == "done"


def test_store_milestone_terminal_status_can_be_reopened_explicitly(tmp_path) -> None:
    s = ProjectStore(base_dir=tmp_path)
    original = Milestone(id="MS1", name="m", goal="g", status="done")
    s.save_milestone("P1", original)

    reopened = Milestone(id="MS1", name="m", goal="g", status="in_progress")
    returned = s.save_milestone("P1", reopened, allow_terminal_rewrite=True)

    assert returned.status == "in_progress"
    assert s.get_milestone("MS1").status == "in_progress"


# ── engine ───────────────────────────────────────────────────────────────────
def _stub_milestones(goal: str) -> list[Milestone]:
    return [
        Milestone(id="MS1", name="research", goal="scope it"),
        Milestone(id="MS2", name="build", goal="build it", dependencies=["MS1"]),
        Milestone(id="MS3", name="verify", goal="verify it", dependencies=["MS2"]),
    ]


def _stub_decompose(ms: Milestone) -> list[Task]:
    # two tasks with a dependency, to exercise the DAG within a milestone
    return [
        Task(id=f"{ms.id}-T1", milestone_id=ms.id, type="research", goal=f"{ms.goal} part1"),
        Task(id=f"{ms.id}-T2", milestone_id=ms.id, type="code", goal=f"{ms.goal} part2",
             depends_on=[f"{ms.id}-T1"]),
    ]


def _engine(tmp_path, **hooks) -> ProjectEngine:
    generate_milestones = hooks.pop("generate_milestones", _stub_milestones)
    decompose_tasks = hooks.pop("decompose_tasks", _stub_decompose)
    return ProjectEngine(
        ProjectStore(base_dir=tmp_path),
        generate_milestones=generate_milestones,
        decompose_tasks=decompose_tasks,
        **hooks,
    )


def test_plan_generates_milestones(tmp_path) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("sleep sys", "make a smart sleep system")
    assert p.status == "running"
    assert [m.id for m in eng.store.milestones_for(p.id)] == ["MS1", "MS2", "MS3"]


def test_plan_falls_back_when_milestone_generation_fails(tmp_path) -> None:
    def broken_generate(goal: str) -> list[Milestone]:
        raise RuntimeError(f"planner unavailable for {goal}")

    eng = _engine(tmp_path, generate_milestones=broken_generate)

    p = eng.plan("fallback", "ship despite planner outage")

    assert p.status == "running"
    assert [m.id for m in eng.store.milestones_for(p.id)] == ["MS1", "MS2", "MS3"]


def test_full_run_drives_project_to_done(tmp_path) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("sleep sys", "make a smart sleep system")
    result = eng.run(p.id, max_ticks=50)
    assert result["final_status"] == "done"
    # every milestone reached done, in dependency order
    mss = {m.id: m.status for m in eng.store.milestones_for(p.id)}
    assert mss == {"MS1": "done", "MS2": "done", "MS3": "done"}
    # all tasks done
    for ms_id in ("MS1", "MS2", "MS3"):
        assert all(t.status == "done" for t in eng.store.tasks_for_milestone(ms_id))


def test_dependent_milestone_waits(tmp_path) -> None:
    # MS2 must not start before MS1 is done — one tick only activates MS1.
    eng = _engine(tmp_path)
    p = eng.plan("x", "g")
    eng.tick(p.id)  # activates MS1 + creates its tasks
    assert eng.store.get_milestone("MS1").status == "in_progress"
    assert eng.store.get_milestone("MS2").status == "pending"  # still waiting on MS1
    assert eng.store.tasks_for_milestone("MS2") == []


def test_qa_rejection_retries_then_passes(tmp_path) -> None:
    calls = {"n": 0}

    def flaky_qa(task: Task, ms: Milestone) -> dict:
        # reject the very first QA, approve everything after
        calls["n"] += 1
        return {"approved": calls["n"] > 1, "reason": "flaky"}

    eng = _engine(tmp_path, qa_task=flaky_qa)
    p = eng.plan("x", "g")
    result = eng.run(p.id, max_ticks=50)
    assert result["final_status"] == "done"  # retry recovered the rejected task


def test_task_execution_error_retries_then_passes(tmp_path) -> None:
    calls: dict[str, int] = {}

    def flaky_execute(task: Task, context: dict) -> str:
        calls[task.id] = calls.get(task.id, 0) + 1
        if task.id == "MS1-T1" and calls[task.id] == 1:
            raise RuntimeError("transient tool failure")
        return f"ok:{task.id}"

    eng = _engine(tmp_path, execute_task=flaky_execute)
    p = eng.plan("x", "g")
    result = eng.run(p.id, max_ticks=50)

    assert result["final_status"] == "done"
    assert calls["MS1-T1"] == 2
    assert eng.store.get_task("MS1-T1").attempts == 2
    events = [event for tick in result["history"] for event in tick["events"]]
    assert "task_error_retry:MS1-T1" in events


def test_task_execution_error_blocks_project_after_retry_cap(tmp_path) -> None:
    def failing_execute(task: Task, context: dict) -> str:
        if task.id == "MS1-T1":
            raise RuntimeError("persistent tool failure")
        return f"ok:{task.id}"

    eng = _engine(tmp_path, execute_task=failing_execute)
    p = eng.plan("x", "g")
    result = eng.run(p.id, max_ticks=20)

    assert result["final_status"] == "blocked"
    assert eng.store.get_project(p.id).status == "blocked"
    assert eng.store.get_project(p.id).current_ms == "MS1"
    assert eng.store.get_milestone("MS1").status == "blocked"
    assert eng.store.get_task("MS1-T1").status == "failed"
    assert eng.store.get_task("MS1-T1").attempts == 2
    events = [event for tick in result["history"] for event in tick["events"]]
    assert "task_error_retry:MS1-T1" in events
    assert "task_failed:MS1-T1" in events
    assert "project_blocked:task_failed" in events


def test_stale_running_claim_does_not_execute_terminal_task(tmp_path, monkeypatch) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("x", "g")
    eng.tick(p.id)
    calls = {"execute": 0}
    original_save_task = eng.store.save_task

    def stale_save(task: Task, **kwargs):
        if task.id == "MS1-T2" and task.status == "running":
            terminal = Task(id=task.id, milestone_id=task.milestone_id, type=task.type, goal=task.goal)
            terminal.status = "done"
            terminal.output = "already accepted"
            return terminal
        return original_save_task(task, **kwargs)

    def execute(task: Task, context: dict) -> str:
        calls["execute"] += 1
        return "should not run"

    monkeypatch.setattr(eng.store, "save_task", stale_save)
    eng._execute = execute

    tick = eng.tick(p.id)

    assert "task_stale_claim_ignored:MS1-T2" in tick["events"]
    assert calls["execute"] == 0


def test_recover_reopens_blocked_project_and_reruns_task(tmp_path) -> None:
    fail = {"enabled": True}

    def maybe_failing_execute(task: Task, context: dict) -> str:
        if task.id == "MS1-T1" and fail["enabled"]:
            raise RuntimeError("persistent tool failure")
        return f"ok:{task.id}"

    eng = _engine(tmp_path, execute_task=maybe_failing_execute)
    p = eng.plan("x", "g")
    blocked = eng.run(p.id, max_ticks=20)
    assert blocked["final_status"] == "blocked"

    fail["enabled"] = False
    recovered = eng.recover(p.id)
    assert recovered["project_status"] == "running"
    assert "project_recovered" in recovered["events"]
    assert "task_recovered:MS1-T1" in recovered["events"]
    audit = eng.store.events_for_project(p.id)
    assert audit[-1]["kind"] == "project.recover"
    assert audit[-1]["payload"]["events"] == recovered["events"]
    assert eng.store.get_task("MS1-T1").status == "pending"
    assert eng.store.get_task("MS1-T1").attempts == 0

    done = eng.run(p.id, max_ticks=20)
    assert done["final_status"] == "done"
    assert eng.store.get_project(p.id).status == "done"
    assert eng.store.get_task("MS1-T1").status == "done"


def test_recover_explicit_task_resets_downstream_dependants(tmp_path) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("x", "g")
    eng.tick(p.id)
    t1 = eng.store.get_task("MS1-T1")
    t2 = eng.store.get_task("MS1-T2")
    t1.status = "failed"
    t1.output = "bad upstream"
    t1.attempts = 2
    t2.status = "done"
    t2.output = "stale downstream"
    eng.store.save_task(t1)
    eng.store.save_task(t2)
    ms = eng.store.get_milestone("MS1")
    ms.status = "blocked"
    eng.store.save_milestone(p.id, ms)
    p.status = "blocked"
    p.current_ms = "MS1"
    eng.store.save_project(p)

    recovered = eng.recover(p.id, task_ids=["MS1-T1"])

    assert recovered["project_status"] == "running"
    assert "task_recovered:MS1-T1" in recovered["events"]
    assert "task_recovered:MS1-T2" in recovered["events"]
    assert eng.store.get_task("MS1-T1").status == "pending"
    assert eng.store.get_task("MS1-T2").status == "pending"
    assert eng.store.get_task("MS1-T2").output is None


def test_intervene_reassign_resets_blocked_task_and_reopens_project(tmp_path) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("x", "g")
    eng.tick(p.id)
    task = eng.store.get_task("MS1-T1")
    task.status = "failed"
    task.output = "bad"
    task.assigned_agent = "old-agent"
    task.attempts = 2
    eng.store.save_task(task)
    ms = eng.store.get_milestone("MS1")
    ms.status = "blocked"
    eng.store.save_milestone(p.id, ms)
    p.status = "blocked"
    p.current_ms = "MS1"
    eng.store.save_project(p)

    result = eng.intervene_task(
        p.id,
        "MS1-T1",
        action="reassign",
        assigned_agent="new-agent",
    )

    updated = eng.store.get_task("MS1-T1")
    assert result["project_status"] == "running"
    assert "task_reassigned:MS1-T1" in result["events"]
    assert "project_recovered" in result["events"]
    audit = eng.store.events_for_project(p.id)
    assert audit[-1]["kind"] == "task.intervention"
    assert audit[-1]["payload"]["action"] == "reassign"
    assert audit[-1]["payload"]["assigned_agent"] == "new-agent"
    assert updated.status == "pending"
    assert updated.assigned_agent == "new-agent"
    assert updated.attempts == 0
    assert updated.output is None

    done = eng.run(p.id, max_ticks=20)
    assert done["final_status"] == "done"
    assert eng.store.get_task("MS1-T1").assigned_agent == "new-agent"


def test_intervene_complete_and_skip_allow_milestone_to_finish(tmp_path) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("x", "g")
    eng.tick(p.id)

    completed = eng.intervene_task(
        p.id,
        "MS1-T1",
        action="complete",
        output="operator accepted research",
        reason="manual review passed",
    )
    assert "task_completed_by_operator:MS1-T1" in completed["events"]

    skipped = eng.intervene_task(
        p.id,
        "MS1-T2",
        action="skip",
        reason="implementation not needed",
    )
    assert "task_skipped:MS1-T2" in skipped["events"]

    tick = eng.tick(p.id)
    assert "milestone_done:MS1" in tick["events"]
    assert eng.store.get_milestone("MS1").status == "done"
    assert eng.store.get_task("MS1-T2").output["skipped"] is True


def test_intervene_reset_cascades_to_downstream_dependants(tmp_path) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("x", "g")
    eng.tick(p.id)
    t1 = eng.store.get_task("MS1-T1")
    t2 = eng.store.get_task("MS1-T2")
    t1.status = "done"
    t1.output = "old upstream"
    t2.status = "done"
    t2.output = "old downstream"
    eng.store.save_task(t1)
    eng.store.save_task(t2)

    result = eng.intervene_task(p.id, "MS1-T1", action="reset")

    assert "task_reset:MS1-T1" in result["events"]
    assert "task_reset:MS1-T2" in result["events"]
    assert eng.store.get_task("MS1-T1").status == "pending"
    assert eng.store.get_task("MS1-T2").status == "pending"
    assert eng.store.get_task("MS1-T2").output is None


def test_milestone_gate_blocks_when_criteria_unmet(tmp_path) -> None:
    def strict_gate(ms: Milestone, tasks: list[Task]) -> dict:
        return {"met": ms.id != "MS1", "reason": "MS1 forced-fail"}

    eng = _engine(tmp_path, gate_milestone=strict_gate)
    p = eng.plan("x", "g")
    result = eng.run(p.id, max_ticks=20)
    assert result["final_status"] == "blocked"
    assert eng.store.get_project(p.id).status == "blocked"
    assert eng.store.get_project(p.id).current_ms == "MS1"
    assert eng.store.get_milestone("MS1").status == "blocked"
    events = [event for tick in result["history"] for event in tick["events"]]
    assert "project_blocked:gate_failed" in events


def test_decompose_exception_blocks_project_instead_of_crashing_tick(tmp_path) -> None:
    def broken_decompose(ms: Milestone) -> list[Task]:
        raise RuntimeError(f"cannot decompose {ms.id}")

    eng = _engine(tmp_path, decompose_tasks=broken_decompose)
    p = eng.plan("x", "g")

    tick = eng.tick(p.id)

    assert "tasks_decompose_failed:MS1" in tick["events"]
    assert "project_blocked:decompose_failed" in tick["events"]
    assert tick["project_status"] == "blocked"
    assert eng.store.get_project(p.id).status == "blocked"
    assert eng.store.get_milestone("MS1").status == "blocked"
    audit = eng.store.events_for_project(p.id)
    assert audit[-1]["kind"] == "project.decompose_failed"
    assert "RuntimeError" in audit[-1]["payload"]["error"]


def test_empty_decompose_blocks_project_instead_of_spinning(tmp_path) -> None:
    eng = _engine(tmp_path, decompose_tasks=lambda _ms: [])
    p = eng.plan("x", "g")

    result = eng.run(p.id, max_ticks=5)

    assert result["final_status"] == "blocked"
    events = [event for tick in result["history"] for event in tick["events"]]
    assert "tasks_decompose_empty:MS1" in events
    assert "project_blocked:decompose_empty" in events
    assert eng.store.tasks_for_milestone("MS1") == []


def test_unreachable_task_dependency_blocks_project_instead_of_spinning(tmp_path) -> None:
    def bad_dag(ms: Milestone) -> list[Task]:
        return [
            Task(
                id=f"{ms.id}-T1",
                milestone_id=ms.id,
                type="code",
                goal="blocked forever",
                depends_on=["missing-task"],
            )
        ]

    eng = _engine(tmp_path, decompose_tasks=bad_dag)
    p = eng.plan("x", "g")

    result = eng.run(p.id, max_ticks=5)

    assert result["final_status"] == "blocked"
    events = [event for tick in result["history"] for event in tick["events"]]
    assert "milestone_blocked_dag:MS1" in events
    assert "project_blocked:task_dag_blocked" in events
    assert eng.store.get_project(p.id).current_ms == "MS1"


def test_assigner_exception_retries_then_blocks_project(tmp_path) -> None:
    def broken_assign(task: Task) -> str:
        raise RuntimeError(f"no assignee for {task.id}")

    eng = _engine(tmp_path, assign_agent=broken_assign)
    p = eng.plan("x", "g")

    result = eng.run(p.id, max_ticks=10)

    assert result["final_status"] == "blocked"
    task = eng.store.get_task("MS1-T1")
    assert task.status == "failed"
    assert task.attempts == 2
    assert "assignment error: RuntimeError" in task.output
    events = [event for tick in result["history"] for event in tick["events"]]
    assert "task_assignment_error_retry:MS1-T1" in events
    assert "task_failed_assignment:MS1-T1" in events


def test_qa_exception_retries_then_blocks_project(tmp_path) -> None:
    def broken_qa(task: Task, ms: Milestone) -> dict:
        raise RuntimeError(f"qa unavailable for {task.id}")

    eng = _engine(tmp_path, qa_task=broken_qa)
    p = eng.plan("x", "g")

    result = eng.run(p.id, max_ticks=10)

    assert result["final_status"] == "blocked"
    task = eng.store.get_task("MS1-T1")
    assert task.status == "failed"
    assert task.attempts == 2
    assert "qa error: RuntimeError" in task.qa_verdict["reason"]
    events = [event for tick in result["history"] for event in tick["events"]]
    assert "task_qa_error_retry:MS1-T1" in events
    assert "task_failed_qa_error:MS1-T1" in events


def test_gate_exception_blocks_project_instead_of_crashing_tick(tmp_path) -> None:
    def broken_gate(ms: Milestone, tasks: list[Task]) -> dict:
        raise RuntimeError(f"gate unavailable for {ms.id}")

    eng = _engine(tmp_path, gate_milestone=broken_gate)
    p = eng.plan("x", "g")

    result = eng.run(p.id, max_ticks=10)

    assert result["final_status"] == "blocked"
    assert eng.store.get_milestone("MS1").status == "blocked"
    events = [event for tick in result["history"] for event in tick["events"]]
    assert "milestone_gate_error:MS1" in events
    assert "project_blocked:gate_error" in events
    audit = eng.store.events_for_project(p.id)
    assert audit[-1]["kind"] == "project.gate_failed"
    assert "RuntimeError" in audit[-1]["payload"]["error"]


def test_stale_project_block_does_not_downgrade_done_project(tmp_path) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("x", "g")
    p.status = "done"
    p.current_ms = None
    eng.store.save_project(p)
    stale = Project(id=p.id, name=p.name, goal=p.goal, status="running", current_ms="MS1")
    events: list[str] = []

    eng._block_project(stale, "MS1", events, reason="late_failure")

    stored = eng.store.get_project(p.id)
    assert stored.status == "done"
    assert stored.current_ms is None
    assert "project_blocked:late_failure" not in events
    assert "project_stale_block_ignored:late_failure" in events


def test_stale_done_tick_reports_stored_terminal_project_status(tmp_path) -> None:
    eng = _engine(tmp_path)
    p = eng.plan("x", "g")
    for ms in eng.store.milestones_for(p.id):
        ms.status = "done"
        eng.store.save_milestone(p.id, ms)
    failed = Project(
        id=p.id,
        name=p.name,
        goal=p.goal,
        milestone_ids=p.milestone_ids,
        status="failed",
        current_ms="MS2",
    )
    eng.store.save_project(failed, allow_terminal_rewrite=True)

    tick = eng.tick(p.id)

    assert tick["project_status"] == "failed"
    assert tick["current_ms"] == "MS2"
    assert f"project_terminal_write_ignored:{p.id}" in tick["events"]
    assert eng.store.get_project(p.id).status == "failed"


def test_stale_gate_failure_does_not_downgrade_done_milestone(tmp_path) -> None:
    def strict_gate(ms: Milestone, tasks: list[Task]) -> dict:
        return {"met": False, "reason": "late fail"}

    eng = _engine(tmp_path, gate_milestone=strict_gate)
    p = eng.plan("x", "g")
    ms = eng.store.milestones_for(p.id)[0]
    ms.status = "done"
    eng.store.save_milestone(p.id, ms)
    t1 = Task(id="MS1-T1", milestone_id="MS1", type="research", goal="a")
    t1.status = "done"
    t2 = Task(id="MS1-T2", milestone_id="MS1", type="code", goal="b")
    t2.status = "done"
    eng.store.save_task(t1)
    eng.store.save_task(t2)
    stale_ms = Milestone(id="MS1", name="research", goal="scope it", status="in_progress")
    events: list[str] = []

    eng._gate_milestone(p, stale_ms, events)

    assert eng.store.get_milestone("MS1").status == "done"
    assert "milestone_gate_failed:MS1" not in events
    assert "milestone_stale_gate_failed_ignored:MS1" in events
