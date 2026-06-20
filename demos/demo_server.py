"""Implementation note."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from runtime.adapters.integrations.local_auth import LocalAuthConfig
from runtime.adapters.integrations.local_auth.config import hash_password
from runtime.adapters.integrations.molili import (
    MoliliAuthConfig,
    MoliliConfig,
    MoliliLinkStore,
)
from runtime.core.cerebrum import LLMPlanner
from runtime.core.graph_runtime import GraphRuntime
from runtime.execution.agents import AgentRegistry, make_all_agent_presets
from runtime.execution.all_skills import register_all as register_all_skills
from runtime.execution.suckers import SkillRegistry
from runtime.execution.tool_engine import ToolExecutor
from runtime.memory.hemolymph import ContextComposer
from runtime.memory.journal import JSONLJournal
from runtime.platform.config.builder import BuiltStack
from runtime.platform.config.schema import AgentConfig
from runtime.platform.models import BudgetSpec
from runtime.platform.ui import create_app
from runtime.safety.auth import IdentityStore, TrustEngine
from runtime.sensing.model_router import MoliliModelRouter

# Implementation note.
MOLILI_ROOTS = {
    "test": "https://ai-api-test.dangbei.net/molili-agi",
    "prod": "https://molili.8kbl.com/molili-agi",
}


def build_stack(
    *, journal_path: Path, registry: SkillRegistry,
    journal: JSONLJournal,
    molili_link_store: MoliliLinkStore,
    molili_base_url: str,
) -> BuiltStack:
    """Implementation note."""
    # Implementation note.
    immunity = TrustEngine(unknown_policy="allow")
    executor = ToolExecutor(registry=registry, immunity=immunity, journal=journal)
    runtime = GraphRuntime(executor=executor, journal=journal)

    # Router pipeline:
    #   ModelDispatchRouter
    #     ├── registry (model_id → sub-router, populated at runtime from
    #     │   /api/config/custom-models — users' own OpenAI/Anthropic/etc.)
    #     └── fallback: MoliliModelRouter (Molili presets like glm-4.7 /
    #         minimax-m2.5 — reached when model id isn't a registered custom)
    # Swapping this in for plain MoliliModelRouter is what makes the UI's
    # Implementation note.
    # of silently falling into Molili.
    from runtime.sensing.model_router.dispatch_router import ModelDispatchRouter

    _molili_router = MoliliModelRouter(
        link_store=molili_link_store,
        base_url=f"{molili_base_url}/chatApi/v1",
        default_model="molili",
        timeout_seconds=60.0,
    )
    router = ModelDispatchRouter(fallback=_molili_router)

    composer = ContextComposer(registry=registry, journal=journal)
    planner = LLMPlanner(
        router=router,
        registry=registry,
        composer=composer,
        planner_model="molili",
        default_budget=BudgetSpec(tokens=50_000, usd=0.50, latency_ms=60_000),
        max_nodes=10,
    )

    return BuiltStack(
        config=AgentConfig(),
        registry=registry,
        journal=journal,
        immunity=immunity,
        executor=executor,
        runtime=runtime,
        planner=planner,
    )


def build_app(*, real: bool = False, prod: bool = False) -> object:
    env = "prod" if prod else "test"
    root = MOLILI_ROOTS[env]

    if real:
        auth_cfg = MoliliAuthConfig(
            mock_mode=False,
            sms_send_url=f"{root}/loginApi/v1/sendSms",
            sms_verify_url=f"{root}/loginApi/v1/loginByMobile",
        )
        info_url = f"{root}/userApi/v1/userInfo"
    else:
        # mock_code: in mock mode every phone passes with this fixed code
        # AND the API echoes it back to the frontend as code_for_dev so
        # the SMS login dialog can auto-fill it — no real SMS gateway
        # required, no console-log hunting.
        auth_cfg = MoliliAuthConfig(mock_mode=True, mock_code="888888")
        info_url = None

    idstore = IdentityStore()

    molili_cfg = MoliliConfig(
        enabled=True,
        base_url=f"{root}/chatApi/v1",
        info_url=info_url,
        default_model="molili",
        auth=auth_cfg,
        jwt_secret="demo-secret-at-least-32-characters-long-xxx-yyy-zzz",
        jwt_expire_seconds=24 * 3600,
    )

    local_cfg = LocalAuthConfig(
        enabled=True,
        users={"admin": hash_password("admin123")},
        jwt_secret="demo-secret-at-least-32-characters-long-xxx-yyy-zzz",
    )

    # Implementation note.
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)
    journal_path = data_dir / "demo_events.jsonl"
    link_store_path = data_dir / "demo_molili_links.json"

    journal = JSONLJournal(journal_path)
    link_store = MoliliLinkStore(path=link_store_path)

    # Implementation note.
    # Implementation note.
    # Implementation note.
    # Implementation note.
    registry = SkillRegistry()
    register_all_skills(registry)
    # Implementation note.
    desktop_added = sum(
        1 for n in registry.all_names()
        if n in ("screen_capture", "screen_info", "mouse_click",
                 "mouse_move", "keyboard_type", "keyboard_press")
    )
    if desktop_added > 0:
        import logging as _lg
        _lg.warning(
            "⚠️  真桌面控制技能已注册（%d 个）· 选 Desktop Operator agent 发指令"
            " 会真操作你的鼠标/键盘/截屏 · 慎用",
            desktop_added,
        )
        # Implementation note.
        from runtime.execution.suckers.computer_use_loop import (
            ModelRouterVisionPlanner,
            register_computer_use_loop,
        )
        vision_router_for_desktop = MoliliModelRouter(
            link_store=link_store,
            base_url=f"{root}/chatApi/v1",    # Implementation note.
            default_model="molili",
            timeout_seconds=60.0,
        )
        vision_planner = ModelRouterVisionPlanner(
            router=vision_router_for_desktop,
            model="glm-4.7",
            system_provider="openai",
            max_tokens=256,
        )
        register_computer_use_loop(registry, vision_planner)
        _lg.warning("⚠️  computer_use_loop 已注册（视觉闭环 · 走 Molili GLM-4.7）")

    # Implementation note.
    stack = build_stack(
        journal_path=journal_path, registry=registry, journal=journal,
        molili_link_store=link_store, molili_base_url=root,
    )

    # Research pipeline skill · needs the LLM router for query rewrite +
    # citation synthesis. Hook it in after the stack is built so we can
    # reuse the planner's router rather than standing up a second one.
    try:
        from runtime.research import (
            register_deep_research_skill,
            register_research_skill,
        )
        register_research_skill(registry, router=stack.planner.router)
        register_deep_research_skill(registry, router=stack.planner.router)
        import logging as _lg
        _lg.info("research_answer + deep_research_answer skills registered")
    except Exception as _e:  # noqa: BLE001
        import logging as _lg
        _lg.warning("research skill registration failed: %s", _e)

    # Implementation note.
    agents = AgentRegistry()
    agents.register_all(make_all_agent_presets(stack.runtime))

    # Implementation note.
    # Implementation note.
    # Implementation note.
    from runtime.execution.parallel_agents import (
        ParallelAgentOrchestrator,
        make_stack_subagent_runner,
    )
    parallel_orch = ParallelAgentOrchestrator(
        max_concurrency=8,
        task_runner=make_stack_subagent_runner(
            stack=stack,
            agent_registry=agents,
            default_tokens=50_000,
            default_usd=0.50,
        ),
    )

    # Implementation note.
    from runtime.execution.agents.groups import AgentGroupRegistry
    group_registry = AgentGroupRegistry()

    # Implementation note.
    from runtime.adapters.channels.manager import ChannelManager
    channel_manager = ChannelManager(stack=stack, agent_registry=agents)

    return create_app(
        journal=journal,
        registry=registry,
        molili_config=molili_cfg,
        molili_link_store=link_store,
        local_auth_config=local_cfg,
        cocoloop_identity_store=idstore,
        agent_registry=agents,
        group_registry=group_registry,
        channel_manager=channel_manager,
        stack=stack,
        molili_jwt_secret=molili_cfg.jwt_secret,
        parallel_agent_orchestrator=parallel_orch,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="octopus-agent chat demo")
    ap.add_argument("--real", action="store_true", help="真调 Molili · 真发短信")
    ap.add_argument("--prod", action="store_true", help="生产环境（需配合 --real）")
    ap.add_argument("--port", type=int, default=8766)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    env = "PROD" if args.prod else "TEST"
    mode = f"REAL · {env}" if args.real else "MOCK (no real SMS)"
    logging.info(
        "▶ octopus demo · mode=%s · http://%s:%d · /chat",
        mode, args.host, args.port,
    )
    logging.info(
        "▶ agent mode via /v1/chat/completions (LLMPlanner(Molili))",
    )
    logging.info(
        "▶ 直聊 Molili via /api/molili/openai/v1/chat/completions",
    )
    uvicorn.run(
        build_app(real=args.real, prod=args.prod),
        host=args.host, port=args.port, log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
