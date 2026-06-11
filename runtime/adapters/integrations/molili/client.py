
from __future__ import annotations

import logging
import time
from typing import Any

try:
    import httpx  # type: ignore[import-untyped]

    HTTPX_AVAILABLE = True
except ImportError:  # pragma: no cover
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)


class MoliliClientError(RuntimeError):

    def __init__(
        self, message: str, *, status_code: int | None = None, body: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body



_TOKEN_DEAD_ERR_CODES = frozenset(
    {"BE_REPLACED", "TOKEN_EXPIRED", "UNAUTHORIZED", "NOT_LOGIN"},
)


def detect_dead_token(upstream: dict[str, Any] | None) -> str | None:
    if not isinstance(upstream, dict):
        return None
    if upstream.get("success") is False:
        code = upstream.get("errCode")
        if isinstance(code, str) and code.upper() in _TOKEN_DEAD_ERR_CODES:
            return f"{code}: {upstream.get('errMessage') or ''}".strip(": ")
    return None


def pluck(data: Any, dotted: str | None) -> Any:
    if not dotted or data is None:
        return None
    cur: Any = data
    for key in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            return None
    return cur


def mask_phone(phone: str) -> str:
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) < 4:
        return "***"
    return f"***{digits[-4:]}"



def post_upstream(
    url: str,
    body: dict[str, Any],
    *,
    timeout: float,
    headers: dict[str, str] | None = None,
    http_client: Any = None,
) -> dict[str, Any]:
    log_body = {
        k: (mask_phone(v) if k in ("phone", "mobile") and isinstance(v, str) else v)
        for k, v in body.items()
    }
    t0 = time.perf_counter()
    client = http_client or (httpx if HTTPX_AVAILABLE else None)
    if client is None:
        raise MoliliClientError("httpx not installed and no http_client injected")
    try:
        r = client.post(
            url, json=body, headers=headers or {}, timeout=timeout,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(
            "molili upstream unreachable: url=%s elapsed_ms=%d body=%s err=%s",
            url, elapsed_ms, log_body, exc,
        )
        raise MoliliClientError(f"upstream unreachable: {exc}") from exc
    elapsed_ms = int((time.perf_counter() - t0) * 1000)

    status = getattr(r, "status_code", 0)
    text = getattr(r, "text", "") or ""
    if status >= 400:
        logger.warning(
            "molili upstream rejected: url=%s status=%s elapsed_ms=%d body=%s resp=%r",
            url, status, elapsed_ms, log_body, text[:500],
        )
        raise MoliliClientError(
            f"upstream rejected: {text[:1024]}",
            status_code=status,
            body=text,
        )
    try:
        parsed = r.json() if (text or getattr(r, "content", b"")) else {}
    except ValueError as exc:
        logger.warning(
            "molili upstream non-JSON: url=%s body=%s resp=%r",
            url, log_body, text[:500],
        )
        raise MoliliClientError(
            "upstream returned non-JSON body", status_code=status, body=text,
        ) from exc

    if isinstance(parsed, dict) and parsed.get("success") is False:
        logger.warning(
            "molili upstream success=false: url=%s errCode=%s errMessage=%s",
            url, parsed.get("errCode"), parsed.get("errMessage"),
        )
    return parsed


def get_upstream(
    url: str,
    *,
    token: str,
    timeout: float,
    params: dict[str, Any] | None = None,
    http_client: Any = None,
) -> dict[str, Any]:
    headers = {"Token": token}
    client = http_client or (httpx if HTTPX_AVAILABLE else None)
    if client is None:
        raise MoliliClientError("httpx not installed and no http_client injected")
    try:
        r = client.get(url, headers=headers, params=params or {}, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        logger.warning("molili GET %s unreachable: %s", url, exc)
        raise MoliliClientError(f"upstream unreachable: {exc}") from exc
    status = getattr(r, "status_code", 0)
    text = getattr(r, "text", "") or ""
    if status >= 400:
        logger.warning(
            "molili GET %s rejected: status=%s body=%r", url, status, text[:500],
        )
        raise MoliliClientError(
            f"upstream rejected: {text[:1024]}", status_code=status, body=text,
        )
    try:
        return r.json() if (text or getattr(r, "content", b"")) else {}
    except ValueError as exc:
        raise MoliliClientError(
            "upstream returned non-JSON", status_code=status, body=text,
        ) from exc


def post_upstream_order(
    url: str,
    body: dict[str, Any],
    *,
    token: str,
    timeout: float,
    http_client: Any = None,
) -> dict[str, Any]:
    headers = {"Token": token, "Content-Type": "application/json"}
    return post_upstream(
        url, body, timeout=timeout, headers=headers, http_client=http_client,
    )
