"""runtime.platform · 平台横切设施（Platform Infrastructure）

子包速查：
  budget         → 预算跟踪与限制
  config         → 配置加载与校验
  credentials    → 凭证管理
  i18n           → 国际化与本地化
  io             → 文件 I/O + atomic write
  models         → Pydantic 数据模型
  prompts        → prompt 资产管理
  ui             → Web UI 后端 routes

  process/       → 进程级状态与生命周期（session / state / scope / paths /
                   utils / eventbus / distributed_lock / streaming /
                   service_provider / event_bridge / turn_model /
                   session_executor）
  observability/ → 可观测性（metrics / health / logging_config /
                   structured_logging / redactor / doctor）
  plugins/       → 插件系统（plugin_base / plugin_compat / plugin_hub /
                   plugin_loader / plugins / skill_market）
  lifecycle/     → 部署与迁移（backup / data_migration / factory_reset /
                   setup_wizard / demo）
  llm_infra/     → LLM 基础设施（llm_cache / llm_caller / budget_tracker）
  runtime_policy/→ 运行时策略（browser_sessions / capabilities /
                   feature_flags / idempotency / identity_filter / retry /
                   workspaces）
"""
from __future__ import annotations

from runtime.platform.plugins.plugin_loader import PluginLoader, get_plugin_loader

# Top-level convenience re-exports (unchanged from before)
from runtime.platform.process.eventbus import DomainEvent, EventBus, get_eventbus
from runtime.platform.process.state import StateStore, get_statestore

__all__ = [
    "DomainEvent",
    "EventBus",
    "PluginLoader",
    "StateStore",
    "get_eventbus",
    "get_plugin_loader",
    "get_statestore",
]

# Backward-compat shims for code that does `from runtime.platform import X`
# where X is a submodule name.
from .lifecycle import (  # noqa: F401
    backup,
    data_migration,
    demo,
    factory_reset,
    setup_wizard,
)
from .llm_infra import (  # noqa: F401
    budget_tracker,
    llm_cache,
    llm_caller,
)
from .observability import (  # noqa: F401
    doctor,
    health,
    logging_config,
    metrics,
    redactor,
    structured_logging,
)
from .plugins import (  # noqa: F401
    plugin_base,
    plugin_compat,
    plugin_hub,
    plugin_loader,
    plugins,
    skill_market,
)
from .process import (  # noqa: F401
    distributed_lock,
    event_bridge,
    eventbus,
    paths,
    scope,
    service_provider,
    session,
    session_executor,
    state,
    streaming,
    turn_model,
    utils,
)
from .runtime_policy import (  # noqa: F401
    browser_sessions,
    capabilities,
    feature_flags,
    idempotency,
    identity_filter,
    retry,
    workspaces,
)
