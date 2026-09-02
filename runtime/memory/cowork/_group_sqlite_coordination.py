"""SQLite journal invariants for atomic Group lifecycle transactions."""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import closing, contextmanager
from pathlib import Path

_DRAIN_MESSAGE = "group storage journal migration requires draining older WAL workers"
_LOCKS_GUARD = threading.Lock()
_STORAGE_LOCKS: dict[str, threading.Lock] = {}


def _storage_thread_lock(base_dir: Path) -> threading.Lock:
    key = str(base_dir.resolve())
    with _LOCKS_GUARD:
        return _STORAGE_LOCKS.setdefault(key, threading.Lock())


@contextmanager
def cowork_storage_write_lock(base_dir: Path | str) -> Iterator[None]:
    """Serialize cross-database cowork writes in one stable lock order.

    SQLite acquires the main database before attached databases. Cowork
    completion uses ``async_work.db`` as main while thread deletion uses
    ``group_events.db`` as main, so two concurrent transactions can otherwise
    form an AB/BA lock cycle and eventually raise ``database is locked``.
    A directory-scoped advisory lock prevents that cycle across threads and
    processes without imposing a wall-clock timeout.
    """

    root = Path(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".cowork-storage-write.lock"
    thread_lock = _storage_thread_lock(root)
    with thread_lock, lock_path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt

            handle.seek(0, 2)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)  # type: ignore[attr-defined]
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(  # type: ignore[attr-defined]
                    handle.fileno(),
                    msvcrt.LK_UNLCK,  # type: ignore[attr-defined]
                    1,
                )
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def migrate_delete_journals(paths: Iterable[Path]) -> None:
    """Migrate closed legacy WAL databases; fail closed while old workers live."""

    for path in paths:
        if not path.exists():
            continue
        try:
            with closing(sqlite3.connect(str(path), timeout=0.25)) as conn:
                conn.execute("PRAGMA busy_timeout=250")
                checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint is not None and int(checkpoint[0] or 0) != 0:
                    raise RuntimeError(_DRAIN_MESSAGE)
                mode = conn.execute("PRAGMA journal_mode=DELETE").fetchone()
                conn.execute("PRAGMA synchronous=FULL")
        except RuntimeError:
            raise
        except sqlite3.Error as exc:
            raise RuntimeError(_DRAIN_MESSAGE) from exc
        if mode is None or str(mode[0]).lower() != "delete":
            raise RuntimeError(_DRAIN_MESSAGE)


def require_delete_journals(conn: sqlite3.Connection, schemas: Iterable[str]) -> None:
    """Verify every participant immediately before a multi-DB transaction."""

    for schema in schemas:
        if not schema.replace("_", "").isalnum():
            raise ValueError(f"invalid SQLite schema name: {schema!r}")
        try:
            row = conn.execute(  # nosec B608 - validated schema identifier
                f"PRAGMA {schema}.journal_mode=DELETE"
            ).fetchone()
        except sqlite3.Error as exc:
            raise RuntimeError(_DRAIN_MESSAGE) from exc
        if row is None or str(row[0]).lower() != "delete":
            raise RuntimeError(_DRAIN_MESSAGE)
        conn.execute(f"PRAGMA {schema}.synchronous=FULL")  # nosec B608 - validated
        synchronous = conn.execute(f"PRAGMA {schema}.synchronous").fetchone()  # nosec B608
        if synchronous is None or int(synchronous[0]) != 2:
            raise RuntimeError("group storage requires FULL SQLite synchronization")


__all__ = [
    "cowork_storage_write_lock",
    "migrate_delete_journals",
    "require_delete_journals",
]
