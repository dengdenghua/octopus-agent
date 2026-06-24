"""Security regression tests for two authz gates added after the full-stack audit.

S1 · observability router (``/api/journal``, ``/api/stream``,
     ``/api/files/stream`` …) previously had NO auth wiring at all — connecting
     replayed the whole journal (file diffs, absolute paths, task history) to
     any anonymous client (verified live: ``/api/files/stream`` streamed 44 KB
     of historical file_op events with absolute home/Windows paths). It now
     honours ``require_auth`` via a router-level dependency, mirroring
     ``create_browser_router``.

S3 · anthropic_compat per-session routes (``GET/POST /v1/sessions/{id}…``)
     authenticated the caller but never checked session ownership, so any
     authenticated actor could read or drive another actor's session by
     guessing its id. ``_owned_or_404`` now enforces ``creator_actor`` — and
     returns 404 (not 403) so a non-owner can't even confirm a session exists.

Both gates are no-ops when ``require_auth=False`` (single-user dev), so local
preview + the EventSource-based Observability panel are unchanged — pinned by
the ``*_dev_mode`` / ``*_open_in_dev`` tests.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from runtime.platform.config import AgentConfig, PlannerConfig, build_from_config  # noqa: E402
from runtime.platform.ui.app import create_app  # noqa: E402
from runtime.safety.auth.identity import Identity, IdentityStore  # noqa: E402
from runtime.sensing.gateway.anthropic_compat import create_anthropic_compat_router  # noqa: E402

_BETA = {"anthropic-beta": "managed-agents-2026-04-01"}


def _store_with_actors() -> tuple[IdentityStore, dict[str, str]]:
    store = IdentityStore()
    keys: dict[str, str] = {}
    for actor in ("alice", "bob"):
        key = f"sk-test-{actor}"
        store.add(Identity(actor_id=actor), api_key_plaintext=key)
        keys[actor] = key
    return store, keys


def _bearer(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


# ── S1 · observability auth gate ─────────────────────────────────────


@pytest.fixture
def obs_stack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[object]:
    monkeypatch.chdir(tmp_path)
    cfg = AgentConfig(
        planner=PlannerConfig(
            type="llm",
            model="mock/ob",
            mock_response='{"reasoning":"r","nodes":[]}',
        ),
    )
    yield build_from_config(cfg)


# These go through the real ``create_app`` factory so they exercise the exact
# app.py call-site wiring the fix added (create_observability_router now
# receives identity_store + require_auth). The dev-mode test proving 200 also
# rules out a global middleware confound: the 401 below can only come from the
# router-level gate that the fix made conditional on require_auth.


def test_observability_requires_auth_when_enabled(obs_stack: object) -> None:
    store, keys = _store_with_actors()
    app = create_app(
        journal=obs_stack.journal,  # type: ignore[attr-defined]
        registry=obs_stack.registry,  # type: ignore[attr-defined]
        stack=obs_stack,
        cocoloop_require_auth=True,
        cocoloop_identity_store=store,
    )
    client = TestClient(app)

    # Anonymous caller is rejected before the handler runs (was: 200 + the
    # whole journal). Pins the leak closed under auth-on.
    assert client.get("/api/journal").status_code == 401

    # Authenticated caller passes the gate (200 or any non-401 handler result).
    assert client.get("/api/journal", headers=_bearer(keys["alice"])).status_code != 401


def test_observability_open_in_dev_mode(obs_stack: object) -> None:
    app = create_app(
        journal=obs_stack.journal,  # type: ignore[attr-defined]
        registry=obs_stack.registry,  # type: ignore[attr-defined]
        stack=obs_stack,
    )
    client = TestClient(app)

    # No token, dev mode (require_auth defaults False) → router-level gate is a
    # no-op, endpoint reachable. This is the property that keeps the frontend
    # EventSource panel working, and rules out a global-auth confound.
    assert client.get("/api/journal").status_code == 200


# ── S3 · anthropic_compat session ownership ──────────────────────────


def _session_client(store: IdentityStore) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_anthropic_compat_router(
            stack=None,
            identity_store=store,
            require_auth=True,
        )
    )
    return TestClient(app)


def test_session_ownership_blocks_other_actor() -> None:
    store, keys = _store_with_actors()
    client = _session_client(store)

    created = client.post(
        "/v1/sessions",
        json={"title": "alice's session"},
        headers={**_BETA, **_bearer(keys["alice"])},
    )
    assert created.status_code == 200, created.text
    sid = created.json()["id"]

    # bob is authenticated but is NOT the creator → 404 on every per-session
    # route (read, list-events, send-events, stream). 404 not 403 so bob can't
    # confirm the session exists.
    bob = {**_BETA, **_bearer(keys["bob"])}
    assert client.get(f"/v1/sessions/{sid}", headers=bob).status_code == 404
    assert client.get(f"/v1/sessions/{sid}/events", headers=bob).status_code == 404
    assert (
        client.post(
            f"/v1/sessions/{sid}/events",
            json={"events": []},
            headers=bob,
        ).status_code
        == 404
    )
    assert client.get(f"/v1/sessions/{sid}/events/stream", headers=bob).status_code == 404

    # alice (the creator) still has full access.
    assert (
        client.get(f"/v1/sessions/{sid}", headers={**_BETA, **_bearer(keys["alice"])}).status_code
        == 200
    )


def test_session_unauthenticated_rejected() -> None:
    store, _keys = _store_with_actors()
    client = _session_client(store)

    # Beta header present, no bearer token, require_auth=True → 401 (the beta
    # check passes, then actor resolution fails).
    assert client.get("/v1/sessions/sesn_whatever", headers=_BETA).status_code == 401
