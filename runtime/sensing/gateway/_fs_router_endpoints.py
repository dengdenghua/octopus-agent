"""Endpoint handlers for the filesystem router.

Extracted from ``fs_router.py`` (god-file reduction). All ``/api/fs`` and
``/api/git`` endpoints register here, delegating to the shared helpers in
``_fs_router_helpers`` and the analysis helpers in ``_fs_router_paths`` /
``_fs_router_diff``.
"""

from __future__ import annotations

import re
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import File, Form, HTTPException, Query, Request, UploadFile

from ._fs_router_diff import (
    _DiffApplyConflict,
    _DiffFormatError,
    _reverse_unified_diff,
)
from ._fs_router_helpers import (
    _assert_in_scope,
    _broadcast_file_written,
    _check_acl,
    _check_lease_conflict_or_acquire,
    _dir_entry_to_tree,
    _extract_user_id,
    _filesystem_roots,
    _FsContext,
    _is_ignored_remote_dir,
    _parse_workspace_path,
    _pick_directory_macos,
    _pick_directory_tk,
    _pick_directory_windows,
    _remote_backend_for,
    _resolve_remote_workspace,
    _tree_depth_of,
    _walk_tree,
)
from ._fs_router_models import (
    FsImportDirectoryResponse,
    FsPickDirectoryResponse,
    FsReadResponse,
    FsRootsResponse,
    FsTreeResponse,
    FsWriteResponse,
)
from ._fs_router_paths import _assert_within_allowed_roots, _safe_relative_parts


def register_endpoints(router: Any, ctx: _FsContext) -> None:
    @router.get("/api/fs/roots", response_model=FsRootsResponse)
    def api_fs_roots() -> dict[str, Any]:
        return {"entries": _filesystem_roots()}

    @router.get("/api/fs/pick-directory", response_model=FsPickDirectoryResponse)
    def api_fs_pick_directory(
        default_path: str | None = Query(default=None),
    ) -> dict[str, Any]:
        try:
            if sys.platform.startswith("win"):
                path = _pick_directory_windows(default_path)
            elif sys.platform == "darwin":
                path = _pick_directory_macos(default_path)
            else:
                path = _pick_directory_tk(default_path)
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
            relative_paths[0] if relative_paths else files[0].filename or "imported-workspace"
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
                    500,
                    f"failed to import directory: {exc}",
                ) from exc
            saved += 1

        return {"success": True, "path": str(import_root), "files": saved}

    @router.get("/api/fs/tree", response_model=FsTreeResponse)
    async def api_fs_tree(
        request: Request,
        path: str,
        depth: int = Query(default=2, ge=0, le=6),
        thread_id: str | None = None,
        workspace_path: str | None = None,
        include_ignored: bool = Query(default=False),
    ) -> dict[str, Any]:
        # Remote-workspace routing: if ``path`` carries a ``workspace_id:``
        # prefix and the workspace exists, list_dir via the MountBackend.
        workspace_id, rel_path = _parse_workspace_path(path)
        ws = _resolve_remote_workspace(ctx, workspace_id)
        if ws is not None:
            _check_acl(ctx, request, ws.id, write=False)
            backend = _remote_backend_for(ctx, ws)
            if backend is None:
                raise HTTPException(
                    500,
                    {
                        "error": "mount_backend_unavailable",
                        "workspace_id": ws.id,
                        "mount_type": ws.mount_type,
                    },
                )
            try:
                entries = await backend.list_dir(rel_path, depth)
            except FileNotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc
            except NotADirectoryError as exc:
                raise HTTPException(404, str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — backend error
                raise HTTPException(500, f"backend list_dir failed: {exc}") from exc
            tree = [
                _dir_entry_to_tree(e, depth=_tree_depth_of(e.path, rel_path))
                for e in entries
                if not _is_ignored_remote_dir(e)
            ]
            return {"entries": tree}
        # Local-path fallback (existing behaviour).
        root = _assert_in_scope(
            ctx,
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
    async def api_fs_read(
        request: Request,
        path: str,
        max_lines: int = Query(default=500, ge=1, le=5000),
        thread_id: str | None = None,
        workspace_path: str | None = None,
    ) -> dict[str, Any]:
        # Remote-workspace routing: if ``path`` carries a ``workspace_id:``
        # prefix and the workspace exists, read_file via the MountBackend.
        workspace_id, rel_path = _parse_workspace_path(path)
        ws = _resolve_remote_workspace(ctx, workspace_id)
        if ws is not None:
            _check_acl(ctx, request, ws.id, write=False)
            backend = _remote_backend_for(ctx, ws)
            if backend is None:
                raise HTTPException(
                    500,
                    {
                        "error": "mount_backend_unavailable",
                        "workspace_id": ws.id,
                        "mount_type": ws.mount_type,
                    },
                )
            try:
                raw = await backend.read_file(rel_path)
            except FileNotFoundError as exc:
                raise HTTPException(404, str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 — backend error
                raise HTTPException(500, f"backend read_file failed: {exc}") from exc
            if isinstance(raw, (bytes, bytearray)):
                content = raw.decode("utf-8", errors="replace")
            else:
                content = str(raw)
            lines = content.splitlines()
            return {
                "path": f"{ws.id}:{rel_path}",
                "content": "\n".join(lines[:max_lines]),
                "lines": lines[:max_lines],
                "truncated": len(lines) > max_lines,
            }
        # Local-path fallback (existing behaviour).
        file_path = _assert_in_scope(
            ctx,
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
                500,
                f"failed to read file: {exc}",
            ) from exc
        lines = content.splitlines()
        return {
            "path": str(file_path),
            "content": "\n".join(lines[:max_lines]),
            "lines": lines[:max_lines],
            "truncated": len(lines) > max_lines,
        }

    @router.post("/api/fs/write", response_model=FsWriteResponse)
    async def api_fs_write(
        request: Request,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        path_value = body.get("path")
        content = body.get("content", "")
        if not isinstance(path_value, str) or not path_value.strip():
            raise HTTPException(400, "path is required")
        if not isinstance(content, str):
            raise HTTPException(400, "content must be a string")
        # Remote-workspace routing: if ``path`` carries a ``workspace_id:``
        # prefix and the workspace exists, write_file via the MountBackend.
        workspace_id, rel_path = _parse_workspace_path(path_value)
        ws = _resolve_remote_workspace(ctx, workspace_id)
        if ws is not None:
            _check_acl(
                ctx,
                request,
                ws.id,
                write=True,
                body=body,
            )
            holder_id = (
                body.get("holder_id")
                if isinstance(body.get("holder_id"), str)
                else None
            )
            thread_id = (
                body.get("thread_id")
                if isinstance(body.get("thread_id"), str)
                else None
            )
            # Task 6.3: lease gate + auto-acquire.
            _check_lease_conflict_or_acquire(ctx, ws.id, rel_path, holder_id)
            backend = _remote_backend_for(ctx, ws)
            if backend is None:
                raise HTTPException(
                    500,
                    {
                        "error": "mount_backend_unavailable",
                        "workspace_id": ws.id,
                        "mount_type": ws.mount_type,
                    },
                )
            payload = content.encode("utf-8")
            try:
                await backend.write_file(rel_path, payload)
            except Exception as exc:  # noqa: BLE001 — backend error
                raise HTTPException(500, f"backend write_file failed: {exc}") from exc
            # Task 6.4: broadcast file_written to the bound cowork group.
            _broadcast_file_written(
                ctx,
                ws.id,
                rel_path,
                holder_id or _extract_user_id(request, body) or "anonymous",
                thread_id,
            )
            return {
                "success": True,
                "path": f"{ws.id}:{rel_path}",
                "bytes": len(payload),
            }
        # Local-path fallback (existing behaviour).
        file_path = _assert_in_scope(
            ctx,
            Path(path_value),
            thread_id=body.get("thread_id") if isinstance(body.get("thread_id"), str) else None,
            workspace_path=body.get("workspace_path")
            if isinstance(body.get("workspace_path"), str)
            else None,
        )
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(
                500,
                f"failed to write file: {exc}",
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
            ctx,
            Path(path_value),
            thread_id=body.get("thread_id") if isinstance(body.get("thread_id"), str) else None,
            workspace_path=body.get("workspace_path")
            if isinstance(body.get("workspace_path"), str)
            else None,
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
