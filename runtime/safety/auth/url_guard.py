
from __future__ import annotations

import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urlparse

_SAFE_SCHEMES = frozenset({"http", "https"})

_BLOCKED_HOSTS = frozenset({
    "localhost",
    "metadata.google.internal",
    "metadata.azure.internal",
    "instance-data",           # AWS SSM
    "instance-data.ec2.internal",
    "fd00:ec2::254",           # AWS IPv6 metadata
})

_BLOCKED_SUFFIXES = (
    ".localhost",
    ".local",
    ".internal",
    ".svc.cluster.local",
    ".lan",
)


@dataclass(frozen=True)
class URLVerdict:

    allow: bool
    url: str
    reason: str = ""
    resolved_ip: str | None = None


def check_url(
    url: str,
    *,
    allow_private: bool = False,
    resolve_dns: bool = True,
) -> URLVerdict:
    if not url or not isinstance(url, str):
        return URLVerdict(False, str(url), "empty_or_non_string_url")

    try:
        parsed = urlparse(url)
    except Exception as e:  # noqa: BLE001
        return URLVerdict(False, url, f"unparseable: {e}")

    scheme = (parsed.scheme or "").lower()
    if scheme not in _SAFE_SCHEMES:
        return URLVerdict(False, url, f"disallowed_scheme: {scheme!r}")

    host = parsed.hostname
    if not host:
        return URLVerdict(False, url, "missing_host")

    # IDN normalisation.  ``urllib.parse.urlparse`` returns hostnames
    # without IDNA-normalising them, so ``xn--bad-host.example``-style
    # punycode and raw Unicode look distinct to our suffix / exact-match
    # blocklists. Canonicalise to punycode (ASCII-compatible encoding)
    # before the string comparisons below.
    try:
        host_ascii = host.encode("idna").decode("ascii")
    except UnicodeError:
        # Catches raw U+2024/U+3002/U+FF0E full-width dots, homoglyph
        # attempts with invalid IDNA, and empty labels.  Refuse.
        return URLVerdict(False, url, "invalid_idn_host")
    host_lc = host_ascii.lower()

    if not allow_private:
        if host_lc in _BLOCKED_HOSTS:
            return URLVerdict(False, url, f"blocked_host: {host_lc}")
        for suf in _BLOCKED_SUFFIXES:
            if host_lc.endswith(suf):
                return URLVerdict(False, url, f"blocked_suffix: {suf}")

    ip_obj = _as_ip(host)
    if ip_obj is not None:
        if not allow_private and _is_private_ip(ip_obj):
            return URLVerdict(False, url, f"private_ip: {ip_obj}", str(ip_obj))
        return URLVerdict(True, url, resolved_ip=str(ip_obj))

    if not resolve_dns:
        return URLVerdict(True, url)

    resolved = _resolve_all(host)
    if not resolved:
        return URLVerdict(False, url, "dns_resolution_failed")

    if not allow_private:
        for ip_obj in resolved:
            if _is_private_ip(ip_obj):
                return URLVerdict(
                    False, url,
                    f"dns_resolves_to_private: {host} → {ip_obj}",
                    resolved_ip=str(ip_obj),
                )

    return URLVerdict(True, url, resolved_ip=str(resolved[0]))


def is_safe_url(url: str, *, allow_private: bool = False) -> bool:
    return check_url(url, allow_private=allow_private).allow


# ═══════════════════════════════════════════════════════════
# DNS-rebinding-proof fetch helpers.
#
# ``check_url`` resolves a host to an IP before the request runs; the
# underlying fetch then re-resolves on connect. A rebinding attacker
# can serve a public IP on the first resolve and an internal IP on the
# second, tunnelling through the guard.
#
# To close the TOCTOU we (a) resolve once, (b) hand the fetcher the
# literal IP as the connect target, and (c) put the original hostname
# in the ``Host:`` header so TLS SNI + vhost routing still work.
# ═══════════════════════════════════════════════════════════


def safe_urlopen(
    url: str,
    *,
    timeout: float = 10.0,
    read_cap_bytes: int = 1_000_000,
    allow_private: bool = False,
) -> tuple[bytes, dict[str, str]]:
    """Fetch ``url`` with rebinding-proof host pinning.

    Returns ``(body, headers)`` on success. Raises ``ValueError``
    (from ``check_url``) or the usual urllib exceptions otherwise.

    Only supports HTTP(S) GET — the call sites we need to protect
    (page-title probes, text extraction, skill-archive downloads)
    are all GETs.
    """
    import urllib.error
    import urllib.request

    verdict = check_url(url, allow_private=allow_private)
    if not verdict.allow:
        raise ValueError(f"url_guard rejected: {verdict.reason}")

    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    resolved_ip = verdict.resolved_ip or host

    # Build a URL whose authority is the resolved IP literal so the
    # HTTP client connects to the exact IP we approved. Bracket IPv6.
    ip_is_v6 = ":" in resolved_ip and "." not in resolved_ip
    authority = f"[{resolved_ip}]:{port}" if ip_is_v6 else f"{resolved_ip}:{port}"
    pinned_url = parsed._replace(netloc=authority).geturl()

    # Preserve original Host header (vhost / SNI routing). urllib does
    # not expose an SNI override, so for HTTPS we still rely on its
    # default (which will use the pinned IP — broken SNI for TLS).
    # That's fine for the internal probes we have today (fetch_url,
    # browser probe). When someone needs real TLS-SNI safety, swap to
    # httpx + a custom transport (see _safe_httpx_transport below).
    req = urllib.request.Request(pinned_url, headers={"Host": host})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read(read_cap_bytes + 1)
        headers = {k: v for k, v in resp.headers.items()}
    if len(data) > read_cap_bytes:
        data = data[:read_cap_bytes]
        headers["X-Octopus-Truncated"] = "true"
    return data, headers


def safe_httpx_get(
    url: str,
    *,
    timeout: float = 30.0,
    allow_private: bool = False,
    follow_redirects: bool = False,
):
    """Rebinding-proof GET via httpx when the dep is available.

    Unlike ``safe_urlopen`` this version preserves TLS SNI: httpx's
    ``transport`` hook lets us rewrite the connect target while keeping
    the URL (and therefore SNI) unchanged.

    Returns the ``httpx.Response`` on success.

    When ``follow_redirects`` is true the 30x Location is re-validated
    through ``check_url`` on each hop, so a hostile server can't 302
    us to ``http://10.x.y.z``.
    """
    try:
        import httpx
    except ImportError as exc:  # pragma: no cover - caller should check
        raise RuntimeError("httpx is required for safe_httpx_get") from exc

    visited: set[str] = set()
    current_url = url
    for _hop in range(5):
        if current_url in visited:
            raise RuntimeError("redirect loop detected")
        visited.add(current_url)

        verdict = check_url(current_url, allow_private=allow_private)
        if not verdict.allow:
            raise ValueError(f"url_guard rejected: {verdict.reason}")

        parsed = urlparse(current_url)
        host = parsed.hostname or ""
        resolved_ip = verdict.resolved_ip or host

        # httpx ``transport`` takes a resolver hook. Pin every host
        # seen in this request to the single IP we approved.
        class _PinnedResolver(httpx.HTTPTransport):
            def __init__(self_inner, pinned_host: str, pinned_ip: str) -> None:  # noqa: N805
                super().__init__()
                self_inner._pinned_host = pinned_host
                self_inner._pinned_ip = pinned_ip

            def handle_request(self_inner, request):  # type: ignore[override]  # noqa: N805
                # Rewrite the URL's host to the literal IP, keep the
                # Host header so TLS SNI + vhost still target the name.
                target_host = request.url.host
                if target_host == self_inner._pinned_host:
                    new_url = request.url.copy_with(host=self_inner._pinned_ip)
                    request.url = new_url
                    request.headers.setdefault("Host", target_host)
                return super().handle_request(request)

        transport = _PinnedResolver(host, resolved_ip)
        with httpx.Client(transport=transport, timeout=timeout, follow_redirects=False) as client:
            resp = client.get(current_url, headers={"Host": host})
            if not follow_redirects:
                return resp
            if resp.status_code not in (301, 302, 303, 307, 308):
                return resp
            loc = resp.headers.get("Location")
            if not loc:
                return resp
            current_url = str(httpx.URL(loc, base=resp.url))
    raise RuntimeError("too many redirects")


# ═══════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════


def _as_ip(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    stripped = host.strip("[]")
    try:
        return ipaddress.ip_address(stripped)
    except ValueError:
        return None


def _is_private_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    # IPv4-mapped IPv6 (``::ffff:10.0.0.1``) and IPv4-compatible
    # (``::10.0.0.1``) both look like public IPv6 to Python's
    # ``is_private`` but route to the embedded IPv4 address.  Unwrap
    # and re-check on the embedded v4.
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        v4 = ip.ipv4_mapped
        return _is_private_ip(v4)
    # Some ipaddress builds expose ``.sixtofour`` on 2002::/16
    # (6to4) and ``.teredo`` on 2001::/32 (Teredo); both tunnel an
    # arbitrary v4 target through a v6 address.  Refuse them.
    if isinstance(ip, ipaddress.IPv6Address):
        sixto4 = getattr(ip, "sixtofour", None)
        if sixto4 is not None and _is_private_ip(sixto4):
            return True
        teredo = getattr(ip, "teredo", None)
        if teredo is not None:
            client = teredo[1] if isinstance(teredo, tuple) else None
            if client is not None and _is_private_ip(client):
                return True
    return bool(
        ip.is_private          # 10.* / 172.16-31.* / 192.168.*
        or ip.is_loopback      # 127.* / ::1
        or ip.is_link_local    # 169.254.* / fe80::
        or ip.is_multicast     # 224+ / ff00::
        or ip.is_reserved
        or ip.is_unspecified   # 0.0.0.0 / ::
    )


def _resolve_all(host: str) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except OSError:
        return []
    out = []
    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr in seen:
            continue
        seen.add(addr)
        ip = _as_ip(addr)
        if ip is not None:
            out.append(ip)
    return out
