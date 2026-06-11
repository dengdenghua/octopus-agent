"""runtime.execution · 执行引擎（Execution Engine）

子包速查：
  agents       → Agent preset 工厂（user-facing roles）
  arms         → Arm + ArmPool —— Worker 池 + 腕足生命周期
  tool_engine  → ToolExecutor —— 单步工具调用 + 鉴权 + Journal
  suckers      → SkillRegistry —— 技能注册 + 发现 + 沙箱测试
  all_skills   → ~200 个 SKILL.md 资产目录
  swarm        → SwarmRuntime —— 多腕并行 + Boids 协调
  parallel_agents / subagents / slash_commands → 子 agent 派发
  misc/        → 杂项 helper（agent_avatar / agent_packs /
                 capability_catalog / capability_permissions /
                 file_write_leases / image_generation /
                 multiagent_contracts / parallel_runner / skill_policy）
"""
from __future__ import annotations

# Backward-compat shims for code that does `from runtime.execution import X`
# where X is a submodule name now living under misc/.
from .misc import (  # noqa: F401
    agent_avatar, agent_packs, capability_catalog, capability_permissions,
    file_write_leases, image_generation, multiagent_contracts,
    parallel_runner, skill_policy,
)
