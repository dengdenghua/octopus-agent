"""System-level endpoints (regeneration status + capabilities) for the agents router.

Pure structural split of ``_agents_endpoints.py`` — no logic changes.
``_register_system`` attaches the regen-pipeline status and capabilities
get/put endpoints to the injected router.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

try:
    from fastapi import HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]

from ._agents_endpoints_shared import _AuthActions
from .agents_models import CapabilitiesWire

if TYPE_CHECKING:
    from ._agents_endpoints import _AgentsCtx


def _register_system(router: Any, ctx: _AgentsCtx, auth: _AuthActions) -> None:
    _auth = auth.auth
    _require_admin = auth.require_admin

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
        request: Request,
        body: CapabilitiesWire,
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
                500,
                f"failed to write capabilities file: {exc}",
            ) from exc
        return {
            "ok": True,
            "capabilities": caps.to_dict(),
            "restart_required": True,
            "message": ("设置已保存 · 重启后端后生效(skill registry 只在启动时构造)"),
        }
