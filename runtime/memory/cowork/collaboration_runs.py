"""Durable lifecycle ledger for every multi-agent collaboration run.

The room/task read model is not sufficient for execution recovery: a process
may stop after dispatch but before the final UI item is written.  This mixin
stores an append-only lifecycle next to the canonical collaboration database,
with leases for safe reclaim and hashes for idempotent terminal delivery.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from runtime.memory.cowork.ids import optional_cowork_id, require_cowork_id

COLLABORATION_RUN_SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_runs (
    run_id          TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    room_id         TEXT NOT NULL DEFAULT '',
    turn_id         TEXT NOT NULL DEFAULT '',
    parent_run_id   TEXT NOT NULL DEFAULT '',
    kind            TEXT NOT NULL,
    status          TEXT NOT NULL,
    attempt         INTEGER NOT NULL DEFAULT 0,
    version         INTEGER NOT NULL DEFAULT 1,
    input_json      TEXT NOT NULL DEFAULT '{}',
    result_json     TEXT,
    result_sha256   TEXT,
    error           TEXT,
    lease_owner     TEXT,
    lease_expires_at TEXT,
    created_at      TEXT NOT NULL,
    started_at      TEXT,
    completed_at    TEXT,
    updated_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_collab_runs_session
ON collaboration_runs(session_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_collab_runs_recovery
ON collaboration_runs(status, lease_expires_at, updated_at);

CREATE TABLE IF NOT EXISTS collaboration_run_events (
    run_id       TEXT NOT NULL,
    seq          INTEGER NOT NULL,
    event_type   TEXT NOT NULL,
    status       TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at   TEXT NOT NULL,
    PRIMARY KEY (run_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_collab_run_events_run
ON collaboration_run_events(run_id, seq);
"""

_RUN_SCHEMA = "octopus.collaboration_run.v1"
_EVENT_SCHEMA = "octopus.collaboration_run_event.v1"
_RUN_STATUSES = frozenset(
    {"queued", "running", "waiting", "completed", "failed", "cancelled", "interrupted"}
)
_TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
_LEGAL_TRANSITIONS = {
    "queued": frozenset({"running", "failed", "cancelled", "interrupted"}),
    "running": frozenset({"waiting", "completed", "failed", "cancelled", "interrupted"}),
    "waiting": frozenset({"running", "completed", "failed", "cancelled", "interrupted"}),
    "interrupted": frozenset({"queued", "running", "failed", "cancelled"}),
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _json_dict(value: Any, *, label: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > 512 * 1024:
        raise ValueError(f"{label} exceeds 524288 bytes")
    decoded = json.loads(encoded)
    return decoded if isinstance(decoded, dict) else {}


def _dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _result_hash(result: dict[str, Any]) -> str:
    return hashlib.sha256(_dump(result).encode("utf-8")).hexdigest()


def _run_from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "schema": _RUN_SCHEMA,
        "run_id": str(row[0]),
        "session_id": str(row[1]),
        "room_id": str(row[2] or ""),
        "turn_id": str(row[3] or ""),
        "parent_run_id": str(row[4] or ""),
        "kind": str(row[5]),
        "status": str(row[6]),
        "attempt": int(row[7]),
        "version": int(row[8]),
        "input": _load(row[9]) or {},
        "result": _load(row[10]),
        "result_sha256": str(row[11]) if row[11] else None,
        "error": str(row[12]) if row[12] else None,
        "lease_owner": str(row[13]) if row[13] else None,
        "lease_expires_at": str(row[14]) if row[14] else None,
        "created_at": str(row[15]),
        "started_at": str(row[16]) if row[16] else None,
        "completed_at": str(row[17]) if row[17] else None,
        "updated_at": str(row[18]),
    }


_RUN_COLUMNS = (
    "run_id,session_id,room_id,turn_id,parent_run_id,kind,status,attempt,version,"
    "input_json,result_json,result_sha256,error,lease_owner,lease_expires_at,"
    "created_at,started_at,completed_at,updated_at"
)


class CollaborationRunStoreMixin:
    """Mixin implemented by :class:`CollaborationStore`.

    The host must provide ``_lock`` and ``_connect()``.  Every mutating method
    writes its event in the same SQLite transaction as the run snapshot.
    """

    _lock: Any
    _connect: Any

    @staticmethod
    def _append_run_event(
        conn: Any,
        *,
        run_id: str,
        event_type: str,
        status: str,
        payload: dict[str, Any] | None = None,
        created_at: str,
    ) -> None:
        next_seq = int(
            conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM collaboration_run_events WHERE run_id=?",
                (run_id,),
            ).fetchone()[0]
        )
        conn.execute(
            "INSERT INTO collaboration_run_events"
            "(run_id,seq,event_type,status,payload_json,created_at) VALUES (?,?,?,?,?,?)",
            (run_id, next_seq, event_type, status, _dump(payload or {}), created_at),
        )

    def create_collaboration_run(
        self,
        *,
        run_id: str,
        session_id: str,
        kind: str,
        room_id: str = "",
        turn_id: str = "",
        parent_run_id: str = "",
        input: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = require_cowork_id(run_id, label="run_id")
        session_id = require_cowork_id(session_id, label="session_id")
        room_id = optional_cowork_id(room_id, label="room_id")
        turn_id = optional_cowork_id(turn_id, label="turn_id")
        parent_run_id = optional_cowork_id(parent_run_id, label="parent_run_id")
        kind = require_cowork_id(kind, label="run kind").lower()
        input_payload = _json_dict(input, label="run input")
        timestamp = _iso(_now())
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if row:
                current = _run_from_row(row)
                identity = (session_id, room_id, turn_id, parent_run_id, kind)
                existing_identity = tuple(
                    str(current[key])
                    for key in ("session_id", "room_id", "turn_id", "parent_run_id", "kind")
                )
                if identity != existing_identity:
                    raise ValueError("run_id already belongs to a different collaboration run")
                return current
            conn.execute(
                "INSERT INTO collaboration_runs"
                "(run_id,session_id,room_id,turn_id,parent_run_id,kind,status,input_json,"
                "created_at,updated_at) VALUES (?,?,?,?,?,?,'queued',?,?,?)",
                (
                    run_id,
                    session_id,
                    room_id,
                    turn_id,
                    parent_run_id,
                    kind,
                    _dump(input_payload),
                    timestamp,
                    timestamp,
                ),
            )
            self._append_run_event(
                conn,
                run_id=run_id,
                event_type="created",
                status="queued",
                payload={"kind": kind},
                created_at=timestamp,
            )
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return _run_from_row(row)

    def collaboration_run(self, run_id: str) -> dict[str, Any] | None:
        run_id = require_cowork_id(run_id, label="run_id")
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return _run_from_row(row) if row else None

    def collaboration_run_events(self, run_id: str) -> list[dict[str, Any]]:
        run_id = require_cowork_id(run_id, label="run_id")
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            rows = conn.execute(
                "SELECT seq,event_type,status,payload_json,created_at "
                "FROM collaboration_run_events WHERE run_id=? ORDER BY seq",
                (run_id,),
            ).fetchall()
        return [
            {
                "schema": _EVENT_SCHEMA,
                "run_id": run_id,
                "seq": int(seq),
                "event_type": str(event_type),
                "status": str(status),
                "payload": _load(payload_json) or {},
                "created_at": str(created_at),
            }
            for seq, event_type, status, payload_json, created_at in rows
        ]

    def collaboration_runs_for_session(
        self,
        session_id: str,
        *,
        statuses: list[str] | tuple[str, ...] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        session_id = require_cowork_id(session_id, label="session_id")
        normalized_statuses = tuple(
            dict.fromkeys(str(status or "").strip().lower() for status in (statuses or ()))
        )
        invalid = [status for status in normalized_statuses if status not in _RUN_STATUSES]
        if invalid:
            raise ValueError(f"invalid collaboration run status: {invalid[0]}")
        limit = max(1, min(int(limit), 1000))
        sql = f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE session_id=?"
        params: list[Any] = [session_id]
        if normalized_statuses:
            placeholders = ",".join("?" for _ in normalized_statuses)
            sql += f" AND status IN ({placeholders})"
            params.extend(normalized_statuses)
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_run_from_row(row) for row in rows]

    def claim_collaboration_run(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> dict[str, Any]:
        run_id = require_cowork_id(run_id, label="run_id")
        worker_id = require_cowork_id(worker_id, label="worker_id")
        lease_seconds = max(5, min(int(lease_seconds), 3600))
        now = _now()
        timestamp = _iso(now)
        expires = _iso(now + timedelta(seconds=lease_seconds))
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"collaboration run not found: {run_id}")
            current = _run_from_row(row)
            status = str(current["status"])
            if status in _TERMINAL_STATUSES:
                raise ValueError(f"cannot claim terminal collaboration run: {status}")
            lease_expiry = str(current.get("lease_expires_at") or "")
            lease_live = status == "running" and lease_expiry > timestamp
            if lease_live:
                if current.get("lease_owner") != worker_id:
                    raise RuntimeError("collaboration run is leased by another worker")
                # Retries from one live worker are idempotent and do not count
                # as a new execution attempt.
                return current
            event_type = "reclaimed" if status in {"running", "interrupted"} else "claimed"
            conn.execute(
                "UPDATE collaboration_runs SET status='running',attempt=attempt+1,version=version+1,"
                "lease_owner=?,lease_expires_at=?,started_at=COALESCE(started_at,?),updated_at=? "
                "WHERE run_id=?",
                (worker_id, expires, timestamp, timestamp, run_id),
            )
            self._append_run_event(
                conn,
                run_id=run_id,
                event_type=event_type,
                status="running",
                payload={"worker_id": worker_id, "lease_expires_at": expires},
                created_at=timestamp,
            )
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return _run_from_row(row)

    def heartbeat_collaboration_run(
        self,
        run_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 120,
    ) -> dict[str, Any]:
        run_id = require_cowork_id(run_id, label="run_id")
        worker_id = require_cowork_id(worker_id, label="worker_id")
        lease_seconds = max(5, min(int(lease_seconds), 3600))
        timestamp = _iso(_now())
        expires = _iso(_now() + timedelta(seconds=lease_seconds))
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            changed = conn.execute(
                "UPDATE collaboration_runs SET lease_expires_at=?,updated_at=?,version=version+1 "
                "WHERE run_id=? AND status='running' AND lease_owner=?",
                (expires, timestamp, run_id, worker_id),
            ).rowcount
            if changed != 1:
                raise RuntimeError("collaboration run lease is not owned by this worker")
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return _run_from_row(row)

    def transition_collaboration_run(
        self,
        run_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
        worker_id: str | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        run_id = require_cowork_id(run_id, label="run_id")
        target = str(status or "").strip().lower()
        if target not in _RUN_STATUSES:
            raise ValueError(f"invalid collaboration run status: {target}")
        worker = optional_cowork_id(worker_id, label="worker_id")
        result_payload = _json_dict(result, label="run result") if result is not None else None
        result_blob = _dump(result_payload) if result_payload is not None else None
        result_sha256 = _result_hash(result_payload) if result_payload is not None else None
        event_payload = _json_dict(payload, label="run event payload")
        timestamp = _iso(_now())
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
            if not row:
                raise KeyError(f"collaboration run not found: {run_id}")
            current = _run_from_row(row)
            current_status = str(current["status"])
            if current_status == target and current_status in _TERMINAL_STATUSES:
                if target == "completed" and current.get("result_sha256") != result_sha256:
                    raise ValueError("completed collaboration run result is immutable")
                return current
            if target not in _LEGAL_TRANSITIONS[current_status]:
                raise ValueError(
                    f"illegal collaboration run transition: {current_status} -> {target}"
                )
            if worker and current.get("lease_owner") not in {None, worker}:
                raise RuntimeError("collaboration run is leased by another worker")
            completed_at = timestamp if target in _TERMINAL_STATUSES else None
            clear_lease = target in _TERMINAL_STATUSES or target in {"waiting", "interrupted"}
            conn.execute(
                "UPDATE collaboration_runs SET status=?,version=version+1,result_json=?,"
                "result_sha256=?,error=?,lease_owner=?,lease_expires_at=?,completed_at=?,updated_at=? "
                "WHERE run_id=?",
                (
                    target,
                    result_blob if result_blob is not None else row[10],
                    result_sha256 if result_sha256 is not None else row[11],
                    str(error)[:4000] if error else None,
                    None if clear_lease else row[13],
                    None if clear_lease else row[14],
                    completed_at,
                    timestamp,
                    run_id,
                ),
            )
            self._append_run_event(
                conn,
                run_id=run_id,
                event_type=event_type or target,
                status=target,
                payload=event_payload,
                created_at=timestamp,
            )
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM collaboration_runs WHERE run_id=?", (run_id,)
            ).fetchone()
        return _run_from_row(row)

    def recoverable_collaboration_runs(
        self,
        *,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        session = optional_cowork_id(session_id, label="session_id")
        limit = max(1, min(int(limit), 1000))
        timestamp = _iso(_now())
        sql = (
            f"SELECT {_RUN_COLUMNS} FROM collaboration_runs "
            "WHERE (status IN ('queued','waiting','interrupted') "
            "OR (status='running' AND (lease_expires_at IS NULL OR lease_expires_at<=?)))"
        )
        params: list[Any] = [timestamp]
        if session:
            sql += " AND session_id=?"
            params.append(session)
        sql += " ORDER BY updated_at ASC LIMIT ?"
        params.append(limit)
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_run_from_row(row) for row in rows]

    def reconcile_expired_collaboration_runs(self, *, limit: int = 1000) -> dict[str, Any]:
        """Turn orphaned live leases into explicit, resumable interruptions.

        Re-executing side-effectful agent work at process startup is unsafe.
        Startup reconciliation therefore records the orphan durably and lets
        the normal resume path reclaim it with the original contract.
        """

        limit = max(1, min(int(limit), 5000))
        timestamp = _iso(_now())
        interrupted: list[str] = []
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_RUN_SCHEMA)
            rows = conn.execute(
                "SELECT run_id,lease_owner,lease_expires_at FROM collaboration_runs "
                "WHERE status='running' AND (lease_expires_at IS NULL OR lease_expires_at<=?) "
                "ORDER BY updated_at ASC LIMIT ?",
                (timestamp, limit),
            ).fetchall()
            for run_id, lease_owner, lease_expires_at in rows:
                changed = conn.execute(
                    "UPDATE collaboration_runs SET status='interrupted',version=version+1,"
                    "error=COALESCE(error,'worker lease expired before terminal result'),"
                    "lease_owner=NULL,lease_expires_at=NULL,updated_at=? "
                    "WHERE run_id=? AND status='running' "
                    "AND (lease_expires_at IS NULL OR lease_expires_at<=?)",
                    (timestamp, str(run_id), timestamp),
                ).rowcount
                if changed != 1:
                    continue
                interrupted.append(str(run_id))
                self._append_run_event(
                    conn,
                    run_id=str(run_id),
                    event_type="lease_expired",
                    status="interrupted",
                    payload={
                        "previous_lease_owner": str(lease_owner or ""),
                        "previous_lease_expires_at": str(lease_expires_at or ""),
                    },
                    created_at=timestamp,
                )
        return {
            "schema": "octopus.collaboration_run_reconciliation.v1",
            "interrupted": len(interrupted),
            "run_ids": interrupted,
        }


__all__ = ["COLLABORATION_RUN_SCHEMA", "CollaborationRunStoreMixin"]
