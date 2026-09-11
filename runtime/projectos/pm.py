"""PM read-model — the "real project management" view on Project OS.

Stored state stays authoritative (milestone/task statuses, dates, estimates).
This module derives the *management* layer on top of it — the stuff a project
manager reads in a dashboard:

- **milestone health** — on_track / at_risk / overdue / blocked / completed,
  computed from due dates, remaining estimates and task status;
- **progress & burndown** — done/total per milestone plus remaining estimate;
- **risks & blockers** — overdue work, blocked milestones, unmet criteria;
- **next actions** — ready, runnable tasks ordered by priority;
- **assignments** — who owns what;
- **retro (复盘)** — what the finished project actually shipped, what it cost
  in attempts/retries, and what risks actually materialized.

Pure functions over the store so everything is unit-testable.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from runtime.projectos.model import Milestone, Project, Task
from runtime.projectos.store import ProjectStore

_HEALTH_ORDER = {"overdue": 0, "blocked": 1, "at_risk": 2, "on_track": 3, "completed": 4}
_PRIORITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
_RUNNABLE = {"pending", "ready", "running"}


def _as_date(value: str) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_dt(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _s(value: Any, default: str = "") -> str:
    """Coerce an untrusted store field to a non-empty string, else ``default``."""
    if value is None:
        return default
    text = str(value)
    return text if text else default


def _today(now: datetime | None) -> date:
    return now.date() if now is not None else date.today()


def _passed(value: str, now: datetime | None) -> bool:
    d = _as_date(value)
    return d is not None and d < _today(now)


def _task_failure_detail(task: Task) -> str:
    """Best-effort failure text for a failed/blocked task.

    The engine stores failure prose in ``task.output`` (an ``error: ...`` /
    ``assignment error: ...`` string) or in ``task.qa_verdict`` when a QA gate
    rejects a node; neither is a first-class ``error`` field, so read them in
    order and only fall back to the bare status when nothing else is recorded.
    """
    verdict = task.qa_verdict or {}
    reason = verdict.get("reason")
    if verdict.get("review_error"):
        return "质量检查暂未完成，原产物已保留；恢复项目后只重试检查。" + (
            str(reason)[:300] if reason else ""
        )
    if isinstance(reason, str) and reason.strip():
        return reason[:400]
    out = task.output
    if isinstance(out, str) and out.strip():
        return out[:400]
    return task.status


def derive_milestone_pm(
    ms: Milestone,
    tasks: list[Task],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The PM view for one milestone: progress, estimate, health, overdue work."""
    done = sum(1 for t in tasks if t.status == "done")
    failed = sum(1 for t in tasks if t.status in ("failed", "blocked", "rejected"))
    total = len(tasks)
    total_estimate = round(sum(t.estimate for t in tasks), 2)
    remaining_estimate = round(sum(t.estimate for t in tasks if t.status != "done"), 2)
    progress = (done / total) if total else (1.0 if ms.status == "done" else 0.0)
    overdue_tasks = [
        {"id": t.id, "goal": t.goal, "due_at": t.due_at, "priority": t.priority}
        for t in tasks
        if t.due_at and t.status != "done" and _passed(t.due_at, now)
    ]
    health = _derive_health(ms, progress, remaining_estimate, bool(overdue_tasks), now)
    return {
        "id": ms.id,
        "name": ms.name,
        "status": ms.status,
        "health": health,
        "priority": ms.priority,
        "planned_start": ms.planned_start,
        "due_at": ms.due_at,
        "done": done,
        "total": total,
        "failed": failed,
        "progress": round(progress, 3),
        "total_estimate": total_estimate,
        "remaining_estimate": remaining_estimate,
        "overdue_tasks": overdue_tasks,
        "success_criteria": list(ms.success_criteria),
    }


def _derive_health(
    ms: Milestone,
    progress: float,
    remaining_estimate: float,
    has_overdue: bool,
    now: datetime | None,
) -> str:
    if ms.status == "done":
        return "completed"
    if ms.status == "blocked":
        return "blocked"
    if has_overdue:
        return "overdue"
    due = _as_date(ms.due_at)
    if due is None:
        return "on_track"
    days_left = (due - _today(now)).days
    if days_left < 0:
        return "overdue"
    # at_risk: the remaining estimate exceeds the time left, or the phase hasn't
    # started while it's already due soon.
    if remaining_estimate > 0 and days_left < remaining_estimate:
        return "at_risk"
    start = _as_date(ms.planned_start)
    if progress == 0 and start is not None and start < _today(now) and days_left <= 3:
        return "at_risk"
    return "on_track"


def _milestone_ready_task(task: Task) -> bool:
    return task.status in _RUNNABLE and not task.depends_on


def build_pm_report(
    store: ProjectStore,
    project_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """The PM console: project-level progress, burndown, risks, next actions."""
    project = store.get_project(project_id)
    if project is None:
        return None
    milestones = store.milestones_for(project_id)
    milestones_pm = [
        derive_milestone_pm(ms, store.tasks_for_milestone(ms.id), now=now) for ms in milestones
    ]
    from runtime.projectos.governance import budget_pause_message, budget_status

    for ms, view in zip(milestones, milestones_pm, strict=True):
        if ms.status in {"active", "in_progress"} and ms.spec.get("ai_budget_usd") is not None:
            tasks = store.tasks_for_milestone(ms.id)
            view["budget"] = budget_status(store, project_id, ms)
            if view["budget"]["paused"] and (not tasks or any(t.status != "done" for t in tasks)):
                view["health"] = "blocked"
                view["block_reason"] = budget_pause_message(view["budget"])
    total_estimate = round(sum(m["total_estimate"] for m in milestones_pm), 2)
    remaining_estimate = round(sum(m["remaining_estimate"] for m in milestones_pm), 2)
    done_tasks = sum(m["done"] for m in milestones_pm)
    total_tasks = sum(m["total"] for m in milestones_pm)
    # Count every planned phase, including phases not decomposed into tasks
    # yet. Otherwise finishing the first phase can incorrectly display 100%.
    overall_progress = round(sum(m["progress"] for m in milestones_pm) / len(milestones_pm), 3) if milestones_pm else 0.0

    all_tasks: list[Task] = []
    for ms in milestones:
        all_tasks.extend(store.tasks_for_milestone(ms.id))

    # risks: overdue milestones, blocked milestones, failed tasks
    risks: list[dict[str, Any]] = []
    for m in milestones_pm:
        if m["health"] in ("overdue", "blocked"):
            risks.append(
                {
                    "type": "milestone",
                    "milestone": m["name"],
                    "health": m["health"],
                    "detail": (
                        "milestone past due"
                        if m["health"] == "overdue"
                        else m.get("block_reason", "blocked — has failed tasks")
                    ),
                }
            )
    for t in all_tasks:
        if t.status in ("failed", "blocked"):
            risks.append(
                {
                    "type": "task",
                    "task_id": t.id,
                    "task": t.goal,
                    "health": "failed" if t.status == "failed" else "blocked",
                    "detail": _task_failure_detail(t),
                }
            )
        elif t.due_at and t.status != "done" and _passed(t.due_at, now):
            risks.append(
                {
                    "type": "task",
                    "task_id": t.id,
                    "task": t.goal,
                    "health": "overdue",
                    "detail": f"已逾期（截止 {t.due_at}）",
                }
            )

    blockers = [m["name"] for m in milestones_pm if m["health"] == "blocked"]
    overdue = [
        {"milestone": m["name"], "tasks": m["overdue_tasks"]}
        for m in milestones_pm
        if m["overdue_tasks"]
    ]

    # next actions: runnable tasks ordered by priority, then milestone order
    next_actions: list[dict[str, Any]] = []
    for ms, m in zip(milestones, milestones_pm, strict=True):
        if "phase_agents" in ms.spec and ms.status in {"active", "in_progress"}:
            from runtime.projectos.governance import phase_authorized

            if not phase_authorized(store, project_id, ms):
                next_actions.append({"milestone": ms.name, "task_id": "", "task": "审批本阶段成员与执行范围：/project run",
                                     "priority": "P0", "estimate": 0, "due_at": ms.due_at, "type": "phase_approval"})
                continue
            if m.get("block_reason") and m.get("budget", {}).get("paused"):
                next_actions.append({"milestone": ms.name, "task_id": "", "task": m["block_reason"],
                                     "priority": "P0", "estimate": 0, "due_at": ms.due_at, "type": "budget_review",
                                     "budget": m["budget"]})
                continue
        phase_tasks = store.tasks_for_milestone(ms.id)
        if ms.spec.get("requires_owner_acceptance") and ms.status != "done" and phase_tasks and all(t.status == "done" for t in phase_tasks):
            from runtime.projectos.acceptance import delivery_accepted

            if not delivery_accepted(store, project_id, ms, phase_tasks):
                next_actions.append({"milestone": m["name"], "milestone_id": ms.id,
                                     "task_id": "", "task": f"等待用户验收：/project accept {ms.id}",
                                     "priority": "P0", "estimate": 0, "due_at": ms.due_at,
                                     "type": "owner_acceptance"})
        for t in store.tasks_for_milestone(ms.id):
            if _milestone_ready_task(t):
                next_actions.append(
                    {
                        "milestone": m["name"],
                        "task_id": t.id,
                        "task": t.goal,
                        "priority": t.priority,
                        "estimate": t.estimate,
                        "due_at": t.due_at,
                    }
                )
    next_actions.sort(key=lambda a: (_PRIORITY_ORDER.get(a["priority"], 3), a["estimate"]))

    # assignments: agent -> runnable/active work
    assignments: dict[str, list[str]] = {}
    for t in all_tasks:
        who = t.assigned_agent or t.assigned_role
        if who:
            assignments.setdefault(who, []).append(t.id)

    burndown = [
        {
            "milestone": m["name"],
            "health": m["health"],
            "done": m["done"],
            "total": m["total"],
            "remaining_estimate": m["remaining_estimate"],
        }
        for m in milestones_pm
    ]

    return {
        "project_id": project_id,
        "name": project.name,
        "status": project.status,
        "overall_progress": overall_progress,
        "progress_basis": "equal_phase_delivery",
        "awaiting_acceptance_count": sum(a.get("type") == "owner_acceptance" for a in next_actions),
        "done_tasks": done_tasks,
        "total_tasks": total_tasks,
        "total_estimate": total_estimate,
        "remaining_estimate": remaining_estimate,
        "milestones": milestones_pm,
        "burndown": burndown,
        "risks": risks,
        "blockers": blockers,
        "overdue": overdue,
        "next_actions": next_actions,
        "assignments": assignments,
    }


# Portfolio roll-up caps. The sidebar and the ops drawer read this payload on
# every project switch, so the unbounded parts (per-task prose, full risk lists)
# are truncated. The complete totals survive in ``counts`` so the UI can still
# render "+N more" affordances instead of silently lying about the size.
_PORTFOLIO_MAX_MILESTONES = 50
_PORTFOLIO_MAX_OVERDUE = 20
_PORTFOLIO_MAX_NEXT_ACTIONS = 10
_PORTFOLIO_MAX_RISKS = 10


def _portfolio_health(milestones_pm: list[dict[str, Any]]) -> str:
    """Worst milestone health wins.

    A portfolio row must never look calmer than the project's own PM console:
    a single blocked milestone already makes the whole project blocked.
    """
    if not milestones_pm:
        return "on_track"
    return min(
        (str(m.get("health") or "on_track") for m in milestones_pm),
        key=lambda health: _HEALTH_ORDER.get(health, len(_HEALTH_ORDER)),
    )


def build_portfolio_entry(
    project: Project,
    report: dict[str, Any] | None,
    *,
    max_milestones: int = _PORTFOLIO_MAX_MILESTONES,
    max_overdue: int = _PORTFOLIO_MAX_OVERDUE,
    max_next_actions: int = _PORTFOLIO_MAX_NEXT_ACTIONS,
    max_risks: int = _PORTFOLIO_MAX_RISKS,
) -> dict[str, Any]:
    """Compact one-project row for the cross-project (portfolio) view.

    ``report`` is a :func:`build_pm_report` payload, or ``None`` when the
    project could not be read (dangling record, scope failure). Unreadable
    projects are still returned, flagged with ``readable=False``: dropping them
    would hide a broken project from the very surface that exists to surface it.
    """
    milestones_pm = list(report.get("milestones") or []) if report else []

    overdue_flat: list[dict[str, Any]] = []
    for group in (report.get("overdue") or []) if report else []:
        milestone = str(group.get("milestone") or "")
        for task in group.get("tasks") or []:
            overdue_flat.append(
                {
                    "milestone": milestone,
                    "id": _s(task.get("id")),
                    "goal": _s(task.get("goal")),
                    "due_at": _s(task.get("due_at")),
                    "priority": _s(task.get("priority"), "P2"),
                }
            )

    risks = list(report.get("risks") or []) if report else []
    next_actions = list(report.get("next_actions") or []) if report else []

    return {
        "id": project.id,
        "name": project.name,
        "goal": project.goal,
        "status": project.status,
        "owner": project.owner,
        "created_at": project.created_at,
        "started_at": project.started_at,
        "finished_at": project.finished_at,
        "execution_thread_id": project.execution_thread_id,
        "health": _portfolio_health(milestones_pm),
        "readable": report is not None,
        "progress": report.get("overall_progress", 0.0) if report else 0.0,
        "done_tasks": report.get("done_tasks", 0) if report else 0,
        "total_tasks": report.get("total_tasks", 0) if report else 0,
        "total_estimate": report.get("total_estimate", 0.0) if report else 0.0,
        "remaining_estimate": report.get("remaining_estimate", 0.0) if report else 0.0,
        "counts": {
            "milestones": len(milestones_pm),
            "risks": len(risks),
            "blockers": len(report.get("blockers") or []) if report else 0,
            "overdue": len(overdue_flat),
            "next_actions": len(next_actions),
        },
        "milestones": [
            {
                "id": _s(m.get("id")),
                "name": _s(m.get("name")),
                "status": _s(m.get("status")),
                "health": _s(m.get("health"), "on_track"),
                "priority": _s(m.get("priority"), "P2"),
                "planned_start": _s(m.get("planned_start")),
                "due_at": _s(m.get("due_at")),
                "done": m.get("done", 0),
                "total": m.get("total", 0),
                "failed": m.get("failed", 0),
                "progress": m.get("progress", 0.0),
                "remaining_estimate": m.get("remaining_estimate", 0.0),
                "overdue_count": len(m.get("overdue_tasks") or []),
            }
            for m in milestones_pm[:max_milestones]
        ],
        "overdue": overdue_flat[:max_overdue],
        "next_actions": next_actions[:max_next_actions],
        "risks": risks[:max_risks],
    }


def build_retro(
    store: ProjectStore,
    project_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """复盘: what a finished project actually shipped and what it cost."""
    project = store.get_project(project_id)
    if project is None:
        return None
    milestones = store.milestones_for(project_id)
    tasks: list[Task] = []
    for ms in milestones:
        tasks.extend(store.tasks_for_milestone(ms.id))

    done = sum(1 for t in tasks if t.status == "done")
    failed = sum(1 for t in tasks if t.status == "failed")
    rejected = sum(1 for t in tasks if t.status == "rejected")
    attempts = sum(t.attempts for t in tasks)
    total_estimate = round(sum(t.estimate for t in tasks), 2)
    duration_days: int | None = None
    start = _as_dt(project.started_at)
    finish = _as_dt(project.finished_at)
    if start and finish:
        duration_days = max(0, (finish - start).days)

    blocked_milestones = [m.name for m in milestones if m.status == "blocked"]
    risks_hit = list(blocked_milestones)
    recommendations: list[str] = []
    if failed or rejected:
        recommendations.append("曾有任务经过 QA 驳回/失败——建议在拆解阶段给出更明确的验收标准")
    if blocked_milestones:
        recommendations.append("存在被阻塞的里程碑——检查依赖与指派是否合理")
    if attempts > len(tasks):
        recommendations.append("多次重试才完成——考虑调低单任务粒度或补充前置研究")
    if not recommendations:
        recommendations.append("全流程一次通过——保持当前拆解粒度")

    return {
        "project_id": project_id,
        "name": project.name,
        "goal": project.goal,
        "status": project.status,
        "milestone_count": len(milestones),
        "task_count": len(tasks),
        "done_tasks": done,
        "failed_tasks": failed,
        "rejected_tasks": rejected,
        "attempts_total": attempts,
        "total_estimate": total_estimate,
        "duration_days": duration_days,
        "blocked_milestones": blocked_milestones,
        "risks_hit": risks_hit,
        "recommendations": recommendations,
    }


def _fmt_health(health: str) -> str:
    labels = {
        "on_track": "正常",
        "at_risk": "有风险",
        "overdue": "已逾期",
        "blocked": "阻塞",
        "completed": "完成",
    }
    return labels.get(health, health)


def format_pm_report(report: dict[str, Any]) -> str:
    """Human-readable PM console for the chat surface."""
    lines = [
        f"# PM 驾驶舱 · {report.get('name')}（{report.get('status')}）",
        "",
        f"整体进度 {report.get('done_tasks')}/{report.get('total_tasks')}"
        f" · 剩余估时 {report.get('remaining_estimate')}d"
        f"（共 {report.get('total_estimate')}d）",
        "",
        "里程碑：",
    ]
    for m in report.get("milestones", []):
        lines.append(
            f"- {m['name']}：{m['done']}/{m['total']} · {int(m['progress'] * 100)}%"
            f" · {_fmt_health(m['health'])}"
            + (f" · 逾期 {len(m['overdue_tasks'])}" if m["overdue_tasks"] else "")
            + (f" · 截止 {m['due_at']}" if m["due_at"] else "")
        )
    risks = report.get("risks") or []
    if risks:
        lines.append("")
        lines.append(f"风险/阻塞（{len(risks)}）：")
        for r in risks[:6]:
            lines.append(
                f"- [{r.get('health')}] {r.get('milestone') or r.get('task')}：{r.get('detail')}"
            )
    actions = report.get("next_actions") or []
    if actions:
        lines.append("")
        lines.append("下一步（按优先级）：")
        for a in actions[:6]:
            lines.append(f"- {a['priority']} {a['task']} · {a['milestone']}")
    return "\n".join(lines)
