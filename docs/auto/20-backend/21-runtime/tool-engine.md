# Tool Engine · 执行器

> 把每步 tool call 串起整套治理 · Auth / Budget / Journal / Hooks · 同时做 OTel span。

**Source**: `runtime/execution/tool_engine/`

## Exports

- `StepExecutionError`
- `ToolExecutor`

## Modules

| Module | Summary |
| --- | --- |
| `executor.py` | — |

## Who imports this

**5** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 1 file(s)
  - `runtime/core/graph_runtime/runtime.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/config/builder.py`
- **`runtime/sensing/`** · 1 file(s)
  - `runtime/sensing/gateway/observability_router.py`

