"""
Meta router · feedback / skills / auth-provider listing.

Extracted from the monolithic ``runtime/platform/ui/app.py`` in the
app.py-split campaign. Houses the "reflective" endpoints that don't
belong to any one feature — feedback on replies, the registered
skill catalog the UI browses, and the list of configured login
methods.

Endpoints
---------

    POST /api/feedback          · record 👍/👎 on a reply
    GET  /api/feedback          · admin read-back with limit + filter
    GET  /api/skills            · registered skill catalog
    GET  /api/auth/providers    · login methods available to the UI

Design notes
------------

* **Stateless factory injection.** All per-app state (skill registry,
  feedback-log path, auth configs, identity store) flows in via
  ``create_meta_router`` kwargs. The function itself owns nothing
  beyond the local closures, matching the pattern in
  ``config_router.py``.
* **Actor resolution stays lazy.** The feedback handler wants an
  optional actor tag. Rather than bind the auth stack at factory
  time, we import ``_resolve_actor`` inside the handler — keeps this
  module light and lets the big openai_gateway module import without
  a circular.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from collections.abc import Sequence
from contextlib import suppress
from functools import lru_cache
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-untyped]

    YAML_AVAILABLE = True
except ImportError:  # pragma: no cover
    YAML_AVAILABLE = False
    yaml = None  # type: ignore[assignment]

try:
    from fastapi import APIRouter, HTTPException, Query, Request
    from pydantic import BaseModel

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Query = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]
    BaseModel = object  # type: ignore[assignment, misc]


_SAFE_SKILL_INSTALL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def _require_safe_skill_install_name(value: str, *, label: str = "skill name") -> str:
    name = str(value or "").strip()
    if not _SAFE_SKILL_INSTALL_NAME_RE.fullmatch(name):
        raise ValueError(
            f"invalid {label}: only alphanumeric characters, hyphens, and underscores are allowed"
        )
    return name


def _ensure_real_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise ValueError(f"{label} must be a real directory: {path}")
    if path.exists() and not path.is_dir():
        raise ValueError(f"{label} must be a directory: {path}")
    path.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{label} must be a real directory: {path}")
    return path


def _contains_symlink(directory: Path) -> bool:
    return any(child.is_symlink() for child in directory.rglob("*"))


def _install_public_skill_dir(skill_root: Path, skill_name: str) -> Path:
    name = _require_safe_skill_install_name(skill_name)
    if skill_root.is_symlink() or not skill_root.is_dir():
        raise ValueError(f"skill source must be a real directory: {skill_root}")
    if _contains_symlink(skill_root):
        raise ValueError(f"skill source must not contain symlinks: {skill_root}")
    if not (skill_root / "SKILL.md").is_file():
        raise FileNotFoundError(f"skill source missing SKILL.md: {skill_root}")

    skills_root = _ensure_real_directory(Path("skills/public"), "skills root")
    target = skills_root / name
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise FileExistsError(f"skill target is not a real directory: {name}")

    stage_parent: Path | None = None
    backup = skills_root / f".{name}.backup-{time.time_ns()}"
    backup_created = False
    try:
        import tempfile

        with tempfile.TemporaryDirectory(prefix=f".{name}.staged-", dir=skills_root) as tmpdir:
            stage_parent = Path(tmpdir)
            staged = stage_parent / name
            shutil.copytree(skill_root, staged)
            if target.exists():
                target.rename(backup)
                backup_created = True
            try:
                staged.rename(target)
            except OSError:
                if backup_created and backup.exists() and not target.exists():
                    backup.rename(target)
                raise
    finally:
        if backup_created and backup.exists():
            shutil.rmtree(backup, ignore_errors=True)
        if stage_parent is not None and stage_parent.exists():
            shutil.rmtree(stage_parent, ignore_errors=True)
    return target


def _uninstall_public_skill_dir(skill_name: str) -> Path:
    name = _require_safe_skill_install_name(skill_name)
    skills_root = _ensure_real_directory(Path("skills/public"), "skills root")
    target = skills_root / name
    if target.is_symlink():
        raise FileExistsError(f"skill target is not a real directory: {name}")
    if not target.exists():
        raise FileNotFoundError(f"skill directory not found: {name}")
    if not target.is_dir():
        raise NotADirectoryError(f"not a directory: {name}")
    shutil.rmtree(target)
    return target


# ═══════════════════════════════════════════════════════════
# Response models · shape the frontend can rely on
# ═══════════════════════════════════════════════════════════


if FASTAPI_AVAILABLE:

    class FeedbackEntry(BaseModel):
        ts: float
        sentiment: str  # "liked" | "disliked"
        message_id: str | None = None
        thread_id: str | None = None
        agent_id: str | None = None
        content_preview: str | None = None
        reason: str | None = None
        actor: str | None = None

    class FeedbackPostResponse(BaseModel):
        ok: bool
        recorded: FeedbackEntry

    class FeedbackListResponse(BaseModel):
        entries: list[FeedbackEntry]

    class SkillWire(BaseModel):
        name: str
        description: str
        affinity: list[str]
        cost_profile: str | None = None
        trusted_source: str | None = None
        has_tests: bool = False
        enabled: bool = True
        surface: str = "skill"
        permission_group: str | None = None
        category: str = "other"
        group: str | None = None
        kind: str = "domain"
        market_visibility: str = "market"
        market_reason: str | None = None
        canonical_skill: str | None = None

    class SkillsResponse(BaseModel):
        skills: list[SkillWire]

    class CapabilityPermissionWire(BaseModel):
        id: str
        enabled: bool
        available: bool
        skill_names: list[str]

    class CapabilityPermissionsResponse(BaseModel):
        permissions: list[CapabilityPermissionWire]

    class SlashCommandWire(BaseModel):
        name: str
        description: str = ""
        argument_hint: str = ""
        allowed_tools: list[str] = []
        model: str = ""
        source: str = ""

    class SlashCommandsResponse(BaseModel):
        commands: list[SlashCommandWire]

    class AuthProvider(BaseModel):
        # ``molili`` and ``local`` producers shape differently, so
        # stay permissive at the model level · the frontend checks
        # ``id`` and uses the id-specific fields it knows about.
        model_config = {"extra": "allow"}
        id: str
        label: str

    class AuthProvidersResponse(BaseModel):
        providers: list[AuthProvider]


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════


def create_meta_router(
    *,
    registry: Any,
    tool_registry: Any = None,
    mobile_skills_root: Path | str | None = None,
    feedback_path: Path | str = "data/feedback.jsonl",
    skill_library_dirs: Sequence[Path | str] | None = None,
    include_default_skill_library: bool = False,
    molili_config: Any = None,
    oct_config: Any = None,
    local_auth_config: Any = None,
    identity_store: Any = None,
    molili_jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> Any:
    """Build the FastAPI router.

    ╔════════════════════════════════════════════════════════════════════╗
    ║ meta_router.py · navigation map (1035 lines, closure factory).     ║
    ║                                                                    ║
    ║   §1 Pydantic models + enums                     ~L1-140           ║
    ║   §2 create_meta_router(...) factory             ~L143             ║
    ║       §2.1 feedback endpoints (POST + GET)        ~L190-269        ║
    ║       §2.2 skills browser + enable/disable        ~L270-376        ║
    ║       §2.3 skills install/uninstall               ~L378-527        ║
    ║       §2.4 user profile (GET + PUT)               ~L529-599        ║
    ║       §2.5 auth status + usage audit              ~L600-670        ║
    ║       §2.6 architecture docs endpoints            ~L672-701        ║
    ║   §3 helper functions (_default_skill_library_dir, etc.) ~L703     ║
    ╚════════════════════════════════════════════════════════════════════╝

    Parameters
    ----------
    registry :
        SkillRegistry — ``/api/skills`` iterates its contents.
    feedback_path :
        JSONL where ``/api/feedback`` appends. Kept as a parameter
        (default preserves the pre-split location) so tests can
        redirect it with ``tmp_path``.
    skill_library_dirs / include_default_skill_library :
        Optional file-backed SKILL.md catalogs to merge into the
        skill browser. These are read-only catalog entries; they do
        not register executable handlers in ``SkillRegistry``.
    molili_config / local_auth_config :
        Optional auth configs. Each is probed by the
        ``auth_providers`` handler for ``enabled`` and the fields
        it surfaces to the UI.
    identity_store / molili_jwt_secret :
        Passed through to ``_resolve_actor`` when tagging feedback
        with the submitting user. Both being ``None`` means
        anonymous feedback still records (tagged ``actor=None``).
    """
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["meta"])
    _feedback_path = Path(feedback_path)
    _skill_library_dirs = [Path(p) for p in (skill_library_dirs or [])]
    if include_default_skill_library:
        default_library = _default_skill_library_dir()
        if default_library not in _skill_library_dirs:
            _skill_library_dirs.append(default_library)

    def _require_admin(request: Request, *, purpose: str) -> None:
        """Require an authenticated admin actor for high-risk operations."""
        try:
            from runtime.sensing.gateway.openai_gateway import _resolve_actor

            actor = _resolve_actor(
                request,
                identity_store,
                True,
                jwt_secret=molili_jwt_secret,
                jwt_issuer=jwt_issuer,
                jwt_audience=jwt_audience,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(401, "auth required") from exc

        if identity_store is None or not actor:
            raise HTTPException(401, "auth required")

        auth_header = request.headers.get("Authorization") or ""
        if not auth_header.lower().startswith("bearer "):
            raise HTTPException(401, "missing Authorization: Bearer <token>")

        token = auth_header[7:].strip()
        identity = None
        if molili_jwt_secret and token.count(".") == 2:
            with suppress(Exception):
                identity = identity_store.verify_jwt(
                    token,
                    secret=molili_jwt_secret,
                    required_issuer=jwt_issuer,
                    required_audience=jwt_audience,
                )
        if identity is None:
            with suppress(Exception):
                identity = identity_store.verify_api_key(token)

        roles = getattr(identity, "roles", ()) or ()
        if "admin" not in {str(r).lower() for r in roles}:
            raise HTTPException(403, f"admin role required to {purpose}")

    # ─── Feedback ───────────────────────────────────────────

    @router.post("/api/feedback", response_model=FeedbackPostResponse)
    def api_feedback(
        body: dict[str, Any],
        request: Request,
    ) -> dict[str, Any]:
        sentiment = str(body.get("sentiment") or "").strip().lower()
        if sentiment not in ("liked", "disliked"):
            raise HTTPException(
                400,
                "sentiment must be 'liked' or 'disliked'",
            )
        actor: str | None = None
        try:
            from runtime.sensing.gateway.openai_gateway import _resolve_actor

            actor = (
                _resolve_actor(  # AUTH-OK: actor-agnostic — optional attribution for feedback log
                    request,
                    identity_store,
                    False,
                    jwt_secret=molili_jwt_secret,
                    jwt_issuer=jwt_issuer,
                    jwt_audience=jwt_audience,
                )
            )
        except Exception as exc:
            import logging as _logging

            _logging.getLogger(__name__).debug("auth resolution failed: %s", exc)

        entry = {
            "ts": time.time(),
            "sentiment": sentiment,
            "message_id": str(body.get("message_id") or "") or None,
            "thread_id": str(body.get("thread_id") or "") or None,
            "agent_id": str(body.get("agent_id") or "") or None,
            "content_preview": str(body.get("content_preview") or "")[:400] or None,
            "reason": str(body.get("reason") or "")[:200] or None,
            "actor": actor,
        }
        try:
            _feedback_path.parent.mkdir(parents=True, exist_ok=True)
            with _feedback_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            raise HTTPException(
                500,
                f"failed to record feedback: {exc}",
            ) from exc
        return {"ok": True, "recorded": entry}

    @router.get("/api/feedback", response_model=FeedbackListResponse)
    def api_feedback_list(
        request: Request,
        limit: int = Query(default=50, ge=1, le=500),
        thread_id: str | None = Query(default=None),
    ) -> dict[str, Any]:
        """Scan recent feedback entries from the end of the JSONL.

        Performance note: full file read per request · fine for the
        admin-dashboard use case (small log, single reader). If
        this ever becomes a hot path, replace with tail-read +
        LRU cache.
        """
        _require_admin(request, purpose="read feedback")
        if not _feedback_path.exists():
            return {"entries": []}
        try:
            lines = _feedback_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {"entries": []}
        out: list[dict[str, Any]] = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                # Single malformed row shouldn't void the whole list
                # — skip and continue. Consider alerting if this
                # happens in prod (corrupted writer).
                continue
            if thread_id and rec.get("thread_id") != thread_id:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return {"entries": out}

    # ─── Skills ─────────────────────────────────────────────

    @router.get("/api/skills", response_model=SkillsResponse)
    def api_skills() -> dict[str, Any]:
        skills_by_name: dict[str, dict[str, Any]] = {}
        dynamic_plugin_skills = _dynamic_plugin_skill_names()
        seen_sources: set[str] = set()
        try:
            registry_names = list(registry.all_names())
        except Exception as exc:  # noqa: BLE001
            _LOG.warning("api_skills: registry.all_names failed: %s", exc)
            registry_names = []
        for name in registry_names:
            try:
                s = registry.get(name)
                if _is_hidden_skill_catalog_entry(
                    str(s.name),
                    str(s.trusted_source or ""),
                    dynamic_plugin_skills,
                    seen_sources,
                ):
                    continue
                affinity = list(s.affinity)
                permission_group = _permission_group_for_skill(str(s.name))
                is_enabled = registry.is_enabled(s.name)
                group = _skill_group_for(str(s.name))
                kind = _skill_kind(group, str(s.name))
                market_profile = _skill_market_profile(
                    name=str(s.name),
                    description=str(s.description or ""),
                    trusted_source=str(s.trusted_source or ""),
                    group=group,
                    kind=kind,
                )
                skills_by_name[s.name] = {
                    "name": s.name,
                    "description": s.description,
                    "affinity": affinity,
                    "cost_profile": s.cost_profile,
                    "trusted_source": s.trusted_source,
                    "has_tests": s.has_tests,
                    "enabled": is_enabled,
                    "surface": "permission" if permission_group else "skill",
                    "permission_group": permission_group,
                    "category": _derive_skill_category(s.name, affinity),
                    "group": group,
                    "kind": kind,
                    **market_profile,
                }
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("api_skills: skipping registry skill %s: %s", name, exc)
                continue
        for skill in _load_file_skill_catalog(_skill_library_dirs):
            # Runtime-registered skills win because those entries are
            # executable and carry their real trust/test metadata.
            try:
                # Dynamic plugin names hide executable all_skills registry
                # entries so plugin-owned tools do not appear twice. Do not
                # apply that rule to the read-only file catalog: bundled
                # public SKILL.md entries (for example pdf) are the fallback
                # surface when the executable registry entry was hidden.
                if _is_hidden_skill_catalog_entry(
                    str(skill.get("name") or ""),
                    str(skill.get("trusted_source") or ""),
                    set(),
                    seen_sources,
                ):
                    continue
                skills_by_name.setdefault(skill["name"], skill)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("api_skills: skipping file skill %s: %s", skill, exc)
                continue
        skills = sorted(
            skills_by_name.values(),
            key=lambda item: str(item.get("name", "")).lower(),
        )
        return {"skills": skills}

    @router.get("/api/capability-catalog")
    def api_capability_catalog(
        q: str | None = Query(default=None),
        source: str | None = Query(default=None),
        kind: str | None = Query(default=None),
        risk_level: str | None = Query(default=None),
        permission_group: str | None = Query(default=None),
        available_only: bool = Query(default=False),
        limit: int = Query(default=500, ge=1, le=2000),
        offset: int = Query(default=0, ge=0),
    ) -> dict[str, Any]:
        from runtime.execution.misc.capability_catalog import (
            build_capability_catalog,
            filter_capability_entries,
        )

        catalog = build_capability_catalog(
            registry=registry,
            tool_registry=tool_registry,
            mobile_skills_root=mobile_skills_root,
        )
        filtered = filter_capability_entries(
            catalog["capabilities"],
            q=q,
            source=source,
            kind=kind,
            risk_level=risk_level,
            permission_group=permission_group,
            available_only=available_only,
            limit=limit,
            offset=offset,
        )
        filtered["summary"] = catalog["summary"]
        return filtered

    @router.post("/api/skills/{skill_name}/enable")
    def api_enable_skill(request: Request, skill_name: str) -> dict[str, Any]:
        _require_admin(request, purpose="modify skills")
        try:
            registry.enable(skill_name)
        except KeyError as exc:
            raise HTTPException(404, f"skill not found: {skill_name}") from exc
        return {"ok": True, "name": skill_name, "enabled": True}

    @router.post("/api/skills/{skill_name}/disable")
    def api_disable_skill(request: Request, skill_name: str) -> dict[str, Any]:
        _require_admin(request, purpose="modify skills")
        try:
            registry.disable(skill_name)
        except KeyError as exc:
            raise HTTPException(404, f"skill not found: {skill_name}") from exc
        return {"ok": True, "name": skill_name, "enabled": False}

    # ─── Skills-market enable / disable ────────────────────
    #
    #
    @router.post("/api/skills-market/{skill_id}/enable")
    def api_market_enable(request: Request, skill_id: str) -> dict[str, Any]:
        _require_admin(request, purpose="modify skills")
        if not registry.has(skill_id):
            from runtime.execution.suckers.market_skills import (
                load_single_market_skill,
            )

            loaded = load_single_market_skill(registry, skill_id)
            if not loaded:
                raise HTTPException(
                    404,
                    f"skill not found: {skill_id} (no SKILL.md in all_skills/)",
                )
        try:
            registry.enable(skill_id)
        except KeyError as exc:
            raise HTTPException(404, f"skill not found: {skill_id}") from exc
        return {"ok": True, "skill_id": skill_id, "enabled": True}

    @router.post("/api/skills-market/{skill_id}/disable")
    def api_market_disable(request: Request, skill_id: str) -> dict[str, Any]:
        _require_admin(request, purpose="modify skills")
        try:
            registry.disable(skill_id)
        except KeyError as exc:
            raise HTTPException(404, f"skill not found: {skill_id}") from exc
        return {"ok": True, "skill_id": skill_id, "enabled": False}

    # ─── Skill install / uninstall ─────────────────────────
    @router.post("/api/skills/install")
    async def api_install_skill(request: Request) -> dict[str, Any]:
        import tempfile

        # Auth: this endpoint mutates skills/public which is auto-loaded
        # as Python code on next boot. It's effectively arbitrary-code
        # installation, so we require BOTH:
        #   1. authenticated caller (require_auth=True regardless of
        #      router config)
        #   2. admin role
        _require_admin(request, purpose="install skills")

        try:
            body = await request.json()
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise HTTPException(400, f"body: {exc}") from exc
        url = (body or {}).get("url", "")
        if not isinstance(url, str) or not url.startswith("http"):
            raise HTTPException(400, "url required (https://...)")
        name_override = (body or {}).get("name")

        # SSRF guard + DNS-rebinding-proof fetch. ``check_url`` alone
        # would re-resolve on connect; use safe_httpx_get which pins
        # the resolved IP as the connect target while keeping the
        # original host name in the Host header.
        from runtime.safety.auth.url_guard import check_url, safe_httpx_get

        verdict = check_url(url, allow_private=False)
        if not verdict.allow:
            raise HTTPException(400, f"url rejected: {verdict.reason}")

        # Validate the new name *now* before any network I/O so we
        # fail fast on hostile filenames (path traversal in
        # ``skills/public/<name>``).
        if name_override is not None:
            if not isinstance(name_override, str) or not name_override:
                raise HTTPException(400, "name must be a non-empty string")
            try:
                name_override = _require_safe_skill_install_name(name_override, label="name")
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc

        try:
            import httpx as _httpx
        except ImportError as e:
            raise HTTPException(500, "httpx required for skill install") from e

        # follow_redirects=False on the transport; safe_httpx_get
        # re-validates the next hop through check_url if we ever
        # enable follow_redirects. We keep it off so the network
        # topology of an outbound skill install stays one hop, one
        # check.
        try:
            r = safe_httpx_get(url, timeout=30.0, follow_redirects=False)
            r.raise_for_status()
        except ValueError as exc:
            raise HTTPException(400, f"url rejected: {exc}") from exc
        except (_httpx.HTTPError, ConnectionError, TimeoutError) as exc:
            raise HTTPException(502, f"download failed: {exc}") from exc
        if len(r.content) > 50 * 1024 * 1024:
            raise HTTPException(413, "archive too large (>50MB)")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            archive = tmp / "skill.zip"
            archive.write_bytes(r.content)
            extract_dir = tmp / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            # Use the hardened extractor (zip-slip + symlink-component +
            # size caps) instead of ``shutil.unpack_archive`` which has
            # none of those defenses.
            try:
                from runtime.execution.suckers.hub.installer import (
                    ArchiveSafetyError,
                    safe_extract_zip,
                )

                safe_extract_zip(r.content, extract_dir)
            except ArchiveSafetyError as exc:
                raise HTTPException(400, f"unsafe archive: {exc}") from exc
            except (OSError, ValueError) as exc:
                raise HTTPException(400, f"unpack failed: {exc}") from exc

            skill_dirs = list(extract_dir.rglob("SKILL.md"))
            if not skill_dirs:
                raise HTTPException(400, "no SKILL.md found in archive")
            skill_root = skill_dirs[0].parent
            skill_name = name_override or skill_root.name
            try:
                target = _install_public_skill_dir(skill_root, skill_name)
                skill_name = target.name
            except FileExistsError as exc:
                raise HTTPException(409, str(exc)) from exc
            except (FileNotFoundError, NotADirectoryError, ValueError) as exc:
                raise HTTPException(400, str(exc)) from exc
            except OSError as exc:
                raise HTTPException(
                    500,
                    f"skill install failed: {type(exc).__name__}: {exc}",
                ) from exc

        return {"ok": True, "name": skill_name, "path": str(target)}

    @router.delete("/api/skills/{skill_name}/uninstall")
    def api_uninstall_skill(request: Request, skill_name: str) -> dict[str, Any]:
        _require_admin(request, purpose="uninstall skills")
        try:
            _uninstall_public_skill_dir(skill_name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except FileExistsError as exc:
            raise HTTPException(409, str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(404, f"skill directory not found: {skill_name}") from exc
        except NotADirectoryError as exc:
            raise HTTPException(400, f"not a directory: {skill_name}") from exc
        except OSError as exc:
            raise HTTPException(
                500,
                f"skill uninstall failed: {type(exc).__name__}: {exc}",
            ) from exc
        return {"ok": True, "name": skill_name, "removed": True}

    @router.get(
        "/api/capability-permissions",
        response_model=CapabilityPermissionsResponse,
    )
    def api_capability_permissions() -> dict[str, Any]:
        from runtime.execution.misc.capability_permissions import (
            list_capability_permissions,
        )

        return {
            "permissions": list_capability_permissions(
                registered_skill_names=set(registry.all_names()),
            ),
        }

    @router.put(
        "/api/capability-permissions/{group}",
        response_model=CapabilityPermissionWire,
    )
    def api_capability_permission_update(
        request: Request,
        group: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        _require_admin(request, purpose="modify capability permissions")
        from runtime.execution.misc.capability_permissions import (
            list_capability_permissions,
            set_capability_group_enabled,
        )

        try:
            set_capability_group_enabled(group, bool(body.get("enabled")))
        except KeyError as exc:
            raise HTTPException(404, f"unknown capability group: {group}") from exc
        updated = list_capability_permissions(
            registered_skill_names=set(registry.all_names()),
        )
        return next(item for item in updated if item["id"] == group)

    # ─── Slash commands ─────────────────────────────────────

    @router.get(
        "/api/slash-commands",
        response_model=SlashCommandsResponse,
    )
    def api_slash_commands() -> dict[str, Any]:
        """Return the merged slash-command catalog (global ∪ project).

        Frontend `/` typeahead uses this to show the user what
        commands are available. Body is intentionally NOT sent — it
        can be long and the client doesn't need to render it until
        expansion time (server-side, via the run endpoint).
        """
        import os

        from runtime.execution.slash_commands import load_slash_commands

        project_dir = os.getcwd()
        try:
            cmds = load_slash_commands(project_dir=project_dir)
        except (OSError, KeyError, ValueError):
            cmds = []
        return {"commands": [c.as_dict() for c in cmds]}

    # ─── Auth status ────────────────────────────────────────

    _molili_enabled = bool(molili_config is not None and getattr(molili_config, "enabled", False))
    _local_auth_enabled = bool(
        local_auth_config is not None and getattr(local_auth_config, "enabled", False)
    )
    _any_auth_enabled = _molili_enabled or _local_auth_enabled

    @router.get("/api/auth/status")
    def auth_status() -> dict[str, Any]:
        has_jwt = _molili_enabled or _local_auth_enabled
        return {
            "enabled": _any_auth_enabled,
            "jwt_available": has_jwt,
            "allow_registration": False,
            "exempt_paths": [],
        }

    def auth_me(request: Request) -> dict[str, Any]:
        """Return the authenticated actor from the real identity store.

        This endpoint used to exist only in the optional stub router. With
        production auth enabled the frontend therefore made a guaranteed 404
        request on every reload even though the bearer token was valid.
        """
        if identity_store is None:
            raise HTTPException(401, "authentication required")

        from runtime.sensing.gateway.openai_gateway import _resolve_actor

        actor = _resolve_actor(
            request,
            identity_store,
            True,
            jwt_secret=molili_jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )
        if not actor:
            raise HTTPException(401, "authentication required")

        identity = identity_store.get(actor) if hasattr(identity_store, "get") else None
        metadata = dict(getattr(identity, "metadata", None) or {})
        roles = [str(role) for role in (getattr(identity, "roles", None) or ())]
        fallback_name = actor.split(":", 1)[-1] if ":" in actor else actor
        username = next(
            (
                str(metadata[key]).strip()
                for key in ("username", "display_name", "email", "mobile")
                if isinstance(metadata.get(key), str) and str(metadata[key]).strip()
            ),
            fallback_name,
        )
        permissions_raw = metadata.get("permissions")
        permissions = (
            [str(value) for value in permissions_raw]
            if isinstance(permissions_raw, (list, tuple))
            else []
        )
        response: dict[str, Any] = {
            "user_id": actor,
            "actor_id": actor,
            "username": username,
            "roles": roles,
            "permissions": permissions,
            "is_active": True,
        }
        for key in ("email", "mobile", "provider"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                response[key] = value.strip()
        return response

    # Leave the route to the compatibility stub when auth is disabled and no
    # real identity store exists; otherwise the generic handler would shadow
    # the stub's anonymous development response.
    if identity_store is not None:
        router.add_api_route("/api/auth/me", auth_me, methods=["GET"])

    # ─── Auth providers ─────────────────────────────────────

    @router.get(
        "/api/auth/providers",
        response_model=AuthProvidersResponse,
    )
    def auth_providers() -> dict[str, Any]:
        """Return the list of configured login methods.

        The frontend Login page hides tabs whose id isn't in the
        returned set — so an empty response means "no providers
        configured, don't show a broken form".
        """
        providers: list[dict[str, Any]] = []
        if oct_config is not None and getattr(oct_config, "enabled", False):
            providers.append(
                {
                    "id": "oct",
                    "label": "邮箱登录",
                    "mock_mode": bool(getattr(oct_config, "mock_mode", False)),
                    "endpoint_send": "/api/auth/oct/email/send",
                    "endpoint_verify": "/api/auth/oct/email/login",
                }
            )
        if molili_config is not None and getattr(
            molili_config,
            "enabled",
            False,
        ):
            providers.append(
                {
                    "id": "molili",
                    "label": "手机号登录",
                    "mock_mode": bool(
                        getattr(
                            getattr(molili_config, "auth", None),
                            "mock_mode",
                            False,
                        ),
                    ),
                    "endpoint_send": "/api/auth/molili/sms/send",
                    "endpoint_verify": "/api/auth/molili/sms/verify",
                }
            )
        if local_auth_config is not None and getattr(
            local_auth_config,
            "enabled",
            False,
        ):
            pw_required = bool(getattr(local_auth_config, "users", {}))
            providers.append(
                {
                    "id": "local",
                    "label": "本地登录",
                    "allow_any_username": bool(
                        getattr(local_auth_config, "allow_any_username", True),
                    ),
                    "password_required": pw_required,
                    "endpoint": "/api/auth/local/login",
                }
            )
        return {"providers": providers}

    #
    #

    ARCHITECTURE_DOCS: dict[str, str] = {  # noqa: N806
        "readme": "docs/architecture/README.md",
        "core-path": "docs/architecture/core-path.md",
        "high-res-map": "docs/architecture/high-res-map.md",
        "high-res-mermaid": "docs/architecture/high-res-map.mermaid.md",
        "chat-modes": "docs/architecture/chat-modes.md",
        "react-self-evo": "docs/architecture/react-self-evolution.md",
        "organ-tiering": "docs/architecture/organ-tiering.md",
        "module-map": "docs/architecture/module-map.md",
        "organ-cerebrum": "docs/architecture/organs/cerebrum.md",
        "organ-ganglia": "docs/architecture/organs/ganglia.md",
        "organ-beak": "docs/architecture/organs/beak.md",
        "organ-hearts": "docs/architecture/organs/hearts.md",
        "organ-chromatophores": "docs/architecture/organs/chromatophores.md",
    }

    @router.get("/api/architecture/docs")
    def list_architecture_docs() -> dict[str, Any]:
        return {
            "docs": [{"id": k, "path": v} for k, v in ARCHITECTURE_DOCS.items()],
        }

    @router.get("/api/architecture/docs/{doc_id}")
    def read_architecture_doc(doc_id: str) -> dict[str, Any]:
        rel = ARCHITECTURE_DOCS.get(doc_id)
        if rel is None:
            raise HTTPException(404, f"unknown doc id: {doc_id!r}")
        p = Path(rel)
        if not p.exists():
            raise HTTPException(404, f"file missing on disk: {rel}")
        try:
            content = p.read_text(encoding="utf-8")
        except OSError as e:
            raise HTTPException(500, f"read failed: {e}") from e
        return {"id": doc_id, "path": rel, "content": content}

    @router.get("/api/mentions/autocomplete")
    def mentions_autocomplete(
        q: str = "",
        workspace: str = "",
        thread_id: str = "",
        actor: str = "",
        scope: str = "all",
        limit: int = 20,
    ) -> dict[str, Any]:
        """Autocomplete suggestions for @-mentions in chat input.

        Returns mention items across multiple categories:
          - agent: registered agents (id, name, description)
          - plugin: installed plugins
          - skill: registered skills
          - pack: dynamic skill packs (research / web / browser / files / code)
          - file/symbol/folder/git/docs/web/terminal: workspace context
            (basic best-effort; rich workspace mentions live in their
            own routers if installed)

        Query parameters:
          q: filter substring (case-insensitive)
          workspace: workspace path for file/symbol scope (currently unused
            here; placeholder for future workspace router integration)
          thread_id: when provided, agent results are filtered to those
            active in the thread first, then padded with global agents
          actor: when provided, items previously used by this actor
            are ranked higher (cross-thread mention history)
          scope: "all" (default), "agent", "plugin", "skill", "pack"
          limit: max items to return (default 20, max 100)
        """
        del workspace  # reserved for future workspace-aware filtering
        max_items = max(1, min(100, int(limit or 20)))
        query = (q or "").strip().lower()
        category_filter = (scope or "all").strip().lower()
        if query.startswith("@"):
            query = query[1:]

        type_prefix = ""
        if ":" in query:
            type_prefix, _, query = query.partition(":")

        # Look up cross-thread history for ranking. Failures are
        # silently ignored — autocomplete still works without history.
        history_boost: dict[tuple[str, str], int] = {}
        if actor:
            try:
                from runtime.memory.users.mention_history import (
                    get_mention_history_store,
                )

                store = get_mention_history_store()
                for stat in store.top_for_actor(actor, limit=50):
                    history_boost[(stat.type, stat.identifier)] = stat.count
            except (
                ImportError,
                AttributeError,
                OSError,
            ):  # best-effort · autocomplete still works without history
                pass

        items: list[dict[str, Any]] = []

        def _matches(haystack: str) -> bool:
            if not query:
                return True
            return query in (haystack or "").lower()

        # ── Agents ───────────────────────────────────────────
        if (category_filter in {"all", "agent"}) and (not type_prefix or type_prefix == "agent"):
            try:
                agents_iter = (
                    list(registry.iter_agents()) if hasattr(registry, "iter_agents") else []
                )
            except (AttributeError, TypeError):
                agents_iter = []
            # Surface thread's active agents first when thread_id given
            active_agent_ids: set[str] = set()
            if thread_id:
                with suppress(Exception):
                    active_agent_ids = _resolve_thread_active_agents(thread_id, registry)
            ranked: list[tuple[bool, dict[str, Any]]] = []
            for agent in agents_iter:
                agent_id = str(getattr(agent, "id", "") or getattr(agent, "name", ""))
                if not agent_id:
                    continue
                display = str(getattr(agent, "display_name", "") or agent_id)
                desc = str(getattr(agent, "description", "") or "")
                if not (_matches(agent_id) or _matches(display) or _matches(desc)):
                    continue
                ranked.append(
                    (
                        agent_id in active_agent_ids,
                        {
                            "type": "agent",
                            "label": display,
                            "value": f"@agent:{agent_id}",
                            "description": desc[:120],
                            "icon": "agent",
                        },
                    )
                )
            ranked.sort(key=lambda pair: (not pair[0], pair[1]["label"].lower()))
            for _is_active, payload in ranked:
                items.append(payload)
                if len(items) >= max_items:
                    break

        # ── Plugins ──────────────────────────────────────────
        if (
            (category_filter in {"all", "plugin"})
            and (not type_prefix or type_prefix == "plugin")
            and len(items) < max_items
        ):
            try:
                plugin_router_module = __import__(
                    "runtime.sensing.gateway.plugins_router",
                    fromlist=["_LATEST_PLUGINS"],
                )
                plugins_list = getattr(plugin_router_module, "_LATEST_PLUGINS", []) or []
            except (ImportError, AttributeError):
                plugins_list = []
            for plugin in plugins_list:
                pid = str(plugin.get("id") or plugin.get("name") or "")
                if not pid:
                    continue
                name = str(plugin.get("name") or pid)
                desc = str(plugin.get("description") or "")
                if not (_matches(pid) or _matches(name) or _matches(desc)):
                    continue
                items.append(
                    {
                        "type": "plugin",
                        "label": name,
                        "value": f"@plugin:{pid}",
                        "description": desc[:120],
                        "icon": "plugin",
                    }
                )
                if len(items) >= max_items:
                    break

        # ── Skills ───────────────────────────────────────────
        if (
            (category_filter in {"all", "skill"})
            and (not type_prefix or type_prefix == "skill")
            and len(items) < max_items
        ):
            try:
                skill_iter = (
                    list(registry.iter_skills()) if hasattr(registry, "iter_skills") else []
                )
            except (AttributeError, TypeError):
                skill_iter = []
            for skill in skill_iter:
                sname = str(getattr(skill, "name", "") or "")
                if not sname:
                    continue
                sdesc = str(getattr(skill, "description", "") or "")
                if not (_matches(sname) or _matches(sdesc)):
                    continue
                items.append(
                    {
                        "type": "skill",
                        "label": sname,
                        "value": f"@skill:{sname}",
                        "description": sdesc[:120],
                        "icon": "skill",
                    }
                )
                if len(items) >= max_items:
                    break

        # ── Skill Packs ──────────────────────────────────────
        if (
            (category_filter in {"all", "pack"})
            and (not type_prefix or type_prefix == "pack")
            and len(items) < max_items
        ):
            try:
                from runtime.execution.suckers.delegation_skills import (
                    _DYNAMIC_SKILL_PACKS,
                )

                pack_dict = _DYNAMIC_SKILL_PACKS
            except (ImportError, AttributeError):
                pack_dict = {}
            for pack_name, pack_skills in pack_dict.items():
                pdesc = f"Bundled skills: {', '.join(pack_skills[:6])}" + (
                    "..." if len(pack_skills) > 6 else ""
                )
                if not (_matches(pack_name) or _matches(pdesc)):
                    continue
                items.append(
                    {
                        "type": "pack",
                        "label": pack_name,
                        "value": f"@pack:{pack_name}",
                        "description": pdesc[:120],
                        "icon": "pack",
                    }
                )
                if len(items) >= max_items:
                    break

        # Re-rank by cross-thread mention history when actor is given.
        # Items the actor has used before float to the top of their
        # bucket; ordering within "never used" is preserved.
        if history_boost:

            def _rank(item: dict[str, Any]) -> tuple[int, int]:
                key = (str(item.get("type", "")), str(item.get("value", "")).split(":", 1)[-1])
                # Negate so higher-count items sort first.
                return (0 if key in history_boost else 1, -history_boost.get(key, 0))

            items.sort(key=_rank)

        return {"items": items[:max_items], "count": len(items[:max_items])}

    @router.get("/api/threads/{thread_id}/active-agents")
    def thread_active_agents(thread_id: str) -> dict[str, Any]:
        """List agents that have participated in the given thread.

        Pulled from team room membership when the thread is bound to a
        team room, otherwise from message senders in the thread history.
        """
        try:
            agent_ids = _resolve_thread_active_agents(thread_id, registry)
        except (AttributeError, KeyError, TypeError):
            agent_ids = set()
        results: list[dict[str, Any]] = []
        for agent_id in sorted(agent_ids):
            try:
                agent = registry.get(agent_id) if hasattr(registry, "get") else None
            except (AttributeError, KeyError):
                agent = None
            if agent is None:
                results.append(
                    {
                        "id": agent_id,
                        "display_name": agent_id,
                        "description": "",
                    }
                )
                continue
            results.append(
                {
                    "id": agent_id,
                    "display_name": str(getattr(agent, "display_name", "") or agent_id),
                    "description": str(getattr(agent, "description", "") or "")[:200],
                }
            )
        return {"agents": results, "count": len(results)}

    return router


_INTERNAL_SKILL_GROUPS = {
    "agent_meta",
    "blackboard",
    "browser",
    "browser_act",
    "builtin",
    "code_intel",
    "computer",
    "cron",
    "fs_search",
    "fs_write",
    "git",
    "lsp",
    "memory",
    "shell",
    "skill_library",
    "web",
}

_INTERNAL_SKILL_PREFIXES = (
    "bb_",
    "browser_",
    "computer_",
    "git_",
    "live_browser_",
    "lsp_",
)

_INTERNAL_SKILL_NAMES = {
    "append_text_file",
    "apply_skill",
    "ask_user_question",
    "background_exec",
    "cancel_scheduled_task",
    "edit_file",
    "edit_text_file",
    "exec_shell",
    "exit_plan_mode",
    "file_stats",
    "find-skills",
    "glob_files",
    "grep_text",
    "hash_text",
    "ipython",
    "keyboard_type",
    "kill_background_exec",
    "kill_shell",
    "learn_skill_from_text",
    "list_cwd",
    "list_learned_skills",
    "list_scheduled_tasks",
    "mouse_click",
    "multi_edit_file",
    "query_skill",
    "read_background_output",
    "read_file",
    "read_file_range",
    "read_shell_output",
    "run_orchestration",
    "run_pipeline",
    "schedule_task",
    "search_capabilities",
    "search_skills",
    "todo_read",
    "todo_write",
    "tree",
    "use_capability",
    "write_text_file",
}

_DUPLICATE_SKILL_CANONICALS = {
    "ad-creative": "ad-copywriter",
    "earnings-preview-single": "earnings-preview",
    "gitlab-cli-skills": "gitlab-cli-guide",
    "http-load-profiler": "http-load-tester",
    "seo-analyzer": "seo-audit",
    "test-driven-dev": "tdd-coach",
    "test-driven-development": "tdd-coach",
}

_PROVIDER_SKILL_CANONICALS = {
    "agnes-image-generate": "generate_image",
    "seedream-image-generate": "generate_image",
    "agnes-video-generate": "generate_video",
    "agnes-video-poll": "generate_video",
    "seedance-video-generate": "generate_video",
    "generate_sound_effects": "generate_speech",
    "generate_speech": "speech-synthesis",
}

_INTERNAL_EXECUTION_MODES = {
    "deep-research-swarm": "deep-research",
    "pptx-author": "pptx",
    "xlsx-author": "xlsx",
}


def _skill_market_profile(
    *,
    name: str,
    description: str,
    trusted_source: str,
    group: str | None,
    kind: str,
) -> dict[str, str | None]:
    """Classify how a skill should appear in the user-facing market.

    This does not disable or unregister skills. It only gives the UI a
    stable visibility hint so internal primitives remain callable while
    the marketplace stays oriented around user-level capabilities.
    """
    skill_name = name.strip()
    lower_name = skill_name.lower()
    lower_desc = description.lower()

    if lower_name in _DUPLICATE_SKILL_CANONICALS:
        return {
            "market_visibility": "duplicate",
            "market_reason": "同类技能已有主入口，避免重复展示",
            "canonical_skill": _DUPLICATE_SKILL_CANONICALS[lower_name],
        }
    if lower_name in _PROVIDER_SKILL_CANONICALS:
        return {
            "market_visibility": "provider",
            "market_reason": "模型或供应商后端入口，归并到主技能下",
            "canonical_skill": _PROVIDER_SKILL_CANONICALS[lower_name],
        }
    if lower_name in _INTERNAL_EXECUTION_MODES:
        return {
            "market_visibility": "internal",
            "market_reason": "执行模式或无界面变体，由主技能自动选择",
            "canonical_skill": _INTERNAL_EXECUTION_MODES[lower_name],
        }
    if trusted_source.startswith("skill://forged/") or lower_name.startswith("forged_"):
        return {
            "market_visibility": "deprecated",
            "market_reason": "自动组合技能，用户价值低，保留给内部兼容",
            "canonical_skill": None,
        }
    if kind != "domain":
        return {
            "market_visibility": "internal",
            "market_reason": "系统或自动化原子技能，不作为市场能力展示",
            "canonical_skill": None,
        }
    if group in _INTERNAL_SKILL_GROUPS:
        return {
            "market_visibility": "internal",
            "market_reason": "底层工具技能，由 agent 自动调用",
            "canonical_skill": None,
        }
    if lower_name in _INTERNAL_SKILL_NAMES or lower_name.startswith(_INTERNAL_SKILL_PREFIXES):
        return {
            "market_visibility": "internal",
            "market_reason": "底层工具技能，由 agent 自动调用",
            "canonical_skill": None,
        }
    if "only when a user wants to create a reusable skill" in lower_desc:
        return {
            "market_visibility": "internal",
            "market_reason": "技能开发辅助入口，不混入普通能力市场",
            "canonical_skill": None,
        }
    return {
        "market_visibility": "market",
        "market_reason": None,
        "canonical_skill": None,
    }


# File-backed SKILL.md catalog. These entries power the frontend skill
# browser for prompt/workflow skills that do not have Python handlers.
_FRONTMATTER_PATTERN = re.compile(
    r"\A\s*---\s*\n(.*?)\n---\s*(?:\n|$)",
    re.DOTALL,
)


def _default_skill_library_dir() -> Path:
    """Preferred skill library directory (``skills/public/``).

    Falls back to the legacy in-package ``all_skills/`` directory when the
    external resources root is unavailable.
    """
    from runtime.platform.process.paths import resources_root

    external = resources_root() / "skills" / "public"
    if external.is_dir():
        return external
    return Path(__file__).resolve().parents[2] / "execution" / "all_skills"


def _permission_group_for_skill(skill_id: str) -> str | None:
    try:
        from runtime.execution.misc.capability_permissions import (
            permission_group_for_skill,
        )

        return permission_group_for_skill(skill_id)
    except (ImportError, AttributeError, KeyError):
        return None


# ═══════════════════════════════════════════════════════════
# Skill kind classification
#
# Source-of-truth lives in ``runtime.execution.all_skills.skill_kind`` ·
# keeps the system/automation/domain buckets consistent between the
# ``/api/skills`` wire payload and the ReAct catalog filter. We just
# re-import here for backward-compat local use (lazy to avoid circular
# import at module load time).
# ═══════════════════════════════════════════════════════════


def _skill_group_for(name: str) -> str | None:
    try:
        from runtime.execution.all_skills import skill_group

        return skill_group(name)
    except (ImportError, AttributeError, KeyError):
        return None


def _skill_kind(group: str | None, name: str = "") -> str:
    """Classify into ``"system" | "automation" | "domain"``.

    Thin wrapper · delegates to ``all_skills.skill_kind`` so the
    classification rules stay in one place.
    """
    try:
        from runtime.execution.all_skills import skill_kind as _classify

        return _classify(name)
    except (ImportError, AttributeError, KeyError):
        return "domain"


@lru_cache(maxsize=1)
def _dynamic_plugin_skill_names() -> set[str]:
    roots: list[Path] = []
    try:
        project = _default_skill_library_dir().parents[2]
    except Exception:
        project = Path.cwd()
    roots.extend(
        [
            project / ".octopus" / "plugins" / "codex",
            Path.home() / ".octopus" / "plugins" / "codex",
            project / ".codex" / "plugins" / "cache",
            Path.home() / ".codex" / "plugins" / "cache",
        ]
    )
    names: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            try:
                rel_parts = skill_md.relative_to(root).parts
            except ValueError:
                continue
            if "skills" not in rel_parts:
                continue
            try:
                text = skill_md.read_text(encoding="utf-8")
            except OSError:
                continue
            meta, _ = _parse_catalog_frontmatter(text)
            name = _clean_text(meta.get("name")) or skill_md.parent.name
            if name:
                names.add(name)
                names.add(skill_md.parent.name)
    return names


def _is_hidden_skill_catalog_entry(
    name: str,
    trusted_source: str,
    dynamic_names: set[str] | None = None,
    seen_sources: set[str] | None = None,
) -> bool:
    if not name:
        return False
    canonical_source = trusted_source.split("#", 1)[0]
    if seen_sources is not None and canonical_source in seen_sources:
        return True
    names = dynamic_names if dynamic_names is not None else _dynamic_plugin_skill_names()
    if name in names and trusted_source.startswith("skill://all_skills/"):
        return True
    if not canonical_source.startswith("skill://all_skills/"):
        if seen_sources is not None:
            seen_sources.add(canonical_source)
        return False
    rel = canonical_source.removeprefix("skill://all_skills/")
    if "#" in trusted_source or "/" in rel:
        return True
    if seen_sources is not None:
        seen_sources.add(canonical_source)
    return False


def _load_file_skill_catalog(
    roots: Sequence[Path],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for skill_md in sorted(root.rglob("SKILL.md")):
            if _should_skip_catalog_path(skill_md, root):
                continue
            try:
                skill = _skill_wire_from_md(skill_md, root=root)
            except Exception as exc:  # noqa: BLE001
                _LOG.warning("skipping catalog file %s after parse failure: %s", skill_md, exc)
                continue
            if skill is not None:
                out.append(skill)
    return out


def _should_skip_catalog_path(path: Path, root: Path) -> bool:
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return True
    return any(part.startswith(".") or part == "__pycache__" for part in parts)


def _skill_wire_from_md(
    skill_md: Path,
    *,
    root: Path,
) -> dict[str, Any] | None:
    try:
        text = skill_md.read_text(encoding="utf-8")
    except OSError:
        return None

    meta, body = _parse_catalog_frontmatter(text)
    name = _clean_text(meta.get("name")) or skill_md.parent.name
    description = (
        _clean_text(meta.get("description"))
        or _first_markdown_paragraph(body)
        or "File-backed skill from the bundled skill library."
    )
    affinity = _coerce_string_list(meta.get("affinity") or meta.get("tags"))
    for tag in _infer_catalog_affinity(name, description):
        if tag not in affinity:
            affinity.append(tag)
    trusted_source = _clean_text(meta.get("trusted_source"))
    if not trusted_source:
        rel_dir = _safe_relative_posix(skill_md.parent, root)
        trusted_source = f"skill://all_skills/{rel_dir}"
    cost_profile = _clean_text(meta.get("cost_profile"))
    has_tests = bool(meta.get("tests")) or (skill_md.parent / "tests").exists()
    market_profile = _skill_market_profile(
        name=name,
        description=description,
        trusted_source=trusted_source,
        group=None,
        kind="domain",
    )
    return {
        "name": name,
        "description": description,
        "affinity": affinity,
        "cost_profile": cost_profile,
        "trusted_source": trusted_source,
        "has_tests": has_tests,
        "category": _derive_skill_category(name, affinity),
        "group": None,
        "kind": "domain",
        **market_profile,
    }


def _parse_catalog_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    clean_text = text.lstrip("\ufeff")
    match = _FRONTMATTER_PATTERN.match(clean_text)
    if not match:
        return {}, text
    body = clean_text[match.end() :]
    raw_frontmatter = match.group(1)
    if YAML_AVAILABLE:
        try:
            parsed = yaml.safe_load(raw_frontmatter) or {}
        except (yaml.YAMLError, TypeError, ValueError):
            parsed = {}
        if isinstance(parsed, dict):
            return parsed, body
        return {}, body
    return _parse_simple_frontmatter(raw_frontmatter), body


def _parse_simple_frontmatter(raw: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        if key:
            data[key] = value.strip().strip("'\"")
    return data


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        raw_items = re.split(r"[,;\n]", value)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        raw_items = list(value)
    else:
        raw_items = [value]
    out: list[str] = []
    for item in raw_items:
        tag = _clean_text(item).lower()
        if tag and tag not in out:
            out.append(tag)
    return out


def _clean_text(value: Any, *, max_len: int = 640) -> str:
    if value is None:
        return ""
    text = " ".join(str(value).split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _first_markdown_paragraph(body: str) -> str:
    lines: list[str] = []
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line:
            if lines:
                break
            continue
        if line.startswith(("#", "```", "|", "<!--")):
            continue
        lines.append(line)
    return _clean_text(" ".join(lines))


def _safe_relative_posix(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.name


def _infer_catalog_affinity(name: str, description: str) -> list[str]:
    text = f"{name} {description}".lower()
    inferred: list[str] = []
    keyword_tags = [
        (
            "ecommerce",
            (
                "1688",
                "alibaba",
                "amazon",
                "amz",
                "shopify",
                "etsy",
                "dropshipping",
                "cross-border",
                "e-commerce",
                "ecommerce",
            ),
        ),
        (
            "sourcing",
            (
                "supplier",
                "sourcing",
                "product selection",
            ),
        ),
        (
            "research",
            (
                "research",
                "analysis",
                "market",
                "competitor",
                "insight",
                "analytics",
            ),
        ),
        (
            "content",
            (
                "copywriting",
                "description",
                "marketing",
                "social",
                "generate",
                "content",
            ),
        ),
        (
            "file",
            (
                "xlsx",
                "docx",
                "pdf",
                "pptx",
                "remotion",
                "website",
            ),
        ),
    ]
    for tag, keywords in keyword_tags:
        if any(keyword in text for keyword in keywords):
            inferred.append(tag)
    return inferred


# ═══════════════════════════════════════════════════════════
# Skill category derivation
# ═══════════════════════════════════════════════════════════
#
#

SKILL_CATEGORIES: dict[str, str] = {
    "sourcing": "货源与选品",
    "research": "市场调研与分析",
    "file": "文件与编码",
    "comm": "通讯与协作",
    "browse": "浏览与搜索",
    "content": "内容生成",
    "system": "系统",
    "memory": "记忆",
    "other": "其他",
}

_CATEGORY_PRIORITY: list[tuple[str, set[str]]] = [
    (
        "sourcing",
        {
            "sourcing",
            "supplier",
            "ecommerce",
            "shopify",
            "1688",
            "aliexpress",
            "cj",
            "amazon",
            "amz",
            "alibaba",
            "etsy",
            "dropshipping",
            "product-selection",
            "selection",
        },
    ),
    ("research", {"research", "analysis", "market", "competitor", "intelligence", "data"}),
    ("browse", {"browse", "browser", "search", "web"}),
    ("file", {"file", "write", "edit", "code", "git", "io"}),
    ("comm", {"im", "slack", "email", "wechat", "dingtalk", "telegram", "feishu", "discord"}),
    ("content", {"write_content", "generate", "translate", "summarize", "transform"}),
    ("memory", {"memory", "kg", "recall"}),
    ("system", {"system", "os", "process", "sandbox", "shell"}),
]


def _derive_skill_category(name: str, affinity: list[str]) -> str:
    tags = {t.lower() for t in affinity}
    name_l = name.lower()
    for cat_id, keywords in _CATEGORY_PRIORITY:
        if tags & keywords:
            return cat_id
        for kw in keywords:
            if kw in name_l:
                return cat_id
    return "other"


def _resolve_thread_active_agents(thread_id: str, registry: Any) -> set[str]:
    """Best-effort resolution of agents active in a thread.

    Strategy (each step is wrapped in suppress so a missing module or
    schema doesn't break the endpoint):

    1. team-room membership: if the thread is bound to a team room,
       use the room's member list.
    2. message history: scan recent messages for sender_agent_id.

    Returns an empty set when nothing can be resolved.
    """
    agent_ids: set[str] = set()
    if not thread_id:
        return agent_ids

    # 1) team room membership
    with suppress(Exception):
        rooms_module = __import__(
            "runtime.safety.organization.team_rooms",
            fromlist=["get_team_rooms_store"],
        )
        get_store = getattr(rooms_module, "get_team_rooms_store", None)
        if callable(get_store):
            store = get_store()
            room = None
            for candidate in store.list_rooms():
                if getattr(candidate, "thread_id", None) == thread_id:
                    room = candidate
                    break
            if room is not None:
                for member in getattr(room, "members", []) or []:
                    member_id = str(
                        getattr(member, "agent_id", "") or getattr(member, "name", "") or member,
                    )
                    if member_id:
                        agent_ids.add(member_id)

    # 2) message senders (last 100 messages, dedupe)
    with suppress(Exception):
        threads_module = __import__(
            "runtime.memory.thread_state",
            fromlist=["get_thread_state_store"],
        )
        get_store = getattr(threads_module, "get_thread_state_store", None)
        if callable(get_store):
            store = get_store()
            messages = list(store.list_messages(thread_id, limit=100))[-100:]
            for msg in messages:
                sender = str(
                    getattr(msg, "sender_agent_id", "") or getattr(msg, "agent_id", "") or "",
                )
                if sender:
                    agent_ids.add(sender)

    # 3) registry sanity-filter — only return ids the registry knows
    if hasattr(registry, "has"):
        return {aid for aid in agent_ids if registry.has(aid)}
    return agent_ids


__all__ = [
    "create_meta_router",
    "SKILL_CATEGORIES",
    "_derive_skill_category",
    "_resolve_thread_active_agents",
]
_LOG = logging.getLogger(__name__)
