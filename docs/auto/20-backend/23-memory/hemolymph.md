---
type: "MemorySubsystem"
title: "Memory · Hemolymph (Context)"
description: "Context Composer · 给 planner 组装上下文（最近 trajectory + learned rules + memories）。"
tags: ["backend", "memory"]
tier: "core"
---
# Memory · Hemolymph (Context)

> Context Composer · 给 planner 组装上下文（最近 trajectory + learned rules + memories）。

**Source**: `runtime/memory/hemolymph/`

## Exports

- `ContextComposer`
- `ContextEngine`
- `TruncationContextEngine`
- `estimate_tokens`

## Modules

| Module | Summary |
| --- | --- |
| `code_index.py` | Auto-retrieve relevant *source* chunks for planner grounding. |
| `composer.py` | — |
| `embedding_backend.py` | Unified, configurable text embedder for octopus's code index. |
| `repo_context.py` | Auto-retrieve relevant codebase context from the project wiki. |
| `semantic_code_index.py` | Read-only semantic search over the work-mode KB's persisted code index. |
| `semantic_rank.py` | Generic semantic ranking — order candidate texts by relevance to a query. |

## Who imports this

**9** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/core/`** · 2 file(s)
  - `runtime/core/cerebrum/llm_planner.py`
  - `runtime/core/cerebrum/react_loop.py`
- **`runtime/execution/`** · 1 file(s)
  - `runtime/execution/suckers/code_intelligence_skills.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/config/builder.py`
- **`runtime/sensing/`** · 3 file(s)
  - `runtime/sensing/gateway/local_brain.py`
  - `runtime/sensing/gateway/observability_router.py`
  - `runtime/sensing/gateway/retrieve_router.py`
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

