"""Media (video understanding) web API.

Exposes the local video semantic index (keyframe extraction + CLIP embedding +
face grouping + optional speech search) as REST endpoints for the frontend
"本地数据库 → 视频" surface. All capabilities are self-gating: when the
underlying model / index is unavailable, endpoints return a clear ``ok: False``
message instead of raising — the UI degrades gracefully.
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request
    from pydantic import BaseModel, Field

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    BaseModel = None  # type: ignore[assignment, misc]
    Field = None  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi


class VideoIndexRequest(BaseModel):
    directory: str = "."
    include_faces: bool = True
    include_transcript: bool = False
    max_files: int = Field(default=100, ge=1, le=1000)
    incremental: bool = False
    watch: bool = False
    interval_sec: float = Field(default=60.0, ge=10.0, le=3600.0)


class VideoWatchRequest(BaseModel):
    directory: str = "."
    interval_sec: float = Field(default=60.0, ge=10.0, le=3600.0)


class VideoSearchRequest(BaseModel):
    query: str = ""
    directory: str = "."
    top_k: int = Field(default=10, ge=1, le=100)


class VideoFaceSearchRequest(BaseModel):
    image_path: str = ""
    directory: str = "."
    top_k: int = Field(default=10, ge=1, le=100)


class VideoClassifyRequest(BaseModel):
    directory: str = "."
    top_k: int = Field(default=5, ge=1, le=50)


class VideoSpeechSearchRequest(BaseModel):
    query: str = ""
    directory: str = "."


class VideoImageSearchRequest(BaseModel):
    image_path: str = ""
    directory: str = "."
    top_k: int = Field(default=10, ge=1, le=100)


class VideoOcrRequest(BaseModel):
    query: str = ""
    directory: str = "."
    top_k: int = Field(default=20, ge=1, le=100)


def create_media_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    require_fastapi(__name__)

    router = APIRouter(tags=["media"])

    def _load_iidx() -> Any:
        from runtime.memory.hemolymph import video_semantic_index as _vidx

        return _vidx

    def _db_path(directory: str) -> str | None:
        """Resolve the video index DB under the given directory (or default)."""
        if not directory or directory.strip() in (".", ""):
            return None
        from pathlib import Path

        return str(Path(directory).expanduser() / "data" / "video_index.db")

    def _indexed_video_paths(db_path: str | None) -> list[str]:
        """List ``video_path`` values from the video_meta table (or [])."""
        import sqlite3
        from pathlib import Path

        path = db_path or "data/video_index.db"
        if not Path(path).exists():
            return []
        try:
            conn = sqlite3.connect(path)
            try:
                rows = conn.execute("SELECT video_path FROM video_meta").fetchall()
            finally:
                conn.close()
        except sqlite3.Error:
            return []
        return [str(r[0]) for r in rows]

    @router.post("/video/index")
    def video_index(req: VideoIndexRequest) -> dict[str, Any]:
        """Build (or rebuild) the video keyframe index for a directory.

        With ``incremental=true`` only new/changed files are processed; with
        ``watch=true`` a background watcher keeps the directory up to date.
        """
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        db_path = _db_path(req.directory)
        if req.watch:
            from runtime.memory.hemolymph.video_watchdog import start_watching

            start_watching(
                req.directory,
                interval_sec=req.interval_sec,
                include_faces=req.include_faces,
                db_path=db_path,
                max_files=req.max_files,
            )
            return {"ok": True, "watching": True, "directory": req.directory}
        result = _vidx.build_video_index(
            req.directory,
            db_path=db_path,
            include_faces=req.include_faces,
            include_transcript=req.include_transcript,
            max_files=req.max_files,
            incremental=req.incremental,
        )
        if result is None:
            return {"ok": False, "message": "video indexing unavailable"}
        return result

    @router.post("/video/watch")
    def video_watch(req: VideoWatchRequest) -> dict[str, Any]:
        """Start a background watcher for a directory (auto incremental index)."""
        from runtime.memory.hemolymph.video_watchdog import start_watching

        start_watching(
            req.directory,
            interval_sec=req.interval_sec,
            db_path=_db_path(req.directory),
        )
        return {"ok": True, "watching": True, "directory": req.directory}

    @router.delete("/video/watch")
    def video_unwatch(directory: str = ".") -> dict[str, Any]:
        """Stop the background watcher for a directory."""
        from runtime.memory.hemolymph.video_watchdog import stop_watching

        stopped = stop_watching(directory)
        return {"ok": True, "stopped": stopped, "directory": directory}

    @router.get("/video/hardware")
    def video_hardware() -> dict[str, Any]:
        """Report configured hardware-acceleration settings (ORT providers, whisper)."""
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True, "hardware": _vidx.hardware_accel()}

    @router.post("/video/search")
    def video_search(req: VideoSearchRequest) -> dict[str, Any]:
        """Find video keyframes semantically closest to a text query."""
        if not req.query.strip():
            return {"ok": False, "message": "missing query"}
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        results = _vidx.search_video_by_text(
            req.query,
            db_path=_db_path(req.directory),
            top_k=req.top_k,
        )
        return {"ok": True, "query": req.query, "hits": results or []}

    @router.post("/video/search/face")
    def video_search_face(req: VideoFaceSearchRequest) -> dict[str, Any]:
        """Find video keyframes containing the same face as an image."""
        if not req.image_path.strip():
            return {"ok": False, "message": "missing image_path"}
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        results = _vidx.search_face_in_videos(
            req.image_path,
            db_path=_db_path(req.directory),
            top_k=req.top_k,
        )
        return {"ok": True, "hits": results or []}

    @router.get("/video/faces")
    def video_faces(directory: str = ".", threshold: float = 0.45) -> dict[str, Any]:
        """Group indexed faces into person clusters across videos."""
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        try:
            result = _vidx.group_video_faces(
                db_path=_db_path(directory), threshold=threshold
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        if result is None:
            return {"ok": False, "message": "video indexing unavailable"}
        return {"ok": True, "groups": result or []}

    @router.post("/video/classify")
    def video_classify(req: VideoClassifyRequest) -> dict[str, Any]:
        """Zero-shot tag every indexed video in a directory."""
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        db_path = _db_path(req.directory)
        try:
            paths = _indexed_video_paths(db_path)
            results = []
            for vp in paths:
                tags = _vidx.classify_video(vp, db_path=db_path, top_k=req.top_k)
                results.append({"video_path": vp, "tags": tags or []})
            return {"ok": True, "results": results}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}

    @router.post("/video/search/speech")
    def video_search_speech(req: VideoSpeechSearchRequest) -> dict[str, Any]:
        """Find video transcript segments containing a text query."""
        if not req.query.strip():
            return {"ok": False, "message": "missing query"}
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        results = _vidx.search_video_by_speech(
            req.query, db_path=_db_path(req.directory)
        )
        return {"ok": True, "hits": results or []}

    @router.post("/video/search/image")
    def video_search_image(req: VideoImageSearchRequest) -> dict[str, Any]:
        """Find video keyframes visually closest to an image file."""
        if not req.image_path.strip():
            return {"ok": False, "message": "missing image_path"}
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        results = _vidx.search_video_by_image(
            req.image_path,
            db_path=_db_path(req.directory),
            top_k=req.top_k,
        )
        return {"ok": True, "hits": results or []}

    @router.post("/video/ocr")
    def video_ocr(req: VideoOcrRequest) -> dict[str, Any]:
        """OCR video keyframes and match a text query against the text."""
        if not req.query.strip():
            return {"ok": False, "message": "missing query"}
        try:
            _vidx = _load_iidx()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "message": str(exc)}
        results = _vidx.ocr_video_keyframes(
            req.query,
            root=req.directory,
            db_path=_db_path(req.directory),
            top_k=req.top_k,
        )
        return {"ok": True, "hits": results or []}

    @router.get("/video/cover")
    def video_cover(
        video_path: str = "", time_sec: float = 0.0, directory: str = "."
    ):
        """Return a JPEG frame of a video at a given time (as image/jpeg)."""
        from fastapi import Response

        if not video_path:
            return Response(status_code=404)
        try:
            _vidx = _load_iidx()
        except Exception:  # noqa: BLE001
            return Response(status_code=404)
        try:
            data = _vidx.extract_frame_jpeg(video_path, time_sec)
        except Exception:  # noqa: BLE001
            return Response(status_code=404)
        if not data:
            return Response(status_code=404)
        return Response(content=data, media_type="image/jpeg")

    return router


__all__ = [
    "VideoIndexRequest",
    "VideoWatchRequest",
    "VideoSearchRequest",
    "VideoFaceSearchRequest",
    "VideoClassifyRequest",
    "VideoSpeechSearchRequest",
    "VideoImageSearchRequest",
    "VideoOcrRequest",
    "create_media_router",
]