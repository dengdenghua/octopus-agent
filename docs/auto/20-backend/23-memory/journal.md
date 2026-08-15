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

- `AssistantChunkEvent`
- `BrowserArtifactEvent`
- `BudgetEvent`
- `BudgetBreakerResetEvent`
- `CompletedNode`
- `CurriculumGoalDecisionEvent`
- `FileOpEvent`
- `FileRollbackEvent`
- `HookInvokedEvent`
- `HookResultEvent`
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
- `SessionSummary`
- `StepEvent`
- `SubSessionSummaryEvent`
- `SubTextDeltaEvent`
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
| `_chunk_rows.py` | Lossless storage packing for delta-chunk runs (dsh ``chunk-rows``). |
| `_journal_base.py` | — |
| `_journal_models.py` | — |
| `_journal_parse.py` | — |
| `activity.py` | Best-effort journal mirrors for long-running orchestration activity. |
| `derive.py` | Project model-visible history from the journal (dsh session-log idea). |
| `journal.py` | — |
| `journal_context.py` | — |
| `progress.py` | — |
| `progress_tracker.py` | — |
| `resume.py` | — |
| `sqlite_index.py` | SQLite-backed query index over the JSONL journal. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `_chunk_rows.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def chunk_packing_enabled()` | Whether the JSONL writer may pack chunk runs. |
| func | `def is_chunk_row(data)` | Whether a decoded JSONL line is a packed chunk row (not an event). |
| func | `def classify_chunk(event)` | Classify a typed event for packing, or ``None`` (store verbatim). |
| func | `def continues_chunk_run(prev, entry)` | Whether ``entry`` extends a run ending in ``prev``. |
| func | `def pack_chunk_row(run)` | Build the storage row for a completed run (``len(run) >= MIN_RUN``). |
| func | `def expand_chunk_row(data)` | Expand a chunk row back to the exact original event dicts. |

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
| class | `class GoalChangeEvent(JournalEvent)` | Durable CAS-guarded goal mutation (dsh ``goal/change``). |
| class | `class UserMessageEvent(JournalEvent)` | Durable human message (dsh ``user/message``). |
| class | `class CurriculumGoalDecisionEvent(JournalEvent)` | Operator decision for a journal-derived learning goal. |
| class | `class McpProposalDecisionEvent(JournalEvent)` | Operator/vet decision for a suggested MCP capability. |
| class | `class ProtocolDriftDecisionEvent(JournalEvent)` | Operator decision for a detected protocol drift event. |
| class | `class SubToolStartEvent(JournalEvent)` | Emitted when a sub-agent begins a tool call. |
| class | `class SubToolEndEvent(JournalEvent)` | Emitted when a sub-agent finishes a tool call. |
| class | `class AssistantChunkEvent(JournalEvent)` | One streamed parent-reply chunk (dsh ``assistant/chunk``). |
| class | `class HookInvokedEvent(JournalEvent)` | One external command hook invocation (dsh ``hook/invoked``). |
| class | `class HookResultEvent(JournalEvent)` | The durable outcome paired with :class:`HookInvokedEvent` (dsh ``hook/result``). |
| class | `class SubTextDeltaEvent(JournalEvent)` | One streamed role-prose chunk (dsh ``assistant/chunk``). |
| class | `class SubSessionSummaryEvent(JournalEvent)` | One completed turn's outcome row for a durable sub-agent session. |
| class | `class BrowserArtifactEvent(JournalEvent)` | A browser screenshot (or similar artifact) was produced. |
| class | `class WorkflowStartEvent(JournalEvent)` | A model-authored orchestration script started (dsh workflow ``on_start``). ``run_id`` correlates every later row of the same run; the event  |
| class | `class WorkflowProgressEvent(JournalEvent)` | One workflow narration row (dsh workflow observer): a phase, a log line, or an agent start/end. ``kind`` is one of ``phase`` / ``log`` / ``a |
| class | `class WorkflowEndEvent(JournalEvent)` | A workflow run settled (dsh workflow ``on_end`` / settlement). |
| class | `class JobChangeEvent(JournalEvent)` | One background-job lifecycle transition (dsh ``tool-jobs``): start, stop request, or terminal settlement. ``status`` mirrors the registry's  |

### `activity.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def capture_attribution()` | Snapshot the ambient journal attribution for later writes (jobs that settle after the turn, worker-thread observers). |
| func | `def write_workflow_start(run_id, name, description, task_id, agent_id, conversation_id)` | Journal a workflow run start (dsh workflow ``on_start``). |
| func | `def write_workflow_progress(run_id, kind, text, agent_seq, agent_label, task_id, agent_id, conversation_id)` | Journal one workflow narration row (phase / log / agent lifecycle). |
| func | `def write_workflow_end(run_id, stop_reason, agents_started, error, task_id, agent_id, conversation_id)` | Journal a workflow run settlement (dsh workflow ``on_end``). |
| func | `def write_job_change(job_id, kind, label, status, detail, task_id, agent_id, conversation_id)` | Journal one background-job lifecycle transition (dsh ``tool-jobs``). |

### `derive.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def derive_model_messages(journal, task_id, user_intent, max_steps)` | Rebuild model-visible messages from the journal's ``StepEvent`` rows. |
| class | `class AssistantChunkStream` | One iteration's streamed parent-reply text, rebuilt from the journal. |
| func | `def derive_assistant_stream(journal, iteration, kind)` | Reconstruct the parent's streamed reply from ``assistant/chunk`` rows. |
| func | `def assert_logged_assistant_reconstructs(journal, expected, iteration)` | Assert the journal reconstructs the given streamed reply — round-trip. |
| class | `class SubagentRoundStream` | One role's streamed prose for one round, rebuilt from the journal. |
| func | `def derive_subagent_streams(journal, session_id, role_id)` | Reconstruct each role's streamed prose from ``SubTextDeltaEvent`` rows. |
| class | `class SessionSummary` | One completed sub-agent session turn's outcome, rebuilt from the journal. |
| func | `def derive_session_summaries(journal, session_id)` | Reconstruct each sub-agent session turn's completion from the journal. |
| class | `class SessionUsageRecord` | One model call's token/cost spend for a sub-agent session. |
| func | `def derive_session_usage(journal, session_id)` | Reconstruct per-call token/cost spend from ``token_usage`` rows. |
| func | `def assert_logged_stream_reconstructs(journal, expected, session_id, role_id)` | Assert the journal reconstructs the given streamed prose — round-trip. |
| func | `def assert_logged_history_reconstructs(journal, expected_steps, task_id)` | Assert the journal reconstructs the given steps — the round-trip. |
| func | `def surface_events_from_journal(journal, session_id, prompts)` | Build a dsh surface for one sub-agent session from real journal events. |

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

**55** file(s) reference this package:

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
- **`runtime/execution/`** · 10 file(s)
  - `runtime/execution/jobs/subagent_producer.py`
  - `runtime/execution/subagents/sessions.py`
  - `runtime/execution/suckers/_ephemeral_events.py`
  - `runtime/execution/suckers/browser_act_skills.py`
  - `runtime/execution/suckers/registry.py`
  - _… and 5 more_
- **`runtime/memory/`** · 5 file(s)
  - `runtime/memory/goals/projection.py`
  - `runtime/memory/goals/service.py`
  - `runtime/memory/hemolymph/composer.py`
  - `runtime/memory/learning/promotion_applier.py`
  - `runtime/memory/runtime_state/hub.py`
- **`runtime/platform/`** · 3 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/ui/app.py`
  - `runtime/platform/ui/state.py`
- **`runtime/safety/`** · 9 file(s)
  - `runtime/safety/hooks/external_bridge.py`
  - `runtime/safety/recovery/intel_collector.py`
  - `runtime/safety/recovery/kg_updater.py`
  - `runtime/safety/recovery/memory_consolidator.py`
  - `runtime/safety/recovery/recipe_evaluator.py`
  - _… and 4 more_
- **`runtime/sensing/`** · 19 file(s)
  - `runtime/sensing/gateway/_observability_journal.py`
  - `runtime/sensing/gateway/_observability_progress_stream.py`
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - `runtime/sensing/gateway/_realtime_react_stream_drive.py`
  - `runtime/sensing/gateway/_realtime_react_stream_reflection.py`
  - _… and 14 more_
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

