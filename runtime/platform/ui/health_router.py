"""Health and capability endpoints for the UI app."""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Request

from runtime import __version__
from runtime.platform.process.paths import app_paths, project_root


def create_health_router(
    *,
    state: Any,
    agent_registry: Any = None,
    channel_manager: Any = None,
    group_registry: Any = None,
    server_host: str | None = None,
    server_port: int | None = None,
    frontend_host: str | None = None,
    frontend_port: int | None = None,
    frontend_proxy_target: str | None = None,
) -> APIRouter:
    """Create ``/api/health`` and ``/api/status`` endpoints."""
    router = APIRouter(tags=["health"])

    @router.get("/api/health")
    def api_health() -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": "ok",
            "ts": datetime.utcnow().isoformat() + "Z",
            "skills": len(state.registry),
            "journal_events": -1,
            "agents": 0,
            "channels": [],
            "groups": 0,
        }
        try:
            out["journal_events"] = len(state.journal.read_all())
        except (OSError, ImportError, AttributeError):
            out["journal_events"] = -1
        if agent_registry is not None:
            with contextlib.suppress(Exception):
                out["agents"] = len(agent_registry)
        if channel_manager is not None:
            with contextlib.suppress(Exception):
                out["channels"] = list(channel_manager.channel_ids())
        if group_registry is not None:
            with contextlib.suppress(Exception):
                out["groups"] = len(group_registry)
        return out

    @router.get("/api/storage/status")
    def api_storage_status() -> dict[str, Any]:
        """Liveness of the octopus-storage sibling (本地数据库 / File Agent), as the
        co-launch heartbeat last observed it. ``up=false`` means search_documents
        degrades; the heartbeat relaunches it when autostart owns its lifecycle."""
        from runtime.sensing.gateway.storage_supervisor import storage_status

        with contextlib.suppress(Exception):
            return storage_status()
        return {"up": False, "heartbeat": False, "error": "unavailable"}

    @router.get("/api/searxng/status")
    def api_searxng_status() -> dict[str, Any]:
        """Liveness of the optional one-click local SearXNG (private web-search
        backend). ``up=false`` just means web search uses the default ddg
        backend; deploy/stop go through the authenticated /api/searxng router."""
        from runtime.sensing.gateway.searxng_supervisor import searxng_status

        with contextlib.suppress(Exception):
            return searxng_status()
        return {"up": False, "heartbeat": False, "error": "unavailable"}

    @router.get("/api/status")
    def api_status() -> dict[str, Any]:
        from runtime.adapters.instrumentation import OTEL_AVAILABLE
        from runtime.adapters.mcp_client.client import STDIO_AVAILABLE

        def _has(mod: str) -> bool:
            try:
                __import__(mod)
                return True
            except ImportError:
                return False

        return {
            "version": __version__,
            "tagline": "biomimetic self-evolving agent OS",
            "skill_count": len(state.registry),
            "journal_source": (str(state.journal_path) if state.journal_path else "in-memory"),
            "capabilities": {
                "opentelemetry": OTEL_AVAILABLE,
                "mcp": STDIO_AVAILABLE,
                "httpx": _has("httpx"),
                "anthropic": _has("anthropic"),
                "yaml": _has("yaml"),
                "playwright": _has("playwright"),
                "fastapi": _has("fastapi"),
            },
        }

    @router.get("/api/runtime/self-check")
    def api_runtime_self_check(request: Request) -> dict[str, Any]:
        return build_runtime_self_check(
            request=request,
            state=state,
            server_host=server_host,
            server_port=server_port,
            frontend_host=frontend_host,
            frontend_port=frontend_port,
            frontend_proxy_target=frontend_proxy_target,
        )

    @router.post("/api/capabilities/enable")
    def api_capabilities_enable(payload: dict[str, Any]) -> dict[str, Any]:
        """Hot-load a skill group that was excluded at startup.

        Body: ``{"group": "web"}`` — registers the named group into the
        live ``SkillRegistry`` so subsequent tool calls succeed without a
        backend restart. Triggered by the UI's one-click "enable" prompt
        when the model tries to call a config-disabled tool (e.g.
        ``web_search`` under ``enable_web_skills=False``).
        """
        from fastapi import HTTPException

        from runtime.execution.all_skills import WEB_ONLY_GROUPS, register_group

        group = str(payload.get("group") or "").strip()
        if not group:
            raise HTTPException(status_code=400, detail="missing 'group' field")
        if group not in WEB_ONLY_GROUPS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"group '{group}' is not a toggleable web-only group; "
                    f"allowed: {sorted(WEB_ONLY_GROUPS)}"
                ),
            )
        newly = register_group(state.registry, group)
        return {
            "ok": True,
            "group": group,
            "newly_registered": newly,
            "skill_count": len(state.registry),
        }

    return router


def build_runtime_self_check(
    *,
    request: Request | None,
    state: Any,
    server_host: str | None = None,
    server_port: int | None = None,
    frontend_host: str | None = None,
    frontend_port: int | None = None,
    frontend_proxy_target: str | None = None,
) -> dict[str, Any]:
    root = project_root(Path(__file__))
    paths = app_paths()
    pyproject_version = _project_version(root)
    frontend_version = _frontend_version(root)
    request_url = str(getattr(request, "url", "") or "")
    request_host = ""
    request_port: int | None = None
    request_scheme = "http"
    if request is not None:
        request_scheme = str(getattr(getattr(request, "url", None), "scheme", "") or "http")
        request_host = str(getattr(getattr(request, "url", None), "hostname", "") or "")
        request_port = getattr(getattr(request, "url", None), "port", None)
    env_port = _coerce_port(
        os.environ.get("OCTOPUS_BACKEND_PORT")
        or os.environ.get("GATEWAY_PORT")
        or os.environ.get("PORT")
    )
    observed_port = request_port or _coerce_port(server_port) or env_port or 8000
    observed_host = _clean_host(server_host or request_host or "127.0.0.1")
    canonical_host = _canonical_backend_host(observed_host)
    canonical_base_url = f"{request_scheme}://{canonical_host}:{observed_port}"
    request_origin_base_url = (
        f"{request_scheme}://{request_host}:{observed_port}" if request_host else canonical_base_url
    )
    frontend = _frontend_runtime_info(
        request=request,
        request_scheme=request_scheme,
        backend_canonical_base_url=canonical_base_url,
        frontend_host=frontend_host,
        frontend_port=frontend_port,
        frontend_proxy_target=frontend_proxy_target,
    )
    version_sources = {
        "runtime": __version__,
        "pyproject": pyproject_version,
        "frontend_package": frontend_version,
    }
    drift = {
        "runtime_matches_pyproject": __version__ == pyproject_version,
        "frontend_matches_runtime": (frontend_version in {"", __version__}),
        "version_sources": version_sources,
    }
    aliases = _loopback_aliases(observed_host, observed_port, request_scheme)
    process = _process_info()
    api_surface = _api_surface_info(request)
    webui = _webui_static_info(root)
    model_compat = _model_compat_info()
    orchestration = _orchestration_surface_info(request)
    run_evidence = _run_evidence_surface_info(request)
    automation = _automation_surface_info(request)
    checks = [
        {
            "id": "runtime_version",
            "severity": "error",
            "passed": drift["runtime_matches_pyproject"],
            "detail": f"runtime={__version__} pyproject={pyproject_version}",
        },
        {
            "id": "frontend_version",
            "severity": "error",
            "passed": drift["frontend_matches_runtime"],
            "detail": f"frontend={frontend_version or 'missing'} runtime={__version__}",
        },
        {
            "id": "loopback_aliases",
            "severity": "error",
            "passed": bool(aliases["same_loopback_family"]),
            "detail": (
                "localhost and 127.0.0.1 are treated as equivalent local aliases"
                if aliases["same_loopback_family"]
                else "request host is not a recognized loopback alias"
            ),
        },
        {
            "id": "backend_base_url",
            "severity": "error",
            "passed": bool(canonical_base_url),
            "detail": canonical_base_url,
        },
        {
            "id": "frontend_origin",
            "severity": "error",
            "passed": bool(frontend["origin_normalized"]),
            "detail": (
                f"origin={frontend['observed_origin'] or 'missing'} "
                f"canonical={frontend['canonical_origin']}"
            ),
        },
        {
            "id": "vite_proxy_target",
            "severity": "error",
            "passed": bool(frontend["proxy_targets_backend"]),
            "detail": (f"proxy_target={frontend['proxy_target']} backend={canonical_base_url}"),
        },
        {
            "id": "api_surface",
            "severity": "error",
            "passed": bool(api_surface["required_routes_present"]),
            "detail": (
                "missing=" + ",".join(api_surface["missing_required_routes"])
                if api_surface["missing_required_routes"]
                else f"routes={api_surface['route_count']}"
            ),
        },
        {
            "id": "journal_path",
            "severity": "error",
            "passed": bool(_journal_source_usable(state)),
            "detail": _journal_source_detail(state),
        },
        {
            "id": "webui_dist",
            "severity": "warn",
            "passed": bool(
                not webui["env_dist_invalid"]
                and (webui["available"] or webui["dev_fallback_expected"])
            ),
            "detail": webui["detail"],
        },
        {
            "id": "openai_compat_profiles",
            "severity": "error",
            "passed": bool(model_compat["required_profiles_present"]),
            "detail": (
                f"profiles={model_compat['profile_count']} "
                f"missing={','.join(model_compat['missing_required_profile_ids']) or 'none'}"
            ),
        },
        {
            "id": "orchestration_surface",
            "severity": "error",
            "passed": bool(orchestration["ready"]),
            "detail": (
                f"routes={orchestration['route_count']} "
                f"missing={','.join(orchestration['missing_required_routes']) or 'none'} "
                f"models={len(orchestration['model_contracts'])}"
            ),
        },
        {
            "id": "run_evidence_surface",
            "severity": "error",
            "passed": bool(run_evidence["ready"]),
            "detail": (
                f"routes={run_evidence['route_count']} "
                f"missing={','.join(run_evidence['missing_required_routes']) or 'none'} "
                f"contracts={len(run_evidence['method_contracts'])}"
            ),
        },
        {
            "id": "automation_surface",
            "severity": "error",
            "passed": bool(automation["ready"]),
            "detail": (
                f"routes={automation['route_count']} "
                f"missing={','.join(automation['missing_required_routes']) or 'none'} "
                f"contracts={len(automation['method_contracts'])}"
            ),
        },
    ]
    ready = all(bool(row["passed"]) or row.get("severity") == "warn" for row in checks)
    warning_count = sum(
        1 for row in checks if row.get("severity") == "warn" and not bool(row["passed"])
    )
    return {
        "schema": "octopus.runtime_self_check.v1",
        "ready": ready,
        "status": "ok" if ready and warning_count == 0 else "degraded",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "version": __version__,
        "version_drift": drift,
        "process": process,
        "backend": {
            "canonical_base_url": canonical_base_url,
            "request_origin_base_url": request_origin_base_url,
            "request_url": request_url,
            "host": observed_host,
            "canonical_host": canonical_host,
            "port": observed_port,
            "env_port": env_port,
            "server_host": server_host or "",
            "server_port": server_port,
        },
        "frontend": frontend,
        "webui": webui,
        "model_compat": model_compat,
        "orchestration": orchestration,
        "run_evidence": run_evidence,
        "automation": automation,
        "api_surface": api_surface,
        "loopback_aliases": aliases,
        "paths": {
            "project_root": str(root),
            "runtime_root": str(paths.root),
            "data_dir": str(paths.data_dir),
            "octopus_home_env": os.environ.get("OCTOPUS_HOME") or "",
            "octopus_data_dir_env": os.environ.get("OCTOPUS_DATA_DIR") or "",
            "journal_source": (
                str(state.journal_path) if getattr(state, "journal_path", None) else "in-memory"
            ),
        },
        "checks": checks,
        "next_actions": [
            str(row["detail"])
            for row in checks
            if not bool(row["passed"]) and row.get("severity") != "warn"
        ],
        "warnings": [
            str(row["detail"])
            for row in checks
            if not bool(row["passed"]) and row.get("severity") == "warn"
        ],
    }


def _project_version(root: Path) -> str:
    try:
        import tomllib

        payload = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        return str(payload.get("project", {}).get("version") or "")
    except (OSError, ValueError, ImportError, TypeError):
        return ""


def _frontend_version(root: Path) -> str:
    try:
        payload = json.loads((root / "frontend" / "package.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError):
        return ""
    return str(payload.get("version") or "")


def _process_info() -> dict[str, Any]:
    argv = [str(part) for part in sys.argv[:8]]
    if len(sys.argv) > len(argv):
        argv.append("...")
    return {
        "schema": "octopus.runtime_process.v1",
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "cwd": os.getcwd(),
        "argv": argv,
    }


def _iter_app_routes(app: Any) -> list[Any]:
    """Every route reachable from the app, nested includes included.

    starlette >=1.3 / fastapi >=0.139 wrap included routers in entries
    that expose children via ``original_router`` (or ``app`` for mounts)
    instead of flattening them — a plain ``app.routes`` scan then sees a
    couple dozen wrappers and every surface check reports its routes
    missing.
    """
    stack = list(getattr(app, "routes", []) or [])
    seen: set[int] = set()
    collected: list[Any] = []
    while stack:
        route = stack.pop()
        if id(route) in seen:
            continue
        seen.add(id(route))
        collected.append(route)
        stack.extend(getattr(route, "routes", []) or [])
        for container_attr in ("original_router", "app"):
            container = getattr(route, container_attr, None)
            if container is not None:
                stack.extend(getattr(container, "routes", []) or [])
    return collected


def _api_surface_info(request: Request | None) -> dict[str, Any]:
    app = getattr(request, "app", None) if request is not None else None
    routes = _iter_app_routes(app)
    route_paths = sorted(
        {
            str(getattr(route, "path", "") or "")
            for route in routes
            if str(getattr(route, "path", "") or "")
        }
    )
    required = (
        "/api/health",
        "/api/status",
        "/api/runtime/self-check",
    )
    missing = [path for path in required if path not in route_paths]
    return {
        "schema": "octopus.api_surface.v1",
        "route_count": len(route_paths),
        "required_routes": list(required),
        "missing_required_routes": missing,
        "required_routes_present": not missing,
    }


def _webui_static_info(root: Path) -> dict[str, Any]:
    env_path = os.environ.get("OCTOPUS_WEBUI_DIST") or ""
    candidates = _webui_dist_candidates(root, env_path)
    env_candidate = candidates[0] if env_path and candidates else None
    env_dist_invalid = bool(
        env_candidate and not (bool(env_candidate["exists"]) and bool(env_candidate["has_index"]))
    )
    selected = next(
        (row for row in candidates if row["exists"] and row["has_index"]),
        None,
    )
    assets_count = 0
    if selected is not None:
        assets_dir = Path(str(selected["path"])) / "assets"
        if assets_dir.is_dir():
            with contextlib.suppress(OSError):
                assets_count = sum(1 for item in assets_dir.iterdir() if item.is_file())
    dev_fallback_expected = not bool(env_path) and selected is None
    detail = (
        f"configured OCTOPUS_WEBUI_DIST is invalid: {env_path}; "
        f"fallback={selected['path'] if selected is not None else 'none'}"
        if env_dist_invalid
        else f"dist={selected['path']} assets={assets_count}"
        if selected is not None
        else "frontend dist not found; dev server fallback expected"
        if dev_fallback_expected
        else f"configured OCTOPUS_WEBUI_DIST is invalid: {env_path}"
    )
    return {
        "schema": "octopus.webui_static.v1",
        "available": selected is not None,
        "selected_dist": str(selected["path"]) if selected is not None else "",
        "env_dist": env_path,
        "env_dist_invalid": env_dist_invalid,
        "assets_count": assets_count,
        "dev_fallback_expected": dev_fallback_expected,
        "candidates": candidates,
        "detail": detail,
    }


def _webui_dist_candidates(root: Path, env_path: str) -> list[dict[str, Any]]:
    raw_candidates: list[tuple[str, Path]] = []
    if env_path:
        raw_candidates.append(("env", Path(env_path)))
    raw_candidates.extend(
        [
            ("frontend_dist", root / "frontend" / "dist"),
            ("ui_package_dist", Path(__file__).resolve().parent / "dist"),
        ]
    )
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, path in raw_candidates:
        text = str(path)
        if text in seen:
            continue
        seen.add(text)
        out.append(
            {
                "source": source,
                "path": text,
                "exists": path.is_dir(),
                "has_index": (path / "index.html").is_file(),
                "has_assets": (path / "assets").is_dir(),
            }
        )
    return out


def _model_compat_info() -> dict[str, Any]:
    try:
        from runtime.sensing.model_router.openai_compat_providers import (
            REQUIRED_DOMESTIC_PROFILE_IDS,
            audit_openai_compat_profile_catalog,
            describe_openai_compat_profile,
            known_openai_compat_profiles,
        )
        from runtime.sensing.model_router.openai_compat_smoke_matrix import (
            openai_compat_smoke_readiness,
        )

        required_profile_ids = list(REQUIRED_DOMESTIC_PROFILE_IDS)
        profiles = list(known_openai_compat_profiles())
        audit = audit_openai_compat_profile_catalog(REQUIRED_DOMESTIC_PROFILE_IDS)
        summaries = [describe_openai_compat_profile(profile) for profile in profiles]
        profile_ids = [str(summary.get("id") or "") for summary in summaries]
        by_id = {str(summary.get("id") or ""): summary for summary in summaries}
        missing = list(audit["missing_required_profile_ids"])
        return {
            "schema": "octopus.openai_compat_profile_self_check.v1",
            "available": True,
            "profile_count": len(profiles),
            "profile_ids": profile_ids,
            "required_profile_ids": required_profile_ids,
            "missing_required_profile_ids": missing,
            "required_profiles_present": bool(audit["catalog_ready"]),
            "domestic_profile_count": len(required_profile_ids) - len(missing),
            "smoke_provider_ids": audit["smoke_provider_ids"],
            "missing_smoke_provider_ids": audit["missing_smoke_provider_ids"],
            "orphan_smoke_provider_ids": audit["orphan_smoke_provider_ids"],
            "resolver_mismatches": audit["resolver_mismatches"],
            "model_alias_mismatches": audit["model_alias_mismatches"],
            "request_contract_mismatches": audit["request_contract_mismatches"],
            "request_contract_count": len(audit["request_contract_probes"]),
            "request_contract_ready": not audit["request_contract_mismatches"],
            "request_contract_probes": audit["request_contract_probes"],
            "sample_probes": audit["sample_probes"],
            "live_smoke": openai_compat_smoke_readiness(),
            "domestic_profiles": [
                {
                    "id": profile_id,
                    "display_name": str(
                        by_id.get(profile_id, {}).get("display_name") or profile_id
                    ),
                    "compat_score": by_id.get(profile_id, {}).get("compat_score"),
                    "normalization_hints": by_id.get(profile_id, {}).get(
                        "normalization_hints",
                        [],
                    ),
                }
                for profile_id in required_profile_ids
                if profile_id in by_id
            ],
            "error": "",
        }
    except Exception as exc:  # noqa: BLE001
        from runtime.sensing.model_router.openai_compat_providers import (
            REQUIRED_DOMESTIC_PROFILE_IDS,
        )

        required_profile_ids = list(REQUIRED_DOMESTIC_PROFILE_IDS)
        return {
            "schema": "octopus.openai_compat_profile_self_check.v1",
            "available": False,
            "profile_count": 0,
            "profile_ids": [],
            "required_profile_ids": required_profile_ids,
            "missing_required_profile_ids": required_profile_ids,
            "required_profiles_present": False,
            "domestic_profile_count": 0,
            "smoke_provider_ids": [],
            "missing_smoke_provider_ids": required_profile_ids,
            "orphan_smoke_provider_ids": [],
            "resolver_mismatches": [],
            "model_alias_mismatches": [],
            "request_contract_mismatches": [],
            "request_contract_count": 0,
            "request_contract_ready": False,
            "request_contract_probes": [],
            "sample_probes": [],
            "domestic_profiles": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


def _orchestration_surface_info(request: Request | None) -> dict[str, Any]:
    required_routes = {
        "/api/agents/parallel/status": ["GET"],
        "/api/agents/parallel/batch/{batch_id}": ["GET"],
        "/api/agents/parallel/batch/{batch_id}/recovery-snapshot": ["GET"],
        "/api/agents/parallel/dispatch": ["POST"],
        "/api/agents/parallel/split": ["POST"],
        "/api/agents/parallel/cancel/{task_id}": ["POST"],
        "/api/agents/parallel/cancel-all": ["POST"],
        "/api/agents/parallel/stream/{batch_id}": ["GET"],
    }
    route_surface = _route_surface_info(request, required_routes)
    model_contracts = _orchestration_model_contracts()
    method_contracts = _orchestrator_method_contracts()
    missing_model_fields = [
        {
            "model": row["model"],
            "missing_fields": row["missing_fields"],
        }
        for row in model_contracts
        if row["missing_fields"]
    ]
    missing_methods = [
        {
            "method": row["method"],
            "reason": row["reason"],
        }
        for row in method_contracts
        if not row["present"]
    ]
    replay_contract = next(
        (row for row in method_contracts if row["method"] == "subscribe.after_sequence"),
        {"present": False},
    )
    ready = (
        route_surface["required_routes_present"]
        and not missing_model_fields
        and not missing_methods
    )
    return {
        "schema": "octopus.orchestration_surface_self_check.v1",
        "ready": ready,
        "route_count": route_surface["route_count"],
        "required_routes": list(required_routes),
        "missing_required_routes": route_surface["missing_required_routes"],
        "route_methods": route_surface["route_methods"],
        "missing_route_methods": route_surface["missing_route_methods"],
        "model_contracts": model_contracts,
        "missing_model_fields": missing_model_fields,
        "method_contracts": method_contracts,
        "missing_methods": missing_methods,
        "capabilities": {
            "parallel_dispatch": route_surface["has_required_route"][
                "/api/agents/parallel/dispatch"
            ],
            "split_planning": route_surface["has_required_route"]["/api/agents/parallel/split"],
            "recovery_snapshot": route_surface["has_required_route"][
                "/api/agents/parallel/batch/{batch_id}/recovery-snapshot"
            ],
            "sse_event_replay": bool(replay_contract.get("present")),
            "completion_receipt": _contract_has_field(
                model_contracts,
                "BatchResult",
                "completion_receipt",
            ),
            "file_write_observability": _contract_has_field(
                model_contracts,
                "BatchResult",
                "file_write_observability",
            ),
            "work_contracts": _contract_has_field(
                model_contracts,
                "BatchPlan",
                "contracts",
            ),
            "owner_scoping": all(
                row["present"]
                for row in method_contracts
                if row["method"]
                in {
                    "get_batch_owner",
                    "get_task_owner",
                    "cancel_all_for_owner",
                }
            ),
        },
        "error": "",
    }


def _run_evidence_surface_info(request: Request | None) -> dict[str, Any]:
    required_routes = {
        "/api/agent-trace/stats": ["GET"],
        "/api/agent-trace/events": ["GET"],
        "/api/agent-trace/task-runs": ["GET"],
        "/api/agent-trace/task-runs/{task_id}": ["GET"],
        "/api/agent-trace/task-runs/{task_id}/review": ["GET"],
        "/api/agent-trace/task-runs/{task_id}/replay-case": ["GET"],
        "/api/agent-trace/task-runs/{task_id}/replay-evaluation": ["GET"],
        "/api/agent-trace/task-runs/{task_id}/process-timeline": ["GET"],
        "/api/agent-trace/task-runs/{task_id}/review/commit": ["POST"],
        "/api/agent-trace/task-runs/{task_id}/review/queue": ["POST"],
        "/api/agent-trace/replay-cases": ["GET"],
        "/api/agent-trace/replay-evaluations": ["GET"],
        "/api/agent-trace/replay-gate": ["GET"],
        "/api/agent-trace/experience-ledger": ["GET"],
        "/api/agent-trace/experience-ledger/weekly-summary": ["GET"],
        "/api/agent-trace/experience-ledger/quality-summary": ["GET"],
        "/api/agent-trace/review-queue": ["GET"],
        "/api/agent-trace/review-queue/summary": ["GET"],
        "/api/agent-trace/review-queue/{item_id}/decision": ["POST"],
        "/api/agent-trace/review-queue/promotions/plan": ["POST"],
        "/api/agent-trace/review-queue/promotions/apply": ["POST"],
        "/api/agent-trace/review-queue/promotions/audit": ["GET"],
        "/api/agent-trace/review-queue/promotions/audit/summary": ["GET"],
        "/api/agent-trace/checkpoints": ["GET"],
        "/api/agent-trace/checkpoints/latest": ["GET"],
        "/api/agent-trace/checkpoints/{checkpoint_id}/resume-proposal": ["GET"],
        "/api/agent-trace/resume-proposals": ["GET"],
        "/api/agent-trace/resume-requests": ["GET"],
        "/api/loops/{run_id}/review": ["GET"],
        "/api/loops/{run_id}/resume-proposal": ["GET"],
        "/api/loops/{run_id}/replay-case": ["GET"],
        "/api/loops/{run_id}/replay-evaluation": ["GET"],
    }
    route_surface = _route_surface_info(request, required_routes)
    method_contracts = _run_evidence_method_contracts()
    missing_methods = [
        {
            "method": row["method"],
            "reason": row["reason"],
        }
        for row in method_contracts
        if not row["present"]
    ]
    ready = route_surface["required_routes_present"] and not missing_methods
    return {
        "schema": "octopus.run_evidence_surface_self_check.v1",
        "ready": ready,
        "route_count": route_surface["route_count"],
        "required_routes": list(required_routes),
        "missing_required_routes": route_surface["missing_required_routes"],
        "route_methods": route_surface["route_methods"],
        "missing_route_methods": route_surface["missing_route_methods"],
        "method_contracts": method_contracts,
        "missing_methods": missing_methods,
        "capabilities": {
            "trace_stats": route_surface["has_required_route"]["/api/agent-trace/stats"],
            "task_run_review": route_surface["has_required_route"][
                "/api/agent-trace/task-runs/{task_id}/review"
            ],
            "task_run_replay_case": route_surface["has_required_route"][
                "/api/agent-trace/task-runs/{task_id}/replay-case"
            ],
            "task_run_replay_evaluation": route_surface["has_required_route"][
                "/api/agent-trace/task-runs/{task_id}/replay-evaluation"
            ],
            "replay_gate": route_surface["has_required_route"]["/api/agent-trace/replay-gate"],
            "process_timeline": route_surface["has_required_route"][
                "/api/agent-trace/task-runs/{task_id}/process-timeline"
            ],
            "experience_ledger": route_surface["has_required_route"][
                "/api/agent-trace/experience-ledger"
            ],
            "review_queue": route_surface["has_required_route"]["/api/agent-trace/review-queue"],
            "promotion_gate": route_surface["has_required_route"][
                "/api/agent-trace/review-queue/promotions/apply"
            ],
            "checkpoint_resume": (
                route_surface["has_required_route"]["/api/agent-trace/checkpoints"]
                and route_surface["has_required_route"]["/api/agent-trace/resume-proposals"]
            ),
            "loop_review": route_surface["has_required_route"]["/api/loops/{run_id}/review"],
            "loop_replay": (
                route_surface["has_required_route"]["/api/loops/{run_id}/replay-case"]
                and route_surface["has_required_route"]["/api/loops/{run_id}/replay-evaluation"]
            ),
            "loop_resume": route_surface["has_required_route"][
                "/api/loops/{run_id}/resume-proposal"
            ],
        },
        "error": "",
    }


def _run_evidence_method_contracts() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.extend(
        _class_method_contracts(
            "AgentTraceStore",
            "runtime.memory.diagnostics.trace_store",
            "AgentTraceStore",
            [
                "stats",
                "events",
                "task_runs",
                "task_run",
                "task_run_review",
                "task_run_replay_case",
                "evaluate_task_run_replay_case",
                "task_run_replay_cases",
                "evaluate_task_run_replay_cases",
                "replay_gate",
                "replay_gate_for_task_ids",
                "approvals",
                "checkpoints",
                "latest_checkpoint",
                "resume_proposal",
                "resume_proposals",
                "resume_requests",
            ],
        )
    )
    checks.extend(
        _class_method_contracts(
            "ExperienceLedger",
            "runtime.memory.learning.experience_ledger",
            "ExperienceLedger",
            [
                "add_from_task_run_review",
                "records",
                "records_for_task",
                "weekly_summary",
                "quality_summary",
            ],
        )
    )
    checks.extend(
        _class_method_contracts(
            "ReviewQueue",
            "runtime.memory.learning.review_queue",
            "ReviewQueue",
            [
                "add_from_task_run_review",
                "items",
                "summary",
                "decide",
            ],
        )
    )
    checks.extend(
        _class_method_contracts(
            "PromotionApplier",
            "runtime.memory.learning.promotion_applier",
            "PromotionApplier",
            [
                "plan",
                "apply",
                "audit",
                "audit_summary",
            ],
        )
    )
    checks.extend(
        _module_function_contracts(
            "process_timeline",
            "runtime.memory.runtime_state.process_timeline",
            ["build_task_run_process_timeline"],
        )
    )
    checks.extend(
        _module_function_contracts(
            "loop_replay",
            "runtime.execution.loops.replay",
            [
                "build_loop_run_replay",
                "build_loop_run_replay_case",
                "evaluate_loop_run_replay_case",
            ],
        )
    )
    checks.extend(
        _module_function_contracts(
            "loop_recovery",
            "runtime.execution.loops.recovery",
            ["build_loop_run_resume_proposal"],
        )
    )
    return checks


def _automation_surface_info(request: Request | None) -> dict[str, Any]:
    required_routes = {
        "/api/browser/system-info": ["GET"],
        "/api/browser/session/status": ["GET"],
        "/api/browser/session/health": ["GET"],
        "/api/browser/session/ensure": ["POST"],
        "/api/browser/session/viewport": ["POST"],
        "/api/browser/session/reset": ["POST"],
        "/api/browser/navigate": ["POST"],
        "/api/browser/action": ["POST"],
        "/api/browser/screenshot/base64": ["GET"],
        "/api/browser/page-info": ["GET"],
        "/api/browser/action-log": ["GET"],
        "/api/browser/session/replay-case": ["GET"],
        "/api/browser/session/replay-case/queue": ["POST"],
        "/api/browser/relay/status": ["GET"],
        "/api/browser/relay/command": ["POST"],
        "/api/browser/relay/result": ["POST"],
        "/api/browser-artifacts/{filename}": ["GET"],
        "/api/computer/status": ["GET"],
        "/api/computer/activity": ["GET"],
        "/api/computer/activity/replay-case": ["GET"],
        "/api/computer/activity/replay-case/queue": ["POST"],
        "/api/computer/screenshot": ["POST"],
        "/api/computer/actions/preview": ["POST"],
        "/api/computer/actions/plan": ["POST"],
        "/api/computer/actions/ground": ["POST"],
        "/api/computer/actions/vision": ["POST"],
        "/api/computer/actions/execute": ["POST"],
        "/api/computer/lease/release": ["POST"],
        "/api/computer/uia/status": ["GET"],
        "/api/computer/uia/tree": ["GET"],
        "/api/computer/uia/find": ["GET"],
    }
    route_surface = _route_surface_info(request, required_routes)
    method_contracts = _automation_method_contracts()
    missing_methods = [
        {
            "method": row["method"],
            "reason": row["reason"],
        }
        for row in method_contracts
        if not row["present"]
    ]
    ready = route_surface["required_routes_present"] and not missing_methods
    return {
        "schema": "octopus.automation_surface_self_check.v1",
        "ready": ready,
        "route_count": route_surface["route_count"],
        "required_routes": list(required_routes),
        "missing_required_routes": route_surface["missing_required_routes"],
        "route_methods": route_surface["route_methods"],
        "missing_route_methods": route_surface["missing_route_methods"],
        "method_contracts": method_contracts,
        "missing_methods": missing_methods,
        "capabilities": {
            "browser_session_lifecycle": (
                route_surface["has_required_route"]["/api/browser/session/status"]
                and route_surface["has_required_route"]["/api/browser/session/ensure"]
                and route_surface["has_required_route"]["/api/browser/session/reset"]
            ),
            "browser_health": route_surface["has_required_route"]["/api/browser/session/health"],
            "browser_navigation": (
                route_surface["has_required_route"]["/api/browser/navigate"]
                and route_surface["has_required_route"]["/api/browser/action"]
            ),
            "browser_screenshot_evidence": (
                route_surface["has_required_route"]["/api/browser/screenshot/base64"]
                and route_surface["has_required_route"]["/api/browser-artifacts/{filename}"]
            ),
            "browser_replay_queue": (
                route_surface["has_required_route"]["/api/browser/session/replay-case"]
                and route_surface["has_required_route"]["/api/browser/session/replay-case/queue"]
            ),
            "browser_relay": (
                route_surface["has_required_route"]["/api/browser/relay/status"]
                and route_surface["has_required_route"]["/api/browser/relay/command"]
                and route_surface["has_required_route"]["/api/browser/relay/result"]
            ),
            "computer_preview_execute": (
                route_surface["has_required_route"]["/api/computer/actions/preview"]
                and route_surface["has_required_route"]["/api/computer/actions/execute"]
            ),
            "computer_grounding": (
                route_surface["has_required_route"]["/api/computer/actions/plan"]
                and route_surface["has_required_route"]["/api/computer/actions/ground"]
                and route_surface["has_required_route"]["/api/computer/actions/vision"]
            ),
            "computer_activity_replay": (
                route_surface["has_required_route"]["/api/computer/activity/replay-case"]
                and route_surface["has_required_route"]["/api/computer/activity/replay-case/queue"]
            ),
            "computer_uia": (
                route_surface["has_required_route"]["/api/computer/uia/status"]
                and route_surface["has_required_route"]["/api/computer/uia/tree"]
                and route_surface["has_required_route"]["/api/computer/uia/find"]
            ),
            "computer_lease": route_surface["has_required_route"]["/api/computer/lease/release"],
            "pixel_replay_gate": _contract_present(
                method_contracts,
                "browser_pixel.browser_pixel_replay_gate_case",
            ),
        },
        "error": "",
    }


def _automation_method_contracts() -> list[dict[str, Any]]:
    checks: list[dict[str, Any]] = []
    checks.extend(
        _class_method_contracts(
            "BrowserSessionCenter",
            "runtime.platform.runtime_policy.browser_sessions",
            "BrowserSessionCenter",
            [
                "ensure",
                "get",
                "record_action",
                "health_report",
                "snapshot",
                "list_snapshots",
            ],
        )
    )
    checks.extend(
        _module_function_contracts(
            "browser_replay",
            "runtime.safety.replay.browser_desktop_replay",
            [
                "browser_session_replay_identity",
                "computer_activity_replay_identity",
            ],
        )
    )
    checks.extend(
        _module_function_contracts(
            "browser_pixel",
            "runtime.safety.replay.browser_pixel_assertions",
            [
                "assert_screenshot_pixels",
                "compare_screenshot_pixels",
                "browser_pixel_replay_gate_case",
            ],
        )
    )
    checks.extend(
        _module_function_contracts(
            "computer_skills",
            "runtime.execution.suckers.computer_skills",
            [
                "_screen_capture",
                "_screen_info",
                "_mouse_click",
                "_mouse_move",
                "_keyboard_type",
                "_keyboard_press",
                "register_computer_skills",
            ],
        )
    )
    checks.extend(
        _module_function_contracts(
            "computer_uia",
            "runtime.execution.suckers.computer_uia_skills",
            [
                "_check_uia",
                "uia_replay_assertion_for_action",
                "register_computer_uia_skills",
            ],
        )
    )
    return checks


def _contract_present(
    contracts: list[dict[str, Any]],
    method: str,
) -> bool:
    for row in contracts:
        if row.get("method") == method:
            return bool(row.get("present"))
    return False


def _class_method_contracts(
    label: str,
    module_name: str,
    class_name: str,
    method_names: list[str],
) -> list[dict[str, Any]]:
    try:
        module = __import__(module_name, fromlist=[class_name])
        cls = getattr(module, class_name)
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "method": f"{label}.{method}",
                "present": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
            for method in method_names
        ]
    return [
        {
            "method": f"{label}.{method}",
            "present": callable(getattr(cls, method, None)),
            "reason": "" if callable(getattr(cls, method, None)) else "missing",
        }
        for method in method_names
    ]


def _module_function_contracts(
    label: str,
    module_name: str,
    function_names: list[str],
) -> list[dict[str, Any]]:
    try:
        module = __import__(module_name, fromlist=function_names)
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "method": f"{label}.{function}",
                "present": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
            for function in function_names
        ]
    return [
        {
            "method": f"{label}.{function}",
            "present": callable(getattr(module, function, None)),
            "reason": "" if callable(getattr(module, function, None)) else "missing",
        }
        for function in function_names
    ]


def _route_surface_info(
    request: Request | None,
    required_routes: dict[str, list[str]],
) -> dict[str, Any]:
    app = getattr(request, "app", None) if request is not None else None
    routes = _iter_app_routes(app)
    route_methods: dict[str, list[str]] = {}
    for route in routes:
        path = str(getattr(route, "path", "") or "")
        if not path:
            continue
        methods = sorted(
            str(method)
            for method in (getattr(route, "methods", None) or [])
            if str(method) not in {"HEAD", "OPTIONS"}
        )
        route_methods[path] = methods
    missing_routes = [path for path in required_routes if path not in route_methods]
    missing_route_methods = [
        {
            "path": path,
            "missing_methods": [
                method for method in methods if method not in route_methods.get(path, [])
            ],
        }
        for path, methods in required_routes.items()
        if path in route_methods
        and any(method not in route_methods.get(path, []) for method in methods)
    ]
    return {
        "route_count": len(route_methods),
        "route_methods": {
            path: route_methods.get(path, []) for path in required_routes if path in route_methods
        },
        "missing_required_routes": missing_routes,
        "missing_route_methods": missing_route_methods,
        "required_routes_present": not missing_routes and not missing_route_methods,
        "has_required_route": {
            path: path in route_methods
            and not any(row["path"] == path for row in missing_route_methods)
            for path in required_routes
        },
    }


def _orchestration_model_contracts() -> list[dict[str, Any]]:
    try:
        from runtime.execution.parallel_agents.models import (
            BatchPlan,
            BatchRecoverySnapshot,
            BatchResult,
            BatchStreamEvent,
            OrchestratorStatus,
            WorkContract,
        )
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "model": "parallel_agents.models",
                "required_fields": [],
                "present_fields": [],
                "missing_fields": ["import"],
                "error": f"{type(exc).__name__}: {exc}",
            }
        ]

    contracts = [
        (
            "BatchResult",
            BatchResult,
            [
                "plan",
                "event_log",
                "completion_receipt",
                "file_write_observability",
            ],
        ),
        (
            "BatchRecoverySnapshot",
            BatchRecoverySnapshot,
            [
                "schema",
                "dag",
                "plan",
                "event_sequence",
                "recovery_hints",
                "completion_receipt",
                "file_write_observability",
                "safety",
            ],
        ),
        (
            "BatchStreamEvent",
            BatchStreamEvent,
            [
                "type",
                "batch_id",
                "sequence",
                "created_at",
                "payload",
                "artifact_paths",
            ],
        ),
        (
            "BatchPlan",
            BatchPlan,
            [
                "phases",
                "contracts",
                "validation_issues",
                "validation_warnings",
            ],
        ),
        (
            "WorkContract",
            WorkContract,
            [
                "owned_scope",
                "forbidden_scope",
                "write_paths",
                "success_criteria",
            ],
        ),
        (
            "OrchestratorStatus",
            OrchestratorStatus,
            [
                "active_count",
                "pending_count",
                "completed_count",
                "failed_count",
                "cancelled_count",
                "max_concurrency",
                "batches",
            ],
        ),
    ]
    return [
        _model_contract_summary(name, model, required_fields)
        for name, model, required_fields in contracts
    ]


def _model_contract_summary(
    name: str,
    model: Any,
    required_fields: list[str],
) -> dict[str, Any]:
    raw_fields = getattr(model, "model_fields", None)
    if raw_fields is None:
        raw_fields = getattr(model, "__fields__", {})
    present_fields = set(str(key) for key in raw_fields)
    aliases = {
        str(getattr(field, "alias", "") or "")
        for field in raw_fields.values()
        if getattr(field, "alias", None)
    }
    all_fields = present_fields | aliases
    missing = [field for field in required_fields if field not in all_fields]
    return {
        "model": name,
        "required_fields": required_fields,
        "present_fields": sorted(all_fields),
        "missing_fields": missing,
        "error": "",
    }


def _orchestrator_method_contracts() -> list[dict[str, Any]]:
    try:
        from runtime.execution.parallel_agents import ParallelAgentOrchestrator
    except Exception as exc:  # noqa: BLE001
        return [
            {
                "method": "ParallelAgentOrchestrator",
                "present": False,
                "reason": f"{type(exc).__name__}: {exc}",
            }
        ]

    required = [
        "dispatch",
        "split",
        "status",
        "get_batch",
        "recovery_snapshot",
        "subscribe",
        "cancel_task",
        "cancel_all",
        "get_batch_owner",
        "get_task_owner",
        "cancel_all_for_owner",
    ]
    out = [
        {
            "method": method,
            "present": callable(getattr(ParallelAgentOrchestrator, method, None)),
            "reason": (
                "" if callable(getattr(ParallelAgentOrchestrator, method, None)) else "missing"
            ),
        }
        for method in required
    ]
    subscribe = getattr(ParallelAgentOrchestrator, "subscribe", None)
    has_after_sequence = False
    if callable(subscribe):
        with contextlib.suppress(TypeError, ValueError):
            has_after_sequence = "after_sequence" in inspect.signature(subscribe).parameters
    out.append(
        {
            "method": "subscribe.after_sequence",
            "present": has_after_sequence,
            "reason": "" if has_after_sequence else "missing parameter",
        }
    )
    return out


def _contract_has_field(
    contracts: list[dict[str, Any]],
    model: str,
    field: str,
) -> bool:
    for row in contracts:
        if row.get("model") != model:
            continue
        return field in row.get("present_fields", []) and field not in row.get(
            "missing_fields",
            [],
        )
    return False


def _journal_source_usable(state: Any) -> bool:
    journal_path = getattr(state, "journal_path", None)
    if journal_path is None:
        return True
    try:
        parent = Path(journal_path).expanduser().resolve().parent
    except (OSError, TypeError, ValueError):
        return False
    return parent.exists() and os.access(parent, os.W_OK)


def _journal_source_detail(state: Any) -> str:
    journal_path = getattr(state, "journal_path", None)
    if journal_path is None:
        return "in-memory"
    try:
        parent = Path(journal_path).expanduser().resolve().parent
    except (OSError, TypeError, ValueError):
        return f"invalid journal_path={journal_path}"
    writable = parent.exists() and os.access(parent, os.W_OK)
    return f"journal_path={journal_path} parent={parent} writable={writable}"


def _clean_host(value: str | None) -> str:
    host = str(value or "").strip().strip("[]").lower()
    return host or "127.0.0.1"


def _canonical_backend_host(host: str) -> str:
    cleaned = _clean_host(host)
    if cleaned in {"localhost", "::1", "0:0:0:0:0:0:0:1"}:
        return "127.0.0.1"
    if cleaned == "0.0.0.0":  # nosec B104 — string comparison, not a bind
        return "127.0.0.1"
    return cleaned


def _loopback_aliases(host: str, port: int, scheme: str) -> dict[str, Any]:
    canonical = _canonical_backend_host(host)
    is_loopback = canonical.startswith("127.") or canonical == "::1"
    urls = [
        f"{scheme}://127.0.0.1:{port}",
        f"{scheme}://localhost:{port}",
    ]
    return {
        "schema": "octopus.loopback_aliases.v1",
        "requested_host": host,
        "canonical_host": canonical,
        "same_loopback_family": is_loopback,
        "aliases": urls if is_loopback else [f"{scheme}://{canonical}:{port}"],
    }


def _frontend_runtime_info(
    *,
    request: Request | None,
    request_scheme: str,
    backend_canonical_base_url: str,
    frontend_host: str | None = None,
    frontend_port: int | None = None,
    frontend_proxy_target: str | None = None,
) -> dict[str, Any]:
    observed_origin = _request_frontend_origin(request)
    frontend_env_port = _coerce_port(os.environ.get("FRONTEND_PORT"))
    port = _coerce_port(frontend_port) or _origin_port(observed_origin) or frontend_env_port or 3000
    configured_host = _clean_host(
        frontend_host or os.environ.get("VITE_CANONICAL_LOOPBACK_HOST") or "localhost"
    )
    canonical_host = _frontend_canonical_host(configured_host)
    canonical_origin = f"{request_scheme}://{canonical_host}:{port}"
    # Backend APIs can treat localhost/127 as equivalent, but the browser cannot:
    # frontend assets, localStorage, sessionStorage and auth state are origin-
    # partitioned. A 127.0.0.1 frontend origin must be redirected to the canonical
    # localhost origin instead of being accepted as "close enough".
    origin_normalized = not observed_origin or observed_origin == canonical_origin
    proxy_target = _normalize_base_url(
        frontend_proxy_target
        or os.environ.get("OCTOPUS_INTERNAL_GATEWAY_BASE_URL")
        or f"http://127.0.0.1:{os.environ.get('GATEWAY_PORT') or '8000'}"
    )
    proxy_targets_backend = (
        _same_local_base_url(proxy_target, backend_canonical_base_url) if proxy_target else False
    )
    aliases = _loopback_aliases(canonical_host, port, request_scheme)["aliases"]
    return {
        "schema": "octopus.frontend_runtime.v1",
        "observed_origin": observed_origin,
        "canonical_origin": canonical_origin,
        "canonical_host": canonical_host,
        "port": port,
        "env_port": frontend_env_port,
        "dev_proxy_mode": True,
        "proxy_target": proxy_target,
        "proxy_targets_backend": proxy_targets_backend,
        "origin_normalized": origin_normalized,
        "loopback_aliases": aliases,
    }


def _request_frontend_origin(request: Request | None) -> str:
    if request is None:
        return ""
    headers = getattr(request, "headers", {}) or {}
    for key in ("origin", "referer"):
        value = str(headers.get(key) or "").strip()
        if not value:
            continue
        try:
            parsed = urlparse(value)
        except (AttributeError, ValueError):
            continue
        if not parsed.scheme or not parsed.netloc:
            continue
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    return ""


def _frontend_canonical_host(host: str) -> str:
    cleaned = _clean_host(host)
    if cleaned in {"0.0.0.0", "::", ""}:  # nosec B104 — string comparison, not a bind
        return "localhost"
    if cleaned in {"::1", "0:0:0:0:0:0:0:1"}:
        return "localhost"
    return cleaned


def _origin_host(value: str) -> str:
    if not value:
        return ""
    try:
        parsed = urlparse(value)
    except (AttributeError, ValueError):
        return ""
    return _clean_host(parsed.hostname or "")


def _origin_port(value: str) -> int | None:
    if not value:
        return None
    try:
        parsed = urlparse(value)
        return _coerce_port(parsed.port)
    except (AttributeError, ValueError):
        return None


def _normalize_base_url(value: str | None) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    try:
        parsed = urlparse(text)
    except (AttributeError, ValueError):
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return ""
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{_clean_host(parsed.hostname)}{port}"


def _is_loopback_host(host: str) -> bool:
    cleaned = _clean_host(host)
    return (
        cleaned == "localhost"
        or cleaned == "::1"
        or cleaned == "0:0:0:0:0:0:0:1"
        or cleaned.startswith("127.")
    )


def _same_local_base_url(left: str, right: str) -> bool:
    left_norm = _normalize_base_url(left)
    right_norm = _normalize_base_url(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    try:
        left_parsed = urlparse(left_norm)
        right_parsed = urlparse(right_norm)
    except (AttributeError, ValueError):
        return False
    return (
        left_parsed.scheme == right_parsed.scheme
        and left_parsed.port == right_parsed.port
        and _is_loopback_host(left_parsed.hostname or "")
        and _is_loopback_host(right_parsed.hostname or "")
    )


def _coerce_port(value: Any) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None
