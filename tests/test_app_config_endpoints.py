"""
Integration tests for ``runtime/platform/ui/app.py`` config endpoints.

Purpose
-------

These tests are **refactor guard-rails**. The endpoints exercised here
are about to be extracted out of the monolithic ``create_app`` into
their own ``create_config_router`` factory (see ``todos`` list). Without
integration coverage, that split is indistinguishable from "silently
broken in production" — there are no existing tests for these routes.

Endpoints covered
-----------------

    GET    /api/config/identity-lock          · privacy filter state
    PUT    /api/config/identity-lock          · admin toggle
    GET    /api/providers                     · LLM provider caps
    GET    /api/config/custom-models          · list
    PUT    /api/config/custom-models/{id}     · upsert + persist
    DELETE /api/config/custom-models/{id}     · remove + persist
    GET    /api/llm-models                    · merged list (molili + custom)

Design notes
------------

* ``chdir(tmp_path)`` — the app hard-codes ``Path("data/custom_models.json")``
  relative to CWD. Redirecting CWD keeps each test hermetic (no cross-
  test pollution, no real repo data touched) and simultaneously locks
  the current on-disk persistence contract. If the future refactor
  moves the path elsewhere, these tests catch it.
* ``identity_filter_reset`` — the module holds a process-wide
  ``_RUNTIME_OVERRIDE``. Tests share the same Python process, so one
  leaving the filter off would cascade. Explicit cleanup.
* No stack injected — ``_register_custom_model`` degrades gracefully
  when ``stack.planner.router`` is absent (returns ``{"ok": False}``).
  That's the path we exercise: the persistence side works regardless.
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.platform.ui.app import create_app
from runtime.sensing.gateway.config_router import create_config_router
from runtime.sensing.model_router import ModelDispatchRouter, ModelRouter

# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════


@pytest.fixture
def isolated_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Redirect CWD so ``Path("data/custom_models.json")`` lands in a
    scratch dir. Restoration is handled by monkeypatch."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def identity_filter_reset() -> Iterator[None]:
    """The identity-filter module keeps a process-wide runtime override.
    Clear it before AND after each test so no cross-test bleed."""
    from runtime.platform import identity_filter as _idf

    _idf.set_runtime_lock(None)
    yield
    _idf.set_runtime_lock(None)


@pytest.fixture
def client(isolated_cwd: Path) -> TestClient:
    """TestClient over a minimally-configured app — no stack, no
    agent registry, just enough to serve the config endpoints."""
    app = create_app()
    return TestClient(app)


@pytest.fixture
def secured_client(isolated_cwd: Path) -> tuple[TestClient, dict[str, str]]:
    """Same app surface, but with auth required so router-level config
    auth can be pinned independently of any outer middleware."""
    from runtime.safety.auth import Identity, IdentityStore

    store = IdentityStore()
    store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
    app = create_app(
        cocoloop_require_auth=True,
        cocoloop_identity_store=store,
    )
    return TestClient(app), {"Authorization": "Bearer sk-alice"}


# ═══════════════════════════════════════════════════════════
# GET /api/config/identity-lock
# ═══════════════════════════════════════════════════════════


class TestIdentityLockGet:
    def test_default_state_is_locked(self, client: TestClient) -> None:
        r = client.get("/api/config/identity-lock")
        assert r.status_code == 200
        data = r.json()
        assert data["locked"] is True
        assert data["source"] == "default"
        # Three documented unlock paths should be reported so the UI
        # can tell users how to bypass. Regression-safety for the
        # settings page that lists them verbatim.
        assert isinstance(data["unlock_paths"], list)
        assert len(data["unlock_paths"]) >= 3

    def test_runtime_override_reported_as_runtime(
        self, client: TestClient,
    ) -> None:
        from runtime.platform import identity_filter as _idf

        _idf.set_runtime_lock(False)
        r = client.get("/api/config/identity-lock")
        assert r.status_code == 200
        data = r.json()
        assert data["locked"] is False
        assert data["source"] == "runtime"


# ═══════════════════════════════════════════════════════════
# PUT /api/config/identity-lock
# ═══════════════════════════════════════════════════════════


class TestIdentityLockPut:
    def test_set_locked_false(self, client: TestClient) -> None:
        r = client.put(
            "/api/config/identity-lock", json={"locked": False},
        )
        assert r.status_code == 200
        assert r.json()["locked"] is False
        assert r.json()["source"] == "runtime"

    def test_set_locked_true(self, client: TestClient) -> None:
        client.put("/api/config/identity-lock", json={"locked": False})
        r = client.put(
            "/api/config/identity-lock", json={"locked": True},
        )
        assert r.status_code == 200
        assert r.json()["locked"] is True

    def test_null_clears_runtime_override(self, client: TestClient) -> None:
        """``null`` reverts to env/default. Important: without this
        path, a UI toggle is a one-way door — you can flip but never
        "forget" the override."""
        client.put("/api/config/identity-lock", json={"locked": False})
        r = client.put(
            "/api/config/identity-lock", json={"locked": None},
        )
        assert r.status_code == 200
        assert r.json()["source"] == "default"

    def test_rejects_non_bool_value(self, client: TestClient) -> None:
        r = client.put(
            "/api/config/identity-lock", json={"locked": "yes"},
        )
        assert r.status_code == 400


class TestConfigAuth:
    def test_identity_lock_requires_auth_when_enabled(
        self, secured_client: tuple[TestClient, dict[str, str]],
    ) -> None:
        client, headers = secured_client

        assert client.get("/api/config/identity-lock").status_code == 401
        assert client.get(
            "/api/config/identity-lock", headers=headers,
        ).status_code == 200

    def test_custom_model_put_requires_auth_when_enabled(
        self, secured_client: tuple[TestClient, dict[str, str]],
    ) -> None:
        client, headers = secured_client
        payload = {"provider": "anthropic", "model": "claude-sonnet-4-6"}

        assert client.put(
            "/api/config/custom-models/claude-mirror", json=payload,
        ).status_code == 401
        assert client.put(
            "/api/config/custom-models/claude-mirror",
            json=payload,
            headers=headers,
        ).status_code == 200


# ═══════════════════════════════════════════════════════════
# GET /api/providers
# ═══════════════════════════════════════════════════════════


class TestProviders:
    def test_returns_capability_list(self, client: TestClient) -> None:
        r = client.get("/api/providers")
        assert r.status_code == 200
        data = r.json()
        assert "providers" in data
        assert isinstance(data["providers"], list)
        # Each entry should have the documented capability fields.
        # We assert shape, not membership — the set of providers that
        # resolves depends on which optional SDKs are installed in the
        # test env (anthropic / google.genai / etc may be missing).
        for entry in data["providers"]:
            assert "name" in entry
            assert "supports_vision" in entry
            assert "supports_tool_use" in entry
            assert "supports_streaming" in entry
            assert "supports_prompt_cache" in entry

    def test_anthropic_always_present(self, client: TestClient) -> None:
        """Anthropic SDK ships as a core dep (agents use Claude by
        default), so it MUST resolve. Other providers are optional."""
        r = client.get("/api/providers")
        names = {p["name"] for p in r.json()["providers"]}
        assert "anthropic" in names


# ═══════════════════════════════════════════════════════════
# GET /api/config/custom-models · list
# ═══════════════════════════════════════════════════════════


class TestCustomModelsList:
    def test_empty_on_fresh_start(self, client: TestClient) -> None:
        r = client.get("/api/config/custom-models")
        assert r.status_code == 200
        assert r.json() == {"models": []}


# ═══════════════════════════════════════════════════════════
# PUT /api/config/custom-models/{id} · upsert
# ═══════════════════════════════════════════════════════════


class TestCustomModelsUpsert:
    def test_create_persists_to_disk(
        self, client: TestClient, isolated_cwd: Path,
    ) -> None:
        payload = {
            "name": "claude-mirror",
            "provider": "anthropic",
            "base_url": "https://mirror.example.com",
            "api_key": "sk-test",
            "model": "claude-sonnet-4-6",
            "max_tokens": 12000,
            "supports_thinking": True,
            "supports_vision": False,
            "supports_tool_use": True,
            "omit_sampling_parameters": True,
            "compat_profile": "kimi_coding",
            "thinking_request_style": "none",
            "drop_tool_choice": True,
            "max_temperature": 0.2,
            "unsupported_request_fields": ["parallel_tool_calls"],
            "default_headers": {"X-Test": "yes"},
        }
        r = client.put(
            "/api/config/custom-models/claude-mirror", json=payload,
        )
        assert r.status_code == 200
        body = r.json()
        # api_key MUST NOT be echoed back — privacy invariant.
        assert "api_key" not in body["model"]
        # But the presence flag should be true so the UI shows "set".
        assert body["model"]["has_api_key"] is True
        # Persisted file exists at the documented location.
        persisted = isolated_cwd / "data" / "custom_models.json"
        assert persisted.exists()
        # And it contains the full secret (not the wire form).
        import json

        stored = json.loads(persisted.read_text(encoding="utf-8"))
        assert stored["claude-mirror"]["api_key"] == "sk-test"
        assert "max_tokens" not in stored["claude-mirror"]
        assert stored["claude-mirror"]["supports_thinking"] is True
        assert stored["claude-mirror"]["supports_vision"] is False
        assert stored["claude-mirror"]["supports_tool_use"] is True
        assert stored["claude-mirror"]["omit_sampling_parameters"] is True
        assert stored["claude-mirror"]["compat_profile"] == "kimi_coding"
        assert stored["claude-mirror"]["thinking_request_style"] == "none"
        assert stored["claude-mirror"]["drop_tool_choice"] is True
        assert stored["claude-mirror"]["max_temperature"] == 0.2
        assert stored["claude-mirror"]["unsupported_request_fields"] == [
            "parallel_tool_calls",
        ]
        assert stored["claude-mirror"]["default_headers"] == {"X-Test": "yes"}

    def test_update_preserves_prior_api_key(
        self, client: TestClient,
    ) -> None:
        """PUT without api_key should NOT wipe the existing secret.
        This is the UX: user opens the form, toggles something minor,
        submits — they didn't retype the secret but shouldn't lose it."""
        client.put(
            "/api/config/custom-models/mid1",
            json={
                "name": "m1", "provider": "openai",
                "base_url": "https://x.test", "api_key": "sk-original",
                "model": "gpt-4",
            },
        )
        # Second PUT with no api_key
        r = client.put(
            "/api/config/custom-models/mid1",
            json={"name": "m1-renamed", "provider": "openai"},
        )
        assert r.status_code == 200
        assert r.json()["model"]["has_api_key"] is True

        # Verify by reading list
        listing = client.get("/api/config/custom-models").json()
        entry = next(m for m in listing["models"] if m["id"] == "mid1")
        assert entry["has_api_key"] is True
        assert entry["name"] == "m1-renamed"

    def test_update_can_clear_headers_and_false_capabilities(
        self, client: TestClient,
    ) -> None:
        client.put(
            "/api/config/custom-models/mid2",
            json={
                "name": "m2", "provider": "openai",
                "base_url": "https://x.test", "api_key": "sk",
                "model": "gpt-4", "supports_thinking": True,
                "supports_vision": True,
                "default_headers": {"X-Route": "a"},
            },
        )
        r = client.put(
            "/api/config/custom-models/mid2",
            json={
                "supports_thinking": False,
                "supports_vision": False,
                "default_headers": {},
            },
        )
        assert r.status_code == 200
        listing = client.get("/api/config/custom-models").json()
        entry = next(m for m in listing["models"] if m["id"] == "mid2")
        assert entry["supports_thinking"] is False
        assert entry["supports_vision"] is False
        assert entry["default_headers"] == {}

    def test_registers_entry_id_and_concrete_model_ids(
        self,
        isolated_cwd: Path,
    ) -> None:
        class _Fallback(ModelRouter):
            def call(self, request):
                raise AssertionError("fallback should not be called")

        dispatcher = ModelDispatchRouter(fallback=_Fallback())
        stack = SimpleNamespace(planner=SimpleNamespace(router=dispatcher))
        app = FastAPI()
        app.include_router(create_config_router(stack=stack).router)
        client = TestClient(app)

        r = client.put(
            "/api/config/custom-models/kimi-code",
            json={
                "name": "Kimi Code",
                "provider": "openai",
                "base_url": "https://api.kimi.com/coding/v1",
                "api_key": "sk-test",
                "models": ["kimi-for-coding", "kimi-for-coding-fast"],
                "display_name": "K2.7 Code",
                "supports_tool_use": True,
                "omit_sampling_parameters": True,
            },
        )
        assert r.status_code == 200
        assert dispatcher.has("kimi-code")
        assert dispatcher.has("kimi-for-coding")
        assert dispatcher.has("kimi-for-coding-fast")

        r = client.put(
            "/api/config/custom-models/kimi-code",
            json={"models": ["kimi-for-coding-v2"]},
        )
        assert r.status_code == 200
        assert dispatcher.has("kimi-code")
        assert not dispatcher.has("kimi-for-coding")
        assert not dispatcher.has("kimi-for-coding-fast")
        assert dispatcher.has("kimi-for-coding-v2")

        r = client.delete("/api/config/custom-models/kimi-code")
        assert r.status_code == 200
        assert r.json()["removed"] is True
        assert not dispatcher.has("kimi-code")
        assert not dispatcher.has("kimi-for-coding-v2")


# ═══════════════════════════════════════════════════════════
# GET /api/config/custom-models/compat-diagnostics
# ═══════════════════════════════════════════════════════════


class TestCustomModelCompatDiagnostics:
    def test_builtin_openai_compat_profile_catalog_is_dry_run_matrix(
        self,
        client: TestClient,
    ) -> None:
        r = client.get("/api/config/openai-compat-profiles")
        assert r.status_code == 200
        data = r.json()
        assert data["schema"] == "octopus.openai_compat_profile_catalog.v1"
        assert data["total"] >= 10

        by_id = {row["id"]: row for row in data["diagnostics"]}
        assert {
            "deepseek",
            "kimi",
            "kimi_coding",
            "qwen",
            "glm",
            "doubao",
            "minimax",
            "hunyuan",
            "baichuan",
            "siliconflow",
        }.issubset(by_id)

        kimi_coding = by_id["kimi_coding"]
        assert kimi_coding["built_in"] is True
        assert kimi_coding["applicable"] is True
        assert kimi_coding["has_api_key"] is False
        assert kimi_coding["upstreams"][0]["model"] == "kimi-k2.7-code"
        assert kimi_coding["upstreams"][0]["profile"] == "kimi_coding"
        assert "drop_sampling_parameters" in kimi_coding["upstreams"][0][
            "normalization_hints"
        ]
        assert {
            "frequency_penalty",
            "presence_penalty",
            "reasoning_effort",
            "temperature",
            "thinking",
            "top_p",
        }.issubset(
            set(kimi_coding["upstreams"][0]["normalization"]["removed_fields"])
        )

        qwen_reasons = {
            item["reason"]
            for item in by_id["qwen"]["upstreams"][0]["fallback_retries"]
        }
        assert "rename_max_tokens" in qwen_reasons
        assert "strict_tool_schema" in qwen_reasons

    def test_openai_compat_diagnostics_are_dry_run_and_secret_safe(
        self,
        client: TestClient,
    ) -> None:
        client.put(
            "/api/config/custom-models/kimi-code",
            json={
                "name": "Kimi Code",
                "provider": "openai",
                "base_url": "https://api.kimi.com/coding/v1",
                "api_key": "sk-realish-secret",
                "models": ["kimi-k2.7-code"],
                "compat_profile": "kimi_coding",
                "drop_tool_choice": True,
                "unsupported_request_fields": ["parallel_tool_calls"],
                "default_headers": {
                    "User-Agent": "OctopusSmoke/1.0",
                    "X-Route-Token": "route-secret",
                },
            },
        )

        r = client.get("/api/config/custom-models/compat-diagnostics")
        assert r.status_code == 200
        data = r.json()
        assert data["schema"] == "octopus.openai_compat_diagnostics.v1"
        assert data["total"] == 1

        row = data["diagnostics"][0]
        assert row["id"] == "kimi-code"
        assert row["applicable"] is True
        assert row["has_api_key"] is True
        assert row["default_header_names"] == ["User-Agent", "X-Route-Token"]
        blob = repr(data)
        assert "sk-realish-secret" not in blob
        assert "route-secret" not in blob

        upstream = row["upstreams"][0]
        assert upstream["profile"] == "kimi_coding"
        assert upstream["profile_summary"]["id"] == "kimi_coding"
        assert upstream["compat_score"] == upstream["profile_summary"]["compat_score"]
        assert "drop_sampling_parameters" in upstream["normalization_hints"]
        assert any("coding endpoint" in note for note in upstream["compatibility_notes"])
        removed = set(upstream["normalization"]["removed_fields"])
        assert {
            "frequency_penalty",
            "parallel_tool_calls",
            "presence_penalty",
            "reasoning_effort",
            "temperature",
            "thinking",
            "tool_choice",
            "top_p",
        }.issubset(removed)
        assert "temperature" not in upstream["normalization"]["normalized_fields"]
        assert "parallel_tool_calls" not in upstream["normalization"]["payload"]

        reasons = {item["reason"] for item in upstream["fallback_retries"]}
        assert "rename_max_tokens" in reasons
        assert "strict_tool_schema" in reasons
        assert "combined_compatibility_fallback" in reasons

    def test_compat_diagnostics_marks_non_openai_entries_not_applicable(
        self,
        client: TestClient,
    ) -> None:
        client.put(
            "/api/config/custom-models/claude-mirror",
            json={
                "name": "Claude Mirror",
                "provider": "anthropic",
                "api_key": "sk-claude-secret",
                "models": ["claude-sonnet-4-6"],
            },
        )

        r = client.get(
            "/api/config/custom-models/compat-diagnostics",
            params={"model_id": "claude-mirror"},
        )
        assert r.status_code == 200
        row = r.json()["diagnostics"][0]
        assert row["applicable"] is False
        assert row["reason"] == "provider is not OpenAI-compatible"
        assert "sk-claude-secret" not in repr(row)


# ═══════════════════════════════════════════════════════════
# DELETE /api/config/custom-models/{id}
# ═══════════════════════════════════════════════════════════


class TestCustomModelsDelete:
    def test_delete_removes_from_list_and_disk(
        self, client: TestClient, isolated_cwd: Path,
    ) -> None:
        client.put(
            "/api/config/custom-models/delme",
            json={
                "name": "x", "provider": "openai",
                "base_url": "https://x.test", "api_key": "sk",
                "model": "gpt-4",
            },
        )
        r = client.delete("/api/config/custom-models/delme")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        # List is empty again
        assert client.get("/api/config/custom-models").json() == {
            "models": [],
        }
        # Disk reflects the delete
        import json

        persisted = isolated_cwd / "data" / "custom_models.json"
        stored = json.loads(persisted.read_text(encoding="utf-8"))
        assert "delme" not in stored

    def test_delete_missing_is_idempotent(
        self, client: TestClient,
    ) -> None:
        """Double-delete shouldn't 500. UI could race two Delete clicks
        and we want the second to be a no-op rather than an error."""
        r = client.delete("/api/config/custom-models/never-existed")
        assert r.status_code == 200
        assert r.json()["ok"] is True


# ═══════════════════════════════════════════════════════════
# GET /api/llm-models · custom models appear in merged list
# ═══════════════════════════════════════════════════════════


class TestLlmModelsMerge:
    def test_custom_model_appears_in_merged_list(
        self, client: TestClient,
    ) -> None:
        client.put(
            "/api/config/custom-models/mirror-x",
            json={
                "name": "Mirror X", "provider": "anthropic",
                "base_url": "https://mirror.test",
                "api_key": "sk-x", "model": "claude-sonnet-4-6",
                "display_name": "Mirror X",
                "supports_thinking": True,
                "supports_vision": True,
            },
        )
        r = client.get("/api/llm-models")
        assert r.status_code == 200
        data = r.json()
        # The merged endpoint must include the custom model alongside
        # whatever built-in molili presets exist. Shape sanity:
        assert "models" in data or "data" in data or isinstance(data, dict)
        # Loosely assert the custom id is somewhere in the response
        # (the exact structure isn't locked — depends on molili
        # gateway, which we're not mocking here).
        blob = repr(data)
        assert "mirror-x" in blob or "Mirror X" in blob
        assert "supports_thinking" in blob

    def test_custom_model_flags_appear_in_merged_list(
        self,
        client: TestClient,
    ) -> None:
        client.put(
            "/api/config/custom-models/kimi-code",
            json={
                "name": "Kimi Code", "provider": "openai",
                "base_url": "https://api.kimi.com/coding/v1",
                "api_key": "sk-x", "models": ["kimi-for-coding"],
                "display_name": "K2.7 Code",
                "omit_sampling_parameters": True,
                "compat_profile": "kimi_coding",
                "thinking_request_style": "none",
                "drop_tool_choice": True,
                "max_temperature": 0.2,
            },
        )

        data = client.get("/api/llm-models").json()
        rows = [
            row for row in data["models"]
            if row.get("entry_id") == "kimi-code"
        ]
        assert rows
        assert rows[0]["id"] == "kimi-for-coding"
        assert rows[0]["display_name"] == "K2.7 Code"
        assert rows[0]["supports_tool_use"] is True
        assert rows[0]["omit_sampling_parameters"] is True
        assert rows[0]["compat_profile"] == "kimi_coding"
        assert rows[0]["thinking_request_style"] == "none"
        assert rows[0]["drop_tool_choice"] is True
        assert rows[0]["max_temperature"] == 0.2


# ═══════════════════════════════════════════════════════════
# Startup rehydration · custom models survive process restart
# ═══════════════════════════════════════════════════════════


class TestStartupHydration:
    def test_disk_state_loaded_on_create_app(
        self, isolated_cwd: Path,
    ) -> None:
        """Create an app, add a model, throw the app away, create a
        new one — the new app must see the model. This is the
        persistence contract the docstring promises."""
        app1 = create_app()
        client1 = TestClient(app1)
        client1.put(
            "/api/config/custom-models/persist-me",
            json={
                "name": "persist-me", "provider": "openai",
                "base_url": "https://p.test",
                "api_key": "sk-p", "model": "gpt-4",
            },
        )

        # Fresh app — reads from the same data/custom_models.json
        app2 = create_app()
        client2 = TestClient(app2)
        listing = client2.get("/api/config/custom-models").json()
        ids = {m["id"] for m in listing["models"]}
        assert "persist-me" in ids


# ═══════════════════════════════════════════════════════════
# GET /api/feature-flags
# ═══════════════════════════════════════════════════════════


class TestFeatureFlagsEndpoint:
    def test_lists_registered_flags(self, client: TestClient) -> None:
        r = client.get("/api/feature-flags")
        assert r.status_code == 200
        data = r.json()
        assert "flags" in data
        names = {entry["name"] for entry in data["flags"]}
        # A few canonical flags that must always be present.
        assert "regeneration.enabled" in names
        assert "safety.invariants_enabled" in names
        assert "ui.ambient_suggestions" in names

    def test_each_entry_has_full_schema(
        self, client: TestClient,
    ) -> None:
        r = client.get("/api/feature-flags")
        for entry in r.json()["flags"]:
            assert set(entry.keys()) >= {
                "name",
                "value",
                "source",
                "default",
                "description",
                "experimental",
                "primary_env",
                "legacy_env",
            }

    def test_reload_endpoint_returns_fresh_snapshot(
        self,
        client: TestClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:

        # Default for camouflage.enabled is False; flip via env then
        # reload through the endpoint and confirm the new value
        # comes through.
        monkeypatch.setenv("OCTOPUS_FF_CAMOUFLAGE_ENABLED", "1")
        r = client.post("/api/feature-flags/reload")
        assert r.status_code == 200
        entry = next(
            e for e in r.json()["flags"] if e["name"] == "camouflage.enabled"
        )
        assert entry["value"] is True
        assert entry["source"] == "env"
