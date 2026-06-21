"""
MCP router · declare / enable / disable MCP servers at runtime.

Extracted from the monolithic ``runtime/platform/ui/app.py`` in the
app.py-split campaign. Owns the Model-Context-Protocol
adapter surface: known presets (one-click ``@page-agent/mcp``
install), runtime spawn bookkeeping, and the JSON endpoints the
frontend Settings → MCP page speaks to.

Endpoints
---------

    GET  /api/mcp/config        · currently-declared servers
    PUT  /api/mcp/config        · enable/disable servers + spawn/kill

State
-----

The factory returns a wrapper carrying two mutable dicts:

    ``config_state``  — declared state (name → enabled + description
                        + command/args/env). Seeds at startup from
                        ``stack.config.mcp_servers``, mutates on PUT.
    ``runtime_state`` — live-registered spawn bookkeeping (name →
                        registered skill names + effective command).
                        Populated when a PUT flips ``enabled=true``;
                        drained when flipped off.

Exposing these lets other app wiring (health endpoint, UI app
startup log) inspect what's registered without re-doing the work.
"""
from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from typing import Any

try:
    from fastapi import APIRouter, HTTPException, Request

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover
    FASTAPI_AVAILABLE = False
    APIRouter = None  # type: ignore[assignment, misc]
    HTTPException = None  # type: ignore[assignment, misc]
    Request = None  # type: ignore[assignment, misc]


# ═══════════════════════════════════════════════════════════
# Known-server presets · one-click install for well-known MCPs
# ═══════════════════════════════════════════════════════════
#
# Each entry gives the UI enough to spawn without the user typing
# command / args. ``bridge: "molili"`` triggers the auto-fill LLM
# env flow (see ``_resolve_molili_bridge_env``).


MCP_PRESETS: dict[str, dict[str, Any]] = {
    "page-agent": {
        # Alibaba Page Agent — real npm package is @page-agent/mcp
        # (verified https://github.com/alibaba/page-agent/tree/main/packages/mcp).
        # One-click flow: ``bridge: "molili"`` auto-fills LLM_BASE_URL
        # to our local /api/molili/openai/v1 proxy and forwards the
        # caller's bearer token as LLM_API_KEY. Explicit env in the
        # PUT body still wins if the user wants a custom LLM.
        "command": "npx",
        "args": ["-y", "@page-agent/mcp"],
        "env": {},
        "bridge": "molili",
        # Trailing "_" separator — the bridge does raw concat.
        "name_prefix": "page_",
        "description": (
            "Page Agent (Alibaba) — browser GUI agent. MCP tools: "
            "execute_task / get_status / stop_task. Needs Chrome "
            "extension + Molili-linked account (or explicit LLM env)."
        ),
    },
}


# ═══════════════════════════════════════════════════════════
# Bundle returned by the factory
# ═══════════════════════════════════════════════════════════


@dataclass
class McpRouter:
    """Package the router with the state dicts callers need to
    introspect. Keeps the external ``app.include_router`` pattern
    while still giving app.py's health endpoint a way to count
    live MCP servers."""
    router: Any
    config_state: dict[str, Any] = field(
        default_factory=lambda: {"mcp_servers": {}},
    )
    runtime_state: dict[str, dict[str, Any]] = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════


def create_mcp_router(
    *,
    registry: Any,
    initial_mcp_servers: Any = None,
) -> McpRouter:
    """Build the MCP router.

    Parameters
    ----------
    registry :
        ``SkillRegistry``. MCP tools get grafted into this at
        enable-time; at disable-time we pop them back out. The
        unregister path reaches into the registry's private
        ``_by_name`` dict because ``SkillRegistry`` doesn't expose
        an ``unregister()`` method — safe, the attribute's been
        stable, but flagged with ``# noqa: SLF001``.
    initial_mcp_servers :
        Optional iterable of ``(name, MCPServerConfig-ish)``
        objects coming from ``stack.config.mcp_servers``. Each
        entry seeds the config_state as ``enabled=True`` with a
        synthesized description — mirrors the pre-split behavior
        so a user's ``config.yaml`` declarations still appear in
        the UI immediately.
    """
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("fastapi not installed")

    router = APIRouter(tags=["mcp"])
    mcp_config_state: dict[str, Any] = {"mcp_servers": {}}
    mcp_runtime: dict[str, dict[str, Any]] = {}

    # Seed declared state from config.yaml's mcp_servers list.
    if initial_mcp_servers:
        servers = {}
        for entry in initial_mcp_servers:
            entry_name = getattr(entry, "name", None)
            if not entry_name:
                continue
            cmd = getattr(entry, "command", "")
            args = getattr(entry, "args", None) or []
            servers[entry_name] = {
                "enabled": True,
                "description": f"{cmd} {' '.join(args)}".strip(),
            }
        mcp_config_state = {"mcp_servers": servers}

    # ─── Helpers ────────────────────────────────────────────

    def _resolve_molili_bridge_env(
        request: Any,
    ) -> dict[str, str]:
        """Auto-fill LLM_* env pointing the MCP server at our local
        Molili proxy. Lets a user enable Page Agent in one click:
        we re-use their bearer token and the UI's base URL as the
        inner LLM target — no manual env wiring."""
        if request is None:
            return {}
        auth = request.headers.get("authorization") or ""
        # Strip "Bearer " prefix; the MCP server will re-attach it.
        token = auth[7:] if auth.lower().startswith("bearer ") else auth
        # Point at our local Molili proxy — same host:port the
        # request came in on (respects uvicorn port + reverse
        # proxies that set host headers).
        base = str(request.base_url).rstrip("/") + "/api/molili/openai/v1"
        env: dict[str, str] = {"LLM_BASE_URL": base}
        if token and token != "__guest__":
            env["LLM_API_KEY"] = token
        # GLM-4.7 is a solid default from Molili's _KNOWN_MODELS.
        env.setdefault("LLM_MODEL_NAME", "glm-4.7")
        return env

    def _register_runtime_mcp(
        name: str,
        entry: dict[str, Any],
        request: Any = None,
    ) -> dict[str, Any]:
        """Spawn an MCP server + graft its tools into the registry.

        Returns a status dict the caller stuffs into the PUT
        response's ``_status`` field so the UI can render an error
        toast on failure (subprocess spawn / missing command /
        import failure) rather than silently doing nothing.
        """
        if registry is None:
            return {"ok": False, "error": "registry not ready"}
        try:
            from runtime.adapters.mcp_client import (
                HttpMCPClient,
                MCPServerConfig,
                PersistentStdioMCPClient,
                register_mcp_tools_as_skills,
            )
            from runtime.adapters.mcp_client.client import (
                HTTP_AVAILABLE,
                STDIO_AVAILABLE,
            )
        except ImportError as e:
            return {"ok": False, "error": f"mcp_client import failed: {e}"}

        preset = MCP_PRESETS.get(name, {})
        transport = str(entry.get("transport") or preset.get("transport") or "stdio")
        url = str(entry.get("url") or preset.get("url") or "")
        is_remote = transport in ("http", "sse") or bool(url)
        name_prefix = (
            entry.get("name_prefix") or preset.get("name_prefix") or name
        )

        if is_remote:
            # Remote (streamable-http / SSE) server.
            if not HTTP_AVAILABLE:
                return {"ok": False, "error": "mcp SDK not installed (pip install mcp)"}
            if not url:
                return {"ok": False, "error": f"no url configured for remote MCP {name!r}"}
            config = MCPServerConfig(
                name=name,
                transport=transport if transport in ("http", "sse") else "http",
                url=url,
                headers=dict(entry.get("headers") or {}),
            )
            summary: dict[str, Any] = {"transport": transport, "url": url}
        else:
            # Local stdio (subprocess) server.
            if not STDIO_AVAILABLE:
                return {"ok": False, "error": "mcp SDK not installed (pip install mcp)"}
            command = entry.get("command") or preset.get("command")
            args = entry.get("args") or preset.get("args", [])
            # env layers (later wins): preset → molili bridge → user env.
            bridge_env: dict[str, str] = {}
            if entry.get("bridge") == "molili" or preset.get("bridge") == "molili":
                bridge_env = _resolve_molili_bridge_env(request)
            env = {
                **preset.get("env", {}),
                **bridge_env,
                **(entry.get("env") or {}),
            }
            if not command:
                return {
                    "ok": False,
                    "error": (
                        f"no command configured for {name!r} "
                        "(not a known preset)"
                    ),
                }
            config = MCPServerConfig(
                name=name, command=command, args=list(args), env=dict(env),
            )
            summary = {"command": command, "args": list(args), "env": dict(env)}

        before = set(registry.all_names())
        client = None
        try:
            client = (
                HttpMCPClient(config)
                if is_remote
                else PersistentStdioMCPClient(config)
            )
            # Production path · enforce user trust approval. The
            # frontend Settings → MCP page surfaces an "Approve" CTA
            # that calls ``/api/mcp/trust``; until then the bridge
            # refuses to register tools from the server.
            register_mcp_tools_as_skills(
                registry, client, name_prefix=name_prefix,
                require_trust=True, server_name=name,
            )
        except Exception as e:  # noqa: BLE001
            # Spawn / connection can fail in dozens of ways (missing
            # binary, npm network error, bad url, handshake timeout) ·
            # bundle them into the UI-visible error string rather than
            # fail the whole PUT.
            if client is not None:
                with contextlib.suppress(Exception):
                    client.close()
            return {"ok": False, "error": f"register failed: {e}"}
        after = set(registry.all_names())
        added = sorted(after - before)
        mcp_runtime[name] = {
            "skills": added,
            "name_prefix": name_prefix,
            "client": client,
            **summary,
        }
        return {"ok": True, "registered": added}

    def _unregister_runtime_mcp(name: str) -> dict[str, Any]:
        record = mcp_runtime.pop(name, None)
        if not record or registry is None:
            return {"ok": True, "removed": []}
        removed: list[str] = []
        for skill_name in record.get("skills") or []:
            # SkillRegistry doesn't expose unregister(); pop the
            # internal dict directly. The attribute is part of the
            # public-for-internal-callers API · stable enough.
            if skill_name in registry._by_name:  # noqa: SLF001
                del registry._by_name[skill_name]
                removed.append(skill_name)
        client = record.get("client")
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
        return {"ok": True, "removed": removed}

    # ─── Endpoints ──────────────────────────────────────────

    @router.get("/api/mcp/config")
    def api_mcp_config() -> dict[str, Any]:
        return mcp_config_state

    @router.put("/api/mcp/config")
    def api_mcp_config_update(
        body: dict[str, Any], request: Request,
    ) -> dict[str, Any]:
        servers = body.get("mcp_servers")
        if not isinstance(servers, dict):
            raise HTTPException(400, "mcp_servers must be an object")
        normalized: dict[str, Any] = {}
        status: dict[str, Any] = {}
        for name, payload in servers.items():
            if not isinstance(name, str) or not isinstance(payload, dict):
                continue
            enabled = bool(payload.get("enabled", False))
            entry: dict[str, Any] = {
                "enabled": enabled,
                "description": str(
                    payload.get("description")
                    or MCP_PRESETS.get(name, {}).get("description")
                    or ""
                ),
            }
            # Pass-through known fields (stdio: command/args/env;
            # remote: transport/url/headers).
            for key in (
                "command", "args", "env", "name_prefix", "bridge",
                "transport", "url", "headers",
            ):
                if key in payload:
                    entry[key] = payload[key]
            normalized[name] = entry

            was_enabled = name in mcp_runtime
            if enabled and not was_enabled:
                status[name] = _register_runtime_mcp(name, entry, request)
                # Bubble errors to the entry so the UI can render.
                if not status[name].get("ok"):
                    entry["enabled"] = False
                    entry["error"] = status[name].get("error")
            elif not enabled and was_enabled:
                status[name] = _unregister_runtime_mcp(name)
        mcp_config_state["mcp_servers"] = normalized
        return {**mcp_config_state, "_status": status}

    # ─── Trust management ─────────────────────────────────

    @router.get("/api/mcp/trust")
    def api_mcp_trust_list() -> dict[str, Any]:
        """List all MCP trust entries · UI renders approval chips."""
        from runtime.adapters.mcp_client.trust import get_trust_store
        store = get_trust_store()
        return {
            "entries": [
                {
                    "server_name": e.server_name,
                    "approved": e.approved,
                    "added_ts": e.added_ts,
                    "tool_digest": e.tool_digest,
                    "note": e.note,
                }
                for e in store.list_all()
            ],
        }

    @router.post("/api/mcp/trust")
    def api_mcp_trust_approve(body: dict[str, Any]) -> dict[str, Any]:
        name = str(body.get("server_name") or "").strip()
        if not name:
            raise HTTPException(400, "server_name required")
        tool_names = body.get("tool_names") or []
        if not isinstance(tool_names, list):
            raise HTTPException(400, "tool_names must be a list")
        note = str(body.get("note") or "")
        from runtime.adapters.mcp_client.trust import get_trust_store
        entry = get_trust_store().approve(
            name, [str(t) for t in tool_names], note=note,
        )
        return {
            "ok": True,
            "entry": {
                "server_name": entry.server_name,
                "approved": entry.approved,
                "added_ts": entry.added_ts,
                "tool_digest": entry.tool_digest,
                "note": entry.note,
            },
        }

    @router.delete("/api/mcp/trust/{server_name}")
    def api_mcp_trust_revoke(server_name: str) -> dict[str, Any]:
        """Revoke approval · tools drop out immediately.

        The trust store flag is the source of truth for *future*
        registrations, but stale runtime state has to come down too:
        without an unregister, the in-memory ``mcp_runtime`` entry
        keeps its skill closures alive and ``ToolExecutor`` will keep
        dispatching into a now-untrusted MCP subprocess until the next
        process restart. We synchronously stop the runtime entry so
        that revocation actually takes effect.
        """
        from runtime.adapters.mcp_client.trust import get_trust_store
        revoked = get_trust_store().revoke(server_name)
        runtime_status: dict[str, Any] | None = None
        if server_name in mcp_runtime:
            try:
                runtime_status = _unregister_runtime_mcp(server_name)
            except Exception as exc:  # noqa: BLE001
                runtime_status = {"error": str(exc)}
        return {
            "ok": revoked,
            "server_name": server_name,
            "runtime": runtime_status,
        }

    return McpRouter(
        router=router,
        config_state=mcp_config_state,
        runtime_state=mcp_runtime,
    )


__all__ = ["MCP_PRESETS", "McpRouter", "create_mcp_router"]
