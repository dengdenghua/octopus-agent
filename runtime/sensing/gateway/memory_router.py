"""Local memory compatibility API.

The frontend settings UI talks to ``/api/memory/*``. This router keeps that
HTTP contract thin and delegates all normalization/persistence to
``runtime.memory.users.user_store`` so memory state has one owner.
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Query, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment,misc]
    HTTPException = None  # type: ignore[assignment,misc]
    Query = None  # type: ignore[assignment,misc]
    Request = None  # type: ignore[assignment,misc]


def create_memory_router() -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    from runtime.memory import user_store

    router = APIRouter(tags=["memory"])

    @router.get("/api/memory")
    def api_memory_get() -> dict[str, Any]:
        return user_store.read_memory()

    @router.get("/api/memory/search")
    def api_memory_search(q: str = "", limit: int = Query(20, ge=1, le=100)) -> list[dict[str, Any]]:
        query = " ".join(q.split()).casefold()
        if not query:
            return []
        terms = [term for term in query.split() if term]
        results: list[dict[str, Any]] = []
        for fact in user_store.read_memory().get("facts", []):
            if not isinstance(fact, dict):
                continue
            content = str(fact.get("content") or "").casefold()
            category = str(fact.get("category") or "").casefold()
            haystack = f"{content} {category}"
            if query not in haystack and not all(term in haystack for term in terms):
                continue
            relevance = 1.0 if query and content.startswith(query) else 0.75
            results.append({**fact, "relevance": relevance})
        results.sort(key=lambda item: item.get("relevance", 0), reverse=True)
        return results[:limit]

    @router.post("/api/memory/reload")
    def api_memory_reload() -> dict[str, Any]:
        return user_store.read_memory()

    @router.delete("/api/memory")
    def api_memory_clear() -> dict[str, Any]:
        return user_store.write_memory(user_store.empty_memory())

    @router.post("/api/memory/facts")
    async def api_memory_add_fact(request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "invalid memory fact")
        content = str(body.get("content") or body.get("fact") or "").strip()
        if not content:
            raise HTTPException(400, "content is required")
        try:
            confidence = float(body.get("confidence", 0.8))
        except Exception:
            confidence = 0.8
        user_store.add_fact(
            content,
            category=str(body.get("category") or "context"),
            confidence=confidence,
            source=str(body.get("source") or "manual"),
            scope=str(body.get("scope") or "global"),
            agent_id=str(body.get("agent_id") or "") or None,
            project=str(body.get("project") or "") or None,
        )
        return user_store.read_memory()

    @router.patch("/api/memory/facts/{fact_id}")
    async def api_memory_update_fact(fact_id: str, request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "invalid memory fact")
        memory = user_store.read_memory()
        found = False
        for fact in memory.get("facts", []):
            if str(fact.get("id")) != fact_id:
                continue
            if "content" in body:
                content = str(body.get("content") or "").strip()
                if not content:
                    raise HTTPException(400, "content is required")
                fact["content"] = content
            for key in ("category", "source", "scope", "agent_id", "project"):
                if key in body:
                    fact[key] = str(body.get(key) or "")
            if "confidence" in body:
                try:
                    confidence = float(body.get("confidence"))
                except Exception:
                    confidence = float(fact.get("confidence", 0.8))
                fact["confidence"] = max(0.0, min(1.0, confidence))
            found = True
            break
        if not found:
            raise HTTPException(404, "memory fact not found")
        return user_store.write_memory(memory)

    @router.delete("/api/memory/facts/{fact_id}")
    def api_memory_delete_fact(fact_id: str) -> dict[str, Any]:
        memory = user_store.read_memory()
        facts = list(memory.get("facts", []))
        next_facts = [fact for fact in facts if str(fact.get("id")) != fact_id]
        if len(next_facts) == len(facts):
            raise HTTPException(404, "memory fact not found")
        memory["facts"] = next_facts
        return user_store.write_memory(memory)

    @router.get("/api/memory/config")
    def api_memory_config() -> dict[str, Any]:
        return user_store.read_config()

    @router.put("/api/memory/config")
    async def api_memory_update_config(request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "invalid memory config")
        return user_store.write_config(body)

    @router.get("/api/memory/export")
    def api_memory_export() -> dict[str, Any]:
        return user_store.read_memory()

    @router.post("/api/memory/import")
    async def api_memory_import(request: Request) -> dict[str, Any]:
        body = await request.json()
        if not isinstance(body, dict):
            raise HTTPException(400, "invalid memory payload")
        return user_store.write_memory(body)

    return router


__all__ = ["create_memory_router"]
