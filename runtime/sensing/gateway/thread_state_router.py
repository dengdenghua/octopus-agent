"""Thread state HTTP router used by the realtime UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Query, Request
    from fastapi.responses import Response

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    Response = None  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi


def create_thread_state_router(
    *,
    store: Any,
    logs_root: Path | str | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    require_fastapi(__name__)

    router = APIRouter(tags=["threads"])

    def _auth(request: Any) -> str | None:
        from runtime.safety.auth.principal import resolve_principal

        principal = resolve_principal(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
        if principal is not None:
            request.state.thread_principal = principal
        return principal.actor_id if principal is not None else None

    def _tenant(request: Any) -> str | None:
        principal = getattr(getattr(request, "state", None), "thread_principal", None)
        return getattr(principal, "tenant_id", None)

    def _require_store() -> None:
        if store is None:
            raise HTTPException(503, "thread state unavailable")

    def _require_thread_id(thread_id: str) -> str:
        from runtime.memory.threads.event_log import validate_thread_id

        try:
            return validate_thread_id(thread_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def _can_access(
        thread: dict[str, Any] | None,
        actor_id: str | None,
        tenant_id: str | None = None,
    ) -> bool:
        if thread is None:
            return False
        raw_metadata = thread.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        stored_tenant = str(metadata.get("tenant_id") or "").strip()
        if tenant_id and not tenant_id.startswith("legacy:") and stored_tenant != tenant_id:
            return False
        if tenant_id and stored_tenant and stored_tenant != tenant_id:
            return False
        owner = metadata.get("owner_actor_id") or metadata.get("actor_id")
        return not isinstance(owner, str) or not owner.strip() or owner.strip() == actor_id

    def _get_owned_thread(
        thread_id: str,
        actor_id: str | None,
        tenant_id: str | None = None,
    ) -> dict[str, Any] | None:
        thread = store.get(thread_id)
        if not _can_access(thread, actor_id, tenant_id):
            return None
        return thread

    def _is_archived(thread_id: str) -> bool:
        if logs_root is None:
            return False
        from runtime.memory.threads.event_log import EventLog, thread_log_path

        summary = EventLog(thread_log_path(logs_root, thread_id)).summary()
        return bool(summary and summary.archived)

    @router.post("/api/threads")
    def create_thread(request: Request, body: dict[str, Any] | None = None) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        payload = body or {}
        raw_metadata = payload.get("metadata")
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        metadata = dict(metadata)
        if actor_id is not None:
            # The body may carry presentation metadata, but ownership is
            # server-derived and cannot be assigned to another actor.
            metadata["owner_actor_id"] = actor_id
            metadata["tenant_id"] = tenant_id or ""
        raw_values = payload.get("values")
        values = raw_values if isinstance(raw_values, dict) else {}
        return store.create(metadata=metadata, values=values)

    @router.get("/api/threads/search")
    def search_threads_get(
        request: Request,
        q: str = "",
        limit: int = Query(20, ge=1, le=200),  # type: ignore[misc]
    ) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        needle = (q or "").strip().lower()
        results: list[dict[str, Any]] = []
        for thread in store.search(limit=500, offset=0):
            if not _can_access(thread, actor_id, tenant_id):
                continue
            thread_id = thread.get("thread_id")
            if isinstance(thread_id, str) and _is_archived(thread_id):
                continue
            values = thread.get("values") or {}
            title = str(values.get("title") or "")
            raw_messages = values.get("messages")
            messages = raw_messages if isinstance(raw_messages, list) else []
            haystack_parts = [title]
            for message in messages:
                if isinstance(message, dict):
                    haystack_parts.append(str(message.get("content") or ""))
            haystack = "\n".join(haystack_parts).lower()
            if needle and needle not in haystack:
                continue
            snippet = ""
            for part in haystack_parts:
                if needle and needle in part.lower():
                    snippet = part
                    break
            results.append(
                {
                    "thread_id": thread.get("thread_id"),
                    "title": title or "New chat",
                    "snippet": snippet[:240],
                    "created_at": thread.get("created_at"),
                    "updated_at": thread.get("updated_at"),
                    "message_count": len(messages),
                    "values": values,
                    "metadata": thread.get("metadata") or {},
                }
            )
            if len(results) >= limit:
                break
        return {"threads": results}

    @router.get("/api/threads/{thread_id}")
    def get_thread(request: Request, thread_id: str) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        thread = _get_owned_thread(thread_id, actor_id, tenant_id)
        if thread is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        return thread

    @router.delete(
        "/api/threads/{thread_id}", status_code=204, response_class=Response, response_model=None
    )
    def delete_thread(request: Request, thread_id: str):
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        existing = store.get(thread_id)
        if existing is not None and not _can_access(existing, actor_id, tenant_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        deleted_state = store.delete(thread_id)
        archived_log = False
        if logs_root is not None:
            from runtime.memory.threads.event_log import archive_thread

            archived_log = archive_thread(logs_root, thread_id)
        if not deleted_state and not archived_log:
            raise HTTPException(404, f"thread not found: {thread_id}")

    @router.post("/api/threads/search")
    def search_threads_post(
        request: Request,
        body: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        payload = body or {}
        metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None
        metadata = dict(metadata) if metadata is not None else None
        if actor_id is not None:
            metadata = metadata or {}
            metadata["owner_actor_id"] = actor_id
            metadata["tenant_id"] = tenant_id or ""
        limit = int(payload.get("limit", 50) or 50)
        offset = int(payload.get("offset", 0) or 0)
        sort_by = str(payload.get("sortBy") or "updated_at")
        sort_order = str(payload.get("sortOrder") or "desc")
        results = store.search(
            limit=limit,
            offset=offset,
            metadata=metadata,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return [
            thread
            for thread in results
            if _can_access(thread, actor_id, tenant_id)
            if not (isinstance(thread.get("thread_id"), str) and _is_archived(thread["thread_id"]))
        ]

    @router.get("/api/threads/{thread_id}/state")
    def get_thread_state(request: Request, thread_id: str) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        if _get_owned_thread(thread_id, actor_id, tenant_id) is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        state = store.get_state(thread_id)
        if state is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        return state

    @router.post("/api/threads/{thread_id}/state")
    def update_thread_state(
        request: Request,
        thread_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        if _get_owned_thread(thread_id, actor_id, tenant_id) is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        try:
            metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else None
            metadata = dict(metadata) if metadata is not None else None
            if actor_id is not None:
                metadata = metadata or {}
                metadata["owner_actor_id"] = actor_id
                metadata["tenant_id"] = tenant_id or ""
            return store.update_state(
                thread_id,
                values=body.get("values") if isinstance(body.get("values"), dict) else None,
                metadata=metadata,
                status=body.get("status") if isinstance(body.get("status"), str) else None,
            )
        except KeyError as exc:
            raise HTTPException(404, f"thread not found: {thread_id}") from exc

    @router.post("/api/threads/{thread_id}/history")
    def get_thread_history(
        request: Request,
        thread_id: str,
        body: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            return []
        if _get_owned_thread(thread_id, actor_id, tenant_id) is None:
            return []
        payload = body or {}
        limit = int(payload.get("limit", 50) or 50)
        return store.get_history(thread_id, limit=limit)

    return router


__all__ = ["create_thread_state_router"]
