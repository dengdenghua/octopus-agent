"""Read-only API for the durable agent trace store."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from ._agent_trace_router_approvals import register_approvals_endpoints
from ._agent_trace_router_promotion import register_promotion_endpoints
from ._agent_trace_router_review import register_review_endpoints
from ._agent_trace_router_stores import RouterDeps
from ._agent_trace_router_trace import register_trace_endpoints


def create_agent_trace_router(
    *,
    store: Any = None,
    db_path: Path | None = None,
    experience_ledger: Any = None,
    experience_ledger_path: Path | None = None,
    review_queue: Any = None,
    review_queue_path: Path | None = None,
    promotion_audit_path: Path | None = None,
    proposal_ledger_path: Path | None = None,
    approval_policy_path: Path | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    router = APIRouter(tags=["agent-trace"])

    def _auth(request: Request, *, force: bool = False) -> str | None:
        from .openai_gateway_router import _resolve_actor

        return _resolve_actor(
            request,
            identity_store,
            True if force and identity_store is not None else require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    deps = RouterDeps(
        store=store,
        db_path=db_path,
        experience_ledger=experience_ledger,
        experience_ledger_path=experience_ledger_path,
        review_queue=review_queue,
        review_queue_path=review_queue_path,
        promotion_audit_path=promotion_audit_path,
        proposal_ledger_path=proposal_ledger_path,
        approval_policy_path=approval_policy_path,
        identity_store=identity_store,
        require_auth=require_auth,
        jwt_secret=jwt_secret,
        jwt_issuer=jwt_issuer,
        jwt_audience=jwt_audience,
        auth=_auth,
    )

    register_trace_endpoints(router, deps)
    register_review_endpoints(router, deps)
    register_promotion_endpoints(router, deps)
    register_approvals_endpoints(router, deps)

    return router


__all__ = ["create_agent_trace_router"]
