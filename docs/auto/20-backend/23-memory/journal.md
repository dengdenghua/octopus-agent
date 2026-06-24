---
type: "MemorySubsystem"
title: "Memory · Journal"
description: "全 append-only 日志 · events: trajectory / immune / budget / step · 所有 agent 行为的 ground truth。"
tags: ["backend", "memory"]
tier: "core"
---
# Memory · Journal

> 全 append-only 日志 · events: trajectory / immune / budget / step · 所有 agent 行为的 ground truth。

**Source**: `runtime/memory/journal/`

## Exports

- `BrowserArtifactEvent`
- `BudgetEvent`
- `BudgetBreakerResetEvent`
- `CompletedNode`
- `CurriculumGoalDecisionEvent`
- `FileOpEvent`
- `FileRollbackEvent`
- `ImmuneEvent`
- `InMemoryJournal`
- `Journal`
- `JournalEvent`
- `JournalEventType`
- `JSONLJournal`
- `JournalIndex`
- `McpProposalDecisionEvent`
- `NodeStartedEvent`
- `PreviewRefreshEvent`
- `ProtocolDriftDecisionEvent`
- `ProgressStatus`
- `ReflexHitEvent`
- `ResumeInfo`
- `SkillProposalDecisionEvent`
- `StepEvent`
- `SubToolEndEvent`
- `SubToolStartEvent`
- `TaskCheckpointEvent`
- `TaskProgressSnapshot`
- `TaskProgressTracker`
- `TaskStartedEvent`
- `TrajectoryEvent`
- `all_task_progress`
- `current_agent_id`
- `current_conversation_id`
- `journal_context`
- `resume_info`
- `task_progress_snapshot`

## Modules

| Module | Summary |
| --- | --- |
| `journal.py` | — |
| `journal_context.py` | — |
| `progress.py` | — |
| `progress_tracker.py` | — |
| `resume.py` | — |
| `sqlite_index.py` | SQLite-backed query index over the JSONL journal. |

## Who imports this

**40** file(s) reference this package:

- **`runtime/adapters/`** · 1 file(s)
  - `runtime/adapters/channels/manager.py`
- **`runtime/cli.py/`** · 1 file(s)
  - `runtime/cli.py`
- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_reflect.py/`** · 1 file(s)
  - `runtime/cli_reflect.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 3 file(s)
  - `runtime/core/cerebrum/llm_planner.py`
  - `runtime/core/cerebrum/resume_cli.py`
  - `runtime/core/graph_runtime/runtime.py`
- **`runtime/execution/`** · 4 file(s)
  - `runtime/execution/suckers/browser_act_skills.py`
  - `runtime/execution/suckers/ephemeral_runner.py`
  - `runtime/execution/swarm/runtime.py`
  - `runtime/execution/tool_engine/executor.py`
- **`runtime/memory/`** · 2 file(s)
  - `runtime/memory/hemolymph/composer.py`
  - `runtime/memory/learning/promotion_applier.py`
- **`runtime/platform/`** · 3 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/ui/app.py`
  - `runtime/platform/ui/state.py`
- **`runtime/safety/`** · 8 file(s)
  - `runtime/safety/recovery/intel_collector.py`
  - `runtime/safety/recovery/kg_updater.py`
  - `runtime/safety/recovery/memory_consolidator.py`
  - `runtime/safety/recovery/recipe_evaluator.py`
  - `runtime/safety/recovery/rule_extractor.py`
  - _… and 3 more_
- **`runtime/sensing/`** · 14 file(s)
  - `runtime/sensing/gateway/dag_debugger_router.py`
  - `runtime/sensing/gateway/evolution_ops/budget.py`
  - `runtime/sensing/gateway/evolution_ops/curriculum.py`
  - `runtime/sensing/gateway/evolution_ops/mcp_ops.py`
  - `runtime/sensing/gateway/evolution_ops/protocol_drift.py`
  - _… and 9 more_
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

