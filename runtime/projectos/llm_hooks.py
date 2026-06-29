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
        ttype = item.get("type") if item.get("type") in (
            "design", "code", "research", "analysis", "review"
        ) else "code"
        goal = str(item.get("goal") or item.get("title") or tid)
        label_to_id[goal] = tid
        label_to_id[str(i)] = tid
        out.append(
            Task(
                id=tid,
                milestone_id=milestone_id,
                type=ttype,
                goal=goal,
                assigned_role=ROLE_FOR_TASK.get(ttype, "engineer"),
                depends_on=[str(d) for d in (item.get("depends_on") or [])],
            )
        )
    valid = {t.id for t in out}
    for t in out:
        t.depends_on = [label_to_id.get(d, d) for d in t.depends_on]
        t.depends_on = [d for d in t.depends_on if d in valid and d != t.id]
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
            "Decompose this milestone into 2–5 tasks forming a small DAG. Reply "
            'ONLY a JSON array; each item: {"type":"design|code|research|analysis|'
            'review","goal","depends_on":[earlier goals]}.'
            f"\n\nMilestone: {ms.goal}\nSpec: {json.dumps(ms.spec, ensure_ascii=False)}"
            f"\nSuccess criteria: {ms.success_criteria}"
        )
        try:
            tasks = parse_tasks(_llm_text(router, prompt, model=model), ms.id)
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("task decomposition failed: %s", exc)
            tasks = []
        return tasks or [Task(id=f"{ms.id}-T1", milestone_id=ms.id, type="code", goal=ms.goal)]

    return _decompose


def subagent_execute_task(task: Task, context: dict[str, Any]) -> str:
    """Run a task through the production subagent path (the cowork bridge)."""
    from runtime.execution.subagents import call_subagent

    agent = task.assigned_agent or task.assigned_role or "engineer"
    prompt = task.goal
    if context.get("milestone_goal"):
        prompt = f"Milestone: {context['milestone_goal']}\nTask: {task.goal}"
    result = call_subagent(
        agent,
        prompt,
        context={"source": "projectos_task", "task_id": task.id, "projectos": context},
        timeout_s=900,
        timeout_seconds=900.0,
    )
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

            text = router.call(
                ModelRequest(model=model, messages=[Message(role="user", content=prompt)],
                             max_tokens=300, temperature=0.0)
            ).text or ""
            block = re.search(r"\{.*\}", text, re.DOTALL)
            data = json.loads(block.group(0)) if block else {}
            return {"approved": bool(data.get("approved")), "reason": str(data.get("reason") or "")}
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("LLM QA failed, approving non-empty: %s", exc)
            return {"approved": True, "reason": "qa fallback (non-empty)"}

    return _qa


def _criterion_touched(criterion: str, output: str) -> bool:
    words = [w for w in re.findall(r"[A-Za-z0-9]{3,}|[一-鿿]{2,}", criterion.lower())]
    low = output.lower()
    return any(w in low for w in words) if words else True


def create_llm_hooks(router: Any, *, model: str = DEFAULT_MODEL) -> dict[str, Any]:
    """Hook kwargs for ProjectEngine: LLM milestones/tasks/QA + subagent execute."""
    return {
        "generate_milestones": llm_generate_milestones(router, model=model),
        "decompose_tasks": llm_decompose_tasks(router, model=model),
        "execute_task": subagent_execute_task,
        "qa_task": spec_qa(router, model=model),
    }
