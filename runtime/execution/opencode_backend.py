"""Managed, loopback-only OpenCode engine with Echo-owned host tools.

The official process owns inference and its tools. Echo owns the authenticated
principal, conversation, cancellation and permission ceiling. No provider
headers are emulated and no model API is exposed to other engines.
"""

from __future__ import annotations

import asyncio
import atexit
import contextlib
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import threading
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from runtime.execution.host_mcp_connection import HostMCPConnection
from runtime.platform.capabilities.tenant_context import use_capability_scope
from runtime.platform.connectors.credential_store import CredentialStore
from runtime.platform.models.custom_model_selection import resolve_custom_model_selection
from runtime.platform.process.paths import app_paths
from runtime.safety.auth.scope import TenantScope


class OpenCodeError(RuntimeError):
    """Safe-to-display engine failure, without credentials or raw responses."""


_WARM_IDLE_SECONDS = 120.0


@dataclass
class _WarmServer:
    signature: str
    root: Path
    process: asyncio.subprocess.Process
    client: httpx.AsyncClient
    loop: asyncio.AbstractEventLoop
    in_use: bool = True
    idle_handle: asyncio.TimerHandle | None = None


_warm_servers: dict[str, _WarmServer] = {}
_MAX_WARM_SERVERS = 3
_warm_lock: asyncio.Lock | None = None
_warm_lock_loop: asyncio.AbstractEventLoop | None = None


def _terminate_warm_server_at_exit() -> None:
    for entry in tuple(_warm_servers.values()):
        if entry.process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                entry.process.terminate()


atexit.register(_terminate_warm_server_at_exit)


def executable() -> str | None:
    configured = os.environ.get("OCTOPUS_OPENCODE_BIN")
    if configured:
        path = Path(configured).expanduser()
        return str(path.resolve()) if path.is_file() else None
    # The local launcher records its pinned installation here. Discover only
    # this source tree's managed tool directory, never an arbitrary cwd's
    # runtime-paths file or a path outside the managed installation.
    state = Path(__file__).resolve().parents[2] / ".codex-run"
    try:
        manifest = json.loads((state / "runtime-paths.json").read_text(encoding="utf-8"))
        recorded = manifest.get("opencode") if isinstance(manifest, dict) else None
        if isinstance(recorded, str) and recorded.strip():
            candidate = Path(recorded).resolve()
            if (
                candidate.is_relative_to((state / "tools" / "opencode").resolve())
                and candidate.is_file()
                and (
                    candidate.suffix.lower() == ".exe"
                    if os.name == "nt"
                    else os.access(candidate, os.X_OK)
                )
            ):
                return str(candidate)
    except (OSError, ValueError):
        pass
    return shutil.which("opencode")


def zen_catalog() -> dict[str, Any]:
    try:
        value = json.loads(app_paths().custom_models_path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def resolve_zen_model(selection: str | None, catalog: dict[str, Any]) -> str:
    selected_go = resolve_custom_model_selection(catalog, selection or "")
    if (selection or "").startswith("official/") or (
        selected_go and selected_go.entry_id not in {"opencode-zen", "opencode-go"}
    ):
        return "echo-shared/" + str(selection)
    if (selected_go and selected_go.entry_id == "opencode-go") or (selection or "").startswith("opencode-go/"):
        entry = catalog.get("opencode-go", {})
        model = selected_go.model if selected_go else selection.removeprefix("opencode-go/")
        if entry.get("managed_by_plugin") not in {"opencode-go", "opencode-zen"} or model not in entry.get("models", []):
            raise OpenCodeError("请先连接 OpenCode Go，并选择套餐模型。")
        if selected_go and selected_go.context_profile != "default":
            raise OpenCodeError("OpenCode Go 请选择默认上下文模型。")
        return f"opencode-go/{model}"
    if selection == "auto":
        selection = None
    entry = catalog.get("opencode-zen")
    if entry is None:
        # The official process offers this public model without a Zen account.
        # It still verifies live availability and zero pricing before inference.
        entry = {"managed_by_plugin": "opencode-zen", "models": ["big-pickle"]}
        catalog = {**catalog, "opencode-zen": entry}
    if not isinstance(entry, dict) or entry.get("managed_by_plugin") != "opencode-zen":
        raise OpenCodeError("请先安装并连接 OpenCode Zen 模型插件。")
    selected = resolve_custom_model_selection(catalog, selection or "")
    if selected:
        if selected.entry_id != "opencode-zen" or selected.context_profile != "default":
            raise OpenCodeError("OpenCode 引擎请选择 Zen 插件中的默认上下文模型。")
        model = selected.model
    else:
        model = (selection or "big-pickle").removeprefix("opencode/")
    if model not in entry.get("models", []):
        raise OpenCodeError("OpenCode 引擎请选择 Zen 模型，例如 big-pickle。")
    return model


def zen_key(scope: TenantScope | None) -> str | None:
    with use_capability_scope(scope):
        key = CredentialStore().get_secret("opencode-zen", "api_key")
    return key or None


def native_model(model: str) -> tuple[str, str]:
    if model.startswith("echo-shared/"):
        return "echo-shared", model.removeprefix("echo-shared/")
    return ("opencode-go", model.removeprefix("opencode-go/")) if model.startswith("opencode-go/") else ("opencode", model)


def model_selection_id(model: str) -> str:
    from runtime.platform.models.custom_model_selection import custom_model_selection_id
    provider, upstream = native_model(model)
    if provider == "echo-shared":
        return upstream
    return custom_model_selection_id("opencode-go" if provider == "opencode-go" else "opencode-zen", upstream)


def model_key(scope: TenantScope | None, model: str) -> str | None:
    if native_model(model)[0] == "echo-shared":
        return None
    if native_model(model)[0] != "opencode-go":
        return zen_key(scope)
    with use_capability_scope(scope):
        key = CredentialStore().get_secret("opencode-zen", "api_key") or CredentialStore().get_secret("opencode-go", "api_key")
    if not key:
        raise OpenCodeError("请先连接 OpenCode Go 套餐。")
    return key


def inspect_readiness(scope: TenantScope | None) -> dict[str, Any]:
    if os.environ.get("OCTOPUS_DEPLOYMENT_MODE", "local").strip().lower() != "local":
        return {"available": False, "reason": "OpenCode 引擎目前仅支持本地运行。"}
    if not executable():
        return {"available": False, "reason": "请安装 OpenCode 并配置 OCTOPUS_OPENCODE_BIN。"}
    try:
        resolve_zen_model(None, zen_catalog())
        zen_key(scope)
    except OpenCodeError as exc:
        return {"available": False, "reason": str(exc)}
    except (OSError, ValueError, RuntimeError):
        return {"available": False, "reason": "暂时无法读取 Zen 连接配置。"}
    return {
        "available": True,
        "reason": None,
        "readiness_kind": "configuration_only",
        "capabilities": ["chat", "web_research", "host_tools", "skills", "plugin_actions"],
    }


def state_directory(scope: TenantScope | None, thread_id: str) -> Path:
    # Never use browser-supplied paths or ids as filesystem components.
    identity = [scope.tenant_id, scope.actor_id] if scope else [None, None]
    digest = hashlib.sha256(json.dumps([*identity, thread_id]).encode()).hexdigest()
    return app_paths().data_dir / "opencode" / digest


def child_environment(
    root: Path,
    key: str | None,
    password: str,
    model: str,
    web: bool,
    *,
    host_mcp: HostMCPConnection | None = None,
    shared_provider: dict[str, Any] | None = None,
) -> dict[str, str]:
    # Do not inherit other provider credentials, plugins, or OpenCode settings.
    allowed = {
        "PATH",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATHEXT",
        "TEMP",
        "TMP",
        "HOME",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "NODE_EXTRA_CA_CERTS",
    }
    env = {k: v for k, v in os.environ.items() if k.upper() in allowed}
    for name in ("CONFIG", "DATA", "CACHE", "STATE"):
        directory = root / name.lower()
        directory.mkdir(parents=True, exist_ok=True)
        env[f"XDG_{name}_HOME"] = str(directory)
    permission = {"*": "deny"}
    if web:
        permission.update(webfetch="allow", websearch="allow")
    if host_mcp:
        permission["echo_*"] = "allow"
    provider, upstream = native_model(model)
    config = {
        "model": f"{provider}/{upstream}",
        "small_model": f"{provider}/{upstream}",
        "share": "disabled",
        "autoupdate": False,
        "snapshot": False,
        "permission": permission,
        "default_agent": "echo",
        "agent": {"echo": {"mode": "primary", "permission": permission, "steps": 16}},
    }
    if key:
        config["provider"] = {provider: {"options": {"apiKey": "{env:OPENCODE_API_KEY}"}}}
        env["OPENCODE_API_KEY"] = key
    if provider == "echo-shared":
        if shared_provider is None or not key:
            raise OpenCodeError("Shared model proxy is unavailable")
        config["provider"][provider] = {
            "name": "Echo models", "npm": "@ai-sdk/openai",
            "models": {upstream: {"name": upstream}},
            "options": {"baseURL": shared_provider["base_url"], "apiKey": "{env:OPENCODE_API_KEY}"},
        }
    if provider == "opencode-go":
        if not key:
            raise OpenCodeError("请先连接 OpenCode Go 套餐。")
        config["provider"][provider].update({
            "name": "OpenCode Go",
            "npm": (
                "@ai-sdk/openai" if upstream.startswith(("gpt-", "grok-", "muse-spark-"))
                else "@ai-sdk/anthropic" if upstream.startswith(("minimax-", "qwen"))
                else "@ai-sdk/openai-compatible"
            ),
            "models": {upstream: {"name": upstream}},
        })
        config["provider"][provider]["options"].update({
            "baseURL": "https://opencode.ai/zen/go/v1",
            "headers": {"User-Agent": "Echo/1.0", "x-opencode-session": hashlib.sha256(str(root).encode()).hexdigest()},
        })
    if host_mcp:
        config["mcp"] = {
            "echo": {
                "type": "remote",
                "url": host_mcp.url,
                "headers": {"Authorization": "Bearer {env:ECHO_HOST_MCP_TOKEN}"},
                "oauth": False,
                "enabled": True,
                # Native approval can wait up to 120s before tool execution.
                "timeout": 180_000,
            }
        }
        env["ECHO_HOST_MCP_TOKEN"] = host_mcp.token
    env.update(
        OPENCODE_SERVER_PASSWORD=password,
        OPENCODE_SERVER_USERNAME="opencode",
        OPENCODE_DISABLE_AUTOUPDATE="true",
        OPENCODE_DISABLE_DEFAULT_PLUGINS="true",
        OPENCODE_DISABLE_CLAUDE_CODE="true",
        OPENCODE_DISABLE_EXTERNAL_SKILLS="true",
        OPENCODE_DISABLE_PROJECT_CONFIG="true",
        OPENCODE_DISABLE_LSP_DOWNLOAD="true",
        OPENCODE_CONFIG_CONTENT=json.dumps(config),
    )
    return env


def _server_signature(command: str, root: Path, key: str | None, model: str) -> str:
    key_digest = hashlib.sha256(key.encode()).hexdigest() if key else "anonymous"
    return hashlib.sha256(
        json.dumps([str(Path(command).resolve()), str(root.resolve()), key_digest, model]).encode()
    ).hexdigest()


def _loop_lock() -> asyncio.Lock:
    global _warm_lock, _warm_lock_loop
    loop = asyncio.get_running_loop()
    if _warm_lock is None or _warm_lock_loop is not loop:
        _warm_lock = asyncio.Lock()
        _warm_lock_loop = loop
    return _warm_lock


async def _stop_server(process: asyncio.subprocess.Process, client: httpx.AsyncClient) -> None:
    await client.aclose()
    if process.returncode is None:
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()


async def _start_server(
    command: str,
    root: Path,
    key: str | None,
    model: str,
    web: bool,
    *,
    host_mcp: HostMCPConnection | None = None,
    shared_provider: dict[str, Any] | None = None,
) -> tuple[asyncio.subprocess.Process, httpx.AsyncClient]:
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    password = secrets.token_urlsafe(32)
    process = await asyncio.create_subprocess_exec(
        command,
        "serve",
        "--hostname",
        "127.0.0.1",
        "--port",
        str(port),
        cwd=workspace,
        env=child_environment(root, key, password, model, web, host_mcp=host_mcp, shared_provider=shared_provider),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    client = httpx.AsyncClient(
        base_url=f"http://127.0.0.1:{port}",
        auth=("opencode", password),
        trust_env=False,
        timeout=10,
    )
    try:
        for _ in range(100):
            if process.returncode is not None:
                raise OpenCodeError("OpenCode 启动失败，请检查安装版本和引擎配置。")
            try:
                response = await client.get("/global/health", timeout=1)
                if response.status_code == 200 and response.json().get("healthy"):
                    break
            except (httpx.TransportError, ValueError):
                pass
            await asyncio.sleep(0.1)
        else:
            raise OpenCodeError("OpenCode 启动超时，请检查本地引擎。")
        await validate_catalog_model(client, model, free_only=not key)
        return process, client
    except BaseException:
        await _stop_server(process, client)
        raise


@asynccontextmanager
async def _ephemeral_server(
    command: str,
    root: Path,
    key: str | None,
    model: str,
    web: bool,
    *,
    host_mcp: HostMCPConnection | None = None,
    shared_provider: dict[str, Any] | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    process, client = await _start_server(command, root, key, model, web, host_mcp=host_mcp, shared_provider=shared_provider)
    try:
        yield client
    finally:
        await _stop_server(process, client)


async def _expire_warm_server(entry: _WarmServer) -> None:
    async with _loop_lock():
        if _warm_servers.get(entry.signature) is not entry or entry.in_use:
            return
        del _warm_servers[entry.signature]
    await _stop_server(entry.process, entry.client)


def _schedule_warm_expiry(entry: _WarmServer) -> None:
    if entry.idle_handle is not None:
        entry.idle_handle.cancel()
    entry.idle_handle = entry.loop.call_later(
        _WARM_IDLE_SECONDS,
        lambda: entry.loop.create_task(_expire_warm_server(entry)),
    )


@asynccontextmanager
async def _warm_text_server(
    command: str, root: Path, key: str | None, model: str
) -> AsyncIterator[httpx.AsyncClient]:
    signature = _server_signature(command, root, key, model)
    loop = asyncio.get_running_loop()
    lock = _loop_lock()
    entry = None
    fresh = False
    async with lock:
        for stale in tuple(_warm_servers.values()):
            if stale.loop is not loop or stale.process.returncode is not None:
                _warm_servers.pop(stale.signature, None)
                if stale.idle_handle is not None:
                    stale.idle_handle.cancel()
                if stale.loop is loop:
                    await _stop_server(stale.process, stale.client)
                elif stale.process.returncode is None:
                    with contextlib.suppress(ProcessLookupError):
                        stale.process.terminate()
        current = _warm_servers.get(signature)
        if current is not None and not current.in_use:
            if current.idle_handle is not None:
                current.idle_handle.cancel()
                current.idle_handle = None
            current.in_use = True
            entry = current
        elif current is None:
            # Remove idle entries for the same state root after model/key changes.
            for old in tuple(_warm_servers.values()):
                if old.root == root.resolve() and not old.in_use:
                    _warm_servers.pop(old.signature, None)
                    if old.idle_handle is not None:
                        old.idle_handle.cancel()
                    await _stop_server(old.process, old.client)
            if len(_warm_servers) >= _MAX_WARM_SERVERS:
                victim = next((e for e in _warm_servers.values() if not e.in_use), None)
                if victim is not None:
                    _warm_servers.pop(victim.signature, None)
                    if victim.idle_handle is not None:
                        victim.idle_handle.cancel()
                    await _stop_server(victim.process, victim.client)
            if len(_warm_servers) < _MAX_WARM_SERVERS:
                process, client = await _start_server(command, root, key, model, False)
                entry = _WarmServer(signature, root.resolve(), process, client, loop)
                _warm_servers[signature] = entry
                fresh = True
    if entry is None:
        async with _ephemeral_server(command, root, key, model, False) as client:
            yield client
        return
    reusable = False
    try:
        if not fresh:
            response = await entry.client.get('/global/health', timeout=1)
            if response.status_code != 200 or not response.json().get('healthy'):
                raise OpenCodeError('OpenCode 本地引擎连接中断，请重试。')
            await validate_catalog_model(entry.client, model, free_only=not key)
        yield entry.client
        reusable = getattr(entry.client, '_echo_reusable', True)
    finally:
        async with lock:
            if _warm_servers.get(signature) is entry:
                if not reusable:
                    del _warm_servers[signature]
                    await _stop_server(entry.process, entry.client)
                else:
                    entry.in_use = False
                    _warm_servers.pop(signature)
                    _warm_servers[signature] = entry
                    _schedule_warm_expiry(entry)


async def _discard_idle_warm_server(root: Path) -> None:
    async with _loop_lock():
        for current in tuple(_warm_servers.values()):
            if current.in_use or current.loop is not asyncio.get_running_loop() or current.root != root.resolve():
                continue
            _warm_servers.pop(current.signature, None)
            if current.idle_handle is not None:
                current.idle_handle.cancel()
            await _stop_server(current.process, current.client)


@asynccontextmanager
async def managed_server(
    command: str,
    root: Path,
    key: str | None,
    model: str,
    web: bool,
    *,
    host_mcp: HostMCPConnection | None = None,
    shared_provider: dict[str, Any] | None = None,
) -> AsyncIterator[httpx.AsyncClient]:
    # A text-only server has an all-deny tool policy and no per-turn MCP
    # credential. Keep up to three isolated conversations warm so replies avoid
    # paying the official process's cold-start cost. Tool-capable turns remain
    # ephemeral because their broker and authorization are scoped to one turn.
    if shared_provider is None and host_mcp is None and not web and threading.current_thread() is threading.main_thread():
        async with _warm_text_server(command, root, key, model) as client:
            yield client
        return
    if threading.current_thread() is threading.main_thread():
        await _discard_idle_warm_server(root)
    async with _ephemeral_server(command, root, key, model, web, host_mcp=host_mcp, shared_provider=shared_provider) as client:
        yield client


async def validate_catalog_model(
    client: httpx.AsyncClient, model: str, *, free_only: bool = False
) -> None:
    """Reject stale Zen selections before OpenCode reports an opaque HTTP 500."""
    try:
        response = await client.get("/provider")
        response.raise_for_status()
        payload = response.json()
        providers = payload.get("all") if isinstance(payload, dict) else None
        if not isinstance(providers, list):
            raise ValueError("invalid provider catalog")
        provider, upstream = native_model(model)
        zen = next(
            (p for p in providers if isinstance(p, dict) and p.get("id") == provider),
            {},
        )
        models = zen.get("models", {})
        if not isinstance(models, dict):
            raise ValueError("invalid model catalog")
    except (httpx.HTTPError, ValueError):
        raise OpenCodeError("无法读取 OpenCode 模型列表，请稍后重试。") from None
    if upstream not in models:
        raise OpenCodeError("OpenCode 当前未提供所选 Zen 模型，请在输入框选择其他模型后重试。")
    if free_only:
        cost = models[upstream].get("cost") if isinstance(models[upstream], dict) else None

        def zero_price(value: Any) -> bool:
            if isinstance(value, dict):
                return all(zero_price(item) for item in value.values())
            return type(value) in (int, float) and value == 0

        if (
            not isinstance(cost, dict)
            or not {"input", "output"}.issubset(cost)
            or not zero_price(cost)
        ):
            raise OpenCodeError("未连接 Zen 账号时仅可使用官方目录中明确标为零费用的模型。")


async def reasoning_variants(client: httpx.AsyncClient, model: str) -> list[str]:
    """Read only variants advertised by the selected native model."""
    response = await client.get("/provider")
    response.raise_for_status()
    provider, upstream = native_model(model)
    for entry in response.json().get("all", []):
        if entry.get("id") == provider:
            variants = entry.get("models", {}).get(upstream, {}).get("variants", {})
            return [name for name, options in variants.items()
                    if isinstance(options, dict) and not options.get("disabled")]
    return []


async def session_for_thread(client: httpx.AsyncClient, root: Path) -> str:
    mapping = root / "session.json"
    if mapping.exists():
        try:
            session_id = json.loads(mapping.read_text(encoding="utf-8"))["session_id"]
            if not isinstance(session_id, str) or not re.fullmatch(r"ses_[A-Za-z0-9]+", session_id):
                raise ValueError("invalid session coordinate")
        except (ValueError, KeyError):
            raise OpenCodeError("OpenCode 会话记录损坏，请新建对话。") from None
        response = await client.get(f"/session/{session_id}")
        if response.status_code == 200:
            return session_id
        if response.status_code != 404:
            raise OpenCodeError("无法读取 OpenCode 会话，请稍后重试。")
        # Do not silently lose a conversation that used to exist.
        raise OpenCodeError("OpenCode 会话已不存在，请新建对话继续。")
    response = await client.post("/session", json={"title": "Echo"})
    response.raise_for_status()
    session_id = response.json()["id"]
    temporary = mapping.with_suffix(".tmp")
    temporary.write_text(json.dumps({"session_id": session_id}), encoding="utf-8")
    temporary.replace(mapping)
    return session_id


def public_model_error(error: Any) -> str:
    detail = json.dumps(error, ensure_ascii=False).lower()
    if "429" in detail or "limit" in detail or "rate" in detail:
        return "当前模型额度或请求频率受限，请稍后重试或切换模型。"
    if "401" in detail or "unauthorized" in detail or "authentication" in detail:
        return "模型连接已失效，请在模型设置中检查授权。"
    if "model" in detail and any(x in detail for x in ("not found", "unavailable", "404")):
        return "当前模型不可用，请切换其他模型。"
    return "OpenCode 调用模型失败，请稍后重试或检查模型连接。"


@dataclass
class MessageEvents:
    """Reduce growing message snapshots without replaying old prose or tools."""

    baseline: set[str]
    text: dict[str, str] = field(default_factory=dict)
    tools: dict[str, str] = field(default_factory=dict)
    last_text_part: str | None = None
    tool_names: dict[str, str] = field(default_factory=dict)

    def consume(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events = []
        for message in messages:
            info = message.get("info", {})
            if info.get("role") != "assistant" or info.get("id") in self.baseline:
                continue
            for part in message.get("parts", []):
                part_id = str(part.get("id", ""))
                if part.get("type") == "text" and not part.get("synthetic"):
                    value = str(part.get("text") or "")
                    old = self.text.get(part_id, "")
                    if value.startswith(old) and len(value) > len(old):
                        events.append(
                            {
                                "type": "text_delta",
                                "delta": value[len(old) :],
                                "start_new_segment": self.last_text_part not in (None, part_id),
                            }
                        )
                        self.last_text_part = part_id
                        self.text[part_id] = value
                elif part.get("type") == "tool":
                    state = part.get("state", {})
                    status = state.get("status")
                    call_id = str(part.get("callID") or part_id)
                    engine_name = str(part.get("tool") or "tool")
                    tool = self.tool_names.get(engine_name, f"opencode.{engine_name}")
                    tool_input = state.get("input", {})
                    encoded_input = json.dumps(tool_input, ensure_ascii=False)
                    input_preview = (
                        tool_input
                        if isinstance(tool_input, dict) and len(encoded_input) <= 100_000
                        else encoded_input[:2000]
                    )
                    if status in ("running", "completed", "error") and call_id not in self.tools:
                        events.append(
                            {
                                "type": "tool_start",
                                "tool_name": tool,
                                "tool_call_id": call_id,
                                "input_preview": input_preview,
                            }
                        )
                    if status in ("completed", "error") and self.tools.get(call_id) not in (
                        "completed",
                        "error",
                    ):
                        events.append(
                            {
                                "type": "tool_end",
                                "tool_name": tool,
                                "tool_call_id": call_id,
                                "success": status == "completed",
                                "status": "success" if status == "completed" else "error",
                                "output_preview": str(
                                    state.get("output") or state.get("error") or ""
                                )[:4000],
                            }
                        )
                    if status != "pending":
                        self.tools[call_id] = status
        return events


async def _abort_and_settle(client: httpx.AsyncClient, session_id: str) -> None:
    # A cancelled HTTP request is not proof that the native model has stopped.
    client._echo_reusable = False
    try:
        async with asyncio.timeout(3):
            response = await client.post(f"/session/{session_id}/abort", timeout=2)
            response.raise_for_status()
            if response.json() is not True:
                return
            while True:
                response = await client.get("/session/status", timeout=1)
                response.raise_for_status()
                statuses = response.json()
                if (
                    isinstance(statuses, dict)
                    and statuses.get(session_id, {"type": "idle"}).get("type") == "idle"
                ):
                    # Retire cancelled processes even after idle: a late prompt
                    # admission must not race with the next warm acquisition.
                    return
                await asyncio.sleep(0.05)
    except (TimeoutError, httpx.HTTPError, ValueError, AttributeError):
        pass  # managed_server must retire an unconfirmed warm connection.


async def stream_prompt(
    client: httpx.AsyncClient,
    session_id: str,
    *,
    text: str,
    system: str,
    model: str,
    interrupted: Callable[[], bool],
    poll_s: float = 0.1,
    tool_names: dict[str, str] | None = None,
    fresh_thread_text: str | None = None,
    reasoning_effort: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    from runtime.execution.opencode_events import (
        TurnEvents,
        message_id,
        receive_events,
        reported_turn_cost,
    )

    variant = None
    if reasoning_effort:
        offered = await reasoning_variants(client, model)
        candidate = "none" if reasoning_effort == "off" and "none" in offered else reasoning_effort
        if candidate in offered:
            variant = candidate
        elif offered:
            raise OpenCodeError("当前模型不支持所选推理档位，请重新选择。")
    url = f"/session/{session_id}"
    previous = await client.get(f"{url}/message")
    previous.raise_for_status()
    previous_messages = previous.json()
    if not previous_messages and fresh_thread_text is not None:
        text = fresh_thread_text
    reducer = MessageEvents(
        {m["info"]["id"] for m in previous_messages}, tool_names=tool_names or {}
    )
    user_message_id = message_id()
    projection = TurnEvents(session_id, user_message_id, reducer)
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=128)
    ready = asyncio.Event()
    receiver = asyncio.create_task(receive_events(client, queue, ready))
    pending = None
    incoming = None
    settled = False
    try:
        # Subscribe before prompt submission so early Parts are not lost.
        try:
            await asyncio.wait_for(ready.wait(), timeout=2)
        except TimeoutError:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            queue.put_nowait(None)
        if interrupted():
            yield {"type": "react_cancelled", "reason": "用户停止了任务"}
            return
        pending = asyncio.create_task(
            client.post(
                f"{url}/message",
                json={
                    "messageID": user_message_id,
                    "model": {"providerID": native_model(model)[0], "modelID": native_model(model)[1]},
                    "agent": "echo",
                    **({"variant": variant} if variant else {}),
                    "system": system,
                    "parts": [{"type": "text", "text": text}],
                },
                timeout=None,
            )
        )
        incoming = asyncio.create_task(queue.get())
        streaming = True
        next_snapshot = 0.0
        loop = asyncio.get_running_loop()
        while True:
            if interrupted():
                await _abort_and_settle(client, session_id)
                settled = True
                yield {"type": "react_cancelled", "reason": "用户停止了任务"}
                return
            waiting = {pending}
            if incoming is not None:
                waiting.add(incoming)
            await asyncio.wait(waiting, timeout=poll_s, return_when=asyncio.FIRST_COMPLETED)
            if incoming is not None and incoming.done():
                native = incoming.result()
                incoming = None
                if native is None:
                    streaming = False
                else:
                    for event in projection.consume(native):
                        yield event
                    incoming = asyncio.create_task(queue.get())
            if not streaming and not pending.done() and loop.time() >= next_snapshot:
                response = await client.get(f"{url}/message")
                response.raise_for_status()
                for event in projection.snapshots(response.json()):
                    yield event
                next_snapshot = loop.time() + 1.0
            if not pending.done():
                continue
            result = await pending
            if result.is_error:
                raise OpenCodeError(
                    public_model_error(
                        {"statusCode": result.status_code, "body": result.text[:16_384]}
                    )
                )
            final = result.json()
            # One final read repairs missed/out-of-order Parts and earlier tool
            # messages. Never replay queued deltas after this snapshot boundary.
            response = await client.get(f"{url}/message")
            response.raise_for_status()
            final_messages = response.json()
            for event in projection.snapshots(final_messages):
                yield event
            for event in reducer.consume([final]):
                yield event
            info = final.get("info", {})
            if info.get("error"):
                raise OpenCodeError(public_model_error(info["error"]))
            if info.get("finish") not in ("stop", "end_turn"):
                raise OpenCodeError("OpenCode 未完成本次回答，请重试继续。")
            if not any(reducer.text.values()):
                raise OpenCodeError("模型没有返回回答，请重试或切换模型。")
            settled = True
            yield {
                "type": "react_completed",
                "success": True,
                "terminated_reason": "completed",
                "completion_receipt": {
                    "engine": "opencode",
                    "model": model,
                    "reasoning_variant": variant,
                    "cost": reported_turn_cost([*final_messages, final], user_message_id),
                    "tokens": info.get("tokens"),
                },
            }
            return
    finally:
        receiver.cancel()
        if incoming is not None:
            incoming.cancel()
        await asyncio.gather(receiver, *([incoming] if incoming else []), return_exceptions=True)
        if pending is not None:
            if not settled:
                await _abort_and_settle(client, session_id)
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
