"""Reliable outbox for collaboration results delivered to a thread timeline.

Execution completion and UI delivery are separate facts.  This ledger keeps a
renderable item until its event-log write is durable, supports at-least-once
replay with stable item ids, and retains terminal failures for operator retry.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from runtime.memory.cowork.ids import optional_cowork_id, require_cowork_id

COLLABORATION_DELIVERY_SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_deliveries (
    delivery_id      TEXT PRIMARY KEY,
    run_id           TEXT NOT NULL DEFAULT '',
    session_id       TEXT NOT NULL,
    turn_id          TEXT NOT NULL,
    channel          TEXT NOT NULL,
    status           TEXT NOT NULL,
    attempt          INTEGER NOT NULL DEFAULT 0,
    max_attempts     INTEGER NOT NULL DEFAULT 8,
    payload_json     TEXT NOT NULL,
    payload_sha256   TEXT NOT NULL,
    lease_owner      TEXT,
    lease_expires_at TEXT,
    next_attempt_at  TEXT,
    deadline_at      TEXT NOT NULL,
    last_error       TEXT,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    delivered_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_collab_deliveries_session
ON collaboration_deliveries(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_collab_deliveries_due
ON collaboration_deliveries(status, next_attempt_at, lease_expires_at);

CREATE TABLE IF NOT EXISTS collaboration_delivery_events (
    delivery_id TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    event_type  TEXT NOT NULL,
    status      TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL,
    PRIMARY KEY (delivery_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_collab_delivery_events_delivery
ON collaboration_delivery_events(delivery_id, seq);
"""

_DELIVERY_SCHEMA = "octopus.collaboration_delivery.v1"
_EVENT_SCHEMA = "octopus.collaboration_delivery_event.v1"
_STATUSES = frozenset(
    {"pending", "delivering", "retry_wait", "delivered", "failed", "dismissed"}
)
_TERMINAL = frozenset({"delivered", "failed", "dismissed"})
_COLUMNS = (
    "delivery_id,run_id,session_id,turn_id,channel,status,attempt,max_attempts,"
    "payload_json,payload_sha256,lease_owner,lease_expires_at,next_attempt_at,"
    "deadline_at,last_error,created_at,updated_at,delivered_at"
)
_MAX_PAYLOAD_BYTES = 512 * 1024


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _dump(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _payload(value: Any) -> tuple[dict[str, Any], str, str]:
    if not isinstance(value, dict):
        raise ValueError("delivery payload must be an object")
    try:
        encoded = _dump(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("delivery payload must be JSON serializable") from exc
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError(f"delivery payload exceeds {_MAX_PAYLOAD_BYTES} bytes")
    normalized = json.loads(encoded)
    return normalized, encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _load(value: Any) -> dict[str, Any]:
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _from_row(row: tuple[Any, ...]) -> dict[str, Any]:
    return {
        "schema": _DELIVERY_SCHEMA,
        "delivery_id": str(row[0]),
        "run_id": str(row[1] or ""),
        "session_id": str(row[2]),
        "turn_id": str(row[3]),
        "channel": str(row[4]),
        "status": str(row[5]),
        "attempt": int(row[6]),
        "max_attempts": int(row[7]),
        "payload": _load(row[8]),
        "payload_sha256": str(row[9]),
        "lease_owner": str(row[10]) if row[10] else None,
        "lease_expires_at": str(row[11]) if row[11] else None,
        "next_attempt_at": str(row[12]) if row[12] else None,
        "deadline_at": str(row[13]),
        "last_error": str(row[14]) if row[14] else None,
        "created_at": str(row[15]),
        "updated_at": str(row[16]),
        "delivered_at": str(row[17]) if row[17] else None,
    }


class CollaborationDeliveryStoreMixin:
    """SQLite outbox mixed into :class:`CollaborationStore`."""

    _lock: Any
    _connect: Any

    @staticmethod
    def _append_delivery_event(
        conn: Any,
        *,
        delivery_id: str,
        event_type: str,
        status: str,
        created_at: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        next_seq = int(
            conn.execute(
                "SELECT COALESCE(MAX(seq),0)+1 FROM collaboration_delivery_events "
                "WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()[0]
        )
        conn.execute(
            "INSERT INTO collaboration_delivery_events"
            "(delivery_id,seq,event_type,status,payload_json,created_at) VALUES (?,?,?,?,?,?)",
            (delivery_id, next_seq, event_type, status, _dump(payload or {}), created_at),
        )

    def enqueue_collaboration_delivery(
        self,
        *,
        delivery_id: str,
        session_id: str,
        turn_id: str,
        payload: dict[str, Any],
        run_id: str = "",
        channel: str = "realtime",
        max_attempts: int = 8,
        deadline_seconds: int = 24 * 60 * 60,
    ) -> dict[str, Any]:
        delivery_id = require_cowork_id(delivery_id, label="delivery_id")
        session_id = require_cowork_id(session_id, label="session_id")
        turn_id = require_cowork_id(turn_id, label="turn_id")
        run_id = optional_cowork_id(run_id, label="run_id")
        channel = require_cowork_id(channel, label="delivery channel").lower()
        max_attempts = max(1, min(int(max_attempts), 100))
        deadline_seconds = max(60, min(int(deadline_seconds), 7 * 24 * 60 * 60))
        _normalized, encoded, digest = _payload(payload)
        now = _now()
        timestamp = _iso(now)
        deadline = _iso(now + timedelta(seconds=deadline_seconds))
        with self._lock, self._connect() as conn:
            conn.executescript(COLLABORATION_DELIVERY_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            if row:
                current = _from_row(row)
                identity = (
                    str(current["session_id"]),
                    str(current["turn_id"]),
                    str(current["run_id"]),
                    str(current["channel"]),
                    str(current["payload_sha256"]),
                )
                if identity != (session_id, turn_id, run_id, channel, digest):
                    raise ValueError("delivery_id already belongs to a different payload")
                return current
            conn.execute(
                "INSERT INTO collaboration_deliveries"
                "(delivery_id,run_id,session_id,turn_id,channel,status,max_attempts,payload_json,"
                "payload_sha256,next_attempt_at,deadline_at,created_at,updated_at) "
                "VALUES (?,?,?,?,?,'pending',?,?,?,?,?,?,?)",
                (
                    delivery_id,
                    run_id,
                    session_id,
                    turn_id,
                    channel,
                    max_attempts,
                    encoded,
                    digest,
                    timestamp,
                    deadline,
                    timestamp,
                    timestamp,
                ),
            )
            self._append_delivery_event(
                conn,
                delivery_id=delivery_id,
                event_type="enqueued",
                status="pending",
                created_at=timestamp,
                payload={"run_id": run_id, "channel": channel},
            )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        return _from_row(row)

    def collaboration_delivery(self, delivery_id: str) -> dict[str, Any] | None:
        delivery_id = require_cowork_id(delivery_id, label="delivery_id")
        with self._lock, self._connect() as conn:
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        return _from_row(row) if row else None

    def collaboration_deliveries_for_session(
        self,
        session_id: str,
        *,
        statuses: list[str] | tuple[str, ...] | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        session_id = require_cowork_id(session_id, label="session_id")
        normalized = tuple(dict.fromkeys(str(s or "").strip().lower() for s in statuses or ()))
        invalid = [status for status in normalized if status not in _STATUSES]
        if invalid:
            raise ValueError(f"invalid collaboration delivery status: {invalid[0]}")
        sql = f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE session_id=?"
        params: list[Any] = [session_id]
        if normalized:
            sql += " AND status IN (" + ",".join("?" for _ in normalized) + ")"
            params.extend(normalized)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_from_row(row) for row in rows]

    def collaboration_delivery_events(self, delivery_id: str) -> list[dict[str, Any]]:
        delivery_id = require_cowork_id(delivery_id, label="delivery_id")
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT seq,event_type,status,payload_json,created_at "
                "FROM collaboration_delivery_events WHERE delivery_id=? ORDER BY seq",
                (delivery_id,),
            ).fetchall()
        return [
            {
                "schema": _EVENT_SCHEMA,
                "delivery_id": delivery_id,
                "seq": int(seq),
                "event_type": str(event_type),
                "status": str(status),
                "payload": _load(payload_json),
                "created_at": str(created_at),
            }
            for seq, event_type, status, payload_json, created_at in rows
        ]

    def due_collaboration_deliveries(
        self,
        *,
        session_id: str = "",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        session_id = optional_cowork_id(session_id, label="session_id")
        timestamp = _iso(_now())
        sql = (
            f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE "
            "((status IN ('pending','retry_wait') AND COALESCE(next_attempt_at,'')<=?) "
            "OR (status='delivering' AND COALESCE(lease_expires_at,'')<=?)) "
            "AND deadline_at>?"
        )
        params: list[Any] = [timestamp, timestamp, timestamp]
        if session_id:
            sql += " AND session_id=?"
            params.append(session_id)
        sql += " ORDER BY created_at,delivery_id LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [_from_row(row) for row in rows]

    def claim_collaboration_delivery(
        self,
        delivery_id: str,
        *,
        worker_id: str,
        lease_seconds: int = 60,
    ) -> dict[str, Any]:
        delivery_id = require_cowork_id(delivery_id, label="delivery_id")
        worker_id = require_cowork_id(worker_id, label="worker_id")
        now = _now()
        timestamp = _iso(now)
        expires = _iso(now + timedelta(seconds=max(5, min(int(lease_seconds), 600))))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"collaboration delivery not found: {delivery_id}")
            current = _from_row(row)
            status = str(current["status"])
            if status in _TERMINAL:
                raise ValueError(f"cannot claim terminal collaboration delivery: {status}")
            if str(current["deadline_at"]) <= timestamp:
                self._mark_delivery_terminal_failure(conn, current, timestamp, "delivery deadline expired")
            elif status == "delivering" and str(current.get("lease_expires_at") or "") > timestamp:
                if current.get("lease_owner") != worker_id:
                    raise RuntimeError("collaboration delivery is leased by another worker")
                return current
            elif str(current.get("next_attempt_at") or "") > timestamp:
                raise RuntimeError("collaboration delivery retry is not due")
            else:
                event_type = "reclaimed" if status == "delivering" else "claimed"
                conn.execute(
                    "UPDATE collaboration_deliveries SET status='delivering',attempt=attempt+1,"
                    "lease_owner=?,lease_expires_at=?,next_attempt_at=NULL,updated_at=? "
                    "WHERE delivery_id=?",
                    (worker_id, expires, timestamp, delivery_id),
                )
                self._append_delivery_event(
                    conn,
                    delivery_id=delivery_id,
                    event_type=event_type,
                    status="delivering",
                    created_at=timestamp,
                    payload={"worker_id": worker_id},
                )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        current = _from_row(row)
        if current["status"] == "failed":
            raise ValueError("cannot claim collaboration delivery after deadline")
        return current

    @classmethod
    def _mark_delivery_terminal_failure(
        cls,
        conn: Any,
        current: dict[str, Any],
        timestamp: str,
        error: str,
    ) -> None:
        delivery_id = str(current["delivery_id"])
        conn.execute(
            "UPDATE collaboration_deliveries SET status='failed',lease_owner=NULL,"
            "lease_expires_at=NULL,next_attempt_at=NULL,last_error=?,updated_at=? "
            "WHERE delivery_id=?",
            (error[:4000], timestamp, delivery_id),
        )
        cls._append_delivery_event(
            conn,
            delivery_id=delivery_id,
            event_type="failed",
            status="failed",
            created_at=timestamp,
            payload={"error": error[:4000]},
        )

    def mark_collaboration_delivery_delivered(
        self,
        delivery_id: str,
        *,
        worker_id: str,
    ) -> dict[str, Any]:
        delivery_id = require_cowork_id(delivery_id, label="delivery_id")
        worker_id = require_cowork_id(worker_id, label="worker_id")
        timestamp = _iso(_now())
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"collaboration delivery not found: {delivery_id}")
            current = _from_row(row)
            if current["status"] == "delivered":
                return current
            if current["status"] != "delivering" or current.get("lease_owner") != worker_id:
                raise RuntimeError("collaboration delivery is not leased by this worker")
            conn.execute(
                "UPDATE collaboration_deliveries SET status='delivered',lease_owner=NULL,"
                "lease_expires_at=NULL,next_attempt_at=NULL,last_error=NULL,updated_at=?,"
                "delivered_at=? WHERE delivery_id=?",
                (timestamp, timestamp, delivery_id),
            )
            self._append_delivery_event(
                conn,
                delivery_id=delivery_id,
                event_type="delivered",
                status="delivered",
                created_at=timestamp,
            )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        return _from_row(row)

    def mark_collaboration_delivery_failed(
        self,
        delivery_id: str,
        *,
        worker_id: str,
        error: str,
    ) -> dict[str, Any]:
        delivery_id = require_cowork_id(delivery_id, label="delivery_id")
        worker_id = require_cowork_id(worker_id, label="worker_id")
        message = str(error or "delivery failed")[:4000]
        now = _now()
        timestamp = _iso(now)
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"collaboration delivery not found: {delivery_id}")
            current = _from_row(row)
            if current["status"] == "delivered":
                return current
            if current["status"] != "delivering" or current.get("lease_owner") != worker_id:
                raise RuntimeError("collaboration delivery is not leased by this worker")
            terminal = (
                int(current["attempt"]) >= int(current["max_attempts"])
                or str(current["deadline_at"]) <= timestamp
            )
            if terminal:
                self._mark_delivery_terminal_failure(conn, current, timestamp, message)
            else:
                delay = min(15 * 60, 2 ** max(0, int(current["attempt"]) - 1))
                next_attempt = _iso(now + timedelta(seconds=delay))
                conn.execute(
                    "UPDATE collaboration_deliveries SET status='retry_wait',lease_owner=NULL,"
                    "lease_expires_at=NULL,next_attempt_at=?,last_error=?,updated_at=? "
                    "WHERE delivery_id=?",
                    (next_attempt, message, timestamp, delivery_id),
                )
                self._append_delivery_event(
                    conn,
                    delivery_id=delivery_id,
                    event_type="retry_scheduled",
                    status="retry_wait",
                    created_at=timestamp,
                    payload={"error": message, "next_attempt_at": next_attempt},
                )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        return _from_row(row)

    def retry_collaboration_delivery(self, delivery_id: str) -> dict[str, Any]:
        delivery_id = require_cowork_id(delivery_id, label="delivery_id")
        now = _now()
        timestamp = _iso(now)
        deadline = _iso(now + timedelta(hours=24))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"collaboration delivery not found: {delivery_id}")
            current = _from_row(row)
            if current["status"] == "delivered":
                return current
            if current["status"] == "delivering" and str(
                current.get("lease_expires_at") or ""
            ) > timestamp:
                raise RuntimeError("collaboration delivery is currently being delivered")
            conn.execute(
                "UPDATE collaboration_deliveries SET status='pending',attempt=0,lease_owner=NULL,"
                "lease_expires_at=NULL,next_attempt_at=?,deadline_at=?,last_error=NULL,updated_at=? "
                "WHERE delivery_id=?",
                (timestamp, deadline, timestamp, delivery_id),
            )
            self._append_delivery_event(
                conn,
                delivery_id=delivery_id,
                event_type="manual_retry",
                status="pending",
                created_at=timestamp,
            )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        return _from_row(row)

    def dismiss_collaboration_delivery(self, delivery_id: str) -> dict[str, Any]:
        delivery_id = require_cowork_id(delivery_id, label="delivery_id")
        timestamp = _iso(_now())
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
            if not row:
                raise KeyError(f"collaboration delivery not found: {delivery_id}")
            current = _from_row(row)
            if current["status"] == "delivered":
                raise ValueError("delivered collaboration delivery cannot be dismissed")
            if current["status"] != "dismissed":
                conn.execute(
                    "UPDATE collaboration_deliveries SET status='dismissed',lease_owner=NULL,"
                    "lease_expires_at=NULL,next_attempt_at=NULL,updated_at=? WHERE delivery_id=?",
                    (timestamp, delivery_id),
                )
                self._append_delivery_event(
                    conn,
                    delivery_id=delivery_id,
                    event_type="dismissed",
                    status="dismissed",
                    created_at=timestamp,
                )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE delivery_id=?",
                (delivery_id,),
            ).fetchone()
        return _from_row(row)

    def reconcile_collaboration_deliveries(self, *, limit: int = 1000) -> dict[str, int]:
        """Expire dead leases/deadlines so every row remains actionable."""

        timestamp = _iso(_now())
        reclaimed = 0
        failed = 0
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                f"SELECT {_COLUMNS} FROM collaboration_deliveries WHERE "
                "(status='delivering' AND COALESCE(lease_expires_at,'')<=?) OR "
                "(status IN ('pending','retry_wait','delivering') AND deadline_at<=?) "
                "ORDER BY updated_at LIMIT ?",
                (timestamp, timestamp, max(1, min(int(limit), 10_000))),
            ).fetchall()
            for row in rows:
                current = _from_row(row)
                if str(current["deadline_at"]) <= timestamp:
                    self._mark_delivery_terminal_failure(
                        conn, current, timestamp, "delivery deadline expired"
                    )
                    failed += 1
                    continue
                conn.execute(
                    "UPDATE collaboration_deliveries SET status='retry_wait',lease_owner=NULL,"
                    "lease_expires_at=NULL,next_attempt_at=?,last_error=?,updated_at=? "
                    "WHERE delivery_id=?",
                    (timestamp, "delivery lease expired", timestamp, current["delivery_id"]),
                )
                self._append_delivery_event(
                    conn,
                    delivery_id=str(current["delivery_id"]),
                    event_type="lease_expired",
                    status="retry_wait",
                    created_at=timestamp,
                )
                reclaimed += 1
        return {"reclaimed": reclaimed, "failed": failed}
