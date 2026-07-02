"""Persistent control-session substrate.

Browser, Chrome relay, Electron webviews, and host-computer automation all
need the same operator contract: who owns control, what surface is being
controlled, which actions are queued/running, whether the user took over, and
which evidence proves what happened.  This store is intentionally small and
SQLite-backed so gateway routers can share it without depending on a long-lived
process singleton.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

_SURFACES = frozenset({"browser", "chrome", "electron_webview", "backend_preview", "computer"})
_SESSION_STATUSES = frozenset({"idle", "running", "paused", "awaiting_confirmation", "stopped", "expired"})
_ACTION_STATUSES = frozenset({"queued", "running", "waiting_user", "done", "failed", "cancelled", "expired"})
_EVIDENCE_KINDS = frozenset({"action", "result", "screenshot", "dom", "lease", "log"})
_SAFE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,239}$")
_MAX_JSON_BYTES = 1024 * 1024
_MAX_TEXT = 65_536

_SCHEMA = """
CREATE TABLE IF NOT EXISTS control_sessions (
    session_id     TEXT PRIMARY KEY,
    owner_id       TEXT NOT NULL,
    owner_label    TEXT NOT NULL,
    surface        TEXT NOT NULL,
    target_id      TEXT NOT NULL,
    status         TEXT NOT NULL,
    paused         INTEGER NOT NULL DEFAULT 0,
    takeover_count INTEGER NOT NULL DEFAULT 0,
    metadata_json  TEXT NOT NULL,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL,
    expires_at     REAL
);
CREATE INDEX IF NOT EXISTS idx_control_sessions_surface
    ON control_sessions(surface, updated_at);

CREATE TABLE IF NOT EXISTS control_actions (
    action_id       TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL,
    surface         TEXT NOT NULL,
    target_id       TEXT NOT NULL,
    action_type     TEXT NOT NULL,
    status          TEXT NOT NULL,
    descriptor_json TEXT NOT NULL,
    result_json     TEXT NOT NULL,
    error           TEXT NOT NULL,
    queued_at       REAL NOT NULL,
    started_at      REAL,
    completed_at    REAL,
    expires_at      REAL,
    FOREIGN KEY(session_id) REFERENCES control_sessions(session_id)
);
CREATE INDEX IF NOT EXISTS idx_control_actions_session
    ON control_actions(session_id, queued_at);

CREATE TABLE IF NOT EXISTS control_evidence (
    evidence_id TEXT PRIMARY KEY,
    session_id  TEXT NOT NULL,
    action_id   TEXT NOT NULL,
    seq         INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    action_type TEXT NOT NULL,
    ok          INTEGER,
    summary     TEXT NOT NULL,
    detail_json TEXT NOT NULL,
    created_at  REAL NOT NULL,
    FOREIGN KEY(session_id) REFERENCES control_sessions(session_id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_control_evidence_session_seq
    ON control_evidence(session_id, seq);

CREATE TABLE IF NOT EXISTS control_events (
    event_seq    INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    event_type   TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_control_events_session
    ON control_events(session_id, event_seq);
"""


def _default_dir() -> Path:
    from runtime.platform.process.paths import app_paths

    return app_paths().data_dir / "control_sessions"


def _require_id(value: object, *, label: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text):
        raise ValueError(
            f"invalid {label}: use 1-240 letters, numbers, dot, underscore, colon, @, or hyphen"
        )
    return text


def _optional_text(value: object, *, max_len: int = _MAX_TEXT) -> str:
    text = str(value or "").strip()
    if len(text) > max_len or any(ord(ch) < 32 and ch not in "\n\r\t" for ch in text):
        raise ValueError("invalid text payload")
    return text


def _json_dict(value: Any, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {}
    try:
        blob = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {label}: not JSON serializable") from exc
    if len(blob.encode("utf-8")) > _MAX_JSON_BYTES:
        raise ValueError(f"invalid {label}: JSON payload exceeds {_MAX_JSON_BYTES} bytes")
    data = json.loads(blob)
    return data if isinstance(data, dict) else {}


def _dump(value: dict[str, Any], *, label: str) -> str:
    return json.dumps(_json_dict(value, label=label), ensure_ascii=False, sort_keys=True)


def _load(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _surface(value: object) -> str:
    text = str(value or "browser").strip()
    if text not in _SURFACES:
        raise ValueError(f"invalid control surface: {text}")
    return text


def _session_status(value: object) -> str:
    text = str(value or "idle").strip()
    if text not in _SESSION_STATUSES:
        raise ValueError(f"invalid control session status: {text}")
    return text


def _action_status(value: object) -> str:
    text = str(value or "queued").strip()
    if text not in _ACTION_STATUSES:
        raise ValueError(f"invalid control action status: {text}")
    return text


def _evidence_kind(value: object) -> str:
    text = str(value or "log").strip()
    if text not in _EVIDENCE_KINDS:
        raise ValueError(f"invalid control evidence kind: {text}")
    return text


def _row_to_session(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    return {
        "session_id": row[0],
        "owner_id": row[1],
        "owner_label": row[2],
        "surface": row[3],
        "target_id": row[4],
        "status": row[5],
        "paused": bool(row[6]),
        "takeover_count": int(row[7] or 0),
        "metadata": _load(row[8]),
        "created_at": float(row[9]),
        "updated_at": float(row[10]),
        "expires_at": float(row[11]) if row[11] is not None else None,
    }


def _row_to_action(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    return {
        "action_id": row[0],
        "session_id": row[1],
        "surface": row[2],
        "target_id": row[3],
        "action_type": row[4],
        "status": row[5],
        "descriptor": _load(row[6]),
        "result": _load(row[7]),
        "error": row[8] or "",
        "queued_at": float(row[9]),
        "started_at": float(row[10]) if row[10] is not None else None,
        "completed_at": float(row[11]) if row[11] is not None else None,
        "expires_at": float(row[12]) if row[12] is not None else None,
    }


def _row_to_evidence(row: sqlite3.Row | tuple[Any, ...]) -> dict[str, Any]:
    ok = row[6]
    return {
        "evidence_id": row[0],
        "session_id": row[1],
        "action_id": row[2] or "",
        "seq": int(row[3]),
        "kind": row[4],
        "action": row[5] or "",
        "ok": None if ok is None else bool(ok),
        "summary": row[7] or "",
        "detail": _load(row[8]),
        "created_at": float(row[9]),
    }


class ControlSessionStore:
    """SQLite store for operator control sessions and replay evidence."""

    def __init__(self, base_dir: Path | str | None = None) -> None:
        self._dir = Path(base_dir) if base_dir else _default_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._db = self._dir / "control_sessions.db"
        self._lock = threading.RLock()
        with self._lock, self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def base_dir(self) -> Path:
        return self._dir

    def _connect(self) -> sqlite3.Connection:
        self._dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self._db), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        return conn

    def upsert_session(
        self,
        *,
        session_id: str | None = None,
        owner_id: str = "",
        owner_label: str = "",
        surface: str = "browser",
        target_id: str = "",
        status: str = "idle",
        metadata: dict[str, Any] | None = None,
        ttl_seconds: float | None = None,
        takeover: bool = False,
    ) -> dict[str, Any]:
        sid = _require_id(session_id or f"control-{uuid4().hex[:16]}", label="session_id")
        surf = _surface(surface)
        target = _optional_text(target_id or "default", max_len=512) or "default"
        owner = _optional_text(owner_id or "agent", max_len=256) or "agent"
        label = _optional_text(owner_label or owner, max_len=512) or owner
        normalized_status = _session_status(status)
        meta = _json_dict(metadata or {}, label="metadata")
        now = time.time()
        expires_at = now + float(ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None

        with self._lock, self._connect() as conn:
            existing = conn.execute(
                "SELECT takeover_count, created_at FROM control_sessions WHERE session_id=?",
                (sid,),
            ).fetchone()
            created_at = float(existing[1]) if existing else now
            takeover_count = (int(existing[0] or 0) if existing else 0) + (
                1 if takeover and existing else 0
            )
            conn.execute(
                "INSERT INTO control_sessions("
                "session_id, owner_id, owner_label, surface, target_id, status, paused, "
                "takeover_count, metadata_json, created_at, updated_at, expires_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "owner_id=excluded.owner_id, owner_label=excluded.owner_label, "
                "surface=excluded.surface, target_id=excluded.target_id, "
                "status=excluded.status, paused=excluded.paused, "
                "takeover_count=excluded.takeover_count, metadata_json=excluded.metadata_json, "
                "updated_at=excluded.updated_at, expires_at=excluded.expires_at",
                (
                    sid,
                    owner,
                    label,
                    surf,
                    target,
                    normalized_status,
                    1 if normalized_status == "paused" else 0,
                    takeover_count,
                    _dump(meta, label="metadata"),
                    created_at,
                    now,
                    expires_at,
                ),
            )
            session = self._session_locked(conn, sid)
            self._event_locked(conn, sid, "session_upserted", session)
            return session

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        sid = _require_id(session_id, label="session_id")
        with self._lock, self._connect() as conn:
            self._expire_locked(conn, sid)
            self._expire_actions_locked(conn, sid)
            return self._session_locked(conn, sid)

    def list_sessions(
        self,
        *,
        surface: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(500, int(limit)))
        params: list[Any] = []
        where = ""
        if surface:
            where = "WHERE surface=?"
            params.append(_surface(surface))
        with self._lock, self._connect() as conn:
            self._expire_all_locked(conn)
            rows = conn.execute(
                "SELECT session_id, owner_id, owner_label, surface, target_id, status, paused, "
                "takeover_count, metadata_json, created_at, updated_at, expires_at "
                f"FROM control_sessions {where} ORDER BY updated_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [_row_to_session(row) for row in rows]

    def set_session_state(
        self,
        session_id: str,
        *,
        status: str,
        reason: str = "",
        owner_id: str | None = None,
        owner_label: str | None = None,
        metadata: dict[str, Any] | None = None,
        takeover: bool = False,
    ) -> dict[str, Any]:
        sid = _require_id(session_id, label="session_id")
        normalized = _session_status(status)
        now = time.time()
        with self._lock, self._connect() as conn:
            existing = self._session_locked(conn, sid)
            if existing is None:
                raise KeyError(sid)
            next_owner = _optional_text(owner_id, max_len=256) if owner_id is not None else existing["owner_id"]
            next_label = (
                _optional_text(owner_label, max_len=512)
                if owner_label is not None
                else existing["owner_label"]
            )
            next_meta = dict(existing.get("metadata") or {})
            if metadata:
                next_meta.update(_json_dict(metadata, label="metadata"))
            if reason:
                next_meta["last_reason"] = _optional_text(reason, max_len=1024)
            takeover_count = int(existing.get("takeover_count") or 0) + (1 if takeover else 0)
            conn.execute(
                "UPDATE control_sessions SET owner_id=?, owner_label=?, status=?, paused=?, "
                "takeover_count=?, metadata_json=?, updated_at=? WHERE session_id=?",
                (
                    next_owner or "agent",
                    next_label or next_owner or "agent",
                    normalized,
                    1 if normalized == "paused" else 0,
                    takeover_count,
                    _dump(next_meta, label="metadata"),
                    now,
                    sid,
                ),
            )
            session = self._session_locked(conn, sid)
            self._event_locked(conn, sid, f"session_{normalized}", {"session": session, "reason": reason})
            return session

    def append_action(
        self,
        session_id: str,
        *,
        action_id: str | None = None,
        action_type: str = "action",
        descriptor: dict[str, Any] | None = None,
        status: str = "queued",
        surface: str | None = None,
        target_id: str | None = None,
        ttl_seconds: float | None = None,
    ) -> dict[str, Any]:
        sid = _require_id(session_id, label="session_id")
        aid = _require_id(action_id or f"action-{uuid4().hex[:16]}", label="action_id")
        normalized_status = _action_status(status)
        action_name = _optional_text(action_type or "action", max_len=128) or "action"
        desc = _json_dict(descriptor or {}, label="descriptor")
        now = time.time()
        expires_at = now + float(ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None
        with self._lock, self._connect() as conn:
            session = self._session_locked(conn, sid)
            if session is None:
                raise KeyError(sid)
            surf = _surface(surface or session["surface"])
            target = _optional_text(target_id if target_id is not None else session["target_id"], max_len=512)
            started_at = now if normalized_status == "running" else None
            completed_at = now if normalized_status in {"done", "failed", "cancelled", "expired"} else None
            conn.execute(
                "INSERT INTO control_actions("
                "action_id, session_id, surface, target_id, action_type, status, "
                "descriptor_json, result_json, error, queued_at, started_at, completed_at, expires_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(action_id) DO UPDATE SET "
                "status=excluded.status, descriptor_json=excluded.descriptor_json, "
                "started_at=COALESCE(control_actions.started_at, excluded.started_at), "
                "completed_at=excluded.completed_at, expires_at=excluded.expires_at",
                (
                    aid,
                    sid,
                    surf,
                    target or "default",
                    action_name,
                    normalized_status,
                    _dump(desc, label="descriptor"),
                    "{}",
                    "",
                    now,
                    started_at,
                    completed_at,
                    expires_at,
                ),
            )
            self._touch_session_locked(conn, sid, self._status_for_action(normalized_status))
            action = self._action_locked(conn, aid)
            self._event_locked(conn, sid, "action_appended", action)
            return action

    def update_action(
        self,
        session_id: str,
        action_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error: str = "",
    ) -> dict[str, Any]:
        sid = _require_id(session_id, label="session_id")
        aid = _require_id(action_id, label="action_id")
        normalized_status = _action_status(status)
        now = time.time()
        result_payload = _json_dict(result or {}, label="result")
        err = _optional_text(error, max_len=4096)
        with self._lock, self._connect() as conn:
            action = self._action_locked(conn, aid)
            if action is None or action["session_id"] != sid:
                raise KeyError(aid)
            conn.execute(
                "UPDATE control_actions SET status=?, result_json=?, error=?, "
                "started_at=COALESCE(started_at, ?), "
                "completed_at=? WHERE action_id=?",
                (
                    normalized_status,
                    _dump(result_payload, label="result"),
                    err,
                    now if normalized_status == "running" else None,
                    now if normalized_status in {"done", "failed", "cancelled", "expired"} else None,
                    aid,
                ),
            )
            self._touch_session_locked(conn, sid, self._status_for_action(normalized_status))
            updated = self._action_locked(conn, aid)
            self._event_locked(conn, sid, "action_updated", updated)
            return updated

    def append_evidence(
        self,
        session_id: str,
        *,
        evidence_id: str | None = None,
        action_id: str = "",
        kind: str = "log",
        action: str = "",
        ok: bool | None = None,
        summary: str = "",
        detail: dict[str, Any] | None = None,
        created_at: float | None = None,
    ) -> dict[str, Any]:
        sid = _require_id(session_id, label="session_id")
        eid = _require_id(evidence_id or f"evidence-{uuid4().hex[:16]}", label="evidence_id")
        aid = _require_id(action_id, label="action_id") if action_id else ""
        normalized_kind = _evidence_kind(kind)
        action_name = _optional_text(action or "", max_len=128)
        text = _optional_text(summary or "", max_len=4096)
        payload = _json_dict(detail or {}, label="detail")
        ts = float(created_at or time.time())
        ok_value = None if ok is None else (1 if ok else 0)
        with self._lock, self._connect() as conn:
            if self._session_locked(conn, sid) is None:
                raise KeyError(sid)
            row = conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM control_evidence WHERE session_id=?",
                (sid,),
            ).fetchone()
            seq = int(row[0] if row else 1)
            conn.execute(
                "INSERT INTO control_evidence("
                "evidence_id, session_id, action_id, seq, kind, action_type, ok, summary, detail_json, created_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    eid,
                    sid,
                    aid,
                    seq,
                    normalized_kind,
                    action_name,
                    ok_value,
                    text,
                    _dump(payload, label="detail"),
                    ts,
                ),
            )
            self._touch_session_locked(conn, sid)
            evidence = self._evidence_locked(conn, eid)
            self._event_locked(conn, sid, "evidence_appended", evidence)
            return evidence

    def replay(self, session_id: str, *, limit: int = 500) -> dict[str, Any]:
        sid = _require_id(session_id, label="session_id")
        limit = max(1, min(5000, int(limit)))
        with self._lock, self._connect() as conn:
            self._expire_locked(conn, sid)
            self._expire_actions_locked(conn, sid)
            session = self._session_locked(conn, sid)
            if session is None:
                raise KeyError(sid)
            actions = [
                _row_to_action(row)
                for row in conn.execute(
                    "SELECT action_id, session_id, surface, target_id, action_type, status, "
                    "descriptor_json, result_json, error, queued_at, started_at, completed_at, expires_at "
                    "FROM control_actions WHERE session_id=? ORDER BY queued_at ASC LIMIT ?",
                    (sid, limit),
                ).fetchall()
            ]
            evidence = [
                _row_to_evidence(row)
                for row in conn.execute(
                    "SELECT evidence_id, session_id, action_id, seq, kind, action_type, ok, summary, "
                    "detail_json, created_at FROM control_evidence "
                    "WHERE session_id=? ORDER BY seq ASC LIMIT ?",
                    (sid, limit),
                ).fetchall()
            ]
        return {
            "schema": "octopus.control_session_replay.v1",
            "session": session,
            "actions": actions,
            "evidence": evidence,
            "playwright_script": self._playwright_script(session, actions),
        }

    def events_after(self, session_id: str, *, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        sid = _require_id(session_id, label="session_id")
        limit = max(1, min(500, int(limit)))
        with self._lock, self._connect() as conn:
            self._expire_locked(conn, sid)
            self._expire_actions_locked(conn, sid)
            rows = conn.execute(
                "SELECT event_seq, event_type, payload_json, created_at FROM control_events "
                "WHERE session_id=? AND event_seq>? ORDER BY event_seq ASC LIMIT ?",
                (sid, int(after), limit),
            ).fetchall()
        return [
            {
                "seq": int(row[0]),
                "type": row[1],
                "payload": _load(row[2]),
                "created_at": float(row[3]),
            }
            for row in rows
        ]

    def _session_locked(self, conn: sqlite3.Connection, session_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT session_id, owner_id, owner_label, surface, target_id, status, paused, "
            "takeover_count, metadata_json, created_at, updated_at, expires_at "
            "FROM control_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        return _row_to_session(row) if row else None

    def _action_locked(self, conn: sqlite3.Connection, action_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT action_id, session_id, surface, target_id, action_type, status, "
            "descriptor_json, result_json, error, queued_at, started_at, completed_at, expires_at "
            "FROM control_actions WHERE action_id=?",
            (action_id,),
        ).fetchone()
        return _row_to_action(row) if row else None

    def _evidence_locked(self, conn: sqlite3.Connection, evidence_id: str) -> dict[str, Any] | None:
        row = conn.execute(
            "SELECT evidence_id, session_id, action_id, seq, kind, action_type, ok, summary, "
            "detail_json, created_at FROM control_evidence WHERE evidence_id=?",
            (evidence_id,),
        ).fetchone()
        return _row_to_evidence(row) if row else None

    def _touch_session_locked(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        status: str | None = None,
    ) -> None:
        now = time.time()
        if status:
            conn.execute(
                "UPDATE control_sessions SET status=?, paused=?, updated_at=? WHERE session_id=?",
                (status, 1 if status == "paused" else 0, now, session_id),
            )
        else:
            conn.execute(
                "UPDATE control_sessions SET updated_at=? WHERE session_id=?",
                (now, session_id),
            )

    def _event_locked(
        self,
        conn: sqlite3.Connection,
        session_id: str,
        event_type: str,
        payload: dict[str, Any] | None,
    ) -> None:
        conn.execute(
            "INSERT INTO control_events(session_id, event_type, payload_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            (
                session_id,
                _optional_text(event_type, max_len=128) or "event",
                _dump(payload or {}, label="event payload"),
                time.time(),
            ),
        )

    def _expire_locked(self, conn: sqlite3.Connection, session_id: str) -> None:
        row = conn.execute(
            "SELECT status, expires_at FROM control_sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row:
            return
        expires_at = row[1]
        if expires_at is not None and float(expires_at) <= time.time() and row[0] != "expired":
            conn.execute(
                "UPDATE control_sessions SET status='expired', paused=1, updated_at=? WHERE session_id=?",
                (time.time(), session_id),
            )
            self._event_locked(conn, session_id, "session_expired", {"session_id": session_id})

    def _expire_actions_locked(self, conn: sqlite3.Connection, session_id: str | None = None) -> None:
        now = time.time()
        params: list[Any] = [now]
        where = "expires_at IS NOT NULL AND expires_at<=? AND status NOT IN ('done', 'failed', 'cancelled', 'expired')"
        if session_id is not None:
            where += " AND session_id=?"
            params.append(session_id)
        rows = conn.execute(
            "SELECT action_id, session_id, surface, target_id, action_type, status, "
            "descriptor_json, result_json, error, queued_at, started_at, completed_at, expires_at "
            f"FROM control_actions WHERE {where}",
            tuple(params),
        ).fetchall()
        for row in rows:
            action = _row_to_action(row)
            conn.execute(
                "UPDATE control_actions SET status='expired', error=?, completed_at=? "
                "WHERE action_id=?",
                ("action expired", now, action["action_id"]),
            )
            self._touch_session_locked(conn, str(action["session_id"]), "paused")
            action["status"] = "expired"
            action["error"] = "action expired"
            action["completed_at"] = now
            self._event_locked(
                conn,
                str(action["session_id"]),
                "action_expired",
                {"action": action},
            )

    def _expire_all_locked(self, conn: sqlite3.Connection) -> None:
        rows = conn.execute(
            "SELECT session_id FROM control_sessions "
            "WHERE expires_at IS NOT NULL AND expires_at<=? AND status!='expired'",
            (time.time(),),
        ).fetchall()
        for row in rows:
            self._expire_locked(conn, str(row[0]))
        self._expire_actions_locked(conn)

    def _status_for_action(self, action_status: str) -> str:
        if action_status == "waiting_user":
            return "awaiting_confirmation"
        if action_status == "running":
            return "running"
        if action_status in {"failed", "cancelled", "expired"}:
            return "paused" if action_status == "expired" else "idle"
        return "idle"

    def _playwright_script(self, session: dict[str, Any], actions: list[dict[str, Any]]) -> str:
        lines = [
            "// Generated from octopus.control_session_replay.v1",
            "import { test, expect } from '@playwright/test';",
            "",
            f"test('replay {session['session_id']}', async ({{ page }}) => {{",
        ]
        for action in actions:
            descriptor = action.get("descriptor") if isinstance(action.get("descriptor"), dict) else {}
            action_type = str(action.get("action_type") or descriptor.get("type") or "")
            if action_type == "navigate" and descriptor.get("url"):
                lines.append(f"  await page.goto({json.dumps(str(descriptor['url']))});")
            elif action_type == "click" and descriptor.get("selector"):
                lines.append(f"  await page.click({json.dumps(str(descriptor['selector']))});")
            elif action_type == "type" and descriptor.get("selector"):
                lines.append(
                    "  await page.fill("
                    f"{json.dumps(str(descriptor['selector']))}, "
                    f"{json.dumps(str(descriptor.get('text') or ''))}"
                    ");"
                )
            else:
                lines.append(f"  // {action_type or 'action'} {json.dumps(descriptor, ensure_ascii=False)}")
        lines.append("  expect(true).toBeTruthy();")
        lines.append("});")
        return "\n".join(lines)


__all__ = [
    "ControlSessionStore",
]
