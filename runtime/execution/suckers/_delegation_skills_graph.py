"""``call_agent_graph`` · declarative DAG fan-out with server-side fan-in.

The gap this closes: ``call_agent_parallel`` fans out independent lanes, and
``run_pipeline`` chains stages per item, but neither lets one lane consume
another lane's output. That shape — A and B in parallel, C reading both — was
only reachable by the model running a lane, reading the result into its own
context, and hand-writing the next prompt. Every fan-in therefore cost a full
round-trip through the lead's context window.

Here the fan-in happens on the server: a node's prompt may reference
``{other_node.output}`` and the substitution is performed from the recorded
outputs before the spawn. The lead never sees the intermediate text.

Topology is DECLARED, not scripted. Each node names its ``depends_on`` and the
runtime derives execution layers, so there is no caller-supplied control flow
to execute — the same reason the budget envelope and the progress stream can
stay wrapped around a spec object. Conditionals and back-edges are deliberately
out of scope: dependencies already express the only ordering the callers
needed, and ``run_orchestration`` covers the one loop shape (rounds with
dry-round early stop) that had real demand.

Layer execution reuses ``_call_agent_parallel``, so per-spawn budget charging,
retry, route policy, blackboard keys and the envelope shape are inherited
rather than re-implemented.
"""

from __future__ import annotations

from typing import Any

from runtime.core.graph_runtime.runtime import (
    TemplateResolutionError,
    _lookup,
    _topo_layers,
)

from ._delegation_skills_common import _DEFAULT_SUBAGENT_TIMEOUT_S

# A graph is a coordination structure, not a work multiplier: the per-node
# spawn is one agent, so the ceiling is about how much topology a single call
# may declare. Kept well under the parallel fan-out cap because a deep graph
# serialises — 12 nodes of depth 12 is 12 sequential spawns.
_MAX_GRAPH_NODES = 12


class _GraphNode:
    """Minimal duck-type for ``_topo_layers``, which only reads ``node_id``."""

    __slots__ = ("node_id",)

    def __init__(self, node_id: str) -> None:
        self.node_id = node_id


class _GraphEdge:
    """Minimal duck-type for ``_topo_layers``: ``from_node`` → ``to_node``."""

    __slots__ = ("from_node", "to_node")

    def __init__(self, from_node: str, to_node: str) -> None:
        self.from_node = from_node
        self.to_node = to_node


def _coerce_graph_nodes(nodes: Any) -> tuple[list[dict[str, Any]], str]:
    """Normalise the caller's node list, or return ``(_, error)``.

    Fails closed on anything ambiguous. A malformed graph that ran anyway would
    spend real spawns on a topology the caller did not describe, which is worse
    than a rejection the model can read and correct.
    """
    if isinstance(nodes, str):
        import json

        try:
            nodes = json.loads(nodes)
        except json.JSONDecodeError as exc:
            return [], f"nodes must be a JSON array: {exc}"
    if not isinstance(nodes, (list, tuple)) or not nodes:
        return [], "nodes is required · a list of {id, prompt, depends_on?, agent_id?}"
    if len(nodes) > _MAX_GRAPH_NODES:
        return [], f"too many nodes ({len(nodes)} > {_MAX_GRAPH_NODES})"

    cleaned: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in nodes:
        if not isinstance(raw, dict):
            return [], f"each node must be an object, got {type(raw).__name__}"
        node_id = str(raw.get("id") or raw.get("node_id") or raw.get("name") or "").strip()
        if not node_id:
            return [], "every node needs an `id` (referenced by depends_on and templates)"
        if node_id in seen_ids:
            return [], f"duplicate node id {node_id!r}"
        prompt = str(raw.get("prompt") or raw.get("task") or raw.get("instruction") or "").strip()
        if not prompt:
            return [], f"node {node_id!r} has no prompt"
        deps_raw = raw.get("depends_on") or raw.get("after") or []
        if isinstance(deps_raw, str):
            deps_raw = [deps_raw]
        deps = [str(d).strip() for d in deps_raw if str(d).strip()]
        seen_ids.add(node_id)
        cleaned.append(
            {
                "id": node_id,
                "prompt": prompt,
                "depends_on": deps,
                "agent_id": str(raw.get("agent_id") or raw.get("role") or "").strip(),
                "output_schema": raw.get("output_schema"),
                "isolate": bool(raw.get("isolate")),
            }
        )

    known = {n["id"] for n in cleaned}
    for node in cleaned:
        unknown = [d for d in node["depends_on"] if d not in known]
        if unknown:
            return [], f"node {node['id']!r} depends on unknown node(s): {sorted(unknown)}"
        if node["id"] in node["depends_on"]:
            return [], f"node {node['id']!r} depends on itself"
    return cleaned, ""


def _plan_layers(nodes: list[dict[str, Any]]) -> tuple[list[list[int]], str]:
    """Derive execution layers, rejecting cycles.

    ``_topo_layers`` drops unreachable nodes rather than raising, so a cycle
    surfaces as a short layer list. Comparing the scheduled count against the
    node count is what turns that silent truncation into an explicit error —
    without it a cyclic graph would run its acyclic prefix and report success.
    """
    graph_nodes = [_GraphNode(n["id"]) for n in nodes]
    edges = [_GraphEdge(dep, n["id"]) for n in nodes for dep in n["depends_on"]]
    layers = _topo_layers(graph_nodes, edges)
    scheduled = sum(len(layer) for layer in layers)
    if scheduled != len(nodes):
        stuck = sorted(
            {n["id"] for i, n in enumerate(nodes)}
            - {nodes[i]["id"] for layer in layers for i in layer}
        )
        return [], f"graph has a dependency cycle · unreachable node(s): {stuck}"
    return layers, ""


def _resolve_node_prompt(prompt: str, outputs: dict[str, Any]) -> tuple[str, str]:
    """Substitute ``{node_id}`` / ``{node_id.output}`` references.

    This is the fan-in. ``_lookup`` is reused verbatim so the reference dialect
    matches the graph runtime's (both ``{a.field}`` and ``{a.output.field}``
    resolve), and an unresolvable reference is an error rather than a silently
    literal ``{a.output}`` reaching the worker as text.
    """
    from runtime.core.graph_runtime.runtime import _INLINE_TEMPLATE_RE

    missing: list[str] = []

    def _sub(match: Any) -> str:
        ref = match.group(1)
        try:
            return str(_lookup(ref, outputs))
        except TemplateResolutionError:
            missing.append(ref)
            return match.group(0)

    resolved = _INLINE_TEMPLATE_RE.sub(_sub, prompt)
    if missing:
        return prompt, f"unresolved reference(s): {sorted(set(missing))}"
    return resolved, ""


def _error(message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": message,
        "nodes": {},
        "layers_run": 0,
        "success_count": 0,
        "failure_count": 0,
    }


def _skipped_node(node_id: str, reason: str) -> dict[str, Any]:
    return {"id": node_id, "output": "", "ok": False, "skipped": True, "error": reason}


def _run_agent_graph(
    nodes: Any = None,
    *,
    default_agent_id: str = "researcher",
    timeout_s: int | str = _DEFAULT_SUBAGENT_TIMEOUT_S,
    context: dict[str, Any] | None = None,
    session: Any = None,
    **_kw: Any,
) -> dict[str, Any]:
    """Run a declared DAG of subagents, resolving fan-in server-side.

    Nodes with no unmet dependency run concurrently; a node whose prompt cites
    ``{other.output}`` receives the substituted text at spawn time.
    """
    from runtime.execution.suckers.delegation_skills import (
        _call_agent_parallel,
        _check_absolute_cap,
        _compute_fingerprint,
        _record_delegation,
        _resolve_session_and_turn,
    )

    cleaned, err = _coerce_graph_nodes(nodes if nodes is not None else _kw.get("graph"))
    if err:
        return _error(err)
    layers, err = _plan_layers(cleaned)
    if err:
        return _error(err)

    # One graph costs ONE against the per-turn delegation cap, matching
    # run_orchestration / run_pipeline: the internal spawn budget bounds the
    # width, so charging per node here would double-count.
    parent_sess, turn_id = _resolve_session_and_turn()
    if session is None:
        session = parent_sess
    _, within = _check_absolute_cap(turn_id)
    if not within:
        return _error(
            "delegation budget exhausted for this turn — do the rest yourself, "
            "don't launch another graph."
        )
    _record_delegation(
        turn_id,
        _compute_fingerprint("call_agent_graph", str([n["id"] for n in cleaned])),
        succeeded=True,
    )

    default_role = str(default_agent_id or "researcher").strip() or "researcher"
    by_id = {n["id"]: n for n in cleaned}
    outputs: dict[str, Any] = {}
    results: dict[str, dict[str, Any]] = {}
    layers_run = 0

    for layer in layers:
        # A node whose dependency failed cannot receive the output it was
        # written to consume. Spawning it anyway would spend budget on a prompt
        # containing an unresolved placeholder, so it is skipped explicitly and
        # reported — the caller can see WHICH branch collapsed rather than
        # reading a confusing worker reply.
        runnable: list[dict[str, Any]] = []
        for idx in layer:
            node = cleaned[idx]
            failed_deps = [d for d in node["depends_on"] if d not in outputs]
            if failed_deps:
                results[node["id"]] = _skipped_node(
                    node["id"],
                    f"upstream node(s) did not produce output: {sorted(failed_deps)}",
                )
                continue
            prompt, perr = _resolve_node_prompt(node["prompt"], outputs)
            if perr:
                results[node["id"]] = _skipped_node(node["id"], perr)
                continue
            runnable.append({**node, "resolved_prompt": prompt})

        if not runnable:
            continue

        env = _call_agent_parallel(
            specs=[
                {
                    "agent_id": n["agent_id"] or default_role,
                    "prompt": n["resolved_prompt"],
                    "bb_key": n["id"],
                    **({"output_schema": n["output_schema"]} if n["output_schema"] else {}),
                }
                for n in runnable
            ],
            timeout_s=timeout_s,
            context=context,
            session=session,
        )
        layers_run += 1

        # ``bb_key`` carries the node id through the envelope, which is how a
        # result is matched back to its node. spec_index is the fallback for a
        # lane that lost its label.
        for succ in env.get("successes", []):
            node_id = str(succ.get("bb_key") or "").strip()
            if not node_id:
                pos = succ.get("spec_index")
                node_id = (
                    runnable[pos]["id"] if isinstance(pos, int) and pos < len(runnable) else ""
                )
            if not node_id or node_id not in by_id:
                continue
            text = str(succ.get("output") or "")
            parsed = succ.get("parsed")
            outputs[node_id] = parsed if isinstance(parsed, dict) else text
            results[node_id] = {
                "id": node_id,
                "agent_id": succ.get("agent_id"),
                "output": text,
                "ok": True,
            }
        for fail in env.get("failures", []):
            node_id = str(fail.get("bb_key") or "").strip()
            if not node_id or node_id not in by_id:
                continue
            results[node_id] = {
                "id": node_id,
                "agent_id": fail.get("agent_id"),
                "output": "",
                "ok": False,
                "error": str(fail.get("error") or fail.get("error_type") or "unknown failure"),
            }

    ok_count = sum(1 for r in results.values() if r.get("ok"))
    return {
        "ok": True,
        "nodes": results,
        "order": [[cleaned[i]["id"] for i in layer] for layer in layers],
        "layers_run": layers_run,
        "success_count": ok_count,
        "failure_count": len(cleaned) - ok_count,
        "total": len(cleaned),
        # Terminal nodes are what the caller usually wants: the leaves of the
        # graph hold the folded result, and re-reading every intermediate output
        # would defeat the point of resolving fan-in server-side.
        "terminal": [
            results.get(n["id"], {}).get("output", "")
            for n in cleaned
            if not any(n["id"] in other["depends_on"] for other in cleaned)
        ],
    }
