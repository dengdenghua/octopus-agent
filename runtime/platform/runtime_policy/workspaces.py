"""Per-thread isolated workspace directories.

Each realtime thread can get its own scratch workspace — a cwd under
``<data_dir>/workspaces/<thread_id>`` where tool calls default to
running. Two concurrent threads can't accidentally write to the
same file, ``git checkout`` in one thread doesn't yank the floor
out from under the other, and the whole workspace can be discarded
in one ``rmtree`` when the thread is archived.

Policy knobs:

* ``allocate(thread_id)``  — idempotent. Returns the Path, creating it
  with a ``.gitignore`` marker on first touch so the user can tell
  at-a-glance which directories are runtime-allocated.
* ``discard(thread_id)``   — best-effort cleanup. Safe to call on a
  non-existent workspace. Refuses to remove anything outside the
  configured root (guards against mistyped ``root``).
* ``resolve_cwd(thread_id, explicit_cwd)`` — helper the runtime uses
  at turn start. If the caller passes an explicit ``cwd`` (power user,
  single-shot script), that wins; otherwise we allocate.

Authenticated runtimes may bind a thread id to a deeper, server-verified
tenant/actor path with ``bind_managed``.  That binding is deliberately kept on
the app-local manager so every consumer (cwd, uploads and artifact outputs)
uses the same layout for the lifetime of the runtime.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

_logger = logging.getLogger(__name__)

MANAGED_WORKSPACE_MARKER = "server-v1"
MANAGED_WORKSPACE_METADATA_KEY = "_workspace_allocation"
MANAGED_WORKSPACE_DELETION_KEY = "_workspace_deletion"
MANAGED_WORKSPACE_DELETION_MARKER = "staged-v1"

# These fields are controlled exclusively by the server in authenticated mode.
# The shared policy lives below both execution and the HTTP gateway so neither
# layer needs to depend on the other to enforce the filesystem boundary.
PROTECTED_WORKSPACE_METADATA_KEYS = frozenset(
    {
        "workspace_path",
        "extra_workspaces",
        "personal_workspace_path",
        "allowed_write_paths",
        "attachment_read_roots",
        "_artifact_output_root",
        "cwd",
        MANAGED_WORKSPACE_METADATA_KEY,
        MANAGED_WORKSPACE_DELETION_KEY,
    }
)

_GITIGNORE_BODY = (
    "# Auto-created by octopus runtime — per-thread isolated workspace.\n"
    "# Safe to delete when the thread is archived.\n"
    "*\n"
    "!.gitignore\n"
    "!workspace.json\n"
    "!upload/\n"
    "!output/\n"
    "!deploy/\n"
    "!skills/\n"
)

_MANIFEST_NAME = "workspace.json"
_STANDARD_DIRS = (
    "upload",
    "output",
    "output/stages",
    "output/final",
    "deploy",
    "skills",
)


def strip_client_workspace_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Return client metadata without server-owned filesystem scope fields."""
    return {
        key: value
        for key, value in metadata.items()
        if key not in PROTECTED_WORKSPACE_METADATA_KEYS
    }


def _scope_segment(value: str) -> str:
    """Produce an opaque, traversal-safe stable path segment."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def managed_workspace_path(
    workspace_root: str | Path,
    *,
    tenant_id: str,
    actor_id: str,
    thread_id: str,
) -> Path:
    """Return the only valid server path for an authenticated thread."""
    root = Path(workspace_root).expanduser().resolve(strict=False)
    thread_segment = Path(thread_id)
    if (
        not thread_id
        or thread_segment.is_absolute()
        or len(thread_segment.parts) != 1
        or thread_segment.name != thread_id
    ):
        raise ValueError("thread id is not a safe workspace path segment")
    candidate = root / _scope_segment(tenant_id) / _scope_segment(actor_id) / thread_id
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError("managed workspace path escapes its root") from exc
    resolved = candidate.resolve(strict=False)
    if resolved != candidate:
        # Reject symlinks even when they redirect to another directory still
        # under workspace_root; otherwise one tenant could alias another.
        raise ValueError("managed workspace path contains a symlink")
    return candidate


def managed_workspace_metadata(
    workspace_root: str | Path,
    *,
    tenant_id: str,
    actor_id: str,
    thread_id: str,
) -> dict[str, str]:
    """Build the immutable metadata written after server allocation."""
    path = managed_workspace_path(
        workspace_root,
        tenant_id=tenant_id,
        actor_id=actor_id,
        thread_id=thread_id,
    )
    return {
        "workspace_path": str(path),
        MANAGED_WORKSPACE_METADATA_KEY: MANAGED_WORKSPACE_MARKER,
    }


def verified_managed_workspace(
    workspace_root: str | Path | None,
    *,
    thread_id: str,
    metadata: dict[str, Any],
    allow_deleting: bool = False,
) -> Path | None:
    """Verify and return a server-managed workspace, otherwise ``None``.

    Verification is structural rather than trusting the marker alone: the
    stored path must exactly equal the deterministic path derived from the
    thread's server-owned actor and tenant metadata.  Ordinary consumers are
    denied while deletion is staged; only the deletion transaction opts into
    ``allow_deleting`` to finish or retry cleanup.
    """
    if workspace_root is None:
        return None
    if (
        metadata.get(MANAGED_WORKSPACE_DELETION_KEY) == MANAGED_WORKSPACE_DELETION_MARKER
        and not allow_deleting
    ):
        # Once deletion is staged, ordinary filesystem consumers must not
        # recreate the path while the cleanup transaction is in progress.
        return None
    if metadata.get(MANAGED_WORKSPACE_METADATA_KEY) != MANAGED_WORKSPACE_MARKER:
        return None
    actor_id = metadata.get("owner_actor_id")
    tenant_id = metadata.get("tenant_id")
    stored_path = metadata.get("workspace_path")
    if not isinstance(actor_id, str) or not actor_id:
        return None
    if not isinstance(tenant_id, str) or not tenant_id:
        return None
    if not isinstance(stored_path, str) or not stored_path:
        return None
    try:
        expected = managed_workspace_path(
            workspace_root,
            tenant_id=tenant_id,
            actor_id=actor_id,
            thread_id=thread_id,
        )
        raw_stored = Path(stored_path).expanduser()
        if not raw_stored.is_absolute():
            return None
        # Normalize dot segments without following symlinks, then require the
        # actual resolution to remain identical as a second symlink defense.
        stored = Path(os.path.abspath(raw_stored))
    except (OSError, RuntimeError, ValueError):
        return None
    if stored != expected or stored.resolve(strict=False) != expected:
        return None
    return stored


@dataclass(frozen=True)
class WorkspaceLayout:
    root: Path
    upload: Path
    output: Path
    stages: Path
    final: Path
    deploy: Path
    skills: Path
    manifest: Path

    def as_dict(self) -> dict[str, str]:
        return {
            "root": str(self.root),
            "upload": str(self.upload),
            "output": str(self.output),
            "stages": str(self.stages),
            "final": str(self.final),
            "deploy": str(self.deploy),
            "skills": str(self.skills),
            "manifest": str(self.manifest),
        }


@dataclass(frozen=True)
class WorkspaceManager:
    root: Path
    _managed_paths: dict[str, Path] = field(
        default_factory=dict,
        init=False,
        repr=False,
        compare=False,
    )
    _managed_lock: RLock = field(
        default_factory=RLock,
        init=False,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        # Resolve once so ``_contains`` comparisons are robust against
        # symlink games and relative paths.
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    def path_for(self, thread_id: str) -> Path:
        """Return a thread workspace path without creating directories."""
        with self._managed_lock:
            managed = self._managed_paths.get(thread_id)
        if managed is not None:
            return managed
        safe = _safe_slug(thread_id)
        return self.root / safe

    def bind_managed(self, thread_id: str, workspace_path: str | Path) -> WorkspaceLayout:
        """Bind ``thread_id`` to a server-verified path below ``root``.

        Realtime execution has several consumers of the workspace manager. A
        one-off cwd override would leave uploads and artifact outputs on the
        legacy ``root/thread`` path, so authenticated allocation is registered
        once and all subsequent ``layout`` calls resolve identically.

        The caller must already have verified actor/tenant ownership. This
        method supplies the final filesystem boundary: it rejects relative
        paths, paths outside the manager root, symlinks and attempts to rebind
        a live thread to a different directory.
        """
        raw = Path(workspace_path).expanduser()
        if not raw.is_absolute():
            raise ValueError("managed workspace path must be absolute")
        normalized = Path(os.path.abspath(raw))
        resolved = raw.resolve(strict=False)
        if resolved != normalized:
            raise ValueError("managed workspace path contains a symlink")
        if not self._contains(resolved):
            raise ValueError("managed workspace path is outside the workspace root")
        with self._managed_lock:
            existing = self._managed_paths.get(thread_id)
            if existing is not None and existing != resolved:
                raise ValueError("thread already has a different managed workspace")
            self._managed_paths[thread_id] = resolved
        resolved.mkdir(parents=True, exist_ok=True)
        self._ensure_layout(resolved, thread_id)
        return self.layout(thread_id)

    def allocate(self, thread_id: str) -> Path:
        """Create (if needed) and return the workspace dir for a thread."""
        path = self.path_for(thread_id)
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        self._ensure_layout(path, thread_id)
        return path

    def layout(self, thread_id: str) -> WorkspaceLayout:
        """Return the standard workspace layout, creating it if necessary."""
        root = self.allocate(thread_id)
        return WorkspaceLayout(
            root=root,
            upload=root / "upload",
            output=root / "output",
            stages=root / "output" / "stages",
            final=root / "output" / "final",
            deploy=root / "deploy",
            skills=root / "skills",
            manifest=root / _MANIFEST_NAME,
        )

    def manifest(self, thread_id: str) -> dict[str, Any]:
        """Return the workspace manifest for a thread."""
        layout = self.layout(thread_id)
        try:
            data = json.loads(layout.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self._write_manifest(layout.root, thread_id)
            data = json.loads(layout.manifest.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
        self._write_manifest(layout.root, thread_id)
        return json.loads(layout.manifest.read_text(encoding="utf-8"))

    def discard(self, thread_id: str) -> bool:
        """Remove the thread's workspace. Returns True iff something was deleted.

        Refuses to touch anything that resolves outside ``root`` — a
        last line of defence against a slug resolving to ``..`` due to
        a bug or malicious input.
        """
        path = self.path_for(thread_id)
        try:
            resolved = path.resolve()
        except OSError:
            return False
        if not self._contains(resolved):
            _logger.warning(
                "workspace discard refused: %s outside root %s",
                resolved,
                self.root,
            )
            return False
        if not resolved.exists():
            with self._managed_lock:
                self._managed_paths.pop(thread_id, None)
            return False
        shutil.rmtree(resolved, ignore_errors=True)
        removed = not resolved.exists()
        if removed:
            with self._managed_lock:
                self._managed_paths.pop(thread_id, None)
        return removed

    def resolve_cwd(self, thread_id: str, explicit: str | None) -> str:
        """Decide which cwd a turn should use.

        An explicit path from the caller wins (power users, scripts).
        An absent path means "put the thread in its own sandbox".
        """
        if explicit is not None and str(explicit).strip():
            return str(explicit)
        return str(self.allocate(thread_id))

    def _contains(self, candidate: Path) -> bool:
        try:
            candidate.relative_to(self.root)
            return True
        except ValueError:
            return False

    def _ensure_layout(self, path: Path, thread_id: str) -> None:
        try:
            (path / ".gitignore").write_text(_GITIGNORE_BODY, encoding="utf-8")
        except OSError as exc:
            _logger.debug("could not write .gitignore in %s: %s", path, exc)
        for rel in _STANDARD_DIRS:
            try:
                (path / rel).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                _logger.debug(
                    "could not create workspace dir %s in %s: %s",
                    rel,
                    path,
                    exc,
                )
        if not (path / _MANIFEST_NAME).exists():
            self._write_manifest(path, thread_id)

    def _write_manifest(self, path: Path, thread_id: str) -> None:
        payload = {
            "schema": "octopus.workspace.v1",
            "thread_id": thread_id,
            "slug": path.name,
            "created_at": datetime.now(UTC).isoformat(),
            "dirs": {
                "upload": "upload",
                "output": "output",
                "stages": "output/stages",
                "final": "output/final",
                "deploy": "deploy",
                "skills": "skills",
            },
        }
        try:
            (path / _MANIFEST_NAME).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            _logger.debug("could not write workspace manifest in %s: %s", path, exc)


def _safe_slug(thread_id: str) -> str:
    """Turn an arbitrary thread id into a safe directory name.

    Allow-list approach: keep alphanumerics, dash, underscore, dot. Anything
    else becomes ``_``. An empty slug falls back to ``thread``. No attempt
    to preserve readability — ids are opaque identifiers upstream, and
    logs always show the original id anyway.
    """
    chars = []
    for ch in thread_id or "":
        if ch.isalnum() or ch in "-_.":
            chars.append(ch)
        else:
            chars.append("_")
    slug = "".join(chars).strip("._") or "thread"
    return slug[:64]


__all__ = [
    "MANAGED_WORKSPACE_DELETION_KEY",
    "MANAGED_WORKSPACE_DELETION_MARKER",
    "MANAGED_WORKSPACE_MARKER",
    "MANAGED_WORKSPACE_METADATA_KEY",
    "PROTECTED_WORKSPACE_METADATA_KEYS",
    "WorkspaceLayout",
    "WorkspaceManager",
    "managed_workspace_metadata",
    "managed_workspace_path",
    "strip_client_workspace_metadata",
    "verified_managed_workspace",
]
