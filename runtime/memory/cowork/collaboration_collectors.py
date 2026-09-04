"""Durable fan-out result collectors for multi-agent collaboration runs.

Workers may finish on different processes, and the coordinator may restart
between dispatch and synthesis.  A collector therefore stores each child
outcome independently, applies the completion policy transactionally, and
keeps terminal settlement immutable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from runtime.memory.cowork.ids import require_cowork_id

COLLABORATION_COLLECTOR_SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_collectors (
    run_id              TEXT PRIMARY KEY,
    completion_policy   TEXT NOT NULL,
    completion_target   INTEGER NOT NULL,
    expected_json       TEXT NOT NULL,
    cancelled_json      TEXT NOT NULL DEFAULT '[]',
    retry_json          TEXT NOT NULL DEFAULT '[]',
    status              TEXT NOT NULL,
    policy_satisfied    INTEGER NOT NULL DEFAULT 0,
    generation          INTEGER NOT NULL DEFAULT 1,
    revision            INTEGER NOT NULL DEFAULT 1,
    created_at          TEXT NOT NULL,
    settled_at          TEXT,
    updated_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_collectors_status
ON collaboration_collectors(status, updated_at);

CREATE TABLE IF NOT EXISTS collaboration_collector_results (
    run_id       TEXT NOT NULL,
    child_id     TEXT NOT NULL,
    attempt      INTEGER NOT NULL DEFAULT 1,
    ordinal      INTEGER NOT NULL,
    status       TEXT NOT NULL,
    result_json  TEXT NOT NULL,
    result_sha256 TEXT NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (run_id, child_id, attempt)
);
CREATE INDEX IF NOT EXISTS idx_collab_collector_results_run
ON collaboration_collector_results(run_id, ordinal, attempt);
"""

_COLLECTOR_SCHEMA = "octopus.collaboration_collector.v1"
_CHILD_SCHEMA = "octopus.collaboration_collector_child.v1"
_POLICIES = frozenset({"all", "first_completed", "first_success", "quorum"})
_CHILD_STATUSES = frozenset({"success", "failed", "cancelled"})
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_MAX_CHILDREN = 512
_MAX_CHILD_RESULT_BYTES = 64 * 1024
_MAX_COLLECTOR_RESULT_BYTES = 4 * 1024 * 1024


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_object(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _load_list(value: Any) -> list[str]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in decoded] if isinstance(decoded, list) else []


def _normalize_result(value: Any) -> tuple[dict[str, Any], str, str]:
    if value is None:
        payload: dict[str, Any] = {}
    elif isinstance(value, dict):
        payload = value
    else:
        raise ValueError("collector child result must be an object")
    try:
        blob = _dump(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("collector child result must be JSON serializable") from exc
    if len(blob.encode("utf-8")) > _MAX_CHILD_RESULT_BYTES:
        raise ValueError(f"collector child result exceeds {_MAX_CHILD_RESULT_BYTES} bytes")
    normalized = json.loads(blob)
    digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return normalized, blob, digest


def _normalize_children(child_ids: list[str] | tuple[str, ...]) -> list[str]:
    if not isinstance(child_ids, (list, tuple)):
        raise ValueError("child_ids must be a list")
    children = list(
        dict.fromkeys(require_cowork_id(child_id, label="collector child_id") for child_id in child_ids)
    )
    if not children:
        raise ValueError("collector requires at least one child")
    if len(children) > _MAX_CHILDREN:
        raise ValueError(f"collector supports at most {_MAX_CHILDREN} children")
    return children


def _collector_from_row(row: tuple[Any, ...], results: list[dict[str, Any]]) -> dict[str, Any]:
    expected = _load_list(row[3])
    cancelled = _load_list(row[4])
    retrying = _load_list(row[5])
    successes = sum(1 for result in results if result["status"] == "success")
    failures = sum(1 for result in results if result["status"] == "failed")
    child_cancelled = sum(1 for result in results if result["status"] == "cancelled")
    completed = len(results)
    remaining = [child_id for child_id in expected if child_id not in {r["child_id"] for r in results}]
    return {
        "schema": _COLLECTOR_SCHEMA,
        "run_id": str(row[0]),
        "completion_policy": str(row[1]),
        "completion_target": int(row[2]),
        "expected_child_ids": expected,
        "expected_count": len(expected),
        "status": str(row[6]),
        "policy_satisfied": bool(row[7]),
        "generation": int(row[8]),
        "revision": int(row[9]),
        "created_at": str(row[10]),
        "settled_at": str(row[11]) if row[11] else None,
        "updated_at": str(row[12]),
        "success_count": successes,
        "failure_count": failures,
        "child_cancelled_count": child_cancelled,
        "completed_count": completed,
        "remaining_count": len(remaining),
        "remaining_child_ids": remaining,
        "cancellation_requested_child_ids": cancelled,
        "active_retry_child_ids": retrying,
        "results": results,
    }


_COLLECTOR_COLUMNS = (
    "run_id,completion_policy,completion_target,expected_json,cancelled_json,retry_json,status,"
    "policy_satisfied,generation,revision,created_at,settled_at,updated_at"
)


class CollaborationCollectorStoreMixin:
    """SQLite-backed collector mixed into the canonical collaboration store."""

    _lock: Any
    _connect: Any
    _append_run_event: Any

    @staticmethod
    def _collector_results(conn: Any, run_id: str) -> list[dict[str, Any]]:
        rows = conn.execute(
            "SELECT r.child_id,r.attempt,r.ordinal,r.status,r.result_json,r.result_sha256,"
            "r.completed_at FROM collaboration_collector_results r "
            "INNER JOIN (SELECT child_id,MAX(attempt) AS attempt "
            "FROM collaboration_collector_results WHERE run_id=? GROUP BY child_id) latest "
            "ON latest.child_id=r.child_id AND latest.attempt=r.attempt "
            "WHERE r.run_id=? ORDER BY r.ordinal",
            (run_id, run_id),
        ).fetchall()
        return [
            {
                "schema": _CHILD_SCHEMA,
                "child_id": str(child_id),
                "attempt": int(attempt),
                "ordinal": int(ordinal),
                "status": str(status),
                "result": _load_object(result_json),
                "result_sha256": str(result_sha256),
                "completed_at": str(completed_at),
            }
            for child_id, attempt, ordinal, status, result_json, result_sha256, completed_at in rows
        ]

    @classmethod
    def _collector_snapshot(cls, conn: Any, run_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            f"SELECT {_COLLECTOR_COLUMNS} FROM collaboration_collectors WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return _collector_from_row(row, cls._collector_results(conn, run_id))

    def create_collaboration_collector(
        self,
        *,
        run_id: str,
        child_ids: list[str] | tuple[str, ...],
        completion_policy: str = "all",
        quorum: int | None = None,
    ) -> dict[str, Any]:
        run_id = require_cowork_id(run_id, label="run_id")
        children = _normalize_children(child_ids)
        policy = str(completion_policy or "all").strip().lower().replace("-", "_")
        if policy == "first":
            policy = "first_completed"
        if policy not in _POLICIES:
            raise ValueError("completion_policy must be all | first_completed | first_success | quorum")
        if policy == "quorum":
            try:
                target = int(quorum) if quorum is not None else len(children) // 2 + 1
            except (TypeError, ValueError) as exc:
                raise ValueError("quorum must be an integer") from exc
            target = max(1, min(target, len(children)))
        else:
            target = len(children) if policy == "all" else 1
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            run_status_row = conn.execute(
                "SELECT status FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if run_status_row is None:
                raise KeyError(f"collaboration run not found: {run_id}")
            current = self._collector_snapshot(conn, run_id)
            if current is not None:
                identity = (
                    current["completion_policy"],
                    current["completion_target"],
                    current["expected_child_ids"],
                )
                if identity != (policy, target, children):
                    raise ValueError("run_id already belongs to a different collector")
                return current
            conn.execute(
                "INSERT INTO collaboration_collectors"
                "(run_id,completion_policy,completion_target,expected_json,status,created_at,updated_at) "
                "VALUES (?,?,?,?,'collecting',?,?)",
                (run_id, policy, target, _dump(children), timestamp, timestamp),
            )
            self._append_run_event(
                conn,
                run_id=run_id,
                event_type="collector_created",
                status=str(run_status_row[0]),
                payload={"completion_policy": policy, "completion_target": target, "expected_count": len(children)},
                created_at=timestamp,
            )
            snapshot = self._collector_snapshot(conn, run_id)
        assert snapshot is not None
        return snapshot

    def close_collaboration_collector(
        self,
        run_id: str,
        *,
        status: str = "cancelled",
        reason: str = "collector closed before every child completed",
    ) -> dict[str, Any] | None:
        """Settle an incomplete collector when its parent run terminates."""

        run_id = require_cowork_id(run_id, label="run_id")
        target = str(status or "").strip().lower()
        if target not in {"failed", "cancelled"}:
            raise ValueError("collector close status must be failed | cancelled")
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            current = self._collector_snapshot(conn, run_id)
            if current is None or current["status"] in _TERMINAL:
                return current
            cancel_ids = list(current["remaining_child_ids"])
            conn.execute(
                "UPDATE collaboration_collectors SET status=?,policy_satisfied=0,"
                "cancelled_json=?,revision=revision+1,settled_at=?,updated_at=? WHERE run_id=?",
                (target, _dump(cancel_ids), timestamp, timestamp, run_id),
            )
            run_status_row = conn.execute(
                "SELECT status FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            self._append_run_event(
                conn,
                run_id=run_id,
                event_type="collector_closed",
                status=str(run_status_row[0]) if run_status_row else target,
                payload={
                    "collector_status": target,
                    "reason": str(reason or "")[:1000],
                    "cancellation_requested_count": len(cancel_ids),
                },
                created_at=timestamp,
            )
            snapshot = self._collector_snapshot(conn, run_id)
        assert snapshot is not None
        return snapshot

    def collaboration_collector(self, run_id: str) -> dict[str, Any] | None:
        run_id = require_cowork_id(run_id, label="run_id")
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            return self._collector_snapshot(conn, run_id)

    def record_collaboration_collector_result(
        self,
        run_id: str,
        *,
        child_id: str,
        status: str,
        result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = require_cowork_id(run_id, label="run_id")
        child_id = require_cowork_id(child_id, label="collector child_id")
        child_status = str(status or "").strip().lower()
        if child_status not in _CHILD_STATUSES:
            raise ValueError("collector child status must be success | failed | cancelled")
        _payload, result_blob, digest = _normalize_result(result)
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            # Serialize policy settlement across independent worker processes,
            # not merely threads sharing one CollaborationStore instance.
            conn.execute("BEGIN IMMEDIATE")
            collector = conn.execute(
                f"SELECT {_COLLECTOR_COLUMNS} FROM collaboration_collectors WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if collector is None:
                raise KeyError(f"collaboration collector not found: {run_id}")
            expected = _load_list(collector[3])
            if child_id not in expected:
                raise ValueError("child_id is not registered with this collector")
            existing = conn.execute(
                "SELECT status,result_sha256 FROM collaboration_collector_results "
                "WHERE run_id=? AND child_id=?",
                (run_id, child_id),
            ).fetchone()
            if existing is not None:
                if (str(existing[0]), str(existing[1])) != (child_status, digest):
                    raise ValueError("collector child result is immutable")
                snapshot = self._collector_snapshot(conn, run_id)
                assert snapshot is not None
                return snapshot
            if str(collector[5]) in _TERMINAL:
                raise ValueError("collector is already settled")
            stored_bytes = int(
                conn.execute(
                    "SELECT COALESCE(SUM(length(CAST(result_json AS BLOB))),0) "
                    "FROM collaboration_collector_results WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
            )
            if stored_bytes + len(result_blob.encode("utf-8")) > _MAX_COLLECTOR_RESULT_BYTES:
                raise ValueError("collector aggregate results exceed 4194304 bytes")
            conn.execute(
                "INSERT INTO collaboration_collector_results"
                "(run_id,child_id,ordinal,status,result_json,result_sha256,completed_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (run_id, child_id, expected.index(child_id), child_status, result_blob, digest, timestamp),
            )
            counts = dict(
                conn.execute(
                    "SELECT status,COUNT(*) FROM collaboration_collector_results "
                    "WHERE run_id=? GROUP BY status",
                    (run_id,),
                ).fetchall()
            )
            success_count = int(counts.get("success", 0))
            completed_count = sum(int(value) for value in counts.values())
            remaining_count = len(expected) - completed_count
            policy = str(collector[1])
            target = int(collector[2])
            policy_satisfied = False
            impossible = False
            if policy == "all":
                policy_satisfied = remaining_count == 0
            elif policy == "first_completed":
                policy_satisfied = completed_count >= 1
            elif policy == "first_success":
                policy_satisfied = success_count >= 1
                impossible = remaining_count == 0 and not policy_satisfied
            else:
                policy_satisfied = success_count >= target
                impossible = success_count + remaining_count < target
            next_status = "completed" if policy_satisfied else "failed" if impossible else "collecting"
            completed_ids = {
                str(row[0])
                for row in conn.execute(
                    "SELECT child_id FROM collaboration_collector_results WHERE run_id=?",
                    (run_id,),
                ).fetchall()
            }
            cancel_ids = (
                [registered for registered in expected if registered not in completed_ids]
                if next_status in _TERMINAL
                else []
            )
            conn.execute(
                "UPDATE collaboration_collectors SET status=?,policy_satisfied=?,"
                "cancelled_json=?,revision=revision+1,settled_at=?,updated_at=? WHERE run_id=?",
                (
                    next_status,
                    int(policy_satisfied),
                    _dump(cancel_ids),
                    timestamp if next_status in _TERMINAL else None,
                    timestamp,
                    run_id,
                ),
            )
            run_status_row = conn.execute(
                "SELECT status FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            self._append_run_event(
                conn,
                run_id=run_id,
                event_type="collector_child_recorded",
                status=str(run_status_row[0]) if run_status_row else "running",
                payload={
                    "child_id": child_id,
                    "child_status": child_status,
                    "result_sha256": digest,
                    "completed_count": completed_count,
                    "success_count": success_count,
                    "collector_status": next_status,
                    "policy_satisfied": policy_satisfied,
                    "cancellation_requested_count": len(cancel_ids),
                },
                created_at=timestamp,
            )
            snapshot = self._collector_snapshot(conn, run_id)
        assert snapshot is not None
        return snapshot


__all__ = ["COLLABORATION_COLLECTOR_SCHEMA", "CollaborationCollectorStoreMixin"]
