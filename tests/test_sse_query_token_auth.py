"""SSE auth-gap fix: `_resolve_actor` accepts the bearer via a `?token=` query.

EventSource cannot set request headers, so under `require_auth` every SSE
endpoint 401'd while the chat WebSocket (which already uses `?token=`) worked.
The frontend now appends `?token=` (`authedEventSource`) and the backend reads
it. The Authorization header still takes precedence when both are present.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from runtime.adapters.web_auth import _resolve_actor
from runtime.safety.auth import Identity, IdentityStore


def _store() -> IdentityStore:
    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    return store


def _req(headers: dict | None = None, query: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=headers or {}, query_params=query or {})


def test_query_token_resolves_actor() -> None:
    actor = _resolve_actor(_req(query={"token": "sk-alice"}), _store(), True)
    assert actor == "alice"


def test_header_takes_precedence_over_query() -> None:
    actor = _resolve_actor(
        _req(headers={"Authorization": "Bearer sk-alice"}, query={"token": "garbage"}),
        _store(),
        True,
    )
    assert actor == "alice"


def test_missing_token_anywhere_raises_when_required() -> None:
    with pytest.raises(HTTPException):
        _resolve_actor(_req(), _store(), True)


def test_invalid_query_token_raises_when_required() -> None:
    with pytest.raises(HTTPException):
        _resolve_actor(_req(query={"token": "sk-nope"}), _store(), True)


def test_bad_query_token_returns_none_when_not_required() -> None:
    assert _resolve_actor(_req(query={"token": "sk-nope"}), _store(), False) is None
