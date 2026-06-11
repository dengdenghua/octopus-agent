"""Workspace manifest API.

This router exposes the per-thread workspace contract used by realtime
code/agent turns. The layout itself lives in ``runtime.platform.runtime_policy.workspaces``;
the API is deliberately read-light and creates the standard directory
structure on first access.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Query
    from fastapi.responses import FileResponse
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    FileResponse = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]

from runtime.platform.runtime_policy.workspaces import WorkspaceManager

if FASTAPI_AVAILABLE:
    class WorkspaceDirEntry(BaseModel):
        key: str
        path: str
        exists: bool

    class WorkspaceInfoResponse(BaseModel):
        thread_id: str
        root: str
        paths: dict[str, str]
        dirs: list[WorkspaceDirEntry]
        manifest: dict[str, Any]

    class WorkspaceOutputEntry(BaseModel):
        name: str
        area: str
        relative_path: str
        path: str
        size: int
        modified: int
        download_url: str

    class WorkspaceOutputsResponse(BaseModel):
        thread_id: str
        area: str
        files: list[WorkspaceOutputEntry]
        count: int


def create_workspaces_router(*, workspace_root: Path | str) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    manager = WorkspaceManager(Path(workspace_root))
    router = APIRouter(tags=["workspaces"])

    def _info(thread_id: str) -> dict[str, Any]:
        if not thread_id.strip():
            raise HTTPException(400, "thread_id is required")
        layout = manager.layout(thread_id)
        paths = layout.as_dict()
        dir_keys = ("upload", "output", "stages", "final", "deploy", "skills")
        return {
            "thread_id": thread_id,
            "root": str(layout.root),
            "paths": paths,
            "dirs": [
                {
                    "key": key,
                    "path": paths[key],
                    "exists": Path(paths[key]).is_dir(),
                }
                for key in dir_keys
            ],
            "manifest": manager.manifest(thread_id),
        }

    def _area_root(thread_id: str, area: str) -> tuple[str, Path]:
        layout = manager.layout(thread_id)
        normalized = (area or "output").strip().lower()
        roots = {
            "output": layout.output,
            "stages": layout.stages,
            "final": layout.final,
            "deploy": layout.deploy,
            "upload": layout.upload,
        }
        if normalized not in roots:
            raise HTTPException(
                400,
                "area must be one of: output, stages, final, deploy, upload",
            )
        return normalized, roots[normalized]

    def _safe_child(root: Path, rel_path: str) -> Path:
        raw = Path(rel_path)
        if raw.is_absolute() or any(part in {"", ".", ".."} for part in raw.parts):
            raise HTTPException(400, "invalid relative path")
        try:
            target = (root / raw).resolve()
            target.relative_to(root.resolve())
        except (OSError, RuntimeError, ValueError) as exc:
            raise HTTPException(400, "invalid relative path") from exc
        return target

    def _output_entries(thread_id: str, area: str, limit: int) -> dict[str, Any]:
        area_key, root = _area_root(thread_id, area)
        files: list[dict[str, Any]] = []
        if root.exists():
            for path in sorted(root.rglob("*"), key=lambda p: str(p).lower()):
                if len(files) >= limit:
                    break
                if not path.is_file():
                    continue
                rel = path.relative_to(root).as_posix()
                suffix = "" if area_key == "output" else f"?area={area_key}"
                files.append({
                    "name": path.name,
                    "area": area_key,
                    "relative_path": rel,
                    "path": str(path),
                    "size": path.stat().st_size,
                    "modified": int(path.stat().st_mtime),
                    "download_url": (
                        f"/api/workspaces/{thread_id}/outputs/{rel}{suffix}"
                    ),
                })
        return {
            "thread_id": thread_id,
            "area": area_key,
            "files": files,
            "count": len(files),
        }

    @router.get(
        "/api/workspaces/{thread_id}",
        response_model=WorkspaceInfoResponse,
    )
    def api_workspace_info(thread_id: str) -> dict[str, Any]:
        return _info(thread_id)

    @router.get(
        "/api/threads/{thread_id}/workspace",
        response_model=WorkspaceInfoResponse,
    )
    def api_thread_workspace_info(thread_id: str) -> dict[str, Any]:
        return _info(thread_id)

    @router.get(
        "/api/workspaces/{thread_id}/outputs",
        response_model=WorkspaceOutputsResponse,
    )
    def api_workspace_outputs(
        thread_id: str,
        area: str = "output",
        limit: int = Query(500, ge=1, le=2000),  # noqa: B008
    ) -> dict[str, Any]:
        return _output_entries(thread_id, area, limit)

    @router.get(
        "/api/threads/{thread_id}/outputs",
        response_model=WorkspaceOutputsResponse,
    )
    def api_thread_workspace_outputs(
        thread_id: str,
        area: str = "output",
        limit: int = Query(500, ge=1, le=2000),  # noqa: B008
    ) -> dict[str, Any]:
        return _output_entries(thread_id, area, limit)

    @router.get("/api/workspaces/{thread_id}/outputs/{artifact_path:path}")
    def api_workspace_output_file(
        thread_id: str,
        artifact_path: str,
        area: str = "output",
        download: bool = False,
    ) -> Any:
        _, root = _area_root(thread_id, area)
        target = _safe_child(root, artifact_path)
        if not target.is_file():
            raise HTTPException(404, f"output not found: {artifact_path}")
        return FileResponse(str(target), filename=target.name if download else None)

    @router.get("/api/threads/{thread_id}/outputs/{artifact_path:path}")
    def api_thread_workspace_output_file(
        thread_id: str,
        artifact_path: str,
        area: str = "output",
        download: bool = False,
    ) -> Any:
        return api_workspace_output_file(
            thread_id,
            artifact_path,
            area=area,
            download=download,
        )

    return router


__all__ = ["create_workspaces_router"]
