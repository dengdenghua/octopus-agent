"""Serve-mode logic split out from :mod:`runtime.cli`.

The public CLI entrypoint in ``runtime.cli`` re-exports ``run_serve``
from here.  This module also holds the background scheduler registration
helpers used by ``octopus-agent serve``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any


def _yellow(enabled: bool, text: str) -> str:
    return f"\x1b[33m{text}\x1b[0m" if enabled else text


def maybe_setup_prompt_evolution(
    stack: Any,
    runner: Any,
    *,
    prompt_variants_path: Path | None,
    evolve_interval_s: int,
    mutator_model: str,
    color: bool,
) -> tuple[Any, int]:
    """Enable optional live prompt evolution for serve mode."""
    from runtime.core.cerebrum import LLMPlanner

    if prompt_variants_path is None:
        return None, 0
    if not prompt_variants_path.exists():
        print(_yellow(color, f"--prompt-variants not found: {prompt_variants_path} · skipping"))
        return None, 0
    if not isinstance(stack.planner, LLMPlanner):
        print(_yellow(color, "prompt A/B needs LLMPlanner · skipping"))
        return None, 0

    from runtime.safety.experiments import (
        EvolutionPolicy,
        PromptEvolver,
        PromptMutator,
        PromptOptimizer,
        load_variants_from_yaml,
    )
    from runtime.sensing.model_router import MockModelRouter

    variants = load_variants_from_yaml(prompt_variants_path)
    optimizer = PromptOptimizer(
        stack, variants, auto_persist_path=prompt_variants_path,
    )

    evolve_count = 0
    if evolve_interval_s > 0:
        if mutator_model.startswith("mock/"):
            mutator_router = MockModelRouter(
                response="<suffix>prefer shorter plans · check inputs first</suffix>",
            )
        else:
            mutator_router = stack.planner.router
        mutator = PromptMutator(router=mutator_router, model=mutator_model)
        evolver = PromptEvolver(optimizer, mutator, EvolutionPolicy())

        def _evolve_tick() -> None:
            evolver.step()

        runner.add_periodic(
            "prompt_evolve",
            interval_s=float(evolve_interval_s),
            callback=_evolve_tick,
            jitter_s=min(30.0, evolve_interval_s * 0.05),
        )
        evolve_count = 1

    return optimizer, evolve_count


def register_intel_task(
    runner: Any,
    src: Any,
    stack: Any,
) -> int:
    """Register one static IntelSourceConfig item with the scheduler."""
    from runtime.safety.recovery import IntelCollector, IntelSource

    if not stack.registry.has("web_search"):
        return 0

    source = IntelSource(
        source_id=src.source_id,
        query=src.query,
        max_results=src.max_results,
        fetch_top_n=src.fetch_top_n,
    )

    def _tick() -> None:
        IntelCollector(
            sources=[source], journal=stack.journal, registry=stack.registry,
        ).run_once()

    runner.add_periodic(
        f"intel_{src.source_id}",
        interval_s=float(src.frequency_seconds),
        callback=_tick,
        jitter_s=min(30.0, src.frequency_seconds * 0.1),
    )
    return 1


def register_intelligence_subscriptions_task(runner: Any) -> int:
    """Schedule UI-created intelligence subscriptions."""

    try:
        interval_s = int(os.environ.get("OCTOPUS_INTELLIGENCE_POLL_SECONDS") or "1800")
    except ValueError:
        interval_s = 1800
    if interval_s <= 0:
        return 0

    def _tick() -> None:
        from runtime.sensing.gateway.intelligence_router import (
            run_enabled_subscriptions_once,
        )

        run_enabled_subscriptions_once(
            due_only=True,
            max_subscriptions=5,
            max_results_per_query=5,
        )

    runner.add_periodic(
        "intelligence_subscriptions",
        interval_s=float(interval_s),
        callback=_tick,
        jitter_s=min(120.0, interval_s * 0.1),
    )
    return 1


def register_reflection_tasks(
    runner: Any,
    stack: Any,
    interval_s: int,
) -> int:
    """Register the periodic self-improvement tasks for serve mode."""
    from runtime.core.cerebrum import LLMPlanner, StaticPlanner

    count = 0
    jitter = min(30.0, interval_s * 0.05)

    if isinstance(stack.planner, LLMPlanner):
        def _learn_rules() -> None:
            stack.planner.learn_from_journal(stack.journal)

        def _learn_memories() -> None:
            stack.planner.learn_memories_from_journal(stack.journal)

        def _learn_kg() -> None:
            stack.planner.learn_kg_from_journal(stack.journal)

        def _assess_recipe() -> None:
            stack.planner.assess_recipe_from_journal(stack.journal)

        runner.add_periodic(
            "reflect_rules", interval_s, _learn_rules, jitter_s=jitter,
        )
        runner.add_periodic(
            "reflect_memories", interval_s, _learn_memories, jitter_s=jitter,
        )
        runner.add_periodic(
            "reflect_kg", interval_s, _learn_kg, jitter_s=jitter,
        )
        runner.add_periodic(
            "reflect_recipe", interval_s, _assess_recipe, jitter_s=jitter,
        )
        count += 4

    if isinstance(stack.planner, StaticPlanner):
        def _rewrite() -> None:
            stack.planner.rewrite_from_journal(stack.journal)

        runner.add_periodic(
            "reflect_workflow", interval_s, _rewrite, jitter_s=jitter,
        )
        count += 1

    def _forge() -> None:
        from runtime.safety.recovery import SkillForge

        SkillForge(journal=stack.journal, registry=stack.registry).run()

    runner.add_periodic(
        "reflect_skill_forge", interval_s, _forge, jitter_s=jitter,
    )
    count += 1

    return count


def run_serve(
    *,
    config_path: Path,
    host: str,
    port: int,
    uds: str | None = None,
    learn_interval_s: int = 0,
    prompt_variants_path: Path | None = None,
    evolve_interval_s: int = 0,
    mutator_model: str = "mock/mutator",
    color: bool = True,
) -> int:
    import sys

    from runtime.adapters.scheduler import BackgroundRunner
    from runtime.cli_core import _Colors
    from runtime.platform.config import ConfigLoadError, build_from_config, load_from_yaml
    from runtime.platform.i18n import _

    c = _Colors(color)
    try:
        cfg = load_from_yaml(config_path)
    except ConfigLoadError as e:
        print(c.red(f"config error: {e}"), file=sys.stderr)
        return 2

    try:
        import uvicorn

        from runtime.platform.ui import create_app
    except ImportError:
        print(_("cli.ui.not_installed"), file=sys.stderr)
        return 2

    stack = build_from_config(cfg)
    runner = BackgroundRunner(name=f"scheduler-{cfg.name}")

    # Constitution LLM-judge tier (opt-in via safety.enable_llm_judge /
    # OCTOPUS_ENABLE_LLM_JUDGE). gate.check_outbound consults the judge
    # on every outbound message; without this registration the tier is
    # a null allow-all. Fail-open: registration problems must not stop
    # serve — the regex rule layer remains the hard floor.
    try:
        from runtime.safety.validation.bootstrap import maybe_register_llm_judge

        judge_router = getattr(getattr(stack, "planner", None), "router", None)
        # Read the flag off the LOADED config (respects --config outside
        # cwd). enabled=None would fall back to the env var / cwd yaml,
        # which silently ignored a non-cwd --config; explicit-wins
        # precedence in llm_judge_enabled honours this value, while the
        # env var can still force-disable in an emergency.
        safety_cfg = getattr(cfg, "safety", None)
        judge_cfg_value = getattr(safety_cfg, "enable_llm_judge", None)
        judge_model = getattr(safety_cfg, "llm_judge_model", None)
        if maybe_register_llm_judge(
            judge_router, config_value=judge_cfg_value, model=judge_model
        ):
            print(_yellow(color, "constitution LLM judge: enabled"))
    except Exception:  # noqa: BLE001 — never block startup on judge wiring
        logging.getLogger(__name__).debug("llm judge bootstrap failed", exc_info=True)

    intel_count = 0
    for src in cfg.intel_sources:
        intel_count += register_intel_task(runner, src, stack)
    intel_count += register_intelligence_subscriptions_task(runner)

    reflection_count = 0
    if learn_interval_s > 0:
        reflection_count = register_reflection_tasks(
            runner, stack, learn_interval_s,
        )

    optimizer, evolve_count = maybe_setup_prompt_evolution(
        stack, runner,
        prompt_variants_path=prompt_variants_path,
        evolve_interval_s=evolve_interval_s,
        mutator_model=mutator_model,
        color=color,
    )

    agent_registry = None
    group_registry = None
    channel_manager = None
    try:
        from runtime.execution.agents import (
            AGENT_PRESET_FACTORIES,
            AgentGroupRegistry,
            AgentRegistry,
        )

        agent_registry = AgentRegistry()
        for factory in AGENT_PRESET_FACTORIES:
            try:
                agent_registry.register(factory(stack.runtime))
            except Exception as exc:
                logging.getLogger(__name__).debug("agent preset registration failed: %s", exc)
                continue

        try:
            from runtime.execution.agents.presets import make_admin_agent
            agent_registry.register(make_admin_agent(stack.runtime))
        except Exception as exc:
            logging.getLogger(__name__).debug("admin agent registration failed: %s", exc)

        group_registry = AgentGroupRegistry()
    except Exception as exc:
        logging.getLogger(__name__).debug("agent/group registry init failed: %s", exc)
        agent_registry = None
        group_registry = None

    try:
        from runtime.adapters.channels import ChannelManager
        channel_manager = ChannelManager(
            stack=stack,
            agent_registry=agent_registry,
            default_agent_id="general",
        )
    except Exception as exc:
        logging.getLogger(__name__).debug("channel manager init failed: %s", exc)
        channel_manager = None

    app = create_app(
        journal=stack.journal,
        registry=stack.registry,
        stack=stack,
        agent_registry=agent_registry,
        group_registry=group_registry,
        channel_manager=channel_manager,
        molili_config=cfg.molili,
        local_auth_config=cfg.local_auth,
    )
    try:
        from runtime.cli_core import _build_reflex_router
        from runtime.sensing.gateway import create_openai_router

        app.include_router(create_openai_router(
            stack,
            default_arm=cfg.default_arm_id,
            reflex_router=_build_reflex_router(),
            prompt_optimizer=optimizer,
            agent_registry=agent_registry,
        ))
    except (OSError, ValueError, TypeError):  # noqa: BLE001 — agent registry init best-effort; service starts without it
        pass

    print(c.bold(_("cli.serve.url_fmt", host=host, port=port)))
    if uds:
        print(c.bold(f"  unix socket: {uds}  (ws+unix:///{uds})"))
    print(c.dim("\u2500" * 60))
    print(f"  config={config_path} \u00b7 planner={cfg.planner.type}")

    _p = cfg.planner
    if _p.type == "llm" and (
        _p.model.startswith("mock/") or _p.mock_response is not None
    ):
        print(c.red(
            f"  \u26a0\ufe0f  MOCK PLANNER \u00b7 planner.model={_p.model} \u00b7 "
            f"mock_response={'set' if _p.mock_response else 'null'}"
        ))
        print(c.red(
            "      \u6240\u6709\u56de\u590d\u5747\u4e3a\u5360\u4f4d mock \u6570\u636e \u00b7 \u975e\u6d4b\u8bd5\u73af\u5883\u8bf7\u6362 --config"
            " \u6307\u5411\u771f\u5b9e LLM \u914d\u7f6e\uff08\u4f8b\u5982 config.local.yaml\uff09"
        ))
    print(
        _("cli.serve.scheduler_info", total=len(runner.task_names()), intel=intel_count, reflection=reflection_count, evolve=evolve_count)
    )
    if optimizer is not None:
        print(_("cli.serve.prompt_ab_info", variants=optimizer.variant_names))

    runner.start()
    try:
        import logging as _logging
        _NOISY_ROUTES = (
            "/api/agents",
            "/api/llm-models",
            "/api/files/stream",
            "/api/preview/stream",
            "/api/evolution/status",
            "/api/auth/status",
            "/api/auth/providers",
            "/api/threads/search",
            "/api/tasks?",
            "/api/regeneration/status",
            "/history HTTP",
        )

        class _DropPollingAccess(_logging.Filter):
            def filter(self, record: _logging.LogRecord) -> bool:
                msg = record.getMessage()
                if " 200 " not in msg and " 304 " not in msg:
                    return True
                return all(r not in msg for r in _NOISY_ROUTES)

        _logging.getLogger("uvicorn.access").addFilter(_DropPollingAccess())

    except Exception as exc:
        logging.getLogger(__name__).debug("uvicorn filter setup failed: %s", exc)

    try:
        if uds:
            import contextlib
            import os
            with contextlib.suppress(FileNotFoundError):
                os.unlink(uds)
            uvicorn.run(app, uds=uds, log_level="info")
        else:
            uvicorn.run(app, host=host, port=port, log_level="info")
    finally:
        runner.stop()
        try:
            from runtime.adapters.mcp_client import close_all_persistent_clients
            close_all_persistent_clients()
        except Exception as exc:
            logging.getLogger(__name__).debug("mcp client shutdown failed: %s", exc)
        print(c.dim(_("cli.serve.stopped")))
        for name, st in runner.stats().items():
            print(_("cli.serve.task_stat", name=name, success=st.success_count, errors=st.error_count))
        if optimizer is not None:
            print(c.dim(_("cli.serve.ranking")))
            for name, rep in sorted(
                optimizer.report().items(),
                key=lambda kv: kv[1].success_rate,
                reverse=True,
            ):
                print(
                    _("cli.serve.variant_info", name=name, uses=rep.assignments, rate=rep.success_rate, verdict=rep.verdict)
                )
    return 0
