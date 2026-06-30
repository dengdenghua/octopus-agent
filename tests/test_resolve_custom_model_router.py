"""Tests for runtime.sensing.gateway.openai_gateway.request_parser._resolve_custom_model_router.

Specifically the variant-name lookup branch added so the picker can
expose ``mimo-v2.5-pro`` / ``mimo-v2.5-flash`` as standalone rows
(rather than the entry alias ``mimo2.5``) while still routing the
request through the entry's base_url + api_key.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _custom_models_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> Path:
    """Point app_paths().custom_models_path to a hermetic tmp file
    so each test starts with a clean slate. Tests then write their
    own JSON to that file before invoking the resolver."""
    target = tmp_path / "custom_models.json"

    from runtime.platform.process.paths import app_paths
    original = app_paths()

    class _Patched:
        custom_models_path = target

        def __getattr__(self, name: str) -> object:
            return getattr(original, name)

    monkeypatch.setattr(
        "runtime.platform.process.paths.app_paths",
        lambda: _Patched(),
    )
    return target


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_entry_alias_resolves_to_first_variant(
    _custom_models_path: Path,
) -> None:
    """Calling with the entry id (``mimo2.5``) returns the first
    variant (``mimo-v2.5-pro``) — preserves legacy behavior so the
    auto-derive fallback still has a stable answer."""
    from runtime.sensing.gateway.openai_gateway.request_parser import (
        _resolve_custom_model_router,
    )
    _write(_custom_models_path, {
        "mimo2.5": {
            "provider": "openai",
            "base_url": "https://example.com/v1",
            "api_key": "fake-key",
            "models": ["mimo-v2.5-pro", "mimo-v2.5-flash"],
        },
    })
    sentinel = object()
    new_router, resolved = _resolve_custom_model_router("mimo2.5", sentinel)
    assert resolved == "mimo-v2.5-pro"
    assert new_router is not sentinel  # built a fresh OpenAI router


def test_variant_name_resolves_to_itself(
    _custom_models_path: Path,
) -> None:
    """When the picker passes ``mimo-v2.5-flash`` (a variant inside
    an entry's models list), the resolver finds the parent entry,
    builds a router with that entry's credentials, and uses the
    variant name as the upstream model — so the request goes to
    mimo-v2.5-flash, NOT to whatever models[0] happens to be."""
    from runtime.sensing.gateway.openai_gateway.request_parser import (
        _resolve_custom_model_router,
    )
    _write(_custom_models_path, {
        "mimo2.5": {
            "provider": "openai",
            "base_url": "https://example.com/v1",
            "api_key": "fake-key",
            "models": ["mimo-v2.5-pro", "mimo-v2.5-flash"],
        },
    })
    sentinel = object()
    new_router, resolved = _resolve_custom_model_router(
        "mimo-v2.5-flash", sentinel,
    )
    assert resolved == "mimo-v2.5-flash"
    assert new_router is not sentinel
    # Router uses the variant as default_model so a downstream
    # ModelRequest with model="" still talks to flash.
    assert getattr(new_router, "default_model", None) == "mimo-v2.5-flash"


def test_unknown_name_passes_through(
    _custom_models_path: Path,
) -> None:
    """A name that's neither an entry id nor a known variant returns
    the router unchanged. Lets the dispatcher hand off to its
    fallback (built-in presets / molili / etc.)."""
    from runtime.sensing.gateway.openai_gateway.request_parser import (
        _resolve_custom_model_router,
    )
    _write(_custom_models_path, {
        "mimo2.5": {
            "provider": "openai",
            "base_url": "https://example.com/v1",
            "api_key": "fake-key",
            "models": ["mimo-v2.5-pro", "mimo-v2.5-flash"],
        },
    })
    sentinel = object()
    new_router, resolved = _resolve_custom_model_router(
        "claude-sonnet-4", sentinel,
    )
    assert resolved == "claude-sonnet-4"
    assert new_router is sentinel


def test_variant_lookup_walks_multiple_entries(
    _custom_models_path: Path,
) -> None:
    """If the user has multiple custom_models entries, the variant
    lookup walks all of them and picks the entry whose models[]
    contains the requested variant."""
    from runtime.sensing.gateway.openai_gateway.request_parser import (
        _resolve_custom_model_router,
    )
    _write(_custom_models_path, {
        "first-provider": {
            "provider": "openai",
            "base_url": "https://first.example.com/v1",
            "api_key": "first-key",
            "models": ["first-small", "first-large"],
        },
        "second-provider": {
            "provider": "openai",
            "base_url": "https://second.example.com/v1",
            "api_key": "second-key",
            "models": ["second-small", "second-large"],
        },
    })
    sentinel = object()
    new_router, resolved = _resolve_custom_model_router(
        "second-large", sentinel,
    )
    assert resolved == "second-large"
    # Should have built the second provider's router (its base_url).
    assert "second.example.com" in getattr(new_router, "base_url", "")


def test_legacy_single_model_field_still_works(
    _custom_models_path: Path,
) -> None:
    """Older entries had a single ``model`` field instead of a
    ``models`` list. Entry-id lookup must still find them."""
    from runtime.sensing.gateway.openai_gateway.request_parser import (
        _resolve_custom_model_router,
    )
    _write(_custom_models_path, {
        "legacy-entry": {
            "provider": "openai",
            "base_url": "https://example.com/v1",
            "api_key": "fake-key",
            "model": "legacy-single-model",
        },
    })
    sentinel = object()
    new_router, resolved = _resolve_custom_model_router(
        "legacy-entry", sentinel,
    )
    assert resolved == "legacy-single-model"
    assert new_router is not sentinel


def test_no_custom_models_file_returns_unchanged(
    _custom_models_path: Path,
) -> None:
    """File doesn't exist → router + name pass through verbatim.
    The autouse fixture creates a tmp_path that doesn't have the
    file, so this is the natural "fresh install" case."""
    from runtime.sensing.gateway.openai_gateway.request_parser import (
        _resolve_custom_model_router,
    )
    sentinel = object()
    new_router, resolved = _resolve_custom_model_router("anything", sentinel)
    assert resolved == "anything"
    assert new_router is sentinel


class TestBuildFallbackFromCustomModels:
    """build_fallback_router_from_custom_models — self model as dispatch fallback
    instead of the login-gated Molili."""

    def test_prefers_entry_matching_planner_model(self, _custom_models_path: Path) -> None:
        _write(_custom_models_path, {
            "kimi-code": {
                "id": "kimi-code", "provider": "openai",
                "base_url": "https://api.kimi.com/coding/v1",
                "api_key": "sk-x", "models": ["kimi-for-coding"],
            },
        })
        from runtime.sensing.model_router.openai_router import (
            OpenAIModelRouter,
            build_fallback_router_from_custom_models,
        )
        r = build_fallback_router_from_custom_models("kimi-for-coding")
        assert isinstance(r, OpenAIModelRouter)
        assert getattr(r, "default_model", None) == "kimi-for-coding"

    def test_falls_back_to_first_entry_when_no_match(self, _custom_models_path: Path) -> None:
        _write(_custom_models_path, {
            "a": {"id": "a", "provider": "openai",
                  "base_url": "https://h/v1", "models": ["m1"]},
        })
        from runtime.sensing.model_router.openai_router import (
            build_fallback_router_from_custom_models,
        )
        r = build_fallback_router_from_custom_models("nonexistent")
        assert r is not None
        assert getattr(r, "default_model", None) == "m1"

    def test_none_when_no_custom_models(self, _custom_models_path: Path) -> None:
        from runtime.sensing.model_router.openai_router import (
            build_fallback_router_from_custom_models,
        )
        # tmp file not written → no entries → caller keeps Molili
        assert build_fallback_router_from_custom_models("x") is None


def test_unconfigured_model_router_raises_clear_error() -> None:
    """The last-resort fallback (no model configured) raises an actionable
    error instead of the old Molili login gate."""
    import pytest as _pytest

    from runtime.sensing.model_router.models import (
        Message,
        ModelRequest,
        UnconfiguredModelRouter,
    )

    req = ModelRequest(model="x", messages=[Message(role="user", content="hi")])
    with _pytest.raises(RuntimeError, match="no LLM model configured"):
        UnconfiguredModelRouter().call(req)
