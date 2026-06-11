"""
runtime.platform.io · low-level filesystem primitives.

Shared primitives for durable file I/O. Keep this module dependency-free
(stdlib only) so anything in runtime/* can import from it without cycles.
"""

from __future__ import annotations

from runtime.platform.io.atomic import (
    AtomicWriteError,
    atomic_write_bytes,
    atomic_write_json,
    atomic_write_text,
    debounced_json_writer,
    read_json_with_backup,
)

__all__ = [
    "AtomicWriteError",
    "atomic_write_bytes",
    "atomic_write_json",
    "atomic_write_text",
    "debounced_json_writer",
    "read_json_with_backup",
]
