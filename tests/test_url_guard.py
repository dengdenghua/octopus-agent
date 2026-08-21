"""Implementation note."""

from __future__ import annotations

import socket

import pytest

from runtime.safety.auth import check_url, is_safe_url

# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestScheme:
    @pytest.fixture(autouse=True)
    def _resolve_example_to_public(self, monkeypatch):
        """Sandbox DNS maps ``example.com`` → 198.18.0.43 (reserved); these
        scheme tests just assert http/https are allowed, so pin it public."""
        import runtime.safety.auth.url_guard as _guard

        monkeypatch.setattr(
            _guard.socket,
            "getaddrinfo",
            lambda host, *a, **kw: [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("142.250.72.14", 0),
                )
            ],
        )

    def test_http_allowed(self):
        v = check_url("http://example.com/path")
        assert v.allow

    def test_https_allowed(self):
        v = check_url("https://example.com/path")
        assert v.allow

    @pytest.mark.parametrize(
        "scheme",
        [
            "file:///etc/passwd",
            "ftp://internal.srv/data",
            "gopher://localhost",
            "javascript:alert(1)",
            "data:text/html,<script>",
            "ssh://root@10.0.0.1",
        ],
    )
    def test_unsafe_scheme_blocked(self, scheme):
        v = check_url(scheme)
        assert not v.allow
        assert "scheme" in v.reason

    def test_empty_url_blocked(self):
        v = check_url("")
        assert not v.allow
        assert "empty" in v.reason

    def test_malformed_url_blocked(self):
        v = check_url("not a url at all")
        # Implementation note.
        assert not v.allow

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com:bad/path",
            "https://example.com:99999/path",
            "https://example.com:0/path",
        ],
    )
    def test_invalid_port_blocked(self, url):
        v = check_url(url)
        assert not v.allow
        assert "invalid_port" in v.reason


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestDirectIP:
    @pytest.mark.parametrize(
        "url,reason_kw",
        [
            ("http://127.0.0.1/x", "private_ip"),
            ("http://127.0.0.1:8080/admin", "private_ip"),
            ("http://169.254.169.254/latest/meta-data/", "private_ip"),
            ("http://10.0.0.1/", "private_ip"),
            ("http://172.16.1.2/", "private_ip"),
            ("http://172.31.255.254/", "private_ip"),
            ("http://192.168.1.1/", "private_ip"),
            ("http://0.0.0.0/", "private_ip"),
            ("http://[::1]/", "private_ip"),
            ("http://[fe80::1]/", "private_ip"),
            ("http://[fd00:ec2::254]/", "blocked_host"),  # Implementation note.
        ],
    )
    def test_private_ip_blocked(self, url, reason_kw):
        v = check_url(url)
        assert not v.allow
        assert reason_kw in v.reason

    def test_public_ip_allowed(self):
        v = check_url("http://8.8.8.8/")
        assert v.allow

    def test_allow_private_flag_lets_through(self):
        """Implementation note."""
        v = check_url("http://10.0.0.1/internal-api", allow_private=True)
        assert v.allow


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestBlockedHostnames:
    @pytest.mark.parametrize(
        "url,reason_kw",
        [
            ("http://localhost/x", "blocked_host"),
            ("http://LOCALHOST/x", "blocked_host"),
            ("http://metadata.google.internal/", "blocked_host"),
            ("http://metadata.azure.internal/", "blocked_host"),
        ],
    )
    def test_special_hosts_blocked(self, url, reason_kw):
        v = check_url(url)
        assert not v.allow
        assert reason_kw in v.reason

    @pytest.mark.parametrize(
        "url",
        [
            "http://my-app.internal/api",
            "http://foo.local/",
            "http://svc.svc.cluster.local/",
            "http://host.lan/",
        ],
    )
    def test_internal_suffixes_blocked(self, url):
        v = check_url(url)
        assert not v.allow
        assert "blocked_suffix" in v.reason

    def test_public_subdomain_of_internal_not_matched(self, monkeypatch):
        """Implementation note."""
        import runtime.safety.auth.url_guard as guard

        def fake_resolve(*a, **kw):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("142.250.72.14", 0),  # Implementation note.
                )
            ]

        monkeypatch.setattr(guard.socket, "getaddrinfo", fake_resolve)

        v = check_url("http://internal.example.com/")
        assert v.allow


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestDNSRebinding:
    def test_hostname_resolving_to_private_blocked(self, monkeypatch):
        """Implementation note."""
        import runtime.safety.auth.url_guard as guard

        def fake_getaddrinfo(host, *a, **kw):
            # Implementation note.
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("10.0.0.5", 0),
                )
            ]

        monkeypatch.setattr(guard.socket, "getaddrinfo", fake_getaddrinfo)

        v = check_url("http://attacker-example.com/")
        assert not v.allow
        assert "dns_resolves_to_private" in v.reason

    def test_hostname_resolving_to_public_allowed(self, monkeypatch):
        import runtime.safety.auth.url_guard as guard

        def fake_getaddrinfo(host, *a, **kw):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("142.250.72.14", 0),  # Implementation note.
                )
            ]

        monkeypatch.setattr(guard.socket, "getaddrinfo", fake_getaddrinfo)

        v = check_url("http://legit.example/")
        assert v.allow

    def test_fake_ip_proxy_pool_is_treated_as_public(self, monkeypatch):
        """198.18.0.0/15 is the Clash/Surge fake-ip pool standing in for the
        whole public internet — it must not be flagged as a private/SSRF
        target or a fake-ip proxy environment can never reach any external
        MCP/OAuth endpoint."""
        import runtime.safety.auth.url_guard as guard

        def fake_getaddrinfo(host, *a, **kw):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("198.18.0.21", 0),
                )
            ]

        monkeypatch.setattr(guard.socket, "getaddrinfo", fake_getaddrinfo)

        v = check_url("https://mcp.linear.app/mcp")
        assert v.allow
        assert "private" not in v.reason

    def test_dns_failure_fails_closed(self, monkeypatch):
        """Implementation note."""
        import runtime.safety.auth.url_guard as guard

        def fake_getaddrinfo(host, *a, **kw):
            raise socket.gaierror("name not known")

        monkeypatch.setattr(guard.socket, "getaddrinfo", fake_getaddrinfo)

        v = check_url("http://nonexistent.example/")
        assert not v.allow
        assert "dns_resolution_failed" in v.reason

    def test_resolve_dns_flag_skipped(self, monkeypatch):
        """Implementation note."""
        import runtime.safety.auth.url_guard as guard

        call_count = [0]

        def fake_getaddrinfo(*a, **kw):
            call_count[0] += 1
            raise socket.gaierror("should not be called")

        monkeypatch.setattr(guard.socket, "getaddrinfo", fake_getaddrinfo)

        v = check_url("http://example.com/", resolve_dns=False)
        assert v.allow
        assert call_count[0] == 0


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class TestIsSafeURL:
    def test_shortcut_matches_check_url_allow(self):
        assert is_safe_url("http://8.8.8.8/") == check_url("http://8.8.8.8/").allow
        assert is_safe_url("http://127.0.0.1/") == check_url("http://127.0.0.1/").allow

    def test_allow_private_shortcut(self):
        assert is_safe_url("http://10.0.0.1/", allow_private=True)


# ═══════════════════════════════════════════════════════════
# Bounded streaming reads
# ═══════════════════════════════════════════════════════════


class TestSafeHttpxRequestStreamingCap:
    def test_caller_cannot_override_supported_response_encodings(self):
        import runtime.safety.auth.url_guard as guard

        with pytest.raises(ValueError, match="Accept-Encoding is managed"):
            guard.safe_httpx_request(
                "GET",
                "https://downloads.example/catalog.json",
                headers={"Accept-Encoding": "br"},
                read_cap_bytes=32,
            )

    def test_legacy_urlopen_uses_safe_redirects_and_bounded_read(self, monkeypatch):
        import runtime.safety.auth.url_guard as guard

        captured: dict[str, object] = {}

        class _Headers(dict):
            pass

        class _Response:
            content = b"abcdef"
            headers = _Headers({"content-type": "text/plain"})

            @staticmethod
            def raise_for_status() -> None:
                return None

        def _request(method, url, **kwargs):
            captured.update({"method": method, "url": url, **kwargs})
            return _Response()

        monkeypatch.setattr(guard, "safe_httpx_request", _request)

        body, headers = guard.safe_urlopen(
            "https://downloads.example/page",
            timeout=2.5,
            read_cap_bytes=5,
        )

        assert body == b"abcde"
        assert headers == {
            "Content-Type": "text/plain",
            "X-Octopus-Truncated": "true",
        }
        assert captured == {
            "method": "GET",
            "url": "https://downloads.example/page",
            "timeout": 2.5,
            "allow_private": False,
            "follow_redirects": True,
            "read_cap_bytes": 6,
        }

    def test_pins_tcp_ip_but_preserves_tls_sni(self, monkeypatch):
        import httpx

        import runtime.safety.auth.url_guard as guard

        captured: dict[str, object] = {}

        class _Transport(httpx.BaseTransport):
            def handle_request(self, request):
                captured["connect_host"] = request.url.host
                captured["host_header"] = request.headers["Host"]
                captured["sni_hostname"] = request.extensions.get("sni_hostname")
                return httpx.Response(200, request=request, content=b"ok")

        monkeypatch.setattr(httpx, "HTTPTransport", _Transport)
        monkeypatch.setattr(
            guard,
            "check_url",
            lambda url, **kwargs: guard.URLVerdict(
                True,
                url,
                resolved_ip="203.0.113.10",
            ),
        )

        response = guard.safe_httpx_request(
            "GET",
            "https://downloads.example:8443/catalog.json",
            headers={"host": "attacker.invalid"},
        )

        assert response.content == b"ok"
        assert captured == {
            "connect_host": "203.0.113.10",
            "host_header": "downloads.example:8443",
            "sni_hostname": "downloads.example",
        }

    def test_aborts_before_reading_past_cap(self, monkeypatch):
        import httpx

        import runtime.safety.auth.url_guard as guard

        yielded: list[bytes] = []
        closed: list[bool] = []

        class _Stream(httpx.SyncByteStream):
            def __iter__(self):
                for chunk in (b"abc", b"def", b"must-not-be-read"):
                    yielded.append(chunk)
                    yield chunk

            def close(self) -> None:
                closed.append(True)

        class _Transport(httpx.BaseTransport):
            def handle_request(self, request):
                return httpx.Response(200, request=request, stream=_Stream())

        monkeypatch.setattr(httpx, "HTTPTransport", _Transport)
        monkeypatch.setattr(
            guard,
            "check_url",
            lambda url, **kwargs: guard.URLVerdict(
                True,
                url,
                resolved_ip="203.0.113.10",
            ),
        )

        with pytest.raises(ValueError, match="response exceeds 5 bytes"):
            guard.safe_httpx_request(
                "GET",
                "https://downloads.example/archive.tar.gz",
                read_cap_bytes=5,
            )

        assert yielded == [b"abc", b"def"]
        assert closed == [True]

    def test_returns_regular_response_within_cap(self, monkeypatch):
        import httpx

        import runtime.safety.auth.url_guard as guard

        class _Stream(httpx.SyncByteStream):
            def __iter__(self):
                yield b'{"ok":'
                yield b"true}"

        class _Transport(httpx.BaseTransport):
            def handle_request(self, request):
                return httpx.Response(
                    200,
                    headers={"Content-Type": "application/json"},
                    request=request,
                    stream=_Stream(),
                )

        monkeypatch.setattr(httpx, "HTTPTransport", _Transport)
        monkeypatch.setattr(
            guard,
            "check_url",
            lambda url, **kwargs: guard.URLVerdict(
                True,
                url,
                resolved_ip="203.0.113.10",
            ),
        )

        response = guard.safe_httpx_request(
            "GET",
            "https://downloads.example/catalog.json",
            read_cap_bytes=32,
        )

        assert response.content == b'{"ok":true}'
        assert response.json() == {"ok": True}

    def test_detached_response_does_not_decode_compressed_body_twice(self, monkeypatch):
        import gzip

        import httpx

        import runtime.safety.auth.url_guard as guard

        encoded = gzip.compress(b'{"ok":true}')

        class _Stream(httpx.SyncByteStream):
            def __iter__(self):
                yield encoded

        class _Transport(httpx.BaseTransport):
            def handle_request(self, request):
                return httpx.Response(
                    200,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Encoding": "gzip",
                        "Content-Length": str(len(encoded)),
                        "Transfer-Encoding": "chunked",
                    },
                    request=request,
                    stream=_Stream(),
                )

        monkeypatch.setattr(httpx, "HTTPTransport", _Transport)
        monkeypatch.setattr(
            guard,
            "check_url",
            lambda url, **kwargs: guard.URLVerdict(
                True,
                url,
                resolved_ip="203.0.113.10",
            ),
        )

        response = guard.safe_httpx_request(
            "GET",
            "https://downloads.example/catalog.json",
            read_cap_bytes=32,
        )

        assert response.content == b'{"ok":true}'
        assert response.json() == {"ok": True}
        assert "content-encoding" not in response.headers
        assert "transfer-encoding" not in response.headers
        assert response.headers["content-length"] == str(len(response.content))

    def test_streaming_cap_applies_after_content_decoding(self, monkeypatch):
        import gzip

        import httpx

        import runtime.safety.auth.url_guard as guard

        encoded = gzip.compress(b"a" * 4096)

        class _Stream(httpx.SyncByteStream):
            def __iter__(self):
                yield encoded

        class _Transport(httpx.BaseTransport):
            def handle_request(self, request):
                return httpx.Response(
                    200,
                    headers={"Content-Encoding": "gzip"},
                    request=request,
                    stream=_Stream(),
                )

        monkeypatch.setattr(httpx, "HTTPTransport", _Transport)
        monkeypatch.setattr(
            guard,
            "check_url",
            lambda url, **kwargs: guard.URLVerdict(
                True,
                url,
                resolved_ip="203.0.113.10",
            ),
        )

        with pytest.raises(ValueError, match="response exceeds 1024 bytes"):
            guard.safe_httpx_request(
                "GET",
                "https://downloads.example/archive.json",
                read_cap_bytes=1024,
            )

    def test_unadvertised_content_encoding_fails_closed(self, monkeypatch):
        import httpx

        import runtime.safety.auth.url_guard as guard

        closed: list[bool] = []

        class _Stream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"opaque"

            def close(self) -> None:
                closed.append(True)

        class _Transport(httpx.BaseTransport):
            def handle_request(self, request):
                return httpx.Response(
                    200,
                    headers={"Content-Encoding": "x-octopus-unsupported"},
                    request=request,
                    stream=_Stream(),
                )

        monkeypatch.setattr(httpx, "HTTPTransport", _Transport)
        monkeypatch.setattr(
            guard,
            "check_url",
            lambda url, **kwargs: guard.URLVerdict(
                True,
                url,
                resolved_ip="203.0.113.10",
            ),
        )

        with pytest.raises(httpx.DecodingError, match="unadvertised content encoding"):
            guard.safe_httpx_request(
                "GET",
                "https://downloads.example/catalog.json",
                read_cap_bytes=32,
            )

        assert closed == [True]

    def test_malformed_advertised_encoding_fails_closed_and_closes(self, monkeypatch):
        import httpx

        import runtime.safety.auth.url_guard as guard

        closed: list[bool] = []

        class _Stream(httpx.SyncByteStream):
            def __iter__(self):
                yield b"not-a-gzip-stream"

            def close(self) -> None:
                closed.append(True)

        class _Transport(httpx.BaseTransport):
            def handle_request(self, request):
                return httpx.Response(
                    200,
                    headers={"Content-Encoding": "gzip"},
                    request=request,
                    stream=_Stream(),
                )

        monkeypatch.setattr(httpx, "HTTPTransport", _Transport)
        monkeypatch.setattr(
            guard,
            "check_url",
            lambda url, **kwargs: guard.URLVerdict(
                True,
                url,
                resolved_ip="203.0.113.10",
            ),
        )

        with pytest.raises(httpx.DecodingError):
            guard.safe_httpx_request(
                "GET",
                "https://downloads.example/catalog.json",
                read_cap_bytes=32,
            )

        assert closed == [True]


# ═══════════════════════════════════════════════════════════
# Implementation note.
# ═══════════════════════════════════════════════════════════


class _FakeHTTPX:
    """Implementation note."""

    def __init__(self):
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(url)
        resp = type("Resp", (), {})()
        resp.url = url
        resp.status_code = 200
        resp.text = "ok"
        resp.headers = {"content-type": "text/html"}
        return resp

    def close(self):
        pass


class TestFetchURLIntegration:
    def test_ssrf_url_blocked_before_httpx(self):
        from runtime.execution.suckers.web_skills import _fetch_url

        fake = _FakeHTTPX()
        result = _fetch_url(
            url="http://169.254.169.254/latest/meta-data/",
            client=fake,
        )
        assert "error" in result
        assert "ssrf_blocked" in result["error"]
        assert result.get("blocked") is True
        # Implementation note.
        assert fake.calls == []

    def test_public_url_passes_through(self, monkeypatch):
        """Implementation note."""
        import runtime.safety.auth.url_guard as guard

        def fake_resolve(host, *a, **kw):
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    socket.IPPROTO_TCP,
                    "",
                    ("142.250.72.14", 0),
                )
            ]

        monkeypatch.setattr(guard.socket, "getaddrinfo", fake_resolve)

        from runtime.execution.suckers.web_skills import _fetch_url

        fake = _FakeHTTPX()
        result = _fetch_url(url="https://example.com/", client=fake)
        assert "error" not in result
        assert fake.calls == ["https://example.com/"]

    def test_allow_private_flag_lets_internal_through(self):
        from runtime.execution.suckers.web_skills import _fetch_url

        fake = _FakeHTTPX()
        result = _fetch_url(
            url="http://10.0.0.1/internal-api",
            client=fake,
            allow_private=True,
        )
        assert "error" not in result
        assert fake.calls == ["http://10.0.0.1/internal-api"]

    def test_file_scheme_blocked(self):
        from runtime.execution.suckers.web_skills import _fetch_url

        fake = _FakeHTTPX()
        result = _fetch_url(url="file:///etc/passwd", client=fake)
        assert "error" in result
        assert "scheme" in result["error"].lower() or "ssrf" in result["error"].lower()
        assert fake.calls == []
