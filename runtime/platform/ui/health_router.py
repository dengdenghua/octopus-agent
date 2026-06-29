"""Health and capability endpoints for the UI app."""
from __future__ import annotations

import contextlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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
            frontend_host=frontend_host,
            frontend_port=frontend_port,
            frontend_proxy_target=frontend_proxy_target,
        )

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
        "frontend_matches_runtime": (
            frontend_version in {"", __version__}
        ),
        "version_sources": version_sources,
    }
    aliases = _loopback_aliases(observed_host, observed_port, request_scheme)
    process = _process_info()
    api_surface = _api_surface_info(request)
    webui = _webui_static_info(root)
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
            "detail": (
                f"proxy_target={frontend['proxy_target']} "
                f"backend={canonical_base_url}"
            ),
        },
        {
            "id": "api_surface",
            "severity": "error",
            "passed": bool(api_surface["required_routes_present"]),
            "detail": (
                "missing="
                + ",".join(api_surface["missing_required_routes"])
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
    ]
    ready = all(
        bool(row["passed"]) or row.get("severity") == "warn" for row in checks
    )
    warning_count = sum(
        1
        for row in checks
        if row.get("severity") == "warn" and not bool(row["passed"])
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
        "api_surface": api_surface,
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


def _api_surface_info(request: Request | None) -> dict[str, Any]:
    app = getattr(request, "app", None) if request is not None else None
    routes = list(getattr(app, "routes", []) or [])
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
        env_candidate
        and not (
            bool(env_candidate["exists"])
            and bool(env_candidate["has_index"])
        )
    )
    selected = next(
        (
            row
            for row in candidates
            if row["exists"] and row["has_index"]
        ),
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
        else
        f"dist={selected['path']} assets={assets_count}"
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
    port = (
        _coerce_port(frontend_port)
        or _origin_port(observed_origin)
        or frontend_env_port
        or 3000
    )
    configured_host = _clean_host(
        frontend_host
        or os.environ.get("VITE_CANONICAL_LOOPBACK_HOST")
        or "localhost"
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
        _same_local_base_url(proxy_target, backend_canonical_base_url)
        if proxy_target
        else False
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
    if cleaned in {"0.0.0.0", "::", ""}:
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
