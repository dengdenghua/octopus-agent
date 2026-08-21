"""Hardened opt-in same-origin proxy for the MX2025 viewer.

The proxy deliberately carries no Octopus authentication state. Enabling it
still gives upstream JavaScript this application's origin, so the plugin keeps
the route behind two explicit local-only configuration switches as well.
"""

from __future__ import annotations

import ipaddress
import logging
import re
from collections.abc import AsyncIterator
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

_logger = logging.getLogger(__name__)

_REQUEST_BODY_LIMIT = 1024 * 1024
_BODY_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_ALLOWED_PATH_ROOTS = frozenset({"pages", "assets", "static", "api", "img", "uni"})
_ALLOWED_ROOT_FILES = frozenset({"favicon.ico", "index.html", "manifest.json"})

_FORWARDED_REQUEST_HEADERS = frozenset(
    {
        "accept",
        "accept-encoding",
        "accept-language",
        "cache-control",
        "content-type",
        "if-modified-since",
        "if-none-match",
        "range",
        "user-agent",
    }
)
_FORWARDED_RESPONSE_HEADERS = frozenset(
    {
        "accept-ranges",
        "cache-control",
        "content-encoding",
        "content-length",
        "content-range",
        "content-type",
        "etag",
        "last-modified",
    }
)

# Third-party code is still same-origin when the operator explicitly opts in,
# but it may only load/connect back through this origin. In particular, the
# upstream cannot remove this policy or widen it to arbitrary network targets.
_PROXY_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "font-src 'self' data:; connect-src 'self'; media-src 'self'; "
    "frame-src 'self'; worker-src 'self' blob:; object-src 'none'; "
    "base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
)
_SECURITY_RESPONSE_HEADERS = {
    "Content-Security-Policy": _PROXY_CSP,
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "SAMEORIGIN",
}
_HOST_LABEL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")


def _fully_unquote_path(value: str) -> str | None:
    """Decode nested percent escapes, rejecting intentionally deep ambiguity."""
    decoded = value
    for _ in range(8):
        next_value = unquote(decoded)
        if next_value == decoded:
            return decoded
        decoded = next_value
    return None


def _canonical_host(hostname: str) -> str:
    if "%" in hostname:
        return ""
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            candidate = hostname.rstrip(".").encode("idna").decode("ascii").lower()
        except UnicodeError:
            return ""
        labels = candidate.split(".")
        if not candidate or len(candidate) > 253 or any(not label for label in labels):
            return ""
        if all(label.isdigit() for label in labels):
            # Reject ambiguous non-canonical integer/dotted IPv4 spellings.
            return ""
        if not all(_HOST_LABEL_RE.fullmatch(label) is not None for label in labels):
            return ""
        return candidate
    return f"[{address.compressed}]" if address.version == 6 else address.compressed


def secure_upstream_origin(base_url: str) -> str | None:
    """Return a normalized HTTPS base URL, rejecting ambiguous URLs."""
    raw = str(base_url or "").strip()
    if not raw or "\\" in raw or any(ord(ch) < 33 for ch in raw):
        return None
    try:
        parsed = urlsplit(raw)
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        return None
    canonical_host = _canonical_host(hostname)
    if not canonical_host or port == 0:
        return None

    decoded_path = _fully_unquote_path(parsed.path or "")
    if decoded_path is None:
        return None
    if any(segment in {".", ".."} for segment in decoded_path.split("/")):
        return None
    if "\\" in decoded_path or any(ord(ch) < 32 for ch in decoded_path):
        return None

    netloc = canonical_host
    if port is not None:
        netloc += f":{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit(("https", netloc, path, "", ""))


def _safe_upstream_path(raw: str) -> str | None:
    """Validate one relative path under the fixed upstream origin."""
    decoded = _fully_unquote_path(str(raw or ""))
    if decoded is None:
        return None
    clean = decoded.strip().lstrip("/")
    if not clean:
        return ""
    if "\\" in clean or "?" in clean or "#" in clean:
        return None
    if any(ord(ch) < 32 for ch in clean):
        return None
    segments = clean.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        return None
    root = segments[0]
    if len(segments) == 1 and root in _ALLOWED_ROOT_FILES:
        return clean
    return clean if root in _ALLOWED_PATH_ROOTS else None


async def _bounded_request_body(request: Request) -> bytes:
    raw_length = request.headers.get("content-length")
    if raw_length is not None:
        try:
            declared_length = int(raw_length)
        except ValueError as exc:
            raise HTTPException(400, "invalid content-length") from exc
        if declared_length < 0:
            raise HTTPException(400, "invalid content-length")
        if declared_length > _REQUEST_BODY_LIMIT:
            raise HTTPException(413, "request body too large")
    if request.method.upper() not in _BODY_METHODS:
        return b""

    chunks = bytearray()
    async for chunk in request.stream():
        if not chunk:
            continue
        chunks.extend(chunk)
        if len(chunks) > _REQUEST_BODY_LIMIT:
            raise HTTPException(413, "request body too large")
    return bytes(chunks)


def _upstream_headers(request: Request, origin: str) -> dict[str, str]:
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() in _FORWARDED_REQUEST_HEADERS
    }
    # Never forward the browser's host Origin/Referer. Fixed upstream values
    # reveal no Octopus URL or principal state and keep public upstream checks
    # deterministic.
    parsed = urlsplit(origin)
    headers["Origin"] = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    headers["Referer"] = origin + "/"
    return headers


def _response_headers(response: httpx.Response) -> dict[str, str]:
    headers = {
        name: value
        for name, value in response.headers.items()
        if name.lower() in _FORWARDED_RESPONSE_HEADERS
    }
    headers.update(_SECURITY_RESPONSE_HEADERS)
    return headers


def register_origin_proxy(
    router: APIRouter,
    *,
    base_url: str,
    http_client: httpx.AsyncClient | None = None,
) -> bool:
    """Mount ``/origin/*`` only for an unambiguous HTTPS upstream."""
    origin = secure_upstream_origin(base_url)
    if not origin:
        _logger.warning("mx2025_viewer proxy rejected: upstream must be a valid HTTPS URL")
        return False

    async def proxy_http(request: Request, upstream_path: str):
        safe_path = _safe_upstream_path(upstream_path)
        if safe_path is None:
            raise HTTPException(404, "upstream path not available")
        body = await _bounded_request_body(request)

        owns_client = http_client is None
        client = http_client or httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=60.0, write=30.0, pool=5.0),
            follow_redirects=False,
            trust_env=False,
        )
        target = f"{origin}/{safe_path}"
        try:
            upstream_request = client.build_request(
                request.method,
                target,
                params=list(request.query_params.multi_items()),
                headers=_upstream_headers(request, origin),
                content=body or None,
            )
            # A caller-provided client may have default headers/cookies. Strip
            # these again after merging so tests and future reuse cannot
            # accidentally reintroduce host credentials.
            for sensitive_header in ("authorization", "proxy-authorization", "cookie"):
                upstream_request.headers.pop(sensitive_header, None)
            upstream_resp = await client.send(upstream_request, stream=True, auth=None)
        except (httpx.HTTPError, OSError, ValueError) as exc:
            if owns_client:
                await client.aclose()
            _logger.warning("mx2025_viewer upstream unavailable (%s)", type(exc).__name__)
            return JSONResponse(
                {"detail": "MX upstream temporarily unavailable"},
                status_code=503,
                headers={"Retry-After": "10", **_SECURITY_RESPONSE_HEADERS},
            )

        # Mock/custom transports may return an already-buffered response even
        # when ``stream=True``. Production HTTP transports remain streaming;
        # support both without trying to consume a response twice.
        buffered_body = upstream_resp.content if upstream_resp.is_stream_consumed else None

        async def stream_body() -> AsyncIterator[bytes]:
            try:
                if buffered_body is not None:
                    if buffered_body:
                        yield buffered_body
                else:
                    async for chunk in upstream_resp.aiter_raw():
                        if chunk:
                            yield chunk
            finally:
                await upstream_resp.aclose()
                if owns_client:
                    await client.aclose()

        return StreamingResponse(
            stream_body(),
            status_code=upstream_resp.status_code,
            headers=_response_headers(upstream_resp),
        )

    # One method per route keeps OpenAPI operation IDs deterministic.
    for method in ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"):
        router.add_api_route(
            "/origin/{upstream_path:path}",
            proxy_http,
            methods=[method],
            operation_id=f"mx2025_viewer_proxy_{method.lower()}",
            include_in_schema=False,
        )

    _logger.info("mx2025_viewer origin proxy enabled for a validated HTTPS upstream")
    return True


__all__ = ["register_origin_proxy", "secure_upstream_origin"]
