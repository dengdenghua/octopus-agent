"""Cross-process serialization for full-snapshot thread mutations."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO


@dataclass(frozen=True, slots=True)
class PersistedThread:
    found: bool
    thread: dict[str, Any] | None
    revision: int = 0
    source_path: Path | None = None


def _lock_root(journal_path: Path | None, per_agent_base: Path | None) -> Path | None:
    if per_agent_base is not None:
        return per_agent_base / "data" / "sessions" / ".thread-mutation-locks"
    if journal_path is not None:
        return journal_path.parent / f".{journal_path.name}.thread-mutation-locks"
    return None


def _lock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        msvcrt.locking(  # type: ignore[attr-defined]
            handle.fileno(),
            msvcrt.LK_LOCK,  # type: ignore[attr-defined]
            1,
        )
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(  # type: ignore[attr-defined]
            handle.fileno(),
            msvcrt.LK_UNLCK,  # type: ignore[attr-defined]
            1,
        )
        return
    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def thread_mutation_lock(
    *,
    journal_path: Path | None,
    per_agent_base: Path | None,
    thread_id: str,
) -> Iterator[None]:
    """Hold one authoritative lock for a logical thread across processes."""

    root = _lock_root(journal_path, per_agent_base)
    if root is None:
        yield
        return
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(thread_id.encode("utf-8")).hexdigest()
    path = root / f"{digest}.lock"
    with path.open("a+b") as handle:
        try:
            _lock_file(handle)
        except (ImportError, OSError) as exc:
            raise RuntimeError("thread mutation lock unavailable") from exc
        try:
            yield
        finally:
            _unlock_file(handle)


def _candidate_paths(
    journal_path: Path | None,
    per_agent_base: Path | None,
    thread_id: str,
) -> list[Path]:
    if journal_path is not None:
        return [journal_path] if journal_path.exists() else []
    if per_agent_base is None or not per_agent_base.exists():
        return []
    filename = f"{thread_id}.jsonl"
    roots = [per_agent_base / "data" / "sessions" / "misc"]
    roots.extend(path / "sessions" for path in (per_agent_base / "agents").glob("*"))
    roots.extend(path / "sessions" for path in (per_agent_base / "teams").glob("*"))
    return [
        path
        for root in roots
        if root.exists()
        for path in root.rglob("*.jsonl")
        if path.name == filename
    ]


def latest_persisted_thread(
    *,
    journal_path: Path | None,
    per_agent_base: Path | None,
    thread_id: str,
) -> PersistedThread:
    """Read the newest durable operation for ``thread_id`` while its lock is held."""

    candidates: list[tuple[int, str, str, dict[str, Any] | None, Path]] = []
    for path in _candidate_paths(journal_path, per_agent_base, thread_id):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in reversed(lines):
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(record, dict) or record.get("thread_id") != thread_id:
                continue
            raw_revision = record.get("revision")
            revision = raw_revision if isinstance(raw_revision, int) and raw_revision >= 0 else 0
            operation_at = str(record.get("operation_at") or "")
            if record.get("op") == "delete":
                candidates.append((revision, operation_at, "", None, path))
                break
            thread = record.get("thread")
            if isinstance(thread, dict):
                candidates.append(
                    (
                        revision,
                        operation_at,
                        str(thread.get("updated_at") or ""),
                        thread,
                        path,
                    )
                )
                break
    if not candidates:
        return PersistedThread(found=False, thread=None)
    revision, _operation_at, _updated, thread, source_path = max(
        candidates,
        key=lambda item: (item[0], item[1], item[2], str(item[4])),
    )
    return PersistedThread(
        found=True,
        thread=thread,
        revision=revision,
        source_path=source_path,
    )


def remove_stale_thread_copies(
    *,
    journal_path: Path | None,
    per_agent_base: Path | None,
    thread_id: str,
    keep_path: Path | None,
) -> None:
    """Keep exactly one per-agent journal after a serialized mutation."""

    if per_agent_base is None or keep_path is None:
        return
    for path in _candidate_paths(journal_path, per_agent_base, thread_id):
        if path == keep_path:
            continue
        path.unlink(missing_ok=True)


__all__ = [
    "PersistedThread",
    "latest_persisted_thread",
    "remove_stale_thread_copies",
    "thread_mutation_lock",
]
