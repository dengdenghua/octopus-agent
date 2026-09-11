"""Durable phase authorization and provider-reported project spending."""

import hashlib
import json
import math

from runtime.projectos._store_project_deletion import assert_project_not_deleting


def phase_fingerprint(ms):
    return hashlib.sha256(
        json.dumps(
            {
                "id": ms.id,
                "name": ms.name,
                "goal": ms.goal,
                "spec": {**ms.spec, "phase_agents": sorted(ms.spec.get("phase_agents", []))},
                "success_criteria": ms.success_criteria,
                "dependencies": sorted(ms.dependencies),
                "planned_start": ms.planned_start,
                "due_at": ms.due_at,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


def phase_authorized(store, project_id, ms):
    if "phase_agents" not in ms.spec:
        return True
    return any(
        e["kind"] == "project.phase_authorized"
        and e["payload"].get("fingerprint") == phase_fingerprint(ms)
        for e in store.events_for_project(project_id, limit=500)
    )


def record_usage(store, project_id, result, *, task_id="", milestone_id=""):
    usage = result.get("governance") or {}
    if not isinstance(usage, dict):
        usage = {}
    root = usage.get("root_id")
    root = root.strip() if isinstance(root, str) else ""
    if root == "__unreported__":
        root = ""
    value = usage.get("cost_usd")
    valid = bool(root) and type(value) in (int, float) and math.isfinite(value) and value >= 0
    # The provider returns a cumulative root snapshot. Keep the maximum, not
    # a sum of repeated snapshots, so retries and parallel callbacks are safe.
    with store._lock, store._conn() as conn:
        conn.execute("BEGIN IMMEDIATE")
        assert_project_not_deleting(conn, project_id)
        if store._project_doc_for_scope(conn, project_id, None) is None:
            raise PermissionError("project usage scope unavailable")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS project_reported_usage (project_id TEXT, root_id TEXT, cost REAL NOT NULL, PRIMARY KEY(project_id, root_id))"
        )
        conn.execute(
            "CREATE TABLE IF NOT EXISTS project_missing_usage (project_id TEXT, root_id TEXT, task_id TEXT, PRIMARY KEY(project_id, root_id, task_id))"
        )
        if valid:
            conn.execute(
                "INSERT INTO project_reported_usage VALUES (?,?,?) ON CONFLICT(project_id,root_id) DO UPDATE SET cost=MAX(cost,excluded.cost)",
                (project_id, root, float(value)),
            )
            # A fresh provider snapshot only resolves this execution. It must
            # never clear another member's receipt or uncorrelated legacy gaps.
            conn.execute("DELETE FROM project_missing_usage WHERE project_id=? AND root_id=?", (project_id, root))
        else:
            conn.execute("INSERT OR IGNORE INTO project_missing_usage VALUES (?,?,?)",
                         (project_id, root or "__unreported__", task_id))
    store.append_event(project_id, kind="project.usage_reported" if valid else "project.usage_missing",
                       payload={"task_id": task_id, "milestone_id": milestone_id,
                                "root_id": root or None,
                                "cost_usd": float(value) if valid else None})
    return valid


def reported_cost(store, project_id):
    with store._lock, store._conn() as conn:
        if store._project_doc_for_scope(conn, project_id, None) is None:
            raise PermissionError("project usage scope unavailable")
        if not conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='project_reported_usage'"
        ).fetchone():
            return 0.0
        return float(
            conn.execute(
                "SELECT COALESCE(SUM(cost),0) FROM project_reported_usage WHERE project_id=?",
                (project_id,),
            ).fetchone()[0]
        )


def budget_reached(store, project_id, ms):
    return budget_status(store, project_id, ms)["paused"]


def budget_status(store, project_id, ms):
    """Read-only explanation shared by execution and the project workbench."""
    cap = ms.spec.get("ai_budget_usd")
    if cap is None:
        return {"paused": False, "reason": None, "limit_usd": None}
    cost = reported_cost(store, project_id)
    with store._lock, store._conn() as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='project_reported_usage'"
        ).fetchone()
        legacy_unknown = (
            exists
            and conn.execute(
                "SELECT 1 FROM project_reported_usage WHERE project_id=? AND root_id='__unreported__'",
                (project_id,),
            ).fetchone()
        )
        missing_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='project_missing_usage'"
        ).fetchone()
        missing = conn.execute(
            "SELECT task_id FROM project_missing_usage WHERE project_id=?", (project_id,)
        ).fetchall() if missing_exists else []
    unknown = legacy_unknown or missing
    reason = "usage_missing" if unknown else "limit_reached" if cost >= float(cap) else None
    missing_tasks = {row[0] for row in missing if row[0]}
    if legacy_unknown:
        missing_tasks.update(e["payload"]["task_id"] for e in store.events_for_project(project_id, limit=500)
                             if e["kind"] == "project.usage_missing" and e["payload"].get("task_id"))
    missing_tasks = sorted(missing_tasks)
    return {"paused": reason is not None, "reason": reason, "missing_task_ids": missing_tasks,
            "reported_cost_usd": cost, "limit_usd": float(cap)}


def budget_pause_message(status):
    if status.get("reason") == "usage_missing":
        tasks = status.get("missing_task_ids") or []
        return "费用回报缺失，无法确认剩余额度；请核对执行记录与费用回报。提高预算不能解除此暂停。" + (
            "待核对任务：" + "、".join(tasks) if tasks else "历史记录未关联具体任务，需核对本项目执行记录。"
        )
    return "已上报费用达到预算上限；可申请调整预算，经批准后继续。"
