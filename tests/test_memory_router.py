from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from runtime.memory import user_store
from runtime.platform.process.paths import app_paths
from runtime.platform.ui.app import create_app
from runtime.sensing.gateway.memory_router import create_memory_router


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.chdir(tmp_path)
    return TestClient(create_app())


def test_app_paths_are_cwd_relative(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    paths = app_paths()
    assert paths.data_dir == tmp_path / "data"
    assert paths.custom_models_path == tmp_path / "data" / "custom_models.json"
    assert paths.user_memory_path == tmp_path / "data" / "user_memory.json"
    assert paths.user_memory_config_path == tmp_path / "data" / "user_memory_config.json"
    assert paths.threads_path == tmp_path / "data" / "threads.jsonl"
    assert paths.cron_jobs_path == tmp_path / "data" / "cron_jobs.json"


def test_user_store_resolves_paths_at_call_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    stored = user_store.add_fact("Remember the blue deployment", source="test")

    assert stored is not None
    persisted = tmp_path / "data" / "user_memory.json"
    assert persisted.exists()
    raw = json.loads(persisted.read_text(encoding="utf-8"))
    assert raw["facts"][0]["content"] == "Remember the blue deployment"


def test_memory_api_uses_real_store_before_stub_router(client: TestClient, tmp_path: Path) -> None:
    created = client.post(
        "/api/memory/facts",
        json={
            "content": "Deploys use blue green rollout",
            "category": "ops",
            "source": "manual",
            "scope": "project",
            "project": "octopus",
        },
    )

    assert created.status_code == 200, created.text
    body = created.json()
    assert "_stub" not in body
    assert body["facts"][0]["scope"] == "project"
    assert body["facts"][0]["project"] == "octopus"
    assert (tmp_path / "data" / "user_memory.json").exists()

    results = client.get("/api/memory/search", params={"q": "blue green"}).json()
    assert results[0]["content"] == "Deploys use blue green rollout"
    assert results[0]["relevance"] > 0


def test_memory_config_uses_same_app_paths(client: TestClient, tmp_path: Path) -> None:
    config = client.put(
        "/api/memory/config",
        json={"enabled": False, "max_facts": 12},
    ).json()

    assert config["enabled"] is False
    assert config["max_facts"] == 12
    assert config["storage_path"] == str(tmp_path / "data" / "user_memory.json")
    assert (tmp_path / "data" / "user_memory_config.json").exists()


def test_memory_config_clamps_invalid_and_unbounded_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    config_path = tmp_path / "data" / "user_memory_config.json"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        json.dumps(
            {
                "debounce_seconds": 999_999,
                "max_facts": 999_999,
                "fact_confidence_threshold": "bad",
                "max_injection_tokens": 999_999,
            }
        ),
        encoding="utf-8",
    )

    config = user_store.read_config()

    assert config["debounce_seconds"] == user_store.MAX_DEBOUNCE_SECONDS
    assert config["max_facts"] == user_store.HARD_MAX_FACTS
    assert config["fact_confidence_threshold"] == 0.5
    assert config["max_injection_tokens"] == user_store.HARD_MAX_INJECTION_TOKENS


def test_memory_import_is_normalized_and_trimmed(
    client: TestClient,
) -> None:
    client.put("/api/memory/config", json={"max_facts": 2})

    imported = client.post(
        "/api/memory/import",
        json={
            "user": {
                "workContext": {
                    "summary": "x" * (user_store.MAX_SECTION_SUMMARY_CHARS + 100),
                },
            },
            "facts": [
                {"content": "fact zero"},
                {
                    "content": "fact one",
                    "category": "c" * (user_store.MAX_LABEL_CHARS + 20),
                    "source": "s" * (user_store.MAX_LABEL_CHARS + 20),
                },
                {"content": "fact two"},
            ],
        },
    )

    body = imported.json()
    assert imported.status_code == 200
    assert [fact["content"] for fact in body["facts"]] == ["fact one", "fact two"]
    assert len(body["facts"][0]["category"]) == user_store.MAX_LABEL_CHARS
    assert len(body["facts"][0]["source"]) == user_store.MAX_LABEL_CHARS
    assert len(body["user"]["workContext"]["summary"]) == user_store.MAX_SECTION_SUMMARY_CHARS


def test_add_fact_respects_configured_max_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    user_store.write_config({"max_facts": 2})

    user_store.add_fact("first")
    user_store.add_fact("second")
    user_store.add_fact("third")

    assert [fact["content"] for fact in user_store.read_memory()["facts"]] == [
        "second",
        "third",
    ]


class TestMemoryRouterAuth:
    def _client(self, require_auth: bool) -> TestClient:
        from runtime.safety.auth import Identity, IdentityStore

        store = IdentityStore()
        store.add(Identity(actor_id="alice"), api_key_plaintext="sk-alice")
        app = FastAPI()
        app.include_router(
            create_memory_router(
                identity_store=store,
                require_auth=require_auth,
            )
        )
        return TestClient(app)

    def test_no_auth_required_by_default(self) -> None:
        client = self._client(require_auth=False)
        assert client.get("/api/memory").status_code == 200

    def test_missing_token_rejected_when_required(self) -> None:
        client = self._client(require_auth=True)
        assert client.get("/api/memory").status_code == 401

    def test_valid_token_accepted_when_required(self) -> None:
        client = self._client(require_auth=True)
        assert (
            client.get(
                "/api/memory",
                headers={"Authorization": "Bearer sk-alice"},
            ).status_code
            == 200
        )
