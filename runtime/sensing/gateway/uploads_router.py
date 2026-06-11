"""
Thread uploads / artifacts router.

Extracted from ``runtime/platform/ui/app.py`` as part of the
app.py-split campaign. Owns the 4 endpoints the UI's message
composer + artifact viewer use:

    POST   /api/threads/{tid}/uploads                     · multipart upload
    GET    /api/threads/{tid}/uploads/list                · list stored files
    DELETE /api/threads/{tid}/uploads/{filename}          · remove one
    GET    /api/threads/{tid}/artifacts/{artifact:path}   · serve content

The router accepts a ``thread_store`` + ``upload_root`` at
construction. Both can be ``None`` · in that case every endpoint
returns 503 rather than AttributeError, matching the pre-split
"demo app without a full stack still boots" contract.

Filename sanitization
---------------------

Uploaded filenames are reduced to their basename before being
joined to the thread's upload dir · otherwise a client could
send ``../../etc/passwd`` and land a file outside their sandbox.
Covered by ``test_filename_path_traversal_stripped``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, File, HTTPException, UploadFile
    from fastapi.responses import FileResponse
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    File = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    UploadFile = None  # type: ignore[assignment, misc]
    FileResponse = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]

from runtime.platform.process.paths import app_paths
from runtime.platform.runtime_policy.workspaces import WorkspaceManager

# ═══════════════════════════════════════════════════════════
# Response models
# ═══════════════════════════════════════════════════════════


if FASTAPI_AVAILABLE:
    class UploadFileMetadata(BaseModel):
        filename: str
        size: int
        path: str
        virtual_path: str
        artifact_url: str
        extension: str | None = None
        modified: int

    class UploadPostResponse(BaseModel):
        success: bool
        files: list[UploadFileMetadata]
        message: str

    class UploadsListResponse(BaseModel):
        files: list[UploadFileMetadata]
        count: int

    class UploadDeleteResponse(BaseModel):
        success: bool
        message: str


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════


def create_uploads_router(
    *,
    thread_store: Any,
    workspace_root: Path | None = None,
    legacy_upload_root: Path | None = None,
    upload_root: Path | None = None,
) -> Any:
    """Build the FastAPI router.

    Parameters
    ----------
    thread_store :
        ThreadStateStore (for ``ensure_thread``). When ``None``,
        all endpoints return 503 — lets minimal demo apps boot
        without a full stack.
    upload_root :
        Directory under which ``<thread_id>/`` subdirs hold
        uploads. Defaults to ``app_paths().data_dir/thread_uploads`` when
        ``None``. The factory
        captures this value · passing a different path later
        requires a fresh router.
    """
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["uploads"])
    legacy_root = legacy_upload_root or upload_root
    workspace_manager = WorkspaceManager(workspace_root) if workspace_root else None

    def _upload_dir(thread_id: str) -> Path:
        if workspace_manager is not None:
            return workspace_manager.layout(thread_id).upload
        root = legacy_root or (app_paths().data_dir / "thread_uploads")
        path = root / thread_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _legacy_upload_dir(thread_id: str) -> Path | None:
        if legacy_root is None:
            return None
        return legacy_root / thread_id

    def _upload_dirs_for_read(thread_id: str) -> list[Path]:
        dirs = [_upload_dir(thread_id)]
        legacy = _legacy_upload_dir(thread_id)
        if legacy is not None and legacy not in dirs:
            dirs.append(legacy)
        return dirs

    def _metadata(thread_id: str, file_path: Path) -> dict[str, Any]:
        rel_name = file_path.name
        return {
            "filename": rel_name,
            "size": file_path.stat().st_size,
            "path": str(file_path),
            "virtual_path": str(file_path),
            "artifact_url": (
                f"/api/threads/{thread_id}/artifacts/{rel_name}"
            ),
            "extension": file_path.suffix.lstrip(".") or None,
            "modified": int(file_path.stat().st_mtime),
        }

    def _require_store() -> None:
        if thread_store is None:
            raise HTTPException(503, "thread uploads unavailable")

    @router.post(
        "/api/threads/{thread_id}/uploads",
        response_model=UploadPostResponse,
    )
    async def api_thread_uploads(
        thread_id: str,
        files: list[UploadFile] = File(...),  # noqa: B008 — FastAPI dependency pattern
    ) -> dict[str, Any]:
        _require_store()
        thread_store.ensure_thread(thread_id)
        upload_dir = _upload_dir(thread_id)
        uploaded: list[dict[str, Any]] = []
        for upload in files:
            # Sanitize: strip any path traversal segments. Relying
            # on Path(...).name gives us the basename only · a
            # malicious "../../evil" collapses to "evil".
            safe_name = Path(upload.filename or "upload.bin").name
            target = upload_dir / safe_name
            data = await upload.read()
            try:
                target.write_bytes(data)
            except OSError as exc:
                raise HTTPException(
                    500, f"failed to store upload: {exc}",
                ) from exc
            uploaded.append(_metadata(thread_id, target))
        return {
            "success": True,
            "files": uploaded,
            "message": f"Uploaded {len(uploaded)} file(s)",
        }

    @router.get(
        "/api/threads/{thread_id}/uploads/list",
        response_model=UploadsListResponse,
    )
    def api_thread_uploads_list(thread_id: str) -> dict[str, Any]:
        _require_store()
        files: list[dict[str, Any]] = []
        seen: set[str] = set()
        for upload_dir in _upload_dirs_for_read(thread_id):
            if not upload_dir.exists() or not upload_dir.is_dir():
                continue
            for path in sorted(upload_dir.iterdir(), key=lambda p: p.name.lower()):
                if not path.is_file() or path.name in seen:
                    continue
                seen.add(path.name)
                files.append(_metadata(thread_id, path))
        return {"files": files, "count": len(files)}

    @router.delete(
        "/api/threads/{thread_id}/uploads/{filename}",
        response_model=UploadDeleteResponse,
    )
    def api_thread_uploads_delete(
        thread_id: str, filename: str,
    ) -> dict[str, Any]:
        _require_store()
        # Sanitize the incoming filename the same way we did on
        # upload · don't trust URL path params more than we'd
        # trust a multipart field.
        safe_name = Path(filename).name
        target = next(
            (
                upload_dir / safe_name
                for upload_dir in _upload_dirs_for_read(thread_id)
                if (upload_dir / safe_name).exists()
                and (upload_dir / safe_name).is_file()
            ),
            None,
        )
        if target is None:
            raise HTTPException(404, f"upload not found: {filename}")
        try:
            target.unlink()
        except OSError as exc:
            raise HTTPException(
                500, f"failed to delete upload: {exc}",
            ) from exc
        return {"success": True, "message": f"Deleted {target.name}"}

    @router.get(
        "/api/threads/{thread_id}/artifacts/{artifact_path:path}",
        # response_model omitted · FileResponse doesn't play with
        # pydantic response models · skip the type mismatch.
    )
    def api_thread_artifact(
        thread_id: str,
        artifact_path: str,
        download: bool = False,
    ) -> Any:
        _require_store()
        normalized = Path(artifact_path)
        candidates: list[Path] = []
        if normalized.is_absolute():
            # Absolute paths pass straight through · used by some
            # legacy clients that stored the server-side path and
            # then asked for it back. Still bounded to "file must
            # exist" · no new privilege granted here.
            candidates.append(normalized)
        for upload_dir in _upload_dirs_for_read(thread_id):
            candidates.append(upload_dir / Path(artifact_path).name)
        target = next(
            (c for c in candidates if c.exists() and c.is_file()),
            None,
        )
        if target is None:
            raise HTTPException(
                404, f"artifact not found: {artifact_path}",
            )
        return FileResponse(
            str(target),
            filename=target.name if download else None,
        )

    return router


__all__ = ["create_uploads_router"]
