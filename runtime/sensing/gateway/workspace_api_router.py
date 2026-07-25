"""Workspace HTTP API · ``/api/workspaces/*``.

Exposes the Workspace entity (mount + membership + file lease) over HTTP.
This is the Phase 2 surface on top of:

  - ``runtime.workspace.WorkspaceStore``        · SQLite persistence
  - ``runtime.sensing.server.mount_backend``    · unified filesystem abstraction
  - ``runtime.platform.io.lease.LeaseStore``    · per-file TTL leases

All endpoints are gated by the ``ui.remote_workspace`` feature flag.
When the flag is off every endpoint returns ``403`` so the router
can be deployed safely behind a gradual rollout.

Note: this router is distinct from the per-thread
``runtime.sensing.gateway.workspaces_router`` (which exposes thread
output directories). The two share the ``/api/workspaces`` prefix but
this router owns the create / list / members / lease / health
endpoints; the thread router continues to own ``GET /api/workspaces/{thread_id}/outputs``.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from runtime.platform.io.lease import (
    LeaseConflictError,
    LeaseNotFoundError,
    LeaseStore,
)
from runtime.sensing.server.mount_backend import (
    MountBackendRegistry,
    default_registry,
)
from runtime.workspace import (
    VALID_MEMBER_ROLES,
    VALID_MOUNT_TYPES,
    WorkspaceStore,
)


# ═══════════════════════════════════════════════════════════
# Request bodies
# ═══════════════════════════════════════════════════════════


class CreateWorkspaceBody(BaseModel):
    name: str = Field(min_length=1)
    mount_type: str = Field(min_length=1)
    mount_target: str = Field(min_length=1)
    mount_options: dict[str, Any] = Field(default_factory=dict)
    owner_id: str = Field(min_length=1)


class AddMemberBody(BaseModel):
    member_id: str = Field(min_length=1)
    role: str = Field(default="viewer")


class AcquireLeaseBody(BaseModel):
    file_path: str = Field(min_length=1)
    holder_id: str = Field(min_length=1)
    ttl_seconds: int = Field(default=1800, gt=0)
    kind: str = Field(default="exclusive")


class RenewLeaseBody(BaseModel):
    ttl_seconds: int = Field(default=1800, gt=0)


# ═══════════════════════════════════════════════════════════
# Router factory
# ═══════════════════════════════════════════════════════════


def _require_flag() -> None:
    """Raise 403 unless ``ui.remote_workspace`` is on."""
    from runtime.platform import feature_flags as _ff

    if not _ff.is_on("ui.remote_workspace"):
        raise HTTPException(
            403,
            detail={
                "error": "remote_workspace_disabled",
                "hint": "set feature flag 'ui.remote_workspace' to enable",
            },
        )


def create_workspace_api_router(
    *,
    workspace_store: WorkspaceStore | None = None,
    lease_store: LeaseStore | None = None,
    registry: MountBackendRegistry | None = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create the ``/api/workspaces/*`` router for the Workspace entity.

    ``workspace_store`` and ``lease_store`` default to the standard
    on-disk locations; tests pass a ``tmp_path``-backed pair.
    ``registry`` defaults to the shared ``default_registry`` so backend
    instances are cached across requests.
    """
    store = workspace_store or WorkspaceStore()
    leases = lease_store or LeaseStore()
    backend_registry = registry or default_registry

    def _auth(request: Request) -> None:
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _auth_dep(request: Request) -> None:
        _auth(request)

    def _workspace_or_404(workspace_id: str):
        ws = store.get_workspace(workspace_id)
        if ws is None:
            raise HTTPException(404, f"workspace {workspace_id!r} not found")
        return ws

    def _bad_request(exc: ValueError) -> HTTPException:
        return HTTPException(400, str(exc))

    async def _test_connection(
        mount_type: str,
        mount_target: str,
        mount_options: dict[str, Any],
    ) -> tuple[bool, str]:
        """Probe the mount; returns (ok, detail)."""
        try:
            backend = backend_registry.get_backend(
                "__workspace_probe__",
                mount_type,
                mount_target,
                mount_options,
            )
        except KeyError as exc:
            return False, str(exc)
        except Exception as exc:  # noqa: BLE001 — backend constructor failure
            return False, f"backend init failed: {exc}"
        try:
            ok = await backend.test_connection()
        except Exception as exc:  # noqa: BLE001 — probe must not raise
            return False, f"test_connection raised: {exc}"
        return ok, "" if ok else "mount unreachable"

    router = APIRouter(tags=["workspace-api"])

    # ─── Workspace CRUD ────────────────────────────────────────────────────

    @router.post("/api/workspaces", dependencies=[Depends(_auth_dep)])
    async def create_workspace(body: CreateWorkspaceBody) -> dict[str, Any]:
        """Create a workspace. The mount must be reachable first."""
        _require_flag()
        if body.mount_type not in VALID_MOUNT_TYPES:
            raise HTTPException(
                400,
                f"invalid mount_type {body.mount_type!r}; "
                f"expected one of {sorted(VALID_MOUNT_TYPES)}",
            )
        ok, detail = await _test_connection(
            body.mount_type, body.mount_target, body.mount_options
        )
        if not ok:
            raise HTTPException(
                400,
                {
                    "error": "mount_unreachable",
                    "mount_type": body.mount_type,
                    "mount_target": body.mount_target,
                    "detail": detail,
                },
            )
        try:
            ws = store.create_workspace(
                name=body.name,
                mount_type=body.mount_type,
                mount_target=body.mount_target,
                mount_options=body.mount_options,
                owner_id=body.owner_id,
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        # Pre-warm the backend cache so the first health/list_dir call
        # doesn't pay the connection cost.
        try:
            backend_registry.get_or_create(
                ws.id, ws.mount_type, ws.mount_target, ws.mount_options
            )
        except Exception:  # noqa: BLE001 — pre-warm is best-effort
            pass
        return {"workspace": ws.to_dict()}

    @router.get("/api/workspaces", dependencies=[Depends(_auth_dep)])
    def list_workspaces(
        user_id: str = Query(default=""),
    ) -> dict[str, Any]:
        """List workspaces accessible to ``user_id``."""
        _require_flag()
        if user_id:
            workspaces = store.list_workspaces_for_user(user_id)
        else:
            workspaces = store.list_workspaces()
        return {"workspaces": [ws.to_dict() for ws in workspaces]}

    @router.get(
        "/api/workspaces/{workspace_id}",
        dependencies=[Depends(_auth_dep)],
    )
    def get_workspace(workspace_id: str) -> dict[str, Any]:
        """Get a single workspace by id."""
        _require_flag()
        ws = _workspace_or_404(workspace_id)
        return {"workspace": ws.to_dict()}

    @router.delete(
        "/api/workspaces/{workspace_id}",
        dependencies=[Depends(_auth_dep)],
    )
    def delete_workspace(workspace_id: str) -> dict[str, Any]:
        """Delete a workspace. Cascades to members."""
        _require_flag()
        if store.get_workspace(workspace_id) is None:
            raise HTTPException(404, f"workspace {workspace_id!r} not found")
        store.delete_workspace(workspace_id)
        backend_registry.invalidate(workspace_id)
        return {"ok": True, "workspace_id": workspace_id}

    # ─── Members ───────────────────────────────────────────────────────────

    @router.get(
        "/api/workspaces/{workspace_id}/members",
        dependencies=[Depends(_auth_dep)],
    )
    def list_members(workspace_id: str) -> dict[str, Any]:
        _require_flag()
        _workspace_or_404(workspace_id)
        members = store.list_members(workspace_id)
        return {"members": [m.to_dict() for m in members]}

    @router.post(
        "/api/workspaces/{workspace_id}/members",
        dependencies=[Depends(_auth_dep)],
    )
    def add_member(
        workspace_id: str, body: AddMemberBody
    ) -> dict[str, Any]:
        _require_flag()
        _workspace_or_404(workspace_id)
        if body.role not in VALID_MEMBER_ROLES:
            raise HTTPException(
                400,
                f"invalid role {body.role!r}; "
                f"expected one of {sorted(VALID_MEMBER_ROLES)}",
            )
        try:
            member = store.add_member(
                workspace_id, body.member_id, role=body.role
            )
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"member": member.to_dict()}

    @router.delete(
        "/api/workspaces/{workspace_id}/members/{member_id}",
        dependencies=[Depends(_auth_dep)],
    )
    def remove_member(
        workspace_id: str, member_id: str
    ) -> dict[str, Any]:
        _require_flag()
        _workspace_or_404(workspace_id)
        removed = store.remove_member(workspace_id, member_id)
        if not removed:
            raise HTTPException(
                404,
                f"member {member_id!r} not in workspace {workspace_id!r}",
            )
        return {"ok": True, "member_id": member_id}

    # ─── File leases ───────────────────────────────────────────────────────

    @router.post(
        "/api/workspaces/{workspace_id}/lease",
        dependencies=[Depends(_auth_dep)],
    )
    def acquire_lease(
        workspace_id: str, body: AcquireLeaseBody
    ) -> dict[str, Any]:
        _require_flag()
        _workspace_or_404(workspace_id)
        try:
            lease = leases.acquire(
                workspace_id=workspace_id,
                file_path=body.file_path,
                holder_id=body.holder_id,
                ttl_seconds=body.ttl_seconds,
                kind=body.kind,
            )
        except LeaseConflictError as exc:
            raise HTTPException(
                409,
                {
                    "error": "lease_conflict",
                    "conflict": exc.lease.to_dict() if hasattr(exc.lease, "to_dict") else _lease_dict(exc.lease),
                    "holder_id": exc.lease.holder_id,
                    "file_path": exc.lease.file_path,
                    "expires_at": exc.lease.expires_at,
                },
            ) from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"lease": _lease_dict(lease)}

    @router.delete(
        "/api/workspaces/{workspace_id}/lease/{lease_id}",
        dependencies=[Depends(_auth_dep)],
    )
    def release_lease(workspace_id: str, lease_id: str) -> dict[str, Any]:
        _require_flag()
        _workspace_or_404(workspace_id)
        released = leases.release(lease_id)
        if not released:
            raise HTTPException(404, f"lease {lease_id!r} not found")
        return {"ok": True, "lease_id": lease_id}

    @router.post(
        "/api/workspaces/{workspace_id}/lease/{lease_id}/renew",
        dependencies=[Depends(_auth_dep)],
    )
    def renew_lease(
        workspace_id: str,
        lease_id: str,
        body: RenewLeaseBody,
    ) -> dict[str, Any]:
        _require_flag()
        _workspace_or_404(workspace_id)
        try:
            lease = leases.renew(lease_id, ttl_seconds=body.ttl_seconds)
        except LeaseNotFoundError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise _bad_request(exc) from exc
        return {"lease": _lease_dict(lease)}

    @router.get(
        "/api/workspaces/{workspace_id}/leases",
        dependencies=[Depends(_auth_dep)],
    )
    def list_leases(workspace_id: str) -> dict[str, Any]:
        _require_flag()
        _workspace_or_404(workspace_id)
        active = leases.list_active(workspace_id=workspace_id)
        return {"leases": [_lease_dict(l) for l in active]}

    # ─── Health ────────────────────────────────────────────────────────────

    @router.post(
        "/api/workspaces/{workspace_id}/health",
        dependencies=[Depends(_auth_dep)],
    )
    async def health(workspace_id: str) -> dict[str, Any]:
        """Re-probe the workspace's mount connection."""
        _require_flag()
        ws = _workspace_or_404(workspace_id)
        try:
            backend = backend_registry.get_or_create(
                ws.id, ws.mount_type, ws.mount_target, ws.mount_options
            )
        except KeyError as exc:
            raise HTTPException(
                500,
                f"backend for mount_type {ws.mount_type!r} not registered: {exc}",
            ) from exc
        except Exception as exc:  # noqa: BLE001 — backend init failure
            raise HTTPException(
                500,
                f"backend init failed: {exc}",
            ) from exc
        try:
            ok = await backend.test_connection()
        except Exception as exc:  # noqa: BLE001 — probe must not raise
            return {
                "workspace_id": workspace_id,
                "ok": False,
                "detail": f"test_connection raised: {exc}",
            }
        return {
            "workspace_id": workspace_id,
            "ok": ok,
            "detail": "" if ok else "mount unreachable",
        }

    return router


def _lease_dict(lease: Any) -> dict[str, Any]:
    """Best-effort lease serialisation.

    ``FileLease`` is a dataclass without ``to_dict``; fall back to
    ``dataclasses.asdict`` if needed.
    """
    if hasattr(lease, "to_dict") and callable(lease.to_dict):
        return lease.to_dict()
    try:
        from dataclasses import asdict

        return asdict(lease)
    except Exception:  # noqa: BLE001
        return {
            "lease_id": getattr(lease, "lease_id", ""),
            "workspace_id": getattr(lease, "workspace_id", ""),
            "file_path": getattr(lease, "file_path", ""),
            "holder_id": getattr(lease, "holder_id", ""),
            "acquired_at": getattr(lease, "acquired_at", 0.0),
            "expires_at": getattr(lease, "expires_at", 0.0),
            "kind": getattr(lease, "kind", "exclusive"),
        }


def register_workspace_api_router(app: Any, **kwargs: Any) -> APIRouter:
    """Build the router and attach it to ``app``.

    Convenience helper for callers that don't use ``include_router``.
    """
    router = create_workspace_api_router(**kwargs)
    app.include_router(router)
    return router


__all__ = [
    "create_workspace_api_router",
    "register_workspace_api_router",
]
