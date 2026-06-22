"""Retrieval router · ``/api/retrieve/rank``.

A generic "rank these candidates by meaning" endpoint backed by the configurable
embedder (lexical fallback when none). Lets a connected phone — or any client —
pick the most relevant skill / cached action / doc for a goal instead of brittle
keyword matching.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class RankRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    query: str
    candidates: list[str] = Field(default_factory=list)
    top_k: int | None = None


def create_retrieve_router() -> Any:
    """Build the router. ``app.include_router(create_retrieve_router())``."""
    try:
        from fastapi import APIRouter
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("fastapi not installed") from exc

    router = APIRouter(tags=["retrieve"])

    @router.post("/api/retrieve/rank")
    def rank(body: RankRequest) -> dict[str, Any]:
        from runtime.memory.hemolymph.semantic_rank import rank as _rank

        return _rank(body.query, body.candidates, top_k=body.top_k)

    @router.get("/api/retrieve/backend")
    def backend() -> dict[str, Any]:
        from runtime.memory.hemolymph import embedding_backend

        return embedding_backend.backend_info()

    return router
