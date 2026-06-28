"""The in-process computer loop skills must authenticate to /api/computer.

Regression for the gap where ``computer_observe``/``plan``/``preview``/
``execute`` (which call the local ``/api/computer`` service over loopback)
got 401'd once control-plane auth was enabled. ``create_app`` now mints a
service identity + injects an in-memory token the loop-skill client sends.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from runtime.execution.suckers import computer_api_skills as cas  # noqa: E402
from runtime.platform.ui.app import create_app  # noqa: E402
from runtime.safety.auth.identity import IdentityStore  # noqa: E402


class _FakeResp:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def __enter__(self) -> _FakeResp:
        return self

    def __exit__(self, *_a: object) -> bool:
        return False

    def read(self) -> bytes:
        return self._payload


def test_call_sends_internal_token_only_when_set(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str | None] = {}

    def fake_urlopen(req: object, timeout: float | None = None) -> _FakeResp:
        captured["auth"] = req.get_header("Authorization")  # type: ignore[attr-defined]
        return _FakeResp(b'{"ok": true}')

    monkeypatch.setattr(cas.urllib_request, "urlopen", fake_urlopen)

    cas.set_internal_api_token("svc-key-abc")
    try:
        cas._call("GET", "/status")
        assert captured["auth"] == "Bearer svc-key-abc"

        cas.set_internal_api_token(None)
        captured.clear()
        cas._call("GET", "/status")
        assert captured["auth"] is None
    finally:
        cas.set_internal_api_token(None)


def test_create_app_mints_loop_service_token_and_it_authenticates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    cas.set_internal_api_token(None)
    store = IdentityStore()
    app = create_app(cocoloop_require_auth=True, cocoloop_identity_store=store)
    try:
        token = cas._internal_token
        assert token, "create_app should mint + inject a service token under auth"

        # The minted token resolves to the dedicated service identity...
        ident = store.verify_api_key(token)
        assert ident is not None
        assert ident.actor_id == "service:computer-loop"

        # ...and authenticates through the real control-plane auth gate:
        client = TestClient(app)
        assert client.get("/api/computer/status").status_code == 401  # anon blocked
        assert (
            client.get(
                "/api/computer/status",
                headers={"Authorization": f"Bearer {token}"},
            ).status_code
            != 401
        )
    finally:
        cas.set_internal_api_token(None)


def test_no_service_token_when_auth_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    cas.set_internal_api_token(None)
    create_app()  # auth off (default)
    # Auth off → endpoint is open, so no token is minted/injected.
    assert cas._internal_token is None
