"""
Filesystem router · ``/api/fs/{tree,read,write}``.

Extracted from the monolithic ``runtime/platform/ui/app.py`` in the
app.py-split campaign. Hosts the raw directory-tree / read-file /
write-file endpoints used by the desktop workspace's file browser
and editor panels.

Endpoints
---------

    GET  /api/fs/tree   · directory tree (bounded depth)
    GET  /api/fs/read   · file contents (bounded line count)
    POST /api/fs/write  · overwrite / create file

Scope note
----------

These endpoints **do not pass through the write-scope resolver**
from ADR-002 · they accept any path the caller can dereference.
That's intentional — they serve the UI's file-explorer surface,
which operates on whatever directory the user opens, not on the
agent's workspace. Agents writing files go through ``write_skills``
which DOES participate in scope enforcement.

If that separation ever changes, add a ``scope`` parameter to
``create_fs_router`` and route through ``resolve_write_scope`` at
handler entry. The tests in ``test_app_fs_endpoints.py`` would
then get updated to assert rejection of out-of-scope writes.

Destructive endpoints (/api/fs/revert) go through
``_assert_writable_root`` which restricts the target to the
configured allowed roots (``OCTOPUS_FS_ALLOWED_ROOTS`` env var,
colon- or semicolon-separated; falls back to ``$OCTOPUS_DATA_DIR``
and CWD).
"""
from __future__ import annotations

import base64
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    File = None  # type: ignore[assignment, misc]
    Form = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    UploadFile = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]


# ═══════════════════════════════════════════════════════════
# Response models
# ═══════════════════════════════════════════════════════════


if FASTAPI_AVAILABLE:
    class FsTreeEntry(BaseModel):
        name: str
        path: str
        type: str  # "dir" | "file"
        depth: int
        size: int | None = None

    class FsTreeResponse(BaseModel):
        entries: list[FsTreeEntry]

    class FsRootsResponse(BaseModel):
        entries: list[FsTreeEntry]

    class FsReadResponse(BaseModel):
        path: str
        content: str
        lines: list[str]
        truncated: bool

    class FsWriteResponse(BaseModel):
        success: bool
        path: str
        bytes: int

    class FsImportDirectoryResponse(BaseModel):
        success: bool
        path: str
        files: int

    class FsPickDirectoryResponse(BaseModel):
        success: bool
        path: str | None = None
        canceled: bool = False
        error: str | None = None


TREE_IGNORED_DIRS = {
    ".cache",
    ".git",
    ".mypy_cache",
    ".next",
    ".octopus",
    ".octopus-browser-relay",
    ".octopus-research",
    ".parcel-cache",
    ".pnpm-store",
    ".pytest_cache",
    ".ruff_cache",
    ".turbo",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "logs",
    "node_modules",
    "playwright-report",
    "test-results",
    "tmp",
    "venv",
}


_HUNK_HEADER_RE = re.compile(
    r"^@@ -(?P<old_start>\d+)(?:,(?P<old_count>\d+))? "
    r"\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))? @@",
)


def _allowed_fs_roots() -> list[Path]:
    """Return the set of roots under which destructive fs endpoints are allowed.

    Policy (union):

    1. ``OCTOPUS_FS_ALLOWED_ROOTS`` env var — colon- (POSIX) or
       semicolon- (Windows) separated absolute paths. Empty entries are
       skipped. Non-existent paths are silently dropped.
    2. ``$OCTOPUS_DATA_DIR`` (if set). The dev runtime stashes
       per-thread workspaces under this root.
    3. ``$OCTOPUS_HOME`` (if set).
    4. Current working directory — covers ``make dev`` / ``pytest``
       from the repo root, where the desktop UI file browser legitimately
       needs to edit the project itself.
    """
    sep = ";" if os.name == "nt" else ":"
    explicit = os.environ.get("OCTOPUS_FS_ALLOWED_ROOTS", "")
    entries: list[Path] = []
    for raw in explicit.split(sep):
        raw = raw.strip()
        if not raw:
            continue
        try:
            p = Path(raw).expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if p.is_dir():
            entries.append(p)
    for env_key in ("OCTOPUS_DATA_DIR", "OCTOPUS_HOME"):
        raw = os.environ.get(env_key)
        if raw:
            try:
                p = Path(raw).expanduser().resolve()
                if p.is_dir():
                    entries.append(p)
            except (OSError, RuntimeError):  # noqa: BLE001 — fs entry inaccessible; skip
                pass
    try:
        from runtime.platform.process.paths import project_root

        entries.append(project_root())
    except (ImportError, OSError, RuntimeError):  # noqa: BLE001
        entries.append(Path.cwd().resolve())
    # de-dupe while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for p in entries:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def _safe_relative_parts(value: str) -> list[str]:
    parts: list[str] = []
    for raw_part in re.split(r"[\\/]+", value):
        part = raw_part.strip()
        if not part or part in {".", ".."}:
            continue
        cleaned = re.sub(r'[<>:"|?*\x00-\x1f]', "_", part)
        if cleaned:
            parts.append(cleaned[:160])
    return parts


def _assert_within_allowed_roots(candidate: Path) -> Path:
    """Raise HTTPException(403) if ``candidate`` falls outside the
    allowed roots.

    Always resolves symlinks so ``/allowed/link`` → ``/etc/shadow``
    cannot slip past the prefix check.
    """
    try:
        resolved = candidate.expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise HTTPException(400, f"invalid path: {exc}") from exc
    roots = _allowed_fs_roots()
    for root in roots:
        try:
            resolved.relative_to(root)
        except ValueError:
            continue
        return resolved
    raise HTTPException(
        403,
        f"path {resolved} is outside allowed fs roots "
        f"({', '.join(str(r) for r in roots)}); "
        "set OCTOPUS_FS_ALLOWED_ROOTS to grant access",
    )


# ═══════════════════════════════════════════════════════════
# Parsed diff (used by write-file revert path)
# ═══════════════════════════════════════════════════════════


class _DiffFormatError(ValueError):
    pass


class _DiffApplyConflict(RuntimeError):
    pass


@dataclass
class _ParsedDiffLine:
    marker: str
    content: str


@dataclass
class _ParsedDiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[_ParsedDiffLine]


def _parse_unified_diff(diff_text: str) -> list[_ParsedDiffHunk]:
    if not diff_text.strip():
        raise _DiffFormatError("diff is required")
    if "\n... (truncated " in diff_text:
        raise _DiffFormatError("truncated diffs cannot be reverted safely")

    hunks: list[_ParsedDiffHunk] = []
    current: _ParsedDiffHunk | None = None
    lines = diff_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")

    for raw_line in lines:
        if raw_line.startswith("@@"):
            if current is not None:
                hunks.append(current)
            match = _HUNK_HEADER_RE.match(raw_line)
            if not match:
                raise _DiffFormatError(f"invalid hunk header: {raw_line}")
            current = _ParsedDiffHunk(
                old_start=int(match.group("old_start")),
                old_count=int(match.group("old_count") or "1"),
                new_start=int(match.group("new_start")),
                new_count=int(match.group("new_count") or "1"),
                lines=[],
            )
            continue

        if current is None:
            continue
        if raw_line.startswith("\\ No newline at end of file"):
            continue
        if raw_line == "":
            continue

        marker = raw_line[:1]
        if marker not in {" ", "+", "-"}:
            raise _DiffFormatError(f"invalid diff line: {raw_line}")
        current.lines.append(_ParsedDiffLine(marker=marker, content=raw_line[1:]))

    if current is not None:
        hunks.append(current)
    if not hunks:
        raise _DiffFormatError("diff contains no hunks")
    return hunks


def _content_lines(text: str) -> list[str]:
    return text.replace("\r\n", "\n").replace("\r", "\n").splitlines()


def _join_content_lines(lines: list[str], *, trailing_newline: bool) -> str:
    if not lines:
        return ""
    content = "\n".join(lines)
    if trailing_newline:
        content += "\n"
    return content


def _preferred_new_index(hunk: _ParsedDiffHunk) -> int:
    if hunk.new_count == 0:
        return max(hunk.new_start, 0)
    return max(hunk.new_start - 1, 0)


def _find_line_segment(
    lines: list[str],
    segment: list[str],
    preferred_index: int,
) -> int:
    if not segment:
        if 0 <= preferred_index <= len(lines):
            return preferred_index
        raise _DiffApplyConflict("empty hunk location is outside the current file")

    end = len(lines) - len(segment)
    if 0 <= preferred_index <= end and lines[
        preferred_index:preferred_index + len(segment)
    ] == segment:
        return preferred_index

    matches: list[int] = []
    for index in range(max(end + 1, 0)):
        if lines[index:index + len(segment)] == segment:
            matches.append(index)
            if len(matches) > 1:
                break
    if len(matches) == 1:
        return matches[0]
    if matches:
        raise _DiffApplyConflict("hunk matches multiple locations in the current file")
    raise _DiffApplyConflict("hunk no longer matches the current file")


def _reverse_unified_diff(current_text: str, diff_text: str) -> str:
    hunks = _parse_unified_diff(diff_text)
    normalized = current_text.replace("\r\n", "\n").replace("\r", "\n")
    lines = _content_lines(normalized)

    for hunk in reversed(hunks):
        new_segment = [
            line.content for line in hunk.lines if line.marker != "-"
        ]
        old_segment = [
            line.content for line in hunk.lines if line.marker != "+"
        ]
        index = _find_line_segment(
            lines,
            new_segment,
            _preferred_new_index(hunk),
        )
        lines[index:index + len(new_segment)] = old_segment

    trailing_newline = normalized.endswith("\n") or (not normalized and bool(lines))
    return _join_content_lines(lines, trailing_newline=trailing_newline)


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════


def create_fs_router(thread_store: Any = None) -> Any:
    """Build the FastAPI router. No config required · all state is
    per-request (the path parameter).
    """
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["fs"])

    def _resolved_path(path_value: str | Path) -> Path:
        return Path(path_value).expanduser().resolve(strict=False)

    def _add_scope_root(roots: list[Path], value: Any) -> None:
        if isinstance(value, str) and value.strip():
            roots.append(_resolved_path(value.strip()))

    def _scope_roots(
        *,
        thread_id: str | None = None,
        workspace_path: str | None = None,
    ) -> list[Path]:
        roots: list[Path] = []
        if thread_store is not None and thread_id:
            try:
                thread = None
                if hasattr(thread_store, "get"):
                    thread = thread_store.get(thread_id)
                if thread is None and hasattr(thread_store, "get_state"):
                    thread = thread_store.get_state(thread_id)
                metadata = (thread or {}).get("metadata", {}) if thread else {}
                if isinstance(metadata, dict):
                    _add_scope_root(roots, metadata.get("workspace_path"))
                    extra = metadata.get("extra_workspaces")
                    if isinstance(extra, list):
                        for root in extra:
                            _add_scope_root(roots, root)
            except (OSError, TypeError, ValueError):  # noqa: BLE001 — scope root resolution failed; fall through to workspace
                pass
        _add_scope_root(roots, workspace_path)

        deduped: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root).casefold()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(root)
        return deduped

    def _path_in_root(path: Path, root: Path) -> bool:
        if path == root:
            return True
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _assert_in_scope(
        path: Path,
        *,
        thread_id: str | None = None,
        workspace_path: str | None = None,
    ) -> Path:
        resolved = _resolved_path(path)
        roots = _scope_roots(
            thread_id=thread_id,
            workspace_path=workspace_path,
        )
        if not roots:
            return resolved
        if any(_path_in_root(resolved, root) for root in roots):
            return resolved
        raise HTTPException(
            403,
            {
                "error": "path_outside_workspace",
                "path": str(resolved),
                "workspace_roots": [str(root) for root in roots],
                "thread_id": thread_id,
            },
        )

    def _serialize_tree_entry(
        root: Path, entry: Path, *, depth: int,
    ) -> dict[str, Any]:
        rel_path = entry.relative_to(root).as_posix()
        is_dir = entry.is_dir()
        size = None if is_dir else entry.stat().st_size
        return {
            "name": entry.name,
            "path": rel_path,
            "type": "dir" if is_dir else "file",
            "depth": depth,
            "size": size,
        }

    def _should_skip_tree_entry(entry: Path, *, include_ignored: bool) -> bool:
        if include_ignored or not entry.is_dir():
            return False
        return entry.name.casefold() in TREE_IGNORED_DIRS

    def _walk_tree(
        root: Path, *, max_depth: int, include_ignored: bool = False,
    ) -> list[dict[str, Any]]:
        if not root.exists() or not root.is_dir():
            raise HTTPException(404, f"directory not found: {root}")

        entries: list[dict[str, Any]] = []

        def _recurse(current: Path, depth: int) -> None:
            if depth > max_depth:
                return
            try:
                children = sorted(
                    current.iterdir(),
                    # Dirs first, then files, both alpha-sorted.
                    key=lambda c: (not c.is_dir(), c.name.lower()),
                )
            except OSError as exc:
                if depth == 0:
                    raise HTTPException(
                        500, f"failed to list directory: {exc}",
                    ) from exc
                return
            for child in children:
                if _should_skip_tree_entry(
                    child,
                    include_ignored=include_ignored,
                ):
                    continue
                try:
                    serialized = _serialize_tree_entry(root, child, depth=depth)
                    child_is_dir = child.is_dir()
                except OSError:
                    continue
                entries.append(serialized)
                if child_is_dir and depth < max_depth:
                    _recurse(child, depth + 1)

        _recurse(root, 0)
        return entries

    def _filesystem_roots() -> list[dict[str, Any]]:
        candidates: list[Path] = []

        if os.name == "nt":
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                drive = Path(f"{letter}:/")
                if drive.exists():
                    candidates.append(drive)
        else:
            candidates.append(Path("/"))

        candidates.extend(_allowed_fs_roots())
        with suppress(RuntimeError):
            candidates.append(Path.home())
        try:
            from runtime.platform.process.paths import project_root

            candidates.append(project_root())
        except (ImportError, OSError, RuntimeError):  # noqa: BLE001
            candidates.append(Path.cwd())

        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in candidates:
            try:
                root = candidate.expanduser().resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            if not root.exists() or not root.is_dir():
                continue
            key = str(root).casefold()
            if key in seen:
                continue
            seen.add(key)
            name = root.anchor.rstrip("\\/") or root.name or str(root)
            entries.append(
                {
                    "name": name,
                    "path": str(root),
                    "type": "dir",
                    "depth": 0,
                    "size": None,
                },
            )
        return entries

    @router.get("/api/fs/roots", response_model=FsRootsResponse)
    def api_fs_roots() -> dict[str, Any]:
        return {"entries": _filesystem_roots()}

    def _pick_directory_windows(default_path: str | None) -> str | None:
        selected_path = ""
        if default_path:
            try:
                candidate = Path(default_path).expanduser().resolve(strict=False)
                if candidate.exists() and candidate.is_dir():
                    selected_path = str(candidate)
            except (OSError, RuntimeError):
                selected_path = ""

        selected_path_b64 = base64.b64encode(selected_path.encode("utf-8")).decode("ascii")
        script = rf"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择工作区文件夹'
$dialog.ShowNewFolderButton = $true
$selectedPath = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{selected_path_b64}'))
if ($selectedPath) {{ $dialog.SelectedPath = $selectedPath }}
if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{
  [Console]::Out.Write($dialog.SelectedPath)
}}
"""
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError(completed.stderr.strip() or "folder picker failed")
        value = completed.stdout.strip()
        return value or None

    def _pick_directory_tk(default_path: str | None) -> str | None:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            kwargs: dict[str, Any] = {"title": "选择工作区文件夹"}
            if default_path:
                kwargs["initialdir"] = default_path
            selected = filedialog.askdirectory(**kwargs)
            return selected or None
        finally:
            root.destroy()

    @router.get("/api/fs/pick-directory", response_model=FsPickDirectoryResponse)
    def api_fs_pick_directory(
        default_path: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            path = (
                _pick_directory_windows(default_path)
                if sys.platform.startswith("win")
                else _pick_directory_tk(default_path)
            )
        except Exception as exc:  # pragma: no cover - depends on local GUI
            return {
                "success": False,
                "path": None,
                "canceled": False,
                "error": str(exc),
            }
        if not path:
            return {"success": False, "path": None, "canceled": True, "error": None}
        return {"success": True, "path": path, "canceled": False, "error": None}

    @router.post(
        "/api/fs/import-directory",
        response_model=FsImportDirectoryResponse,
    )
    async def api_fs_import_directory(
        files: list[UploadFile] = File(...),  # noqa: B008
        relative_paths: list[str] = Form(default=[]),  # noqa: B008
    ) -> dict[str, Any]:
        from runtime.platform.process.paths import app_paths

        if not files:
            raise HTTPException(400, "files are required")
        first_rel = (
            relative_paths[0]
            if relative_paths
            else files[0].filename or "imported-workspace"
        )
        first_parts = _safe_relative_parts(first_rel)
        folder_name = first_parts[0] if len(first_parts) > 1 else "imported-workspace"
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", folder_name).strip(".-") or "workspace"
        import_root = (
            app_paths().data_dir
            / "imported_workspaces"
            / f"{int(time.time())}-{slug[:48]}-{uuid.uuid4().hex[:8]}"
        )
        import_root.mkdir(parents=True, exist_ok=True)

        saved = 0
        for index, upload in enumerate(files):
            rel = (
                relative_paths[index]
                if index < len(relative_paths)
                else upload.filename or f"file-{index}"
            )
            parts = _safe_relative_parts(rel)
            if len(parts) > 1:
                parts = parts[1:]
            if not parts:
                parts = [Path(upload.filename or f"file-{index}").name]
            target = import_root.joinpath(*parts)
            try:
                resolved_target = target.resolve(strict=False)
                resolved_target.relative_to(import_root.resolve())
            except (OSError, ValueError) as exc:
                raise HTTPException(400, "invalid relative path") from exc
            data = await upload.read()
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            except OSError as exc:
                raise HTTPException(
                    500, f"failed to import directory: {exc}",
                ) from exc
            saved += 1

        return {"success": True, "path": str(import_root), "files": saved}

    @router.get("/api/fs/tree", response_model=FsTreeResponse)
    def api_fs_tree(
        path: str,
        depth: int = Query(default=2, ge=0, le=6),
        thread_id: str | None = None,
        workspace_path: str | None = None,
        include_ignored: bool = Query(default=False),
    ) -> dict[str, Any]:
        root = _assert_in_scope(
            Path(path),
            thread_id=thread_id,
            workspace_path=workspace_path,
        )
        return {
            "entries": _walk_tree(
                root,
                max_depth=depth,
                include_ignored=include_ignored,
            ),
        }

    @router.get("/api/fs/read", response_model=FsReadResponse)
    def api_fs_read(
        path: str,
        max_lines: int = Query(default=500, ge=1, le=5000),
        thread_id: str | None = None,
        workspace_path: str | None = None,
    ) -> dict[str, Any]:
        file_path = _assert_in_scope(
            Path(path),
            thread_id=thread_id,
            workspace_path=workspace_path,
        )
        if not file_path.exists() or not file_path.is_file():
            raise HTTPException(404, f"file not found: {file_path}")
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise HTTPException(
                500, f"failed to read file: {exc}",
            ) from exc
        lines = content.splitlines()
        return {
            "path": str(file_path),
            "content": "\n".join(lines[:max_lines]),
            "lines": lines[:max_lines],
            "truncated": len(lines) > max_lines,
        }

    @router.post("/api/fs/write", response_model=FsWriteResponse)
    def api_fs_write(body: dict[str, Any]) -> dict[str, Any]:
        path_value = body.get("path")
        content = body.get("content", "")
        if not isinstance(path_value, str) or not path_value.strip():
            raise HTTPException(400, "path is required")
        if not isinstance(content, str):
            raise HTTPException(400, "content must be a string")
        file_path = _assert_in_scope(
            Path(path_value),
            thread_id=body.get("thread_id") if isinstance(body.get("thread_id"), str) else None,
            workspace_path=body.get("workspace_path") if isinstance(body.get("workspace_path"), str) else None,
        )
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(
                500, f"failed to write file: {exc}",
            ) from exc
        return {
            "success": True,
            "path": str(file_path),
            "bytes": len(content.encode("utf-8")),
        }

    @router.post("/api/fs/revert-diff")
    def api_fs_revert_diff(body: dict[str, Any]) -> dict[str, Any]:
        """Reverse-apply a unified diff against the current file contents."""
        path_value = body.get("path")
        diff_text = body.get("diff")
        if not isinstance(path_value, str) or not path_value.strip():
            raise HTTPException(400, "path is required")
        if not isinstance(diff_text, str) or not diff_text.strip():
            raise HTTPException(400, "diff is required")

        file_path = _assert_in_scope(
            Path(path_value),
            thread_id=body.get("thread_id") if isinstance(body.get("thread_id"), str) else None,
            workspace_path=body.get("workspace_path") if isinstance(body.get("workspace_path"), str) else None,
        )
        if file_path.exists() and not file_path.is_file():
            raise HTTPException(404, f"file not found: {file_path}")

        try:
            current = (
                file_path.read_text(encoding="utf-8", errors="replace")
                if file_path.exists()
                else ""
            )
            reverted = _reverse_unified_diff(current, diff_text)
        except _DiffFormatError as exc:
            raise HTTPException(400, str(exc)) from exc
        except _DiffApplyConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(500, f"failed to read file: {exc}") from exc

        delete_empty = body.get("delete_empty") is True
        try:
            if delete_empty and reverted == "":
                if file_path.exists():
                    file_path.unlink()
                return {
                    "success": True,
                    "reverted": True,
                    "path": str(file_path),
                    "bytes": 0,
                    "deleted": True,
                }
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(reverted, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(500, f"failed to write file: {exc}") from exc

        return {
            "success": True,
            "reverted": True,
            "path": str(file_path),
            "bytes": len(reverted.encode("utf-8")),
            "deleted": False,
        }

    @router.post("/api/fs/revert")
    def api_fs_revert(body: dict[str, Any]) -> dict[str, Any]:
        """Revert a file to its last git-committed state.

        Both ``path`` and ``workspace`` (if given) must resolve under
        the allowed fs roots — otherwise this endpoint would let a
        WebSocket client revert files in any directory reachable by
        the server (CVE-class bug).
        """
        import subprocess
        path_value = body.get("path")
        workspace = body.get("workspace")
        if not isinstance(path_value, str) or not path_value.strip():
            raise HTTPException(400, "path is required")
        file_path = _assert_within_allowed_roots(Path(path_value).expanduser())
        if workspace:
            if not isinstance(workspace, str):
                raise HTTPException(400, "workspace must be a string")
            cwd_path = _assert_within_allowed_roots(Path(workspace).expanduser())
        else:
            cwd_path = _assert_within_allowed_roots(file_path.parent)
        # The file must live under the chosen cwd so that ``git
        # checkout -- <file>`` can only affect the asserted workspace.
        try:
            file_path.relative_to(cwd_path)
        except ValueError:
            raise HTTPException(
                400,
                f"path {file_path} is not inside workspace {cwd_path}",
            ) from None
        try:
            proc = subprocess.run(
                ["git", "checkout", "--", str(file_path)],
                capture_output=True,
                text=True,
                cwd=str(cwd_path),
                timeout=10.0,
                shell=False,
            )
            if proc.returncode != 0:
                raise HTTPException(500, f"git checkout failed: {proc.stderr.strip()}")
            return {"reverted": True, "path": str(file_path)}
        except FileNotFoundError:
            raise HTTPException(503, "git not found") from None
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "git checkout timed out") from None

    @router.get("/api/git/status")
    def api_git_status(
        path: str = Query(default="."),
    ) -> dict[str, Any]:
        """Run git status --porcelain in the given directory."""
        import subprocess
        root = Path(path).expanduser()
        if not root.is_dir():
            raise HTTPException(404, f"directory not found: {root}")
        try:
            proc = subprocess.run(
                ["git", "status", "--porcelain=v1", "--branch"],
                capture_output=True,
                text=True,
                cwd=str(root),
                timeout=10.0,
            )
            if proc.returncode != 0:
                return {"branch": "", "files": [], "error": proc.stderr.strip()}
        except FileNotFoundError:
            return {"branch": "", "files": [], "error": "git not found"}
        except subprocess.TimeoutExpired:
            return {"branch": "", "files": [], "error": "timeout"}

        branch = ""
        files: list[dict[str, str]] = []
        for line in proc.stdout.splitlines():
            if line.startswith("## "):
                branch = line[3:].split("...")[0]
                continue
            if len(line) < 4:
                continue
            xy = line[:2]
            file_path = line[3:].strip()
            status = "M"
            if "A" in xy or "?" in xy:
                status = "A"
            elif "D" in xy:
                status = "D"
            elif "R" in xy:
                status = "R"
            files.append({"path": file_path, "status": status})
        return {"branch": branch, "files": files}

    return router


__all__ = ["create_fs_router"]
