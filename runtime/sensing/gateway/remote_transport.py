"""
Remote Transport · connect a desktop session to a remote
octopus-agent runtime over authenticated HTTP and WebSocket.

The desktop binary runs locally but routes every API call to a backend
process running on a different host. The user sees the same UI;
the work runs where the data is.

Scope of this module
--------------------
This module provides:

  * The ``RemoteBackend`` data model (one named remote target with
    SSH params + cached health status).
  * A ``BackendRegistry`` that persists the list to disk via
    ``atomic_write_json``.
  * HTTP and bidirectional WebSocket proxy helpers for a remote runtime.
  * Encrypted-at-rest bearer credentials forwarded only to that runtime.
  * Per-request OpenSSH local forwarding for private runtime endpoints.
  * Health-check helpers (one-shot + periodic).

What this module does NOT do (yet)
----------------------------------
  * SSE relay. Realtime turns use the implemented WebSocket relay.
  * SSH key generation / host enrollment workflow. Remote setup is
    user's responsibility for now (point at an existing trusted host).
  * Failover.

Both follow-ups are isolated by ``ui.remote_transport`` feature
flag — until that ships, all routes return 403.

Storage
-------
``data/remote_backends.json``::

    {
      "backends": [
        { "id": "...", "name": "...", "url": "https://host:8000",
          "ssh": null | { "host": "...", "user": "...", "port": 22,
                          "identity_file": "..." },
          "has_auth": true | false,
          "added_at": "...", "last_health": "ok" | "error" | null,
          "last_health_at": "..." }
      ]
    }
"""

from __future__ import annotations

import contextlib
import json as _json
import logging
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse
from uuid import uuid4

from runtime.platform.io import atomic_write_json, read_json_with_backup
from runtime.platform.process.sliding_window_limiter import SlidingWindowLimiter

# Inbound anti-abuse ceiling on the relayed client WS, mirroring the
# team-rooms handler. The relay forwards every frame to the remote
# backend, so an unbounded local client could push arbitrary memory at
# the upstream; bounding the frame size and rate keeps a single bad
# client from amplifying a flood. Lenient — legit JSON-RPC frames are a
# few KB.
_PROXY_WS_MAX_INBOUND_BYTES = 256 * 1024
_PROXY_WS_MSG_PER_SEC = 30

_LOG = logging.getLogger("octopus.remote_transport")


# ═══════════════════════════════════════════════════════════
# Data model
# ═══════════════════════════════════════════════════════════


@dataclass
class SshTunnel:
    """SSH transport descriptor. Mirrors ``SshBackend`` config so an
    existing SSH-trusted host can be reused without re-entering
    credentials.
    """

    host: str
    user: str | None = None
    port: int = 22
    identity_file: str | None = None
    connect_timeout: int = 10

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SshTunnel | None:
        try:
            host = str(raw.get("host") or "").strip()
            if not host:
                return None
            user = str(raw.get("user") or "").strip() or None
            identity_file = str(raw.get("identity_file") or "").strip() or None
            raw_port = raw.get("port", 22)
            raw_timeout = raw.get("connect_timeout", 10)
            port = int(22 if raw_port in (None, "") else raw_port)
            connect_timeout = int(10 if raw_timeout in (None, "") else raw_timeout)
            if (
                host.startswith("-")
                or re.search(r"[\s\x00-\x1f\x7f@]", host)
                or (user is not None and re.search(r"[\s\x00-\x1f\x7f@]", user))
                or (identity_file is not None and re.search(r"[\x00-\x1f\x7f]", identity_file))
                or not 1 <= port <= 65535
                or not 1 <= connect_timeout <= 120
            ):
                return None
            return cls(
                host=host,
                user=user,
                port=port,
                identity_file=identity_file,
                connect_timeout=connect_timeout,
            )
        except (TypeError, ValueError):
            return None


@dataclass
class RemoteBackend:
    """One named remote octopus-agent runtime."""

    id: str
    name: str
    url: str  # http(s)://host:port
    ssh: SshTunnel | None = None
    added_at: str = ""
    last_health: str | None = None  # "ok" | "error" | None (untested)
    last_health_at: str | None = None
    health_detail: str | None = None  # last error message
    has_auth: bool = False
    # Runtime-only proof that a loopback URL was created by our own SSH
    # forwarder. Never loaded from or persisted to the registry.
    tunnel_active: bool = False

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("tunnel_active", None)
        d["ssh"] = self.ssh.to_dict() if self.ssh else None
        d["transport"] = "ssh_tunnel" if self.ssh else "direct"
        d["capabilities"] = {
            "http": True,
            "realtime": True,
            "ssh_tunnel": self.ssh is not None,
        }
        return d

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RemoteBackend | None:
        try:
            bid = str(raw["id"]).strip()
            name = str(raw["name"]).strip()
            url = str(raw["url"]).strip()
            if not bid or not name or not url:
                return None
            ssh_raw = raw.get("ssh")
            ssh = SshTunnel.from_dict(ssh_raw) if isinstance(ssh_raw, dict) else None
            if isinstance(ssh_raw, dict) and ssh is None:
                return None
            url = _validate_url(url)
            return cls(
                id=bid,
                name=name,
                url=url,
                ssh=ssh,
                added_at=str(raw.get("added_at") or ""),
                last_health=raw.get("last_health"),
                last_health_at=raw.get("last_health_at"),
                health_detail=raw.get("health_detail"),
                has_auth=bool(raw.get("has_auth", False)),
            )
        except (KeyError, TypeError, ValueError):
            return None


# ═══════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════


def _validate_url(url: str) -> str:
    """Return the canonicalized URL or raise ValueError."""
    text = (url or "").strip().rstrip("/")
    if not text:
        raise ValueError("url is required")
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError(
            f"url must start with http:// or https:// (got {text!r})",
        )
    if not parsed.hostname:
        raise ValueError("url must contain a host")
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"url has invalid port: {exc}") from exc
    if port == 0:
        raise ValueError("url port must be between 1 and 65535")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("url must not contain embedded credentials")
    if parsed.fragment:
        raise ValueError("url must not contain a fragment")
    return text


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class SshTunnelError(RuntimeError):
    """Raised when a configured SSH transport cannot be established."""


class SshTunnelForwarder:
    """Own one fail-closed OpenSSH local forward for a remote backend.

    The registry URL names the service as visible *from the SSH host*, e.g.
    ``http://127.0.0.1:8000``. The forwarder rewrites that endpoint to an
    ephemeral local loopback port only after OpenSSH confirms the forward.
    """

    def __init__(self, backend: RemoteBackend) -> None:
        if backend.ssh is None:
            raise ValueError("backend has no SSH tunnel configuration")
        tunnel = SshTunnel.from_dict(backend.ssh.to_dict())
        if tunnel is None:
            raise SshTunnelError("SSH tunnel configuration is invalid")
        parsed = urlparse(backend.url)
        if parsed.scheme != "http":
            raise SshTunnelError(
                "SSH tunnel endpoints must use http://; SSH already encrypts the transport"
            )
        if not parsed.hostname:
            raise SshTunnelError("SSH tunnel endpoint is missing a host")
        self.backend = backend
        self.tunnel = tunnel
        self._process: subprocess.Popen[bytes] | None = None
        self._local_port: int | None = None

    @staticmethod
    def _reserve_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            return int(listener.getsockname()[1])

    def _argv(self, local_port: int) -> list[str]:
        tunnel = self.tunnel
        ssh = shutil.which("ssh")
        if ssh is None:
            raise SshTunnelError("OpenSSH client is not available")
        parsed = urlparse(self.backend.url)
        remote_host = parsed.hostname or ""
        remote_port = parsed.port or 80
        forward_host = f"[{remote_host}]" if ":" in remote_host else remote_host
        target = f"{tunnel.user}@{tunnel.host}" if tunnel.user else tunnel.host
        argv = [
            ssh,
            "-N",
            "-T",
            "-p",
            str(tunnel.port),
            "-o",
            f"ConnectTimeout={tunnel.connect_timeout}",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=3",
            "-o",
            "ExitOnForwardFailure=yes",
            "-o",
            "BatchMode=yes",
        ]
        if tunnel.identity_file:
            argv.extend(["-i", tunnel.identity_file, "-o", "IdentitiesOnly=yes"])
        argv.extend(["-L", f"127.0.0.1:{local_port}:{forward_host}:{remote_port}", target])
        return argv

    def start(self) -> RemoteBackend:
        if self._process is not None:
            raise SshTunnelError("SSH tunnel is already started")
        tunnel = self.tunnel
        local_port = self._reserve_port()
        argv = self._argv(local_port)
        try:
            process = subprocess.Popen(  # noqa: S603 - argv is validated and never shell-expanded
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                start_new_session=True,
            )
        except OSError as exc:
            raise SshTunnelError(f"failed to start OpenSSH: {exc}") from exc
        self._process = process
        self._local_port = local_port

        deadline = time.monotonic() + max(1, tunnel.connect_timeout)
        while time.monotonic() < deadline:
            if process.poll() is not None:
                detail = ""
                if process.stderr is not None:
                    with contextlib.suppress(OSError):
                        detail = process.stderr.read(4096).decode("utf-8", errors="replace").strip()
                self.close()
                raise SshTunnelError(detail or "OpenSSH exited before forwarding")
            try:
                with socket.create_connection(("127.0.0.1", local_port), timeout=0.2):
                    parsed = urlparse(self.backend.url)
                    local_netloc = f"127.0.0.1:{local_port}"
                    return replace(
                        self.backend,
                        url=urlunparse(parsed._replace(netloc=local_netloc)),
                        ssh=None,
                        tunnel_active=True,
                    )
            except OSError:
                time.sleep(0.05)

        self.close()
        raise SshTunnelError("timed out establishing SSH tunnel")

    def close(self) -> None:
        process = self._process
        self._process = None
        self._local_port = None
        if process is None or process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            process.kill()
            with contextlib.suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1.0)
        if process.stderr is not None:
            with contextlib.suppress(OSError):
                process.stderr.close()


@contextlib.contextmanager
def connect_remote_backend(
    backend: RemoteBackend,
    *,
    forwarder_factory: Any = SshTunnelForwarder,
) -> Iterator[RemoteBackend]:
    """Yield a directly reachable backend, opening SSH when configured."""

    if backend.ssh is None:
        yield backend
        return
    forwarder = forwarder_factory(backend)
    try:
        yield forwarder.start()
    finally:
        forwarder.close()


# ═══════════════════════════════════════════════════════════
# Registry
# ═══════════════════════════════════════════════════════════


class BackendRegistry:
    """Process-wide cache of registered remote backends, persisted
    to ``<data>/remote_backends.json``.

    Single global lock — registrations happen rarely (interactive
    UI), no need for fine-grained concurrency.
    """

    def __init__(self, store_path: str | Path, *, credential_store: Any = None) -> None:
        self._path = Path(store_path)
        self._lock = threading.RLock()
        self._backends: dict[str, RemoteBackend] = {}
        self._credential_store = credential_store
        self._load()

    def _secrets(self) -> Any:
        if self._credential_store is None:
            from runtime.platform.connectors.credential_store import CredentialStore

            self._credential_store = CredentialStore(
                root=self._path.parent / ".remote-backend-credentials",
            )
        return self._credential_store

    @staticmethod
    def _credential_id(backend_id: str) -> str:
        return f"remote-backend:{backend_id}"

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> None:
        raw = read_json_with_backup(self._path, default={})
        if not isinstance(raw, dict):
            return
        for entry in raw.get("backends") or []:
            if isinstance(entry, dict):
                b = RemoteBackend.from_dict(entry)
                if b is not None:
                    self._backends[b.id] = b

    def _flush(self) -> None:
        payload = {
            "backends": [b.to_dict() for b in self._backends.values()],
        }
        atomic_write_json(self._path, payload)

    def list(self) -> list[RemoteBackend]:
        with self._lock:
            return list(self._backends.values())

    def get(self, backend_id: str) -> RemoteBackend | None:
        with self._lock:
            return self._backends.get(backend_id)

    def get_by_name(self, name: str) -> RemoteBackend | None:
        with self._lock:
            for b in self._backends.values():
                if b.name == name:
                    return b
            return None

    def add(
        self,
        *,
        name: str,
        url: str,
        ssh: SshTunnel | None = None,
        auth_token: str | None = None,
    ) -> RemoteBackend:
        canonical_url = _validate_url(url)
        if ssh is not None:
            validated_ssh = SshTunnel.from_dict(ssh.to_dict())
            if validated_ssh is None:
                raise ValueError("ssh tunnel configuration is invalid")
            if urlparse(canonical_url).scheme.lower() != "http":
                raise ValueError(
                    "SSH tunnel endpoints must use http://; SSH encrypts the transport"
                )
            ssh = validated_ssh
        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("name is required")
        clean_token = (auth_token or "").strip()
        if clean_token and (
            len(clean_token) > 16_384 or re.search(r"[\x00-\x1f\x7f]", clean_token)
        ):
            raise ValueError("auth_token is invalid")
        with self._lock:
            if any(b.name == clean_name for b in self._backends.values()):
                raise ValueError(f"backend named {clean_name!r} already exists")
            backend = RemoteBackend(
                id=uuid4().hex,
                name=clean_name,
                url=canonical_url,
                ssh=ssh,
                added_at=_now_iso(),
                has_auth=bool(clean_token),
            )
            if clean_token:
                self._secrets().set_secret(
                    self._credential_id(backend.id),
                    "auth_token",
                    clean_token,
                )
            self._backends[backend.id] = backend
            self._flush()
            return backend

    def remove(self, backend_id: str) -> bool:
        with self._lock:
            backend = self._backends.get(backend_id)
            if backend is None:
                return False
            del self._backends[backend_id]
            self._flush()
            if backend.has_auth:
                with contextlib.suppress(Exception):
                    self._secrets().clear_connector(self._credential_id(backend_id))
            return True

    def auth_token(self, backend_id: str) -> str | None:
        with self._lock:
            backend = self._backends.get(backend_id)
            if backend is None or not backend.has_auth:
                return None
            return self._secrets().get_secret(
                self._credential_id(backend_id),
                "auth_token",
            )

    def set_auth_token(self, backend_id: str, auth_token: str | None) -> RemoteBackend | None:
        clean_token = (auth_token or "").strip()
        if clean_token and (
            len(clean_token) > 16_384 or re.search(r"[\x00-\x1f\x7f]", clean_token)
        ):
            raise ValueError("auth_token is invalid")
        with self._lock:
            backend = self._backends.get(backend_id)
            if backend is None:
                return None
            credential_id = self._credential_id(backend_id)
            if clean_token:
                self._secrets().set_secret(credential_id, "auth_token", clean_token)
                backend.has_auth = True
            else:
                if backend.has_auth:
                    self._secrets().clear_connector(credential_id)
                backend.has_auth = False
            self._flush()
            return backend

    def update_health(
        self,
        backend_id: str,
        *,
        status: str,
        detail: str | None = None,
    ) -> RemoteBackend | None:
        if status not in {"ok", "error"}:
            raise ValueError(f"status must be 'ok' or 'error' (got {status!r})")
        with self._lock:
            backend = self._backends.get(backend_id)
            if backend is None:
                return None
            backend.last_health = status
            backend.last_health_at = _now_iso()
            backend.health_detail = detail
            self._flush()
            return backend


# ═══════════════════════════════════════════════════════════
# Health check
# ═══════════════════════════════════════════════════════════


def health_check(
    backend: RemoteBackend,
    *,
    timeout_seconds: float = 5.0,
    http_client: Any = None,
    auth_token: str | None = None,
) -> tuple[str, str | None]:
    """Hit ``<url>/api/health`` and return (status, detail).

    ``http_client`` lets tests inject a stub. Production passes
    ``None`` and we lazy-import ``httpx``. We keep this function
    sync — caller can run it in a worker thread or asyncio
    executor as needed.
    """
    target = backend.url.rstrip("/") + "/api/health"
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
    try:
        if http_client is None:
            from runtime.safety.auth.url_guard import safe_httpx_request

            resp = safe_httpx_request(
                "GET",
                target,
                timeout=timeout_seconds,
                headers=headers,
                allow_private=backend.tunnel_active,
            )
            ok = 200 <= resp.status_code < 300
            detail = None if ok else f"HTTP {resp.status_code}"
        else:
            resp = http_client.get(target, timeout=timeout_seconds, headers=headers)
            ok = 200 <= getattr(resp, "status_code", 0) < 300
            detail = None if ok else f"HTTP {resp.status_code}"
    except (ConnectionError, TimeoutError) as exc:
        return "error", f"{type(exc).__name__}: {exc}"
    return ("ok" if ok else "error"), detail


# ═══════════════════════════════════════════════════════════
# HTTP proxy (one-shot, non-streaming)
# ═══════════════════════════════════════════════════════════


def proxy_request(
    backend: RemoteBackend,
    *,
    method: str,
    path: str,
    json: Any = None,
    timeout_seconds: float = 30.0,
    http_client: Any = None,
    auth_token: str | None = None,
) -> dict[str, Any]:
    """Forward a request to a remote backend.

    Returns ``{"status_code": int, "body": dict | str}``.

    Realtime WebSocket traffic is handled by ``proxy_websocket``;
    this helper intentionally remains a one-shot HTTP request.
    """
    method = (method or "GET").upper()
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError(f"unsupported method {method!r}")
    target = backend.url.rstrip("/") + "/" + path.lstrip("/")
    headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
    try:
        if http_client is None:
            from runtime.safety.auth.url_guard import safe_httpx_request

            resp = safe_httpx_request(
                method,
                target,
                json=json,
                headers=headers,
                timeout=timeout_seconds,
                allow_private=backend.tunnel_active,
            )
        else:
            resp = http_client.request(
                method,
                target,
                json=json,
                headers=headers,
                timeout=timeout_seconds,
            )
        status = int(getattr(resp, "status_code", 0) or 0)
        try:
            body: Any = resp.json() if hasattr(resp, "json") else resp.text
            if callable(body):
                body = body()
        except (_json.JSONDecodeError, AttributeError):
            body = getattr(resp, "text", "") if hasattr(resp, "text") else ""
        return {"status_code": status, "body": body}
    except (ConnectionError, TimeoutError) as exc:
        return {
            "status_code": 0,
            "body": {
                "error": "proxy_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            },
        }


__all__ = [
    "BackendRegistry",
    "RemoteBackend",
    "SshTunnelError",
    "SshTunnelForwarder",
    "SshTunnel",
    "connect_remote_backend",
    "health_check",
    "proxy_request",
    "proxy_websocket",
]


# ═══════════════════════════════════════════════════════════
# WebSocket proxy (bidirectional, JSON-RPC 2.0)
# ═══════════════════════════════════════════════════════════
#
# The remote octopus-agent runtime exposes its realtime gateway at
# ``<url>/api/realtime``. We tunnel a desktop client's WebSocket
# session through to that endpoint by:
#
#   1. Translate ``http(s)://`` → ``ws(s)://`` for the upstream URL
#   2. Open an ``httpx.AsyncClient`` WebSocket (or ``websockets``
#      package — both are stdlib-adjacent; we use ``websockets``
#      as it's already a starlette dependency)
#   3. Pump messages in both directions until either side closes
#
# Two relay tasks: client→remote and remote→client. ``asyncio.wait``
# with ``FIRST_COMPLETED`` lets us detect either side's close and
# tear down cleanly. No buffering — every frame is forwarded as it
# arrives, so JSON-RPC request/response/notification semantics pass
# through transparently.


def _to_ws_url(http_url: str, path: str) -> str:
    """Translate an HTTP backend URL to its WebSocket form, joined
    with ``path``. ``https://`` becomes ``wss://``, ``http://``
    becomes ``ws://``.
    """
    base = http_url.rstrip("/")
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[len("http://") :]
    else:
        # Already a ws:// URL or something weird — pass through.
        ws_base = base
    return ws_base + "/" + path.lstrip("/")


async def proxy_websocket(
    backend: RemoteBackend,
    client_ws: Any,
    *,
    path: str = "/api/realtime",
    upstream_factory: Any = None,
    auth_token: str | None = None,
) -> None:
    """Bidirectionally relay a WebSocket session to the remote
    backend's realtime gateway.

    ``client_ws`` is the local ``starlette.websockets.WebSocket``
    that the operator's browser/Electron has opened to *us*. We
    open a second WebSocket to the remote backend and pump frames
    in both directions.

    Returns when either side closes. Caller is responsible for
    accepting the client websocket BEFORE calling (so error
    responses can still be sent if the upstream connect fails).

    ``upstream_factory`` lets tests inject a stub. It must be an
    async context manager yielding an object with
    ``send(text: str)`` / ``recv() -> str`` / ``close()``.
    """
    upstream_url = _to_ws_url(backend.url, path)
    from urllib.parse import urlparse

    from runtime.safety.auth.url_guard import check_url

    parsed_upstream = urlparse(upstream_url)
    http_equivalent = parsed_upstream._replace(
        scheme="https" if parsed_upstream.scheme == "wss" else "http"
    ).geturl()
    verdict = (
        check_url(
            http_equivalent,
            allow_private=backend.tunnel_active,
        )
        if upstream_factory is None
        else None
    )
    if verdict is not None and not verdict.allow:
        await client_ws.send_text(_ws_error_envelope(f"url_guard rejected: {verdict.reason}"))
        await client_ws.close(code=1008)
        return

    # Lazy-import websockets (heavy dep, server-only).
    if upstream_factory is None:
        assert verdict is not None
        try:
            import websockets  # type: ignore[import-not-found]
        except ImportError as exc:
            await client_ws.send_text(
                _ws_error_envelope(
                    "websockets package not available — pip install websockets",
                ),
            )
            await client_ws.close(code=1011)
            raise RuntimeError("websockets package required") from exc
        connect_kwargs: dict[str, Any] = {"max_size": None, "proxy": None}
        if auth_token:
            connect_kwargs["additional_headers"] = {
                "Authorization": f"Bearer {auth_token}",
            }
        if verdict.resolved_ip:
            # websockets uses ``host`` for the TCP dial target while retaining
            # the URI hostname for the WebSocket Host/SNI identity. This pins
            # the connection to the address that passed the guard.
            connect_kwargs["host"] = verdict.resolved_ip
        connect = websockets.connect(upstream_url, **connect_kwargs)
    else:
        connect = upstream_factory(upstream_url)

    try:
        async with connect as upstream:
            # Per-connection inbound guard, local to this pump so it's
            # freed when the connection closes. Oversized frames are
            # dropped before relay; a runaway client's sustained flood is
            # shed without forwarding. Mirrors ``team_rooms_ws``.
            _inbound_limiter = SlidingWindowLimiter(
                limit=_PROXY_WS_MSG_PER_SEC,
                window_s=1.0,
            )

            async def _client_to_remote() -> None:
                while True:
                    try:
                        msg = await client_ws.receive_text()
                    except Exception as exc:
                        _LOG.debug("client_ws receive_text broke: %s", exc)
                        break
                    if len(msg) > _PROXY_WS_MAX_INBOUND_BYTES:
                        _LOG.warning(
                            "proxy: dropping %d-byte inbound frame (limit %d)",
                            len(msg),
                            _PROXY_WS_MAX_INBOUND_BYTES,
                        )
                        continue
                    if not _inbound_limiter.allow("inbound"):
                        _LOG.debug("proxy: shedding over-rate inbound frame")
                        continue
                    try:
                        await upstream.send(msg)
                    except Exception as exc:
                        _LOG.debug("upstream send broke: %s", exc)
                        break

            async def _remote_to_client() -> None:
                while True:
                    try:
                        msg = await upstream.recv()
                    except Exception as exc:
                        _LOG.debug("upstream recv broke: %s", exc)
                        break
                    if not isinstance(msg, str):
                        # Binary frames — re-encode.
                        try:
                            msg = msg.decode("utf-8")  # type: ignore[union-attr]
                        except (AttributeError, UnicodeDecodeError) as exc:
                            _LOG.debug("binary decode skipped: %s", exc)
                            continue
                    try:
                        await client_ws.send_text(msg)
                    except Exception as exc:
                        _LOG.debug("client_ws send_text broke: %s", exc)
                        break

            import asyncio

            t1 = asyncio.create_task(_client_to_remote())
            t2 = asyncio.create_task(_remote_to_client())
            done, pending = await asyncio.wait(
                {t1, t2},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in pending:
                with contextlib.suppress(Exception):
                    await task
    except Exception as exc:
        _LOG.warning("websocket proxy failed: %s", exc)
        with contextlib.suppress(Exception):
            await client_ws.send_text(
                _ws_error_envelope(f"upstream failed: {type(exc).__name__}: {exc}"),
            )


def _ws_error_envelope(message: str) -> str:
    """Compose a JSON-RPC 2.0 error notification frame.

    Clients of the realtime gateway already parse JSON-RPC envelopes,
    so wrapping the proxy error in the same shape lets the existing
    error handler render it without a separate code path.
    """
    import json

    return json.dumps(
        {
            "jsonrpc": "2.0",
            "method": "proxy/error",
            "params": {"message": message},
        }
    )


# ═══════════════════════════════════════════════════════════
# Streaming proxy removed; realtime uses the WebSocket relay.
# ═══════════════════════════════════════════════════════════
#
# The WebSocket relay at ``proxy_websocket`` /
# ``/api/remote-backends/{id}/realtime`` is the sole live-turn path.
