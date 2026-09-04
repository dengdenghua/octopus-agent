from __future__ import annotations

import json
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

ChannelHealth = Literal["unknown", "healthy", "degraded", "unsupported"]

_SCHEMA_VERSION = 1
_MAX_FILE_BYTES = 1_000_000


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
    }


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
        self._load()

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
            summary = str(error).replace("\n", " ").strip()
            state["last_error"] = summary[:500] or type(error).__name__
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
                summary = str(error).replace("\n", " ").strip()
                state["last_error_at"] = _now()
                state["last_error"] = summary[:500] or type(error).__name__
                state["failure_count"] += 1
            self._save()

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
            for key in ("inbound_count", "outbound_count", "failure_count"):
                value = state[key]
                state[key] = max(0, int(value)) if isinstance(value, (int, float)) else 0
            self._channels[channel_id] = state

    def _save(self) -> None:
        path = self._path
        if path is None:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"version": _SCHEMA_VERSION, "channels": self._channels},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(tmp, path)
