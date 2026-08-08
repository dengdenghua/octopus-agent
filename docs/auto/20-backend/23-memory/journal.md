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
- `ToolEffectIntentEvent`
- `ToolEffectReconciliationEvent`
- `TrajectoryEvent`
- `all_task_progress`
- `current_agent_id`
- `current_conversation_id`
- `current_owner_actor_id`
- `current_tenant_id`
- `journal_context`
- `resume_info`
- `task_progress_snapshot`

## Modules

| Module | Summary |
| --- | --- |
| `_journal_base.py` | — |
| `_journal_models.py` | — |
| `_journal_parse.py` | — |
| `journal.py` | — |
| `journal_context.py` | — |
| `progress.py` | — |
| `progress_tracker.py` | — |
| `resume.py` | — |
| `sqlite_index.py` | SQLite-backed query index over the JSONL journal. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `_journal_base.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class Journal` |  |

### `_journal_models.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class JournalEvent(BaseModel)` |  |
| class | `class StepEvent(JournalEvent)` |  |
| class | `class TrajectoryEvent(JournalEvent)` |  |
| class | `class ImmuneEvent(JournalEvent)` |  |
| class | `class BudgetEvent(JournalEvent)` |  |
| class | `class BudgetBreakerResetEvent(JournalEvent)` | Operator reset for a derived budget/circuit-breaker component. |
| class | `class TaskStartedEvent(JournalEvent)` |  |
| class | `class NodeStartedEvent(JournalEvent)` |  |
| class | `class TaskCheckpointEvent(JournalEvent)` |  |
| class | `class ReactCheckpointEvent(JournalEvent)` | ReAct iteration checkpoint · written after each completed thought→action→observation cycle so a crashed/refreshed session can resume from th |
| class | `class ToolEffectIntentEvent(JournalEvent)` | Durable write-ahead marker for one tool invocation. |
| class | `class ToolEffectReconciliationEvent(JournalEvent)` | Auditable operator decision for an indeterminate external effect. |
| class | `class TaskPausedEvent(JournalEvent)` |  |
| class | `class TaskResumedEvent(JournalEvent)` |  |
| class | `class TokenUsageEvent(JournalEvent)` |  |
| class | `class FileOpEvent(JournalEvent)` |  |
| class | `class FileRollbackEvent(JournalEvent)` |  |
| class | `class PreviewRefreshEvent(JournalEvent)` |  |
| class | `class ReflexHitEvent(JournalEvent)` |  |
| class | `class SkillProposalDecisionEvent(JournalEvent)` | Operator decision for a self-evolution skill proposal. |
| class | `class CurriculumGoalDecisionEvent(JournalEvent)` | Operator decision for a journal-derived learning goal. |
| class | `class McpProposalDecisionEvent(JournalEvent)` | Operator/vet decision for a suggested MCP capability. |
| class | `class ProtocolDriftDecisionEvent(JournalEvent)` | Operator decision for a detected protocol drift event. |
| class | `class SubToolStartEvent(JournalEvent)` | Emitted when a sub-agent begins a tool call. |
| class | `class SubToolEndEvent(JournalEvent)` | Emitted when a sub-agent finishes a tool call. |
| class | `class BrowserArtifactEvent(JournalEvent)` | A browser screenshot (or similar artifact) was produced. |

### `journal.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class InMemoryJournal(Journal)` |  |
| class | `class JSONLJournal(Journal)` |  |

### `journal_context.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def current_agent_id()` |  |
| func | `def current_conversation_id()` |  |
| func | `def current_tenant_id()` |  |
| func | `def current_owner_actor_id()` |  |
| func | `def journal_context(agent_id, conversation_id, tenant_id, owner_actor_id)` |  |

### `progress.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TaskProgressSnapshot` |  |
| func | `def task_progress_snapshot(journal, task_id)` |  |
| func | `def all_task_progress(journal)` |  |

### `progress_tracker.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TaskProgressTracker` |  |

### `resume.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CompletedNode` |  |
| class | `class ResumeInfo` |  |
| func | `def resume_info(journal, task_id)` |  |

### `sqlite_index.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class JournalIndex` | SQLite query index over a JSONL journal. |


## Who imports this

**49** file(s) reference this package:

- **`runtime/_cli_commands.py/`** · 1 file(s)
  - `runtime/_cli_commands.py`
- **`runtime/adapters/`** · 1 file(s)
  - `runtime/adapters/channels/manager.py`
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
- **`runtime/execution/`** · 7 file(s)
  - `runtime/execution/suckers/_ephemeral_events.py`
  - `runtime/execution/suckers/browser_act_skills.py`
  - `runtime/execution/suckers/registry.py`
  - `runtime/execution/swarm/runtime.py`
  - `runtime/execution/tool_engine/_executor_fileops.py`
  - _… and 2 more_
- **`runtime/memory/`** · 3 file(s)
  - `runtime/memory/hemolymph/composer.py`
  - `runtime/memory/learning/promotion_applier.py`
  - `runtime/memory/runtime_state/hub.py`
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
- **`runtime/sensing/`** · 19 file(s)
  - `runtime/sensing/gateway/_observability_journal.py`
  - `runtime/sensing/gateway/_observability_progress_stream.py`
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - `runtime/sensing/gateway/_realtime_react_stream_drive.py`
  - `runtime/sensing/gateway/_realtime_react_stream_reflection.py`
  - _… and 14 more_
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

