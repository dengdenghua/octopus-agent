---
type: "RuntimeSubsystem"
title: "Cerebrum · 规划器"
description: "LLM Planner + Static Planner · 把自然语言意图拆成 TaskGraph。"
tags: ["backend", "runtime"]
tier: "core"
---
# Cerebrum · 规划器

> LLM Planner + Static Planner · 把自然语言意图拆成 TaskGraph。

**Source**: `runtime/core/cerebrum/`

## Exports

- `LLMPlanner`
- `PlannerError`
- `StaticPlanner`

## Modules

| Module | Summary |
| --- | --- |
| `agent_auto_delegate.py` | Auto-delegate to pinned agents on the first ReAct step. |
| `ai_mode.py` | AI Mode — Marvis-style two-mode wrapper over the 3-tier router. |
| `capability_router.py` | — |
| `checkpoint_integrity.py` | — |
| `checkpoint_mirror.py` | Distributed checkpoint mirror — P3 fourth slice. |
| `completion_receipt.py` | — |
| `input_mentions.py` | Parse @plugin/@skill/@agent mention tokens from user prompts. |
| `llm_planner.py` | — |
| `output_styles.py` | Per-turn output style overlays for the ReAct system prompt. |
| `pause_control.py` | — |
| `planner.py` | — |
| `plugin_auto_load.py` | Auto-activate pinned plugins/skill-packs from user mentions. |
| `prompt_persistence.py` | — |
| `react_checkpointing.py` | Periodic auto-checkpoint + distributed mirror for the ReAct loop. |
| `react_context.py` | — |
| `react_execution.py` | — |
| `react_guards.py` | ReAct trajectory guards: post-step / pre-Final-Answer quality gates. |
| `react_loop.py` | — |
| `react_loop_controls.py` | Operator controls + run-budget knobs for the ReAct loop. |
| `react_native.py` | Native tool-use path for the single-agent ReAct loop. |
| `react_parallel_dispatch.py` | Concurrent multi-action dispatcher for the ReAct loop (口子 2). |
| `react_parsing.py` | ReAct trajectory parsing + post-step quality checks. |
| `react_security_detectors.py` | Security + quality detectors for ReAct trajectory steps. |
| `react_security_guards.py` | Security + quality guards (post-step / pre-Final-Answer gates). |
| `react_types.py` | — |
| `resume_cli.py` | CLI for inspecting + driving ReAct checkpoint resume (P3 long-task durability). |
| `rules_persistence.py` | — |
| `run_state.py` | — |
| `stable_prompt.py` | Cache-stable prompt builder. |
| `thinking_mode.py` | Structured thinking-mode helpers. |
| `todo_protocol.py` | Shared rules for the user-visible task checklist protocol. |
| `token_juicer.py` | Token compression for tool observations before they enter the LLM message stream. |
| `tool_output_sink.py` | Optional side-channel for streaming tool stdout/stderr. |
| `turn_complexity.py` | Three-tier smart model routing. |
| `verification_policy.py` | — |

## Who imports this

**37** file(s) reference this package:

- **`runtime/cli_code.py/`** · 1 file(s)
  - `runtime/cli_code.py`
- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_reflect.py/`** · 1 file(s)
  - `runtime/cli_reflect.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/cli_serve.py/`** · 1 file(s)
  - `runtime/cli_serve.py`
- **`runtime/core/`** · 1 file(s)
  - `runtime/core/graph_runtime/runtime.py`
- **`runtime/execution/`** · 6 file(s)
  - `runtime/execution/loops/controller.py`
  - `runtime/execution/misc/parallel_runner.py`
  - `runtime/execution/parallel_agents/orchestrator.py`
  - `runtime/execution/parallel_agents/stack_runner.py`
  - `runtime/execution/swarm/runtime.py`
  - `runtime/execution/tool_spec_builder.py`
- **`runtime/memory/`** · 1 file(s)
  - `runtime/memory/diagnostics/trace_store.py`
- **`runtime/platform/`** · 5 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/lifecycle/demo.py`
  - `runtime/platform/process/streaming.py`
  - `runtime/platform/ui/app.py`
  - `runtime/platform/ui/reflex_admin_router.py`
- **`runtime/safety/`** · 4 file(s)
  - `runtime/safety/experiments/prompt_optimizer.py`
  - `runtime/safety/recovery/gepa_bridge.py`
  - `runtime/safety/recovery/workflow_applier.py`
  - `runtime/safety/validation/trust_signal.py`
- **`runtime/sensing/`** · 12 file(s)
  - `runtime/sensing/gateway/agents_router.py`
  - `runtime/sensing/gateway/config_router.py`
  - `runtime/sensing/gateway/evolution_ops/recipe_forge.py`
  - `runtime/sensing/gateway/observability_router.py`
  - `runtime/sensing/gateway/openai_gateway/context_manager.py`
  - _… and 7 more_
- **`runtime/tentacle/`** · 2 file(s)
  - `runtime/tentacle/coordinator.py`
  - `runtime/tentacle/mobile/cerebrum_adapter.py`
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

