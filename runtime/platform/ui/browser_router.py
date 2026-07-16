"""Browser session and relay compatibility router for the UI app."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse, Response
from starlette.requests import HTTPConnection

from runtime.memory.learning.review_queue import ReviewQueue
from runtime.platform.io import atomic_write_json, read_json_with_backup
from runtime.platform.process.paths import app_paths, project_root
from runtime.platform.runtime_policy.browser_sessions import BrowserSessionCenter
from runtime.safety.replay.browser_desktop_replay import browser_session_replay_identity

# Written into the profile dir while a persistent browser context is
# live; removed on clean shutdown. A leftover sentinel on the next
# launch means the previous session crashed (or the process was
# killed) — surfaced as ``session["recovered_from_crash"]`` so callers
# can re-validate login state instead of silently trusting it.
_SESSION_SENTINEL_NAME = ".octopus_session_active"


def secure_profile_dir(profile_dir: Path) -> None:
    """Owner-only access for the browser profile.

    The persistent context stores cookies and localStorage in
    PLAINTEXT here; the default mkdir mode (umask, typically 755)
    let every local user read login tokens.
    """
    with contextlib.suppress(OSError):
        os.chmod(profile_dir, 0o700)


def mark_session_active(profile_dir: Path) -> bool:
    """Write the crash sentinel. Returns True when a stale sentinel
    was already present (= previous session did not shut down
    cleanly)."""
    sentinel = profile_dir / _SESSION_SENTINEL_NAME
    crashed = sentinel.exists()
    with contextlib.suppress(OSError):
        sentinel.write_text(f"{os.getpid()} {time.time():.0f}\n", encoding="utf-8")
    return crashed


def mark_session_closed(profile_dir: Path | str | None) -> None:
    """Remove the crash sentinel on clean shutdown."""
    if not profile_dir:
        return
    with contextlib.suppress(OSError):
        (Path(profile_dir) / _SESSION_SENTINEL_NAME).unlink(missing_ok=True)


def create_browser_router(
    *,
    identity_store: Any = None,
    require_auth: bool = False,
    jwt_secret: str | None = None,
    jwt_issuer: str | None = None,
    jwt_audience: str | None = None,
) -> APIRouter:
    """Create the ``/api/browser/*`` session and relay router.

    These endpoints drive a real browser (navigation, form fill, credential
    entry). They previously had NO auth at all — inconsistent with the other
    routers that honour ``require_auth``. The router-level dependency below
    closes that gap: when ``require_auth`` is off (default / single-user dev)
    ``_resolve_actor`` is a no-op so local preview is unchanged; when auth is
    enabled it enforces 401 across every browser endpoint.
    """

    def _auth_dep(request: HTTPConnection) -> None:
        from runtime.adapters.web_auth import _resolve_actor

        _resolve_actor(  # AUTH-OK: actor-agnostic
            request,
            identity_store,
            require_auth,
            jwt_secret=jwt_secret,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
        )

    router = APIRouter(tags=["browser"], dependencies=[Depends(_auth_dep)])
    browser_config_state: dict[str, Any] = {
        "max_open_tabs": 20,
        "max_saved_tabs": 10,
        "connection_mode": "playwright",
        "cdp_port": 9222,
        "headless": True,
        "viewport_width": 1440,
        "viewport_height": 900,
        "relay_allowed_hosts": [],
        "relay_blocked_hosts": [],
        "relay_require_allowlist": False,
    }
    browser_policy_path = app_paths().browser_policy_path
    browser_session_center = BrowserSessionCenter(browser_config_state)
    browser_sessions = browser_session_center.sessions
    browser_relay_state: dict[str, Any] = {
        "connected": False,
        "extension_version": "",
        "last_seen": 0,
        "active_tab": None,
        "pending_commands": [],
        "command_results": {},
        "control_lease": None,
        "human_interrupt": None,
    }
    browser_relay_queue_lock = threading.Lock()
    relay_read_only_actions = {"extract", "aria", "screenshot", "wait"}

    def _normalize_relay_host_patterns(value: Any) -> list[str]:
        raw_items: list[Any]
        if isinstance(value, str):
            raw_items = [item.strip() for item in value.split(",")]
        elif isinstance(value, (list, tuple, set)):
            raw_items = list(value)
        else:
            raw_items = []
        out: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            text = str(item or "").strip().lower()
            if not text:
                continue
            if "://" in text:
                parsed = urllib.parse.urlparse(text)
                text = parsed.hostname or ""
            else:
                text = text.split("/", 1)[0].split("?", 1)[0]
                if ":" in text and not text.startswith("["):
                    text = text.split(":", 1)[0]
                text = text.strip("[]")
            if not text:
                continue
            text = "*." + text[2:].strip(".") if text.startswith("*.") else text.strip(".")
            if text and text not in seen:
                seen.add(text)
                out.append(text)
        return out[:200]

    def _apply_relay_heartbeat(body: dict[str, Any]) -> list[dict[str, Any]]:
        browser_relay_state["connected"] = True
        browser_relay_state["last_seen"] = _now_ts()
        browser_relay_state["extension_version"] = str(body.get("extension_version") or "local-dev")
        active_tab = body.get("active_tab")
        if isinstance(active_tab, dict):
            browser_relay_state["active_tab"] = {
                "id": active_tab.get("id"),
                "url": active_tab.get("url"),
                "title": active_tab.get("title"),
            }
        control_event = body.get("control_event")
        if isinstance(control_event, dict):
            event_type = str(control_event.get("type") or "").strip()
            if event_type == "human_interrupt":
                _record_relay_interrupt(
                    reason=str(control_event.get("reason") or "human_activity"),
                    source=str(control_event.get("source") or "chrome_extension"),
                    detail={
                        "activity": control_event.get("activity"),
                        "lease": control_event.get("lease"),
                    },
                )
            elif event_type == "clear_interrupt":
                _clear_relay_interrupt()
        return _drain_relay_commands()

    def _drain_relay_commands() -> list[dict[str, Any]]:
        with browser_relay_queue_lock:
            pending = list(browser_relay_state.get("pending_commands") or [])
            browser_relay_state["pending_commands"] = []
            return pending

    def _apply_relay_result(body: dict[str, Any]) -> dict[str, Any]:
        command_id = str(body.get("id") or "").strip()
        if not command_id:
            raise ValueError("id is required")
        browser_relay_state["last_seen"] = _now_ts()
        active_tab = body.get("active_tab")
        if isinstance(active_tab, dict):
            browser_relay_state["active_tab"] = {
                "id": active_tab.get("id"),
                "url": active_tab.get("url"),
                "title": active_tab.get("title"),
            }
        result = body.get("result")
        if not isinstance(result, dict):
            result = {"ok": False, "error": "missing relay result"}
        result.setdefault("ok", True)
        result.setdefault("id", command_id)
        if (browser_relay_state.get("control_lease") or {}).get("command_id") == command_id:
            browser_relay_state["control_lease"] = None
        result["control"] = _relay_control_snapshot()
        browser_relay_state.setdefault("command_results", {})[command_id] = result
        return result

    def _browser_policy_payload() -> dict[str, Any]:
        return {
            "schema": "octopus.browser_relay_site_policy.v1",
            "relay_allowed_hosts": list(browser_config_state.get("relay_allowed_hosts") or []),
            "relay_blocked_hosts": list(browser_config_state.get("relay_blocked_hosts") or []),
            "relay_require_allowlist": bool(
                browser_config_state.get("relay_require_allowlist"),
            ),
        }

    def _load_persisted_browser_policy() -> None:
        payload = read_json_with_backup(browser_policy_path, default={})
        if not isinstance(payload, dict):
            return
        if "relay_allowed_hosts" in payload:
            browser_config_state["relay_allowed_hosts"] = _normalize_relay_host_patterns(
                payload.get("relay_allowed_hosts"),
            )
        if "relay_blocked_hosts" in payload:
            browser_config_state["relay_blocked_hosts"] = _normalize_relay_host_patterns(
                payload.get("relay_blocked_hosts"),
            )
        if "relay_require_allowlist" in payload:
            browser_config_state["relay_require_allowlist"] = bool(
                payload.get("relay_require_allowlist"),
            )

    def _persist_browser_policy() -> None:
        atomic_write_json(browser_policy_path, _browser_policy_payload())

    _load_persisted_browser_policy()

    def _relay_host_from_url(url: str) -> str:
        try:
            return (urllib.parse.urlparse(url).hostname or "").strip(".").lower()
        except ValueError:
            return ""

    def _relay_host_matches(host: str, patterns: list[str]) -> bool:
        if not host:
            return False
        normalized = host.strip(".").lower()
        for pattern in patterns:
            item = pattern.strip().lower()
            if item == "*":
                return True
            if item.startswith("*."):
                suffix = item[2:]
                if normalized == suffix or normalized.endswith(f".{suffix}"):
                    return True
                continue
            if normalized == item:
                return True
        return False

    def _relay_policy_snapshot(
        *,
        decision: str = "",
        reason: str = "",
        target_host: str = "",
        target_url: str = "",
    ) -> dict[str, Any]:
        return {
            "schema": "octopus.browser_relay_site_policy.v1",
            "decision": decision,
            "reason": reason,
            "target_host": target_host,
            "target_url": target_url,
            "persisted": browser_policy_path.exists(),
            "policy_path": str(browser_policy_path),
            "allowed_hosts": list(browser_config_state.get("relay_allowed_hosts") or []),
            "blocked_hosts": list(browser_config_state.get("relay_blocked_hosts") or []),
            "require_allowlist": bool(
                browser_config_state.get("relay_require_allowlist"),
            ),
        }

    def _relay_site_policy_decision(action: str, body: dict[str, Any]) -> dict[str, Any]:
        active_tab = browser_relay_state.get("active_tab")
        active_tab = active_tab if isinstance(active_tab, dict) else {}
        target_url = str(body.get("url") or active_tab.get("url") or "").strip()
        target_host = _relay_host_from_url(target_url)
        if action == "navigate" and not target_host:
            return _relay_policy_snapshot(
                decision="block",
                reason="missing_or_invalid_target_url",
                target_url=target_url,
            )
        blocked_hosts = list(browser_config_state.get("relay_blocked_hosts") or [])
        if _relay_host_matches(target_host, blocked_hosts):
            return _relay_policy_snapshot(
                decision="block",
                reason="host_blocked",
                target_host=target_host,
                target_url=target_url,
            )
        require_allowlist = bool(browser_config_state.get("relay_require_allowlist"))
        allowed_hosts = list(browser_config_state.get("relay_allowed_hosts") or [])
        if require_allowlist and not _relay_host_matches(target_host, allowed_hosts):
            return _relay_policy_snapshot(
                decision="block",
                reason="host_not_allowed",
                target_host=target_host,
                target_url=target_url,
            )
        return _relay_policy_snapshot(
            decision="allow",
            reason="host_allowed" if target_host else "no_target_host",
            target_host=target_host,
            target_url=target_url,
        )

    def _relay_active_tab_snapshot() -> dict[str, Any] | None:
        active_tab = browser_relay_state.get("active_tab")
        if not isinstance(active_tab, dict):
            return None
        return {
            "id": active_tab.get("id"),
            "url": str(active_tab.get("url") or ""),
            "title": str(active_tab.get("title") or ""),
        }

    def _relay_control_lease() -> dict[str, Any] | None:
        lease = browser_relay_state.get("control_lease")
        if not isinstance(lease, dict):
            return None
        expires_at = int(lease.get("expires_at") or 0)
        if expires_at and expires_at <= _now_ts():
            browser_relay_state["control_lease"] = None
            return None
        return lease

    def _relay_control_snapshot() -> dict[str, Any]:
        lease = _relay_control_lease()
        interrupt = browser_relay_state.get("human_interrupt")
        interrupt = interrupt if isinstance(interrupt, dict) else None
        if interrupt:
            mode = "interrupted"
        elif lease:
            mode = "agent_active"
        else:
            mode = "idle"
        return {
            "schema": "octopus.browser_relay_control.v1",
            "mode": mode,
            "lease": lease,
            "human_interrupt": interrupt,
            "blocked": bool(interrupt),
            "pending_commands": len(browser_relay_state.get("pending_commands") or []),
        }

    def _record_relay_interrupt(
        *,
        reason: str,
        source: str,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        interrupt = {
            "schema": "octopus.browser_relay_human_interrupt.v1",
            "reason": reason,
            "source": source,
            "at": _now_ts(),
            "active_tab": _relay_active_tab_snapshot(),
            "detail": detail or {},
        }
        results = browser_relay_state.setdefault("command_results", {})
        for item in browser_relay_state.get("pending_commands") or []:
            command_id = str(item.get("id") or "").strip()
            if command_id:
                results[command_id] = {
                    "ok": False,
                    "id": command_id,
                    "error": f"browser relay interrupted: {reason}",
                    "control": {
                        "schema": "octopus.browser_relay_control.v1",
                        "mode": "interrupted",
                        "human_interrupt": interrupt,
                        "blocked": True,
                    },
                }
        active_lease = browser_relay_state.get("control_lease")
        if isinstance(active_lease, dict):
            command_id = str(active_lease.get("command_id") or "").strip()
            if command_id:
                results[command_id] = {
                    "ok": False,
                    "id": command_id,
                    "error": f"browser relay interrupted: {reason}",
                    "control": {
                        "schema": "octopus.browser_relay_control.v1",
                        "mode": "interrupted",
                        "human_interrupt": interrupt,
                        "blocked": True,
                    },
                }
        browser_relay_state["human_interrupt"] = interrupt
        browser_relay_state["control_lease"] = None
        browser_relay_state["pending_commands"] = []
        return interrupt

    def _clear_relay_interrupt() -> None:
        browser_relay_state["human_interrupt"] = None

    def _make_relay_lease(
        *,
        command_id: str,
        action: str,
        body: dict[str, Any],
        site_policy: dict[str, Any],
    ) -> dict[str, Any]:
        timeout_seconds = float(body.get("timeout_seconds") or 8)
        lease_seconds = float(body.get("lease_seconds") or max(5.0, timeout_seconds + 2.0))
        lease_seconds = max(3.0, min(60.0, lease_seconds))
        active_tab = _relay_active_tab_snapshot()
        return {
            "schema": "octopus.browser_relay_tab_lease.v1",
            "id": f"lease-{command_id}",
            "command_id": command_id,
            "owner": "agent",
            "action": action,
            "read_only": action in relay_read_only_actions,
            "issued_at": _now_ts(),
            "expires_at": _now_ts() + int(lease_seconds),
            "tab": active_tab,
            "require_same_tab": active_tab is not None,
            "require_same_url": bool(active_tab and active_tab.get("url")),
            "site_policy": site_policy,
        }

    def _resolve_browser_extension_path() -> Path:
        """Locate the companion browser-relay extension on disk.

        Search order:
          1. ``$OCTOPUS_BROWSER_EXTENSION_DIR`` — explicit override,
             takes precedence over everything else.
          2. ``$CWD/extensions/octopus-browser-relay`` — committed
             product surface (preferred).
          3. ``$CWD/.octopus-browser-relay`` — pre-2026-05 location;
             still resolved as a fallback for users who already had
             a local copy at the old path.
        If none exist, the **first non-override** candidate is created
        and returned (i.e. the new ``extensions/`` location).
        (Pre-2026-05 this list had a hard-coded ``E:/octopus/...``
        entry from one developer's local dev box · removed when we
        finally caught it in the repo scan.)
        """
        import os

        candidates: list[Path] = []
        env_override = os.environ.get("OCTOPUS_BROWSER_EXTENSION_DIR")
        if env_override:
            candidates.append(Path(env_override).expanduser())
        root = project_root()
        candidates.extend(
            [
                root / "extensions" / "octopus-browser-relay",
                root / ".octopus-browser-relay",
            ]
        )
        for candidate in candidates:
            if candidate.exists():
                return candidate
        # Default new layout for fresh checkouts.
        fallback = candidates[-2] if not env_override else candidates[1]
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback

    def _browser_version(executable: Path) -> str:
        # Windows: NEVER run `<browser>.exe --version`. Chromium-family
        # browsers on Windows don't honour --version as a CLI flag —
        # they actually *launch the browser window* and ignore the arg,
        # so calling this repeatedly on page mount spawned real
        # Chrome/Edge/Brave windows (users reported their machine
        # freezing under a blast of new tabs). Read the PE header
        # version resource instead — same answer, zero side effects.
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                size = ctypes.windll.version.GetFileVersionInfoSizeW(str(executable), None)
                if not size:
                    return ""
                buf = ctypes.create_string_buffer(size)
                if not ctypes.windll.version.GetFileVersionInfoW(str(executable), 0, size, buf):
                    return ""
                value = ctypes.c_void_p(0)
                value_size = wintypes.UINT(0)
                if not ctypes.windll.version.VerQueryValueW(
                    buf, r"\\", ctypes.byref(value), ctypes.byref(value_size)
                ):
                    return ""

                # VS_FIXEDFILEINFO layout — dwFileVersionMS / dwFileVersionLS
                class _FixedInfo(ctypes.Structure):
                    _fields_ = [
                        ("dwSignature", wintypes.DWORD),
                        ("dwStrucVersion", wintypes.DWORD),
                        ("dwFileVersionMS", wintypes.DWORD),
                        ("dwFileVersionLS", wintypes.DWORD),
                        ("dwProductVersionMS", wintypes.DWORD),
                        ("dwProductVersionLS", wintypes.DWORD),
                        ("dwFileFlagsMask", wintypes.DWORD),
                        ("dwFileFlags", wintypes.DWORD),
                        ("dwFileOS", wintypes.DWORD),
                        ("dwFileType", wintypes.DWORD),
                        ("dwFileSubtype", wintypes.DWORD),
                        ("dwFileDateMS", wintypes.DWORD),
                        ("dwFileDateLS", wintypes.DWORD),
                    ]

                info = ctypes.cast(value, ctypes.POINTER(_FixedInfo)).contents
                return (
                    f"{info.dwFileVersionMS >> 16}."
                    f"{info.dwFileVersionMS & 0xFFFF}."
                    f"{info.dwFileVersionLS >> 16}."
                    f"{info.dwFileVersionLS & 0xFFFF}"
                )
            except (OSError, ValueError, TypeError):
                return ""
        # POSIX: `--version` is safe and standard on Linux/macOS.
        try:
            completed = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                text=True,
                timeout=2,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return (completed.stdout or completed.stderr or "").strip()

    def _detect_browsers() -> list[dict[str, Any]]:
        candidates_by_browser = [
            (
                "chrome",
                "Google Chrome",
                [
                    "google-chrome",
                    "google-chrome-stable",
                    "chrome",
                    "chrome.exe",
                    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                    "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
                    "/usr/bin/google-chrome",
                    "/usr/bin/google-chrome-stable",
                    "/usr/bin/chromium",
                    "/usr/bin/chromium-browser",
                    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                ],
                True,
            ),
            (
                "edge",
                "Microsoft Edge",
                [
                    "microsoft-edge",
                    "microsoft-edge-stable",
                    "msedge.exe",
                    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                    "/usr/bin/microsoft-edge",
                    "/usr/bin/microsoft-edge-stable",
                    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                ],
                True,
            ),
            (
                "chromium",
                "Chromium",
                [
                    "chromium",
                    "chromium-browser",
                    "chromium.exe",
                    "/Applications/Chromium.app/Contents/MacOS/Chromium",
                    "/usr/bin/chromium",
                    "/usr/bin/chromium-browser",
                    r"C:\Program Files\Chromium\Application\chromium.exe",
                    r"C:\Program Files (x86)\Chromium\Application\chromium.exe",
                ],
                True,
            ),
            (
                "brave",
                "Brave",
                [
                    "brave",
                    "brave-browser",
                    "brave.exe",
                    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
                    "/usr/bin/brave-browser",
                    r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                    r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
                ],
                True,
            ),
            (
                "firefox",
                "Firefox",
                [
                    "firefox",
                    "firefox.exe",
                    "/Applications/Firefox.app/Contents/MacOS/firefox",
                    "/usr/bin/firefox",
                    r"C:\Program Files\Mozilla Firefox\firefox.exe",
                    r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
                ],
                False,
            ),
        ]
        seen: set[str] = set()
        browsers: list[dict[str, Any]] = []
        for name, display_name, candidates, chromium_based in candidates_by_browser:
            executable: Path | None = None
            for candidate in candidates:
                resolved = (
                    candidate
                    if Path(candidate).is_absolute() or "\\" in candidate or ":" in candidate
                    else shutil.which(candidate)
                )
                if not resolved:
                    continue
                candidate_path = Path(resolved)
                if candidate_path.exists():
                    executable = candidate_path
                    break
            if executable is None:
                continue
            normalized = str(executable).lower()
            if normalized in seen:
                continue
            seen.add(normalized)
            browsers.append(
                {
                    "name": name,
                    "display_name": display_name,
                    "version": _browser_version(executable),
                    "path": str(executable),
                    "chromium_based": chromium_based,
                    "cdp_supported": chromium_based,
                    "connection_modes": ["extension", "cdp"] if chromium_based else ["playwright"],
                }
            )
        return browsers

    def _playwright_runtime() -> Any | None:
        try:
            from playwright.sync_api import sync_playwright  # type: ignore[import-not-found]
        except ImportError:
            return None
        return sync_playwright

    def _browser_runtime_errors() -> tuple[type[BaseException], ...]:
        try:
            from playwright.sync_api import (  # type: ignore[import-not-found]
                Error as PlaywrightError,
            )
            from playwright.sync_api import (
                TimeoutError as PlaywrightTimeoutError,
            )
        except ImportError:
            return (OSError, ImportError, RuntimeError)
        return (OSError, ImportError, RuntimeError, PlaywrightError, PlaywrightTimeoutError)

    def _preferred_browser_executable() -> str | None:
        for browser in _detect_browsers():
            if bool(browser.get("chromium_based")):
                path = str(browser.get("path") or "")
                if path:
                    return path
        return None

    def _now_ts() -> int:
        return browser_session_center.now()

    def _session_project_id(session_id: str, body: dict[str, Any] | None = None) -> str:
        body = body or {}
        return str(
            body.get("project_id") or body.get("workspace_id") or body.get("owner_id") or session_id
        ).strip()

    def _session_profile_id(session_id: str, body: dict[str, Any] | None = None) -> str:
        body = body or {}
        return str(
            body.get("profile_id")
            or body.get("browser_profile_id")
            or _session_project_id(session_id, body)
            or session_id
        ).strip()

    def _browser_profile_dir(session: dict[str, Any]) -> Path:
        profile_id = str(session.get("profile_id") or session.get("session_id") or "default")
        root = Path("data/browser_sessions/profiles").resolve()
        profile_dir = (root / profile_id).resolve()
        if not str(profile_dir).startswith(str(root)):
            raise HTTPException(400, "invalid browser profile id")
        profile_dir.mkdir(parents=True, exist_ok=True)
        secure_profile_dir(profile_dir)
        session["profile_dir"] = str(profile_dir)
        return profile_dir

    def _ensure_browser_session(
        session_id: str,
        *,
        headless: bool | None = None,
        project_id: str | None = None,
        profile_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return browser_session_center.ensure(
                session_id,
                headless=headless,
                project_id=project_id,
                profile_id=profile_id,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    def _session_viewport(session: dict[str, Any]) -> tuple[int, int]:
        width = int(session.get("viewport_width") or browser_config_state["viewport_width"])
        height = int(session.get("viewport_height") or browser_config_state["viewport_height"])
        width = max(240, min(4096, width))
        height = max(160, min(4096, height))
        session["viewport_width"] = width
        session["viewport_height"] = height
        return width, height

    def _ensure_real_browser_session(session: dict[str, Any]) -> bool:
        if session.get("page") is not None:
            return True
        sync_playwright = _playwright_runtime()
        if sync_playwright is None:
            return False
        executable_path = _preferred_browser_executable()
        if not executable_path:
            return False
        playwright = None
        browser = None
        context = None
        page = None
        try:
            playwright = sync_playwright().start()
            profile_dir = _browser_profile_dir(session)
            session["recovered_from_crash"] = mark_session_active(profile_dir)
            viewport_width, viewport_height = _session_viewport(session)
            context = playwright.chromium.launch_persistent_context(
                user_data_dir=str(profile_dir),
                executable_path=executable_path,
                headless=bool(session.get("headless", True)),
                viewport={
                    "width": viewport_width,
                    "height": viewport_height,
                },
            )
            page = context.pages[0] if context.pages else context.new_page()
        except _browser_runtime_errors():
            with contextlib.suppress(Exception):
                if context is not None:
                    context.close()
            with contextlib.suppress(Exception):
                if browser is not None:
                    browser.close()
            with contextlib.suppress(Exception):
                if playwright is not None:
                    playwright.stop()
            # The sentinel was written before launch; a launch failure
            # here is NOT a crash to recover from. Clear it so the next
            # attempt doesn't falsely report recovered_from_crash (common
            # when the chromium profile is locked).
            mark_session_closed(session.get("profile_dir"))
            return False
        session["playwright"] = playwright
        session["browser"] = browser
        session["context"] = context
        session["page"] = page
        session["mode"] = "playwright"
        return True

    def _close_real_browser_session(session: dict[str, Any]) -> None:
        for key in ("page", "context", "browser"):
            resource = session.get(key)
            if resource is None:
                continue
            with contextlib.suppress(Exception):
                resource.close()
            session[key] = None
        playwright = session.get("playwright")
        if playwright is not None:
            with contextlib.suppress(Exception):
                playwright.stop()
            session["playwright"] = None
        mark_session_closed(session.get("profile_dir"))
        session["mode"] = "mock"

    def _record_browser_action(
        session: dict[str, Any],
        action: str,
        detail: str,
        *,
        status: str = "ok",
        error: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        browser_session_center.record_action(
            session,
            action,
            detail,
            status=status,
            error=error,
            metadata=metadata,
        )

    def _queue_browser_replay_case(
        replay_case: dict[str, Any],
        *,
        reason: str = "",
        priority: str = "",
    ) -> dict[str, Any]:
        session_id = str(replay_case.get("session_id") or "default")
        health = replay_case.get("health")
        health = health if isinstance(health, dict) else {}
        last_action = replay_case.get("last_action")
        last_action = last_action if isinstance(last_action, dict) else {}
        issues = health.get("issues") if isinstance(health.get("issues"), list) else []
        failed = str(last_action.get("status") or "") == "failed"
        chosen_priority = priority or ("P0" if failed or not health.get("healthy") else "P1")
        action_name = str(last_action.get("action") or "no action")
        action_detail = str(last_action.get("detail") or "")
        issue_text = ", ".join(str(issue) for issue in issues) or "none"
        case_id = str(replay_case.get("case_id") or "")
        fingerprint = str(replay_case.get("fingerprint") or "")
        text = (
            f"Browser session `{session_id}` replay case `{case_id}` captured for operator review.\n"
            f"Last action: {action_name} {action_detail}".strip()
            + f"\nHealth score: {health.get('score', 0)}; issues: {issue_text}."
        )
        if reason:
            text += f"\nReason: {reason[:500]}"
        queue = ReviewQueue(app_paths().review_queue_path)
        return queue.upsert_item(
            source="browser_session_replay",
            source_kind="browser_desktop_replay",
            candidate_kind="browser_session_replay_case",
            priority=chosen_priority,
            target_bucket="browser_desktop_replay",
            title=f"Review browser replay case: {session_id}",
            text=text,
            metadata={
                "schema": replay_case.get("schema"),
                "case_id": case_id,
                "fingerprint": fingerprint,
                "session_id": session_id,
                "replay_ready": bool(replay_case.get("replay_ready")),
                "health": health,
                "last_action": last_action,
                "action_count": replay_case.get("action_count"),
            },
            tags=[
                "browser",
                "desktop",
                "replay_case",
                "review_queue",
                "operator_review",
            ],
        )

    def _browser_replay_evidence(
        session_id: str,
        session: dict[str, Any],
        *,
        limit: int = 100,
    ) -> dict[str, Any]:
        actions = [
            action
            for action in list(session.get("actions", []))[-limit:]
            if isinstance(action, dict)
        ]
        health = browser_session_center.health_report(session_id, limit=min(limit, 100))
        identity = browser_session_replay_identity(
            session_id=session_id,
            actions=actions,
            health=health,
        )
        return {
            "schema": "octopus.browser_replay_evidence_hint.v1",
            "case_id": identity["case_id"],
            "fingerprint": identity["fingerprint"],
            "replay_ready": bool(actions),
            "replay_case_url": f"/api/browser/session/replay-case?session_id={session_id}",
            "queue_url": "/api/browser/session/replay-case/queue",
            "queue_body": {"session_id": session_id},
        }

    def _page_title_for_url(url: str) -> str:
        # SSRF + DNS-rebinding guard. ``safe_urlopen`` resolves once
        # and pins the connect target to the approved IP so a hostile
        # DNS can't swap in an internal address between check and
        # fetch.
        try:
            from runtime.safety.auth.url_guard import safe_urlopen
        except Exception:  # noqa: BLE001 — best-effort; fail-open
            return url
        try:
            raw, headers = safe_urlopen(
                url,
                timeout=5.0,
                read_cap_bytes=32768,
                allow_private=False,
            )
        except (ValueError, urllib.error.URLError, TimeoutError, OSError):
            return url
        content_type = headers.get("Content-Type", "")
        # safe_urlopen stripped the charset hint from the original
        # HTTPResponse; fall back to UTF-8.
        text = raw.decode("utf-8", errors="replace")
        lower = text.lower()
        start = lower.find("<title>")
        end = lower.find("</title>")
        if start != -1 and end != -1 and end > start:
            return text[start + 7 : end].strip()
        if "text/plain" in content_type:
            return url
        return url

    def _navigate_browser_session(session: dict[str, Any], url: str) -> dict[str, str]:
        if _ensure_real_browser_session(session):
            page = session.get("page")
            if page is not None:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=10_000)
                    title = page.title()
                    final_url = page.url
                    history = list(session.get("history", []))
                    history_index = int(session.get("history_index", -1))
                    if history_index + 1 < len(history):
                        history = history[: history_index + 1]
                    history.append({"url": final_url, "title": title})
                    session["history"] = history
                    session["history_index"] = len(history) - 1
                    session["current_url"] = final_url
                    session["current_title"] = title
                    _record_browser_action(session, "navigate", final_url)
                    return {"url": final_url, "title": title}
                except _browser_runtime_errors():
                    _close_real_browser_session(session)
        title = _page_title_for_url(url)
        history = list(session.get("history", []))
        history_index = int(session.get("history_index", -1))
        if history_index + 1 < len(history):
            history = history[: history_index + 1]
        history.append({"url": url, "title": title})
        session["history"] = history
        session["history_index"] = len(history) - 1
        session["current_url"] = url
        session["current_title"] = title
        _record_browser_action(session, "navigate", url)
        return {"url": url, "title": title}

    def _move_browser_history(session: dict[str, Any], delta: int) -> dict[str, str]:
        if _ensure_real_browser_session(session):
            page = session.get("page")
            if page is not None:
                try:
                    if delta < 0:
                        page.go_back(wait_until="domcontentloaded", timeout=10_000)
                    else:
                        page.go_forward(wait_until="domcontentloaded", timeout=10_000)
                    session["current_url"] = page.url
                    session["current_title"] = page.title()
                    action_name = "back" if delta < 0 else "forward"
                    _record_browser_action(session, action_name, session["current_url"])
                    return {"url": session["current_url"], "title": session["current_title"]}
                except _browser_runtime_errors():
                    _close_real_browser_session(session)
        history = list(session.get("history", []))
        if not history:
            return {"url": "", "title": ""}
        current_index = int(session.get("history_index", len(history) - 1))
        target_index = max(0, min(len(history) - 1, current_index + delta))
        entry = history[target_index]
        session["history_index"] = target_index
        session["current_url"] = str(entry.get("url") or "")
        session["current_title"] = str(entry.get("title") or "")
        action_name = "back" if delta < 0 else "forward"
        _record_browser_action(session, action_name, session["current_url"])
        return {"url": session["current_url"], "title": session["current_title"]}

    def _reload_browser_session(session: dict[str, Any]) -> dict[str, str]:
        if _ensure_real_browser_session(session):
            page = session.get("page")
            if page is not None:
                try:
                    page.reload(wait_until="domcontentloaded", timeout=10_000)
                    session["current_url"] = page.url
                    session["current_title"] = page.title()
                    _record_browser_action(session, "reload", session["current_url"])
                    return {"url": session["current_url"], "title": session["current_title"]}
                except _browser_runtime_errors():
                    _close_real_browser_session(session)
        url = str(session.get("current_url") or "")
        if not url:
            return {"url": "", "title": ""}
        title = _page_title_for_url(url)
        session["current_title"] = title
        history = list(session.get("history", []))
        index = int(session.get("history_index", -1))
        if 0 <= index < len(history):
            history[index] = {"url": url, "title": title}
            session["history"] = history
        _record_browser_action(session, "reload", url)
        return {"url": url, "title": title}

    def _browser_screenshot_payload(session: dict[str, Any]) -> dict[str, Any]:
        width, height = _session_viewport(session)
        if _ensure_real_browser_session(session):
            page = session.get("page")
            if page is not None:
                try:
                    image = page.screenshot(full_page=True, type="png")
                    return {
                        "base64": base64.b64encode(image).decode("ascii"),
                        "width": width,
                        "height": height,
                    }
                except _browser_runtime_errors():
                    _close_real_browser_session(session)
        title = html.escape(str(session.get("current_title") or "Octopus Browser Session"))
        url = html.escape(
            str(session.get("current_url") or "Navigate to a URL to start browser automation")
        )
        action_count = int(session.get("action_count", 0))
        svg = f"""
<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
  <defs>
    <linearGradient id="bg" x1="0" x2="1" y1="0" y2="1">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="100%" stop-color="#1e293b" />
    </linearGradient>
  </defs>
  <rect width="{width}" height="{height}" fill="url(#bg)" />
  <rect x="40" y="36" width="{width - 80}" height="{height - 72}" rx="24" fill="#f8fafc" opacity="0.96" />
  <rect x="72" y="78" width="{width - 144}" height="52" rx="16" fill="#e2e8f0" />
  <circle cx="96" cy="104" r="8" fill="#ef4444" />
  <circle cx="124" cy="104" r="8" fill="#f59e0b" />
  <circle cx="152" cy="104" r="8" fill="#22c55e" />
  <text x="188" y="111" fill="#334155" font-size="20" font-family="Segoe UI, Arial, sans-serif">{url}</text>
  <text x="88" y="204" fill="#0f172a" font-size="34" font-weight="700" font-family="Segoe UI, Arial, sans-serif">{title}</text>
  <text x="88" y="254" fill="#475569" font-size="22" font-family="Segoe UI, Arial, sans-serif">Interactive preview placeholder rendered by the compatibility backend.</text>
  <text x="88" y="292" fill="#475569" font-size="22" font-family="Segoe UI, Arial, sans-serif">Actions recorded: {action_count}</text>
  <text x="88" y="330" fill="#475569" font-size="22" font-family="Segoe UI, Arial, sans-serif">Session: {html.escape(str(session.get("session_id") or ""))}</text>
</svg>
""".strip()
        return {
            "base64": base64.b64encode(svg.encode("utf-8")).decode("ascii"),
            "width": width,
            "height": height,
        }

    # ─── Filesystem helpers for desktop workspace pages ───────────────
    @router.get("/api/browser/system-info")
    def api_browser_system_info() -> dict[str, Any]:
        system = {
            "os": platform.system(),
            "os_version": platform.version(),
            "os_release": platform.release(),
            "architecture": platform.machine() or platform.architecture()[0],
            "python_version": sys.version.split()[0],
        }
        return {"system": system, "browsers": _detect_browsers()}

    @router.post("/api/browser/launch")
    def api_browser_launch(body: dict[str, Any]) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "").strip()
        if not session_id:
            raise HTTPException(400, "session_id is required")
        session = _ensure_browser_session(
            session_id,
            headless=bool(body.get("headless", browser_config_state["headless"])),
            project_id=_session_project_id(session_id, body),
            profile_id=_session_profile_id(session_id, body),
        )
        browser_session_center.update_settings(session, body)
        return {"status": "launched", "session": browser_session_center.snapshot(session)}

    @router.get("/api/browser/session/status")
    def api_browser_session_status(session_id: str = Query(default="default")) -> dict[str, Any]:
        try:
            session = browser_session_center.get(session_id)
            snapshot = (
                browser_session_center.snapshot(session)
                if session is not None
                else browser_session_center.missing_snapshot(session_id)
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"exists": session is not None, "session": snapshot}

    @router.get("/api/browser/session/health")
    def api_browser_session_health(
        session_id: str = Query(default="default"),
        limit: int = Query(default=10, ge=1, le=100),
    ) -> dict[str, Any]:
        try:
            return browser_session_center.health_report(session_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/browser/session/ensure")
    def api_browser_session_ensure(body: dict[str, Any]) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "default").strip()
        session = _ensure_browser_session(
            session_id,
            headless=body.get("headless") if "headless" in body else None,
            project_id=_session_project_id(session_id, body),
            profile_id=_session_profile_id(session_id, body),
        )
        browser_session_center.update_settings(session, body)
        return {"status": "ready", "session": browser_session_center.snapshot(session)}

    @router.post("/api/browser/session/viewport")
    def api_browser_session_viewport(body: dict[str, Any]) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "default").strip()
        if not session_id:
            raise HTTPException(400, "session_id is required")
        session = _ensure_browser_session(
            session_id,
            headless=body.get("headless") if "headless" in body else None,
            project_id=_session_project_id(session_id, body),
            profile_id=_session_profile_id(session_id, body),
        )
        browser_session_center.update_settings(
            session,
            {
                "viewport_width": body.get("width", body.get("viewport_width")),
                "viewport_height": body.get("height", body.get("viewport_height")),
            },
        )
        width, height = _session_viewport(session)
        page = session.get("page")
        if page is not None:
            try:
                page.set_viewport_size({"width": width, "height": height})
            except _browser_runtime_errors() as exc:
                _record_browser_action(
                    session,
                    "viewport",
                    f"{width}x{height}",
                    status="failed",
                    error=str(exc),
                    metadata={"width": width, "height": height},
                )
                raise HTTPException(500, f"browser viewport update failed: {exc}") from exc
        _record_browser_action(
            session,
            "viewport",
            f"{width}x{height}",
            metadata={"width": width, "height": height},
        )
        return {
            "ok": True,
            "session": browser_session_center.snapshot(session),
        }

    @router.post("/api/browser/session/reset")
    def api_browser_session_reset(body: dict[str, Any]) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "default").strip()
        if not session_id:
            raise HTTPException(400, "session_id is required")
        session = browser_session_center.pop(session_id)
        if session is not None:
            _close_real_browser_session(session)
        relaunch = bool(body.get("relaunch", False))
        if relaunch:
            session = _ensure_browser_session(
                session_id,
                headless=body.get("headless") if "headless" in body else None,
                project_id=_session_project_id(session_id, body),
                profile_id=_session_profile_id(session_id, body),
            )
            browser_session_center.update_settings(session, body)
            return {
                "ok": True,
                "status": "ready",
                "session": browser_session_center.snapshot(session),
            }
        return {
            "ok": True,
            "status": "closed",
            "session": browser_session_center.missing_snapshot(session_id),
        }

    @router.post("/api/browser/navigate")
    def api_browser_navigate(body: dict[str, Any]) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "").strip()
        url = str(body.get("url") or "").strip()
        if not session_id:
            raise HTTPException(400, "session_id is required")
        if not url:
            raise HTTPException(400, "url is required")
        session = _ensure_browser_session(
            session_id,
            project_id=_session_project_id(session_id, body),
            profile_id=_session_profile_id(session_id, body),
        )
        return _navigate_browser_session(session, url)

    @router.post("/api/browser/action")
    def api_browser_action(body: dict[str, Any]) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "").strip()
        action = str(body.get("action") or "").strip()
        if not session_id:
            raise HTTPException(400, "session_id is required")
        if not action:
            raise HTTPException(400, "action is required")
        session = browser_sessions.get(session_id)
        if session is None:
            raise HTTPException(404, f"browser session not found: {session_id}")
        if action == "back":
            return _move_browser_history(session, -1)
        if action == "forward":
            return _move_browser_history(session, 1)
        if action == "reload":
            return _reload_browser_session(session)
        if _ensure_real_browser_session(session):
            page = session.get("page")
            if page is not None:
                try:
                    if action == "click":
                        selector = str(body.get("selector") or "").strip()
                        if not selector:
                            raise HTTPException(400, "selector is required for click")
                        page.click(selector, timeout=10_000)
                    elif action == "type":
                        selector = str(body.get("selector") or "").strip()
                        text = str(body.get("text") or "")
                        if not selector:
                            raise HTTPException(400, "selector is required for type")
                        page.fill(selector, text, timeout=10_000)
                    elif action == "hover":
                        selector = str(body.get("selector") or "").strip()
                        if not selector:
                            raise HTTPException(400, "selector is required for hover")
                        page.hover(selector, timeout=10_000)
                    elif action == "click_at":
                        try:
                            x = int(body.get("x"))
                            y = int(body.get("y"))
                        except (TypeError, ValueError) as exc:
                            raise HTTPException(400, "x and y are required for click_at") from exc
                        page.mouse.click(x, y)
                    elif action == "double_click_at":
                        try:
                            x = int(body.get("x"))
                            y = int(body.get("y"))
                        except (TypeError, ValueError) as exc:
                            raise HTTPException(
                                400, "x and y are required for double_click_at"
                            ) from exc
                        page.mouse.dblclick(x, y)
                    elif action == "wait":
                        selector = str(body.get("selector") or "").strip()
                        timeout = int(body.get("timeout") or 10_000)
                        if not selector:
                            raise HTTPException(400, "selector is required for wait")
                        page.wait_for_selector(selector, timeout=timeout)
                    elif action == "press":
                        key = str(body.get("key") or "Enter")
                        page.keyboard.press(key)
                    elif action == "scroll":
                        selector = str(body.get("selector") or "").strip()
                        y_value = body.get("y", body.get("deltaY"))
                        if selector:
                            page.locator(selector).scroll_into_view_if_needed(timeout=10_000)
                        elif y_value is not None:
                            page.evaluate(f"window.scrollBy(0, {int(y_value)})")
                        else:
                            raise HTTPException(400, "selector or y is required for scroll")
                    elif action == "aria":
                        text = ""
                        try:
                            text = page.locator("body").inner_text(timeout=5000)
                        except _browser_runtime_errors():
                            text = ""
                        snapshot = {
                            "role": "document",
                            "name": page.title(),
                            "url": page.url,
                            "text": text[:5000],
                            "truncated": len(text) > 5000,
                        }
                        session["current_url"] = page.url
                        session["current_title"] = page.title()
                        _record_browser_action(session, action, "page semantic snapshot")
                        return {
                            "ok": True,
                            "url": str(session.get("current_url") or ""),
                            "title": str(session.get("current_title") or ""),
                            "nodes": snapshot,
                        }
                    else:
                        raise HTTPException(400, f"unsupported browser action: {action}")
                    session["current_url"] = page.url
                    session["current_title"] = page.title()
                    detail = str(
                        body.get("selector")
                        or body.get("text")
                        or body.get("y")
                        or (
                            f"{body.get('x')},{body.get('y')}"
                            if body.get("x") is not None and body.get("y") is not None
                            else action
                        )
                    )
                    _record_browser_action(session, action, detail)
                    return {
                        "ok": True,
                        "url": str(session.get("current_url") or ""),
                        "title": str(session.get("current_title") or ""),
                    }
                except HTTPException:
                    raise
                except _browser_runtime_errors() as exc:
                    _record_browser_action(
                        session,
                        action,
                        str(body.get("selector") or body.get("text") or body.get("y") or action),
                        status="failed",
                        error=str(exc),
                    )
                    raise HTTPException(
                        status_code=500,
                        detail={
                            "error": f"browser action failed: {exc}",
                            "replay_evidence": _browser_replay_evidence(session_id, session),
                        },
                    ) from exc
        detail = str(
            body.get("selector")
            or body.get("text")
            or (
                f"{body.get('x')},{body.get('y')}"
                if body.get("x") is not None and body.get("y") is not None
                else action
            )
        )
        _record_browser_action(session, action, detail)
        return {
            "ok": True,
            "url": str(session.get("current_url") or ""),
            "title": str(session.get("current_title") or ""),
        }

    @router.get("/api/browser/screenshot/base64")
    def api_browser_screenshot_base64(session_id: str) -> dict[str, Any]:
        session = browser_sessions.get(session_id)
        if session is None:
            raise HTTPException(404, f"browser session not found: {session_id}")
        _record_browser_action(session, "screenshot", str(session.get("current_url") or ""))
        return _browser_screenshot_payload(session)

    @router.get("/api/browser/page-info")
    def api_browser_page_info(session_id: str) -> dict[str, Any]:
        session = browser_sessions.get(session_id)
        if session is None:
            raise HTTPException(404, f"browser session not found: {session_id}")
        return {
            "url": str(session.get("current_url") or ""),
            "title": str(session.get("current_title") or ""),
        }

    @router.get("/api/browser/extract-text")
    def api_browser_extract_text(session_id: str) -> dict[str, Any]:
        session = browser_sessions.get(session_id)
        if session is None:
            raise HTTPException(404, f"browser session not found: {session_id}")
        url = str(session.get("current_url") or "")
        title = str(session.get("current_title") or "")
        text = ""
        if _ensure_real_browser_session(session):
            page = session.get("page")
            if page is not None:
                try:
                    url = page.url
                    title = page.title()
                    text = page.locator("body").inner_text(timeout=5_000)
                    session["current_url"] = url
                    session["current_title"] = title
                except _browser_runtime_errors():
                    text = ""
        if not text and url:
            # SSRF + rebinding-proof fetch.
            try:
                from runtime.safety.auth.url_guard import safe_urlopen

                raw, _headers = safe_urlopen(
                    url,
                    timeout=8.0,
                    read_cap_bytes=256_000,
                    allow_private=False,
                )
                html_text = raw.decode("utf-8", errors="replace")
                text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_text)
                text = re.sub(r"(?s)<[^>]+>", " ", text)
                text = html.unescape(re.sub(r"\s+", " ", text)).strip()
            except (ValueError, urllib.error.URLError, TimeoutError, OSError):
                text = ""
        _record_browser_action(session, "extract", url)
        max_chars = 20_000
        return {
            "url": url,
            "title": title,
            "text": text[:max_chars],
            "truncated": len(text) > max_chars,
            "textLength": len(text),
        }

    @router.get("/api/browser/sessions")
    def api_browser_sessions() -> dict[str, Any]:
        sessions = browser_session_center.list_snapshots()
        return {"sessions": sessions, "count": len(sessions)}

    @router.get("/api/browser/action-log")
    def api_browser_action_log(
        session_id: str,
        limit: int = Query(default=50, ge=1, le=500),
    ) -> dict[str, Any]:
        session = browser_sessions.get(session_id)
        if session is None:
            raise HTTPException(404, f"browser session not found: {session_id}")
        actions = list(session.get("actions", []))[-limit:]
        return {"actions": actions}

    @router.get("/api/browser/session/replay-case")
    def api_browser_session_replay_case(
        session_id: str,
        limit: int = Query(default=100, ge=1, le=500),
    ) -> dict[str, Any]:
        session = browser_sessions.get(session_id)
        if session is None:
            raise HTTPException(404, f"browser session not found: {session_id}")
        actions = list(session.get("actions", []))[-limit:]
        health = browser_session_center.health_report(session_id, limit=min(limit, 100))
        identity = browser_session_replay_identity(
            session_id=session_id,
            actions=[action for action in actions if isinstance(action, dict)],
            health=health,
        )
        return {
            "schema": "octopus.browser_session_replay_case.v1",
            "case_id": identity["case_id"],
            "fingerprint": identity["fingerprint"],
            "session_id": session_id,
            "replay_ready": bool(actions),
            "health": health,
            "session": browser_session_center.snapshot(session),
            "actions": actions,
            "action_count": len(actions),
            "last_action": actions[-1] if actions else None,
        }

    @router.post("/api/browser/session/replay-case/queue")
    def api_browser_session_replay_case_queue(body: dict[str, Any]) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "default").strip()
        if not session_id:
            raise HTTPException(400, "session_id is required")
        limit = int(body.get("limit") or 100)
        limit = max(1, min(500, limit))
        replay_case = api_browser_session_replay_case(session_id=session_id, limit=limit)
        if not replay_case.get("replay_ready"):
            raise HTTPException(409, "browser replay case has no actions to review")
        queued = _queue_browser_replay_case(
            replay_case,
            reason=str(body.get("reason") or ""),
            priority=str(body.get("priority") or ""),
        )
        return {
            "ok": True,
            "schema": "octopus.browser_session_replay_case_queue.v1",
            "replay_case": replay_case,
            "queue": queued,
        }

    @router.post("/api/browser/close")
    def api_browser_close(body: dict[str, Any]) -> dict[str, Any]:
        session_id = str(body.get("session_id") or "").strip()
        if not session_id:
            raise HTTPException(400, "session_id is required")
        session = browser_session_center.pop(session_id)
        if session is not None:
            _close_real_browser_session(session)
        return {"ok": True}

    @router.get("/api/browser/config")
    def api_browser_config() -> dict[str, Any]:
        return browser_config_state

    @router.put("/api/browser/config")
    def api_browser_config_update(body: dict[str, Any]) -> dict[str, Any]:
        allowed_modes = {"playwright", "extension", "cdp"}
        persist_policy = False
        for key in (
            "max_open_tabs",
            "max_saved_tabs",
            "cdp_port",
            "viewport_width",
            "viewport_height",
        ):
            if key in body:
                try:
                    browser_config_state[key] = int(body[key])
                except (TypeError, ValueError) as exc:
                    raise HTTPException(400, f"{key} must be an integer") from exc
        if "connection_mode" in body:
            mode = str(body["connection_mode"])
            if mode not in allowed_modes:
                raise HTTPException(
                    400, "connection_mode must be one of playwright, extension, cdp"
                )
            browser_config_state["connection_mode"] = mode
        if "headless" in body:
            browser_config_state["headless"] = bool(body["headless"])
        if "relay_allowed_hosts" in body:
            browser_config_state["relay_allowed_hosts"] = _normalize_relay_host_patterns(
                body.get("relay_allowed_hosts"),
            )
            persist_policy = True
        if "relay_blocked_hosts" in body:
            browser_config_state["relay_blocked_hosts"] = _normalize_relay_host_patterns(
                body.get("relay_blocked_hosts"),
            )
            persist_policy = True
        if "relay_require_allowlist" in body:
            browser_config_state["relay_require_allowlist"] = bool(
                body.get("relay_require_allowlist"),
            )
            persist_policy = True
        if persist_policy:
            _persist_browser_policy()
        return browser_config_state

    @router.get("/api/browser/relay/status")
    def api_browser_relay_status() -> dict[str, Any]:
        extension_path = _resolve_browser_extension_path()
        manifest = extension_path / "manifest.json"
        last_seen = int(browser_relay_state.get("last_seen") or 0)
        connected = bool(manifest.exists() and last_seen and (_now_ts() - last_seen) <= 15)
        browser_relay_state["connected"] = connected
        return {
            "connected": connected,
            "extension_version": str(
                browser_relay_state.get("extension_version")
                or ("local-dev" if manifest.exists() else "")
            ),
            "pending_commands": len(browser_relay_state.get("pending_commands") or []),
            "last_seen": last_seen,
            "active_tab": browser_relay_state.get("active_tab"),
            "extension_path": str(extension_path),
            "manifest_exists": manifest.exists(),
            "site_policy": _relay_policy_snapshot(),
            "control": _relay_control_snapshot(),
        }

    @router.post("/api/browser/relay/heartbeat")
    def api_browser_relay_heartbeat(body: dict[str, Any]) -> dict[str, Any]:
        pending = _apply_relay_heartbeat(body)
        return {
            "ok": True,
            "pending_commands": len(pending),
            "commands": pending,
            "control": _relay_control_snapshot(),
        }

    @router.websocket("/api/browser/relay/ws")
    async def api_browser_relay_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        browser_relay_state["connected"] = True
        browser_relay_state["last_seen"] = _now_ts()
        last_keepalive = time.monotonic()
        try:
            while True:
                message: Any = None
                with contextlib.suppress(TimeoutError):
                    message = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=0.1,
                    )

                if isinstance(message, dict):
                    message_type = str(message.get("type") or "")
                    if message_type == "heartbeat":
                        pending = _apply_relay_heartbeat(message)
                        if pending:
                            await websocket.send_json({"type": "commands", "commands": pending})
                    elif message_type == "result":
                        try:
                            _apply_relay_result(message)
                        except ValueError as exc:
                            await websocket.send_json({"type": "error", "error": str(exc)})

                # Commands can be enqueued by a concurrent HTTP request while
                # no extension message is arriving. Drain them immediately so
                # delivery no longer depends on an MV3 JavaScript timer.
                pending = _drain_relay_commands()
                if pending:
                    await websocket.send_json({"type": "commands", "commands": pending})

                # Chrome 116+ keeps an extension service worker alive when a
                # WebSocket exchanges traffic inside the 30-second window.
                now = time.monotonic()
                if now - last_keepalive >= 15:
                    await websocket.send_json({"type": "ping", "at": _now_ts()})
                    last_keepalive = now
        except WebSocketDisconnect:
            pass

    @router.post("/api/browser/relay/control")
    def api_browser_relay_control(body: dict[str, Any]) -> dict[str, Any]:
        action = str(body.get("action") or "").strip()
        if action in {"stop", "interrupt"}:
            interrupt = _record_relay_interrupt(
                reason=str(body.get("reason") or "operator_stop"),
                source=str(body.get("source") or "side_panel"),
                detail={"active_tab": _relay_active_tab_snapshot()},
            )
            return {"ok": True, "interrupt": interrupt, "control": _relay_control_snapshot()}
        if action in {"resume", "clear_interrupt"}:
            _clear_relay_interrupt()
            return {"ok": True, "control": _relay_control_snapshot()}
        if action == "status":
            return {"ok": True, "control": _relay_control_snapshot()}
        raise HTTPException(400, "action must be one of stop, interrupt, resume, clear_interrupt")

    @router.post("/api/browser/relay/command")
    def api_browser_relay_command(body: dict[str, Any]) -> dict[str, Any]:
        last_seen = int(browser_relay_state.get("last_seen") or 0)
        if not last_seen or (_now_ts() - last_seen) > 15:
            raise HTTPException(409, "browser relay extension is not connected")
        action = str(body.get("action") or "").strip()
        if not action:
            raise HTTPException(400, "action is required")
        control = _relay_control_snapshot()
        if control["blocked"]:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "browser relay paused by human interrupt",
                    "control": control,
                },
            )
        active_lease = _relay_control_lease()
        if active_lease:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "browser relay tab lease is already active",
                    "control": _relay_control_snapshot(),
                },
            )
        site_policy = _relay_site_policy_decision(action, body)
        if site_policy["decision"] == "block":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "browser relay site policy blocked command",
                    "site_policy": site_policy,
                },
            )
        command_id = str(uuid.uuid4())
        lease = _make_relay_lease(
            command_id=command_id,
            action=action,
            body=body,
            site_policy=site_policy,
        )
        command = {
            "id": command_id,
            "action": action,
            "params": {k: v for k, v in body.items() if k not in {"id", "action"}},
            "site_policy": site_policy,
            "lease": lease,
            "created_at": _now_ts(),
        }
        browser_relay_state["control_lease"] = lease
        with browser_relay_queue_lock:
            pending = list(browser_relay_state.get("pending_commands") or [])
            pending.append(command)
            browser_relay_state["pending_commands"] = pending

        deadline = time.time() + float(body.get("timeout_seconds") or 8)
        results = browser_relay_state.setdefault("command_results", {})
        while time.time() < deadline:
            result = results.pop(command_id, None)
            if result is not None:
                if (browser_relay_state.get("control_lease") or {}).get("command_id") == command_id:
                    browser_relay_state["control_lease"] = None
                if result.get("ok") is False:
                    raise HTTPException(500, str(result.get("error") or "relay command failed"))
                result.setdefault("site_policy", site_policy)
                result["control"] = _relay_control_snapshot()
                return result
            time.sleep(0.1)

        with browser_relay_queue_lock:
            browser_relay_state["pending_commands"] = [
                item
                for item in (browser_relay_state.get("pending_commands") or [])
                if item.get("id") != command_id
            ]
        if (browser_relay_state.get("control_lease") or {}).get("command_id") == command_id:
            browser_relay_state["control_lease"] = None
        raise HTTPException(504, "browser relay command timed out")

    @router.post("/api/browser/relay/result")
    def api_browser_relay_result(body: dict[str, Any]) -> dict[str, Any]:
        try:
            _apply_relay_result(body)
        except ValueError:
            raise HTTPException(400, "id is required") from None
        return {"ok": True}

    @router.get("/api/browser/relay/bookmarklet.js")
    def api_browser_relay_bookmarklet_js() -> Any:
        script_path = _resolve_browser_extension_path() / "bookmarklet.js"
        if not script_path.exists():
            raise HTTPException(404, "bookmarklet relay script not found")
        return FileResponse(script_path, media_type="application/javascript")

    @router.get("/api/browser/relay/bookmarklet-poll")
    def api_browser_relay_bookmarklet_poll(
        callback: str = Query(""),
        version: str = Query("bookmarklet"),
        url: str = Query(""),
        title: str = Query(""),
    ) -> Response:
        if not re.fullmatch(r"[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*", callback):
            raise HTTPException(400, "invalid callback")
        browser_relay_state["connected"] = True
        browser_relay_state["last_seen"] = _now_ts()
        browser_relay_state["extension_version"] = version or "bookmarklet"
        browser_relay_state["active_tab"] = {
            "id": "bookmarklet",
            "url": url,
            "title": title,
        }
        pending = list(browser_relay_state.get("pending_commands") or [])
        browser_relay_state["pending_commands"] = []
        payload = {
            "ok": True,
            "pending_commands": len(pending),
            "commands": pending,
        }
        return Response(
            f"{callback}({json.dumps(payload, ensure_ascii=False)});",
            media_type="application/javascript",
        )

    @router.post("/api/browser/relay/bookmarklet-result")
    async def api_browser_relay_bookmarklet_result(request: Request) -> dict[str, Any]:
        raw = await request.body()
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
            raise HTTPException(400, "invalid relay result") from exc
        if not isinstance(body, dict):
            raise HTTPException(400, "invalid relay result")
        return api_browser_relay_result(body)

    @router.post("/api/browser/open-extension-folder")
    def api_browser_open_extension_folder() -> dict[str, Any]:
        extension_path = _resolve_browser_extension_path()
        try:
            if os.name == "nt":
                os.startfile(str(extension_path))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                # macOS has no xdg-open; the file opener is `open`.
                subprocess.Popen(["open", str(extension_path)])
            else:
                subprocess.Popen(["xdg-open", str(extension_path)])
        except (OSError, ValueError):  # noqa: BLE001 — browser session cleanup; best-effort
            pass
        return {"opened": True, "path": str(extension_path)}

    @router.get("/api/browser/extension-path")
    def api_browser_extension_path() -> dict[str, Any]:
        extension_path = _resolve_browser_extension_path()
        return {"path": str(extension_path), "exists": extension_path.exists()}

    @router.get("/api/browser-artifacts/{filename}")
    def serve_browser_artifact(filename: str) -> Any:
        """Serve a browser screenshot saved by ``live_browser_screenshot``.

        Files land in ``data/browser_artifacts/<filename>``. Only ``.png``
        files are served (screenshots only); directory traversal is
        blocked by the simple name check.
        """
        from fastapi import HTTPException
        from fastapi.responses import FileResponse

        from runtime.execution.suckers.browser_act_skills import (
            _artifacts_root,
        )

        # Prevent path traversal
        clean = Path(filename).name
        if not clean.endswith(".png") or "/" in filename or "\\" in filename:
            raise HTTPException(404, "not found")
        fpath = _artifacts_root() / clean
        if not fpath.is_file():
            raise HTTPException(404, "artifact not found")
        return FileResponse(str(fpath), media_type="image/png")

    return router
