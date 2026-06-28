"""Health and capability endpoints for the UI app."""
from __future__ import annotations

import contextlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request

from runtime import __version__
from runtime.platform.process.paths import project_root


def create_health_router(
    *,
    state: Any,
    agent_registry: Any = None,
    channel_manager: Any = None,
    group_registry: Any = None,
    server_host: str | None = None,
    server_port: int | None = None,
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
            "journal_source": (
                str(state.journal_path) if state.journal_path else "in-memory"
            ),
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
        )

    return router


def build_runtime_self_check(
    *,
    request: Request | None,
    state: Any,
    server_host: str | None = None,
    server_port: int | None = None,
) -> dict[str, Any]:
    root = project_root(Path(__file__))
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
        f"{request_scheme}://{request_host}:{observed_port}"
        if request_host
        else canonical_base_url
    )
    version_sources = {
        "runtime": __version__,
        "pyproject": pyproject_version,
        "frontend_package": frontend_version,
    }
    drift = {
        "runtime_matches_pyproject": __version__ == pyproject_version,
        "frontend_matches_runtime": (
            frontend_version in {"", __version__}
        ),
        "version_sources": version_sources,
    }
    aliases = _loopback_aliases(observed_host, observed_port, request_scheme)
    checks = [
        {
            "id": "runtime_version",
            "passed": drift["runtime_matches_pyproject"],
            "detail": f"runtime={__version__} pyproject={pyproject_version}",
        },
        {
            "id": "frontend_version",
            "passed": drift["frontend_matches_runtime"],
            "detail": f"frontend={frontend_version or 'missing'} runtime={__version__}",
        },
        {
            "id": "loopback_aliases",
            "passed": bool(aliases["same_loopback_family"]),
            "detail": (
                "localhost and 127.0.0.1 are treated as equivalent local aliases"
                if aliases["same_loopback_family"]
                else "request host is not a recognized loopback alias"
            ),
        },
        {
            "id": "backend_base_url",
            "passed": bool(canonical_base_url),
            "detail": canonical_base_url,
        },
    ]
    ready = all(bool(row["passed"]) for row in checks)
    return {
        "schema": "octopus.runtime_self_check.v1",
        "ready": ready,
        "status": "ok" if ready else "degraded",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "version": __version__,
        "version_drift": drift,
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
        "loopback_aliases": aliases,
        "paths": {
            "project_root": str(root),
            "journal_source": (
                str(state.journal_path) if getattr(state, "journal_path", None) else "in-memory"
            ),
        },
        "checks": checks,
        "next_actions": [
            str(row["detail"])
            for row in checks
            if not bool(row["passed"])
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


def _clean_host(value: str | None) -> str:
    host = str(value or "").strip().strip("[]").lower()
    return host or "127.0.0.1"


def _canonical_backend_host(host: str) -> str:
    cleaned = _clean_host(host)
    if cleaned in {"localhost", "::1", "0:0:0:0:0:0:0:1"}:
        return "127.0.0.1"
    if cleaned == "0.0.0.0":
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


def _coerce_port(value: Any) -> int | None:
    try:
        port = int(value)
    except (TypeError, ValueError):
        return None
    if 1 <= port <= 65535:
        return port
    return None
