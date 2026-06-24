"""
Observability router · journal / reflect / kg / progress / stream / run.

Extracted from ``runtime/platform/ui/app.py`` as part of the
app.py-split campaign. Groups the 6 endpoints the UI's
Observability panel + `/api/stream` SSE feed rely on:

    GET  /api/journal    · event counts + recent tail
    GET  /api/reflect    · kick all 6 reflection producers
    GET  /api/kg         · query the knowledge graph
    GET  /api/progress   · per-task progress snapshots
    GET  /api/stream     · SSE feed of journal appends
    POST /api/run        · quick static-planner probe run

These are the debug / introspection surface. They expose the
journal — which carries file diffs, absolute paths, and task
history — over ``/api/stream`` and ``/api/files/stream``. So they
DO honour ``require_auth`` via a router-level dependency (see
``create_observability_router``): off by default for single-user
dev (no-op, frontend EventSource panel unchanged), enforced as 401
when auth is enabled so a deployed/multi-user server doesn't leak
the whole work log to any anonymous client.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

try:
    from fastapi import APIRouter, Depends, HTTPException, Query, Request
    from fastapi.responses import StreamingResponse

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    StreamingResponse = None  # type: ignore[assignment, misc]


# Standard SSE headers · keep proxies (nginx, Cloudflare) from buffering or
# killing long-lived event streams. X-Accel-Buffering disables nginx response
# buffering; Cache-Control/Connection keep the stream open. The generators
# below already emit a 15s ``: keepalive`` comment to defeat idle timeouts.
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


# ═══════════════════════════════════════════════════════════
# Module-level helpers (previously in app.py tail)
# ═══════════════════════════════════════════════════════════


def _safe_put(q: Any, event: Any) -> None:
    """Push event into a bounded queue with back-pressure protection.

    If the queue is full we drop the OLDEST event and retry · the
    alternative (dropping the new one) would stall a slow
    consumer's view of recent events. Journal throughput is never
    blocked on a slow SSE client.
    """
    try:
        q.put_nowait(event)
    except (OSError, ValueError):
        with contextlib.suppress(OSError, ValueError):
            q.get_nowait()
        with contextlib.suppress(OSError, ValueError):
            q.put_nowait(event)


def _snapshot_to_dict(snap: Any) -> dict[str, Any]:
    """TaskProgressSnapshot → JSON-safe dict."""
    return {
        "task_id": snap.task_id,
        "total_nodes": snap.total_nodes,
        "nodes_completed": snap.nodes_completed,
        "progress_pct": snap.progress_pct,
        "current_node_id": snap.current_node_id,
        "current_node_index": snap.current_node_index,
        "status": snap.status,
        "strategy": snap.strategy,
        "task_type": snap.task_type,
        "started_at": (snap.started_at.isoformat() if snap.started_at else None),
        "last_event_ts": (snap.last_event_ts.isoformat() if snap.last_event_ts else None),
        "tokens_spent": snap.tokens_spent,
        "usd_spent": snap.usd_spent,
    }


def _safe_call(fn: Any) -> dict[str, Any]:
    """Wrap a reflection-producer call so one failure doesn't
    bring down the aggregate response · returns ``{"error": "..."}``
    for the failed producer and the others still populate."""
    try:
        return fn()
    except (OSError, ImportError, ValueError, TypeError) as e:
        return {"error": f"{type(e).__name__}: {e}"}


def _skill_forge_stub(journal: Any, registry: Any) -> dict[str, Any]:
    from runtime.safety.recovery import SkillForge

    result = SkillForge(journal, registry).run()
    return {
        "candidates": result.candidates_total,
        "promoted": len(result.promoted),
        "retired": len(result.retired),
    }


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════


def _serialize_rollback_entry(entry: Any) -> dict[str, Any]:
    content = getattr(entry, "content", None)
    return {
        "path": getattr(entry, "path", ""),
        "action": getattr(entry, "action", ""),
        "expected_current_sha256": getattr(
            entry,
            "expected_current_sha256",
            "",
        ),
        "source_event_id": getattr(entry, "source_event_id", ""),
        "content_bytes": (len(content.encode("utf-8")) if isinstance(content, str) else None),
    }


def _serialize_rollback_result(
    result: Any,
    *,
    dry_run: bool,
    matched_events: int,
    event_id: str | None,
    task_id: str | None,
    path: str | None,
    project_root: str | None,
) -> dict[str, Any]:
    return {
        "dry_run": dry_run,
        "matched_events": matched_events,
        "event_id": event_id,
        "task_id": task_id,
        "path": path,
        "project_root": project_root,
        "applied": int(getattr(result, "applied", 0) or 0),
        "skipped": int(getattr(result, "skipped", 0) or 0),
        "failed": int(getattr(result, "failed", 0) or 0),
        "entries": [
            _serialize_rollback_entry(entry) for entry in getattr(result, "entries", ()) or ()
        ],
        "errors": list(getattr(result, "errors", ()) or ()),
    }


def _serialize_file_rollback_event(event: Any) -> dict[str, Any]:
    return {
        "event_type": getattr(event, "event_type", "file_rollback"),
        "event_id": str(getattr(event, "event_id", "") or ""),
        "ts": (event.ts.isoformat() if getattr(event, "ts", None) is not None else None),
        "dry_run": bool(getattr(event, "dry_run", False)),
        "project_root": getattr(event, "project_root", ""),
        "event_id_filter": getattr(event, "event_id_filter", None),
        "task_id_filter": getattr(event, "task_id_filter", None),
        "path_filter": getattr(event, "path_filter", None),
        "applied": int(getattr(event, "applied", 0) or 0),
        "skipped": int(getattr(event, "skipped", 0) or 0),
        "failed": int(getattr(event, "failed", 0) or 0),
        "source_event_ids": list(
            getattr(event, "source_event_ids", []) or [],
        ),
        "paths": list(getattr(event, "paths", []) or []),
        "errors": list(getattr(event, "errors", []) or []),
    }


def create_observability_router(
    *,
    journal: Any,
    registry: Any,
    planner: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    """Build the router.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ observability_router.py · navigation map (1242 lines).             ║
    ║                                                                    ║
    ║   §1 helpers (snapshot/serialise/safe_call)       ~L44             ║
    ║   §2 create_observability_router (factory)        ~L178            ║
    ║       §2.1 /api/journal + /api/journal/timeline   ~L292            ║
    ║       §2.2 /api/reflect                           ~L346            ║
    ║       §2.3 /api/evolution (status + delete)       ~L413            ║
    ║       §2.4 /api/kg (CRUD + export/import)         ~L519            ║
    ║       §2.5 /api/knowledge (graph/stats/neighbors) ~L623            ║
    ║       §2.6 /api/progress + /api/stream (SSE)      ~L666            ║
    ║       §2.7 /api/files/stream + rollback           ~L828            ║
    ║       §2.8 /api/blackboard + /api/hemolymph       ~L948            ║
    ║       §2.9 /api/regeneration/summary              ~L1011           ║
    ╚════════════════════════════════════════════════════════════════════╝

    Parameters
    ----------
    journal :
        Must be the SAME Journal instance the rest of the runtime
        writes to · ``/api/stream`` subscribes to its append
        callback and ``/api/progress`` builds a TaskProgressTracker
        off it.
    registry :
        SkillRegistry · only touched by ``/api/run`` to execute a
        static probe skill and by ``_skill_forge_stub`` to enumerate
        skills during the reflect pass.
    planner :
        Optional LLMPlanner · enables the cheap
        ``/api/evolution/status`` endpoint that reads in-memory
        ``learned_rules_section`` + ``learned_memories_section`` and
        counts react_loop trajectories. None → endpoint returns
        ``{"enabled": False}`` (planner-less test harness).
    """
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    def _auth_dep(request: Request) -> None:
        # Router-level auth gate · mirrors create_browser_router. These
        # endpoints expose the journal (file diffs, absolute paths, task
        # history) over /api/stream + /api/files/stream. require_auth off
        # (default / single-user dev) → _resolve_actor is a no-op so local
        # preview + the EventSource-based Observability panel are unchanged;
        # require_auth on (deployed / multi-user) → 401 across every endpoint
        # instead of leaking the whole work log to any anonymous client.
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(  # AUTH-OK: actor-agnostic — router-level dep, 401 enforcement only
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["observability"], dependencies=[Depends(_auth_dep)])

    # Progress tracker owns incremental O(N_tasks) snapshots · build
    # once per app, not per request.
    from runtime.memory.journal import TaskProgressTracker

    progress_tracker = TaskProgressTracker(journal)

    def _rollback_file_events(
        *,
        event_id: str | None = None,
        task_id: str | None = None,
        path: str | None = None,
        limit: int = 500,
    ) -> list[Any]:
        events: list[Any] = []
        for event in journal.read_by_type("file_op"):
            if event_id and str(getattr(event, "event_id", "") or "") != event_id:
                continue
            if task_id and str(getattr(event, "task_id", "") or "") != task_id:
                continue
            if path and str(getattr(event, "path", "") or "") != path:
                continue
            events.append(event)
        return events[-limit:]

    def _rollback_result(
        *,
        event_id: str | None,
        task_id: str | None,
        path: str | None,
        project_root: str | None,
        limit: int,
        dry_run: bool,
    ) -> dict[str, Any]:
        from runtime.memory.runtime_state.file_transactions import (
            apply_file_rollback_ledger,
        )

        events = _rollback_file_events(
            event_id=event_id,
            task_id=task_id,
            path=path,
            limit=limit,
        )
        result = apply_file_rollback_ledger(
            events,
            project_root=project_root,
            dry_run=dry_run,
        )
        if not dry_run:
            from runtime.memory.journal import FileRollbackEvent

            journal.write(
                FileRollbackEvent(
                    dry_run=False,
                    project_root=project_root or "",
                    event_id_filter=event_id,
                    task_id_filter=task_id,
                    path_filter=path,
                    applied=int(getattr(result, "applied", 0) or 0),
                    skipped=int(getattr(result, "skipped", 0) or 0),
                    failed=int(getattr(result, "failed", 0) or 0),
                    source_event_ids=[
                        str(getattr(entry, "source_event_id", "") or "")
                        for entry in getattr(result, "entries", ()) or ()
                        if getattr(entry, "source_event_id", "") or ""
                    ],
                    paths=[
                        str(getattr(entry, "path", "") or "")
                        for entry in getattr(result, "entries", ()) or ()
                        if getattr(entry, "path", "") or ""
                    ],
                    errors=list(getattr(result, "errors", ()) or ()),
                )
            )
        return _serialize_rollback_result(
            result,
            dry_run=dry_run,
            matched_events=len(events),
            event_id=event_id,
            task_id=task_id,
            path=path,
            project_root=project_root,
        )

    # ─── /api/journal ───────────────────────────────────────
    @router.get("/api/journal")
    def api_journal(
        limit: int = Query(default=20, ge=1, le=500),
    ) -> dict[str, Any]:
        events = journal.read_all()
        counts: dict[str, int] = {}
        for e in events:
            counts[e.event_type] = counts.get(e.event_type, 0) + 1
        tail = [
            {
                "event_type": e.event_type,
                "ts": e.ts.isoformat(),
                "task_id": str(e.task_id) if e.task_id else None,
                "arm_id": e.arm_id,
            }
            for e in events[-limit:]
        ]
        return {"total": len(events), "counts": counts, "recent": tail}

    # ─── /api/journal/timeline ─────────────────────────────
    @router.get("/api/journal/timeline")
    def api_journal_timeline(
        task_id: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        events = journal.read_all()
        grouped: dict[str, list[dict[str, Any]]] = {}
        for e in events:
            tid = str(e.task_id) if e.task_id else "_no_task"
            if task_id and tid != task_id:
                continue
            entry = {
                "event_type": e.event_type,
                "ts": e.ts.isoformat(),
                "task_id": tid,
                "arm_id": e.arm_id,
            }
            payload = getattr(e, "payload", None)
            if isinstance(payload, dict):
                for k in (
                    "skill_name",
                    "strategy",
                    "strategy_id",
                    "thought",
                    "action",
                    "observation",
                    "iteration",
                    "final_answer",
                    "error",
                    "tokens_in",
                    "tokens_out",
                    "usd",
                    "latency_ms",
                    "model",
                    "provider",
                ):
                    if k in payload:
                        entry[k] = payload[k]
            grouped.setdefault(tid, []).append(entry)
        task_ids = sorted(
            grouped.keys(), key=lambda k: grouped[k][0]["ts"] if grouped[k] else "", reverse=True
        )[:limit]
        return {
            "task_ids": task_ids,
            "timelines": {tid: grouped[tid] for tid in task_ids},
        }

    # ─── /api/reflect ───────────────────────────────────────
    @router.get("/api/reflect")
    def api_reflect() -> dict[str, Any]:
        if len(journal.read_all()) == 0:
            return {"error": "journal empty · run something first"}

        # Lazy imports · these pull in heavier analysis code that
        # doesn't need to be at module-load time.
        from runtime.memory.knowledge_graph import KnowledgeGraph
        from runtime.safety.recovery import (
            KGUpdater,
            MemoryConsolidator,
            RecipeEvaluator,
            RuleExtractor,
            WorkflowRewriter,
        )

        sf_result = _safe_call(
            lambda: _skill_forge_stub(journal, registry),
        )
        re_report = RuleExtractor(journal).extract()
        kg = KnowledgeGraph()
        kg_report = KGUpdater(journal, kg).update()
        mc = MemoryConsolidator(journal).consolidate()
        wr = WorkflowRewriter(journal).analyze()
        rc = RecipeEvaluator(journal).evaluate()

        return {
            "skill_forge": sf_result,
            "rule_extractor": {"rules": len(re_report.rules_produced)},
            "kg": {
                "accepted": kg_report.triples_accepted,
                "total": kg.count(),
            },
            "memory": {"memories": len(mc.memories_produced)},
            "workflow": {
                "proposals": len(wr.proposals),
                "by_kind": wr.proposals_by_kind,
            },
            "recipe": {
                "recipes": rc.recipes_found,
                "best": rc.best.recipe_id if rc.best else None,
            },
        }

    def _parse_section_lines(section: str) -> list[str]:
        out: list[str] = []
        for ln in (section or "").splitlines():
            stripped = ln.lstrip()
            if stripped.startswith("- ["):
                out.append(stripped[2:].strip())  # Implementation note.
        return out

    def _rebuild_section(header: str, items: list[str]) -> str:
        if not items:
            return ""
        lines = [header]
        for item in items:
            lines.append(f"  - {item}")
        return "\n".join(lines)

    # ─── /api/evolution/status ──────────────────────────────
    # Cheap read-only view of what the planner has currently
    # internalized from past runs. Unlike /api/reflect (which
    # RUNS all 6 producers synchronously · expensive), this just
    # reads the pre-computed ``learned_*_section`` strings + counts
    # trajectories by strategy_id. Cost: O(1) + O(N_trajectories).
    @router.get("/api/evolution/status")
    def api_evolution_status() -> dict[str, Any]:
        if planner is None:
            return {
                "enabled": False,
                "reason": "no planner wired to observability router",
            }
        rules_section = getattr(planner, "learned_rules_section", "") or ""
        memories_section = getattr(planner, "learned_memories_section", "") or ""
        # Count rule/memory lines: each bullet starts with "  - "
        # (see format_rules_for_prompt / format_memories_for_prompt).
        rules_count = sum(1 for ln in rules_section.splitlines() if ln.lstrip().startswith("- ["))
        memories_count = sum(
            1 for ln in memories_section.splitlines() if ln.lstrip().startswith("- [")
        )

        # Trajectory-level counts from journal · by strategy_id
        react_trajs = 0
        react_failures = 0
        total_trajs = 0
        try:
            from runtime.memory.journal import TrajectoryEvent

            for ev in journal.read_by_type("trajectory"):
                if not isinstance(ev, TrajectoryEvent):
                    continue
                total_trajs += 1
                if ev.trajectory.strategy_id == "react_loop":
                    react_trajs += 1
                    if not ev.trajectory.outcome.success:
                        react_failures += 1
        except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
            pass

        rules_lines = _parse_section_lines(rules_section)
        memories_lines = _parse_section_lines(memories_section)

        react_variants: list[dict[str, Any]] = []
        try:
            from runtime.core.cerebrum.react_loop import (
                get_react_variant_stats,
            )

            react_variants = get_react_variant_stats()
        except (OSError, ImportError, AttributeError):
            react_variants = []

        return {
            "enabled": True,
            "rules_count": rules_count,
            "memories_count": memories_count,
            "rules_section": rules_section,
            "memories_section": memories_section,
            "rules_lines": rules_lines,
            "memories_lines": memories_lines,
            "trajectories": {
                "total": total_trajs,
                "react_loop": react_trajs,
                "react_loop_failures": react_failures,
            },
            "react_variants": react_variants,
        }

    # ─── DELETE /api/evolution/rules/{index} ────────────────
    @router.delete("/api/evolution/rules/{index}")
    def api_forget_rule(index: int) -> dict[str, Any]:
        if planner is None:
            raise HTTPException(status_code=503, detail="planner not wired")
        current = _parse_section_lines(
            getattr(planner, "learned_rules_section", "") or "",
        )
        if index < 0 or index >= len(current):
            raise HTTPException(
                status_code=404,
                detail=f"rule index {index} out of range (have {len(current)})",
            )
        dropped = current.pop(index)
        planner.learned_rules_section = _rebuild_section(
            "LEARNED MITIGATIONS (from past failures):",
            current,
        )
        return {"dropped": dropped, "remaining": len(current)}

    # ─── DELETE /api/evolution/memories/{index} ─────────────
    @router.delete("/api/evolution/memories/{index}")
    def api_forget_memory(index: int) -> dict[str, Any]:
        if planner is None:
            raise HTTPException(status_code=503, detail="planner not wired")
        current = _parse_section_lines(
            getattr(planner, "learned_memories_section", "") or "",
        )
        if index < 0 or index >= len(current):
            raise HTTPException(
                status_code=404,
                detail=f"memory index {index} out of range (have {len(current)})",
            )
        dropped = current.pop(index)
        planner.learned_memories_section = _rebuild_section(
            "CONSOLIDATED MEMORIES (past pattern stats):",
            current,
        )
        return {"dropped": dropped, "remaining": len(current)}

    # ─── /api/kg ────────────────────────────────────────────
    @router.get("/api/kg")
    def api_kg(
        subject: str | None = None,
        predicate: str | None = None,
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        from runtime.memory.knowledge_graph import KnowledgeGraph
        from runtime.safety.recovery import KGUpdater

        kg = KnowledgeGraph()
        KGUpdater(journal, kg).update()
        triples = kg.query(subject=subject, predicate=predicate)[:limit]
        return {
            "count": len(triples),
            "kg_size": kg.count(),
            "triples": [
                {
                    "subject": t.subject,
                    "predicate": t.predicate,
                    "object": t.object[:200],
                    "confidence": t.confidence,
                }
                for t in triples
            ],
        }

    # ─── /api/kg/export + /api/kg/import ───────────────────
    @router.get("/api/kg/export")
    def api_kg_export() -> dict[str, Any]:
        from runtime.memory.knowledge_graph import KnowledgeGraph
        from runtime.safety.recovery import KGUpdater

        kg = KnowledgeGraph()
        KGUpdater(journal, kg).update()
        triples = kg.export_triples(active_only=True)
        return {"count": len(triples), "triples": triples}

    @router.post("/api/kg/import")
    async def api_kg_import(request: Any) -> dict[str, Any]:
        from runtime.memory.knowledge_graph import KnowledgeGraph
        from runtime.safety.recovery import KGUpdater

        try:
            body = await request.json()
        except (OSError, json.JSONDecodeError, ValueError, TypeError) as e:
            raise HTTPException(400, f"body: {e}") from e

        kg = KnowledgeGraph()
        KGUpdater(journal, kg).update()

        obsidian_text = body.get("obsidian")
        if isinstance(obsidian_text, str):
            result = kg.import_obsidian_markdown(
                obsidian_text,
                page_name=body.get("page_name", ""),
            )
        else:
            triples = body.get("triples", [])
            if not isinstance(triples, list):
                raise HTTPException(400, "triples must be a list")
            result = kg.import_triples(
                triples,
                source_label=body.get("source", "api_import"),
                default_confidence=float(body.get("confidence", 0.75)),
            )
        return result

    # ─── /api/knowledge/graph + /api/knowledge/stats ────────
    def _build_kg_view(limit: int = 200) -> tuple[list, list, dict]:
        from runtime.memory.knowledge_graph import KnowledgeGraph
        from runtime.safety.recovery import KGUpdater

        kg = KnowledgeGraph()
        KGUpdater(journal, kg).update()
        triples = kg.query()[:limit]

        entity_set: dict[str, dict[str, Any]] = {}
        rels: list[dict[str, Any]] = []
        type_counts: dict[str, int] = {}

        for i, t in enumerate(triples):
            for val, role in [(t.subject, "subject"), (t.object, "object")]:
                if val not in entity_set:
                    etype = "subject" if role == "subject" else "object"
                    entity_set[val] = {
                        "id": val,
                        "name": val[:80],
                        "entity_type": etype,
                        "description": "",
                    }
                    type_counts[etype] = type_counts.get(etype, 0) + 1
            rels.append(
                {
                    "id": f"rel_{i}",
                    "source_name": t.subject,
                    "target_name": t.object[:200],
                    "relationship_type": t.predicate,
                    "confidence": t.confidence,
                }
            )

        entities = list(entity_set.values())
        stats = {
            "total_entities": len(entities),
            "total_relationships": len(rels),
            "entity_types": type_counts,
        }
        return entities, rels, stats

    @router.get("/api/knowledge/graph")
    def api_knowledge_graph(
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        entities, relationships, _ = _build_kg_view(limit)
        return {"entities": entities, "relationships": relationships}

    @router.get("/api/knowledge/stats")
    def api_knowledge_stats() -> dict[str, Any]:
        _, _, stats = _build_kg_view(500)
        return stats

    @router.get("/api/knowledge/neighbors")
    def api_knowledge_neighbors(
        entity: str = Query(...),
        hops: int = Query(default=1, ge=1, le=3),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> dict[str, Any]:
        from runtime.memory.knowledge_graph import KnowledgeGraph
        from runtime.safety.recovery import KGUpdater

        kg = KnowledgeGraph()
        KGUpdater(journal, kg).update()
        triples = kg.neighbors(entity, hops=hops)[:limit]
        nodes: dict[str, dict[str, str]] = {}
        edges: list[dict[str, Any]] = []
        for i, t in enumerate(triples):
            for val in [t.subject, t.object]:
                if val not in nodes:
                    nodes[val] = {"id": val, "label": val[:60]}
            edges.append(
                {
                    "id": f"e_{i}",
                    "source": t.subject,
                    "target": t.object[:200],
                    "label": t.predicate,
                    "confidence": t.confidence,
                }
            )
        return {
            "center": entity,
            "nodes": list(nodes.values()),
            "edges": edges,
        }

    # ─── /api/progress ──────────────────────────────────────
    @router.get("/api/progress")
    def api_progress(
        task_id: str | None = None,
    ) -> dict[str, Any]:
        if task_id is not None:
            snap = progress_tracker.get(task_id)
            if snap is None:
                raise HTTPException(
                    404,
                    f"no events for task_id={task_id!r}",
                )
            return _snapshot_to_dict(snap)

        snaps = progress_tracker.snapshots
        return {
            "count": progress_tracker.count(),
            "running": progress_tracker.running_count(),
            "tasks": [_snapshot_to_dict(s) for s in snaps[:50]],
        }

    def _event_base_payload(event: Any) -> dict[str, Any]:
        return {
            "event_type": event.event_type,
            "ts": event.ts.isoformat(),
            "task_id": (str(event.task_id) if event.task_id else None),
            "arm_id": event.arm_id,
        }

    def _enrich_event_payload(event: Any) -> dict[str, Any]:
        from runtime.memory.journal import (
            BrowserArtifactEvent,
            FileOpEvent,
            FileRollbackEvent,
            PreviewRefreshEvent,
            SubToolEndEvent,
            SubToolStartEvent,
        )

        payload = _event_base_payload(event)
        if isinstance(event, FileOpEvent):
            payload.update(
                {
                    "path": event.path,
                    "action": event.action,
                    "bytes_delta": event.bytes_delta,
                    "old_size": event.old_size,
                    "new_size": event.new_size,
                    "sucker_id": event.sucker_id,
                    "diff": event.diff,
                }
            )
        elif isinstance(event, FileRollbackEvent):
            payload.update(_serialize_file_rollback_event(event))
        elif isinstance(event, PreviewRefreshEvent):
            payload.update(
                {
                    "target": event.target,
                    "trigger_path": event.trigger_path,
                    "reason": event.reason,
                }
            )
        elif isinstance(event, SubToolStartEvent):
            payload.update(
                {
                    "role_id": event.role_id,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "iteration": event.iteration,
                    "args_preview": event.args_preview,
                    "parent_tool_use_id": event.parent_tool_use_id,
                }
            )
        elif isinstance(event, SubToolEndEvent):
            payload.update(
                {
                    "role_id": event.role_id,
                    "tool_call_id": event.tool_call_id,
                    "tool_name": event.tool_name,
                    "iteration": event.iteration,
                    "is_error": event.is_error,
                    "duration_ms": event.duration_ms,
                    "output_preview": event.output_preview,
                    "parent_tool_use_id": event.parent_tool_use_id,
                }
            )
        elif isinstance(event, BrowserArtifactEvent):
            payload.update(
                {
                    "kind": event.kind,
                    "url": event.url,
                    "filename": event.filename,
                    "caption": event.caption,
                    "mime_type": event.mime_type,
                    "width": event.width,
                    "height": event.height,
                    "thread_id": event.thread_id,
                }
            )
        return payload

    # ─── /api/stream (SSE) ──────────────────────────────────
    @router.get("/api/stream")
    def api_stream() -> Any:
        import queue as _queue

        q: _queue.Queue[Any] = _queue.Queue(maxsize=500)
        unsubscribe = journal.subscribe(
            lambda event: _safe_put(q, event),
        )

        def _gen():
            try:
                yield f": connected · {len(journal)} events so far\n\n"
                while True:
                    try:
                        event = q.get(timeout=15.0)
                    except _queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    payload = _enrich_event_payload(event)
                    yield f"data: {json.dumps(payload)}\n\n"
            finally:
                unsubscribe()

        return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)

    @router.get("/api/preview/stream")
    def api_preview_stream() -> Any:
        import queue as _queue

        q: _queue.Queue[Any] = _queue.Queue(maxsize=200)

        def _only_preview(event: Any) -> None:
            if getattr(event, "event_type", "") == "preview_refresh":
                _safe_put(q, event)

        unsubscribe = journal.subscribe(_only_preview)

        def _gen():
            try:
                try:
                    from runtime.memory.journal import PreviewRefreshEvent

                    recent = [e for e in journal.read_all() if isinstance(e, PreviewRefreshEvent)][
                        -5:
                    ]
                    for ev in recent:
                        payload = _enrich_event_payload(ev)
                        yield (f"event: preview_refresh\ndata: {json.dumps(payload)}\n\n")
                except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
                    pass

                yield ": connected\n\n"
                while True:
                    try:
                        event = q.get(timeout=15.0)
                    except _queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    payload = _enrich_event_payload(event)
                    yield (f"event: preview_refresh\ndata: {json.dumps(payload)}\n\n")
            finally:
                unsubscribe()

        return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)

    @router.get("/api/files/stream")
    def api_files_stream() -> Any:
        import queue as _queue

        q: _queue.Queue[Any] = _queue.Queue(maxsize=500)

        def _only_file_op(event: Any) -> None:
            if getattr(event, "event_type", "") == "file_op":
                _safe_put(q, event)

        unsubscribe = journal.subscribe(_only_file_op)

        def _gen():
            try:
                try:
                    from runtime.memory.journal import FileOpEvent

                    recent = [e for e in journal.read_all() if isinstance(e, FileOpEvent)][-20:]
                    for ev in recent:
                        payload = _enrich_event_payload(ev)
                        yield (f"event: file_op\ndata: {json.dumps(payload)}\n\n")
                except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
                    pass

                yield ": connected\n\n"
                while True:
                    try:
                        event = q.get(timeout=15.0)
                    except _queue.Empty:
                        yield ": keepalive\n\n"
                        continue
                    payload = _enrich_event_payload(event)
                    yield (f"event: file_op\ndata: {json.dumps(payload)}\n\n")
            finally:
                unsubscribe()

        return StreamingResponse(_gen(), media_type="text/event-stream", headers=_SSE_HEADERS)

    # ═══════════════════════════════════════════════════════
    # Observability panels · feed the /workspace/observability UI
    # page with four focused endpoints. None require identity /
    # scope · they're read-only views of already-ambient state.
    # ═══════════════════════════════════════════════════════

    # ─── /api/blackboard · turn-scoped KV viewer ────────────
    # File rollback endpoints expose reversible file_op ledgers.
    @router.get("/api/files/rollback/preview")
    def api_files_rollback_preview(
        event_id: str | None = Query(default=None),
        task_id: str | None = Query(default=None),
        path: str | None = Query(default=None),
        project_root: str | None = Query(default=None),
        limit: int = Query(default=500, ge=1, le=2000),
    ) -> dict[str, Any]:
        """Dry-run reversible file operations from the journal."""
        return _rollback_result(
            event_id=event_id,
            task_id=task_id,
            path=path,
            project_root=project_root,
            limit=limit,
            dry_run=True,
        )

    @router.post("/api/files/rollback/apply")
    def api_files_rollback_apply(body: dict[str, Any]) -> dict[str, Any]:
        """Apply a task/path-scoped rollback ledger under a project root."""
        project_root = body.get("project_root")
        if not isinstance(project_root, str) or not project_root.strip():
            raise HTTPException(400, "project_root required for rollback apply")
        event_id = body.get("event_id")
        task_id = body.get("task_id")
        path = body.get("path")
        event_filter = event_id.strip() if isinstance(event_id, str) else None
        task_filter = task_id.strip() if isinstance(task_id, str) else None
        path_filter = path.strip() if isinstance(path, str) else None
        if not event_filter and not task_filter and not path_filter:
            raise HTTPException(
                400,
                "event_id, task_id or path required for rollback apply",
            )
        limit_value = body.get("limit", 500)
        try:
            limit = int(limit_value)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, "limit must be an integer") from exc
        if limit < 1 or limit > 2000:
            raise HTTPException(400, "limit must be between 1 and 2000")

        return _rollback_result(
            event_id=event_filter,
            task_id=task_filter,
            path=path_filter,
            project_root=project_root.strip(),
            limit=limit,
            dry_run=False,
        )

    @router.get("/api/files/rollback/history")
    def api_files_rollback_history(
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        events = journal.read_by_type("file_rollback")[-limit:]
        serialized = [_serialize_file_rollback_event(event) for event in reversed(events)]
        return {
            "count": len(serialized),
            "events": serialized,
        }

    @router.get("/api/blackboard")
    def api_blackboard(
        turn_id: str | None = None,
    ) -> dict[str, Any]:
        """Return either the list of active turns (no ``turn_id``)
        or a single turn's full snapshot (with ``turn_id``).

        The blackboard is process-local and ephemeral — this endpoint
        only makes sense for live debugging during a run. For the UI:
        poll the list on a heartbeat, then drill into a specific
        ``turn_id`` on click.
        """
        from runtime.memory.runtime_state.blackboard import (
            get_blackboard,
            list_active_turns,
        )

        if not turn_id:
            return {"turns": list_active_turns()}
        bb = get_blackboard(turn_id)
        if bb is None:
            raise HTTPException(404, f"no blackboard for turn_id={turn_id!r}")
        # snapshot() is already shallow-copied inside the bb lock, so
        # serializing here is safe. Values may be arbitrary JSON —
        # stringify exotic types defensively.
        snap = bb.snapshot()
        safe: dict[str, Any] = {}
        for k, v in snap.items():
            try:
                json.dumps(v)
                safe[k] = v
            except (TypeError, ValueError):
                safe[k] = repr(v)[:500]
        return {
            "turn_id": turn_id,
            "key_count": len(safe),
            "entries": safe,
            "audit": bb.audit(),
        }

    # ─── /api/hemolymph/recent · compose ring-buffer ────────
    @router.get("/api/hemolymph/recent")
    def api_hemolymph_recent(
        limit: int = Query(default=20, ge=1, le=50),
    ) -> dict[str, Any]:
        """Recent ``ContextComposer.compose()`` snapshots.

        Each entry is a compact view of how the four quotas (system /
        suckers / memory / history) were filled on one compose call:
        ``{ts, budget_tokens, tokens_used, utilization,
        by_bucket: {bucket: {used, alloc}}, segment_count, recipe_id,
        task_type}``. Feeds the 4-bucket budget meter panel.
        """
        from runtime.memory.hemolymph.composer import (
            get_recent_compose_snapshots,
        )

        snaps = get_recent_compose_snapshots(limit=limit)
        return {
            "count": len(snaps),
            "max_tracked": 50,
            "snapshots": snaps,
        }

    # ─── /api/regeneration/summary · 6-producer aggregate ───
    @router.get("/api/regeneration/summary")
    def api_regeneration_summary() -> dict[str, Any]:
        """Aggregate snapshot of the 6 reflection producers.

        Unlike ``/api/reflect`` (which RE-RUNS every producer on each
        call · expensive), this reads the pre-computed ``learned_*``
        sections off the planner + journal counters. Intended for
        the Observability panel's heartbeat polling: cheap, stateless,
        safe to call once per second.

        Shape: one key per producer; each carries a ``status`` and
        small count fields the UI renders as a tile.
        """
        from runtime.memory.journal import TrajectoryEvent

        # Trajectory counts · drive most producers' freshness signal
        traj_total = 0
        traj_failures = 0
        traj_by_strategy: dict[str, int] = {}
        try:
            for ev in journal.read_by_type("trajectory"):
                if not isinstance(ev, TrajectoryEvent):
                    continue
                traj_total += 1
                strat = ev.trajectory.strategy_id or "unknown"
                traj_by_strategy[strat] = traj_by_strategy.get(strat, 0) + 1
                if not ev.trajectory.outcome.success:
                    traj_failures += 1
        except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
            pass

        # rule_extractor · sync with planner's learned rules
        rules_count = 0
        memories_count = 0
        if planner is not None:
            rules_count = sum(
                1
                for ln in (getattr(planner, "learned_rules_section", "") or "").splitlines()
                if ln.lstrip().startswith("- [")
            )
            memories_count = sum(
                1
                for ln in (getattr(planner, "learned_memories_section", "") or "").splitlines()
                if ln.lstrip().startswith("- [")
            )

        # skill_forge · count forged skills in registry
        forged_count = 0
        try:
            for name in registry.all_names():
                sk = registry.get(name)
                if "forged" in (getattr(sk, "affinity", []) or []):
                    forged_count += 1
        except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
            pass

        # kg_updater · ambient triple count if KG is queryable
        kg_size = 0
        try:
            from runtime.memory.knowledge_graph import KnowledgeGraph
            from runtime.safety.recovery import KGUpdater

            kg = KnowledgeGraph()
            KGUpdater(journal, kg).update()
            kg_size = kg.count()
        except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
            pass

        # recipe_evaluator · GEPA recipe count (best-effort)
        recipes_count = 0
        try:
            from runtime.core.cerebrum.react_loop import (
                get_react_variant_stats,
            )

            recipes_count = len(get_react_variant_stats())
        except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
            pass

        return {
            "skill_forge": {
                "status": "ready" if forged_count else "idle",
                "forged_count": forged_count,
            },
            "rule_extractor": {
                "status": "ready" if rules_count else "idle",
                "rules_count": rules_count,
                "failure_trajectories": traj_failures,
            },
            "memory_consolidator": {
                "status": "ready" if memories_count else "idle",
                "memories_count": memories_count,
                "trajectories_scanned": traj_total,
            },
            "kg_updater": {
                "status": "ready" if kg_size else "idle",
                "triple_count": kg_size,
            },
            "workflow_rewriter": {
                "status": "ready" if traj_total >= 5 else "warming",
                "trajectories_scanned": traj_total,
            },
            "recipe_evaluator": {
                "status": "ready" if recipes_count else "idle",
                "recipes_tracked": recipes_count,
            },
            "trajectories": {
                "total": traj_total,
                "failures": traj_failures,
                "by_strategy": traj_by_strategy,
            },
        }

    # ─── /api/budget/summary · per-task cost roll-up ────────
    @router.get("/api/budget/summary")
    def api_budget_summary(
        limit: int = Query(default=20, ge=1, le=200),
    ) -> dict[str, Any]:
        """Aggregate cost across recent tasks.

        Reads ``budget_commit`` events from the journal, groups by
        ``task_id``, sums ``tokens_in + tokens_out`` and ``usd``.
        Returns the latest ``limit`` tasks (most recent first) plus
        a grand total. Cheap enough for a 2s heartbeat.
        """
        per_task: dict[str, dict[str, Any]] = {}
        total_tokens = 0
        total_usd = 0.0
        commit_count = 0
        try:
            for ev in journal.read_by_type("budget_commit"):
                commit_count += 1
                tid = str(ev.task_id) if ev.task_id else "(unbound)"
                cost = getattr(ev, "cost", None)
                tokens = 0
                usd = 0.0
                if cost is not None:
                    tokens = int(getattr(cost, "tokens_in", 0) + getattr(cost, "tokens_out", 0))
                    usd = float(getattr(cost, "usd", 0.0))
                entry = per_task.setdefault(
                    tid,
                    {
                        "task_id": tid,
                        "tokens": 0,
                        "usd": 0.0,
                        "commit_count": 0,
                        "last_ts": None,
                    },
                )
                entry["tokens"] += tokens
                entry["usd"] = round(entry["usd"] + usd, 6)
                entry["commit_count"] += 1
                entry["last_ts"] = ev.ts.isoformat() if ev.ts else None
                total_tokens += tokens
                total_usd += usd
        except (OSError, ImportError, AttributeError):  # noqa: BLE001 — observability metric source unavailable; skip
            pass

        # Sort by last_ts DESC · missing goes last
        tasks = sorted(
            per_task.values(),
            key=lambda x: x["last_ts"] or "",
            reverse=True,
        )[:limit]
        return {
            "total_tokens": total_tokens,
            "total_usd": round(total_usd, 6),
            "commit_count": commit_count,
            "task_count": len(per_task),
            "tasks": tasks,
        }

    # ─── /api/run (probe) ───────────────────────────────────
    @router.post("/api/run")
    def api_run(body: dict[str, Any]) -> dict[str, Any]:
        from runtime.core.cerebrum import StaticPlanner
        from runtime.core.cerebrum.planner import Rule
        from runtime.core.graph_runtime import GraphRuntime
        from runtime.execution.tool_engine import ToolExecutor
        from runtime.platform.models import (
            ArmId,
            Budget,
            BudgetLimits,
            BudgetSpec,
            ParsedIntent,
            SkillId,
        )
        from runtime.safety.auth import TrustEngine

        goal = str(body.get("goal", "")).strip()
        if not goal:
            raise HTTPException(400, "goal required")

        immunity = TrustEngine(trusted_sources=["skill://public/*"])
        executor = ToolExecutor(
            registry=registry,
            immunity=immunity,
            journal=journal,
        )
        runtime = GraphRuntime(executor=executor, journal=journal)
        planner = StaticPlanner(
            rules=[
                Rule(
                    name="ui_probe",
                    intent_types=["task"],
                    skill_sequence=[SkillId("list_cwd")],
                ),
            ],
            default_budget=BudgetSpec(tokens=10_000, usd=0.10),
            fallback_skill=SkillId("list_cwd"),
        )

        intent = ParsedIntent(
            raw=goal,
            intent_type="task",
            normalized_goal=goal,
        )
        graph = planner.plan(intent)
        budget = Budget(
            task_id=graph.task_id,
            limits=BudgetLimits(tokens=10_000, usd=0.10),
        )
        traj = runtime.run(
            graph,
            budget=budget,
            caller="arms/ui",
            arm_id=ArmId("ui_arm"),
        )
        return {
            "success": traj.outcome.success,
            "steps": traj.step_count,
            "tokens_spent": budget.tokens_spent,
            "usd_spent": round(budget.usd_spent, 6),
        }

    return router


__all__ = ["create_observability_router"]
