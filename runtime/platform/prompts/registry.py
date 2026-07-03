"""
runtime.platform.prompts.registry · hot-reload-capable prompt registry.

Why a second registry beside ``loader.PromptLoader``?
-----------------------------------------------------

The original ``PromptLoader`` (see ``runtime/platform/prompts/__init__.py``)
loads YAML files lazily, caches forever, and has no concept of variants.
That contract is shipped — call sites in ``runtime/core/cerebrum`` rely on
its lookup precedence — so we can't change it under their feet.

This module is additive: a new ``PromptRegistry`` aimed at the
**editable templates** under ``prompts/`` (Markdown).  The differences:

* Stores raw text (Markdown), not YAML-with-content-key.
* Supports *variants* — alternate phrasings of the same prompt — stored
  one directory deeper so the base directory stays uncluttered.  The
  layout is::

      prompts/
        system_prompt.md           ← base
        variants/
          system_prompt/
            friendly.md
            pragmatic.md

* Honors the ``ui.prompts_hot_reload`` feature flag.  When ON, ``get()``
  consults ``Path.stat().st_mtime_ns`` for every read and re-loads if the
  file is newer than the cached entry.  When OFF, the cache is sticky —
  even if you ``echo "..." > prompts/foo.md`` mid-process, ``get()`` keeps
  serving the version it loaded on first access.

* Round-trip writes via ``set()`` go through ``atomic_write_text`` so a
  crash mid-edit never produces a half-written prompt.  Every overwrite
  rotates the previous version to ``<file>.md.bak`` (free rollback).

* All public methods are thread-safe under a single ``RLock``.  Concurrent
  readers don't tear; a writer briefly stalls readers.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime.platform.io import atomic_write_text

_logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# Internal cache record
# ═══════════════════════════════════════════════════════════


@dataclass
class _Entry:
    """One cached prompt body + its source file's mtime (ns)."""

    content: str
    mtime_ns: int
    path: Path


class PromptRegistry:
    """A hot-reload-aware registry over a ``prompts/`` directory.

    Parameters
    ----------
    prompts_dir :
        Directory containing base ``*.md`` templates.  Created if it
        doesn't exist on first ``set()``.
    variants_dir :
        Optional override for the variants subtree.  Defaults to
        ``prompts_dir / "variants"``.

    Thread-safety
    -------------
    All public methods acquire ``self._lock`` (an ``RLock``).  Re-entry
    is fine (``get`` may call helpers that also lock).  Writers briefly
    block readers — that is acceptable for an editable-templates store
    that gets touched on the order of single-digit times per second.

    Hot-reload semantics
    --------------------
    ``get()`` and ``list()`` only re-stat the filesystem when
    ``feature_flags.is_on("ui.prompts_hot_reload")`` returns ``True``.
    With the flag OFF, in-memory cache wins absolutely — predictable
    perf, predictable behavior, no surprise reloads in production.
    """

    def __init__(
        self,
        prompts_dir: str | Path,
        *,
        variants_dir: str | Path | None = None,
    ) -> None:
        self._dir = Path(prompts_dir)
        self._variants_dir = (
            Path(variants_dir) if variants_dir is not None else self._dir / "variants"
        )
        self._lock = threading.RLock()
        # Two-level cache:
        #   (name, None)        → base file entry
        #   (name, "variant")   → variant file entry
        self._cache: dict[tuple[str, str | None], _Entry] = {}
        self._scanned = False

    # ───────────────────────────────────────────────────────
    # Internal helpers
    # ───────────────────────────────────────────────────────

    def _hot_reload_enabled(self) -> bool:
        """``ui.prompts_hot_reload`` flag check.  Imported lazily so the
        module loads even before flag registration in test contexts."""
        try:
            from runtime.platform import feature_flags as _ff
        except (
            ImportError,
            TypeError,
            AttributeError,
            OSError,
        ):  # pragma: no cover - belt and suspenders
            return False
        return _ff.is_on("ui.prompts_hot_reload")

    def _path_for(self, name: str, variant: str | None) -> Path:
        if variant is None:
            return self._dir / f"{name}.md"
        return self._variants_dir / name / f"{variant}.md"

    def _read_path(self, path: Path) -> _Entry | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            return None
        return _Entry(
            content=content,
            mtime_ns=stat.st_mtime_ns,
            path=path,
        )

    def _scan_locked(self) -> None:
        """Populate the cache from disk.  Caller must hold ``self._lock``.

        Idempotent: a second call replaces existing entries.
        """
        new_cache: dict[tuple[str, str | None], _Entry] = {}

        # Base prompts
        if self._dir.exists():
            for path in sorted(self._dir.glob("*.md")):
                if not path.is_file():
                    continue
                entry = self._read_path(path)
                if entry is not None:
                    new_cache[(path.stem, None)] = entry

        # Variants — one subdirectory per base name
        if self._variants_dir.exists():
            for name_dir in sorted(self._variants_dir.iterdir()):
                if not name_dir.is_dir():
                    continue
                base_name = name_dir.name
                for vpath in sorted(name_dir.glob("*.md")):
                    if not vpath.is_file():
                        continue
                    entry = self._read_path(vpath)
                    if entry is not None:
                        new_cache[(base_name, vpath.stem)] = entry

        self._cache = new_cache
        self._scanned = True

    def _ensure_scanned_locked(self) -> None:
        if not self._scanned:
            self._scan_locked()

    def _refresh_one_locked(
        self,
        name: str,
        variant: str | None,
    ) -> _Entry | None:
        """Re-stat the file for ``(name, variant)``; reload if mtime
        changed; return the (possibly fresh) entry, or ``None`` if the
        file is gone."""
        path = self._path_for(name, variant)
        try:
            stat = path.stat()
        except OSError:
            self._cache.pop((name, variant), None)
            return None

        cached = self._cache.get((name, variant))
        if cached is None or cached.mtime_ns != stat.st_mtime_ns:
            entry = self._read_path(path)
            if entry is not None:
                self._cache[(name, variant)] = entry
            return entry
        return cached

    # ───────────────────────────────────────────────────────
    # Public API
    # ───────────────────────────────────────────────────────

    def reload(self) -> None:
        """Force a full re-scan from disk, dropping the cache."""
        with self._lock:
            self._scan_locked()

    def get(self, name: str, variant: str | None = None) -> str:
        """Return the prompt body for ``name`` (optionally a variant).

        Variant fallback: if ``variant`` is given but no variant file
        exists, the base ``name`` is returned instead.  Raises
        ``KeyError`` only if neither variant nor base is registered.
        """
        with self._lock:
            self._ensure_scanned_locked()

            hot = self._hot_reload_enabled()

            # First try the variant (if requested)
            if variant is not None:
                if hot:
                    entry = self._refresh_one_locked(name, variant)
                    if entry is not None:
                        return entry.content
                else:
                    cached = self._cache.get((name, variant))
                    if cached is not None:
                        return cached.content
                # fall through to base

            # Base lookup
            if hot:
                entry = self._refresh_one_locked(name, None)
                if entry is not None:
                    return entry.content
            else:
                cached = self._cache.get((name, None))
                if cached is not None:
                    return cached.content

            raise KeyError(
                f"prompt {name!r}"
                + (f" (variant {variant!r})" if variant else "")
                + " not found in registry"
            )

    def list(self) -> list[dict[str, Any]]:
        """List registered prompts.

        Returns a list of dicts shaped::

            {
                "name": "system_prompt",
                "variants": ["friendly", "pragmatic"],
                "modified_at": 1234567890.123,  # base mtime, seconds
            }

        Variants are sorted alphabetically.  ``modified_at`` reflects
        the base file's mtime (or the most-recent variant if no base
        exists).  When the hot-reload flag is ON, this triggers a
        re-scan; otherwise it serves from cache.
        """
        with self._lock:
            self._ensure_scanned_locked()
            if self._hot_reload_enabled():
                self._scan_locked()

            # Bucket by base name
            buckets: dict[str, dict[str, Any]] = {}
            for (name, variant), entry in self._cache.items():
                bucket = buckets.setdefault(
                    name,
                    {"name": name, "variants": [], "modified_at": 0.0},
                )
                if variant is None:
                    bucket["modified_at"] = entry.mtime_ns / 1_000_000_000
                else:
                    bucket["variants"].append(variant)
                    # If no base, surface the variant mtime so callers
                    # have something useful.
                    if bucket["modified_at"] == 0.0:
                        bucket["modified_at"] = entry.mtime_ns / 1_000_000_000

            for bucket in buckets.values():
                bucket["variants"] = sorted(bucket["variants"])
            return sorted(
                buckets.values(),
                key=lambda b: b["name"],
            )

    def set(
        self,
        name: str,
        content: str,
        *,
        variant: str | None = None,
    ) -> None:
        """Write a prompt body to disk atomically and invalidate cache.

        Always uses ``atomic_write_text`` (durable, with ``.bak``
        rollover).  After the write, the cache entry is updated from
        the freshly-stat'd file so subsequent ``get()`` calls return
        the new content even if the hot-reload flag is OFF.
        """
        if not name or any(ch in name for ch in ("/", "\\", "..", "\x00")):
            raise ValueError(f"invalid prompt name {name!r}")
        if variant is not None and (
            not variant or any(ch in variant for ch in ("/", "\\", "..", "\x00"))
        ):
            raise ValueError(f"invalid variant name {variant!r}")

        path = self._path_for(name, variant)
        with self._lock:
            atomic_write_text(path, content)
            entry = self._read_path(path)
            if entry is None:
                # Extremely unlikely (we just wrote it) but guard.
                self._cache.pop((name, variant), None)
            else:
                self._cache[(name, variant)] = entry
            # Make sure list() reflects newly-introduced prompts
            # without forcing a full rescan.
            self._scanned = True


__all__ = ["PromptRegistry"]
