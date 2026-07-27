---
type: "RuntimeSubsystem"
title: "Suckers · 技能注册"
description: "Skill 注册表 · 原子层 · 沙箱 · 测试 tier。"
tags: ["backend", "runtime"]
tier: "core"
---
# Suckers · 技能注册

> Skill 注册表 · 原子层 · 沙箱 · 测试 tier。

**Source**: `runtime/execution/suckers/`

## Package summary

Suckers = skill pool.

## Exports

- `ATOMIC_SKILL_NAMES`
- `DEFAULT_CAPACITY`
- `DEFAULT_REFILL_RATE`
- `Skill`
- `SkillNotFound`
- `SkillRateLimiter`
- `SkillRegistry`
- `SkillSearcher`
- `SkillExpect`
- `SkillTestCase`
- `SkillTester`
- `SkillTestReport`
- `SkillTestResult`
- `SkillTestsFailed`
- `SkillTestTier`
- `TIER_THRESHOLDS`
- `TfIdfSkillSearcher`
- `dump_forged_skill_to_md`
- `is_atomic`
- `load_forged_skills_from_dir`

## Modules

| Module | Summary |
| --- | --- |
| `agent_doc_skills.py` | Agent documentation skills loaded from ``skills/public``. |
| `agent_meta_skills.py` | — |
| `ask_user_question.py` | ask_user_question · pause-and-ask skill. |
| `blackboard_skills.py` | blackboard_skills · expose the turn-scoped shared dict as 3 skills. |
| `browser_act_skills.py` | — |
| `browser_backend.py` | Unified browser automation backend — the seam over three tracks. |
| `browser_backends.py` | Real BrowserBackend adapters over the three automation tracks. |
| `browser_backends_mock.py` | Mock browser backend — scripted, deterministic, no runtime needed. |
| `browser_dom_js.py` | Shared in-page JavaScript for browser perception. |
| `browser_session_worker.py` | Persistent, thread-affine browser sessions for agent browser skills. |
| `browser_skills.py` | — |
| `builtins.py` | — |
| `capability_skills.py` | — |
| `code_edit_skills.py` | AST-aware code editing skills · tree-sitter powered. |
| `code_intelligence_skills.py` | — |
| `codex_plugin_skills.py` | — |
| `computer_api_skills.py` | Agent-facing computer automation skills. |
| `computer_skills.py` | — |
| `computer_uia_skills.py` | — |
| `computer_use_loop.py` | — |
| `computer_use_record.py` | Record a successful computer-use loop as a journal Trajectory. |
| `crawler_skills.py` | — |
| `cron_skills.py` | cron_skills · let the agent self-schedule a future turn from inside a turn. |
| `delegation_budget.py` | Smart per-turn delegation budget. |
| `delegation_skills.py` | — |
| `desktop_grounding.py` | Semantic grounding for the desktop vision loop. |
| `echo_skills.py` | ECHO Universe Engine 叙事 Ganglion 接入. |
| `enterprise_skills.py` | Octopus Enterprise 企业服务 Arm 接入. |
| `ephemeral_agents.py` | Ephemeral sub-agent roles · lightweight personas for one-shot delegation tasks (``researcher`` / ``debugger`` / ``reviewer`` / …). |
| `ephemeral_injection_gate.py` | Prompt-injection taint gate for ephemeral sub-agent tool calls. |
| `ephemeral_runner.py` | LLM-backed runner for ephemeral sub-agent roles. |
| `forged_persistence.py` | — |
| `fs_search_skills.py` | — |
| `hub/installer.py` | — |
| `image_search_backends.py` | Image-search provider backends for the kimi-compat skill group. |
| `kg_skill.py` | — |
| `kimi_compat_skills.py` | — |
| `layers.py` | — |
| `loader/md_loader.py` | — |
| `lsp_skills.py` | LSP (Language Server Protocol) integration skills. |
| `market_skills.py` | — |
| `memory_skills.py` | memory_skills · per-agent long-term memory / user-profile / diary skills. |
| `notebook_skills.py` | — |
| `plan_mode.py` | — |
| `rate_limit.py` | Per-skill rate limiter — runaway-loop protection for LLM agents. |
| `registry.py` | — |
| `search.py` | Semantic skill search — TF-IDF-based skill discovery. |
| `skill_library_skills.py` | skill_library_skills · expose Kimi-style "learned skills" as 3 skills. |
| `storage_skills.py` | File Agent document search via the octopus-storage sibling service. |
| `sub_agent.py` | Legacy compatibility shim for subagent dispatch. |
| `testing.py` | — |
| `verdict_repair.py` | Verdict-gated repair loop — the closed-loop orchestration octopus lacked. |
| `verify_skills.py` | Project verification · detect project type and run checks. |
| `web_skills.py` | — |
| `write_skills.py` | — |

## Who imports this

**51** file(s) reference this package:

- **`runtime/adapters/`** · 1 file(s)
  - `runtime/adapters/mcp_client/bridge.py`
- **`runtime/cli.py/`** · 1 file(s)
  - `runtime/cli.py`
- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_reflect.py/`** · 1 file(s)
  - `runtime/cli_reflect.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 5 file(s)
  - `runtime/core/cerebrum/capability_router.py`
  - `runtime/core/cerebrum/llm_planner.py`
  - `runtime/core/cerebrum/react_context.py`
  - `runtime/core/cerebrum/react_execution.py`
  - `runtime/core/cerebrum/react_loop.py`
- **`runtime/execution/`** · 6 file(s)
  - `runtime/execution/all_skills/__init__.py`
  - `runtime/execution/arms/base.py`
  - `runtime/execution/loops/verifiers.py`
  - `runtime/execution/misc/skill_policy.py`
  - `runtime/execution/subagents/bridge.py`
  - `runtime/execution/tool_engine/executor.py`
- **`runtime/memory/`** · 3 file(s)
  - `runtime/memory/cowork/runtime.py`
  - `runtime/memory/hemolymph/composer.py`
  - `runtime/memory/learning/deep_evolution.py`
- **`runtime/platform/`** · 5 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/lifecycle/demo.py`
  - `runtime/platform/ui/app.py`
  - `runtime/platform/ui/browser_router.py`
  - `runtime/platform/ui/state.py`
- **`runtime/research/`** · 2 file(s)
  - `runtime/research/pipeline.py`
  - `runtime/research/prefetch.py`
- **`runtime/safety/`** · 6 file(s)
  - `runtime/safety/evolution/auto_trigger.py`
  - `runtime/safety/evolution/browser_desktop_quality.py`
  - `runtime/safety/evolution/browser_desktop_repair_recipes.py`
  - `runtime/safety/hooks/tool_edge_hooks.py`
  - `runtime/safety/recovery/intel_collector.py`
  - `runtime/safety/recovery/skill_forge.py`
- **`runtime/sensing/`** · 18 file(s)
  - `runtime/sensing/gateway/agent_world_router.py`
  - `runtime/sensing/gateway/computer_actions.py`
  - `runtime/sensing/gateway/computer_router.py`
  - `runtime/sensing/gateway/debug_router.py`
  - `runtime/sensing/gateway/evolution_ops_router.py`
  - _… and 13 more_
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

