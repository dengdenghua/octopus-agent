"""Tests for runtime.sensing.gateway.remote_transport + remote_backends_router."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform import feature_flags as ff
from runtime.safety.auth import Identity, IdentityStore
from runtime.sensing.gateway.remote_backends_router import (
    create_remote_backends_router,
)
from runtime.sensing.gateway.remote_transport import (
    BackendRegistry,
    RemoteBackend,
    SshTunnel,
    SshTunnelError,
    SshTunnelForwarder,
    _validate_url,
    connect_remote_backend,
    health_check,
    proxy_request,
)


@pytest.fixture(autouse=True)
def _reset_flags() -> Iterator[None]:
    original = dict(ff._SPECS)
    yield
    ff._SPECS.clear()
    ff._SPECS.update(original)
    ff._SNAPSHOT = None
    ff._FILE_PATH = None


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "remote_backends.json"


# ─── URL validation ─────────────────────────────────────────


def test_url_must_have_scheme() -> None:
    with pytest.raises(ValueError):
        _validate_url("example.com")


def test_url_strips_trailing_slash() -> None:
    assert _validate_url("https://example.com/") == "https://example.com"


def test_url_rejects_empty() -> None:
    with pytest.raises(ValueError):
        _validate_url("   ")


def test_url_rejects_embedded_credentials_and_fragment() -> None:
    with pytest.raises(ValueError, match="credentials"):
        _validate_url("https://user:pass@example.com")
    with pytest.raises(ValueError, match="fragment"):
        _validate_url("https://example.com/#secret")


# ─── Registry round-trip ────────────────────────────────────


def test_registry_starts_empty(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    assert reg.list() == []


def test_add_then_list(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    b = reg.add(name="prod", url="https://api.example.com:8000")
    assert b.id
    assert b.name == "prod"
    assert b.url == "https://api.example.com:8000"
    assert reg.list() == [b]
    public = b.to_dict()
    assert public["transport"] == "direct"
    assert public["capabilities"] == {
        "http": True,
        "realtime": True,
        "ssh_tunnel": False,
    }


def test_add_persists_across_instances(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    reg.add(name="staging", url="http://staging.local:8000")

    reloaded = BackendRegistry(store_path)
    backends = reloaded.list()
    assert len(backends) == 1
    assert backends[0].name == "staging"


def test_auth_token_is_encrypted_and_survives_reload(store_path: Path) -> None:
    token = "secret-remote-token"
    reg = BackendRegistry(store_path)
    backend = reg.add(
        name="secured",
        url="https://secured.example.com",
        auth_token=token,
    )

    assert backend.has_auth is True
    assert reg.auth_token(backend.id) == token
    assert token not in store_path.read_text(encoding="utf-8")
    credentials_file = store_path.parent / ".remote-backend-credentials" / "credentials.v1.json"
    assert credentials_file.exists()
    assert token not in credentials_file.read_text(encoding="utf-8")

    reloaded = BackendRegistry(store_path)
    assert reloaded.get(backend.id).has_auth is True  # type: ignore[union-attr]
    assert reloaded.auth_token(backend.id) == token


def test_set_and_clear_auth_token(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    backend = reg.add(name="secured", url="https://secured.example.com")

    updated = reg.set_auth_token(backend.id, "replacement-token")
    assert updated is not None and updated.has_auth is True
    assert reg.auth_token(backend.id) == "replacement-token"

    cleared = reg.set_auth_token(backend.id, None)
    assert cleared is not None and cleared.has_auth is False
    assert reg.auth_token(backend.id) is None


def test_remove_clears_auth_token(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    backend = reg.add(
        name="secured",
        url="https://secured.example.com",
        auth_token="temporary-token",
    )

    assert reg.remove(backend.id) is True
    assert reg.auth_token(backend.id) is None


def test_add_rejects_duplicate_name(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    reg.add(name="dup", url="https://a.example.com")
    with pytest.raises(ValueError):
        reg.add(name="dup", url="https://b.example.com")


def test_add_with_ssh_tunnel_persists(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    reg.add(
        name="prod",
        url="http://localhost:8000",
        ssh=SshTunnel(host="bastion.example.com", user="ops", port=22),
    )
    reloaded = BackendRegistry(store_path)
    backend = reloaded.list()[0]
    assert backend.ssh is not None
    assert backend.ssh.host == "bastion.example.com"
    assert backend.ssh.user == "ops"
    assert backend.to_dict()["transport"] == "ssh_tunnel"
    assert backend.to_dict()["capabilities"]["ssh_tunnel"] is True


def test_registry_rejects_invalid_or_https_ssh_configuration(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    with pytest.raises(ValueError, match="configuration is invalid"):
        reg.add(
            name="unsafe",
            url="http://127.0.0.1:8000",
            ssh=SshTunnel(host="-oProxyCommand=bad"),
        )
    with pytest.raises(ValueError, match="must use http"):
        reg.add(
            name="tls-over-tunnel",
            url="https://127.0.0.1:8000",
            ssh=SshTunnel(host="bastion.example.com"),
        )


@pytest.mark.parametrize(
    "raw",
    [
        {"host": "-oProxyCommand=bad"},
        {"host": "host name"},
        {"host": "host", "user": "bad@user"},
        {"host": "host", "port": 0},
        {"host": "host", "connect_timeout": 121},
        {"host": "host", "identity_file": "bad\npath"},
    ],
)
def test_ssh_tunnel_rejects_unsafe_descriptor(raw: dict[str, Any]) -> None:
    assert SshTunnel.from_dict(raw) is None


def test_ssh_forwarder_builds_fail_closed_local_forward(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "runtime.sensing.gateway.remote_transport.shutil.which", lambda _: "/usr/bin/ssh"
    )
    backend = RemoteBackend(
        id="x",
        name="x",
        url="http://127.0.0.1:8000/base",
        ssh=SshTunnel(
            host="bastion.example.com",
            user="ops",
            port=2202,
            identity_file="/keys/id_ed25519",
        ),
    )

    argv = SshTunnelForwarder(backend)._argv(43123)

    assert argv[0] == "/usr/bin/ssh"
    assert "ExitOnForwardFailure=yes" in argv
    assert "BatchMode=yes" in argv
    assert "127.0.0.1:43123:127.0.0.1:8000" in argv
    assert argv[-1] == "ops@bastion.example.com"
    assert "StrictHostKeyChecking=no" not in argv


def test_ssh_forwarder_rejects_https_endpoint() -> None:
    backend = RemoteBackend(
        id="x",
        name="x",
        url="https://internal.example.com:8000",
        ssh=SshTunnel(host="bastion.example.com"),
    )
    with pytest.raises(SshTunnelError, match="must use http"):
        SshTunnelForwarder(backend)


def test_connect_remote_backend_never_silently_falls_back() -> None:
    events: list[str] = []
    backend = RemoteBackend(
        id="x",
        name="x",
        url="http://127.0.0.1:8000",
        ssh=SshTunnel(host="bastion.example.com"),
    )

    class _Forwarder:
        def __init__(self, configured: RemoteBackend) -> None:
            assert configured is backend

        def start(self) -> RemoteBackend:
            events.append("start")
            return RemoteBackend(
                id="x",
                name="x",
                url="http://127.0.0.1:43123",
                tunnel_active=True,
            )

        def close(self) -> None:
            events.append("close")

    with connect_remote_backend(backend, forwarder_factory=_Forwarder) as connected:
        assert connected.tunnel_active is True
        assert connected.url.endswith(":43123")
    assert events == ["start", "close"]


def test_remove(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    b = reg.add(name="x", url="https://x.example.com")
    assert reg.remove(b.id) is True
    assert reg.list() == []
    assert reg.remove("nonexistent") is False


def test_update_health(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    b = reg.add(name="x", url="https://x.example.com")
    assert b.last_health is None

    updated = reg.update_health(b.id, status="ok")
    assert updated is not None
    assert updated.last_health == "ok"
    assert updated.last_health_at is not None

    failed = reg.update_health(b.id, status="error", detail="HTTP 500")
    assert failed.last_health == "error"
    assert failed.health_detail == "HTTP 500"


def test_update_health_rejects_invalid_status(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    b = reg.add(name="x", url="https://x.example.com")
    with pytest.raises(ValueError):
        reg.update_health(b.id, status="weird")


def test_get_by_name(store_path: Path) -> None:
    reg = BackendRegistry(store_path)
    b = reg.add(name="prod", url="https://example.com")
    assert reg.get_by_name("prod") == b
    assert reg.get_by_name("missing") is None


# ─── Health check (HTTP mocked) ─────────────────────────────


class _StubResponse:
    def __init__(self, status_code: int, json_data: Any = None, text: str = "") -> None:
        self.status_code = status_code
        self._json = json_data
        self.text = text

    def json(self) -> Any:
        return self._json


class _StubClient:
    def __init__(self, response: _StubResponse | Exception) -> None:
        self._response = response
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append(("GET", url, kwargs))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response

    def request(self, method: str, url: str, **kwargs: Any) -> _StubResponse:
        self.calls.append((method, url, kwargs))
        if isinstance(self._response, Exception):
            raise self._response
        return self._response


def test_health_check_ok() -> None:
    backend = RemoteBackend(id="x", name="x", url="https://example.com")
    status, detail = health_check(backend, http_client=_StubClient(_StubResponse(200)))
    assert status == "ok"
    assert detail is None


def test_health_check_forwards_auth_token() -> None:
    backend = RemoteBackend(id="x", name="x", url="https://example.com")
    stub = _StubClient(_StubResponse(200))
    health_check(backend, http_client=stub, auth_token="remote-secret")
    assert stub.calls[0][2]["headers"] == {
        "Authorization": "Bearer remote-secret",
    }


def test_health_check_non_2xx() -> None:
    backend = RemoteBackend(id="x", name="x", url="https://example.com")
    status, detail = health_check(backend, http_client=_StubClient(_StubResponse(503)))
    assert status == "error"
    assert "503" in (detail or "")


def test_health_check_network_error() -> None:
    backend = RemoteBackend(id="x", name="x", url="https://example.com")
    status, detail = health_check(backend, http_client=_StubClient(ConnectionRefusedError("nope")))
    assert status == "error"
    assert "ConnectionRefusedError" in (detail or "")


# ─── Proxy ──────────────────────────────────────────────────


def test_proxy_returns_status_and_body() -> None:
    backend = RemoteBackend(id="x", name="x", url="https://example.com")
    response = _StubResponse(201, json_data={"ok": True})
    result = proxy_request(
        backend,
        method="POST",
        path="/api/echo",
        json={"hi": 1},
        http_client=_StubClient(response),
    )
    assert result["status_code"] == 201
    assert result["body"] == {"ok": True}


def test_proxy_forwards_auth_token() -> None:
    backend = RemoteBackend(id="x", name="x", url="https://example.com")
    stub = _StubClient(_StubResponse(200, json_data={"ok": True}))
    proxy_request(
        backend,
        method="GET",
        path="/api/echo",
        auth_token="remote-secret",
        http_client=stub,
    )
    assert stub.calls[0][2]["headers"] == {
        "Authorization": "Bearer remote-secret",
    }


def test_proxy_rejects_unsupported_method() -> None:
    backend = RemoteBackend(id="x", name="x", url="https://example.com")
    with pytest.raises(ValueError):
        proxy_request(
            backend,
            method="OPTIONS",
            path="/x",
            http_client=_StubClient(_StubResponse(200)),
        )


def test_proxy_wraps_exceptions() -> None:
    backend = RemoteBackend(id="x", name="x", url="https://example.com")
    result = proxy_request(
        backend,
        method="GET",
        path="/x",
        http_client=_StubClient(TimeoutError("slow")),
    )
    assert result["status_code"] == 0
    assert result["body"]["error"] == "proxy_failed"
    assert "TimeoutError" in result["body"]["detail"]


# ─── Router endpoints ──────────────────────────────────────


@pytest.fixture
def client(store_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_remote_backends_router(store_path=store_path))
    return TestClient(app)


@pytest.fixture
def secured_client(store_path: Path) -> tuple[TestClient, dict[str, str]]:
    store = IdentityStore()
    store.add(
        Identity(actor_id="alice", roles=("operator",)),
        api_key_plaintext="sk-alice",
    )
    app = FastAPI()
    app.include_router(
        create_remote_backends_router(
            store_path=store_path,
            identity_store=store,
            require_auth=True,
        )
    )
    return TestClient(app), {"Authorization": "Bearer sk-alice"}


def test_get_works_with_flag_off(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", raising=False)
    ff.reload()
    r = client.get("/api/remote-backends")
    assert r.status_code == 200
    assert r.json()["enabled"] is False
    assert r.json()["backends"] == []


def test_get_requires_auth_when_enabled(
    secured_client: tuple[TestClient, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, headers = secured_client
    monkeypatch.delenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", raising=False)
    ff.reload()

    assert client.get("/api/remote-backends").status_code == 401
    assert client.get("/api/remote-backends", headers=headers).status_code == 200


def test_post_blocked_when_flag_off(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", raising=False)
    ff.reload()
    r = client.post(
        "/api/remote-backends",
        json={"name": "x", "url": "https://example.com"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "remote_transport_disabled"


def test_post_then_get_with_flag_on(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    r = client.post(
        "/api/remote-backends",
        json={"name": "prod", "url": "https://api.example.com"},
    )
    assert r.status_code == 200
    bid = r.json()["backend"]["id"]

    listing = client.get("/api/remote-backends").json()
    assert listing["enabled"] is True
    assert any(b["id"] == bid for b in listing["backends"])


def test_post_stores_auth_without_returning_secret(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    store_path: Path,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    token = "top-secret-remote-token"
    response = client.post(
        "/api/remote-backends",
        json={
            "name": "secured",
            "url": "https://secured.example.com",
            "auth_token": token,
        },
    )
    assert response.status_code == 200
    assert response.json()["backend"]["has_auth"] is True
    assert token not in response.text
    assert token not in store_path.read_text(encoding="utf-8")


def test_credentials_endpoint_sets_and_clears_auth(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    backend_id = client.post(
        "/api/remote-backends",
        json={"name": "secured", "url": "https://secured.example.com"},
    ).json()["backend"]["id"]

    updated = client.put(
        f"/api/remote-backends/{backend_id}/credentials",
        json={"auth_token": "new-secret"},
    )
    assert updated.status_code == 200
    assert updated.json()["backend"]["has_auth"] is True
    assert "new-secret" not in updated.text

    cleared = client.put(
        f"/api/remote-backends/{backend_id}/credentials",
        json={"auth_token": ""},
    )
    assert cleared.status_code == 200
    assert cleared.json()["backend"]["has_auth"] is False


def test_credentials_endpoint_rejects_invalid_or_unknown(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    unknown = client.put(
        "/api/remote-backends/missing/credentials",
        json={"auth_token": "secret"},
    )
    assert unknown.status_code == 404

    backend_id = client.post(
        "/api/remote-backends",
        json={"name": "secured", "url": "https://secured.example.com"},
    ).json()["backend"]["id"]
    invalid = client.put(
        f"/api/remote-backends/{backend_id}/credentials",
        json={"auth_token": "line-one\nline-two"},
    )
    assert invalid.status_code == 400


def test_post_validates_payload(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    r = client.post("/api/remote-backends", json={"url": "https://x.com"})
    assert r.status_code == 400
    r = client.post("/api/remote-backends", json={"name": "x"})
    assert r.status_code == 400
    r = client.post("/api/remote-backends", json={"name": "x", "url": "no-scheme"})
    assert r.status_code == 400


def test_post_with_invalid_ssh_returns_400(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    r = client.post(
        "/api/remote-backends",
        json={
            "name": "x",
            "url": "https://x.com",
            "ssh": {"user": "ops"},  # missing host
        },
    )
    assert r.status_code == 400


def test_post_allows_private_endpoint_only_through_ssh(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    direct = client.post(
        "/api/remote-backends",
        json={"name": "direct", "url": "http://127.0.0.1:8000"},
    )
    assert direct.status_code == 400

    tunneled = client.post(
        "/api/remote-backends",
        json={
            "name": "tunneled",
            "url": "http://127.0.0.1:8000",
            "ssh": {"host": "bastion.example.com", "user": "ops"},
        },
    )
    assert tunneled.status_code == 200
    assert tunneled.json()["backend"]["transport"] == "ssh_tunnel"

    tunneled_https = client.post(
        "/api/remote-backends",
        json={
            "name": "bad-tunnel",
            "url": "https://127.0.0.1:8000",
            "ssh": {"host": "bastion.example.com"},
        },
    )
    assert tunneled_https.status_code == 400
    assert tunneled_https.json()["detail"]["reason"] == "ssh_tunnel_requires_http_endpoint"


def test_health_endpoint_uses_configured_ssh_tunnel(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    backend_id = client.post(
        "/api/remote-backends",
        json={
            "name": "tunneled",
            "url": "http://127.0.0.1:8000",
            "ssh": {"host": "bastion.example.com"},
        },
    ).json()["backend"]["id"]

    @contextmanager
    def _connected(configured: RemoteBackend) -> Iterator[RemoteBackend]:
        assert configured.ssh is not None
        yield RemoteBackend(
            id=configured.id,
            name=configured.name,
            url="http://127.0.0.1:43123",
            tunnel_active=True,
        )

    with (
        patch(
            "runtime.sensing.gateway.remote_backends_router.connect_remote_backend",
            _connected,
        ),
        patch(
            "runtime.sensing.gateway.remote_backends_router.health_check",
            return_value=("ok", None),
        ) as mocked_health,
    ):
        response = client.post(f"/api/remote-backends/{backend_id}/health")

    assert response.status_code == 200
    connected = mocked_health.call_args.args[0]
    assert connected.tunnel_active is True
    assert connected.url == "http://127.0.0.1:43123"


def test_delete_known_backend(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    bid = client.post(
        "/api/remote-backends",
        json={"name": "x", "url": "https://x.com"},
    ).json()["backend"]["id"]
    r = client.delete(f"/api/remote-backends/{bid}")
    assert r.status_code == 200
    r = client.delete(f"/api/remote-backends/{bid}")
    assert r.status_code == 404


def test_health_endpoint_records_status(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    bid = client.post(
        "/api/remote-backends",
        json={"name": "x", "url": "https://x.com"},
    ).json()["backend"]["id"]

    with patch(
        "runtime.sensing.gateway.remote_backends_router.health_check",
        return_value=("ok", None),
    ) as mocked_health:
        r = client.post(f"/api/remote-backends/{bid}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert mocked_health.call_args.kwargs["auth_token"] is None

    listing = client.get("/api/remote-backends").json()
    assert listing["backends"][0]["last_health"] == "ok"


def test_proxy_endpoint_forwards(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    bid = client.post(
        "/api/remote-backends",
        json={
            "name": "x",
            "url": "https://x.com",
            "auth_token": "remote-secret",
        },
    ).json()["backend"]["id"]

    with patch(
        "runtime.sensing.gateway.remote_backends_router.proxy_request",
        return_value={"status_code": 200, "body": {"echo": True}},
    ) as mocked_proxy:
        r = client.post(
            f"/api/remote-backends/{bid}/proxy",
            json={"method": "GET", "path": "/api/health"},
        )
    assert r.status_code == 200
    assert r.json()["body"] == {"echo": True}
    assert mocked_proxy.call_args.kwargs["auth_token"] == "remote-secret"


def test_proxy_404_for_unknown_backend(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCTOPUS_FF_UI_REMOTE_TRANSPORT", "1")
    ff.reload()
    r = client.post(
        "/api/remote-backends/missing/proxy",
        json={"method": "GET", "path": "/x"},
    )
    assert r.status_code == 404
