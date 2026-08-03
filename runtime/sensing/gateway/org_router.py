"""Organization API router (阶段一 企业协作 · 组织 API 路由).

Exposes the enterprise-space org tree (``Organization`` / ``Department`` /
``Channel`` · unified Human+Agent members · channel ACL) from
``runtime.workspace`` as HTTP endpoints for the UI / API consumers.

Auth model:
  * org 写操作(建成员/部门/频道、删组织/部门) → 调用者必须是该 org 的 owner/admin
  * channel 写操作(ACL 管理) → 调用者必须是该 channel 的 owner/admin
  * channel 读操作(GET 单频道/频道成员) → 调用者需 ``can_access_channel``
  * ``require_auth=False`` 且 actor 为 None 时,写操作仍尽力鉴权(actor 为 None
    视为无权限 → 403)
"""

from __future__ import annotations

from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = object  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi
from runtime.workspace import (
    OrgStore,
    role_has_channel_admin,
    role_has_org_admin,
)


def create_org_router(
    *,
    org_store: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    require_fastapi(__name__)

    store: Any = org_store if org_store is not None else OrgStore()
    router = APIRouter(tags=["orgs"])

    def _auth(request: Request, *, force: bool = False) -> str | None:
        # Mutation endpoints force-auth; reads fall back to anonymous.
        try:
            from runtime.sensing.gateway.openai_gateway_router import _resolve_actor

            return _resolve_actor(
                request,
                identity_store,
                require_auth or force,
                jwt_secret=jwt_secret,
                jwt_issuer=jwt_issuer,
                jwt_audience=jwt_audience,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            if require_auth or force:
                raise HTTPException(401, "auth required") from exc
            return None

    def _require_org_admin(org_id: str, actor: str | None) -> None:
        """403 unless ``actor`` is the org's owner/admin."""
        if actor is None:
            raise HTTPException(403, "org admin required")
        role = store.get_org_member_role(org_id, actor)
        if not role_has_org_admin(role or ""):
            raise HTTPException(403, "org admin required")

    def _require_channel_admin(channel_id: str, actor: str | None) -> None:
        """403 unless ``actor`` is the channel's owner/admin."""
        if actor is None:
            raise HTTPException(403, "channel admin required")
        role = store.get_channel_member_role(channel_id, actor)
        if not role_has_channel_admin(role or ""):
            raise HTTPException(403, "channel admin required")

    # ── organizations ──────────────────────────────────────────────────────

    @router.post("/api/orgs")
    def create_org(body: dict[str, Any] | None, request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: org creation is actor-agnostic (owner from body)
        payload = body or {}
        name = str(payload.get("name") or "")
        owner_id = str(payload.get("owner_id") or "")
        if not name.strip():
            raise HTTPException(400, "name is required")
        if not owner_id:
            raise HTTPException(400, "owner_id is required")
        try:
            org = store.create_organization(name=name, owner_id=owner_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return org.to_dict()

    @router.get("/api/orgs")
    def list_orgs(request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic — global org listing
        orgs = store.list_organizations()
        return {"count": len(orgs), "organizations": [o.to_dict() for o in orgs]}

    # NOTE: /api/orgs/mine must be registered before /api/orgs/{org_id}.
    @router.get("/api/orgs/mine")
    def list_my_orgs(request: Request) -> dict[str, Any]:
        actor = _auth(request)
        if actor is None:
            return {"count": 0, "organizations": []}
        orgs = store.list_organizations_for_user(actor)
        return {"count": len(orgs), "organizations": [o.to_dict() for o in orgs]}

    @router.get("/api/orgs/{org_id}")
    def get_org(org_id: str, request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic read
        org = store.get_organization(org_id)
        if org is None:
            raise HTTPException(404, "organization not found")
        return org.to_dict()

    @router.delete("/api/orgs/{org_id}")
    def delete_org(org_id: str, request: Request) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        _require_org_admin(org_id, actor)
        store.delete_organization(org_id)
        return {"deleted": org_id}

    # ── org members ├───────────────────────────────────────────────────────

    @router.post("/api/orgs/{org_id}/members")
    def add_org_member(
        org_id: str, body: dict[str, Any] | None, request: Request
    ) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        _require_org_admin(org_id, actor)
        payload = body or {}
        member_id = str(payload.get("member_id") or "")
        if not member_id:
            raise HTTPException(400, "member_id is required")
        try:
            member = store.add_org_member(
                org_id,
                member_id,
                kind=str(payload.get("kind") or "agent"),
                role=str(payload.get("role") or "member"),
                display_name=str(payload.get("display_name") or ""),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return member.to_dict()

    @router.get("/api/orgs/{org_id}/members")
    def list_org_members(org_id: str, request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic read
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        members = store.list_org_members(org_id)
        return {"count": len(members), "members": [m.to_dict() for m in members]}

    @router.delete("/api/orgs/{org_id}/members/{member_id}")
    def remove_org_member(
        org_id: str, member_id: str, request: Request
    ) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        _require_org_admin(org_id, actor)
        store.remove_org_member(org_id, member_id)
        return {"deleted": member_id}

    # ── departments ────────────────────────────────────────────────────────

    @router.post("/api/orgs/{org_id}/departments")
    def create_department(
        org_id: str, body: dict[str, Any] | None, request: Request
    ) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        _require_org_admin(org_id, actor)
        payload = body or {}
        name = str(payload.get("name") or "")
        if not name.strip():
            raise HTTPException(400, "name is required")
        parent_id = payload.get("parent_id")
        try:
            dept = store.create_department(
                org_id=org_id,
                name=name,
                parent_id=str(parent_id) if parent_id else None,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return dept.to_dict()

    @router.get("/api/orgs/{org_id}/departments")
    def list_departments(org_id: str, request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic read
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        depts = store.list_departments(org_id)
        return {"count": len(depts), "departments": [d.to_dict() for d in depts]}

    @router.delete("/api/orgs/{org_id}/departments/{dept_id}")
    def delete_department(
        org_id: str, dept_id: str, request: Request
    ) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        _require_org_admin(org_id, actor)
        store.delete_department(dept_id)
        return {"deleted": dept_id}

    # ── channels ───────────────────────────────────────────────────────────

    @router.post("/api/orgs/{org_id}/channels")
    def create_channel(
        org_id: str, body: dict[str, Any] | None, request: Request
    ) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        _require_org_admin(org_id, actor)
        payload = body or {}
        name = str(payload.get("name") or "")
        if not name.strip():
            raise HTTPException(400, "name is required")
        department_id = payload.get("department_id")
        try:
            channel = store.create_channel(
                org_id=org_id,
                name=name,
                kind=str(payload.get("kind") or "channel"),
                department_id=str(department_id) if department_id else None,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # The creator (org admin) becomes the channel owner so they can manage
        # the ACL — mirroring create_organization auto-adding its owner.
        if actor is not None:
            store.add_channel_member(
                channel.id, actor, role="owner", require_org_member=False
            )
        return channel.to_dict()

    @router.get("/api/orgs/{org_id}/channels")
    def list_channels(org_id: str, request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic read
        if store.get_organization(org_id) is None:
            raise HTTPException(404, "organization not found")
        channels = store.list_channels(org_id)
        return {"count": len(channels), "channels": [c.to_dict() for c in channels]}

    # NOTE: /api/channels/mine must be registered before /api/channels/{id}.
    @router.get("/api/channels/mine")
    def list_my_channels(request: Request) -> dict[str, Any]:
        actor = _auth(request)
        if actor is None:
            return {"count": 0, "channels": []}
        channels = store.list_channels_for_user(actor)
        return {"count": len(channels), "channels": [c.to_dict() for c in channels]}

    @router.get("/api/channels/{channel_id}")
    def get_channel(channel_id: str, request: Request) -> dict[str, Any]:
        actor = _auth(request, force=True)
        channel = store.get_channel(channel_id)
        if channel is None:
            raise HTTPException(404, "channel not found")
        if not store.can_access_channel(channel_id, actor or ""):
            raise HTTPException(403, "channel access denied")
        return channel.to_dict()

    @router.delete("/api/channels/{channel_id}")
    def delete_channel(channel_id: str, request: Request) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_channel(channel_id) is None:
            raise HTTPException(404, "channel not found")
        _require_channel_admin(channel_id, actor)
        store.delete_channel(channel_id)
        return {"deleted": channel_id}

    # ── channel ACL ────────────────────────────────────────────────────────

    @router.post("/api/channels/{channel_id}/members")
    def add_channel_member(
        channel_id: str, body: dict[str, Any] | None, request: Request
    ) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_channel(channel_id) is None:
            raise HTTPException(404, "channel not found")
        _require_channel_admin(channel_id, actor)
        payload = body or {}
        member_id = str(payload.get("member_id") or "")
        if not member_id:
            raise HTTPException(400, "member_id is required")
        try:
            member = store.add_channel_member(
                channel_id,
                member_id,
                role=str(payload.get("role") or "member"),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return member.to_dict()

    @router.get("/api/channels/{channel_id}/members")
    def list_channel_members(channel_id: str, request: Request) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_channel(channel_id) is None:
            raise HTTPException(404, "channel not found")
        if not store.can_access_channel(channel_id, actor or ""):
            raise HTTPException(403, "channel access denied")
        members = store.list_channel_members(channel_id)
        return {"count": len(members), "members": [m.to_dict() for m in members]}

    @router.delete("/api/channels/{channel_id}/members/{member_id}")
    def remove_channel_member(
        channel_id: str, member_id: str, request: Request
    ) -> dict[str, Any]:
        actor = _auth(request, force=True)
        if store.get_channel(channel_id) is None:
            raise HTTPException(404, "channel not found")
        _require_channel_admin(channel_id, actor)
        store.remove_channel_member(channel_id, member_id)
        return {"deleted": member_id}

    return router


__all__ = ["create_org_router"]
