from __future__ import annotations

import json
import logging
import os
import re
import sqlite3
import threading
import time
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

ChannelHealth = Literal["unknown", "healthy", "degraded", "unsupported"]

_SCHEMA_VERSION = 1
_MAX_FILE_BYTES = 1_000_000
_MAX_SEEN_PER_CHANNEL = 2_048
_INBOUND_LEASE_SECONDS = 600.0
logger = logging.getLogger(__name__)

_SECRET_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._~+\-/=]{8,}"),
    re.compile(r"(?i)\b(sk-[a-z0-9_-]{8})[a-z0-9_-]+"),
    re.compile(
        r"(?i)((?:token|secret|password|api[_-]?key)\s*[=:]\s*)"
        r"([^\s,;]{4})[^\s,;]+"
    ),
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _empty_state() -> dict[str, Any]:
    return {
        "health_status": "unknown",
        "last_checked_at": None,
        "check_latency_ms": None,
        "last_inbound_at": None,
        "last_outbound_at": None,
        "last_error_at": None,
        "last_error": None,
        "inbound_count": 0,
        "outbound_count": 0,
        "failure_count": 0,
        "duplicate_count": 0,
    }


def _sanitize_error(error: BaseException | str) -> str:
    summary = str(error).replace("\n", " ").strip()
    for pattern in _SECRET_PATTERNS:
        summary = pattern.sub(r"\1***", summary)
    return summary[:500] or type(error).__name__


class ChannelOperationsStore:
    """Durable, bounded operational state for external message channels.

    Credentials and message bodies never enter this store.  It only retains
    counters, timestamps, the latest sanitized exception summary, and the
    result of an explicit health probe so operators can distinguish
    "configured" from "actually working" after a restart.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path is not None else None
        self._lock = threading.RLock()
        self._channels: dict[str, dict[str, Any]] = {}
        self._seen: dict[str, list[str]] = {}
        self._seen_db: sqlite3.Connection | None = None
        self._load()
        self._open_seen_db()

    def snapshot(self, channel_id: str) -> dict[str, Any]:
        with self._lock:
            return dict(self._channels.get(channel_id, _empty_state()))

    def record_inbound(self, channel_id: str) -> None:
        with self._lock:
            state = self._state(channel_id)
            state["last_inbound_at"] = _now()
            state["inbound_count"] += 1
            self._save()

    def record_outbound(self, channel_id: str) -> None:
        with self._lock:
            state = self._state(channel_id)
            state["last_outbound_at"] = _now()
            state["outbound_count"] += 1
            state["health_status"] = "healthy"
            self._save()

    def record_error(self, channel_id: str, error: BaseException | str) -> None:
        with self._lock:
            state = self._state(channel_id)
            state["last_error_at"] = _now()
            state["health_status"] = "degraded"
            # Keep diagnostics useful without allowing an adapter to grow the
            # state file or persist a full credential-bearing response body.
            state["last_error"] = _sanitize_error(error)
            state["failure_count"] += 1
            self._save()

    def record_probe(
        self,
        channel_id: str,
        *,
        healthy: bool | None,
        latency_ms: int,
        error: BaseException | str | None = None,
    ) -> None:
        with self._lock:
            state = self._state(channel_id)
            state["health_status"] = (
                "unsupported" if healthy is None else "healthy" if healthy else "degraded"
            )
            state["last_checked_at"] = _now()
            state["check_latency_ms"] = max(0, int(latency_ms))
            if healthy is True:
                state["last_error"] = None
            elif healthy is False and error is not None:
                state["last_error_at"] = _now()
                state["last_error"] = _sanitize_error(error)
                state["failure_count"] += 1
            self._save()

    def claim_inbound(self, channel_id: str, message_key: str) -> bool:
        """Atomically claim a provider event, storing only its SHA-256 digest."""
        if not message_key:
            return True
        digest = sha256(message_key.encode("utf-8", errors="replace")).hexdigest()
        with self._lock:
            if self._seen_db is not None:
                try:
                    now = time.time()
                    with self._seen_db:
                        cursor = self._seen_db.execute(
                            "INSERT OR IGNORE INTO channel_seen"
                            "(channel_id,digest,status,lease_expires_at) VALUES (?,?,'processing',?)",
                            (channel_id, digest, now + _INBOUND_LEASE_SECONDS),
                        )
                        claimed = cursor.rowcount == 1
                        if not claimed:
                            cursor = self._seen_db.execute(
                                "UPDATE channel_seen SET status='processing',lease_expires_at=? "
                                "WHERE channel_id=? AND digest=? AND status='processing' "
                                "AND lease_expires_at<=?",
                                (
                                    now + _INBOUND_LEASE_SECONDS,
                                    channel_id,
                                    digest,
                                    now,
                                ),
                            )
                            claimed = cursor.rowcount == 1
                        if claimed:
                            self._seen_db.execute(
                                "DELETE FROM channel_seen WHERE channel_id=? AND seq NOT IN "
                                "(SELECT seq FROM channel_seen WHERE channel_id=? "
                                "ORDER BY seq DESC LIMIT ?)",
                                (channel_id, channel_id, _MAX_SEEN_PER_CHANNEL),
                            )
                    if claimed:
                        return True
                    state = self._state(channel_id)
                    state["duplicate_count"] += 1
                    self._save()
                    return False
                except sqlite3.Error as exc:
                    logger.warning("channel dedup store failed; using memory fallback: %s", exc)
            seen = self._seen.setdefault(channel_id, [])
            if digest in seen:
                state = self._state(channel_id)
                state["duplicate_count"] += 1
                self._save()
                return False
            seen.append(digest)
            if len(seen) > _MAX_SEEN_PER_CHANNEL:
                del seen[: len(seen) - _MAX_SEEN_PER_CHANNEL]
            return True

    def complete_inbound(self, channel_id: str, message_key: str) -> None:
        """Mark a claimed provider event complete after outbound delivery."""
        if not message_key:
            return
        digest = sha256(message_key.encode("utf-8", errors="replace")).hexdigest()
        with self._lock:
            if self._seen_db is not None:
                try:
                    with self._seen_db:
                        self._seen_db.execute(
                            "UPDATE channel_seen SET status='done',lease_expires_at=NULL "
                            "WHERE channel_id=? AND digest=?",
                            (channel_id, digest),
                        )
                    return
                except sqlite3.Error as exc:
                    logger.warning("channel dedup completion failed: %s", exc)

    def release_inbound(self, channel_id: str, message_key: str) -> None:
        """Release an event claim when processing failed before delivery.

        Providers retry webhook delivery after transient model or network
        failures.  Keeping a failed event in the idempotency set would turn
        that retry into a silent drop, so claims are removed on the error path.
        """
        if not message_key:
            return
        digest = sha256(message_key.encode("utf-8", errors="replace")).hexdigest()
        with self._lock:
            if self._seen_db is not None:
                try:
                    with self._seen_db:
                        self._seen_db.execute(
                            "DELETE FROM channel_seen WHERE channel_id=? AND digest=?",
                            (channel_id, digest),
                        )
                    return
                except sqlite3.Error as exc:
                    logger.warning("channel dedup release failed: %s", exc)
            seen = self._seen.get(channel_id)
            if not seen or digest not in seen:
                return
            self._seen[channel_id] = [value for value in seen if value != digest]
            if not self._seen[channel_id]:
                self._seen.pop(channel_id, None)

    def _state(self, channel_id: str) -> dict[str, Any]:
        if not channel_id:
            raise ValueError("channel_id must be non-empty")
        return self._channels.setdefault(channel_id, _empty_state())

    def _load(self) -> None:
        path = self._path
        if path is None or not path.exists():
            return
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                return
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict) or payload.get("version") != _SCHEMA_VERSION:
            return
        raw_channels = payload.get("channels")
        if not isinstance(raw_channels, dict):
            return
        for channel_id, raw in raw_channels.items():
            if not isinstance(channel_id, str) or not isinstance(raw, dict):
                continue
            state = _empty_state()
            for key in state:
                if key in raw:
                    state[key] = raw[key]
            if state["health_status"] not in {
                "unknown",
                "healthy",
                "degraded",
                "unsupported",
            }:
                state["health_status"] = "unknown"
            for key in (
                "inbound_count",
                "outbound_count",
                "failure_count",
                "duplicate_count",
            ):
                value = state[key]
                state[key] = max(0, int(value)) if isinstance(value, (int, float)) else 0
            self._channels[channel_id] = state

    def _open_seen_db(self) -> None:
        if self._path is None:
            return
        db_path = self._path.with_suffix(self._path.suffix + ".seen.sqlite3")
        try:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(db_path, check_same_thread=False, timeout=5.0)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS channel_seen ("
                "seq INTEGER PRIMARY KEY AUTOINCREMENT,"
                "channel_id TEXT NOT NULL,"
                "digest TEXT NOT NULL,"
                "status TEXT NOT NULL DEFAULT 'processing',"
                "lease_expires_at REAL,"
                "UNIQUE(channel_id,digest))"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_channel_seen_recent "
                "ON channel_seen(channel_id,seq DESC)"
            )
            connection.commit()
            self._seen_db = connection
        except (OSError, sqlite3.Error) as exc:
            logger.warning("channel dedup store unavailable; using memory fallback: %s", exc)

    def _save(self) -> None:
        path = self._path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(
                    {
                        "version": _SCHEMA_VERSION,
                        "channels": self._channels,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            os.replace(tmp, path)
        except OSError as exc:
            # Telemetry must never take down the actual message path.
            logger.warning("channel operations save failed: %s", exc)
