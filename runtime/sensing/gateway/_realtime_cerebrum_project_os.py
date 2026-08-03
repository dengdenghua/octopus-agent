"""Project OS bridge for the realtime runtime.

Split out of ``realtime_cerebrum.py``: the Project OS control-command
parser, the milestone/todo mapping helpers and the ``_drive_project_os``
driver that runs Project OS directly from a cowork thread in project
mode.

Every function takes the owning ``CerebrumRuntime`` as its first
argument; cross-method calls go through the runtime so subclass
overrides keep working.
"""

from __future__ import annotations

import asyncio
import json
import shlex
from typing import TYPE_CHECKING, Any

from runtime.platform.models import ParsedIntent
from runtime.protocol import ReasoningItem, TodoEntry, TodoListItem

if TYPE_CHECKING:
    from runtime.memory.threads.event_log import EventLog
    from runtime.protocol import Turn
    from runtime.sensing.gateway.realtime_cerebrum import CerebrumRuntime
    from runtime.sensing.gateway.realtime_gateway import EventEmitter


def _format_project_os_result(state: dict[str, Any]) -> str:
    """Human-readable Project OS result for the realtime chat surface."""
    raw_project = state.get("project")
    project: dict[str, Any] = raw_project if isinstance(raw_project, dict) else {}
    raw_result = state.get("result")
    result: dict[str, Any] = raw_result if isinstance(raw_result, dict) else {}
    raw_milestones = state.get("milestones")
    milestones: list[Any] = raw_milestones if isinstance(raw_milestones, list) else []
    raw_tasks = state.get("tasks")
    tasks_by_ms: dict[str, Any] = raw_tasks if isinstance(raw_tasks, dict) else {}
    roster = [str(member) for member in (state.get("roster") or []) if str(member).strip()]

    project_name = str(project.get("name") or "当前项目")
    project_id = str(project.get("id") or "")
    status = str(result.get("final_status") or project.get("status") or "running")
    ticks = result.get("ticks")

    reused = bool(state.get("reused"))
    control = state.get("control") if isinstance(state.get("control"), dict) else None
    if control:
        headline = "Project OS 已执行控制命令。"
    else:
        headline = "Project OS 已继续推进项目。" if reused else "Project OS 已接管并运行项目。"
    lines = [
        headline,
        "",
    ]
    if project_id:
        lines.append(f"项目：{project_name}（{project_id}）")
    else:
        lines.append(f"项目：{project_name}")
    lines.append(f"状态：{status}" + (f" · ticks {ticks}" if ticks is not None else ""))
    if roster:
        lines.append(f"成员：{', '.join(roster)}")
    lines.append("")
    lines.append("里程碑进展：")

    for milestone in milestones[:6]:
        if not isinstance(milestone, dict):
            continue
        ms_id = str(milestone.get("id") or "")
        ms_name = str(milestone.get("name") or ms_id or "milestone")
        ms_status = str(milestone.get("status") or "pending")
        tasks = tasks_by_ms.get(ms_id) if isinstance(tasks_by_ms, dict) else []
        tasks = tasks if isinstance(tasks, list) else []
        done = sum(1 for task in tasks if isinstance(task, dict) and task.get("status") == "done")
        lines.append(f"- {ms_name}：{ms_status} · {done}/{len(tasks)} 任务完成")
        assignments: list[str] = []
        for task in tasks[:4]:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id") or "")
            assignee = str(task.get("assigned_agent") or task.get("assigned_role") or "")
            task_status = str(task.get("status") or "")
            if task_id and assignee:
                assignments.append(f"{task_id}->{assignee}({task_status})")
        if assignments:
            lines.append(f"  派发：{', '.join(assignments)}")
    if len(milestones) > 6:
        lines.append(f"- 其余 {len(milestones) - 6} 个里程碑已省略，可在 Project OS 视图继续查看。")
    if status == "blocked":
        lines.append("")
        lines.append("项目已阻塞；请处理失败任务、验收条件或依赖后再继续推进。")
    elif status not in {"done", "failed"}:
        lines.append("")
        lines.append("项目还未结束；后续回合会继续从当前 Project OS 状态推进。")
    return "\n".join(lines)


def _project_os_todo_item(state: dict[str, Any]) -> TodoListItem | None:
    """Map Project OS milestones to the existing realtime todo-list item."""
    raw_project = state.get("project")
    project: dict[str, Any] = raw_project if isinstance(raw_project, dict) else {}
    raw_milestones = state.get("milestones")
    milestones: list[Any] = raw_milestones if isinstance(raw_milestones, list) else []
    raw_tasks = state.get("tasks")
    tasks_by_ms: dict[str, Any] = raw_tasks if isinstance(raw_tasks, dict) else {}
    if not milestones:
        return None

    def _status(raw: Any) -> str:
        value = str(raw or "").strip()
        if value == "done":
            return "completed"
        if value in {"active", "in_progress", "running"}:
            return "in_progress"
        if value in {"blocked", "failed"}:
            return "blocked"
        return "pending"

    entries: list[TodoEntry] = []
    for milestone in milestones:
        if not isinstance(milestone, dict):
            continue
        ms_id = str(milestone.get("id") or "").strip()
        name = str(milestone.get("name") or ms_id or "milestone").strip()
        status = _status(milestone.get("status"))
        tasks = tasks_by_ms.get(ms_id) if isinstance(tasks_by_ms, dict) else []
        tasks = tasks if isinstance(tasks, list) else []
        done = sum(1 for task in tasks if isinstance(task, dict) and task.get("status") == "done")
        suffix = f" · {done}/{len(tasks)} tasks" if tasks else ""
        entries.append(TodoEntry(title=f"{name}{suffix}", status=status))
    if not entries:
        return None

    project_name = str(project.get("name") or "Project OS").strip()
    project_id = str(project.get("id") or "").strip()
    explanation = f"Project OS · {project_name}" + (f" ({project_id})" if project_id else "")
    return TodoListItem(explanation=explanation, plan=entries)


def _parse_project_os_control(text: str) -> dict[str, Any] | None:
    """Parse explicit Project OS control commands in project-mode chat."""
    raw = str(text or "").strip()
    if not raw.startswith("/project"):
        return None
    try:
        parts = shlex.split(raw)
    except ValueError:
        return {"type": "help"}
    if len(parts) < 2:
        return {"type": "help"}
    command = parts[1].lower()
    rest = parts[2:]

    def _kv(tokens: list[str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for token in tokens:
            if "=" not in token:
                continue
            key, value = token.split("=", 1)
            key = key.strip().lower()
            if key:
                out[key] = value.strip()
        return out

    if command == "recover":
        opts = _kv(rest)
        task_ids = [
            item.strip()
            for item in opts.get("tasks", opts.get("task_ids", "")).split(",")
            if item.strip()
        ]
        return {
            "type": "recover",
            "task_ids": task_ids,
            "run": "run" in rest or opts.get("run", "").lower() in {"1", "true", "yes"},
        }
    if command == "task" and len(rest) >= 2:
        task_id = rest[0]
        action = rest[1].lower()
        tail = rest[2:]
        opts = _kv(tail)
        return {
            "type": "task",
            "task_id": task_id,
            "action": action,
            "assigned_agent": opts.get("agent") or opts.get("assigned_agent"),
            "assigned_role": opts.get("role") or opts.get("assigned_role"),
            "reason": opts.get("reason", ""),
            "output": opts.get("output"),
            "run": "run" in tail or opts.get("run", "").lower() in {"1", "true", "yes"},
            "cascade": opts.get("cascade", "true").lower() not in {"0", "false", "no"},
        }
    return {"type": "help"}


async def _drive_project_os(
    runtime: CerebrumRuntime,
    turn: Turn,
    log: EventLog,
    emitter: EventEmitter,
    intent: ParsedIntent,
    *,
    thread_id: str,
    text: str,
) -> None:
    """Run Project OS directly from a cowork thread in project mode."""
    if runtime._cowork_group_store is None:
        await runtime._emit_agent_message(
            turn,
            log,
            emitter,
            "Project OS 需要先绑定协作组；当前线程还没有可用的 cowork group。",
        )
        return
    if runtime._project_store is None:
        from runtime.projectos.store import ProjectStore

        runtime._project_store = ProjectStore()

    context = intent.user_context if isinstance(intent.user_context, dict) else {}
    goal = str(getattr(intent, "normalized_goal", "") or text or "").strip() or "当前目标"
    raw_name = str(context.get("team_name") or context.get("project") or "").strip()
    name = raw_name[:80] if raw_name else "当前项目"
    try:
        max_ticks = int(context.get("project_os_max_ticks") or 50)
    except (TypeError, ValueError):
        max_ticks = 50
    max_ticks = max(1, min(max_ticks, 200))

    control = _parse_project_os_control(text)
    from runtime.projectos.cowork_bridge import full_project_state, run_project_from_group

    def _run() -> dict[str, Any]:
        if control is not None:
            project = runtime._project_store.project_for_thread(thread_id)
            if project is None:
                return {
                    "ok": False,
                    "error": "project_not_found",
                    "message": "Project OS 当前线程还没有可恢复或干预的项目。",
                }
            engine = None
            if control.get("type") in {"recover", "task"}:
                from runtime.projectos.cowork_bridge import engine_for_group

                engine = engine_for_group(
                    runtime._project_store,
                    runtime._cowork_group_store,
                    thread_id,
                    hooks=dict(runtime._project_os_hooks),
                )
            if control.get("type") == "recover" and engine is not None:
                intervention = engine.recover(
                    project.id,
                    task_ids=control.get("task_ids") or [],
                )
                result = (
                    engine.run(project.id, max_ticks=max_ticks)
                    if control.get("run")
                    else {"final_status": intervention.get("project_status")}
                )
                state = full_project_state(runtime._project_store, project.id) or {}
                return {
                    "ok": True,
                    "roster": [],
                    "reused": True,
                    "control": control,
                    "intervention": intervention,
                    "result": result,
                    **state,
                }
            if control.get("type") == "task" and engine is not None:
                intervention = engine.intervene_task(
                    project.id,
                    str(control.get("task_id") or ""),
                    action=str(control.get("action") or ""),
                    assigned_agent=control.get("assigned_agent"),
                    assigned_role=control.get("assigned_role"),
                    output=control.get("output"),
                    reason=str(control.get("reason") or ""),
                    cascade=bool(control.get("cascade", True)),
                )
                intervention_events = [
                    str(event) for event in (intervention.get("events") or [])
                ]
                if any(
                    event.startswith(
                        (
                            "task_not_found:",
                            "milestone_not_found:",
                            "unknown_task_action:",
                        )
                    )
                    for event in intervention_events
                ):
                    state = full_project_state(runtime._project_store, project.id) or {}
                    return {
                        "ok": False,
                        "error": "project_task_intervention_failed",
                        "message": "Project OS 任务控制命令未执行："
                        + ", ".join(intervention_events),
                        "control": control,
                        "intervention": intervention,
                        **state,
                    }
                result = (
                    engine.run(project.id, max_ticks=max_ticks)
                    if control.get("run")
                    else {"final_status": intervention.get("project_status")}
                )
                state = full_project_state(runtime._project_store, project.id) or {}
                return {
                    "ok": True,
                    "roster": [],
                    "reused": True,
                    "control": control,
                    "intervention": intervention,
                    "result": result,
                    **state,
                }
            return {
                "ok": False,
                "error": "unknown_project_command",
                "message": (
                    "可用命令：/project recover [tasks=T1,T2] [run]；"
                    "/project task <task_id> <reassign|reset|complete|skip> "
                    "[agent=agent-id] [reason=...] [run]"
                ),
            }
        return run_project_from_group(
            runtime._project_store,
            runtime._cowork_group_store,
            thread_id,
            name=name,
            goal=goal,
            hooks=dict(runtime._project_os_hooks),
            run=True,
            max_ticks=max_ticks,
            reuse_active=True,
        )

    loop = asyncio.get_running_loop()
    try:
        state = await loop.run_in_executor(None, _run)
    except ValueError:
        await runtime._emit_agent_message(
            turn,
            log,
            emitter,
            "Project OS 已进入项目模式，但当前协作组没有可执行的 agent 成员。"
            "请先添加至少一个参与者后再运行项目。",
        )
        return
    if not state.get("ok", True):
        await runtime._emit_agent_message(
            turn,
            log,
            emitter,
            str(state.get("message") or "Project OS 控制命令无法执行。"),
        )
        return
    raw_project = state.get("project")
    project: dict[str, Any] = raw_project if isinstance(raw_project, dict) else {}
    project_id = project.get("id")
    if project_id and isinstance(state.get("trace"), dict):
        state["trace"]["audit_events"] = runtime._project_store.events_for_project(
            str(project_id),
            limit=20,
        )
    if project_id and state.get("control"):
        state["trace"] = {
            "schema": "octopus.projectos.control_trace.v1",
            "thread_id": thread_id,
            "project_id": project.get("id"),
            "project_name": project.get("name"),
            "project_status": (
                state.get("result", {}).get("final_status")
                if isinstance(state.get("result"), dict)
                else project.get("status")
            ),
            "available_actions": state.get("available_actions") or [],
            "action_specs": state.get("action_specs") or [],
            "control": state.get("control"),
            "intervention": state.get("intervention"),
            "audit_events": runtime._project_store.events_for_project(
                str(project_id),
                limit=20,
            ),
        }
    todo_item = _project_os_todo_item(state)
    if todo_item is not None:
        await runtime._emit_todo_list(turn, log, emitter, todo_item)
    trace = state.get("trace")
    if isinstance(trace, dict):
        await runtime._emit_reasoning(
            turn,
            log,
            emitter,
            ReasoningItem(
                summary=["Project OS run trace"],
                content=json.dumps(trace, ensure_ascii=False, sort_keys=True),
            ),
        )
    await runtime._emit_agent_message(
        turn,
        log,
        emitter,
        _format_project_os_result(state),
    )
