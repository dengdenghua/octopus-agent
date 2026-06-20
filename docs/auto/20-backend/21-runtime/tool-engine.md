# Tool Engine · 执行器

> 把每步 tool call 串起整套治理 · Auth / Budget / Journal / Hooks · 同时做 OTel span。

**Source**: `runtime/execution/tool_engine/`

## Exports

- `NormalizedToolCall`
- `NormalizedToolLifecycleEvent`
- `NormalizedToolResult`
- `StepExecutionError`
- `ToolCallOrigin`
- `ToolLifecycleKind`
- `ToolExecutor`
- `normalize_tool_lifecycle_event`
- `normalize_step_tool_result`
- `normalize_tool_result`
- `normalize_task_node_tool_call`
- `normalize_tool_call`
- `output_signals_error`
- `render_tool_output`
- `tool_lifecycle_event_to_react_event`
- `tool_lifecycle_event_to_trace_payload`

## Modules

| Module | Summary |
| --- | --- |
| `executor.py` | — |
| `skill_gate.py` | Shared pre-execution safety gate for direct skill dispatch. |
| `tool_protocol.py` | — |

## Who imports this

**14** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 4 file(s)
  - `runtime/core/cerebrum/react_execution.py`
  - `runtime/core/cerebrum/react_loop.py`
  - `runtime/core/cerebrum/react_parallel_dispatch.py`
  - `runtime/core/graph_runtime/runtime.py`
- **`runtime/execution/`** · 2 file(s)
  - `runtime/execution/suckers/capability_skills.py`
  - `runtime/execution/suckers/forged_persistence.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/config/builder.py`
- **`runtime/safety/`** · 1 file(s)
  - `runtime/safety/recovery/skill_forge.py`
- **`runtime/sensing/`** · 4 file(s)
  - `runtime/sensing/gateway/observability_router.py`
  - `runtime/sensing/gateway/realtime_react_stream.py`
  - `runtime/sensing/gateway/realtime_turn_outcome.py`
  - `runtime/sensing/gateway/tool_bridge.py`

