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

from pathlib import Path
from typing import Any

try:
    from fastapi import APIRouter, Depends, HTTPException, Query, Request

    FASTAPI_AVAILABLE = True
except Exception:  # pragma: no cover - fastapi optional at import time
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    Depends = None  # type: ignore[assignment, misc]


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
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    import os

    base = (registry_base or os.environ.get("OCTOPUS_REGISTRY_URL") or "https://api.octoapk.com").rstrip("/")
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
            assets = [a for a in assets if q in a.name.lower() or q in a.description.lower() or q in a.slug.lower()]
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

    return router
