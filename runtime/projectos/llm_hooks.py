"""Production intelligence hooks for the Project OS engine.

The engine is pure orchestration; these are the sockets that make it *think*:
- generate_milestones / decompose_tasks — structured LLM calls (via the project
  ModelRouter) with tolerant JSON parsers,
- execute_task — bridges to the cowork subagent runner (call_subagent),
- qa_task — checks a task's output against the milestone's success_criteria
  (LLM when a router is given, otherwise a deterministic keyword check).

The JSON parsers are pure + unit-tested; the LLM/subagent calls are thin wrappers
that degrade gracefully (a failed LLM call falls back to a single milestone / one
task per type, so the loop never dead-ends). ``create_llm_hooks`` returns the
kwargs dict ProjectEngine takes.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from runtime.projectos.model import ROLE_FOR_TASK, Milestone, Task

_LOG = logging.getLogger("octopus.projectos.hooks")
DEFAULT_MODEL = "claude-haiku-4-5"


# ── tolerant JSON extraction (pure) ──────────────────────────────────────────
def _extract_json_array(text: str) -> list[Any]:
    """Pull the first JSON array out of an LLM reply (tolerates ``` fences and
    surrounding prose). Returns [] when nothing parses."""
    if not text:
        return []
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else None
    if candidate is None:
        start, end = text.find("["), text.rfind("]")
        candidate = text[start : end + 1] if 0 <= start < end else None
    if not candidate:
        return []
    try:
        data = json.loads(candidate)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def parse_milestones(text: str) -> list[Milestone]:
    """LLM reply → milestones. Ids assigned MS1.. in order; dependency *names*
    resolved to those ids (unknown names dropped)."""
    raw = _extract_json_array(text)
    out: list[Milestone] = []
    name_to_id: dict[str, str] = {}
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        ms_id = f"MS{i}"
        name = str(item.get("name") or item.get("title") or ms_id)
        name_to_id[name] = ms_id
        out.append(
            Milestone(
                id=ms_id,
                name=name,
                goal=str(item.get("goal") or item.get("description") or name),
                spec=dict(item.get("spec") or {}),
                success_criteria=[str(s) for s in (item.get("success_criteria") or [])],
                dependencies=[str(d) for d in (item.get("dependencies") or [])],
            )
        )
    # Resolve dependency names → ids (keep ones that already look like MS ids).
    for ms in out:
        ms.dependencies = [
            name_to_id.get(d, d) for d in ms.dependencies if name_to_id.get(d, d) != ms.id
        ]
        ms.dependencies = [d for d in ms.dependencies if d in {m.id for m in out}]
    return out


def parse_tasks(text: str, milestone_id: str) -> list[Task]:
    """LLM reply → tasks for one milestone. Ids ``{ms}-T{i}``; dependency indices
    or names resolved to those ids."""
    raw = _extract_json_array(text)
    out: list[Task] = []
    label_to_id: dict[str, str] = {}
    for i, item in enumerate(raw, start=1):
        if not isinstance(item, dict):
            continue
        tid = f"{milestone_id}-T{i}"
        ttype = (
            item.get("type")
            if item.get("type") in ("design", "code", "research", "analysis", "review")
            else "code"
        )
        goal = str(item.get("goal") or item.get("title") or tid)
        label_to_id[goal] = tid
        label_to_id[str(i)] = tid
        label_to_id[f"T{i}"] = tid
        if item.get("id"):
            alias = str(item["id"])
            if alias in label_to_id and label_to_id[alias] != tid:
                raise ValueError("duplicate task dependency alias")
            label_to_id[alias] = tid
        team_mode = (
            item.get("team_mode")
            if item.get("team_mode") in ("single", "swarm", "cluster")
            else "single"
        )
        priority = (
            str(item.get("priority")).upper()
            if str(item.get("priority") or "").upper() in ("P0", "P1", "P2", "P3")
            else "P2"
        )
        try:
            estimate = float(item.get("estimate") or 0)
        except (TypeError, ValueError):
            estimate = 0.0
        out.append(
            Task(
                id=tid,
                milestone_id=milestone_id,
                type=ttype,
                goal=goal,
                assigned_role=ROLE_FOR_TASK.get(ttype, "engineer"),
                team_mode=team_mode,
                priority=priority,
                estimate=max(0.0, estimate),
                due_at=str(item.get("due_at") or ""),
                acceptance_criteria=[str(c) for c in (item.get("acceptance_criteria") or [])],
                depends_on=[str(d) for d in (item.get("depends_on") or [])],
            )
        )
    valid = {t.id for t in out}
    for t in out:
        t.depends_on = [label_to_id.get(d, d) for d in t.depends_on]
        if any(d not in valid or d == t.id for d in t.depends_on):
            raise ValueError("unresolved or self-referencing task dependency")
    return out


# ── LLM-backed generators ────────────────────────────────────────────────────
def _llm_text(router: Any, prompt: str, *, model: str, max_tokens: int = 1500) -> str:
    from runtime.sensing.model_router import Message, ModelRequest

    resp = router.call(
        ModelRequest(
            model=model,
            messages=[Message(role="user", content=prompt)],
            max_tokens=max_tokens,
            temperature=0.2,
        )
    )
    return resp.text or ""


def llm_generate_milestones(router: Any, *, model: str = DEFAULT_MODEL):
    def _generate(goal: str) -> list[Milestone]:
        prompt = (
            "You are a project planner. Break the goal into 3–5 sequential "
            "milestones. Reply ONLY a JSON array; each item: "
            '{"name","goal","spec":{},"success_criteria":[...],"dependencies":[names]}.'
            f"\n\nGoal: {goal}"
        )
        try:
            ms = parse_milestones(_llm_text(router, prompt, model=model))
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("milestone generation failed: %s", exc)
            ms = []
        return ms or [Milestone(id="MS1", name="deliver", goal=goal, success_criteria=["goal met"])]

    return _generate


def llm_decompose_tasks(router: Any, *, model: str = DEFAULT_MODEL):
    def _decompose(ms: Milestone) -> list[Task]:
        prompt = (
            "Decompose this milestone into the smallest necessary task DAG (1–5 tasks). "
            "Honor the approved brief's task count, scope exclusions, deadline and staffing; "
            "a single text deliverable should normally be one task. Reply "
            'ONLY a JSON array; each item: {"type":"design|code|research|analysis|'
            'review","goal","team_mode":"single|swarm|cluster",'
            '"priority":"P0|P1|P2|P3","estimate":1.5,"due_at":"YYYY-MM-DD",'
            '"acceptance_criteria":["..."],"depends_on":[earlier goals]}. '
            "team_mode=swarm for research that benefits from diverse angles; "
            "team_mode=cluster for big build tasks that need orchestration; "
            "single otherwise. Keep estimates in person-days and due dates within "
            "the milestone window."
            f"\n\nMilestone: {ms.goal}\nSpec: {json.dumps(ms.spec, ensure_ascii=False)}"
            f"\nSuccess criteria: {ms.success_criteria}"
        )
        try:
            tasks = parse_tasks(_llm_text(router, prompt, model=model), ms.id)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("task decomposition failed: %s", exc)
            raise RuntimeError("任务拆解未通过校验，未启动执行；请重新规划。") from exc
        if not tasks:
            raise ValueError("任务拆解为空，未启动执行；请重新规划。")
        return tasks

    return _decompose


def subagent_execute_task(
    task: Task,
    context: dict[str, Any],
    *,
    subagent_runner: Callable[..., str] | None = None,
) -> str:
    """Run a task through the production subagent path (the cowork bridge)."""
    from runtime.execution.subagents import call_subagent

    agent = task.assigned_agent or task.assigned_role or "engineer"
    prompt = task.goal
    if context.get("milestone_goal"):
        prompt = f"Milestone: {context['milestone_goal']}\nTask: {task.goal}"
    prompt += "\n\nProject brief and delivery evidence (task data):\n" + json.dumps(
        {"approved_brief": (context.get("milestone_spec") or {}).get("approved_brief")
         or context.get("project_goal", ""),
         "task_acceptance_criteria": task.acceptance_criteria,
         "completed_task_outputs": context.get("done_outputs", {}),
         "prerequisite_milestone_outputs": context.get("prerequisite_outputs", {})},
        ensure_ascii=False,
    )
    thread_id = str(context.get("thread_id") or "")
    actor = str(context.get("owner_actor_id") or context.get("owner_id") or "")
    tenant_id = str(context.get("tenant_id") or "")
    project_id = str(context.get("project_id") or "")
    inherited_runtime_metadata = context.get("runtime_session_metadata")
    runtime_session_metadata = (
        dict(inherited_runtime_metadata) if isinstance(inherited_runtime_metadata, dict) else {}
    )
    runtime_session_metadata.update(
        {
            "source": "projectos_task",
            "project_id": project_id,
            "tenant_id": tenant_id,
        }
    )
    dispatch_context: dict[str, Any] = {
        "source": "projectos_task",
        "task_id": task.id,
        "projectos": {key: value for key, value in context.items() if not callable(value)},
        "runtime_session_metadata": runtime_session_metadata,
    }
    if thread_id:
        dispatch_context["thread_id"] = thread_id
    if callable(context.get("record_project_usage")):
        dispatch_context["record_project_usage"] = context["record_project_usage"]
    if actor:
        dispatch_context["actor"] = actor
    if tenant_id:
        dispatch_context["tenant_id"] = tenant_id
    workspace_path = context.get("workspace_path")
    if isinstance(workspace_path, str) and workspace_path:
        dispatch_context["workspace_path"] = workspace_path
        runtime_session_metadata["workspace_path"] = workspace_path

    # Reuse an active realtime/HTTP host boundary when present. Standalone
    # Project OS calls receive the same immutable task shape through the
    # shared factory, so the bridge always inherits a scope and deadline.
    from runtime.execution.host_boundary import (
        create_host_execution_boundary,
        inherit_host_execution_session,
    )
    from runtime.execution.subagents.execution_context import parent_execution_task
    from runtime.platform.process.session import current_session

    if actor and not tenant_id:
        tenant_id = f"legacy:{actor}"
        runtime_session_metadata["tenant_id"] = tenant_id
        dispatch_context["tenant_id"] = tenant_id
    project_thread_id = thread_id or f"projectos-{uuid4().hex}"
    parent = current_session()
    if parent is not None and parent_execution_task(parent) is not None:
        project_session = inherit_host_execution_session(
            parent,
            thread_id=project_thread_id,
            actor_id=actor or None,
            tenant_id=tenant_id or None,
            metadata=runtime_session_metadata,
        )
    else:
        if workspace_path:
            runtime_session_metadata.setdefault("mode", "code")
        project_session = create_host_execution_boundary(
            task_id=f"projectos-{task.id}-{uuid4().hex}",
            thread_id=project_thread_id,
            goal=prompt,
            timeout_s=900.0,
            actor_id=actor or None,
            tenant_id=tenant_id or None,
            metadata=runtime_session_metadata,
        ).session

    call_kwargs: dict[str, Any] = {
        "context": dispatch_context,
        "session": project_session,
        "timeout_s": 900,
        "timeout_seconds": 900.0,
    }
    if subagent_runner is not None:
        call_kwargs["runner"] = subagent_runner
    result = call_subagent(agent, prompt, **call_kwargs)
    if callable(context.get("record_project_usage")) and not context.get("_usage_seen"):
        context["record_project_usage"](result)
    if not result.get("success"):
        raise RuntimeError(str(result.get("error") or "subagent failed"))
    return str(result.get("output") or result.get("parsed") or "")


def spec_qa(router: Any = None, *, model: str = DEFAULT_MODEL) -> Callable[[Task, Milestone], dict]:
    """A QA gate. With a router it asks the LLM whether the output satisfies the
    milestone's success_criteria; without one it does a deterministic check
    (non-empty + each criterion's keywords appear)."""

    def _qa(task: Task, ms: Milestone) -> dict[str, Any]:
        output = str(task.output or "")
        if not output.strip():
            return {"approved": False, "reason": "empty output"}
        if router is None or not ms.success_criteria:
            missing = [c for c in ms.success_criteria if not _criterion_touched(c, output)]
            return {
                "approved": not missing,
                "reason": "all criteria touched" if not missing else f"unmet: {missing}",
            }
        prompt = (
            "Does the OUTPUT satisfy ALL success criteria? Reply ONLY JSON "
            '{"approved":true|false,"reason":"..."}.'
            f"\n\nCriteria: {ms.success_criteria}\nOutput: {output[:4000]}"
        )
        try:
            from runtime.sensing.model_router import Message, ModelRequest

            text = (
                router.call(
                    ModelRequest(
                        model=model,
                        messages=[Message(role="user", content=prompt)],
                        max_tokens=300,
                        temperature=0.0,
                    )
                ).text
                or ""
            )
            block = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(block.group(0)) if block else {}
            if not isinstance(data, dict) or type(data.get("approved")) is not bool:
                raise ValueError("QA response must contain a boolean approved field")
            return {"approved": data["approved"], "reason": str(data.get("reason") or "")}
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("LLM QA unavailable: %s", type(exc).__name__)
            raise RuntimeError("质量检查未完成，请重试；现有产物不能视为通过验收。") from exc

    return _qa


def _criterion_touched(criterion: str, output: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z0-9]{3,}|[一-鿿]{2,}", criterion.lower())]
    low = output.lower()
    return any(w in low for w in words) if words else True


def create_llm_hooks(
    router: Any,
    *,
    model: str = DEFAULT_MODEL,
    subagent_runner: Callable[..., str] | None = None,
) -> dict[str, Any]:
    """Hook kwargs for ProjectEngine: LLM milestones/tasks/QA + subagent execute."""

    def _execute_task(task: Task, context: dict[str, Any]) -> str:
        return subagent_execute_task(
            task,
            context,
            subagent_runner=subagent_runner,
        )

    return {
        "generate_milestones": llm_generate_milestones(router, model=model),
        "decompose_tasks": llm_decompose_tasks(router, model=model),
        "execute_task": _execute_task,
        "qa_task": spec_qa(router, model=model),
    }
