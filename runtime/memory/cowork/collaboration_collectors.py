"""Durable fan-out result collectors for multi-agent collaboration runs.

Workers may finish on different processes, and the coordinator may restart
between dispatch and synthesis.  A collector therefore stores each child
outcome independently, applies the completion policy transactionally, and
keeps terminal settlement immutable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from runtime.memory.cowork.ids import normalize_actor_id, require_cowork_id

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
    updated_at          TEXT NOT NULL,
    archived_at         TEXT,
    archive_json        TEXT NOT NULL DEFAULT '{}'
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
ON collaboration_collector_results(run_id, ordinal);

CREATE TABLE IF NOT EXISTS collaboration_collector_retry_tasks (
    task_id    TEXT PRIMARY KEY,
    run_id     TEXT NOT NULL,
    child_id   TEXT NOT NULL,
    generation INTEGER NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_collector_retry_tasks_run
ON collaboration_collector_retry_tasks(run_id, generation);

CREATE TABLE IF NOT EXISTS collaboration_collector_steering (
    run_id       TEXT NOT NULL,
    child_id     TEXT NOT NULL,
    generation   INTEGER NOT NULL,
    seq          INTEGER NOT NULL,
    text         TEXT NOT NULL,
    actor_id     TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, child_id, generation, seq)
);
CREATE INDEX IF NOT EXISTS idx_collab_collector_steering_run
ON collaboration_collector_steering(run_id, child_id, generation, seq);
"""

_COLLECTOR_SCHEMA = "octopus.collaboration_collector.v1"
_CHILD_SCHEMA = "octopus.collaboration_collector_child.v1"
_POLICIES = frozenset({"all", "first_completed", "first_success", "quorum"})
_CHILD_STATUSES = frozenset({"success", "failed", "cancelled"})
_TERMINAL = frozenset({"completed", "failed", "cancelled"})
_MAX_CHILDREN = 512
_MAX_CHILD_RESULT_BYTES = 64 * 1024
_MAX_COLLECTOR_RESULT_BYTES = 4 * 1024 * 1024
_MAX_STEERING_TEXT_LENGTH = 20_000


class CollaborationSteeringConflictError(ValueError):
    """A member result was produced before the newest accepted correction."""


def ensure_collaboration_collector_schema(conn: Any) -> None:
    """Apply the additive/rebuild migration for pre-attempt collectors."""

    collector_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(collaboration_collectors)")
    }
    if "retry_json" not in collector_columns:
        conn.execute(
            "ALTER TABLE collaboration_collectors ADD COLUMN retry_json TEXT NOT NULL DEFAULT '[]'"
        )
    if "generation" not in collector_columns:
        conn.execute(
            "ALTER TABLE collaboration_collectors ADD COLUMN generation INTEGER NOT NULL DEFAULT 1"
        )
    if "archived_at" not in collector_columns:
        conn.execute("ALTER TABLE collaboration_collectors ADD COLUMN archived_at TEXT")
    if "archive_json" not in collector_columns:
        conn.execute(
            "ALTER TABLE collaboration_collectors "
            "ADD COLUMN archive_json TEXT NOT NULL DEFAULT '{}'"
        )
    result_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(collaboration_collector_results)")
    }
    if result_columns and "attempt" not in result_columns:
        conn.execute(
            "ALTER TABLE collaboration_collector_results "
            "RENAME TO collaboration_collector_results_v1"
        )
        conn.execute(
            "CREATE TABLE collaboration_collector_results ("
            "run_id TEXT NOT NULL,child_id TEXT NOT NULL,"
            "attempt INTEGER NOT NULL DEFAULT 1,ordinal INTEGER NOT NULL,"
            "status TEXT NOT NULL,result_json TEXT NOT NULL,result_sha256 TEXT NOT NULL,"
            "completed_at TEXT NOT NULL,PRIMARY KEY (run_id,child_id,attempt))"
        )
        conn.execute(
            "INSERT INTO collaboration_collector_results"
            "(run_id,child_id,attempt,ordinal,status,result_json,result_sha256,completed_at) "
            "SELECT run_id,child_id,1,ordinal,status,result_json,result_sha256,completed_at "
            "FROM collaboration_collector_results_v1"
        )
        conn.execute("DROP TABLE collaboration_collector_results_v1")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_collab_collector_results_run "
            "ON collaboration_collector_results(run_id,ordinal)"
        )


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
        dict.fromkeys(
            require_cowork_id(child_id, label="collector child_id") for child_id in child_ids
        )
    )
    if not children:
        raise ValueError("collector requires at least one child")
    if len(children) > _MAX_CHILDREN:
        raise ValueError(f"collector supports at most {_MAX_CHILDREN} children")
    return children


def _normalize_steering_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError("steering text is required")
    if len(text) > _MAX_STEERING_TEXT_LENGTH:
        raise ValueError(f"steering text must be at most {_MAX_STEERING_TEXT_LENGTH} characters")
    if any((ord(char) < 32 and char not in "\n\r\t") or ord(char) == 127 for char in text):
        raise ValueError("steering text contains unsupported control characters")
    return text


def _effective_results(
    results: list[dict[str, Any]],
    *,
    retrying: list[str],
    generation: int,
) -> list[dict[str, Any]]:
    retry_set = set(retrying)
    return [
        result
        for result in results
        if result["child_id"] not in retry_set or int(result.get("attempt") or 1) >= generation
    ]


def _collector_from_row(row: tuple[Any, ...], results: list[dict[str, Any]]) -> dict[str, Any]:
    archived_at = str(row[13]) if len(row) > 13 and row[13] else None
    if archived_at:
        archive = _load_object(row[14] if len(row) > 14 else "{}")
        archived = archive.get("snapshot")
        archived = dict(archived) if isinstance(archived, dict) else {}
        archived.update(
            {
                "schema": _COLLECTOR_SCHEMA,
                "run_id": str(row[0]),
                "revision": int(row[9]),
                "updated_at": str(row[12]),
                "archived": True,
                "archived_at": archived_at,
            }
        )
        return archived
    expected = _load_list(row[3])
    cancelled = _load_list(row[4])
    retrying = _load_list(row[5])
    generation = int(row[8])
    effective = _effective_results(results, retrying=retrying, generation=generation)
    successes = sum(1 for result in effective if result["status"] == "success")
    failures = sum(1 for result in effective if result["status"] == "failed")
    child_cancelled = sum(1 for result in effective if result["status"] == "cancelled")
    completed = len(effective)
    completed_ids = {str(result["child_id"]) for result in effective}
    remaining = [child_id for child_id in expected if child_id not in completed_ids]
    retry_set = set(retrying)
    projected_results = [
        {
            **result,
            "pending_retry": (
                result["child_id"] in retry_set and int(result.get("attempt") or 1) < generation
            ),
        }
        for result in results
    ]
    return {
        "schema": _COLLECTOR_SCHEMA,
        "run_id": str(row[0]),
        "completion_policy": str(row[1]),
        "completion_target": int(row[2]),
        "expected_child_ids": expected,
        "expected_count": len(expected),
        "status": str(row[6]),
        "policy_satisfied": bool(row[7]),
        "generation": generation,
        "revision": int(row[9]),
        "created_at": str(row[10]),
        "settled_at": str(row[11]) if row[11] else None,
        "updated_at": str(row[12]),
        "archived": False,
        "archived_at": None,
        "success_count": successes,
        "failure_count": failures,
        "child_cancelled_count": child_cancelled,
        "completed_count": completed,
        "remaining_count": len(remaining),
        "remaining_child_ids": remaining,
        "cancellation_requested_child_ids": cancelled,
        "active_retry_child_ids": retrying,
        "results": projected_results,
    }


_COLLECTOR_COLUMNS = (
    "run_id,completion_policy,completion_target,expected_json,cancelled_json,retry_json,status,"
    "policy_satisfied,generation,revision,created_at,settled_at,updated_at,"
    "archived_at,archive_json"
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
        snapshot = _collector_from_row(row, cls._collector_results(conn, run_id))
        if not snapshot.get("archived"):
            snapshot["attempt_count"] = int(
                conn.execute(
                    "SELECT COUNT(*) FROM collaboration_collector_results WHERE run_id=?",
                    (run_id,),
                ).fetchone()[0]
            )
        return snapshot

    @staticmethod
    def _collector_attempts(conn: Any, run_id: str) -> list[dict[str, Any]]:
        archive_row = conn.execute(
            "SELECT archived_at,archive_json FROM collaboration_collectors WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if archive_row is not None and archive_row[0]:
            archive = _load_object(archive_row[1])
            attempts = archive.get("attempts")
            return (
                [dict(item) for item in attempts if isinstance(item, dict)]
                if isinstance(attempts, list)
                else []
            )
        rows = conn.execute(
            "SELECT child_id,attempt,ordinal,status,result_json,result_sha256,completed_at "
            "FROM collaboration_collector_results WHERE run_id=? ORDER BY ordinal,attempt",
            (run_id,),
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
            raise ValueError(
                "completion_policy must be all | first_completed | first_success | quorum"
            )
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
                payload={
                    "completion_policy": policy,
                    "completion_target": target,
                    "expected_count": len(children),
                },
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

    def collaboration_collector_attempts(self, run_id: str) -> list[dict[str, Any]]:
        run_id = require_cowork_id(run_id, label="run_id")
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            return self._collector_attempts(conn, run_id)

    def submit_collaboration_collector_steering(
        self,
        run_id: str,
        *,
        child_id: str,
        text: str,
        actor_id: str = "user",
    ) -> dict[str, Any]:
        """Persist one ordered correction for an active collector member.

        Delivery is cursor based rather than destructively consumed. A worker
        restart therefore replays the current generation from sequence zero,
        while one live worker advances only its in-memory cursor.
        """

        run_id = require_cowork_id(run_id, label="run_id")
        child_id = require_cowork_id(child_id, label="collector child_id")
        correction = _normalize_steering_text(text)
        actor = normalize_actor_id(actor_id or "user", label="actor_id") or "user"
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            collector = self._collector_snapshot(conn, run_id)
            if collector is None:
                raise KeyError(f"collaboration collector not found: {run_id}")
            if collector.get("archived") or collector.get("status") != "collecting":
                raise ValueError("collaboration collector is not accepting steering")
            if child_id not in collector.get("expected_child_ids", []):
                raise ValueError("child_id is not registered with this collector")
            if child_id not in collector.get("remaining_child_ids", []):
                raise ValueError("collector child has already settled")
            generation = int(collector.get("generation") or 1)
            seq = int(
                conn.execute(
                    "SELECT COALESCE(MAX(seq),0)+1 FROM collaboration_collector_steering "
                    "WHERE run_id=? AND child_id=? AND generation=?",
                    (run_id, child_id, generation),
                ).fetchone()[0]
            )
            conn.execute(
                "INSERT INTO collaboration_collector_steering"
                "(run_id,child_id,generation,seq,text,actor_id,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (run_id, child_id, generation, seq, correction, actor, timestamp),
            )
            conn.execute(
                "UPDATE collaboration_collectors SET revision=revision+1,updated_at=? "
                "WHERE run_id=?",
                (timestamp, run_id),
            )
            run_status_row = conn.execute(
                "SELECT status FROM collaboration_runs WHERE run_id=?",
                (run_id,),
            ).fetchone()
            self._append_run_event(
                conn,
                run_id=run_id,
                event_type="collector_child_steered",
                status=str(run_status_row[0]) if run_status_row else "running",
                payload={
                    "child_id": child_id,
                    "generation": generation,
                    "seq": seq,
                    "actor_id": actor,
                    "text_chars": len(correction),
                    "text_sha256": hashlib.sha256(correction.encode("utf-8")).hexdigest(),
                },
                created_at=timestamp,
            )
            updated = self._collector_snapshot(conn, run_id)
        assert updated is not None
        return {
            "steering": {
                "schema": "octopus.collaboration_steering.v1",
                "run_id": run_id,
                "child_id": child_id,
                "generation": generation,
                "seq": seq,
                "text": correction,
                "actor_id": actor,
                "created_at": timestamp,
            },
            "collector": updated,
        }

    def collaboration_collector_steering(
        self,
        run_id: str,
        *,
        child_id: str | None = None,
        generation: int | None = None,
        after_seq: int = 0,
    ) -> list[dict[str, Any]]:
        """Read an ordered steering stream without consuming durable rows."""

        run_id = require_cowork_id(run_id, label="run_id")
        normalized_child = (
            require_cowork_id(child_id, label="collector child_id") if child_id else None
        )
        try:
            after = max(0, int(after_seq))
        except (TypeError, ValueError):
            after = 0
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            row = conn.execute(
                "SELECT generation,archived_at,archive_json FROM collaboration_collectors "
                "WHERE run_id=?",
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError(f"collaboration collector not found: {run_id}")
            selected_generation = int(generation if generation is not None else row[0])
            if row[1]:
                archived = _load_object(row[2]).get("steering")
                values = (
                    [dict(item) for item in archived if isinstance(item, dict)]
                    if isinstance(archived, list)
                    else []
                )
                return [
                    item
                    for item in values
                    if int(item.get("generation") or 0) == selected_generation
                    and int(item.get("seq") or 0) > after
                    and (normalized_child is None or item.get("child_id") == normalized_child)
                ]
            clauses = ["run_id=?", "generation=?", "seq>?"]
            params: list[Any] = [run_id, selected_generation, after]
            if normalized_child is not None:
                clauses.append("child_id=?")
                params.append(normalized_child)
            rows = conn.execute(
                "SELECT child_id,generation,seq,text,actor_id,created_at "
                "FROM collaboration_collector_steering WHERE "
                + " AND ".join(clauses)
                + " ORDER BY seq,child_id",
                params,
            ).fetchall()
        return [
            {
                "schema": "octopus.collaboration_steering.v1",
                "run_id": run_id,
                "child_id": str(row[0]),
                "generation": int(row[1]),
                "seq": int(row[2]),
                "text": str(row[3]),
                "actor_id": str(row[4]),
                "created_at": str(row[5]),
            }
            for row in rows
        ]

    @staticmethod
    def _archived_result(item: dict[str, Any]) -> dict[str, Any]:
        """Retain audit identity and hashes while dropping provider payloads."""

        return {
            key: value for key, value in item.items() if key not in {"result", "pending_retry"}
        } | {"result": {"archived": True}}

    def _archive_collector_in_connection(
        self,
        conn: Any,
        run_id: str,
        *,
        reason: str,
        timestamp: str,
    ) -> dict[str, Any]:
        current = self._collector_snapshot(conn, run_id)
        if current is None:
            raise KeyError(f"collaboration collector not found: {run_id}")
        if current.get("archived"):
            return current
        if current["status"] not in _TERMINAL:
            raise ValueError("only terminal collaboration collectors can be archived")
        run_status_row = conn.execute(
            "SELECT status FROM collaboration_runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if run_status_row is None:
            raise KeyError(f"collaboration run not found: {run_id}")
        if str(run_status_row[0]) not in {"completed", "failed", "cancelled"}:
            raise ValueError("collector cannot be archived before its parent run is terminal")
        attempts = self._collector_attempts(conn, run_id)
        steering_rows = conn.execute(
            "SELECT child_id,generation,seq,text,actor_id,created_at "
            "FROM collaboration_collector_steering WHERE run_id=? "
            "ORDER BY generation,seq,child_id",
            (run_id,),
        ).fetchall()
        archived_steering = [
            {
                "schema": "octopus.collaboration_steering.v1",
                "run_id": run_id,
                "child_id": str(child_id),
                "generation": int(generation),
                "seq": int(seq),
                "actor_id": str(actor_id),
                "created_at": str(created_at),
                "text_chars": len(str(text)),
                "text_sha256": hashlib.sha256(str(text).encode("utf-8")).hexdigest(),
                "archived": True,
            }
            for child_id, generation, seq, text, actor_id, created_at in steering_rows
        ]
        archived_snapshot = {
            **current,
            "active_retry_child_ids": [],
            "archived": True,
            "archived_at": timestamp,
            "results": [self._archived_result(item) for item in current.get("results") or []],
        }
        archive_payload = {
            "schema": "octopus.collaboration_collector_archive.v1",
            "reason": str(reason or "collector retention policy")[:1000],
            "snapshot": archived_snapshot,
            "attempts": [self._archived_result(item) for item in attempts],
            "steering": archived_steering,
        }
        conn.execute(
            "UPDATE collaboration_collectors SET archived_at=?,archive_json=?,retry_json='[]',"
            "revision=revision+1,updated_at=? WHERE run_id=? AND archived_at IS NULL",
            (timestamp, _dump(archive_payload), timestamp, run_id),
        )
        # The compact archive retains child identity, status, attempt, hash and
        # timestamps, but releases potentially large model bodies and obsolete
        # retry bindings.
        conn.execute("DELETE FROM collaboration_collector_results WHERE run_id=?", (run_id,))
        conn.execute(
            "DELETE FROM collaboration_collector_retry_tasks WHERE run_id=?",
            (run_id,),
        )
        conn.execute("DELETE FROM collaboration_collector_steering WHERE run_id=?", (run_id,))
        self._append_run_event(
            conn,
            run_id=run_id,
            event_type="collector_archived",
            status=str(run_status_row[0]) if run_status_row else str(current["status"]),
            payload={
                "reason": archive_payload["reason"],
                "attempt_count": int(current.get("attempt_count") or 0),
                "result_count": len(current.get("results") or []),
                "steering_count": len(archived_steering),
            },
            created_at=timestamp,
        )
        archived = self._collector_snapshot(conn, run_id)
        assert archived is not None
        return archived

    def archive_collaboration_collectors(
        self,
        run_ids: list[str] | tuple[str, ...],
        *,
        reason: str = "collector archived by user",
    ) -> list[dict[str, Any]]:
        """Compact a batch of terminal collectors in one SQLite transaction."""

        normalized = list(
            dict.fromkeys(require_cowork_id(run_id, label="run_id") for run_id in run_ids)
        )
        if not normalized:
            return []
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            return [
                self._archive_collector_in_connection(
                    conn,
                    run_id,
                    reason=reason,
                    timestamp=timestamp,
                )
                for run_id in normalized
            ]

    def apply_collaboration_collector_retention(
        self,
        *,
        session_id: str | None = None,
        ttl_seconds: int = 90 * 24 * 60 * 60,
        max_collectors_per_session: int = 1000,
    ) -> dict[str, Any]:
        """Archive old terminal collectors by age and per-session count.

        ``0`` disables the corresponding axis. Active collectors are always
        pinned. The operation is idempotent and safe to run at startup or from
        the operations read path.
        """

        session = (
            require_cowork_id(session_id, label="session_id") if session_id is not None else None
        )
        ttl = max(0, int(ttl_seconds))
        cap = max(0, int(max_collectors_per_session))
        if ttl == 0 and cap == 0:
            return {"archived": 0, "run_ids": []}
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=ttl) if ttl else None
        timestamp = now.isoformat()
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            sql = (
                "SELECT c.run_id,r.session_id,c.updated_at "
                "FROM collaboration_collectors c "
                "INNER JOIN collaboration_runs r ON r.run_id=c.run_id "
                "WHERE c.archived_at IS NULL AND c.status IN ('completed','failed','cancelled') "
                "AND r.status IN ('completed','failed','cancelled')"
            )
            params: tuple[Any, ...] = ()
            if session is not None:
                sql += " AND r.session_id=?"
                params = (session,)
            sql += " ORDER BY r.session_id,c.updated_at DESC,c.run_id DESC"
            rows = conn.execute(sql, params).fetchall()
            ranks: dict[str, int] = {}
            selected: list[str] = []
            for run_id, row_session, updated_at in rows:
                session_key = str(row_session)
                rank = ranks.get(session_key, 0)
                ranks[session_key] = rank + 1
                over_cap = cap > 0 and rank >= cap
                expired = False
                if cutoff is not None:
                    try:
                        updated = datetime.fromisoformat(str(updated_at))
                        if updated.tzinfo is None:
                            updated = updated.replace(tzinfo=UTC)
                        expired = updated.astimezone(UTC) <= cutoff
                    except (TypeError, ValueError):
                        expired = False
                if over_cap or expired:
                    selected.append(str(run_id))
            archived = [
                self._archive_collector_in_connection(
                    conn,
                    run_id,
                    reason="collector retention policy",
                    timestamp=timestamp,
                )
                for run_id in selected
            ]
        return {
            "archived": len(archived),
            "run_ids": [str(item["run_id"]) for item in archived],
        }

    def bind_collaboration_collector_retry_task(
        self,
        run_id: str,
        *,
        child_id: str,
        task_id: str,
    ) -> dict[str, Any]:
        """Durably connect a task to an active or next retry generation.

        A terminal collector accepts a pre-binding for its next generation.
        This closes the crash window between reopening the collector and
        making the staged background batch runnable.
        """

        run_id = require_cowork_id(run_id, label="run_id")
        child_id = require_cowork_id(child_id, label="collector child_id")
        task_id = require_cowork_id(task_id, label="task_id")
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            collector = self._collector_snapshot(conn, run_id)
            if collector is None:
                raise KeyError(f"collaboration collector not found: {run_id}")
            if collector.get("archived"):
                raise ValueError("archived collaboration collector cannot be retried")
            if collector["status"] == "collecting":
                if child_id not in collector["active_retry_child_ids"]:
                    raise ValueError("child_id is not active in this collector retry generation")
                generation = int(collector["generation"])
            elif collector["status"] in _TERMINAL:
                retryable = [
                    str(item["child_id"])
                    for item in collector["results"]
                    if item["status"] in {"failed", "cancelled"}
                ]
                retryable.extend(collector["cancellation_requested_child_ids"])
                if child_id not in retryable:
                    raise ValueError("child_id does not have a retryable result")
                generation = int(collector["generation"]) + 1
            else:
                raise ValueError("collector is not accepting retry tasks")
            existing = conn.execute(
                "SELECT run_id,child_id,generation,created_at "
                "FROM collaboration_collector_retry_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
            identity = (run_id, child_id, generation)
            if existing is not None:
                if tuple(existing[:3]) != identity:
                    raise ValueError("task_id already belongs to a different collector retry")
                return {
                    "task_id": task_id,
                    "run_id": str(existing[0]),
                    "child_id": str(existing[1]),
                    "generation": int(existing[2]),
                    "created_at": str(existing[3]),
                }
            occupied = conn.execute(
                "SELECT task_id,created_at FROM collaboration_collector_retry_tasks "
                "WHERE run_id=? AND child_id=? AND generation=? LIMIT 1",
                identity,
            ).fetchone()
            if occupied is not None:
                raise ValueError(f"collector retry lane already has a task: {str(occupied[0])}")
            conn.execute(
                "INSERT INTO collaboration_collector_retry_tasks"
                "(task_id,run_id,child_id,generation,created_at) VALUES (?,?,?,?,?)",
                (task_id, run_id, child_id, generation, timestamp),
            )
        return {
            "task_id": task_id,
            "run_id": run_id,
            "child_id": child_id,
            "generation": generation,
            "created_at": timestamp,
        }

    def collaboration_collector_retry_task(self, task_id: str) -> dict[str, Any] | None:
        task_id = require_cowork_id(task_id, label="task_id")
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            row = conn.execute(
                "SELECT run_id,child_id,generation,created_at "
                "FROM collaboration_collector_retry_tasks WHERE task_id=?",
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "task_id": task_id,
            "run_id": str(row[0]),
            "child_id": str(row[1]),
            "generation": int(row[2]),
            "created_at": str(row[3]),
        }

    def collaboration_collector_retry_tasks(
        self,
        run_id: str,
        *,
        generation: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return durable queue bindings for one collector attempt."""

        run_id = require_cowork_id(run_id, label="run_id")
        params: list[Any] = [run_id]
        sql = (
            "SELECT task_id,child_id,generation,created_at "
            "FROM collaboration_collector_retry_tasks WHERE run_id=?"
        )
        if generation is not None:
            generation = max(1, int(generation))
            sql += " AND generation=?"
            params.append(generation)
        sql += " ORDER BY generation,created_at,task_id"
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [
            {
                "task_id": str(row[0]),
                "run_id": run_id,
                "child_id": str(row[1]),
                "generation": int(row[2]),
                "created_at": str(row[3]),
            }
            for row in rows
        ]

    def discard_collaboration_collector_retry_tasks(
        self,
        task_ids: list[str] | tuple[str, ...],
    ) -> int:
        """Release pre-bindings for a batch that never became runnable."""

        normalized = list(
            dict.fromkeys(require_cowork_id(task_id, label="task_id") for task_id in task_ids)
        )
        if not normalized:
            return 0
        placeholders = ",".join("?" for _ in normalized)
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            deleted = conn.execute(
                "DELETE FROM collaboration_collector_retry_tasks "
                f"WHERE task_id IN ({placeholders})",  # nosec B608 - placeholders only
                normalized,
            ).rowcount
        return int(deleted or 0)

    def reopen_collaboration_collector(
        self,
        run_id: str,
        *,
        child_ids: list[str] | tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        """Open a new attempt for failed or explicitly cancelled children.

        Previous attempts remain append-only. The current snapshot projects
        only the latest attempt per child, so a successful retry replaces a
        failed lane for policy calculation without erasing its audit trail.
        """

        run_id = require_cowork_id(run_id, label="run_id")
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_COLLECTOR_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            current = self._collector_snapshot(conn, run_id)
            if current is None:
                raise KeyError(f"collaboration collector not found: {run_id}")
            if current.get("archived"):
                raise ValueError("archived collaboration collector cannot be reopened")
            if current["status"] not in _TERMINAL:
                raise ValueError("collector must be settled before reopening")
            expected = list(current["expected_child_ids"])
            retryable = [
                str(item["child_id"])
                for item in current["results"]
                if item["status"] in {"failed", "cancelled"}
            ]
            retryable.extend(current["cancellation_requested_child_ids"])
            retryable = list(dict.fromkeys(retryable))
            retrying = retryable if child_ids is None else _normalize_children(child_ids)
            unknown = [child_id for child_id in retrying if child_id not in expected]
            if unknown:
                raise ValueError(f"child_id is not registered with this collector: {unknown[0]}")
            not_retryable = [child_id for child_id in retrying if child_id not in retryable]
            if not_retryable:
                raise ValueError(f"child_id already has a successful result: {not_retryable[0]}")
            if not retrying:
                raise ValueError("collector has no failed or cancelled children to retry")
            generation = int(current["generation"]) + 1
            conn.execute(
                "UPDATE collaboration_collectors SET status='collecting',policy_satisfied=0,"
                "generation=?,revision=revision+1,cancelled_json='[]',retry_json=?,"
                "settled_at=NULL,updated_at=? WHERE run_id=?",
                (generation, _dump(retrying), timestamp, run_id),
            )
            run_status_row = conn.execute(
                "SELECT status FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            self._append_run_event(
                conn,
                run_id=run_id,
                event_type="collector_reopened",
                status=str(run_status_row[0]) if run_status_row else "running",
                payload={"generation": generation, "child_ids": retrying},
                created_at=timestamp,
            )
            snapshot = self._collector_snapshot(conn, run_id)
        assert snapshot is not None
        return snapshot

    def record_collaboration_collector_result(
        self,
        run_id: str,
        *,
        child_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        expected_generation: int | None = None,
        expected_steering_seq: int | None = None,
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
            collector_status = str(collector[6])
            generation = int(collector[8])
            if expected_generation is not None and int(expected_generation) != generation:
                raise ValueError("collector retry task belongs to a stale generation")
            if expected_steering_seq is not None:
                latest_steering_seq = int(
                    conn.execute(
                        "SELECT COALESCE(MAX(seq),0) "
                        "FROM collaboration_collector_steering "
                        "WHERE run_id=? AND child_id=? AND generation=?",
                        (run_id, child_id, generation),
                    ).fetchone()[0]
                )
                if int(expected_steering_seq) != latest_steering_seq:
                    raise CollaborationSteeringConflictError(
                        "collector member result predates accepted steering"
                    )
            existing = conn.execute(
                "SELECT status,result_sha256 FROM collaboration_collector_results "
                "WHERE run_id=? AND child_id=? AND attempt=?",
                (run_id, child_id, generation),
            ).fetchone()
            if existing is not None:
                if (str(existing[0]), str(existing[1])) != (child_status, digest):
                    raise ValueError("collector child result is immutable")
                snapshot = self._collector_snapshot(conn, run_id)
                assert snapshot is not None
                return snapshot
            if collector_status in _TERMINAL:
                latest = conn.execute(
                    "SELECT status,result_sha256 FROM collaboration_collector_results "
                    "WHERE run_id=? AND child_id=? ORDER BY attempt DESC LIMIT 1",
                    (run_id, child_id),
                ).fetchone()
                if latest is not None and (str(latest[0]), str(latest[1])) == (
                    child_status,
                    digest,
                ):
                    snapshot = self._collector_snapshot(conn, run_id)
                    assert snapshot is not None
                    return snapshot
                raise ValueError("collector is already settled")
            retrying = _load_list(collector[5])
            if retrying and child_id not in retrying:
                raise ValueError("child_id is not active in this collector retry generation")
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
                "(run_id,child_id,attempt,ordinal,status,result_json,result_sha256,completed_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    child_id,
                    generation,
                    expected.index(child_id),
                    child_status,
                    result_blob,
                    digest,
                    timestamp,
                ),
            )
            latest_results = self._collector_results(conn, run_id)
            effective_results = _effective_results(
                latest_results,
                retrying=retrying,
                generation=generation,
            )
            success_count = sum(1 for item in effective_results if item["status"] == "success")
            completed_count = len(effective_results)
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
            next_status = (
                "completed" if policy_satisfied else "failed" if impossible else "collecting"
            )
            completed_ids = {str(item["child_id"]) for item in effective_results}
            cancel_ids = (
                [registered for registered in expected if registered not in completed_ids]
                if next_status in _TERMINAL
                else []
            )
            conn.execute(
                "UPDATE collaboration_collectors SET status=?,policy_satisfied=?,"
                "cancelled_json=?,retry_json=?,revision=revision+1,settled_at=?,updated_at=? "
                "WHERE run_id=?",
                (
                    next_status,
                    int(policy_satisfied),
                    _dump(cancel_ids),
                    "[]" if next_status in _TERMINAL else _dump(retrying),
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
                    "attempt": generation,
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


__all__ = [
    "COLLABORATION_COLLECTOR_SCHEMA",
    "CollaborationCollectorStoreMixin",
    "ensure_collaboration_collector_schema",
]
