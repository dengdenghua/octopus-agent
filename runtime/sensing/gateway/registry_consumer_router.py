"""资产 Registry 消费路由(母体接 registry · 只读浏览 + 安装 prompt-skill)。

把 octopus-runtime SDK([octopus_runtime])包成 HTTP 面:让母体前端/客户端能浏览公网 registry 的技能、
按需安装(下载→验签→落地 ``skills/public/<slug>/SKILL.md``→**运行时热注册**,无需重启)。

- GET  /api/registry/skills                列 registry 技能(search/category/offset/limit)
- GET  /api/registry/skills/{slug}         单技能详情(信封 + body 预览)
- POST /api/registry/skills/{slug}/install 安装:sync 落地 + 运行时注册

设计边界:**只装 prompt-pack(type=skill,body 当 prompt 注入、从不执行)**;执行型资产不过此路由。
additive 新文件,零碰 Codex WIP(cowork/oct/i18n);SDK 读/解析半边仍 runtime-free,本路由是产品侧 glue。
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, Depends, HTTPException, Query, Request

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover - fastapi optional at import time
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]

from runtime.sensing._fastapi_guard import require_fastapi

# registry 除 skill 外还托管 role / twin-role(数字分身岗位模板)/ plugin / task /
# twin / experience(见 asset.type,api.octoapk.com 实测 473 条)。角色类(role/
# twin-role)与 skill 同属 kind=data 声明式 prompt,落地规则等价 → 直接可"安装"成
# 本地可用 agent(同 enterprise_assets_router._scaffold_local_agent 的落地形状)。
# plugin 类目前统一标 kind=code(codex-plugin 集成说明),即便实测 body 常是纯文本,
# 出于沿用 octopus_runtime.materialize.SAFE_TYPES 的既有安全边界,本路由只做只读浏览、
# 不提供一键安装(避免绕过该边界)。
_ROLE_ASSET_TYPES = ("role", "twin-role")


def _ensure_safe_dir(path: Path) -> None:
    if path.is_symlink():
        raise ValueError(f"agent scaffold path must not be a symlink: {path}")
    if path.exists() and not path.is_dir():
        raise ValueError(f"agent scaffold path must be a directory: {path}")
    path.mkdir(parents=True, exist_ok=True)


def _atomic_write_text(path: Path, content: str) -> None:
    _ensure_safe_dir(path.parent)
    tmp: Path | None = None
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as f:
        tmp = Path(f.name)
        f.write(content)
        f.flush()
    try:
        tmp.replace(path)
    except Exception:
        if tmp is not None and tmp.exists():
            tmp.unlink()
        raise


def _scaffold_local_agent_from_registry_asset(asset: Any) -> tuple[str, Path]:
    """把 registry role/twin-role 资产落地成本地 agent(profile.jsonc + agent-core/*)。

    形状对齐 enterprise_assets_router._scaffold_local_agent:body 当 SOUL,
    写入 default_agents_root()/registry_<slug>/,下次 /api/agents 扫描即可见。
    """
    from runtime.execution.agents.loader import default_agents_root

    slug = str(getattr(asset, "slug", "") or asset.id.split("/")[-1])
    agent_id = f"registry_{re.sub(r'[^a-z0-9_]+', '_', slug.lower()).strip('_') or 'imported_role'}"
    name = asset.name or slug
    category = asset.category or "specialist"
    tags = list(asset.tags or [])
    description = asset.description or ""
    body = asset.body or ""

    agent_root = default_agents_root() / agent_id
    core = agent_root / "agent-core"
    _ensure_safe_dir(agent_root)
    _ensure_safe_dir(core)
    profile = {
        "id": agent_id,
        "name": name,
        "icon": "🌐",
        "did": f"DID-{agent_id.upper()}-REGISTRY",
        "description": description,
        "category": category,
        "tags": tags,
        "model": {"provider": "auto", "name": "auto"},
        "runtime": "local",
        "source": "registry",
    }
    _atomic_write_text(
        agent_root / "profile.jsonc", json.dumps(profile, ensure_ascii=False, indent=2)
    )
    soul = body or (
        f"You are {name}.\n\nPrimary mission: {description}\n\n"
        f"Specialties: {', '.join(tags)}.\nBe concise, action-oriented, and precise."
    )
    _atomic_write_text(core / "SOUL.md", soul)
    _atomic_write_text(
        core / "IDENTITY.md",
        f"- Name: {name}\n- Role: {category} specialist\n- Source: registry asset library\n",
    )
    _atomic_write_text(
        core / "tool-registry.jsonc",
        json.dumps(
            {"arms": ["fs_writer", "git", "shell"], "extra_affinity": tags, "private_skills": []},
            ensure_ascii=False,
            indent=2,
        ),
    )
    try:
        from runtime.execution.misc.agent_avatar import write_pixel_agent_avatar

        write_pixel_agent_avatar(agent_root / "avatar.svg", name)
    except Exception:  # noqa: BLE001 - 头像生成失败不阻断安装
        pass
    return agent_id, agent_root


def _asset_type(asset_id: str) -> str:
    return asset_id.split("/", 1)[0]


def _is_installable_role_asset(asset: Any) -> bool:
    return str(getattr(asset, "type", "") or "") in _ROLE_ASSET_TYPES and (
        str(getattr(asset, "kind", "") or "") == "data"
    )


def _register_runtime(skill_registry: Any, skills_root: Path) -> int:
    """把 skills_root 下的 prompt-skill 注册进**活 registry**(无需重启)。
    已注册的同名会被 register_market_skills 自身跳过,故只净增新装的。"""
    if skill_registry is None or not skills_root.is_dir():
        return 0
    try:
        from runtime.execution.suckers.market_skills import register_market_skills

        return int(
            register_market_skills(
                skill_registry,
                all_skills_dir=skills_root,
                respect_enabled_flag=False,
                verify_tests=False,
            )
        )
    except Exception:  # noqa: BLE001 - 注册失败不阻断安装(落地的文件下次启动仍会被加载)
        return 0


def create_registry_consumer_router(
    *,
    skill_registry: Any = None,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
    registry_base: str | None = None,
    skills_root: Path | str | None = None,
) -> Any:
    require_fastapi(__name__)

    import os

    base = (
        registry_base or os.environ.get("OCTOPUS_REGISTRY_URL") or "https://api.octoapk.com"
    ).rstrip("/")
    if skills_root is None:
        try:
            from runtime.platform.process.paths import resources_root

            skills_root = resources_root() / "skills" / "public"
        except Exception:  # noqa: BLE001
            skills_root = Path("skills/public")
    skills_root = Path(skills_root)

    def _auth_dep(request: Request) -> None:
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["registry"], dependencies=[Depends(_auth_dep)])

    @router.get("/api/registry/skills")
    def list_registry_skills(
        search: str | None = None,
        category: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        from octopus_runtime import RegistryClient

        try:
            assets = RegistryClient(base).list_skills()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"registry unreachable: {exc}") from exc
        if category:
            assets = [a for a in assets if (a.category or "") == category]
        if search:
            q = search.lower()
            assets = [
                a
                for a in assets
                if q in a.name.lower() or q in a.description.lower() or q in a.slug.lower()
            ]
        total = len(assets)
        paged = assets[offset : offset + limit]
        return {
            "skills": [a.model_dump() for a in paged],
            "total": total,
            "offset": offset,
            "limit": limit,
            "source": base,
        }

    @router.get("/api/registry/skills/{slug}")
    def registry_skill_detail(slug: str) -> dict[str, Any]:
        from octopus_runtime import RegistryClient

        asset_id = slug if "/" in slug else f"skill/{slug}"
        try:
            p = RegistryClient(base).fetch(asset_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(404, f"skill not found: {slug} ({exc})") from exc
        d = p.model_dump()
        body = d.pop("body", "")
        d["body_preview"] = body[:1200]
        d["body_chars"] = len(body)
        d["installed"] = (skills_root / p.slug / "SKILL.md").is_file()
        return d

    @router.post("/api/registry/skills/{slug}/install")
    def install_registry_skill(slug: str) -> dict[str, Any]:
        from octopus_runtime import sync_skills

        try:
            ok, skipped, errors = sync_skills([slug], skills_root, base_url=base)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"install failed: {exc}") from exc
        if errors:
            raise HTTPException(502, f"install failed: {errors[0][1]}")
        if skipped and not ok:
            raise HTTPException(400, f"skipped: {skipped[0][1]}")
        registered = _register_runtime(skill_registry, skills_root)
        return {"installed": slug, "path": ok[0][1] if ok else None, "registered_now": registered}

    # ─── 角色(role / twin-role,数字分身岗位模板)─── 只读浏览 + 安装成本地 agent ───

    @router.get("/api/registry/roles")
    def list_registry_roles(
        search: str | None = None,
        category: str | None = None,
        role_type: str | None = Query(default=None, alias="type"),
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        from octopus_runtime import RegistryClient

        types = (role_type,) if role_type in _ROLE_ASSET_TYPES else _ROLE_ASSET_TYPES
        try:
            client = RegistryClient(base)
            assets = [a for t in types for a in client.list_assets(type_=t)]
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"registry unreachable: {exc}") from exc
        if category:
            assets = [a for a in assets if (a.category or "") == category]
        if search:
            q = search.lower()
            assets = [
                a
                for a in assets
                if q in a.name.lower() or q in a.description.lower() or q in a.slug.lower()
            ]
        total = len(assets)
        paged = assets[offset : offset + limit]
        return {
            "roles": [a.model_dump() for a in paged],
            "total": total,
            "offset": offset,
            "limit": limit,
            "source": base,
        }

    @router.get("/api/registry/roles/{asset_id:path}")
    def registry_role_detail(asset_id: str) -> dict[str, Any]:
        from octopus_runtime import RegistryClient

        if "/" not in asset_id:
            asset_id = f"role/{asset_id}"
        try:
            p = RegistryClient(base).fetch(asset_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(404, f"role not found: {asset_id} ({exc})") from exc
        d = p.model_dump()
        body = d.pop("body", "")
        d["body_preview"] = body[:1200]
        d["body_chars"] = len(body)
        return d

    @router.post("/api/registry/roles/{asset_id:path}/install")
    def install_registry_role(asset_id: str) -> dict[str, Any]:
        from octopus_runtime import RegistryClient

        if "/" not in asset_id:
            asset_id = f"role/{asset_id}"
        if _asset_type(asset_id) not in _ROLE_ASSET_TYPES:
            raise HTTPException(400, f"not a role asset: {asset_id}")
        try:
            asset = RegistryClient(base).fetch(asset_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(404, f"role not found: {asset_id} ({exc})") from exc
        if not _is_installable_role_asset(asset):
            raise HTTPException(
                400,
                f"not an installable role asset: type={asset.type or '?'} kind={asset.kind or '?'}",
            )
        agent_id, agent_root = _scaffold_local_agent_from_registry_asset(asset)
        return {
            "installed": True,
            "agent_id": agent_id,
            "name": asset.name,
            "path": str(agent_root),
        }

    # ─── 插件(plugin)─── 只读浏览(kind=code,沿用 SAFE_TYPES 边界,不提供安装)───

    @router.get("/api/registry/plugins")
    def list_registry_plugins(
        search: str | None = None,
        category: str | None = None,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        from octopus_runtime import RegistryClient

        try:
            assets = RegistryClient(base).list_assets(type_="plugin")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(502, f"registry unreachable: {exc}") from exc
        if category:
            assets = [a for a in assets if (a.category or "") == category]
        if search:
            q = search.lower()
            assets = [
                a
                for a in assets
                if q in a.name.lower() or q in a.description.lower() or q in a.slug.lower()
            ]
        total = len(assets)
        paged = assets[offset : offset + limit]
        return {
            "plugins": [a.model_dump() for a in paged],
            "total": total,
            "offset": offset,
            "limit": limit,
            "source": base,
            "installable": False,
        }

    @router.get("/api/registry/plugins/{slug}")
    def registry_plugin_detail(slug: str) -> dict[str, Any]:
        from octopus_runtime import RegistryClient

        asset_id = slug if "/" in slug else f"plugin/{slug}"
        try:
            p = RegistryClient(base).fetch(asset_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(404, f"plugin not found: {slug} ({exc})") from exc
        d = p.model_dump()
        body = d.pop("body", "")
        d["body_preview"] = body[:1200]
        d["body_chars"] = len(body)
        d["installable"] = False
        return d

    return router
