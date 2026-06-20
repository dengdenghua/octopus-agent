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
| `skill_gate.py` | Shared pre-execution safety gate for direct skill dispatch. |

## Who imports this

**8** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 1 file(s)
  - `runtime/core/graph_runtime/runtime.py`
- **`runtime/execution/`** · 2 file(s)
  - `runtime/execution/suckers/capability_skills.py`
  - `runtime/execution/suckers/forged_persistence.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/config/builder.py`
- **`runtime/safety/`** · 1 file(s)
  - `runtime/safety/recovery/skill_forge.py`
- **`runtime/sensing/`** · 1 file(s)
  - `runtime/sensing/gateway/observability_router.py`

