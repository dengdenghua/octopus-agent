# Modules (Engineering Reference)

> This document organizes the runtime by its **6 actual engineering modules**, not by biological organ names.
> For the organ metaphor, see [vision/biomimetic-map.md](../vision/biomimetic-map.md).

---

## Module 1: Core — Planning & Coordination

**Path**: `runtime/core/`

The brain and nervous system of the runtime. Handles task planning, event routing, and process coordination.

### Sub-modules

| Sub-module | Path | Purpose |
|---|---|---|
| Cerebrum | `core/cerebrum/` | ReAct loop, planner, security detectors, context management |
| Hearts | `core/hearts/` | Process coordination, distributed locks, health checks |
| Nerves | `core/nerves/` | In-process event bus, hooks, reflex rule engine |
| Graph Runtime | `core/graph_runtime/` | DAG workflow execution |

### Key Entry Points

- `cerebrum/react_loop.py` → `stream_react_loop()` — main execution loop
- `cerebrum/planner.py` → task decomposition
- `nerves/bus.py` → `TypedEventBus` — publish/subscribe within process
- `nerves/reflex/reflex_router.py` → rule-based fast path
- `hearts/coordinator.py` → process-level coordination

---

## Module 2: Execution — Tools & Skills

**Path**: `runtime/execution/`

The hands of the runtime. Loads skills, routes tasks to workers, and executes tools.

### Sub-modules

| Sub-module | Path | Purpose |
|---|---|---|
| Arms | `execution/arms/` | Worker pool, skill routing, shell state |
| Suckers | `execution/suckers/` | Skill loader, 60+ built-in skills |
| Tool Engine | `execution/tool_engine/` | Tool execution with safety gates |
| Swarm | `execution/swarm/` | Multi-agent swarm runtime |
| Parallel Agents | `execution/parallel_agents/` | Parallel agent orchestrator |
| Agents | `execution/agents/` | Agent loader, presets, groups |
| Sub-agents | `execution/subagents/` | Sub-agent bridge and registry |
| Slash Commands | `execution/slash_commands/` | Slash command loader |
| Misc | `execution/misc/` | Agent avatars, packs, parallel runner, skill policy |

### Skill Categories (in `execution/suckers/`)

| Category | Examples |
|---|---|
| Browser | `browser_skills.py`, `browser_act_skills.py`, `crawler_skills.py` |
| Code | `code_edit_skills.py`, `lsp_skills.py`, `write_skills.py` |
| Memory | `memory_skills.py`, `blackboard_skills.py` |
| Delegation | `delegation_skills.py`, `ephemeral_agents.py`, `sub_agent.py` |
| Search | `web_skills.py`, `fs_search_skills.py`, `search.py` |
| Computer Use | `computer_skills.py`, `computer_api_skills.py`, `computer_uia_skills.py` |
| Document | `agent_doc_skills.py`, `agent_meta_skills.py` |
| Testing | `testing.py`, `verify_skills.py` |
| Scheduling | `cron_skills.py` |
| Planning | `plan_mode.py` |
| Management | `skill_library_skills.py`, `market_skills.py`, `capability_skills.py` |

### All Skills (in `execution/all_skills/`)

60+ pre-packaged skills, each with a `SKILL.md` frontmatter:
browse, chart-gen, code-mentor, deep-research, edge-tts, kubectl, r2-upload, tdd-coach, ui-blueprint, and more.

---

## Module 3: Memory — Storage & Learning

**Path**: `runtime/memory/`

The memory and learning system. Stores events, manages context, and drives the evolution loop.

### Sub-modules

| Sub-module | Path | Purpose |
|---|---|---|
| Journal | `memory/journal/` | Event log, checkpoint resume, progress tracking |
| Hemolymph | `memory/hemolymph/` | Context composition for each turn |
| Learning | `memory/learning/` | Turn scoring, deep evolution, skill promotion |
| Knowledge Graph | `memory/knowledge_graph/` | KG storage (SQLite + Kuzu), triple extraction |
| Runtime State | `memory/runtime_state/` | Blackboard, hot cache, context compressor, file transactions |
| Skills Lib | `memory/skills_lib/` | Skill library, curation, ambient suggestions |
| Threads | `memory/threads/` | Thread store, compaction, LLM summarizer |
| Cowork | `memory/cowork/` | Cross-agent cowork store |
| Users | `memory/users/` | User profiles, preferences, mention history |
| Diagnostics | `memory/diagnostics/` | Error classification, trace store, wiki compiler |

### Learning Pipeline

```
Turn execution
    → turn_scoring.py (score each turn)
    → experience_ledger.py (track outcomes)
    → review_queue.py (queue for review)
    → deep_evolution.py (batch analysis)
    → promotion_applier.py (shadow → canary → public)
```

---

## Module 4: Safety — Governance & Evolution

**Path**: `runtime/safety/`

The largest module. Handles security, budget control, evolution, and experiments.

### Sub-modules

| Sub-module | Path | Purpose |
|---|---|---|
| Validation | `safety/validation/` | Constitution gate (Rule + LLM-Judge + Human-Gate), prompt injection defense |
| Auth | `safety/auth/` | Trust engine, attack memory, adaptive immunity, path guard |
| Budget Breaker | `safety/budget_breaker/` | Three-state circuit breaker |
| Evolution | `safety/evolution/` | Fitness evaluation, drift monitor, skill usage, guard judge |
| Experiments | `safety/experiments/` | A/B scheduler, prompt evolver/mutator/optimizer, auto-retire |
| Recovery | `safety/recovery/` | Skill forge, rule extractor, genome registry, native replay, GEPA bridge |
| Chromatophores | `safety/chromatophores/` | Signal bus, Boids arbitration |
| Sandboxing | `safety/sandboxing/` | Local + Docker sandbox backends |
| Hooks | `safety/hooks/` | Pre/post tool-use hooks |
| Invariants | `safety/invariants/` | Invariant enforcement |
| Organization | `safety/organization/` | Team topologies, forge, performance log |
| Gene Locks | `safety/gene_locks/` | Genome change approval gates |
| Audit | `safety/audit/` | Audit chain, trust gateway, webhook verify |
| Approval | `safety/approval/` | Approval gate, policy store, cancellation, device lock |

### Safety Check Flow

```
Tool call request
    → immunity.check() (tolerance → innate+memory → adaptive)
    → path_guard.check() (sensitive path protection)
    → approval_gate.check() (risk rating → auto-approve or queue)
    → sandbox.execute() (run in isolated environment)
    → immunity.learn() (update baselines, crystallize attacks)
    → journal.write() (audit trail)
```

### Outbound Check Flow (Constitution)

```
Agent output → channel adapter
    → gate.check_outbound()
        → Pass 1: Rule (regex PII/secret scan)
        → Pass 2: Rewrite (auto-redact matchable PII)
        → Pass 3: LLM-Judge (semantic violations, optional)
        → Pass 4: Human-Gate (high-risk approval queue)
    → channel.send()
```

---

## Module 5: Sensing — Input & Model Routing

**Path**: `runtime/sensing/`

Handles all input processing and LLM model routing.

### Sub-modules

| Sub-module | Path | Purpose |
|---|---|---|
| Gateway | `sensing/gateway/` | API routes, realtime Cerebrum runtime, agent market sources |
| Model Router | `sensing/model_router/` | LLM provider routing, device management, ollama support |
| Normalize | `sensing/normalize/` | Sensor normalization, file watcher |

### Supported LLM Providers

10+ providers via `platform/models/`: Anthropic, OpenAI, Google, Azure, local (ollama), and more.

---

## Module 6: Platform — Infrastructure

**Path**: `runtime/platform/`

Cross-cutting infrastructure used by all other modules.

### Sub-modules

| Sub-module | Path | Purpose |
|---|---|---|
| Config | `platform/config/` | Config builder, schema, presets |
| Process | `platform/process/` | Session, event bus, streaming, distributed lock, turn model |
| UI | `platform/ui/` | Web UI routes, chat page, health, permissions |
| Plugins | `platform/plugins/` | Plugin loader, hub, skill market |
| Budget | `platform/budget/` | Iteration budget, rate limit tracking |
| Models | `platform/models/` | LLM pipeline, context, governance, primitives |
| LLM Infra | `platform/llm_infra/` | LLM caller, cache, budget tracker |
| Credentials | `platform/credentials/` | Credential pool and sources |
| I18n | `platform/i18n/` | Internationalization (en, zh-CN, ja, ko) |
| Observability | `platform/observability/` | Doctor, health, metrics, logging, redactor |
| Lifecycle | `platform/lifecycle/` | Backup, migration, factory reset, setup wizard |
| Prompts | `platform/prompts/` | Prompt registry, seed, budget |
| Runtime Policy | `platform/runtime_policy/` | Feature flags, capabilities, retry, workspaces |
| IO | `platform/io/` | Atomic file operations |

---

## Cross-cutting: Adapters & Tentacle

### Adapters (`runtime/adapters/`)

| Sub-module | Purpose |
|---|---|
| Channels | 20+ channel adapters (Discord, Slack, WeChat, Telegram, Email, etc.) |
| MCP Client | Model Context Protocol client bridge |
| Scheduler | Cron-based task scheduler |
| Integrations | Third-party integrations (Molili, local auth) |
| Instrumentation | OpenTelemetry tracing |
| Web Auth | Web authentication |

### Tentacle (`runtime/tentacle/`)

Mobile and cross-device connector:
- `coordinator.py` — manage tentacle connections
- `pool.py` — tentacle pool
- `mobile/` — mobile MCP server + Cerebrum adapter
- `transport/` — WebSocket server for remote access
- `dashboard.py` — tentacle monitoring dashboard

---

## Module Dependency Graph

```
Platform (infrastructure)
    ↑ used by all
Core (planning + events)
    ↑ depends on Platform
Execution (tools + skills)
    ↑ depends on Core, Platform
Memory (storage + learning)
    ↑ depends on Core, Platform
Safety (governance + evolution)
    ↑ depends on Core, Memory, Platform
Sensing (input + model routing)
    ↑ depends on Core, Platform
Adapters (channels + integrations)
    ↑ depends on Core, Safety, Platform
Tentacle (mobile + devices)
    ↑ depends on Core, Execution, Platform
```
