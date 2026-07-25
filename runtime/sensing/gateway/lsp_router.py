"""Thin HTTP wrapper around the registered LSP skills.

This exposes definition / references / diagnostics to the frontend without
bypassing the existing skill registry. The heavy lifting still lives in
`runtime.execution.suckers.lsp_skills`.
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi

if FASTAPI_AVAILABLE:

    class LspSymbolRequest(BaseModel):
        path: str
        symbol: str
        workspace: str | None = None

    class LspDiagnosticsRequest(BaseModel):
        path: str
        workspace: str | None = None


def create_lsp_router(registry: Any) -> Any:
    require_fastapi(__name__)

    router = APIRouter(tags=["lsp"])

    def _call_skill(name: str, **kwargs: Any) -> dict[str, Any]:
        if registry is None or not registry.has(name):
            raise HTTPException(503, f"skill not available: {name}")
        skill = registry.get(name)
        try:
            return skill.handler(**kwargs)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(500, f"lsp skill failed: {exc}") from exc

    @router.post("/api/lsp/definition")
    def api_lsp_definition(body: LspSymbolRequest) -> dict[str, Any]:
        return _call_skill(
            "find_symbol",
            path=body.path,
            symbol=body.symbol,
            sandbox_dir=body.workspace,
        )

    @router.post("/api/lsp/references")
    def api_lsp_references(body: LspSymbolRequest) -> dict[str, Any]:
        return _call_skill(
            "find_refs",
            path=body.path,
            symbol=body.symbol,
            sandbox_dir=body.workspace,
        )

    @router.post("/api/lsp/diagnostics")
    def api_lsp_diagnostics(body: LspDiagnosticsRequest) -> dict[str, Any]:
        return _call_skill(
            "get_diagnostics",
            path=body.path,
            sandbox_dir=body.workspace,
        )

    return router


__all__ = ["create_lsp_router"]
