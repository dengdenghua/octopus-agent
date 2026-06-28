from __future__ import annotations

import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from runtime.safety.evolution.browser_desktop_quality import (
    compute_browser_desktop_quality,
)
from runtime.safety.evolution.browser_desktop_runtime_readiness import (
    compute_browser_desktop_runtime_readiness,
)

SCHEMA = "octopus.browser_desktop_runtime_probe.v1"
PROBE_PAGE_URL = (
    "data:text/html;charset=utf-8,"
    "%3C!doctype%20html%3E%3Ctitle%3EOctopus%20runtime%20probe%3C/title%3E"
    "%3Cmain%3Ebrowser%20desktop%20runtime%20probe%3C/main%3E"
)


def run_browser_desktop_runtime_probe(
    *,
    api_base_url: str = "http://127.0.0.1:8000",
    session_id: str | None = None,
    timeout_s: float = 5.0,
    queue_browser_replay: bool = False,
    bearer_token: str = "",
    auto_local_auth: bool = False,
    local_auth_username: str = "runtime-probe",
    local_auth_password: str = "",
    real_chrome_relay: bool = False,
    open_real_chrome_relay: bool = False,
    cleanup_session: bool = True,
    persist_evidence: bool | None = None,
    evidence_path: str | Path | None = None,
    review_queue_path: str | Path | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    """Exercise the local browser/desktop automation health surface.

    The probe intentionally avoids desktop clicks and keyboard input. It only
    creates a headless browser session, records a safe navigation/action, reads
    Computer Use status, and feeds those snapshots into the runtime-readiness
    gate used by the scorecard.
    """

    clean_session_id = _session_id(session_id)
    base_url = _base_url(api_base_url)
    owns_client = client is None
    if client is None:
        try:
            import httpx  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - httpx is in test env
            return _probe_error(
                base_url=base_url,
                session_id=clean_session_id,
                error=f"httpx unavailable: {exc}",
                review_queue_path=review_queue_path,
            )
        client = httpx.Client(timeout=max(0.1, float(timeout_s)))

    operations: list[dict[str, Any]] = []
    browser_health: dict[str, Any] | None = None
    computer_status: dict[str, Any] | None = None
    computer_preview: dict[str, Any] | None = None
    computer_execute: dict[str, Any] | None = None
    computer_replay_case: dict[str, Any] | None = None
    browser_queue_result: dict[str, Any] | None = None
    chrome_relay_handshake: dict[str, Any] | None = None
    real_chrome_relay_probe: dict[str, Any] | None = None
    cleanup_operations: list[dict[str, Any]] = []
    cleanup_status: dict[str, Any] = {
        "schema": "octopus.browser_desktop_runtime_probe_cleanup.v1",
        "enabled": bool(cleanup_session),
        "required": False,
        "attempted": False,
        "ok": True,
        "reason": "browser session cleanup was not required",
    }
    clean_token = str(bearer_token or "").strip()
    auth_events: list[dict[str, Any]] = []
    browser_session_ensured = False
    desktop_lease_release_required = False
    try:
        if not clean_token and auto_local_auth:
            token_result = _obtain_local_auth_token(
                client,
                base_url,
                operations=auth_events,
                timeout_s=timeout_s,
                username=local_auth_username,
                password=local_auth_password,
            )
            clean_token = str(token_result.get("access_token") or "").strip()
        ensure_result = _request_json(
            client,
            "post",
            base_url,
            "/api/browser/session/ensure",
            operations=operations,
            timeout_s=timeout_s,
            json={
                "session_id": clean_session_id,
                "headless": True,
                "project_id": "browser-desktop-runtime-probe",
                "profile_id": clean_session_id,
            },
            bearer_token=clean_token,
        )
        browser_session_ensured = isinstance(ensure_result, dict)
        _request_json(
            client,
            "post",
            base_url,
            "/api/browser/navigate",
            operations=operations,
            timeout_s=timeout_s,
            json={
                "session_id": clean_session_id,
                "url": PROBE_PAGE_URL,
            },
            bearer_token=clean_token,
        )
        _request_json(
            client,
            "post",
            base_url,
            "/api/browser/action",
            operations=operations,
            timeout_s=timeout_s,
            json={"session_id": clean_session_id, "action": "aria"},
            bearer_token=clean_token,
        )
        browser_health = _request_json(
            client,
            "get",
            base_url,
            "/api/browser/session/health",
            operations=operations,
            timeout_s=timeout_s,
            params={"session_id": clean_session_id, "limit": 20},
            bearer_token=clean_token,
        )
        if queue_browser_replay and _dict(browser_health).get("replay_ready") is True:
            browser_queue_result = _request_json(
                client,
                "post",
                base_url,
                "/api/browser/session/replay-case/queue",
                operations=operations,
                timeout_s=timeout_s,
                json={
                    "session_id": clean_session_id,
                    "reason": "browser_desktop_runtime_probe",
                },
                bearer_token=clean_token,
            )
        chrome_relay_handshake = _run_chrome_relay_handshake(
            client,
            base_url,
            operations=operations,
            timeout_s=timeout_s,
            bearer_token=clean_token,
        )
        if real_chrome_relay:
            if open_real_chrome_relay:
                _request_json(
                    client,
                    "post",
                    base_url,
                    "/api/browser/open-real-chrome-relay",
                    operations=operations,
                    timeout_s=timeout_s,
                    json={"api_base_url": base_url},
                    bearer_token=clean_token,
                )
            real_chrome_relay_probe = _run_real_chrome_relay_probe(
                client,
                base_url,
                operations=operations,
                timeout_s=timeout_s,
                bearer_token=clean_token,
                wait_for_real_connection=open_real_chrome_relay,
            )
        computer_status = _request_json(
            client,
            "get",
            base_url,
            "/api/computer/status",
            operations=operations,
            timeout_s=timeout_s,
            bearer_token=clean_token,
        )
        computer_preview = _request_json(
            client,
            "post",
            base_url,
            "/api/computer/actions/preview",
            operations=operations,
            timeout_s=timeout_s,
            json={
                "action": "wait",
                "ms": 10,
                "lease_owner_id": clean_session_id,
                "lease_owner_label": "Runtime probe",
            },
            bearer_token=clean_token,
        )
        preview_token = (
            str(_dict(computer_preview).get("token") or "")
            if isinstance(computer_preview, dict)
            else ""
        )
        if preview_token:
            computer_execute = _request_json(
                client,
                "post",
                base_url,
                "/api/computer/actions/execute",
                operations=operations,
                timeout_s=timeout_s,
                json={
                    "token": preview_token,
                    "lease_owner_id": clean_session_id,
                    "lease_owner_label": "Runtime probe",
                },
                bearer_token=clean_token,
            )
            desktop_lease_release_required = isinstance(computer_execute, dict)
        computer_replay_case = _request_json(
            client,
            "get",
            base_url,
            "/api/computer/activity/replay-case",
            operations=operations,
            timeout_s=timeout_s,
            params={"limit": 20},
            bearer_token=clean_token,
        )
    finally:
        if cleanup_session and browser_session_ensured:
            cleanup_status = {
                "schema": "octopus.browser_desktop_runtime_probe_cleanup.v1",
                "enabled": True,
                "required": True,
                "attempted": True,
                "ok": False,
            }
            _request_json(
                client,
                "post",
                base_url,
                "/api/browser/session/reset",
                operations=cleanup_operations,
                timeout_s=timeout_s,
                json={
                    "session_id": clean_session_id,
                    "relaunch": False,
                },
                bearer_token=clean_token,
            )
            cleanup_status.update(_cleanup_status_from_operations(cleanup_operations))
            if desktop_lease_release_required:
                _request_json(
                    client,
                    "post",
                    base_url,
                    "/api/computer/lease/release",
                    operations=cleanup_operations,
                    timeout_s=timeout_s,
                    json={
                        "lease_owner_id": clean_session_id,
                        "lease_owner_label": "Runtime probe",
                    },
                    bearer_token=clean_token,
                )
                cleanup_status.update(
                    _cleanup_status_from_operations(
                        cleanup_operations,
                        require_browser_reset=True,
                        require_desktop_lease_release=True,
                    )
                )
        elif cleanup_session:
            if desktop_lease_release_required:
                _request_json(
                    client,
                    "post",
                    base_url,
                    "/api/computer/lease/release",
                    operations=cleanup_operations,
                    timeout_s=timeout_s,
                    json={
                        "lease_owner_id": clean_session_id,
                        "lease_owner_label": "Runtime probe",
                    },
                    bearer_token=clean_token,
                )
            cleanup_status = {
                "schema": "octopus.browser_desktop_runtime_probe_cleanup.v1",
                "enabled": True,
                "required": bool(desktop_lease_release_required),
                "attempted": bool(desktop_lease_release_required),
                "ok": _cleanup_status_from_operations(
                    cleanup_operations,
                    require_browser_reset=False,
                    require_desktop_lease_release=desktop_lease_release_required,
                ).get("ok") is True,
                "reason": (
                    "desktop lease cleanup completed"
                    if desktop_lease_release_required
                    else "browser session was not ensured"
                ),
            }
        else:
            cleanup_status = {
                "schema": "octopus.browser_desktop_runtime_probe_cleanup.v1",
                "enabled": False,
                "required": bool(browser_session_ensured or desktop_lease_release_required),
                "attempted": False,
                "ok": not browser_session_ensured and not desktop_lease_release_required,
                "reason": (
                    "browser session cleanup disabled"
                    if browser_session_ensured or desktop_lease_release_required
                    else "cleanup disabled and no cleanup was required"
                ),
            }
        if owns_client:
            close = getattr(client, "close", None)
            if callable(close):
                close()

    auth_status = _auth_status(
        operations=operations,
        auth_events=auth_events,
        bearer_token_provided=bool(clean_token),
        initial_bearer_token_provided=bool(str(bearer_token or "").strip()),
        auto_local_auth=auto_local_auth,
    )
    all_operations = [*auth_events, *operations, *cleanup_operations]
    operations_ok = all(row.get("ok") is True for row in [*auth_events, *operations])
    cleanup_ok = cleanup_status.get("ok") is True
    operation_status = _operation_status_from_operations(all_operations)
    runtime_readiness = compute_browser_desktop_runtime_readiness(
        browser_health=browser_health,
        computer_status=computer_status,
        computer_preview=computer_preview,
        computer_execute=computer_execute,
        computer_replay_case=computer_replay_case,
        auth_status=auth_status,
        operation_status=operation_status,
        cleanup_status=cleanup_status,
        review_queue_path=review_queue_path,
    )
    quality = compute_browser_desktop_quality(
        browser_health=browser_health,
        computer_status=computer_status,
        computer_preview=computer_preview,
        computer_execute=computer_execute,
        computer_replay_case=computer_replay_case,
        chrome_relay_handshake=chrome_relay_handshake,
        real_chrome_relay_probe=real_chrome_relay_probe,
        auth_status=auth_status,
        operation_status=operation_status,
        cleanup_status=cleanup_status,
        review_queue_path=review_queue_path,
    )
    ok = operations_ok and cleanup_ok
    ready = ok and quality.get("ready") is True
    report = {
        "schema": SCHEMA,
        "ok": ok,
        "ready": ready,
        "score": quality.get("effective_score"),
        "api_base_url": base_url,
        "session_id": clean_session_id,
        "queue_browser_replay": bool(queue_browser_replay),
        "cleanup_session": bool(cleanup_session),
        "open_real_chrome_relay": bool(open_real_chrome_relay),
        "auth": auth_status,
        "operation_status": operation_status,
        "cleanup": cleanup_status,
        "browser_health": browser_health or {"provided": False},
        "computer_status": computer_status or {"provided": False},
        "computer_preview": computer_preview or {"provided": False},
        "computer_execute": computer_execute or {"provided": False},
        "computer_replay_case": computer_replay_case or {"provided": False},
        "browser_queue_result": browser_queue_result,
        "chrome_relay_handshake": chrome_relay_handshake or {"provided": False},
        "real_chrome_relay_probe": real_chrome_relay_probe or {
            "schema": "octopus.real_chrome_relay_probe.v1",
            "enabled": bool(real_chrome_relay),
            "provided": False,
        },
        "runtime_readiness": runtime_readiness,
        "quality": quality,
        "operations": all_operations,
        "next_actions": quality.get("next_actions") or [],
        "created_at": time.time(),
    }
    should_persist = owns_client if persist_evidence is None else bool(persist_evidence)
    if should_persist and report["ready"] is True:
        try:
            from runtime.safety.evolution.browser_desktop_runtime_evidence import (
                write_browser_desktop_runtime_evidence,
            )

            report["runtime_evidence_snapshot"] = write_browser_desktop_runtime_evidence(
                report,
                path=evidence_path,
            )
        except Exception as exc:  # noqa: BLE001
            report["runtime_evidence_snapshot"] = {
                "schema": "octopus.browser_desktop_runtime_evidence_lookup.v1",
                "available": False,
                "usable": False,
                "fresh": False,
                "error": str(exc),
            }
    else:
        report["runtime_evidence_snapshot"] = {
            "schema": "octopus.browser_desktop_runtime_evidence_lookup.v1",
            "available": False,
            "usable": False,
            "fresh": False,
            "reason": (
                "runtime probe evidence persistence disabled"
                if not should_persist
                else "runtime probe was not ready"
            ),
        }
    return report


def _obtain_local_auth_token(
    client: Any,
    base_url: str,
    *,
    operations: list[dict[str, Any]],
    timeout_s: float,
    username: str,
    password: str,
) -> dict[str, Any]:
    providers = _request_json(
        client,
        "get",
        base_url,
        "/api/auth/providers",
        operations=operations,
        timeout_s=timeout_s,
    )
    provider_rows = providers.get("providers") if isinstance(providers, dict) else []
    local_provider = next(
        (
            row for row in provider_rows
            if isinstance(row, dict) and row.get("id") == "local"
        ),
        None,
    )
    if not local_provider:
        return {"access_token": ""}
    body: dict[str, Any] = {
        "username": str(username or "runtime-probe")[:64],
        "display_name": "Runtime Probe",
    }
    if password:
        body["password"] = password
    response = _request_json(
        client,
        "post",
        base_url,
        str(local_provider.get("endpoint") or "/api/auth/local/login"),
        operations=operations,
        timeout_s=timeout_s,
        json=body,
    )
    return response if isinstance(response, dict) else {}


def _run_chrome_relay_handshake(
    client: Any,
    base_url: str,
    *,
    operations: list[dict[str, Any]],
    timeout_s: float,
    bearer_token: str,
) -> dict[str, Any]:
    """Exercise the Chrome relay command/result loop without touching Chrome."""

    initial = _request_json(
        client,
        "post",
        base_url,
        "/api/browser/relay/heartbeat",
        operations=operations,
        timeout_s=timeout_s,
        json={
            "extension_version": "runtime-probe",
            "active_tab": {
                "id": "runtime-probe",
                "url": PROBE_PAGE_URL,
                "title": "Octopus runtime probe",
            },
        },
        bearer_token=bearer_token,
    )
    if not isinstance(initial, dict):
        return _relay_handshake_report(
            ok=False,
            command_result=None,
            polled=None,
            result_ack=None,
            status=None,
            error="relay heartbeat failed",
        )

    command_result: dict[str, Any] = {}
    command_error = ""

    def _issue_command() -> None:
        nonlocal command_result
        nonlocal command_error
        try:
            command_result = _request_json(
                client,
                "post",
                base_url,
                "/api/browser/relay/command",
                operations=operations,
                timeout_s=timeout_s,
                json={
                    "action": "eval",
                    "script": "document.title",
                    "timeout_seconds": min(2.0, max(0.5, float(timeout_s))),
                },
                bearer_token=bearer_token,
            ) or {}
        except Exception as exc:  # noqa: BLE001
            command_error = f"{type(exc).__name__}: {exc}"

    thread = threading.Thread(target=_issue_command, daemon=True)
    thread.start()
    polled: dict[str, Any] | None = None
    for _ in range(20):
        time.sleep(0.05)
        polled = _request_json(
            client,
            "post",
            base_url,
            "/api/browser/relay/heartbeat",
            operations=operations,
            timeout_s=timeout_s,
            json={
                "extension_version": "runtime-probe",
                "active_tab": {
                    "id": "runtime-probe",
                    "url": PROBE_PAGE_URL,
                    "title": "Octopus runtime probe",
                },
            },
            bearer_token=bearer_token,
        )
        commands = polled.get("commands") if isinstance(polled, dict) else []
        command = next(
            (row for row in commands if isinstance(row, dict) and row.get("id")),
            None,
        )
        if command is None:
            continue
        result_ack = _request_json(
            client,
            "post",
            base_url,
            "/api/browser/relay/result",
            operations=operations,
            timeout_s=timeout_s,
            json={
                "id": command["id"],
                "active_tab": {
                    "id": "runtime-probe",
                    "url": PROBE_PAGE_URL,
                    "title": "Octopus runtime probe",
                },
                "result": {
                    "ok": True,
                    "id": command["id"],
                    "value": "Octopus runtime probe",
                    "source": "runtime_probe",
                },
            },
            bearer_token=bearer_token,
        )
        thread.join(timeout=max(0.2, min(2.5, float(timeout_s))))
        status = _request_json(
            client,
            "get",
            base_url,
            "/api/browser/relay/status",
            operations=operations,
            timeout_s=timeout_s,
            bearer_token=bearer_token,
        )
        return _relay_handshake_report(
            ok=(
                isinstance(result_ack, dict)
                and result_ack.get("ok") is True
                and isinstance(command_result, dict)
                and command_result.get("ok") is True
            ),
            command_result=command_result,
            polled=polled,
            result_ack=result_ack,
            status=status,
            command_id=str(command["id"]),
            error=command_error,
        )

    thread.join(timeout=0.2)
    return _relay_handshake_report(
        ok=False,
        command_result=command_result,
        polled=polled,
        result_ack=None,
        status=None,
        error=command_error or "relay command was not delivered to the simulated extension",
    )


def _run_real_chrome_relay_probe(
    client: Any,
    base_url: str,
    *,
    operations: list[dict[str, Any]],
    timeout_s: float,
    bearer_token: str,
    wait_for_real_connection: bool = False,
) -> dict[str, Any]:
    """Ask an already-connected real relay extension/bookmarklet to answer."""

    status = _wait_for_real_chrome_relay_status(
        client,
        base_url,
        operations=operations,
        timeout_s=timeout_s,
        bearer_token=bearer_token,
        wait_for_real_connection=wait_for_real_connection,
    )
    if not isinstance(status, dict) or status.get("connected") is not True:
        return _real_relay_probe_report(
            ok=False,
            status=status,
            command_result=None,
            error="real Chrome relay is not connected",
        )
    extension_version = str(status.get("extension_version") or "")
    active_tab = _dict(status.get("active_tab"))
    if not _looks_like_real_chrome_relay_status(status):
        return _real_relay_probe_report(
            ok=False,
            status=status,
            command_result=None,
            extension_version=extension_version,
            active_tab=active_tab,
            error=(
                "relay status is from the runtime self-test heartbeat, not a "
                "real Chrome extension or bookmarklet"
            ),
        )
    command_result = _request_json(
        client,
        "post",
        base_url,
        "/api/browser/relay/command",
        operations=operations,
        timeout_s=timeout_s,
        json={
            "action": "aria",
            "timeout_seconds": min(6.0, max(1.0, float(timeout_s))),
        },
        bearer_token=bearer_token,
    )
    result = _dict(command_result)
    ok = (
        result.get("ok") is True
        and bool(str(result.get("id") or ""))
        and (
            bool(str(result.get("title") or ""))
            or bool(str(result.get("url") or ""))
            or isinstance(result.get("nodes"), dict)
        )
    )
    return _real_relay_probe_report(
        ok=ok,
        status=status,
        command_result=command_result,
        extension_version=extension_version,
        active_tab=active_tab,
        error="" if ok else str(result.get("error") or "real relay command did not return page evidence"),
    )


def _real_relay_probe_report(
    *,
    ok: bool,
    status: dict[str, Any] | None,
    command_result: dict[str, Any] | None,
    extension_version: str = "",
    active_tab: dict[str, Any] | None = None,
    error: str = "",
) -> dict[str, Any]:
    active = _dict(active_tab) or _dict(_dict(status).get("active_tab"))
    return {
        "schema": "octopus.real_chrome_relay_probe.v1",
        "enabled": True,
        "ok": ok,
        "connected": _dict(status).get("connected") is True,
        "extension_version": extension_version or str(_dict(status).get("extension_version") or ""),
        "active_tab": {
            "id": active.get("id"),
            "url": _redact_sensitive_text(str(active.get("url") or ""))[:500],
            "title": _redact_sensitive_text(str(active.get("title") or ""))[:300],
        },
        "command_result": _redact_sensitive_value(command_result)
        if command_result
        else {"provided": False},
        "error": error,
        "evidence_level": "real_chrome_profile_verified" if ok else "missing",
        "note": (
            "Uses an already-connected Chrome extension or bookmarklet. It does "
            "not install the extension, open Chrome, or bypass website/session permissions."
        ),
    }


def _wait_for_real_chrome_relay_status(
    client: Any,
    base_url: str,
    *,
    operations: list[dict[str, Any]],
    timeout_s: float,
    bearer_token: str,
    wait_for_real_connection: bool,
) -> dict[str, Any] | None:
    deadline = time.time() + (float(timeout_s) if wait_for_real_connection else 0.0)
    while True:
        payload = _request_json(
            client,
            "get",
            base_url,
            "/api/browser/relay/status",
            operations=operations,
            timeout_s=timeout_s,
            bearer_token=bearer_token,
        )
        status = payload if isinstance(payload, dict) else None
        if (
            isinstance(status, dict)
            and status.get("connected") is True
            and _looks_like_real_chrome_relay_status(status)
        ):
            return status
        if not wait_for_real_connection or time.time() >= deadline:
            return status
        time.sleep(0.25)


def _looks_like_real_chrome_relay_status(status: dict[str, Any]) -> bool:
    extension_version = str(status.get("extension_version") or "").strip()
    active_tab = _dict(status.get("active_tab"))
    tab_id = str(active_tab.get("id") or "")
    tab_url = str(active_tab.get("url") or "")
    if extension_version == "runtime-probe" or tab_id == "runtime-probe":
        return False
    if tab_url == PROBE_PAGE_URL:
        return False
    return bool(extension_version or active_tab)


def _relay_handshake_report(
    *,
    ok: bool,
    command_result: dict[str, Any] | None,
    polled: dict[str, Any] | None,
    result_ack: dict[str, Any] | None,
    status: dict[str, Any] | None,
    command_id: str = "",
    error: str = "",
) -> dict[str, Any]:
    return {
        "schema": "octopus.browser_chrome_relay_handshake.v1",
        "ok": ok,
        "command_id": command_id,
        "command_result": _redact_sensitive_value(command_result)
        if command_result
        else {"provided": False},
        "polled": _redact_sensitive_value(polled) if polled else {"provided": False},
        "result_ack": _redact_sensitive_value(result_ack)
        if result_ack
        else {"provided": False},
        "status": _redact_sensitive_value(status) if status else {"provided": False},
        "error": _redact_sensitive_text(error),
    }


def _auth_status(
    *,
    operations: list[dict[str, Any]],
    auth_events: list[dict[str, Any]],
    bearer_token_provided: bool,
    initial_bearer_token_provided: bool,
    auto_local_auth: bool,
) -> dict[str, Any]:
    auth_blocked = [
        row for row in operations
        if int(row.get("status_code") or 0) == 401
        or "authorization" in str(row.get("error") or "").lower()
        or "invalid token" in str(row.get("error") or "").lower()
        or "invalid jwt" in str(row.get("error") or "").lower()
    ]
    local_login = next(
        (
            row for row in auth_events
            if str(row.get("path") or "").endswith("/api/auth/local/login")
        ),
        None,
    )
    return {
        "schema": "octopus.browser_desktop_runtime_probe_auth.v1",
        "bearer_token_provided": bearer_token_provided,
        "initial_bearer_token_provided": initial_bearer_token_provided,
        "auto_local_auth_enabled": bool(auto_local_auth),
        "local_auth_attempted": local_login is not None,
        "local_auth_succeeded": bool(local_login and local_login.get("ok") is True),
        "auth_blocked": bool(auth_blocked),
        "auth_blocked_count": len(auth_blocked),
    }


def _request_json(
    client: Any,
    method: str,
    base_url: str,
    path: str,
    *,
    operations: list[dict[str, Any]],
    timeout_s: float,
    json: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    bearer_token: str = "",
) -> dict[str, Any] | None:
    url = urljoin(f"{base_url}/", path.lstrip("/"))
    started = time.time()
    status_code = 0
    content_type = ""
    response_preview = ""
    caller = getattr(client, method)
    kwargs: dict[str, Any] = {"params": params}
    token = str(bearer_token or "").strip()
    if token:
        kwargs["headers"] = {"Authorization": f"Bearer {token}"}
    if json is not None:
        kwargs["json"] = json
    if timeout_s is not None:
        kwargs["timeout"] = max(0.1, float(timeout_s))
    transient_errors: list[str] = []
    max_attempts = 2
    for attempt in range(1, max_attempts + 1):
        try:
            try:
                response = caller(url, **kwargs)
            except TypeError:
                kwargs.pop("timeout", None)
                if "headers" in kwargs:
                    try:
                        response = caller(url, **kwargs)
                    except TypeError:
                        kwargs.pop("headers", None)
                        response = caller(url, **kwargs)
                else:
                    response = caller(url, **kwargs)
            status_code = int(getattr(response, "status_code", 0) or 0)
            content_type = _response_content_type(response)
            payload, json_error, response_preview = _response_payload(response)
            if not isinstance(payload, dict):
                payload = {"payload": payload}
            ok = 200 <= status_code < 300 and not json_error
            error = (
                ""
                if ok
                else _operation_error(
                    payload,
                    status_code=status_code,
                    content_type=content_type,
                    json_error=json_error,
                )
            )
            if not ok and attempt < max_attempts and _retryable_response(status_code):
                transient_errors.append(error)
                time.sleep(0.1 * attempt)
                continue
            operation = {
                "path": path,
                "method": method.upper(),
                "ok": ok,
                "status_code": status_code,
                "duration_ms": round((time.time() - started) * 1000, 2),
                "error": error,
                "attempts": attempt,
            }
            if transient_errors:
                operation["transient_errors"] = transient_errors
            if content_type:
                operation["content_type"] = content_type
            if response_preview and not ok:
                operation["response_preview"] = response_preview
            operations.append(operation)
            return payload if ok else None
        except Exception as exc:  # noqa: BLE001
            error = f"{type(exc).__name__}: {exc}"
            if attempt < max_attempts and _retryable_exception(exc):
                transient_errors.append(error)
                time.sleep(0.1 * attempt)
                continue
            operation = {
                "path": path,
                "method": method.upper(),
                "ok": False,
                "status_code": status_code,
                "duration_ms": round((time.time() - started) * 1000, 2),
                "error": error,
                "attempts": attempt,
            }
            if transient_errors:
                operation["transient_errors"] = transient_errors
            if content_type:
                operation["content_type"] = content_type
            if response_preview:
                operation["response_preview"] = response_preview
            operations.append(operation)
            return None
    return None


def _probe_error(
    *,
    base_url: str,
    session_id: str,
    error: str,
    review_queue_path: str | Path | None,
) -> dict[str, Any]:
    runtime_readiness = compute_browser_desktop_runtime_readiness(
        review_queue_path=review_queue_path,
    )
    quality = compute_browser_desktop_quality(review_queue_path=review_queue_path)
    return {
        "schema": SCHEMA,
        "ok": False,
        "ready": False,
        "score": quality.get("effective_score"),
        "api_base_url": base_url,
        "session_id": session_id,
        "error": error,
        "browser_health": {"provided": False},
        "computer_status": {"provided": False},
        "computer_preview": {"provided": False},
        "computer_execute": {"provided": False},
        "computer_replay_case": {"provided": False},
        "runtime_readiness": runtime_readiness,
        "quality": quality,
        "operations": [],
        "next_actions": quality.get("next_actions") or [],
        "created_at": time.time(),
    }


def _base_url(value: str) -> str:
    clean = str(value or "").strip() or "http://127.0.0.1:8000"
    return clean.rstrip("/")


def _session_id(value: str | None) -> str:
    clean = str(value or "").strip()
    if clean:
        return clean[:120]
    return f"browser-desktop-runtime-probe-{uuid.uuid4().hex[:8]}"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _cleanup_status_from_operations(
    cleanup_operations: list[dict[str, Any]],
    *,
    require_browser_reset: bool = True,
    require_desktop_lease_release: bool = False,
) -> dict[str, Any]:
    browser_row = next(
        (
            item for item in reversed(cleanup_operations)
            if str(item.get("path") or "").endswith("/api/browser/session/reset")
        ),
        None,
    )
    lease_row = next(
        (
            item for item in reversed(cleanup_operations)
            if str(item.get("path") or "").endswith("/api/computer/lease/release")
        ),
        None,
    )
    missing: list[str] = []
    if require_browser_reset and not browser_row:
        missing.append("/api/browser/session/reset")
    if require_desktop_lease_release and not lease_row:
        missing.append("/api/computer/lease/release")
    if missing:
        return {
            "ok": False,
            "status_code": 0,
            "error": f"cleanup request was not recorded: {', '.join(missing)}",
            "browser_session_reset": _cleanup_row(browser_row),
            "desktop_lease_release": _cleanup_row(lease_row),
        }
    rows = [row for row in (browser_row, lease_row) if isinstance(row, dict)]
    failed = [row for row in rows if row.get("ok") is not True]
    status_code = int((failed[0] if failed else rows[-1]).get("status_code") or 0) if rows else 0
    return {
        "ok": not failed,
        "status_code": status_code,
        "error": "; ".join(str(row.get("error") or "") for row in failed if row.get("error")),
        "browser_session_reset": _cleanup_row(browser_row),
        "desktop_lease_release": _cleanup_row(lease_row),
    }


def _cleanup_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(row, dict):
        return {"attempted": False, "ok": False, "status_code": 0, "error": ""}
    return {
        "attempted": True,
        "ok": row.get("ok") is True,
        "status_code": int(row.get("status_code") or 0),
        "error": str(row.get("error") or ""),
        "duration_ms": row.get("duration_ms"),
    }


def _operation_status_from_operations(
    operations: list[dict[str, Any]],
) -> dict[str, Any]:
    failed = [
        {
            "method": row.get("method"),
            "path": row.get("path"),
            "status_code": row.get("status_code"),
            "error": row.get("error"),
        }
        for row in operations
        if row.get("ok") is not True
    ]
    return {
        "schema": "octopus.browser_desktop_runtime_probe_operations.v1",
        "ok": not failed,
        "total": len(operations),
        "failed_count": len(failed),
        "failed_operations": failed,
    }


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", {}) or {}
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return ""
    return str(getter("content-type") or getter("Content-Type") or "").strip()


def _response_payload(response: Any) -> tuple[Any, str, str]:
    try:
        return response.json(), "", ""
    except Exception as exc:  # noqa: BLE001
        preview = _redacted_preview(str(getattr(response, "text", "") or ""))
        return (
            {
                "error": "non-json response",
                "detail": f"{type(exc).__name__}: {exc}",
                "body_preview": preview,
            },
            f"{type(exc).__name__}: {exc}",
            preview,
        )


def _operation_error(
    payload: dict[str, Any],
    *,
    status_code: int,
    content_type: str,
    json_error: str,
) -> str:
    if json_error:
        suffix = f" status={status_code}" if status_code else ""
        media = f" content_type={content_type}" if content_type else ""
        return f"non-json response{suffix}{media}: {json_error}"
    detail = payload.get("error") or payload.get("detail") or payload.get("message")
    if isinstance(detail, dict):
        detail = detail.get("error") or detail.get("detail") or str(detail)
    return str(detail or f"HTTP {status_code}")


def _retryable_response(status_code: int) -> bool:
    return status_code in {408, 425, 429, 500, 502, 503, 504}


def _retryable_exception(exc: Exception) -> bool:
    text = f"{type(exc).__name__}: {exc}".lower()
    return any(
        marker in text
        for marker in (
            "readerror",
            "connecterror",
            "remoteprotocolerror",
            "connection reset",
            "connection refused",
            "temporarily unavailable",
            "timed out",
            "timeout",
        )
    )


_SENSITIVE_QUERY_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth",
    "authorization",
    "bearer",
    "jwt",
    "key",
    "relay_token",
    "secret",
    "sig",
    "signature",
    "token",
}


def _redact_sensitive_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: (
                "<redacted>"
                if _is_sensitive_key(str(key))
                else _redact_sensitive_value(row)
            )
            for key, row in value.items()
        }
    if isinstance(value, list):
        return [_redact_sensitive_value(row) for row in value]
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_value(row) for row in value)
    if isinstance(value, str):
        return _redact_sensitive_text(value)
    return value


def _redact_sensitive_text(text: str) -> str:
    clean = str(text or "")
    if not clean:
        return ""
    redacted = _redact_sensitive_url(clean)
    redacted = re.sub(
        r"(?i)([?&](?:access_token|api_key|apikey|auth|authorization|bearer|jwt|key|relay_token|secret|sig|signature|token)=)[^&#\s]+",
        r"\1<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(authorization:\s*bearer\s+)[A-Za-z0-9._~+/=-]+",
        r"\1<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"(?i)(access_token[\"'\s:=]+)[A-Za-z0-9._~+/=-]+",
        r"\1<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"sk-[A-Za-z0-9_-]{12,}",
        "sk-<redacted>",
        redacted,
    )
    redacted = re.sub(
        r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b",
        "<jwt-redacted>",
        redacted,
    )
    return redacted


def _redact_sensitive_url(text: str) -> str:
    try:
        parts = urlsplit(text)
    except ValueError:
        return text
    if not parts.query:
        return text
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not query:
        return text
    redacted_query = [
        (key, "<redacted>" if _is_sensitive_key(key) else value)
        for key, value in query
    ]
    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        urlencode(redacted_query, doseq=True),
        parts.fragment,
    ))


def _is_sensitive_key(key: str) -> bool:
    clean = str(key or "").strip().lower().replace("-", "_")
    return clean in _SENSITIVE_QUERY_KEYS or clean.endswith("_token") or clean.endswith("_secret")


def _redacted_preview(text: str, *, limit: int = 500) -> str:
    return _redact_sensitive_text(text[:limit])


__all__ = [
    "SCHEMA",
    "run_browser_desktop_runtime_probe",
]
