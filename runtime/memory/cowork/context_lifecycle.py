"""Transactional, privacy-safe lifecycle ledger for cowork context turns.

The context planner decides what each member may see.  This ledger records the
admission and final disposition of that decision without copying message or
result bodies.  It gives retries and process recovery one atomic advancement
key (session + turn), detects conflicting replays, and preserves partial group
outcomes for audit.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from runtime.memory.cowork.ids import optional_cowork_id, require_cowork_id

CONTEXT_LIFECYCLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS collaboration_context_turns (
    session_id       TEXT NOT NULL,
    turn_id          TEXT NOT NULL,
    run_id           TEXT NOT NULL DEFAULT '',
    engine           TEXT NOT NULL,
    message_sha256   TEXT NOT NULL,
    plan_sha256      TEXT NOT NULL,
    status           TEXT NOT NULL,
    expected_members INTEGER NOT NULL,
    committed_members INTEGER NOT NULL DEFAULT 0,
    aborted_members  INTEGER NOT NULL DEFAULT 0,
    selected_tokens  INTEGER NOT NULL DEFAULT 0,
    full_tokens      INTEGER NOT NULL DEFAULT 0,
    deep_recall      INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    completed_at     TEXT,
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (session_id, turn_id)
);
CREATE INDEX IF NOT EXISTS idx_collab_context_turns_session
ON collaboration_context_turns(session_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS collaboration_context_members (
    session_id        TEXT NOT NULL,
    turn_id           TEXT NOT NULL,
    agent_id          TEXT NOT NULL,
    admission_sha256  TEXT NOT NULL,
    result_sha256     TEXT,
    status            TEXT NOT NULL,
    selected_tokens   INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (session_id, turn_id, agent_id)
);
CREATE INDEX IF NOT EXISTS idx_collab_context_members_turn
ON collaboration_context_members(session_id, turn_id, status);
"""

_TURN_SCHEMA = "octopus.cowork_context_lifecycle.v1"
_TERMINAL_TURN_STATUSES = frozenset({"committed", "partial", "aborted", "rolled_back"})
_MEMBER_STATUSES = frozenset({"committed", "aborted"})


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digest(value: Any) -> str:
    return _sha256(_canonical(value))


def _bounded_count(value: Any) -> int:
    try:
        return max(0, min(100_000_000, int(value)))
    except (TypeError, ValueError):
        return 0


def _valid_digest(value: Any, *, label: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise ValueError(f"{label} must be a sha256 digest")
    return digest


def _turn_from_rows(turn: Any, members: list[Any]) -> dict[str, Any]:
    return {
        "schema": _TURN_SCHEMA,
        "session_id": str(turn[0]),
        "turn_id": str(turn[1]),
        "run_id": str(turn[2] or ""),
        "engine": str(turn[3]),
        "message_sha256": str(turn[4]),
        "plan_sha256": str(turn[5]),
        "status": str(turn[6]),
        "expected_members": int(turn[7]),
        "committed_members": int(turn[8]),
        "aborted_members": int(turn[9]),
        "selected_tokens": int(turn[10]),
        "full_tokens": int(turn[11]),
        "deep_recall": bool(turn[12]),
        "created_at": str(turn[13]),
        "completed_at": str(turn[14]) if turn[14] else None,
        "updated_at": str(turn[15]),
        "members": [
            {
                "agent_id": str(row[0]),
                "admission_sha256": str(row[1]),
                "result_sha256": str(row[2]) if row[2] else None,
                "status": str(row[3]),
                "selected_tokens": int(row[4]),
                "updated_at": str(row[5]),
            }
            for row in members
        ],
    }


_TURN_COLUMNS = (
    "session_id,turn_id,run_id,engine,message_sha256,plan_sha256,status,"
    "expected_members,committed_members,aborted_members,selected_tokens,"
    "full_tokens,deep_recall,created_at,completed_at,updated_at"
)


class CollaborationContextLifecycleStoreMixin:
    """Mixin implemented by :class:`CollaborationStore`."""

    _lock: Any
    _connect: Any

    def admit_context_turn(
        self,
        *,
        session_id: str,
        turn_id: str,
        message: str,
        receipt: dict[str, Any],
        run_id: str = "",
    ) -> dict[str, Any]:
        """Atomically admit one assembled plan under a stable advancement key."""

        session_id = require_cowork_id(session_id, label="session_id")
        turn_id = require_cowork_id(turn_id, label="turn_id")
        run_id = optional_cowork_id(run_id, label="run_id")
        if not isinstance(receipt, dict):
            raise ValueError("context lifecycle receipt must be an object")
        engine = require_cowork_id(
            receipt.get("selection_engine") or "deterministic", label="engine"
        )
        raw_members = receipt.get("members")
        if not isinstance(raw_members, list) or not raw_members:
            raise ValueError("context lifecycle receipt requires members")
        members: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in raw_members[:512]:
            if not isinstance(raw, dict):
                continue
            agent_id = require_cowork_id(raw.get("agent_id") or "", label="agent_id")
            if agent_id in seen:
                raise ValueError("context lifecycle receipt contains duplicate member")
            seen.add(agent_id)
            admission = {
                "agent_id": agent_id,
                "authorization_fingerprint": _valid_digest(
                    raw.get("authorization_fingerprint"),
                    label="authorization_fingerprint",
                ),
                "selected_sources_sha256": _valid_digest(
                    raw.get("selected_sources_sha256"),
                    label="selected_sources_sha256",
                ),
                "selected_tokens": _bounded_count(raw.get("selected_tokens")),
                "full_tokens": _bounded_count(raw.get("full_tokens")),
            }
            members.append({**admission, "admission_sha256": _digest(admission)})
        if not members:
            raise ValueError("context lifecycle receipt has no valid members")

        canonical_receipt = {
            "schema": str(receipt.get("schema") or ""),
            "selection_engine": engine,
            "selected_tokens": sum(member["selected_tokens"] for member in members),
            "full_tokens": sum(member["full_tokens"] for member in members),
            "deep_recall": bool(receipt.get("deep_recall")),
            "members": [
                {
                    "agent_id": member["agent_id"],
                    "admission_sha256": member["admission_sha256"],
                }
                for member in members
            ],
        }
        message_sha256 = _sha256(str(message or ""))
        plan_sha256 = _digest(canonical_receipt)
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(CONTEXT_LIFECYCLE_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                f"SELECT {_TURN_COLUMNS} FROM collaboration_context_turns "
                "WHERE session_id=? AND turn_id=?",
                (session_id, turn_id),
            ).fetchone()
            if existing:
                identity = (run_id, engine, message_sha256, plan_sha256)
                if identity != tuple(str(existing[index] or "") for index in (2, 3, 4, 5)):
                    raise ValueError("context turn advancement key replay conflicts with admission")
            else:
                conn.execute(
                    "INSERT INTO collaboration_context_turns("
                    "session_id,turn_id,run_id,engine,message_sha256,plan_sha256,status,"
                    "expected_members,selected_tokens,full_tokens,deep_recall,created_at,updated_at"
                    ") VALUES (?,?,?,?,?,?,'admitted',?,?,?,?,?,?)",
                    (
                        session_id,
                        turn_id,
                        run_id,
                        engine,
                        message_sha256,
                        plan_sha256,
                        len(members),
                        canonical_receipt["selected_tokens"],
                        canonical_receipt["full_tokens"],
                        1 if canonical_receipt["deep_recall"] else 0,
                        timestamp,
                        timestamp,
                    ),
                )
                conn.executemany(
                    "INSERT INTO collaboration_context_members("
                    "session_id,turn_id,agent_id,admission_sha256,status,selected_tokens,"
                    "created_at,updated_at) VALUES (?,?,?,?,'admitted',?,?,?)",
                    [
                        (
                            session_id,
                            turn_id,
                            member["agent_id"],
                            member["admission_sha256"],
                            member["selected_tokens"],
                            timestamp,
                            timestamp,
                        )
                        for member in members
                    ],
                )
        snapshot = self.context_turn(session_id, turn_id)
        if snapshot is None:  # pragma: no cover - guarded by same transaction
            raise RuntimeError("context turn admission disappeared")
        return snapshot

    def settle_context_turn(
        self,
        session_id: str,
        turn_id: str,
        outcomes: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Commit successful member advances and abort failed ones atomically."""

        session_id = require_cowork_id(session_id, label="session_id")
        turn_id = require_cowork_id(turn_id, label="turn_id")
        if not isinstance(outcomes, list):
            raise ValueError("context outcomes must be a list")
        normalized: dict[str, tuple[str, str]] = {}
        for raw in outcomes[:512]:
            if not isinstance(raw, dict):
                continue
            agent_id = require_cowork_id(raw.get("agent_id") or "", label="agent_id")
            status = str(raw.get("status") or "").strip().lower()
            if status not in _MEMBER_STATUSES:
                raise ValueError("context member status must be committed or aborted")
            result_sha256 = _valid_digest(raw.get("result_sha256"), label="result_sha256")
            current = normalized.get(agent_id)
            if current is not None and current != (status, result_sha256):
                raise ValueError("context outcomes conflict for one member")
            normalized[agent_id] = (status, result_sha256)
        if not normalized:
            raise ValueError("context outcomes require at least one member")

        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(CONTEXT_LIFECYCLE_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            turn = conn.execute(
                "SELECT status FROM collaboration_context_turns WHERE session_id=? AND turn_id=?",
                (session_id, turn_id),
            ).fetchone()
            if not turn:
                raise KeyError("context turn not found")
            if str(turn[0]) == "rolled_back":
                raise ValueError("rolled back context turn cannot advance")
            changed = False
            for agent_id, (status, result_sha256) in normalized.items():
                row = conn.execute(
                    "SELECT status,result_sha256 FROM collaboration_context_members "
                    "WHERE session_id=? AND turn_id=? AND agent_id=?",
                    (session_id, turn_id, agent_id),
                ).fetchone()
                if not row:
                    raise ValueError("context outcome member was not admitted")
                prior_status = str(row[0])
                prior_digest = str(row[1]) if row[1] else None
                if prior_status != "admitted":
                    if (prior_status, prior_digest) != (status, result_sha256):
                        raise ValueError("context member replay conflicts with committed outcome")
                    continue
                conn.execute(
                    "UPDATE collaboration_context_members SET status=?,result_sha256=?,updated_at=? "
                    "WHERE session_id=? AND turn_id=? AND agent_id=? AND status='admitted'",
                    (status, result_sha256, timestamp, session_id, turn_id, agent_id),
                )
                changed = True
            counts = conn.execute(
                "SELECT COUNT(*),SUM(status='committed'),SUM(status='aborted'),"
                "SUM(status='admitted') FROM collaboration_context_members "
                "WHERE session_id=? AND turn_id=?",
                (session_id, turn_id),
            ).fetchone()
            expected = int(counts[0] or 0)
            committed = int(counts[1] or 0)
            aborted = int(counts[2] or 0)
            remaining = int(counts[3] or 0)
            turn_status = (
                "admitted"
                if remaining
                else "committed"
                if committed == expected
                else "partial"
                if committed
                else "aborted"
            )
            completed_at = timestamp if turn_status in _TERMINAL_TURN_STATUSES else None
            if changed:
                conn.execute(
                    "UPDATE collaboration_context_turns SET status=?,committed_members=?,"
                    "aborted_members=?,completed_at=?,updated_at=? "
                    "WHERE session_id=? AND turn_id=?",
                    (
                        turn_status,
                        committed,
                        aborted,
                        completed_at,
                        timestamp,
                        session_id,
                        turn_id,
                    ),
                )
        snapshot = self.context_turn(session_id, turn_id)
        if snapshot is None:  # pragma: no cover
            raise RuntimeError("settled context turn disappeared")
        return snapshot

    def rollback_context_turn(self, session_id: str, turn_id: str) -> dict[str, Any]:
        """Roll back an admission only before any member successfully advances."""

        session_id = require_cowork_id(session_id, label="session_id")
        turn_id = require_cowork_id(turn_id, label="turn_id")
        timestamp = _now()
        with self._lock, self._connect() as conn:
            conn.executescript(CONTEXT_LIFECYCLE_SCHEMA)
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT status,committed_members FROM collaboration_context_turns "
                "WHERE session_id=? AND turn_id=?",
                (session_id, turn_id),
            ).fetchone()
            if not row:
                raise KeyError("context turn not found")
            if str(row[0]) == "rolled_back":
                pass
            elif int(row[1] or 0) > 0:
                raise ValueError("committed context turn cannot be rolled back")
            else:
                conn.execute(
                    "UPDATE collaboration_context_members SET status='aborted',updated_at=? "
                    "WHERE session_id=? AND turn_id=? AND status='admitted'",
                    (timestamp, session_id, turn_id),
                )
                aborted = int(
                    conn.execute(
                        "SELECT COUNT(*) FROM collaboration_context_members "
                        "WHERE session_id=? AND turn_id=? AND status='aborted'",
                        (session_id, turn_id),
                    ).fetchone()[0]
                )
                conn.execute(
                    "UPDATE collaboration_context_turns SET status='rolled_back',"
                    "aborted_members=?,completed_at=?,updated_at=? "
                    "WHERE session_id=? AND turn_id=?",
                    (aborted, timestamp, timestamp, session_id, turn_id),
                )
        snapshot = self.context_turn(session_id, turn_id)
        if snapshot is None:  # pragma: no cover
            raise RuntimeError("rolled back context turn disappeared")
        return snapshot

    def context_turn(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        session_id = require_cowork_id(session_id, label="session_id")
        turn_id = require_cowork_id(turn_id, label="turn_id")
        with self._lock, self._connect() as conn:
            conn.executescript(CONTEXT_LIFECYCLE_SCHEMA)
            turn = conn.execute(
                f"SELECT {_TURN_COLUMNS} FROM collaboration_context_turns "
                "WHERE session_id=? AND turn_id=?",
                (session_id, turn_id),
            ).fetchone()
            if not turn:
                return None
            members = conn.execute(
                "SELECT agent_id,admission_sha256,result_sha256,status,selected_tokens,updated_at "
                "FROM collaboration_context_members WHERE session_id=? AND turn_id=? "
                "ORDER BY agent_id",
                (session_id, turn_id),
            ).fetchall()
        return _turn_from_rows(turn, members)


__all__ = [
    "CONTEXT_LIFECYCLE_SCHEMA",
    "CollaborationContextLifecycleStoreMixin",
]
