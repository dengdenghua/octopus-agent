from __future__ import annotations

import json

import pytest

from runtime.platform.models import model_capabilities as caps
from tools.refresh_model_capabilities import distill


@pytest.fixture(autouse=True)
def _clear_capability_cache():
    """The snapshot is cached process-wide; isolate every test from the rest."""
    caps.reset_capability_cache()
    yield
    caps.reset_capability_cache()


def _write_snapshot(tmp_path, models: dict) -> None:
    target = tmp_path / "resources" / "models"
    target.mkdir(parents=True)
    (target / "capabilities.json").write_text(
        json.dumps({"source": "test", "models": models}),
        encoding="utf-8",
    )


@pytest.fixture
def snapshot(tmp_path, monkeypatch):
    """Point the loader at a snapshot we control."""

    def _install(models: dict) -> None:
        _write_snapshot(tmp_path, models)
        monkeypatch.setenv("OCTOPUS_RESOURCES_DIR", str(tmp_path))
        caps.reset_capability_cache()

    return _install


def test_reads_context_window_and_temperature_from_the_snapshot(snapshot) -> None:
    snapshot({"model-a": {"context": 1_048_576, "temperature": False}})

    assert caps.known_model_context_window("model-a") == 1_048_576
    assert caps.model_rejects_temperature("model-a") is True


def test_unknown_models_claim_nothing(snapshot) -> None:
    """An absent model must leave behaviour exactly as it was before."""
    snapshot({"model-a": {"context": 1000}})

    assert caps.known_model_context_window("nope") is None
    assert caps.model_rejects_temperature("nope") is False


def test_temperature_is_only_reported_when_upstream_says_false(snapshot) -> None:
    # ``temperature: true`` is the default assumption, so the refresher does
    # not record it — a model with no key must not read as "rejects".
    snapshot({"plain": {"context": 1000}})

    assert caps.model_rejects_temperature("plain") is False


def test_matches_through_our_own_id_decorations(snapshot) -> None:
    """``::1m`` suffixes and ``vendor/model`` prefixes must still resolve."""
    snapshot({"kimi-k3": {"context": 1_048_576, "temperature": False}})

    assert caps.known_model_context_window("kimi-k3::1m") == 1_048_576
    assert caps.model_rejects_temperature("moonshotai/kimi-k3") is True


def test_a_missing_snapshot_degrades_silently(tmp_path, monkeypatch) -> None:
    """No snapshot on disk must not raise — every caller is on a model path."""
    monkeypatch.setenv("OCTOPUS_RESOURCES_DIR", str(tmp_path))
    caps.reset_capability_cache()

    assert caps.known_model_context_window("anything") is None
    assert caps.model_rejects_temperature("anything") is False


def test_a_corrupt_snapshot_degrades_silently(tmp_path, monkeypatch) -> None:
    target = tmp_path / "resources" / "models"
    target.mkdir(parents=True)
    (target / "capabilities.json").write_text("{not json", encoding="utf-8")
    monkeypatch.setenv("OCTOPUS_RESOURCES_DIR", str(tmp_path))
    caps.reset_capability_cache()

    assert caps.known_model_context_window("anything") is None
    assert caps.model_rejects_temperature("anything") is False


def test_the_shipped_snapshot_loads_and_carries_real_models() -> None:
    """Guard the vendored artifact itself, not just the loader."""
    assert caps.known_model_context_window("kimi-k3") is not None
    assert caps.model_rejects_temperature("kimi-k3") is True


def test_distill_keeps_only_actionable_claims() -> None:
    raw = {
        "prov": {
            "models": {
                "keeps-both": {
                    "limit": {"context": 200_000, "output": 8_192},
                    "temperature": False,
                    "cost": {"input": 1.0},
                },
                "keeps-context-only": {"limit": {"context": 128_000}, "temperature": True},
                "dropped-entirely": {"temperature": True, "cost": {"input": 1.0}},
                "bad-context": {"limit": {"context": 0}},
            }
        }
    }

    assert distill(raw) == {
        "keeps-both": {"context": 200_000, "temperature": False},
        "keeps-context-only": {"context": 128_000},
    }


def test_distill_keeps_the_first_provider_for_a_duplicated_model() -> None:
    """A model id appears under both a relay and its vendor; do not arbitrate."""
    raw = {
        "a": {"models": {"shared": {"limit": {"context": 100_000}}}},
        "b": {"models": {"shared": {"limit": {"context": 999_999}}}},
    }

    assert distill(raw)["shared"]["context"] in (100_000, 999_999)
    assert len(distill(raw)) == 1


def test_distill_tolerates_malformed_upstream_shapes() -> None:
    raw = {
        "ok": {"models": {"m": {"limit": {"context": 1000}}}},
        "no-models": {},
        "models-not-a-dict": {"models": []},
        "model-not-a-dict": {"models": {"x": "nope"}},
        "provider-not-a-dict": None,
    }

    assert distill(raw) == {"m": {"context": 1000}}


def test_router_omits_temperature_for_a_model_that_rejects_it(snapshot) -> None:
    """The payload must not carry temperature when upstream says it 400s.

    Measured: kimi-k3 answers HTTP 400 for any temperature value, while its
    siblings on the same relay accept it. Before this, the only protection was
    an operator hand-setting ``omit_sampling_parameters`` per entry, which
    nobody does for the dozens of models a relay exposes.
    """
    snapshot({"picky": {"temperature": False}})
    from runtime.platform.models.llm import ModelRequest
    from runtime.sensing.model_router.openai_router import OpenAIModelRouter

    router = OpenAIModelRouter(
        base_url="https://relay.example/v1", api_key="sk-test", default_model="picky"
    )
    request = ModelRequest(
        model="picky", messages=[{"role": "user", "content": "hi"}], temperature=0.7
    )

    assert "temperature" not in router._build_payload(request, "picky")
    # A sibling on the same endpoint is unaffected.
    assert "temperature" in router._build_payload(request, "relaxed")


def test_operator_context_window_beats_the_snapshot(snapshot, monkeypatch) -> None:
    snapshot({"m": {"context": 1_000_000}})
    monkeypatch.setattr(
        "runtime.platform.models.custom_model_flags.custom_model_entry_for",
        lambda _model: {"context_window": 128_000},
    )
    from runtime.platform.models.custom_model_flags import model_context_window

    assert model_context_window("m") == 128_000


def test_snapshot_fills_in_an_undeclared_context_window(snapshot, monkeypatch) -> None:
    """Without this the fallback was a flat guess that truncated real work."""
    snapshot({"m": {"context": 1_000_000}})
    monkeypatch.setattr(
        "runtime.platform.models.custom_model_flags.custom_model_entry_for",
        lambda _model: {"base_url": "https://relay.example/v1"},
    )
    from runtime.platform.models.custom_model_flags import model_context_window

    assert model_context_window("m") == 1_000_000
