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

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `code_index.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def reciprocal_rank_fusion(rankings, k)` | Fuse several ranked key-lists into one order by Reciprocal Rank Fusion. |
| func | `def retrieve_code_context(query, root, budget_tokens, max_chunks, ttl, _sink, strict_explicit_paths)` | Return the source chunks most relevant to ``query`` as a prompt section, or ``None`` when there is no source or no chunk overlaps the query. |

### `composer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def get_recent_compose_snapshots(limit)` | Return up to ``limit`` most-recent compose snapshots, newest last. |
| func | `def estimate_tokens(text)` |  |
| func | `def score_skill_relevance(query, name, affinity, description)` | Lexical relevance of a skill to the task. Zero infra: English word overlap + name/affinity substring hits + CJK bigram overlap. Higher = mor |
| class | `class ContextEngine(ABC)` | Abstract base for pluggable context-compression strategies. |
| class | `class TruncationContextEngine(ContextEngine)` | Default engine — drops whole segments from the lowest-priority buckets first until the total fits within the budget. |
| class | `class ContextComposer` |  |

### `embedding_backend.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def embed_model()` |  |
| func | `def embed_endpoint()` |  |
| func | `def backend_info()` | Describe the active embedding backend — for the setup UI / CLI to show the user, in plain terms, what their stack is wired to. |
| func | `def available()` | True when SOME embedding backend is reachable — a remote endpoint is set, or fastembed / sentence-transformers is importable. Cheap; doesn't |
| func | `def embed_texts(texts)` | Embed ``texts`` via the configured backend (remote endpoint preferred, else in-process). ``None`` when no backend is available; ``[]`` for n |
| func | `def get_encoder()` | Return an ``.encode``-compatible encoder for the configured backend, or ``None`` when nothing is available. |

### `repo_context.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def is_private_agent_context_path(path)` | Whether a repo/wiki path is agent-private prompt material. |
| func | `def retrieve_repo_context(query, wiki_dir, budget_tokens, max_pages, _sink)` | Retrieve the wiki pages most relevant to ``query`` (BM25) as a prompt section. Returns ``None`` when there is no wiki or no page overlaps. |
| func | `def build_codebase_context(goal, strict_explicit_scope)` | Combined codebase grounding for a goal: relevant wiki pages (summaries) + the actual source chunks. Returns ``(prompt_section, sources)`` wh |
| func | `def render_codebase_context(goal)` | ``build_codebase_context``'s prompt section only — the existing string contract for callers that don't need the structured source list. |
| func | `def collect_codebase_sources(goal)` | The docs/chunks that ``render_codebase_context(goal)`` would inject, as structured ``{"kind", "title", "path"}`` dicts — for a UI grounding  |

### `semantic_code_index.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def search_persisted(query, top_k, db_path)` | Top-k semantically-nearest chunks from the persisted KB index, or ``None`` when the semantic layer isn't available (no DB / no embedding bac |

### `semantic_rank.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def rank(query, candidates, top_k)` | Rank ``candidates`` by relevance to ``query``. |


## Who imports this

**10** file(s) reference this package:

- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/core/`** · 2 file(s)
  - `runtime/core/cerebrum/_react_prompt_assembly_sections.py`
  - `runtime/core/cerebrum/llm_planner.py`
- **`runtime/execution/`** · 1 file(s)
  - `runtime/execution/suckers/code_intelligence_skills.py`
- **`runtime/platform/`** · 1 file(s)
  - `runtime/platform/config/builder.py`
- **`runtime/sensing/`** · 4 file(s)
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - `runtime/sensing/gateway/local_brain.py`
  - `runtime/sensing/gateway/retrieve_router.py`
  - `runtime/sensing/gateway/wiki_router.py`
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

