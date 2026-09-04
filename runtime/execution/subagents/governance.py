"""Cross-process governance ledger for recursively delegated sub-agents.

The bridge's in-memory counters protect one Python process.  This SQLite
ledger extends the same contract across workers and restarts, while recording
provider-reported token/cost usage against the root human turn.  A root is a
turn, not an entire project, so long-running projects keep continuity without
receiving an unbounded recursive-spend allowance in any single turn.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS subagent_governance_roots (
    root_id       TEXT PRIMARY KEY,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd      REAL NOT NULL DEFAULT 0,
    breaker       TEXT NOT NULL DEFAULT 'open',
    trip_reason   TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS subagent_governance_usage (
    usage_id      TEXT PRIMARY KEY,
    root_id       TEXT NOT NULL,
    session_id    TEXT NOT NULL DEFAULT '',
    task_id       TEXT NOT NULL DEFAULT '',
    iteration     INTEGER NOT NULL DEFAULT 0,
    model         TEXT NOT NULL DEFAULT '',
    input_tokens  INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    cost_usd      REAL NOT NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_subagent_governance_usage_root
ON subagent_governance_usage(root_id, created_at);
CREATE TABLE IF NOT EXISTS subagent_governance_leases (
    lease_id      TEXT PRIMARY KEY,
    root_id       TEXT NOT NULL,
    owner_id      TEXT NOT NULL,
    depth         INTEGER NOT NULL,
    acquired_at   TEXT NOT NULL,
    expires_at    TEXT NOT NULL,
    released_at   TEXT
);
CREATE INDEX IF NOT EXISTS idx_subagent_governance_leases_active
ON subagent_governance_leases(released_at, expires_at, root_id);
"""


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _positive_env(name: str, default: int, *, ceiling: int) -> int:
    raw = os.environ.get(name, "").strip()
    if raw:
        try:
            return max(1, min(int(raw), ceiling))
        except ValueError:
            pass
    return default


def _positive_float_env(name: str, default: float, *, ceiling: float) -> float:
    raw = os.environ.get(name, "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return min(value, ceiling)
        except ValueError:
            pass
    return default


def root_token_limit() -> int:
    return _positive_env(
        "OCTOPUS_MAX_SUBAGENT_TOKENS_PER_ROOT", 2_000_000, ceiling=100_000_000
    )


def root_cost_limit_usd() -> float:
    return _positive_float_env(
        "OCTOPUS_MAX_SUBAGENT_COST_USD_PER_ROOT", 25.0, ceiling=100_000.0
    )


def lease_seconds() -> int:
    return _positive_env("OCTOPUS_SUBAGENT_LEASE_SECONDS", 1_800, ceiling=86_400)


class SubagentGovernanceStore:
    """Small WAL-backed ledger safe to share between application workers."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @staticmethod
    def _ensure_root(conn: sqlite3.Connection, root_id: str, now: str) -> None:
        conn.execute(
            "INSERT OR IGNORE INTO subagent_governance_roots"
            "(root_id,created_at,updated_at) VALUES (?,?,?)",
            (root_id, now, now),
        )

    def snapshot(self, root_id: str) -> dict[str, Any]:
        root = str(root_id or "unscoped")
        now = _iso(_now())
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_root(conn, root, now)
            conn.execute(
                "UPDATE subagent_governance_leases SET released_at=? "
                "WHERE released_at IS NULL AND expires_at<=?",
                (now, now),
            )
            row = conn.execute(
                "SELECT input_tokens,output_tokens,cost_usd,breaker,trip_reason,"
                "created_at,updated_at FROM subagent_governance_roots WHERE root_id=?",
                (root,),
            ).fetchone()
            active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM subagent_governance_leases "
                    "WHERE root_id=? AND released_at IS NULL AND expires_at>?",
                    (root, now),
                ).fetchone()[0]
            )
            conn.commit()
        return {
            "root_id": root,
            "input_tokens": int(row[0]),
            "output_tokens": int(row[1]),
            "tokens_used": int(row[0]) + int(row[1]),
            "cost_usd": round(float(row[2]), 6),
            "breaker": str(row[3]),
            "trip_reason": str(row[4]) if row[4] else None,
            "active_leases": active,
            "created_at": str(row[5]),
            "updated_at": str(row[6]),
            "token_limit": root_token_limit(),
            "cost_limit_usd": root_cost_limit_usd(),
        }

    def acquire(
        self,
        root_id: str,
        *,
        depth: int,
        global_limit: int,
        root_limit: int,
        owner_id: str = "",
    ) -> dict[str, Any] | None:
        root = str(root_id or "unscoped")
        owner = owner_id or f"{os.getpid()}:{uuid.uuid4().hex}"
        lease_id = uuid.uuid4().hex
        now_dt = _now()
        now = _iso(now_dt)
        expires = _iso(now_dt + timedelta(seconds=lease_seconds()))
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_root(conn, root, now)
            conn.execute(
                "UPDATE subagent_governance_leases SET released_at=? "
                "WHERE released_at IS NULL AND expires_at<=?",
                (now, now),
            )
            breaker = conn.execute(
                "SELECT breaker FROM subagent_governance_roots WHERE root_id=?", (root,)
            ).fetchone()[0]
            global_active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM subagent_governance_leases "
                    "WHERE released_at IS NULL AND expires_at>?",
                    (now,),
                ).fetchone()[0]
            )
            root_active = int(
                conn.execute(
                    "SELECT COUNT(*) FROM subagent_governance_leases "
                    "WHERE root_id=? AND released_at IS NULL AND expires_at>?",
                    (root, now),
                ).fetchone()[0]
            )
            if breaker != "open" or global_active >= global_limit or root_active >= root_limit:
                conn.rollback()
                return None
            conn.execute(
                "INSERT INTO subagent_governance_leases"
                "(lease_id,root_id,owner_id,depth,acquired_at,expires_at) "
                "VALUES (?,?,?,?,?,?)",
                (lease_id, root, owner, max(1, int(depth)), now, expires),
            )
            conn.commit()
        return {
            "lease_id": lease_id,
            "root_id": root,
            "owner_id": owner,
            "depth": max(1, int(depth)),
            "expires_at": expires,
        }

    def renew(self, lease_id: str) -> bool:
        now_dt = _now()
        now = _iso(now_dt)
        expires = _iso(now_dt + timedelta(seconds=lease_seconds()))
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE subagent_governance_leases SET expires_at=? "
                "WHERE lease_id=? AND released_at IS NULL AND expires_at>?",
                (expires, str(lease_id), now),
            )
        return cursor.rowcount == 1

    def release(self, lease_id: str) -> bool:
        now = _iso(_now())
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE subagent_governance_leases SET released_at=? "
                "WHERE lease_id=? AND released_at IS NULL",
                (now, str(lease_id)),
            )
        return cursor.rowcount == 1

    def record_usage(
        self,
        root_id: str,
        *,
        usage_id: str,
        input_tokens: int,
        output_tokens: int,
        cost_usd: float,
        session_id: str = "",
        task_id: str = "",
        iteration: int = 0,
        model: str = "",
    ) -> dict[str, Any]:
        root = str(root_id or "unscoped")
        input_count = max(0, int(input_tokens))
        output_count = max(0, int(output_tokens))
        cost = max(0.0, float(cost_usd))
        now = _iso(_now())
        with self._lock, self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_root(conn, root, now)
            inserted = conn.execute(
                "INSERT OR IGNORE INTO subagent_governance_usage"
                "(usage_id,root_id,session_id,task_id,iteration,model,input_tokens,"
                "output_tokens,cost_usd,created_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(usage_id),
                    root,
                    str(session_id),
                    str(task_id),
                    int(iteration),
                    str(model),
                    input_count,
                    output_count,
                    cost,
                    now,
                ),
            ).rowcount
            if inserted:
                conn.execute(
                    "UPDATE subagent_governance_roots SET input_tokens=input_tokens+?,"
                    "output_tokens=output_tokens+?,cost_usd=cost_usd+?,updated_at=? "
                    "WHERE root_id=?",
                    (input_count, output_count, cost, now, root),
                )
            row = conn.execute(
                "SELECT input_tokens,output_tokens,cost_usd,breaker "
                "FROM subagent_governance_roots WHERE root_id=?",
                (root,),
            ).fetchone()
            tokens = int(row[0]) + int(row[1])
            total_cost = float(row[2])
            breaker = str(row[3])
            reason: str | None = None
            if tokens >= root_token_limit():
                reason = "token_limit"
            elif total_cost >= root_cost_limit_usd():
                reason = "cost_limit"
            if reason and breaker == "open":
                breaker = "tripped"
                conn.execute(
                    "UPDATE subagent_governance_roots SET breaker='tripped',"
                    "trip_reason=?,updated_at=? WHERE root_id=?",
                    (reason, now, root),
                )
            conn.commit()
        snapshot = self.snapshot(root)
        snapshot["usage_recorded"] = bool(inserted)
        return snapshot


_STORE: SubagentGovernanceStore | None = None
_STORE_PATH: Path | None = None
_STORE_LOCK = threading.Lock()


def governance_store() -> SubagentGovernanceStore:
    global _STORE, _STORE_PATH
    raw = os.environ.get("OCTOPUS_SUBAGENT_GOVERNANCE_DB", "").strip()
    if raw:
        path = Path(raw)
    else:
        from runtime.platform.process.paths import app_paths

        path = app_paths().data_dir / "subagent-governance.db"
    resolved = path.expanduser().resolve()
    with _STORE_LOCK:
        if _STORE is None or resolved != _STORE_PATH:
            _STORE = SubagentGovernanceStore(resolved)
            _STORE_PATH = resolved
        return _STORE


def reset_governance_store_for_tests() -> None:
    global _STORE, _STORE_PATH
    with _STORE_LOCK:
        _STORE = None
        _STORE_PATH = None


__all__ = [
    "SubagentGovernanceStore",
    "governance_store",
    "lease_seconds",
    "reset_governance_store_for_tests",
    "root_cost_limit_usd",
    "root_token_limit",
]
