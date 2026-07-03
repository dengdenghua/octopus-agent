from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_LEASE_METADATA_KEY = "_file_write_leases"
_HANDOFF_METADATA_KEY = "_file_write_lease_handoffs"
_HISTORY_METADATA_KEY = "_file_write_lease_history"
_LOCK = threading.RLock()


class FileWriteLeaseConflict(PermissionError):
    """Raised when another owner already controls a file for this turn."""


@dataclass(frozen=True)
class FileWriteLease:
    path: str
    owner: str
    acquired_at: float
    reentrant: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "owner": self.owner,
            "acquired_at": self.acquired_at,
            "reentrant": self.reentrant,
        }


def acquire_file_write_lease(
    session: Any,
    path: str | Path | None,
    *,
    owner: str,
) -> FileWriteLease | None:
    """Acquire a per-turn file write lease.

    The lease table lives in ``Session.metadata`` so it naturally expires
    with the turn. Same-owner writes are reentrant; cross-owner writes to
    the same canonical path fail before touching the filesystem.
    """

    if session is None or path is None:
        return None
    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        return None
    path_key = canonical_write_path_key(path)
    if not path_key:
        return None
    clean_owner = str(owner or "unknown").strip() or "unknown"

    with _LOCK:
        leases = metadata.get(_LEASE_METADATA_KEY)
        if not isinstance(leases, dict):
            leases = {}
            metadata[_LEASE_METADATA_KEY] = leases
        existing = leases.get(path_key)
        if isinstance(existing, dict):
            existing_owner = str(existing.get("owner") or "")
            if existing_owner and existing_owner != clean_owner:
                if _consume_handoff(
                    metadata,
                    path_key,
                    from_owner=existing_owner,
                    to_owner=clean_owner,
                ):
                    _append_history(
                        metadata,
                        event="handoff_consumed",
                        path=path_key,
                        owner=clean_owner,
                        from_owner=existing_owner,
                        to_owner=clean_owner,
                    )
                    lease = FileWriteLease(
                        path=path_key,
                        owner=clean_owner,
                        acquired_at=time.time(),
                    )
                    leases[path_key] = lease.to_dict()
                    return lease
                _append_history(
                    metadata,
                    event="conflict",
                    path=path_key,
                    owner=existing_owner,
                    requester=clean_owner,
                )
                raise FileWriteLeaseConflict(
                    "file_write_lease_conflict:"
                    f"{path_key}:owner={existing_owner}:requester={clean_owner}"
                )
            lease = FileWriteLease(
                path=path_key,
                owner=clean_owner,
                acquired_at=float(existing.get("acquired_at") or time.time()),
                reentrant=True,
            )
            leases[path_key] = lease.to_dict()
            _append_history(
                metadata,
                event="reentrant",
                path=path_key,
                owner=clean_owner,
            )
            return lease

        lease = FileWriteLease(
            path=path_key,
            owner=clean_owner,
            acquired_at=time.time(),
        )
        leases[path_key] = lease.to_dict()
        _append_history(
            metadata,
            event="acquire",
            path=path_key,
            owner=clean_owner,
        )
        return lease


def canonical_write_path_key(path: str | Path) -> str:
    raw = Path(path).expanduser()
    try:
        resolved = raw.resolve(strict=False)
    except OSError:
        resolved = raw.absolute()
    return str(resolved).casefold()


def authorize_file_write_handoff(
    session: Any,
    path: str | Path,
    *,
    from_owner: str,
    to_owner: str,
) -> bool:
    if session is None:
        return False
    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    path_key = canonical_write_path_key(path)
    source = str(from_owner or "").strip()
    target = str(to_owner or "").strip()
    if not path_key or not source or not target:
        return False
    with _LOCK:
        handoffs = metadata.get(_HANDOFF_METADATA_KEY)
        if not isinstance(handoffs, dict):
            handoffs = {}
            metadata[_HANDOFF_METADATA_KEY] = handoffs
        handoffs[path_key] = {
            "from_owner": source,
            "to_owner": target,
            "authorized_at": time.time(),
        }
        _append_history(
            metadata,
            event="handoff_authorized",
            path=path_key,
            owner=source,
            from_owner=source,
            to_owner=target,
        )
    return True


def release_file_write_lease(
    session: Any,
    path: str | Path,
    *,
    owner: str,
) -> bool:
    if session is None:
        return False
    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        return False
    path_key = canonical_write_path_key(path)
    clean_owner = str(owner or "").strip()
    if not path_key or not clean_owner:
        return False
    with _LOCK:
        leases = metadata.get(_LEASE_METADATA_KEY)
        if not isinstance(leases, dict):
            return False
        existing = leases.get(path_key)
        if not isinstance(existing, dict):
            return False
        if str(existing.get("owner") or "") != clean_owner:
            return False
        leases.pop(path_key, None)
        _append_history(
            metadata,
            event="release",
            path=path_key,
            owner=clean_owner,
        )
    return True


def file_write_lease_snapshot(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Return a JSON-safe snapshot of file write leases for observability."""

    if not isinstance(metadata, dict):
        metadata = {}
    leases_raw = metadata.get(_LEASE_METADATA_KEY)
    handoffs_raw = metadata.get(_HANDOFF_METADATA_KEY)
    history_raw = metadata.get(_HISTORY_METADATA_KEY)
    leases = _dict_values(leases_raw)
    handoffs = _dict_values(handoffs_raw)
    history = [
        dict(item)
        for item in (history_raw if isinstance(history_raw, list) else [])
        if isinstance(item, dict)
    ]
    return {
        "lease_count": len(leases),
        "pending_handoff_count": len(handoffs),
        "handoff_count": sum(
            1 for item in history if str(item.get("event") or "").startswith("handoff_")
        ),
        "conflict_count": sum(1 for item in history if item.get("event") == "conflict"),
        "leases": leases,
        "pending_handoffs": handoffs,
        "history": history,
    }


def _consume_handoff(
    metadata: dict[str, Any],
    path_key: str,
    *,
    from_owner: str,
    to_owner: str,
) -> bool:
    handoffs = metadata.get(_HANDOFF_METADATA_KEY)
    if not isinstance(handoffs, dict):
        return False
    handoff = handoffs.get(path_key)
    if not isinstance(handoff, dict):
        return False
    if (
        str(handoff.get("from_owner") or "") != from_owner
        or str(handoff.get("to_owner") or "") != to_owner
    ):
        return False
    handoffs.pop(path_key, None)
    return True


def _append_history(
    metadata: dict[str, Any],
    *,
    event: str,
    path: str,
    owner: str,
    **extra: Any,
) -> None:
    history = metadata.get(_HISTORY_METADATA_KEY)
    if not isinstance(history, list):
        history = []
        metadata[_HISTORY_METADATA_KEY] = history
    item: dict[str, Any] = {
        "event": event,
        "path": path,
        "owner": owner,
        "at": time.time(),
    }
    item.update({key: value for key, value in extra.items() if value is not None and value != ""})
    history.append(item)


def _dict_values(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, dict):
        return []
    return [dict(item) for item in value.values() if isinstance(item, dict)]


__all__ = [
    "FileWriteLease",
    "FileWriteLeaseConflict",
    "acquire_file_write_lease",
    "authorize_file_write_handoff",
    "canonical_write_path_key",
    "file_write_lease_snapshot",
    "release_file_write_lease",
]
