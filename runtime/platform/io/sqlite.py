"""SQLite connections whose transaction context also closes the handle.

The standard ``sqlite3.Connection`` context manager commits or rolls back but
does not close the connection. Short-lived stores in tests and request-scoped
application factories therefore accumulate descriptors unless every caller
adds a second ``closing(...)`` wrapper. This factory makes the safe lifecycle
the default while preserving normal sqlite transaction semantics.
"""

from __future__ import annotations

import sqlite3
from os import PathLike
from typing import Any


class ClosingConnection(sqlite3.Connection):
    """Commit/rollback and then close when leaving a ``with`` block."""

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> bool:
        try:
            return bool(super().__exit__(exc_type, exc, traceback))
        finally:
            self.close()


def connect_closing(
    database: str | bytes | PathLike[str],
    *args: Any,
    **kwargs: Any,
) -> ClosingConnection:
    """Open a connection that always closes after its transaction context."""

    kwargs["factory"] = ClosingConnection
    return sqlite3.connect(database, *args, **kwargs)


__all__ = ["ClosingConnection", "connect_closing"]
