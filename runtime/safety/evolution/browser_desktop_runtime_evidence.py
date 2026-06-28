from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from runtime.platform.process.paths import app_paths

SCHEMA = "octopus.browser_desktop_runtime_evidence.v1"
LOOKUP_SCHEMA = "octopus.browser_desktop_runtime_evidence_lookup.v1"
DEFAULT_MAX_AGE_S = 30 * 60


def browser_desktop_runtime_evidence_path(
    path: str | Path | None = None,
) -> Path:
    if path is not None:
        return Path(path).expanduser()
    return app_paths().browser_desktop_runtime_evidence_path


def write_browser_desktop_runtime_evidence(
    report: dict[str, Any],
    *,
    path: str | Path | None = None,
    max_age_s: int = DEFAULT_MAX_AGE_S,
    now: float | None = None,
) -> dict[str, Any]:
    created_at = float(now if now is not None else time.time())
    ttl = max(1, int(max_age_s))
    payload = {
        "schema": SCHEMA,
        "source_schema": report.get("schema"),
        "created_at": created_at,
        "expires_at": created_at + ttl,
        "ttl_seconds": ttl,
        "ok": report.get("ok") is True,
        "ready": report.get("ready") is True,
        "score": report.get("score"),
        "api_base_url": str(report.get("api_base_url") or ""),
        "session_id": str(report.get("session_id") or ""),
        "auth": _safe_dict(report.get("auth")),
        "operation_status": _safe_dict(report.get("operation_status")),
        "cleanup": _safe_dict(report.get("cleanup")),
        "browser_health": _safe_dict(report.get("browser_health")),
        "chrome_relay_handshake": _safe_dict(report.get("chrome_relay_handshake")),
        "real_chrome_relay_probe": _safe_dict(report.get("real_chrome_relay_probe")),
        "computer_status": _safe_dict(report.get("computer_status")),
        "computer_preview": _safe_dict(report.get("computer_preview")),
        "computer_execute": _safe_dict(report.get("computer_execute")),
        "computer_replay_case": _safe_dict(report.get("computer_replay_case")),
        "runtime_readiness": _safe_dict(report.get("runtime_readiness")),
        "operations": _safe_operations(report.get("operations")),
        "policy": {
            "schema": "octopus.browser_desktop_runtime_evidence_policy.v1",
            "secrets_redacted": True,
            "stores_preview_token": False,
            "stores_redacted_preview_token_marker": True,
            "stores_bearer_token": False,
            "stores_local_auth_password": False,
        },
    }
    target = browser_desktop_runtime_evidence_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f"{target.name}.tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(target)
    return {
        "schema": LOOKUP_SCHEMA,
        "available": True,
        "usable": _is_usable(payload),
        "fresh": True,
        "path": str(target),
        "age_seconds": 0,
        "evidence": payload,
    }


def load_browser_desktop_runtime_evidence(
    *,
    path: str | Path | None = None,
    max_age_s: int = DEFAULT_MAX_AGE_S,
    now: float | None = None,
) -> dict[str, Any]:
    target = browser_desktop_runtime_evidence_path(path)
    current = float(now if now is not None else time.time())
    if not target.is_file():
        return _lookup(
            available=False,
            path=target,
            reason="runtime evidence snapshot is missing",
        )
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return _lookup(
            available=True,
            path=target,
            reason=f"runtime evidence snapshot is unreadable: {exc}",
        )
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        return _lookup(
            available=True,
            path=target,
            reason="runtime evidence snapshot schema is invalid",
            evidence=payload if isinstance(payload, dict) else {},
        )
    created_at = float(payload.get("created_at") or 0.0)
    expires_at = float(payload.get("expires_at") or 0.0)
    age = max(0, int(round(current - created_at))) if created_at else 0
    ttl = max(1, int(max_age_s))
    fresh = bool(created_at and age <= ttl and (not expires_at or current <= expires_at))
    usable = fresh and _is_usable(payload)
    reason = ""
    if not fresh:
        reason = "runtime evidence snapshot is stale"
    elif not usable:
        reason = "runtime evidence snapshot is not ready"
    return _lookup(
        available=True,
        usable=usable,
        fresh=fresh,
        path=target,
        reason=reason,
        age_seconds=age,
        evidence=payload,
    )


def _lookup(
    *,
    available: bool,
    path: Path,
    usable: bool = False,
    fresh: bool = False,
    reason: str = "",
    age_seconds: int = 0,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema": LOOKUP_SCHEMA,
        "available": available,
        "usable": usable,
        "fresh": fresh,
        "path": str(path),
        "reason": reason,
        "age_seconds": age_seconds,
        "evidence": evidence or {},
    }


def _is_usable(payload: dict[str, Any]) -> bool:
    operation_status = _safe_dict(payload.get("operation_status"))
    cleanup = _safe_dict(payload.get("cleanup"))
    chrome_relay_handshake = _safe_dict(payload.get("chrome_relay_handshake"))
    runtime_readiness = _safe_dict(payload.get("runtime_readiness"))
    computer_preview = _safe_dict(payload.get("computer_preview"))
    computer_execute = _safe_dict(payload.get("computer_execute"))
    computer_replay_case = _safe_dict(payload.get("computer_replay_case"))
    preview_risk = _safe_dict(computer_preview.get("risk"))
    execute_action = _safe_dict(computer_execute.get("action"))
    execute_risk = _safe_dict(computer_execute.get("risk"))
    return (
        payload.get("ok") is True
        and payload.get("ready") is True
        and operation_status.get("ok") is True
        and cleanup.get("ok") is True
        and chrome_relay_handshake.get("ok") is True
        and computer_preview.get("ok") is True
        and bool(computer_preview.get("token"))
        and preview_risk.get("level") == "low"
        and computer_execute.get("ok") is True
        and execute_action.get("action") == "wait"
        and execute_risk.get("level") == "low"
        and computer_replay_case.get("schema")
        == "octopus.computer_activity_replay_case.v1"
        and computer_replay_case.get("replay_ready") is True
        and runtime_readiness.get("ready") is True
        and int(operation_status.get("failed_count") or 0) == 0
    )


def _safe_dict(value: Any) -> dict[str, Any]:
    return _redact_sensitive_value(value) if isinstance(value, dict) else {}


def _safe_operations(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    for row in value:
        if not isinstance(row, dict):
            continue
        rows.append({
            "method": row.get("method"),
            "path": row.get("path"),
            "ok": row.get("ok") is True,
            "status_code": int(row.get("status_code") or 0),
            "duration_ms": row.get("duration_ms"),
            "attempts": int(row.get("attempts") or 1),
            "error": _redact_sensitive_text(str(row.get("error") or "")),
            "transient_errors": _redact_sensitive_value(row.get("transient_errors") or []),
            "content_type": str(row.get("content_type") or ""),
            "response_preview": _redact_sensitive_text(
                str(row.get("response_preview") or "")[:500]
            ),
        })
    return rows


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


__all__ = [
    "DEFAULT_MAX_AGE_S",
    "LOOKUP_SCHEMA",
    "SCHEMA",
    "browser_desktop_runtime_evidence_path",
    "load_browser_desktop_runtime_evidence",
    "write_browser_desktop_runtime_evidence",
]
