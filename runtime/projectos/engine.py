"""L2 execution engine — the milestone-driven loop.

    while project_not_done:
        1. MS check        — activate the next milestone whose deps are met
        2. assign tasks    — decompose a fresh milestone into a task DAG
        3. agents execute  — run the ready frontier (role chosen by task type)
        4. QA evaluate     — gate each task output against the spec; retry/fail
        5. update MS       — when all tasks pass, gate the milestone & advance

The milestone is the stop condition (project done ⇔ all milestones done), not the
loop. Every step writes back through the store (resumable), and the four
intelligence hooks (generate / decompose / execute / qa / gate) are injected:
production wires them to LLM + the cowork subagent runner; tests/demo pass
deterministic stubs. The engine itself is pure orchestration.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import uuid4

from runtime.projectos.model import (
    ROLE_FOR_TASK,
    Milestone,
    Project,
    Task,
    ready_tasks,
)
from runtime.projectos.store import ProjectStore

MilestoneGenerator = Callable[[str], list[Milestone]]  # (project_goal) -> milestones
TaskDecomposer = Callable[[Milestone], list[Task]]      # (milestone) -> task DAG
Executor = Callable[[Task, dict[str, Any]], Any]        # (task, context) -> output
QAEvaluator = Callable[[Task, Milestone], dict[str, Any]]      # -> {"approved", "reason"}
MilestoneGate = Callable[[Milestone, list[Task]], dict[str, Any]]  # -> {"met", "reason"}

MAX_TASK_ATTEMPTS = 2


def stub_generate_milestones(goal: str) -> list[Milestone]:
    """No-LLM fallback: a generic Plan → Build → Verify phasing that fits almost
    any project, so the engine/CLI runs deterministically without a model router
    (production injects LLM hooks for goal-specific milestones)."""
    return [
        Milestone(id="MS1", name="plan", goal=f"Scope and plan: {goal}",
                  success_criteria=["plan approved"]),
        Milestone(id="MS2", name="build", goal=f"Build: {goal}",
                  success_criteria=["implementation complete"], dependencies=["MS1"]),
        Milestone(id="MS3", name="verify", goal=f"Verify and deliver: {goal}",
                  success_criteria=["verified against goal"], dependencies=["MS2"]),
    ]


def stub_decompose_tasks(ms: Milestone) -> list[Task]:
    """No-LLM fallback: a research → execution pair (a 2-node DAG)."""
    return [
        Task(id=f"{ms.id}-T1", milestone_id=ms.id, type="research", goal=f"{ms.goal} — assess"),
        Task(id=f"{ms.id}-T2", milestone_id=ms.id, type="code", goal=f"{ms.goal} — do",
             depends_on=[f"{ms.id}-T1"]),
    ]


def _default_execute(task: Task, context: dict[str, Any]) -> str:
    return f"[{task.assigned_role}] output for «{task.goal}»"


def _default_qa(task: Task, milestone: Milestone) -> dict[str, Any]:
    ok = bool(task.output)
    return {"approved": ok, "reason": "non-empty output" if ok else "empty output"}


def _default_gate(milestone: Milestone, tasks: list[Task]) -> dict[str, Any]:
    met = bool(tasks) and all(t.status == "done" for t in tasks)
    return {"met": met, "reason": "all tasks done" if met else "tasks pending"}


def _default_assign(task: Task) -> str:
    """Default routing: the fixed role for the task type. A custom group injects
    an assigner that picks one of ITS actual members instead (see cowork_bridge)."""
    return ROLE_FOR_TASK.get(task.type, "engineer")


AgentAssigner = Callable[[Task], str]  # (task) -> concrete agent/member id


class ProjectEngine:
    def __init__(
        self,
        store: ProjectStore,
        *,
        generate_milestones: MilestoneGenerator,
        decompose_tasks: TaskDecomposer,
        execute_task: Executor = _default_execute,
        qa_task: QAEvaluator = _default_qa,
        gate_milestone: MilestoneGate = _default_gate,
        assign_agent: AgentAssigner = _default_assign,
    ) -> None:
        self.store = store
        self._generate = generate_milestones
        self._decompose = decompose_tasks
        self._execute = execute_task
        self._qa = qa_task
        self._gate = gate_milestone
        self._assign = assign_agent

    # ── planning ─────────────────────────────────────────────────────────────
    def plan(self, name: str, goal: str) -> Project:
        """Turn a one-line goal into a project with generated milestones."""
        pid = f"P-{uuid4().hex[:8]}"
        milestones = self._generate(goal)
        for ms in milestones:
            self.store.save_milestone(pid, ms)
        project = Project(
            id=pid,
            name=name,
            goal=goal,
            milestone_ids=[m.id for m in milestones],
            status="running",
        )
        self.store.save_project(project)
        return project

    # ── the loop ─────────────────────────────────────────────────────────────
    def tick(self, project_id: str) -> dict[str, Any]:
        """One iteration of the loop. Returns the events it produced."""
        project = self.store.get_project(project_id)
        if project is None:
            return {"events": ["project_not_found"], "project_status": "failed"}
        events: list[str] = []

        active = self._ensure_active_milestone(project, events)
        if active is None:
            return {"events": events, "project_status": project.status, "current_ms": None}

        self._ensure_tasks(project_id, active, events)
        self._run_frontier(project, active, events)
        self._gate_milestone(project, active, events)
        return {
            "events": events,
            "project_status": self.store.get_project(project_id).status,
            "current_ms": active.id,
        }

    def run(self, project_id: str, *, max_ticks: int = 50) -> dict[str, Any]:
        """Drive ticks until the project is done/failed/blocked or max_ticks."""
        history: list[dict[str, Any]] = []
        for _ in range(max_ticks):
            r = self.tick(project_id)
            history.append(r)
            if r["project_status"] in ("done", "failed", "blocked"):
                break
            if any(e == "no_runnable_milestone" for e in r["events"]):
                break  # blocked — nothing to advance
        final = self.store.get_project(project_id)
        return {
            "ticks": len(history),
            "final_status": final.status if final else "failed",
            "history": history,
        }

    # ── steps ────────────────────────────────────────────────────────────────
    def _ensure_active_milestone(self, project: Project, events: list[str]) -> Milestone | None:
        mss = self.store.milestones_for(project.id)
        done = {m.id for m in mss if m.status == "done"}
        active = next((m for m in mss if m.status in ("active", "in_progress")), None)
        if active is not None:
            return active
        blocked = next((m for m in mss if m.status == "blocked"), None)
        if blocked is not None:
            self._block_project(project, blocked.id, events, reason="milestone_blocked")
            return None
        if mss and len(done) == len(mss):
            project.status = "done"
            self.store.save_project(project)
            events.append("project_done")
            return None
        nxt = next(
            (m for m in mss
             if m.status == "pending" and all(d in done for d in m.dependencies)),
            None,
        )
        if nxt is None:
            events.append("no_runnable_milestone")  # all blocked on unmet deps
            self._block_project(project, project.current_ms, events, reason="no_runnable_milestone")
            return None
        nxt.status = "active"
        self.store.save_milestone(project.id, nxt)
        project.current_ms = nxt.id
        self.store.save_project(project)
        events.append(f"milestone_activated:{nxt.id}")
        return nxt

    def _ensure_tasks(self, project_id: str, ms: Milestone, events: list[str]) -> None:
        if self.store.tasks_for_milestone(ms.id):
            return
        new_tasks = self._decompose(ms)
        for t in new_tasks:
            t.milestone_id = ms.id
            t.assigned_role = t.assigned_role or ROLE_FOR_TASK.get(t.type, "engineer")
            self.store.save_task(t)
        ms.task_ids = [t.id for t in new_tasks]
        ms.status = "in_progress"
        self.store.save_milestone(project_id, ms)
        events.append(f"tasks_created:{ms.id}:{len(new_tasks)}")

    def _run_frontier(self, project: Project, ms: Milestone, events: list[str]) -> None:
        tasks = self.store.tasks_for_milestone(ms.id)
        for task in ready_tasks(tasks):
            task.assigned_role = ROLE_FOR_TASK.get(task.type, task.assigned_role or "engineer")
            task.assigned_agent = self._assign(task)  # concrete member (custom group) or role
            task.status = "running"
            task.attempts += 1
            self.store.save_task(task)
            context = self._context(project, ms, tasks)
            try:
                task.output = self._execute(task, context)
            except Exception as exc:  # noqa: BLE001 — one task failing must not kill the loop
                task.output = f"error: {type(exc).__name__}: {exc}"
                if task.attempts >= MAX_TASK_ATTEMPTS:
                    task.status = "failed"
                    events.append(f"task_failed:{task.id}")
                else:
                    task.status = "pending"
                    events.append(f"task_error_retry:{task.id}")
                self.store.save_task(task)
                continue
            verdict = self._qa(task, ms)
            task.qa_verdict = verdict
            if verdict.get("approved"):
                task.status = "done"
                events.append(f"task_done:{task.id}")
            elif task.attempts >= MAX_TASK_ATTEMPTS:
                task.status = "failed"
                events.append(f"task_failed_qa:{task.id}")
            else:
                task.status = "pending"  # QA rejected → retry next tick
                events.append(f"task_rejected:{task.id}")
            self.store.save_task(task)

    def _gate_milestone(self, project: Project, ms: Milestone, events: list[str]) -> None:
        tasks = self.store.tasks_for_milestone(ms.id)
        if not tasks or not all(t.status == "done" for t in tasks):
            if any(t.status == "failed" for t in tasks):
                ms.status = "blocked"
                self.store.save_milestone(project.id, ms)
                events.append(f"milestone_blocked:{ms.id}")
                self._block_project(project, ms.id, events, reason="task_failed")
            return
        gate = self._gate(ms, tasks)
        if gate.get("met"):
            ms.status = "done"
            self.store.save_milestone(project.id, ms)
            project.current_ms = None
            self.store.save_project(project)
            events.append(f"milestone_done:{ms.id}")
        else:
            ms.status = "blocked"
            self.store.save_milestone(project.id, ms)
            events.append(f"milestone_gate_failed:{ms.id}")
            self._block_project(project, ms.id, events, reason="gate_failed")

    def _block_project(
        self,
        project: Project,
        milestone_id: str | None,
        events: list[str],
        *,
        reason: str,
    ) -> None:
        project.status = "blocked"
        if milestone_id:
            project.current_ms = milestone_id
        self.store.save_project(project)
        events.append(f"project_blocked:{reason}")

    def _context(self, project: Project, ms: Milestone, tasks: list[Task]) -> dict[str, Any]:
        return {
            "project_goal": project.goal,
            "milestone_goal": ms.goal,
            "milestone_spec": ms.spec,
            "success_criteria": ms.success_criteria,
            "done_outputs": {t.id: t.output for t in tasks if t.status == "done"},
        }
