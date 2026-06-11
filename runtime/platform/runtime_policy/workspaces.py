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

Stateless; a ``WorkspaceManager`` instance is cheap and does not hold
locks across calls.
"""
from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_logger = logging.getLogger(__name__)

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

    def __post_init__(self) -> None:
        # Resolve once so ``_contains`` comparisons are robust against
        # symlink games and relative paths.
        object.__setattr__(self, "root", Path(self.root).expanduser().resolve())

    def path_for(self, thread_id: str) -> Path:
        """Return a thread workspace path without creating directories."""
        safe = _safe_slug(thread_id)
        return self.root / safe

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
            return False
        shutil.rmtree(resolved, ignore_errors=True)
        return not resolved.exists()

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


__all__ = ["WorkspaceLayout", "WorkspaceManager"]
