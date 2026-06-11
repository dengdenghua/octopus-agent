# Organ Directory Map

This file maps the biomimetic architecture vocabulary to the current
implementation package locations.

The runtime was reorganized into seven semantic groups. New code should import
from the grouped paths below, for example `runtime.execution.tool_engine` instead of the
old flat `runtime.beak`. Backward-compatible re-exports still exist in
`runtime/__init__.py` for older callers.

| Organ / concept | Current implementation package |
|---|---|
| `cerebrum/` | `runtime/core/cerebrum/` |
| `ganglia/` | `runtime/core/ganglia/` |
| `spinal_cord/` | `runtime/core/spinal_cord/` |
| `nerves/` | `runtime/core/nerves/` |
| `hearts/` | `runtime/core/hearts/` |
| `agents/` | `runtime/execution/agents/` |
| `arms/` | `runtime/execution/arms/` |
| `beak/` | `runtime/execution/beak/` |
| `suckers/` | `runtime/execution/suckers/` |
| `parallel_agents/` | `runtime/execution/parallel_agents/` |
| `swarm/` | `runtime/execution/swarm/` |
| `tentacle/` | `runtime/tentacle/` |
| `eyes/` | `runtime/sensing/eyes/` |
| `skin/` | `runtime/sensing/skin/` |
| `siphon/` | `runtime/sensing/siphon/` |
| `mantle/` | `runtime/sensing/mantle/` |
| `genome/` | `runtime/memory/genome/` |
| `hemolymph/` | `runtime/memory/hemolymph/` |
| `knowledge_graph/` | `runtime/memory/knowledge_graph/` |
| `threads/` | `runtime/memory/threads/` |
| `immunity/` | `runtime/safety/immunity/` |
| `ink/` | `runtime/safety/ink/` |
| `invariants/` | `runtime/safety/invariants/` |
| `regeneration/` | `runtime/safety/regeneration/` |
| `camouflage/` | `runtime/safety/camouflage/` |
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

## Runtime Path

The default workspace turn enters through the realtime gateway, uses a fast
reflex layer first, then a ReAct loop for tool-using work. `deep` mode opts into
the older deliberative path:

```text
request
  -> siphon/realtime_gateway
  -> spinal_cord/reflex_router
  -> ReAct loop (default workspace slow path)
  -> beak/ToolExecutor
  -> journal + item protocol events

deep mode:
request
  -> cerebrum planner
  -> ganglia TaskGraph runtime
  -> synthesized answer
```

## Practical Navigation Guide

- Realtime transport: `runtime/sensing/siphon/realtime_gateway.py`
- Realtime runtime bridge: `runtime/sensing/siphon/realtime_cerebrum.py`
- Thread event log and replay: `runtime/memory/threads/`
- Compatibility chat/thread/team APIs: `runtime/sensing/siphon/thread_compat_router.py`
- Tool execution and governance: `runtime/execution/beak/executor.py`
- Skill catalog: `runtime/execution/all_skills/__init__.py`
- Write-scope permissions: `runtime/platform/scope.py`
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
