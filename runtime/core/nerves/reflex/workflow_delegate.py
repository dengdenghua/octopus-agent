
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

_LOG = logging.getLogger("octopus.reflex.workflow")


def _workflows_dir() -> Path:
    return Path("data/workflows")


def _resolve_workflow(wf_ref: str) -> dict[str, Any] | None:
    """Look up a workflow by id (preferred · stable filename) or by
    exact ``name`` match (fallback). Returns the parsed JSON dict, or
    None when nothing matches."""
    d = _workflows_dir()
    if not d.is_dir():
        return None
    direct = d / f"{wf_ref}.json"
    if direct.is_file():
        try:
            return json.loads(direct.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return None
    for p in d.glob("*.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if data.get("name") == wf_ref or data.get("id") == wf_ref:
            return data
    return None


def _extract_final_text(trajectory: Any) -> str:
    """Best-effort scan of trajectory for the final text output.

    Workflows don't yet declare a canonical ``output`` schema, so we
    walk the last step in priority order (output > content > response
    > text). Empty when nothing matches.
    """
    steps = getattr(trajectory, "steps", None) or []
    if not steps:
        return ""
    last = steps[-1]
    for attr in ("output", "content", "response", "text"):
        val = getattr(last, attr, None)
        if isinstance(val, str) and val.strip():
            return val
    if isinstance(last, dict):
        for k in ("output", "content", "response", "text"):
            v = last.get(k)
            if isinstance(v, str) and v.strip():
                return v
    return ""


def run_workflow_for_reflex(
    wf_ref: str, user_input: str, stack: Any
) -> tuple[bool, str]:
    """Run the named workflow with the user's input · returns
    ``(success, text)``. ``success=False`` means the caller should
    fall back to the canned reply or ``reply_on_action_failure``.
    """
    if not wf_ref or not isinstance(wf_ref, str):
        return False, ""
    data = _resolve_workflow(wf_ref.strip())
    if data is None:
        _LOG.info("workflow not found: %s", wf_ref)
        return False, ""
    if stack is None or not hasattr(stack, "runtime"):
        return False, ""
    try:
        from runtime.sensing.gateway.workflow_editor_router import (
            _visual_to_task_graph,
        )
    except Exception:  # noqa: BLE001
        return False, ""
    defn = data.get("definition") or {}
    nodes = defn.get("nodes") or []
    edges = defn.get("edges") or []
    if not nodes:
        return False, ""
    task_graph = _visual_to_task_graph(
        nodes, edges, input_data={"input": user_input}
    )
    try:
        trajectory = stack.runtime.run(task_graph)
    except Exception as exc:  # noqa: BLE001
        _LOG.warning("workflow %s run failed: %s", wf_ref, exc)
        return False, ""
    return True, _extract_final_text(trajectory)


__all__ = ["run_workflow_for_reflex"]
