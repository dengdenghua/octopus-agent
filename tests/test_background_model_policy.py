"""External-engine defaults preserve maintenance without unattended model calls."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from runtime.execution.model_services import background_model_calls_enabled, background_model_router
from runtime.platform.config.schema import AgentConfig, ExecutionConfig


@pytest.mark.parametrize("engine", ["opencode", "octopus"])
@pytest.mark.parametrize("choice", [None, False, True])
def test_background_policy_is_separate_and_explicit(engine, choice):
    stack = SimpleNamespace(
        config=AgentConfig(
            execution=ExecutionConfig(member_engine=engine, background_model_calls=choice)
        )
    )
    assert background_model_calls_enabled(stack) is (
        choice if choice is not None else engine == "octopus"
    )


def test_disabled_and_independent_service_never_access_planner():
    class Host:
        config = AgentConfig()

        @property
        def planner(self):
            raise AssertionError("background policy accessed native planner")

    host = Host()
    assert background_model_router(host) is None
    host.config = AgentConfig(execution=ExecutionConfig(background_model_calls=True))
    host.background_router = object()
    assert background_model_router(host) is host.background_router
    host.background_router = None
    assert background_model_router(host) is None


def test_memory_scheduler_keeps_real_deterministic_buckets(tmp_path, monkeypatch):
    from runtime.cli_serve import register_memory_distill_task
    from runtime.memory.users import user_store

    monkeypatch.setenv("OCTOPUS_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("OCTOPUS_MEMORY_DISTILL_SECONDS", "3600")
    memory = user_store.empty_memory()
    memory["facts"] = [
        {"id": "preference", "content": "用户喜欢简洁回复", "category": "preference"}
    ]
    user_store.write_memory(memory)

    class Host:
        config = AgentConfig()

        @property
        def planner(self):
            raise AssertionError("deterministic maintenance accessed native planner")

    scheduler = Mock()
    assert register_memory_distill_task(scheduler, Host()) == 1
    callback = scheduler.add_periodic.call_args.kwargs["callback"]
    callback()
    assert "简洁" in user_store.read_memory()["user"]["personalContext"]["summary"]


def test_disabled_jobs_do_not_construct_model_components(tmp_path, monkeypatch):
    from runtime.cli_serve import maybe_setup_prompt_evolution
    from runtime.safety.evolution.auto_trigger import AutoTriggerConfig, EvolutionAutoTrigger
    from runtime.safety.experiments.scheduler import CamouflageConfig, CamouflageScheduler

    class Host:
        config = AgentConfig()

        @property
        def planner(self):
            raise AssertionError("disabled background job accessed planner")

        @property
        def is_llm_planner(self):
            raise AssertionError("disabled background job inspected planner")

    host = Host()
    assert maybe_setup_prompt_evolution(
        host,
        Mock(),
        prompt_variants_path=tmp_path / "variants.yaml",
        evolve_interval_s=10,
        mutator_model="external",
        color=False,
    ) == (None, 0)
    trigger = EvolutionAutoTrigger()
    monkeypatch.setattr(
        trigger, "_wire_events", Mock(side_effect=AssertionError("events activated"))
    )
    trigger.start(host, AutoTriggerConfig(enabled=True))
    assert not trigger._active
    assert trigger.status()["background_model_calls"] is False
    scheduler = CamouflageScheduler()
    monkeypatch.setattr(
        scheduler, "_build_components", Mock(side_effect=AssertionError("models built"))
    )
    scheduler.start(host, CamouflageConfig(enabled=True))
    assert scheduler._thread is None
