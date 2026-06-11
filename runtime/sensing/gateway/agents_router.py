
from __future__ import annotations

import contextlib
import json
import re
import subprocess
from typing import Any

from runtime.execution.misc.agent_avatar import pixel_agent_avatar_svg

# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════
#
# agents_router.py · navigation map (1616 lines, ~30 routes).
#
#   §1 helpers (avatar / soul / wire shape)         ~L27
#   §2 create_agents_router (closure factory)       ~L246
#       §2.1 auth + identity helpers                ~L264
#       §2.2 /api/agents (CRUD)                     ~L383
#       §2.3 /api/agents/local-partners             ~L611
#       §2.4 /api/agents/{id}/visuals|avatar|reload ~L817
#       §2.5 /api/arms                              ~L1067
#       §2.6 /api/agents/{id}/tool-registry         ~L1091
#       §2.7 /api/tasks (list/get/pause/resume/del) ~L1187
#       §2.8 /api/regeneration/status               ~L1357
#       §2.9 /api/settings/capabilities             ~L1402
#       §2.10 /api/conversations                    ~L1440
#       §2.11 /api/groups (CRUD + membership)       ~L1506
#
# Closure factory pattern: every route handler has access to the
# captured stack/registry/services. Splitting would require either
# converting to a class (handlers become methods) or threading
# 6+ deps as args. The navigation map below is comment-only.
#

_PERSONA_RE = re.compile(
    r"^##\s+Persona\s*\n(.*?)(?=^##\s+|\Z)",
    re.DOTALL | re.MULTILINE,
)

_BUILTIN_AGENT_IDS = frozenset(
    {"general", "coder", "vibe_selling", "ecommerce_mind", "admin", "desktop_operator"}
)


def _soul_for_display(soul: str | None) -> str | None:
    """Return only the user-facing persona paragraph.

    Strips the HARD SYSTEM RULE banner, Identity, Working Rules,
    MEMORY/USER, and REMINDER sections — those are all internal
    LLM scaffolding and should never appear in user-facing UI.
    """
    if not soul:
        return None
    m = _PERSONA_RE.search(soul)
    if m:
        body = m.group(1).strip()
        return body or None
    # Legacy / hand-rolled soul without "## Persona" header:
    # strip the banner prefix and any REMINDER tail, return the rest.
    txt = soul
    if txt.lstrip().startswith("# HARD SYSTEM RULE"):
        # drop everything up to first "---" divider (banner ends with ---)
        parts = txt.split("\n---\n", 1)
        if len(parts) == 2:
            txt = parts[1]
    # drop REMINDER tail
    txt = re.split(r"^##\s+REMINDER\b", txt, maxsplit=1, flags=re.MULTILINE)[0]
    txt = txt.strip()
    return txt or None

try:
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import FileResponse, Response

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    FileResponse = None  # type: ignore[assignment, misc]
    Response = None  # type: ignore[assignment, misc]


def _avatar_url_for(agent_id: str) -> str | None:
    """Return a URL the UI can <img> load, or None if no avatar on disk.

    Convention: ``agents/<id>/avatar.{png,webp,jpg,svg}`` · served by the
    ``GET /api/agents/{id}/avatar`` route below. Keeping the check
    cheap (Path.is_file, no read) so every list-agents response
    doesn't hit the disk hard. If the file appears/disappears at
    runtime the next list call reflects it · no caching.
    """
    from runtime.execution.agents.loader import default_agents_root
    try:
        root = default_agents_root()
    except (OSError, ImportError):
        return None
    agent_dir = root / agent_id
    profile_path = agent_dir / "profile.jsonc"
    if profile_path.is_file():
        try:
            from runtime.platform.process.utils import parse_jsonc

            profile = parse_jsonc(profile_path.read_text(encoding="utf-8"))
            if "avatar" in profile and (
                profile.get("avatar") is None or profile.get("avatar") is False
            ):
                return None
        except (OSError, ValueError, TypeError):  # noqa: BLE001 — best-effort profile parse; fall through to file-extension detection
            pass
    for ext in ("png", "webp", "jpg", "jpeg", "svg"):
        path = agent_dir / f"avatar.{ext}"
        if path.is_file():
            return f"/api/agents/{agent_id}/avatar?v={int(path.stat().st_mtime)}"
    return None


def _agent_visual_urls_for(agent_id: str) -> dict[str, str]:
    from runtime.execution.agents.loader import default_agents_root

    try:
        root = default_agents_root()
    except (OSError, ImportError):
        return {}

    visuals_dir = root / agent_id / "visuals"
    urls: dict[str, str] = {}
    for view in ("front", "side", "back"):
        for ext in ("png", "jpg", "jpeg", "webp", "svg"):
            path = visuals_dir / f"{view}.{ext}"
            if path.is_file():
                urls[view] = (
                    f"/api/agents/{agent_id}/visuals/{view}"
                    f"?v={int(path.stat().st_mtime)}"
                )
                break

    reference = visuals_dir / "reference.png"
    if reference.is_file():
        version = int(reference.stat().st_mtime)
        for view in ("front", "side", "back"):
            urls.setdefault(
                view,
                f"/api/agents/{agent_id}/visuals/{view}?v={version}",
            )
    return urls


# ═══════════════════════════════════════════════════════════
# Pydantic wire models — see agents_models.py
# ═══════════════════════════════════════════════════════════

# ── LocalPartner subsystem ─────────────────────────────────────────
# All LocalPartner detection / registration / security primitives live
# in agents_local_partner.py. We re-bind them here with the legacy
# underscore-prefixed names so the closure-scoped router endpoints
# (which use _validate_local_partner_alias, _which_local_partner_command,
# etc.) keep working without further surgery.
from .agents_local_partner import (  # noqa: E402
    LOCAL_PARTNER_SPECS as _LOCAL_PARTNER_SPECS,
)
from .agents_local_partner import (
    identity_has_admin_role as _identity_has_admin_role,
)
from .agents_local_partner import (
    safe_executable as _safe_local_partner_executable,
)
from .agents_local_partner import (
    to_wire as _local_partner_wire,
)
from .agents_local_partner import (
    validate_alias as _validate_local_partner_alias,
)
from .agents_local_partner import (
    which_command as _which_local_partner_command,
)
from .agents_local_partner import (
    write_partner_agent as _write_local_partner_agent,
)
from .agents_models import (  # noqa: E402
    AgentDetailWire,
    AgentVisualsWire,
    AgentWire,
    ArmOptionWire,
    ArmWire,
    CapabilitiesWire,
    CreateAgentRequest,
    GenerateAgentVisualsRequest,
    GroupCreate,
    GroupUpdate,
    GroupWire,
    LocalPartnerRegisterRequest,
    LocalPartnerRegisterResponse,
    LocalPartnerRegisterResult,
    LocalPartnerWire,
    PauseTaskBody,
    ResumeTaskBody,
    ToolRegistryWire,
    UpdateAgentRequest,
)


def _to_wire(agent: Any) -> AgentWire:
    tool_groups = [str(arm.arm_id) for arm in agent.arms]
    return AgentWire(
        name=agent.agent_id,
        display_name=agent.display_name or None,
        description=agent.description,
        icon=agent.icon or None,
        avatar_url=_avatar_url_for(agent.agent_id),
        visual_urls=_agent_visual_urls_for(agent.agent_id),
        model=agent.model,
        tool_groups=tool_groups or None,
        soul=_soul_for_display(agent.soul),
        capabilities=dict(getattr(agent, "capabilities", {}) or {}),
    )


def _to_detail_wire(agent: Any) -> AgentDetailWire:
    try:
        skill_policy_obj = agent.skill_policy()
        allowed_skills = skill_policy_obj.as_list()
        skill_policy = {
            "allowed": allowed_skills,
            "sources": {
                source: list(names)
                for source, names in skill_policy_obj.sources.items()
            },
            "reason_map": {
                name: list(sources)
                for name, sources in skill_policy_obj.reason_map.items()
            },
            "allow_all": skill_policy_obj.allow_all,
        }
    except (AttributeError, TypeError, ValueError):
        allowed_skills = agent.allowed_skill_union()
        skill_policy = {}
    arms_wire = [
        ArmWire(
            arm_id=str(arm.arm_id),
            display_name=getattr(arm, "display_name", "") or "",
            description=getattr(arm, "description", "") or "",
            affinity=list(arm.affinity),
            icon=getattr(arm, "icon", "") or "",
        )
        for arm in agent.arms
    ]
    return AgentDetailWire(
        name=agent.agent_id,
        display_name=agent.display_name or None,
        description=agent.description,
        icon=agent.icon or None,
        avatar_url=_avatar_url_for(agent.agent_id),
        visual_urls=_agent_visual_urls_for(agent.agent_id),
        model=agent.model,
        tool_groups=[a.arm_id for a in arms_wire] or None,
        soul=_soul_for_display(agent.soul),
        capabilities=dict(getattr(agent, "capabilities", {}) or {}),
        arms=arms_wire,
        allowed_skills=allowed_skills,
        skill_policy=skill_policy,
        extra_affinity=list(agent.extra_affinity),
        budget=dict(getattr(agent, "budget", {}) or {}),
    )


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _group_to_wire(g: Any) -> GroupWire:
    return GroupWire(
        group_id=g.group_id,
        display_name=g.display_name,
        description=g.description,
        members=list(g.members),
        created_at=g.created_at.isoformat() if g.created_at else "",
        updated_at=g.updated_at.isoformat() if g.updated_at else "",
    )


def create_agents_router(
    *,
    registry: Any,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    journal: Any = None,
    group_registry: Any = None,
    runtime: Any = None,
    thread_store: Any = None,
) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["agents"])

    def _auth(request: Any) -> str | None:
        from .openai_gateway_router import _resolve_actor
        return _resolve_actor(
            request, identity_store, require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    def _resolve_identity(request: Any) -> Any:
        """Resolve full Identity (not just actor_id) for endpoints that
        need to check roles. Returns ``None`` when require_auth is off
        (single-user dev mode) or when no identity_store is wired.
        """
        if not require_auth or identity_store is None:
            return None
        auth = request.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            return None
        token = auth[7:].strip()
        if jwt_secret and token.count(".") == 2:
            with contextlib.suppress(Exception):
                identity = identity_store.verify_jwt(
                    token,
                    secret=jwt_secret,
                    required_issuer=jwt_issuer,
                    required_audience=jwt_audience,
                )
                if identity is not None:
                    return identity
        with contextlib.suppress(Exception):
            return identity_store.verify_api_key(token)
        return None

    def _require_admin(request: Any) -> None:
        """Gate for high-risk endpoints (writes to global agent registry,
        triggers subprocess discovery, mutates SOUL.md).

        Single-user dev mode (require_auth=False) bypasses this — that's
        consistent with how the rest of the router treats _auth. When
        require_auth=True, the resolved identity must carry the
        ``admin`` role.
        """
        _auth(request)  # AUTH-OK: actor-agnostic — credential check; role check follows
        if not require_auth:
            return
        identity = _resolve_identity(request)
        if not _identity_has_admin_role(identity):
            raise HTTPException(403, "admin role required")

    def _require_task_owner(request: Any, task_id: str) -> str | None:
        """Enforce that the caller owns the thread containing ``task_id``.

        The chain is task_id → ActiveTask.thread_id → Thread.metadata
        ["owner_id"]. Returns actor_id (None in dev mode). Raises 404
        if the task doesn't exist; 403 if the caller doesn't own its
        thread.

        Backward-compat: tasks whose threads have ``owner_id is None``
        (legacy or dev-mode threads) are visible to everyone — matching
        the parallel_agents_router pattern. Once all threads are
        created with owner_id, this branch rarely fires.
        """
        actor = _auth(request)
        if not require_auth:
            return actor
        if not actor:
            raise HTTPException(401, "authentication required")
        from runtime.core.cerebrum.pause_control import get_pause_controller
        ctrl = get_pause_controller()
        thread_id = ctrl.get_task_thread_id(task_id)
        if thread_id is None:
            raise HTTPException(404, f"task not found: {task_id}")
        if thread_store is None:
            # No thread_store wired → can't verify ownership. Allow
            # for backward-compat but log a warning. Operators should
            # wire thread_store= when constructing this router.
            return actor
        try:
            thread = thread_store.get_state(thread_id)
        except (AttributeError, TypeError):
            thread = None
        if thread is None:
            return actor  # thread missing — defer to endpoint's own 404
        owner = (thread.get("metadata") or {}).get("owner_id")
        if owner is not None and owner != actor:
            raise HTTPException(403, "not the owner of this task's thread")
        return actor

    def _require_thread_owner(request: Any, thread_id: str) -> str | None:
        """Enforce that the caller owns ``thread_id``.

        Used by /api/conversations/{id}/events and similar endpoints
        that take thread_id directly. Same backward-compat as
        _require_task_owner.
        """
        actor = _auth(request)
        if not require_auth:
            return actor
        if not actor:
            raise HTTPException(401, "authentication required")
        if thread_store is None:
            return actor  # no store wired → can't verify
        try:
            thread = thread_store.get_state(thread_id)
        except (AttributeError, TypeError):
            thread = None
        if thread is None:
            return actor
        owner = (thread.get("metadata") or {}).get("owner_id")
        if owner is not None and owner != actor:
            raise HTTPException(403, "not the owner of this thread")
        return actor

    # Agent IDs that should not appear in the agent gallery/picker.
    # These agents are system-level or capability-only and have their own
    # dedicated entry points.
    _AGENT_GALLERY_SKIP_IDS = frozenset({"admin", "desktop_operator"})  # noqa: N806

    @router.get("/api/agents")
    def list_agents(request: Request) -> list[AgentWire]:
        _auth(request)  # AUTH-OK: actor-agnostic — agent registry is server-global
        return [
            _to_wire(a)
            for a in registry.all_agents()
            if a.agent_id not in _AGENT_GALLERY_SKIP_IDS
        ]

    @router.post("/api/agents", status_code=201)
    def create_agent(request: Request, body: CreateAgentRequest) -> AgentDetailWire:
        """Create a new agent from scratch.

        Creates the agent directory structure, writes profile.jsonc and
        agent-core/SOUL.md, then hot-loads the agent into the registry.
        """
        _require_admin(request)  # Mutation: writes to global agents/ dir + loads code
        if runtime is None:
            raise HTTPException(
                503, "agent creation needs a GraphRuntime in this router"
            )

        # Validate agent_id
        agent_id = body.name.strip()
        if not agent_id:
            raise HTTPException(400, "agent name is required")
        if "/" in agent_id or "\\" in agent_id or agent_id in (".", ".."):
            raise HTTPException(400, "invalid agent_id: cannot contain path separators")
        if not agent_id.replace("-", "").replace("_", "").isalnum():
            raise HTTPException(
                400, "invalid agent_id: only alphanumeric, hyphens, and underscores allowed"
            )

        # Check for reserved names
        if agent_id in _BUILTIN_AGENT_IDS:
            raise HTTPException(400, f"agent_id '{agent_id}' is reserved")

        from runtime.execution.agents.loader import (
            default_agents_root,
            load_agent,
        )

        root = default_agents_root()
        agent_dir = root / agent_id

        # Check if agent already exists
        if agent_dir.exists():
            raise HTTPException(409, f"agent already exists: {agent_id}")
        if registry.has(agent_id):
            raise HTTPException(409, f"agent already registered: {agent_id}")

        # Create directory structure
        try:
            agent_dir.mkdir(parents=True)
            (agent_dir / "agent-core").mkdir()
            (agent_dir / "agent-core" / ".soul_history").mkdir()
            (agent_dir / "agent-core" / "diary").mkdir()
            (agent_dir / "agent-core" / "skills").mkdir()
            (agent_dir / "memory").mkdir()
            (agent_dir / "permissions").mkdir()
            (agent_dir / "project").mkdir()
            (agent_dir / "runtime").mkdir()
            (agent_dir / "sessions").mkdir()
            (agent_dir / "skills").mkdir()
        except OSError as exc:
            raise HTTPException(
                500, f"failed to create agent directories: {type(exc).__name__}: {exc}"
            ) from exc

        # Generate a unique DID
        import uuid
        did = f"DID-{uuid.uuid4().hex[:12].upper()}-{uuid.uuid4().hex[:6].upper()}"

        # Build profile.jsonc
        import json

        from runtime.platform.io import atomic_write_text
        profile = {
            "id": agent_id,
            "templateId": agent_id,
            "templateVersion": "1.0.0",
            "name": agent_id.replace("-", " ").replace("_", " ").title(),
            "icon": "🤖",
            "did": did,
            "description": body.description or f"A custom agent named {agent_id}.",
            "avatar": "avatar.svg",
            "model": {
                "provider": "auto",
                "name": body.model or "auto"
            },
            "runtime": "local",
            "creator": "user",
            "defaultProject": {
                "dir": "project"
            },
            "capabilities": {}
        }

        profile_path = agent_dir / "profile.jsonc"
        try:
            profile_text = (
                f"// Octopus Agent profile · {agent_id}\n"
                "// Created by user via API\n\n"
                + json.dumps(profile, ensure_ascii=False, indent=2)
            )
            atomic_write_text(profile_path, profile_text)
        except OSError as exc:
            raise HTTPException(
                500, f"failed to write profile.jsonc: {type(exc).__name__}: {exc}"
            ) from exc

        # Write SOUL.md
        soul_content = body.soul or f"""# Soul

You are {agent_id}, a helpful AI assistant.

## Personality

- Friendly and professional.
- Clear and concise in communication.
- Adaptable to various tasks.

## Values

- Be helpful while respecting user autonomy.
- Provide accurate information.
- Acknowledge limitations when uncertain.

---

_This file is yours to evolve. As you learn who you are, update it._
"""
        soul_path = agent_dir / "agent-core" / "SOUL.md"
        try:
            atomic_write_text(soul_path, soul_content, newline=None)
        except OSError as exc:
            raise HTTPException(
                500, f"failed to write SOUL.md: {type(exc).__name__}: {exc}"
            ) from exc

        # Write default IDENTITY.md
        identity_content = f"""# Identity

- **Name**: {agent_id}
- **Role**: Custom AI assistant

## Communication Style

- Clear and professional.
- Matches the user's language.
- Provides helpful, accurate information.

## Available arms

- Configurable via tool-registry.jsonc
"""
        identity_path = agent_dir / "agent-core" / "IDENTITY.md"
        try:
            atomic_write_text(identity_path, identity_content, newline=None)
        except OSError as exc:
            raise HTTPException(
                500, f"failed to write IDENTITY.md: {type(exc).__name__}: {exc}"
            ) from exc

        # Write default AGENTS.md
        agents_md_content = """# Working rules (shared by all Octopus agents)

## Project context discovery

Before starting any task, automatically discover the project context.

## Following conventions

When making changes, first read the surrounding code.

## Security

- Never introduce code that exposes or logs secrets.
- Never commit secrets or keys to the repository.
"""
        agents_md_path = agent_dir / "agent-core" / "AGENTS.md"
        try:
            atomic_write_text(agents_md_path, agents_md_content, newline=None)
        except OSError as exc:
            raise HTTPException(
                500, f"failed to write AGENTS.md: {type(exc).__name__}: {exc}"
            ) from exc

        # Write default avatar.svg
        avatar_svg = pixel_agent_avatar_svg(profile["name"])
        avatar_path = agent_dir / "avatar.svg"
        try:
            atomic_write_text(avatar_path, avatar_svg, newline=None)
        except OSError as exc:
            raise HTTPException(
                500, f"failed to write avatar.svg: {type(exc).__name__}: {exc}"
            ) from exc

        # Write tool-registry.jsonc if tool_groups provided
        if body.tool_groups:
            tool_registry = {
                "arms": list(body.tool_groups),
                "extra_affinity": [],
                "private_skills": []
            }
            tool_registry_path = agent_dir / "agent-core" / "tool-registry.jsonc"
            try:
                tool_text = (
                    "// Tool registry for this agent\n\n"
                    + json.dumps(tool_registry, ensure_ascii=False, indent=2)
                )
                atomic_write_text(tool_registry_path, tool_text)
            except OSError as exc:
                raise HTTPException(
                    500, f"failed to write tool-registry.jsonc: {type(exc).__name__}: {exc}"
                ) from exc

        # Hot-load the new agent
        try:
            new_agent = load_agent(agent_dir, runtime, root / "_shared")
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(
                500, f"agent load failed after creation: {type(exc).__name__}: {exc}"
            ) from exc

        registry.register(new_agent)
        return _to_detail_wire(new_agent)

    @router.get("/api/agents/local-partners")
    def list_local_partners(request: Request) -> dict[str, list[LocalPartnerWire]]:
        # Listing is read-only — does NOT require admin (a regular
        # user can ask "what's installed" without being able to register).
        _auth(request)  # AUTH-OK: actor-agnostic — registry is server-global
        return {
            "partners": [
                _local_partner_wire(
                    spec, registry, which_fn=_which_local_partner_command,
                )
                for spec in _LOCAL_PARTNER_SPECS.values()
            ]
        }

    @router.post("/api/agents/local-partners/register")
    def register_local_partners(
        request: Request,
        body: LocalPartnerRegisterRequest,
    ) -> LocalPartnerRegisterResponse:
        # Mutates the global agent registry, writes SOUL.md / IDENTITY.md
        # under default_agents_root(), and binds the agent to a real
        # subprocess command. Admin-only when require_auth=True.
        _require_admin(request)
        if runtime is None:
            raise HTTPException(
                503, "local partner registration needs a GraphRuntime in this router"
            )
        if not body.partners:
            raise HTTPException(400, "at least one local partner is required")

        # Reject the whole request on any malformed alias before we
        # start writing files — atomic from the caller's POV.
        validated_aliases: dict[str, str] = {}
        for item in body.partners:
            try:
                validated_aliases[item.id] = _validate_local_partner_alias(item.alias)
            except ValueError as exc:
                raise HTTPException(400, f"{item.id}: {exc}") from exc

        results: list[LocalPartnerRegisterResult] = []
        registered_count = 0
        already_exists_count = 0
        skipped_count = 0

        for item in body.partners:
            spec = _LOCAL_PARTNER_SPECS.get(item.id)
            if spec is None:
                skipped_count += 1
                results.append(LocalPartnerRegisterResult(
                    id=item.id,
                    agent_id="",
                    status="error",
                    message=f"unknown local partner: {item.id}",
                ))
                continue

            agent_id = str(spec["agent_id"])
            alias = validated_aliases[item.id] or str(spec["default_alias"])
            if registry.has(agent_id):
                already_exists_count += 1
                results.append(LocalPartnerRegisterResult(
                    id=str(spec["id"]),
                    agent_id=agent_id,
                    status="already_exists",
                    message="already registered",
                    agent=_to_detail_wire(registry.get(agent_id)),
                ))
                continue

            command, executable = _which_local_partner_command(list(spec["commands"]))
            if not executable or not command:
                skipped_count += 1
                results.append(LocalPartnerRegisterResult(
                    id=str(spec["id"]),
                    agent_id=agent_id,
                    status="not_detected",
                    message="local executable was not found on PATH",
                ))
                continue

            # PATH-poisoning guard: reject executables that resolve into
            # the user's home or the current working directory subtree.
            # An attacker dropping ``claude.cmd`` in cwd would otherwise
            # win the PATH race.
            if not _safe_local_partner_executable(executable):
                skipped_count += 1
                results.append(LocalPartnerRegisterResult(
                    id=str(spec["id"]),
                    agent_id=agent_id,
                    status="error",
                    message=(
                        f"refusing to register executable from a user-writable "
                        f"location: {executable}"
                    ),
                ))
                continue

            try:
                agent = _write_local_partner_agent(
                    spec=spec,
                    alias=alias,
                    command=command,
                    executable=executable,
                    runtime=runtime,
                    registry=registry,
                )
            except (OSError, ValueError, TypeError) as exc:
                skipped_count += 1
                results.append(LocalPartnerRegisterResult(
                    id=str(spec["id"]),
                    agent_id=agent_id,
                    status="error",
                    message=f"{type(exc).__name__}: {exc}",
                ))
                continue

            registered_count += 1
            results.append(LocalPartnerRegisterResult(
                id=str(spec["id"]),
                agent_id=agent_id,
                status="registered",
                message="registered",
                agent=_to_detail_wire(agent),
            ))

        return LocalPartnerRegisterResponse(
            results=results,
            registered_count=registered_count,
            already_exists_count=already_exists_count,
            skipped_count=skipped_count,
        )

    @router.put("/api/agents/{agent_id}")
    def update_agent(request: Request, agent_id: str, body: UpdateAgentRequest) -> AgentDetailWire:
        _require_admin(request)  # Mutation: rewrites profile.jsonc, reloads agent into registry
        if runtime is None:
            raise HTTPException(
                503, "agent update needs a GraphRuntime in this router"
            )
        if "/" in agent_id or "\\" in agent_id or agent_id in ("", ".", ".."):
            raise HTTPException(400, "invalid agent_id")

        from runtime.execution.agents.loader import (
            default_agents_root,
            load_agent,
        )
        from runtime.platform.io import atomic_write_text
        from runtime.platform.process.utils import parse_jsonc

        root = default_agents_root()
        agent_dir = root / agent_id
        profile_path = agent_dir / "profile.jsonc"
        if not profile_path.is_file():
            raise HTTPException(404, f"agent not found: {agent_id}")

        try:
            profile = parse_jsonc(profile_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise HTTPException(
                500, f"failed to read profile.jsonc: {type(exc).__name__}: {exc}"
            ) from exc

        provided_fields = set(getattr(body, "model_fields_set", None) or getattr(body, "__fields_set__", set()))
        display_name = (body.display_name or "").strip()
        if "display_name" in provided_fields:
            if not display_name:
                raise HTTPException(400, "display_name cannot be empty")
            profile["name"] = display_name
        if "description" in provided_fields:
            profile["description"] = body.description or ""
        if "model" in provided_fields:
            profile["model"] = {"provider": "auto", "name": (body.model or "").strip() or "auto"}

        try:
            profile_text = (
                f"// Octopus Agent profile · {agent_id}\n\n"
                + json.dumps(profile, ensure_ascii=False, indent=2)
            )
            atomic_write_text(profile_path, profile_text)
        except OSError as exc:
            raise HTTPException(
                500, f"failed to write profile.jsonc: {type(exc).__name__}: {exc}"
            ) from exc

        if "soul" in provided_fields:
            soul_path = agent_dir / "agent-core" / "SOUL.md"
            try:
                atomic_write_text(soul_path, body.soul, newline=None)
            except OSError as exc:
                raise HTTPException(
                    500, f"failed to write SOUL.md: {type(exc).__name__}: {exc}"
                ) from exc

        try:
            updated_agent = load_agent(agent_dir, runtime, root / "_shared")
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(
                500, f"agent load failed after update: {type(exc).__name__}: {exc}"
            ) from exc

        if hasattr(registry, "replace"):
            registry.replace(updated_agent)
        else:
            if registry.has(agent_id) and hasattr(registry, "remove"):
                registry.remove(agent_id)
            registry.register(updated_agent)
        return _to_detail_wire(updated_agent)

    @router.get("/api/agents/{agent_id}")
    def get_agent(request: Request, agent_id: str) -> AgentDetailWire:
        _auth(request)  # AUTH-OK: actor-agnostic — agents are server-global
        if not registry.has(agent_id):
            raise HTTPException(404, f"agent not found: {agent_id}")
        return _to_detail_wire(registry.get(agent_id))

    @router.post("/api/agents/{agent_id}/visuals/generate")
    def generate_agent_visuals_route(
        request: Request,
        agent_id: str,
        body: GenerateAgentVisualsRequest,
    ) -> AgentVisualsWire:
        _require_admin(request)  # Mutation: regenerates avatar via LLM, writes to disk
        if "/" in agent_id or "\\" in agent_id or agent_id in ("", ".", ".."):
            raise HTTPException(400, "invalid agent_id")
        if not registry.has(agent_id):
            raise HTTPException(404, f"agent not found: {agent_id}")

        from runtime.execution.agents.loader import default_agents_root
        from runtime.execution.misc.image_generation import generate_agent_visuals

        try:
            root = default_agents_root().resolve()
        except OSError as exc:
            raise HTTPException(500, f"agents root unavailable: {exc}") from exc

        agent_dir = (root / agent_id).resolve()
        try:
            agent_dir.relative_to(root)
        except ValueError as exc:
            raise HTTPException(400, "invalid agent path") from exc
        if not agent_dir.is_dir():
            raise HTTPException(404, f"agent folder not found: {agent_id}")

        agent = registry.get(agent_id)
        try:
            result = generate_agent_visuals(
                agent_id=agent_id,
                display_name=agent.display_name or agent_id,
                description=agent.description or "",
                output_dir=agent_dir / "visuals",
                style_prompt=body.style_prompt,
                provider=body.provider,
            )
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
            raise HTTPException(
                500,
                f"agent visual generation failed: {type(exc).__name__}: {exc}",
            ) from exc
        return AgentVisualsWire(
            agent_id=agent_id,
            provider=result.provider,
            prompt=result.prompt,
            visual_urls=_agent_visual_urls_for(agent_id),
        )

    @router.get("/api/agents/{agent_id}/visuals/{view}", include_in_schema=False)
    def get_agent_visual(request: Request, agent_id: str, view: str) -> Any:
        from runtime.execution.agents.loader import default_agents_root

        if "/" in agent_id or "\\" in agent_id or agent_id in ("", ".", ".."):
            raise HTTPException(400, "invalid agent_id")
        if view not in {"front", "side", "back"}:
            raise HTTPException(400, "invalid visual view")
        try:
            root = default_agents_root()
        except OSError as exc:
            raise HTTPException(500, f"agents root unavailable: {exc}") from exc

        visuals_dir = root / agent_id / "visuals"
        for ext, mime in (
            ("png", "image/png"),
            ("jpg", "image/jpeg"),
            ("jpeg", "image/jpeg"),
            ("webp", "image/webp"),
            ("svg", "image/svg+xml"),
        ):
            p = visuals_dir / f"{view}.{ext}"
            if p.is_file():
                return FileResponse(str(p), media_type=mime)
        reference = visuals_dir / "reference.png"
        if reference.is_file():
            return FileResponse(str(reference), media_type="image/png")
        raise HTTPException(404, f"no {view} visual for agent: {agent_id}")

    @router.delete("/api/agents/{agent_id}", status_code=204, response_class=Response, response_model=None)
    def delete_agent(request: Request, agent_id: str):
        _require_admin(request)  # Mutation: deletes agent directory + unloads from registry
        if "/" in agent_id or "\\" in agent_id or agent_id in ("", ".", ".."):
            raise HTTPException(400, "invalid agent_id")
        if agent_id in _BUILTIN_AGENT_IDS:
            raise HTTPException(400, f"agent_id '{agent_id}' is reserved")

        from runtime.execution.agents.loader import default_agents_root

        try:
            root = default_agents_root().resolve()
        except OSError as exc:
            raise HTTPException(500, f"agents root unavailable: {exc}") from exc

        agent_dir = (root / agent_id).resolve()
        try:
            agent_dir.relative_to(root)
        except ValueError as exc:
            raise HTTPException(400, "invalid agent path") from exc

        exists_on_disk = agent_dir.is_dir()
        exists_in_registry = registry.has(agent_id)
        if not exists_on_disk and not exists_in_registry:
            raise HTTPException(404, f"agent not found: {agent_id}")

        if exists_on_disk:
            import shutil

            try:
                shutil.rmtree(agent_dir)
            except OSError as exc:
                raise HTTPException(
                    500,
                    f"failed to delete agent directory: {type(exc).__name__}: {exc}",
                ) from exc

        if hasattr(registry, "remove"):
            registry.remove(agent_id)
        return

    @router.get("/api/agents/{agent_id}/avatar", include_in_schema=False)
    def get_agent_avatar(request: Request, agent_id: str) -> Any:
        """Serve ``agents/<id>/avatar.{png,webp,jpg,svg}`` from disk.

        Not auth-gated · avatars are UI decoration rendered in <img>
        tags. Adding the ``_auth`` check here would force every
        image-load to re-do the actor resolution and JWT parse,
        which is wasteful for a public-by-nature asset. Content is
        still scoped to the agents this instance has on disk · an
        attacker can't enumerate paths outside ``agents/<id>/``.
        """
        from runtime.execution.agents.loader import default_agents_root
        try:
            root = default_agents_root()
        except OSError as exc:
            raise HTTPException(500, f"agents root unavailable: {exc}") from exc
        # Reject path-traversal attempts early · agent_id should be a
        # plain slug, not something that could climb out of ``root``.
        if "/" in agent_id or "\\" in agent_id or agent_id in ("", ".", ".."):
            raise HTTPException(400, "invalid agent_id")
        agent_dir = root / agent_id
        profile_path = agent_dir / "profile.jsonc"
        if profile_path.is_file():
            try:
                from runtime.platform.process.utils import parse_jsonc

                profile = parse_jsonc(profile_path.read_text(encoding="utf-8"))
                if "avatar" in profile and (
                    profile.get("avatar") is None or profile.get("avatar") is False
                ):
                    raise HTTPException(404, f"no avatar for agent: {agent_id}")
            except HTTPException:
                raise
            except (OSError, ValueError, TypeError):  # noqa: BLE001 — best-effort profile parse; fall through to file-extension detection
                pass
        for ext, mime in (
            ("png", "image/png"),
            ("webp", "image/webp"),
            ("jpg", "image/jpeg"),
            ("jpeg", "image/jpeg"),
            ("svg", "image/svg+xml"),
        ):
            p = agent_dir / f"avatar.{ext}"
            if p.is_file():
                return FileResponse(str(p), media_type=mime)
        raise HTTPException(404, f"no avatar for agent: {agent_id}")

    @router.post("/api/agents/{agent_id}/reload")
    def reload_agent(request: Request, agent_id: str) -> dict[str, Any]:
        """Hot-reload one agent from disk.

        Re-reads ``agents/<agent_id>/`` (profile / soul / identity /
        tool-registry / memory / etc.) and swaps the in-memory Agent.
        Previously-issued Agent references used by in-flight turns keep
        their old soul by Python object identity — no torn state.

        Returns the new Agent wire view. 404 if the folder is gone;
        503 if hot-reload isn't available (runtime missing)."""
        _require_admin(request)  # Mutation: hot-reloads agent code into registry
        if runtime is None:
            raise HTTPException(
                503,
                "hot reload needs a GraphRuntime · pass runtime=... to "
                "create_agents_router",
            )
        from runtime.execution.agents.loader import (
            default_agents_root,
            load_agent,
        )
        root = default_agents_root()
        agent_dir = root / agent_id
        if not agent_dir.is_dir() or not (agent_dir / "profile.jsonc").exists():
            raise HTTPException(404, f"agent folder not found: {agent_id}")
        try:
            new_agent = load_agent(agent_dir, runtime, root / "_shared")
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(
                400, f"agent rebuild failed: {type(exc).__name__}: {exc}",
            ) from exc
        prev = registry.replace(new_agent)
        return {
            "ok": True,
            "agent": _to_wire(new_agent).model_dump(),
            "replaced": prev is not None,
        }

    @router.post("/api/agents/reload")
    def reload_all_agents(request: Request) -> dict[str, Any]:
        """Hot-reload every agent folder under ``agents/``.

        Drops-in-place-replaces each registered agent. Agents that are
        in the filesystem but not in the registry get registered. Agents
        in the registry but no longer on disk are left alone (would
        need an explicit delete endpoint to remove).
        """
        _require_admin(request)  # Mutation: bulk hot-reload of all agents
        if runtime is None:
            raise HTTPException(
                503, "hot reload needs a GraphRuntime in this router",
            )
        from runtime.execution.agents.loader import load_all_agents
        try:
            rebuilt = load_all_agents(runtime)
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(
                400, f"agent scan failed: {type(exc).__name__}: {exc}",
            ) from exc
        replaced = 0
        added = 0
        for agent in rebuilt:
            prev = registry.replace(agent)
            if prev is None:
                added += 1
            else:
                replaced += 1
        return {
            "ok": True,
            "replaced": replaced,
            "added": added,
            "total": len(rebuilt),
        }


    @router.get("/api/arms")
    def list_arms(request: Request) -> list[ArmOptionWire]:
        _auth(request)  # AUTH-OK: actor-agnostic — arm registry is server-global
        if runtime is None:
            raise HTTPException(
                503, "listing arms needs a GraphRuntime in this router",
            )
        from runtime.execution.agents.loader import _ARM_FACTORIES
        out: list[ArmOptionWire] = []
        for arm_id, factory in _ARM_FACTORIES.items():
            try:
                worker = factory(runtime)
            except (TypeError, ValueError, AttributeError):
                continue
            out.append(ArmOptionWire(
                arm_id=arm_id,
                display_name=getattr(worker, "display_name", "") or "",
                description=getattr(worker, "description", "") or "",
                affinity=list(worker.affinity),
                icon=getattr(worker, "icon", "") or "",
                skills=[str(s) for s in worker.allowed_skills],
            ))
        return out

    @router.get("/api/agents/{agent_id}/tool-registry")
    def get_tool_registry(
        request: Request, agent_id: str,
    ) -> ToolRegistryWire:
        _auth(request)  # AUTH-OK: actor-agnostic — tool-registry is read-only
        if "/" in agent_id or "\\" in agent_id or agent_id in ("", ".", ".."):
            raise HTTPException(400, "invalid agent_id")
        from runtime.execution.agents.loader import (
            _parse_jsonc,
            default_agents_root,
        )
        path = default_agents_root() / agent_id / "agent-core" / "tool-registry.jsonc"
        if not path.is_file():
            return ToolRegistryWire()
        try:
            data = _parse_jsonc(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(
                400,
                f"tool-registry parse failed: {type(exc).__name__}: {exc}",
            ) from exc
        return ToolRegistryWire(
            arms=[str(x) for x in (data.get("arms") or [])],
            extra_affinity=[str(x) for x in (data.get("extra_affinity") or [])],
            private_skills=[str(x) for x in (data.get("private_skills") or [])],
        )

    @router.put("/api/agents/{agent_id}/tool-registry")
    def put_tool_registry(
        request: Request,
        agent_id: str,
        body: ToolRegistryWire,
    ) -> AgentDetailWire:
        _require_admin(request)  # Mutation: rewrites agent tool-registry config
        if runtime is None:
            raise HTTPException(
                503, "tool-registry edits need a GraphRuntime in this router",
            )
        if "/" in agent_id or "\\" in agent_id or agent_id in ("", ".", ".."):
            raise HTTPException(400, "invalid agent_id")
        from runtime.execution.agents.loader import (
            _ARM_FACTORIES,
            default_agents_root,
            load_agent,
        )
        root = default_agents_root()
        agent_dir = root / agent_id
        if not agent_dir.is_dir() or not (agent_dir / "profile.jsonc").exists():
            raise HTTPException(404, f"agent folder not found: {agent_id}")

        # Validate arms · fail loud on unknown names
        unknown = [a for a in body.arms if a not in _ARM_FACTORIES]
        if unknown:
            raise HTTPException(
                400,
                "unknown arm(s): " + ", ".join(sorted(set(unknown)))
                + " · known: " + ", ".join(sorted(_ARM_FACTORIES)),
            )

        # Build JSON payload · preserve key order for git-friendly diffs
        import json
        payload = {
            "arms": list(body.arms),
            "extra_affinity": list(body.extra_affinity),
        }
        if body.private_skills:
            payload["private_skills"] = list(body.private_skills)

        core_dir = agent_dir / "agent-core"
        core_dir.mkdir(parents=True, exist_ok=True)
        target = core_dir / "tool-registry.jsonc"

        # Atomic write via shared utility (.bak rotation + fsync)
        from runtime.platform.io import atomic_write_text
        text = (
            "// arms reference factories in "
            "runtime/execution/arms/presets.py.\n"
            "// extra_affinity keywords boost agent matching by topic.\n"
            "// edited via PUT /api/agents/{id}/tool-registry\n\n"
            + json.dumps(payload, ensure_ascii=False, indent=2)
        )
        atomic_write_text(target, text)

        # Hot reload · reuse the same path as POST /api/agents/{id}/reload
        try:
            new_agent = load_agent(agent_dir, runtime, root / "_shared")
        except (OSError, ValueError, TypeError) as exc:
            raise HTTPException(
                400,
                f"agent rebuild failed after tool-registry save: "
                f"{type(exc).__name__}: {exc}",
            ) from exc
        registry.replace(new_agent)
        return _to_detail_wire(new_agent)


    @router.get("/api/tasks")
    def list_tasks(
        request: Request, status: str | None = None,
    ) -> dict[str, Any]:
        actor = _auth(request)
        from runtime.core.cerebrum.pause_control import get_pause_controller
        ctrl = get_pause_controller()

        # Filter to tasks owned by the caller. In dev mode (no auth) or
        # when thread_store is not wired, we fall back to "show all" —
        # matching the legacy behavior so existing dashboards don't
        # silently empty out.
        owned_threads: set[str] | None = None
        legacy_threads: set[str] = set()
        if require_auth and actor and thread_store is not None:
            owned_threads = ctrl.list_thread_ids_for_owner(thread_store, actor)
            # Legacy threads (no owner_id) are visible to everyone — same
            # backward-compat rule as the per-task / per-conversation
            # checks. Compute once so legacy items are kept in the lists.
            try:
                all_threads = thread_store.search(limit=10000)
                for thread in all_threads:
                    if (thread.get("metadata") or {}).get("owner_id") is None:
                        tid = thread.get("thread_id")
                        if tid:
                            legacy_threads.add(tid)
            except (TypeError, AttributeError):  # noqa: BLE001 — thread_store may be None or missing search() in dev mode
                pass

        def _is_owned(item: Any) -> bool:
            if owned_threads is None:
                return True  # dev mode / no store: show all
            tid = getattr(item, "thread_id", None) or ""
            # Tasks with no thread_id (legacy/unscoped) are visible
            if not tid:
                return True
            return tid in owned_threads or tid in legacy_threads

        def _to_dict(req: Any) -> dict[str, Any]:
            return req.to_dict()

        out: dict[str, Any] = {}
        if status in (None, "paused", "all"):
            out["paused"] = [
                _to_dict(r) for r in ctrl.list_paused() if _is_owned(r)
            ]
        if status in (None, "pending", "all"):
            out["pending"] = [
                _to_dict(r) for r in ctrl.list_pending() if _is_owned(r)
            ]
        if status in (None, "active", "all"):
            out["active"] = [
                t.to_dict() for t in ctrl.list_active() if _is_owned(t)
            ]
        return out

    @router.get("/api/tasks/{task_id}")
    def get_task(request: Request, task_id: str) -> dict[str, Any]:
        _require_task_owner(request, task_id)
        from runtime.core.cerebrum.pause_control import get_pause_controller
        ctrl = get_pause_controller()
        req = ctrl.get_request(task_id)
        out: dict[str, Any] = {
            "task_id": task_id,
            "is_pending_pause": task_id in {r.task_id for r in ctrl.list_pending()},
            "is_paused": ctrl.is_paused(task_id),
            "pause_request": req.to_dict() if req else None,
        }
        # Enrich with latest checkpoint if journal is available
        if journal is not None:
            try:
                ckpts = [
                    e for e in journal.read_by_type("react_checkpoint")
                    if str(getattr(e, "task_id", "")) == task_id
                ]
                if ckpts:
                    last = ckpts[-1]
                    out["last_checkpoint"] = {
                        "iteration_completed": last.iteration_completed,
                        "max_iterations": last.max_iterations,
                        "steps_count": len(last.steps_snapshot),
                        "has_final_answer": last.has_final_answer,
                    }
            except (AttributeError, TypeError, ValueError):  # noqa: BLE001 — best-effort field extract; skip on failure
                pass
            try:
                usage = [
                    {
                        "iteration": e.iteration,
                        "input_tokens": e.input_tokens,
                        "output_tokens": e.output_tokens,
                        "cost_usd": e.cost_usd,
                        "model": e.model,
                    }
                    for e in journal.read_by_type("token_usage")
                    if str(getattr(e, "task_id", "")) == task_id
                ]
                if usage:
                    usage.sort(key=lambda r: r["iteration"])
                    out["token_usage"] = usage
                    out["token_usage_total"] = {
                        "input_tokens": sum(u["input_tokens"] for u in usage),
                        "output_tokens": sum(u["output_tokens"] for u in usage),
                        "cost_usd": sum(u["cost_usd"] for u in usage),
                    }
            except (AttributeError, TypeError, ValueError):  # noqa: BLE001 — best-effort field extract; skip on failure
                pass
        return out

    @router.post("/api/tasks/{task_id}/pause")
    async def pause_task(
        request: Request, task_id: str, body: PauseTaskBody = PauseTaskBody(),
    ) -> dict[str, Any]:
        _require_task_owner(request, task_id)
        from runtime.core.cerebrum.pause_control import get_pause_controller
        ctrl = get_pause_controller()
        req = ctrl.request_pause(
            task_id=task_id, reason=body.reason, requested_by="", note=body.note,
        )
        return {"ok": True, "request": req.to_dict()}

    @router.delete("/api/tasks/{task_id}")
    def delete_task(request: Request, task_id: str) -> dict[str, Any]:
        _require_task_owner(request, task_id)
        from runtime.core.cerebrum.pause_control import get_pause_controller
        ctrl = get_pause_controller()
        ctrl.clear(task_id)
        ctrl.unregister_active(task_id)
        return {"ok": True, "task_id": task_id}

    @router.post("/api/tasks/{task_id}/resume")
    async def resume_task(
        request: Request, task_id: str, body: ResumeTaskBody = ResumeTaskBody(),
    ) -> dict[str, Any]:
        _require_task_owner(request, task_id)
        from runtime.core.cerebrum.pause_control import get_pause_controller
        ctrl = get_pause_controller()

        req = ctrl.get_request(task_id)
        thread_id = req.thread_id if req else ""
        if thread_id:
            ctrl.set_pending_resume(thread_id, task_id)
        if body.extra_iterations > 0 or body.extra_tokens > 0 or body.extra_usd > 0:
            ctrl.set_grant(
                task_id,
                extra_iterations=body.extra_iterations,
                extra_tokens=body.extra_tokens,
                extra_usd=body.extra_usd,
            )
        if journal is not None:
            with contextlib.suppress(Exception):
                journal.write_task_resumed(
                    task_id=task_id,
                    extra_tokens=body.extra_tokens,
                    extra_usd=body.extra_usd,
                    extra_iterations=body.extra_iterations,
                )
        return {
            "ok": True,
            "task_id": task_id,
            "thread_id": thread_id,
            "extra_tokens": body.extra_tokens,
            "extra_iterations": body.extra_iterations,
            "message": (
                f"登记 pending resume 到 thread {thread_id or '?'} · "
                "下条消息 run_stream 会自动接续"
            ),
        }


    @router.get("/api/regeneration/status")
    def evolution_status(request: Request) -> dict[str, Any]:
        _auth(request)  # AUTH-OK: actor-agnostic — regeneration scheduler status is server-global
        out: dict[str, Any] = {}
        try:
            from runtime.safety.recovery.scheduler import get_scheduler
            out["scheduler"] = get_scheduler().status()
        except (ImportError, AttributeError):
            out["scheduler"] = {"running": False, "error": "module load failed"}
        try:
            from runtime.safety.experiments.scheduler import (
                get_camouflage_scheduler,
            )
            out["camouflage"] = get_camouflage_scheduler().status()
        except (ImportError, AttributeError):
            out["camouflage"] = {
                "enabled": False,
                "running": False,
                "error": "module load failed",
            }
        import json as _json
        from pathlib import Path as _Path

        from runtime.execution.agents.loader import default_agents_root
        data_dir = _Path(default_agents_root()).parent / "data"
        files = {
            "learned_rules": "learned_rules.json",
            "learned_memories": "learned_memories.json",
            "workflow_proposals": "workflow_proposals.json",
            "recipe_scores": "recipe_scores.json",
            "gepa_proposals": "gepa_proposals.json",
            "forged_skills": "forged_skills.json",
        }
        for key, fname in files.items():
            p = data_dir / fname
            if p.is_file():
                try:
                    out[key] = _json.loads(p.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    out[key] = None
            else:
                out[key] = None
        return out


    @router.get("/api/settings/capabilities")
    def get_capabilities(request: Request) -> CapabilitiesWire:
        _auth(request)  # AUTH-OK: actor-agnostic — capabilities config is server-global
        from runtime.platform.runtime_policy.capabilities import load as _load_caps
        caps = _load_caps()
        return CapabilitiesWire(
            browser_automation=caps.browser_automation,
            desktop_automation=caps.desktop_automation,
        )

    @router.put("/api/settings/capabilities")
    def put_capabilities(
        request: Request, body: CapabilitiesWire,
    ) -> dict[str, Any]:
        _require_admin(request)  # Mutation: rewrites system-level capabilities
        from runtime.platform.runtime_policy.capabilities import Capabilities
        from runtime.platform.runtime_policy.capabilities import save as _save_caps
        caps = Capabilities(
            browser_automation=body.browser_automation,
            desktop_automation=body.desktop_automation,
        )
        try:
            _save_caps(caps)
        except OSError as exc:
            raise HTTPException(
                500, f"failed to write capabilities file: {exc}",
            ) from exc
        return {
            "ok": True,
            "capabilities": caps.to_dict(),
            "restart_required": True,
            "message": (
                "设置已保存 · 重启后端后生效(skill registry 只在启动时构造)"
            ),
        }


    if journal is not None:
        @router.get("/api/conversations")
        def list_conversations(
            request: Request,
            agent: str | None = None,
            limit: int = 50,
        ) -> list[dict[str, Any]]:
            actor = _auth(request)
            cids = journal.list_conversations(agent_id=agent)

            # Filter to conversations owned by the caller
            owned_threads: set[str] | None = None
            if require_auth and actor and thread_store is not None:
                from runtime.core.cerebrum.pause_control import get_pause_controller
                ctrl = get_pause_controller()
                owned_threads = ctrl.list_thread_ids_for_owner(thread_store, actor)

            out: list[dict[str, Any]] = []
            for cid in cids[:limit]:
                # Skip if not owned (when filtering is active)
                if owned_threads is not None and cid not in owned_threads:
                    continue
                events = journal.read_by_conversation(cid)
                if not events:
                    continue
                agents = {e.agent_id for e in events if e.agent_id}
                out.append({
                    "conversation_id": cid,
                    "agent_id": next(iter(agents)) if len(agents) == 1 else None,
                    "first_ts": events[0].ts.isoformat(),
                    "last_ts": events[-1].ts.isoformat(),
                    "event_count": len(events),
                })
            return out

        @router.get("/api/conversations/{conversation_id}/events")
        def get_conversation_events(
            request: Request,
            conversation_id: str,
            limit: int = 200,
        ) -> dict[str, Any]:
            _require_thread_owner(request, conversation_id)
            events = journal.read_by_conversation(conversation_id)
            if not events:
                raise HTTPException(
                    404, f"conversation not found: {conversation_id}",
                )
            return {
                "conversation_id": conversation_id,
                "total": len(events),
                "events": [
                    {
                        "event_id": str(e.event_id),
                        "event_type": e.event_type,
                        "ts": e.ts.isoformat(),
                        "task_id": str(e.task_id) if e.task_id else None,
                        "agent_id": e.agent_id,
                        "actor": e.actor,
                    }
                    for e in events[:limit]
                ],
            }


    if group_registry is not None:
        from runtime.execution.agents.groups import AgentGroup, AgentGroupNotFound

        @router.get("/api/groups")
        def list_groups(request: Request) -> list[GroupWire]:
            _auth(request)  # AUTH-OK: actor-agnostic — group registry is server-global
            return [_group_to_wire(g) for g in group_registry.list_all()]

        @router.get("/api/groups/{group_id}")
        def get_group(request: Request, group_id: str) -> GroupWire:
            _auth(request)  # AUTH-OK: actor-agnostic — group registry is server-global
            try:
                g = group_registry.get(group_id)
            except AgentGroupNotFound as e:
                raise HTTPException(404, f"group not found: {group_id}") from e
            return _group_to_wire(g)

        @router.post("/api/groups", status_code=201)
        def create_group(
            request: Request, body: GroupCreate,
        ) -> GroupWire:
            _require_admin(request)  # Mutation: creates agent group in registry
            try:
                group_registry.create(AgentGroup(
                    group_id=body.group_id,
                    display_name=body.display_name,
                    description=body.description,
                    members=body.members,
                ))
            except ValueError as e:
                msg = str(e)
                code = 409 if "duplicate" in msg else 400
                raise HTTPException(code, msg) from e
            return _group_to_wire(group_registry.get(body.group_id))

        @router.put("/api/groups/{group_id}")
        def update_group(
            request: Request, group_id: str, body: GroupUpdate,
        ) -> GroupWire:
            _require_admin(request)  # Mutation: updates agent group
            try:
                g = group_registry.update(
                    group_id,
                    display_name=body.display_name,
                    description=body.description,
                )
            except AgentGroupNotFound as e:
                raise HTTPException(404, f"group not found: {group_id}") from e
            return _group_to_wire(g)

        @router.delete("/api/groups/{group_id}", status_code=204, response_class=Response, response_model=None)
        def delete_group(request: Request, group_id: str):
            _require_admin(request)  # Mutation: deletes agent group
            if not group_registry.remove(group_id):
                raise HTTPException(404, f"group not found: {group_id}")
            return

        @router.post(
            "/api/groups/{group_id}/members/{agent_id}", status_code=200,
        )
        def add_member(
            request: Request, group_id: str, agent_id: str,
        ) -> dict[str, Any]:
            _require_admin(request)  # Mutation: adds agent to group
            if not registry.has(agent_id):
                raise HTTPException(404, f"agent not found: {agent_id}")
            try:
                added = group_registry.add_member(group_id, agent_id)
            except AgentGroupNotFound as e:
                raise HTTPException(404, f"group not found: {group_id}") from e
            except ValueError as e:
                raise HTTPException(400, str(e)) from e
            return {
                "group_id": group_id,
                "agent_id": agent_id,
                "added": added,
            }

        @router.delete(
            "/api/groups/{group_id}/members/{agent_id}", status_code=200,
        )
        def remove_member(
            request: Request, group_id: str, agent_id: str,
        ) -> dict[str, Any]:
            _require_admin(request)  # Mutation: removes agent from group
            try:
                removed = group_registry.remove_member(group_id, agent_id)
            except AgentGroupNotFound as e:
                raise HTTPException(404, f"group not found: {group_id}") from e
            return {
                "group_id": group_id,
                "agent_id": agent_id,
                "removed": removed,
            }

        @router.get("/api/groups/by-agent/{agent_id}")
        def groups_for_agent_ep(
            request: Request, agent_id: str,
        ) -> dict[str, Any]:
            _auth(request)  # AUTH-OK: actor-agnostic — group membership is server-global
            static_groups: list[str] = []
            if registry.has(agent_id):
                agent = registry.get(agent_id)
                static_groups = list(getattr(agent, "groups", []))
            dynamic_groups = group_registry.groups_for_agent(agent_id)
            effective = sorted(set(static_groups) | set(dynamic_groups))
            return {
                "agent_id": agent_id,
                "groups": effective,
                "static": static_groups,
                "dynamic": dynamic_groups,
            }

    return router
