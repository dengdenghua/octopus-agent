# Organ Directory Map

This file maps the biomimetic architecture vocabulary to the current
implementation package locations.

The runtime was reorganized into seven semantic groups. New code should import
from the grouped paths below, for example `runtime.execution.tool_engine` instead of the
old flat `runtime.beak`. Backward-compatible re-exports still exist in
`runtime/__init__.py` for older callers.

Every package below has been verified to exist in the current tree. Some
early biomimetic names were retired in favour of functional ones — the
concept is shown in parentheses where the directory no longer carries the
old name.

| Organ / concept | Current implementation package |
|---|---|
| `cerebrum/` | `runtime/core/cerebrum/` |
| `ganglia/` (TaskGraph runtime) | `runtime/core/graph_runtime/` |
| `spinal_cord/` (reflex layer) | `runtime/core/nerves/reflex/` |
| `nerves/` | `runtime/core/nerves/` |
| `hearts/` | `runtime/core/hearts/` |
| `agents/` | `runtime/execution/agents/` |
| `arms/` | `runtime/execution/arms/` |
| `beak/` (tool execution) | `runtime/execution/tool_engine/` |
| `suckers/` | `runtime/execution/suckers/` |
| `parallel_agents/` | `runtime/execution/parallel_agents/` |
| `swarm/` | `runtime/execution/swarm/` |
| `tentacle/` | `runtime/tentacle/` |
| `siphon/` (realtime gateway) | `runtime/sensing/gateway/` |
| `model_router/` | `runtime/sensing/model_router/` |
| `normalize/` | `runtime/sensing/normalize/` |
| `server/` | `runtime/sensing/server/` |
| `hemolymph/` | `runtime/memory/hemolymph/` |
| `knowledge_graph/` | `runtime/memory/knowledge_graph/` |
| `threads/` | `runtime/memory/threads/` |
| `journal/` | `runtime/memory/journal/` |
| `immunity/` (trust engine) | `runtime/safety/auth/` |
| `invariants/` | `runtime/safety/invariants/` |
| `regeneration/` (recovery) | `runtime/safety/recovery/` |
| `chromatophores/` | `runtime/safety/chromatophores/` |
| `channels/` | `runtime/adapters/channels/` |
| `integrations/` | `runtime/adapters/integrations/` |
| `mcp_client/` | `runtime/adapters/mcp_client/` |
| `scheduler/` | `runtime/adapters/scheduler/` |
| `instrumentation/` | `runtime/adapters/instrumentation/` |
| `config/` | `runtime/platform/config/` |
| `models/` | `runtime/platform/models/` |
| `ui/` | `runtime/platform/ui/` |
| `i18n/` | `runtime/platform/i18n/` |

Retired biomimetic names with no current dedicated package: `eyes`, `skin`,
`mantle`, `genome`, `ink`, `camouflage`.

## Runtime Path

The default workspace turn enters through the realtime gateway, uses a fast
reflex layer first, then a ReAct loop for tool-using work. `deep` mode opts into
the older deliberative path:

```text
request
  -> sensing/gateway/realtime_gateway
  -> core/nerves/reflex
  -> ReAct loop (default workspace slow path)
  -> execution/tool_engine/ToolExecutor
  -> journal + item protocol events

deep mode:
request
  -> core/cerebrum planner
  -> core/graph_runtime TaskGraph runtime
  -> synthesized answer
```

## Practical Navigation Guide

- Realtime transport: `runtime/sensing/gateway/realtime_gateway.py`
- Realtime runtime bridge: `runtime/sensing/gateway/realtime_cerebrum.py`
- Thread event log and replay: `runtime/memory/threads/`
- Compatibility chat/thread/team APIs: `runtime/sensing/gateway/` (channels_router, team_tasks_router, …)
- Tool execution and governance: `runtime/execution/tool_engine/executor.py`
- Skill catalog: `runtime/execution/all_skills/__init__.py`
- Write-scope permissions: `runtime/platform/process/scope.py`
- Frontend route source of truth: `frontend/src/router.tsx`
- Frontend realtime state: `frontend/src/core/realtime/`
- Frontend conversation and team pages: `frontend/src/app/workspace/`
- Tests: `tests/`

## Migrated Canonical Notes

Some root-level organ notes have already been consolidated under
`docs/architecture/organs/`.

- `beak`
- `camouflage`
- `cerebrum`
- `chromatophores`
- `ganglia`
- `hearts`
- `hemolymph`
- `ink`
- `skin`
- `spinal_cord`
