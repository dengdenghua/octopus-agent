"""Thread state HTTP router used by the realtime UI."""

from __future__ import annotations

import logging
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

_logger = logging.getLogger(__name__)


def create_thread_state_router(
    *,
    store: Any,
    logs_root: Path | str | None = None,
    session_titles: Any = None,
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

    def _title_service() -> Any:
        if store is None:
            raise HTTPException(503, "thread state unavailable")
        if session_titles is not None:
            return session_titles
        from runtime.memory.threads.session_title import SessionTitleService

        return SessionTitleService(store)

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

    # DSH P2: Full-text search endpoint
    @router.get("/api/threads/fts")
    def full_text_search(
        request: Request,
        q: str = "",
        agent_id: str | None = None,
        team_id: str | None = None,
        after: str | None = None,
        before: str | None = None,
        limit: int = Query(20, ge=1, le=100),  # type: ignore[misc]
    ) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        if not hasattr(store, "search_threads"):
            raise HTTPException(501, "full-text search not enabled")
        query = (q or "").strip()
        if not query:
            raise HTTPException(400, "query parameter 'q' is required")
        try:
            results = store.search_threads(
                query,
                agent_id=agent_id,
                team_id=team_id,
                after=after,
                before=before,
                limit=limit,
            )
        except Exception as exc:
            _logger.exception("search failed")
            raise HTTPException(500, f"search failed: {exc}") from exc
        # Filter results by ownership
        filtered = [
            {
                "thread_id": r.thread_id,
                "title": r.title,
                "snippet": r.snippet,
                "rank": r.rank,
                "created_at": r.created_at,
                "updated_at": r.updated_at,
            }
            for r in results
            if _can_access(store.get(r.thread_id), actor_id, tenant_id)
        ]
        return {"results": filtered, "count": len(filtered)}

    # DSH P2: Export thread as Markdown (before {thread_id} to avoid conflict)
    @router.get("/api/threads/{thread_id}/export")
    def export_thread(
        request: Request,
        thread_id: str,
    ) -> Response:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        if _get_owned_thread(thread_id, actor_id, tenant_id) is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        if not hasattr(store, "export_thread_markdown"):
            raise HTTPException(501, "markdown export not enabled")
        try:
            markdown = store.export_thread_markdown(thread_id)
        except Exception as exc:
            _logger.exception("export failed")
            raise HTTPException(500, f"export failed: {exc}") from exc
        if markdown is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        return Response(
            content=markdown,
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="{thread_id}.md"'},
        )

    # DSH P2: Feedback endpoints (before {thread_id} to avoid conflict)
    @router.post("/api/threads/{thread_id}/feedback")
    def add_feedback(
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
        if not hasattr(store, "add_message_feedback"):
            raise HTTPException(501, "feedback system not enabled")
        message_index = body.get("message_index")
        feedback_type = body.get("feedback_type")
        tags = body.get("tags", [])
        comment = body.get("comment", "")
        if not isinstance(message_index, int) or message_index < 0:
            raise HTTPException(400, "message_index must be non-negative integer")
        if feedback_type not in ("thumbs_up", "thumbs_down"):
            raise HTTPException(
                400, "feedback_type must be 'thumbs_up' or 'thumbs_down'"
            )
        if not isinstance(tags, list):
            raise HTTPException(400, "tags must be a list")
        try:
            feedback = store.add_message_feedback(
                thread_id,
                message_index,
                feedback_type,
                tags=tags,
                comment=comment,
                user_id=actor_id,
            )
        except Exception as exc:
            _logger.exception("add feedback failed")
            raise HTTPException(500, f"add feedback failed: {exc}") from exc
        if feedback is None:
            raise HTTPException(500, "failed to add feedback")
        return {
            "thread_id": feedback.thread_id,
            "message_index": feedback.message_index,
            "feedback_type": feedback.feedback_type,
            "tags": list(feedback.tags),
            "comment": feedback.comment,
            "timestamp": feedback.timestamp,
            "user_id": feedback.user_id,
        }

    @router.get("/api/threads/{thread_id}/feedback/stats")
    def get_feedback_stats(
        request: Request,
        thread_id: str,
    ) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        if _get_owned_thread(thread_id, actor_id, tenant_id) is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        if not hasattr(store, "get_feedback_stats"):
            raise HTTPException(501, "feedback system not enabled")
        try:
            stats = store.get_feedback_stats(thread_id)
        except Exception as exc:
            _logger.exception("get feedback stats failed")
            raise HTTPException(500, f"get feedback stats failed: {exc}") from exc
        return stats

    @router.get("/api/threads/{thread_id}/feedback")
    def get_feedback(
        request: Request,
        thread_id: str,
        message_index: int | None = None,
    ) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        if _get_owned_thread(thread_id, actor_id, tenant_id) is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        if not hasattr(store, "get_message_feedback"):
            raise HTTPException(501, "feedback system not enabled")
        try:
            if message_index is not None:
                feedbacks = store.get_message_feedback(thread_id, message_index)
            else:
                feedbacks = store.get_message_feedback(thread_id, None)
        except Exception as exc:
            _logger.exception("get feedback failed")
            raise HTTPException(500, f"get feedback failed: {exc}") from exc
        return {
            "feedbacks": [
                {
                    "thread_id": f.thread_id,
                    "message_index": f.message_index,
                    "feedback_type": f.feedback_type,
                    "tags": list(f.tags),
                    "comment": f.comment,
                    "timestamp": f.timestamp,
                    "user_id": f.user_id,
                }
                for f in feedbacks
            ]
        }

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

    @router.post("/api/threads/{thread_id}/fork")
    def fork_thread(
        request: Request,
        thread_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Fork a new thread from a completed-turn prefix (dsh sessions.fork).

        ``at_message_index`` anchors the cut at the first completed turn at
        or after it; omitted/out-of-range falls back to the last completed
        turn. Anchoring on an in-flight turn fails with 409
        ``fork-unavailable`` instead of clipping.
        """
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        if _get_owned_thread(thread_id, actor_id, tenant_id) is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        payload = body or {}
        at_index = payload.get("at_message_index") if isinstance(payload, dict) else None
        if at_index is not None and not isinstance(at_index, int):
            raise HTTPException(400, "at_message_index must be an integer")
        from runtime.memory.threads.store import ForkUnavailableError

        try:
            child = store.fork_thread(thread_id, at_message_index=at_index)
        except KeyError as exc:
            raise HTTPException(404, f"thread not found: {thread_id}") from exc
        except ForkUnavailableError as exc:
            raise HTTPException(409, "fork-unavailable") from exc
        values = child.get("values") if isinstance(child.get("values"), dict) else {}
        seeded = values.get("messages") or []
        return {
            "thread_id": child["thread_id"],
            "seeded_messages": len(seeded) if isinstance(seeded, list) else 0,
        }

    @router.post("/api/threads/{thread_id}/title/rename")
    def rename_thread_title(
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
        title = body.get("title") if isinstance(body, dict) else None
        if not isinstance(title, str):
            raise HTTPException(400, "title is required")
        try:
            snapshot = _title_service().rename(thread_id, title)
        except KeyError as exc:
            raise HTTPException(404, f"thread not found: {thread_id}") from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return snapshot.to_wire()

    @router.post("/api/threads/{thread_id}/title/refresh")
    def refresh_thread_title(
        request: Request,
        thread_id: str,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        actor_id = _auth(request)
        tenant_id = _tenant(request)
        _require_store()
        thread_id = _require_thread_id(thread_id)
        if _is_archived(thread_id):
            raise HTTPException(404, f"thread not found: {thread_id}")
        if _get_owned_thread(thread_id, actor_id, tenant_id) is None:
            raise HTTPException(404, f"thread not found: {thread_id}")
        payload = body or {}
        provider = payload.get("provider") if isinstance(payload, dict) else None
        force = bool(payload.get("force", False)) if isinstance(payload, dict) else False
        try:
            snapshot = _title_service().refresh(
                thread_id,
                provider=provider if isinstance(provider, str) else None,
                force=force,
            )
        except KeyError as exc:
            raise HTTPException(404, f"thread not found: {thread_id}") from exc
        return snapshot.to_wire()

    return router


def build_auto_title_service(store: Any, *, model_router: Any = None) -> Any:
    """Wire a ``SessionTitleService`` for first-turn auto-title (dsh auto-title).

    ``store`` ``None`` → ``None`` (auto-title disabled). With a model router a
    named ``llm`` provider is registered so the first completed turn upgrades
    the fallback title to a short LLM summary; without one the service still
    works (fallback titles) but nothing is regenerated. Provider registration
    failures degrade to a provider-less service and never raise.
    """
    if store is None:
        return None
    from runtime.memory.threads.session_title import SessionTitleService

    service = SessionTitleService(store)
    if model_router is None:
        return service
    try:
        from runtime.projectos.llm_hooks import DEFAULT_MODEL as _TITLE_MODEL
        from runtime.sensing.model_router import Message, ModelRequest

        def _llm_title_provider(thread: dict[str, Any]) -> str | None:
            values = thread.get("values") or {}
            messages = values.get("messages") or []
            first_human = next(
                (
                    m
                    for m in messages
                    if isinstance(m, dict)
                    and m.get("type") == "human"
                    and isinstance(m.get("content"), str)
                    and m["content"].strip()
                ),
                None,
            )
            if first_human is None:
                return None
            prompt = (
                "You are a session-title assistant. Write a concise "
                "conversation title (under 60 characters, plain text, "
                "no quotes or punctuation at the end) for a thread that "
                "starts with this user message:\n\n"
                f"{first_human['content'].strip()[:400]}"
            )
            resp = model_router.call(
                ModelRequest(
                    model=_TITLE_MODEL,
                    messages=[Message(role="user", content=prompt)],
                    max_tokens=60,
                    temperature=0.2,
                )
            )
            return resp.text or None

        service.register_provider("llm", _llm_title_provider, model=_TITLE_MODEL)
    except Exception as exc:  # noqa: BLE001 — auto-title is best-effort
        _logger.warning("session title provider unavailable: %s", exc)
    return service


__all__ = ["build_auto_title_service", "create_thread_state_router"]
