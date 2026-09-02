# Architecture (Engineering Reference)

> This document describes **what is actually implemented** in the codebase.
> For the biomimetic vision and future designs, see [vision/biomimetic-architecture.md](../vision/biomimetic-architecture.md).
> For the organ-to-code mapping table, see [vision/biomimetic-map.md](../vision/biomimetic-map.md).

---

## Runtime Module Structure

```
runtime/
├── core/               Planning engine + Event bus + Process coordination
│   ├── cerebrum/       ReAct loop + Planner + Security detectors
│   ├── hearts/         Process coordination (distributed lock, health check)
│   └── nerves/         In-process typed event bus + Reflex rule engine
├── execution/          Execution layer
│   ├── arms/           Worker pool + Skill routing
│   ├── suckers/        Skill loader (60+ built-in skills)
│   ├── tool_engine/    Tool execution engine
│   ├── swarm/          Multi-agent swarm runtime
│   └── parallel_agents/ Parallel agent orchestrator
├── memory/             Memory and learning
│   ├── journal/        Event log + Checkpoint resume
│   ├── hemolymph/      Context composer
│   ├── learning/       Reflection loop + Skill promotion
│   ├── knowledge_graph/ KG (SQLite + Kuzu)
│   ├── runtime_state/  Blackboard + Hot cache + Context compressor
│   ├── threads/        Thread store + Compaction + LLM summarizer
│   └── skills_lib/     Skill library + Curation
├── safety/             Safety and governance
│   ├── validation/     Constitution outbound check (Rule + LLM-Judge)
│   ├── auth/           Trust engine + Attack memory + Adaptive immunity
│   ├── budget_breaker/ Budget circuit breaker
│   ├── evolution/      Fitness evaluation + Drift monitor
│   ├── experiments/    A/B experiments + Prompt variants
│   ├── recovery/       Skill forge + Genome registry + Rule extractor
│   ├── chromatophores/ Signal bus + Boids arbitration
│   ├── sandboxing/     Sandbox (local + Docker)
│   ├── hooks/          Pre/post tool-use hooks
│   ├── invariants/     Invariant enforcement
│   ├── organization/   Team topologies + Forge
│   └── gene_locks/     Genome change approval gates
├── sensing/            Input and model routing
│   ├── gateway/        API gateways + Realtime Cerebrum runtime
│   ├── model_router/   LLM provider routing + Device management
│   └── normalize/      Sensor normalization + File watcher
├── adapters/           Channel adapters (20+ channels)
│   ├── channels/       Discord/Slack/WeChat/Telegram/Email/...
│   ├── mcp_client/     MCP protocol client
│   ├── scheduler/      Cron scheduler
│   └── integrations/   Account integrations (Oct, local auth)
├── platform/           Infrastructure
│   ├── config/         Config builder + Schema + Presets
│   ├── process/        Session + EventBus + Streaming + Distributed lock
│   ├── ui/             Web UI routes + Chat page + Health
│   ├── plugins/        Plugin loader + Skill market
│   ├── budget/         Iteration budget + Rate limit
│   ├── models/         LLM pipeline + Context + Governance
│   ├── llm_infra/      LLM caller + Cache + Budget tracker
│   ├── credentials/    Credential pool + Sources
│   └── i18n/           Internationalization (en/zh/ja/ko)
├── protocol/           Wire protocol
│   ├── envelope.py     JSON-RPC 2.0 envelope
│   ├── items.py        Item model (discriminated union)
│   └── events.py       Event types
├── research/           Deep research pipeline
└── tentacle/           Mobile / cross-device connector
    ├── coordinator.py  Tentacle coordinator
    ├── pool.py         Tentacle pool
    ├── mobile/         Mobile MCP server + Cerebrum adapter
    └── transport/      WebSocket server
```

---

## Core Data Flow

```
User Input
    │
    ▼
Sensing (model_router + gateway)
    │
    ▼
Cerebrum (react_loop)
    │  Planner decomposes task → tool calls
    │  Security detectors scan each step
    │  Token juicer manages context budget
    │
    ▼
Tool Engine (executor)
    │  Before execute: immunity.check() + path_guard
    │  Execute in sandbox (local/docker)
    │  After execute: immunity.learn() + journal.write()
    │
    ▼
Siphon (protocol/envelope)
    │  Stream results via JSON-RPC WebSocket
    │  SSE fallback for simple clients
    │
    ▼
Client (frontend / channel adapter)
```

---

## Key Subsystems

### 1. ReAct Loop (`core/cerebrum/react_loop.py`)

The central execution loop. Each turn:

1. **Plan**: LLM decides next action (tool call or response)
2. **Guard**: Security detectors check the planned action
3. **Execute**: Tool engine runs the action in sandbox
4. **Observe**: Result feeds back into context
5. **Repeat** until task complete or budget exhausted

Supports:
- Single-step and parallel dispatch modes
- Auto-diagnostics after write operations
- Checkpoint/resume across sessions
- Pause/resume control

### 2. Event Bus (`core/nerves/bus.py`)

In-process typed event bus (`TypedEventBus`). Events:

- `SkillRegistered` / `SkillRetired`
- `AgentAdded` / `AgentRemoved`
- `BudgetPressure`
- `ConversationOpened`

No cross-process bus (NATS/Redis Streams removed — zero consumers at time of cleanup).

### 3. Reflex Engine (`core/nerves/reflex/`)

Rule-based fast path that bypasses the LLM:

- Auto-reply rules (greetings, status queries)
- Git track (auto-commit on file changes)
- Test runner (auto-run tests after code edits)
- Broadcast (notify channels on events)
- Tiered execution (skip/notify/auto-execute)

### 4. Trust Engine (`safety/auth/trust_engine.py`)

Three-layer security check before every tool execution:

1. **Tolerance**: Self-whitelist bypass (internal calls)
2. **Innate + Memory**: Trust source whitelist + attack pattern DB
3. **Adaptive**: z-score behavioral anomaly scoring (optional, needs predicted cost input to be effective)

Post-execution learning: updates behavioral baselines, crystallizes attack patterns.

### 5. Constitution Gate (`safety/validation/gate.py`)

Outbound check on all channel outputs:

- **Pass 1 — Rule**: Regex/keyword scan for PII, secrets, API keys
- **Pass 2 — Rewrite**: Auto-redact matchable PII (`[REDACTED:email]`)
- **Pass 3 — LLM-Judge**: Second LLM call for semantic violations (optional, off by default)
- **Pass 4 — Human-Gate**: Approval queue for high-risk actions

### 6. Budget Breaker (`safety/budget_breaker/breaker.py`)

Three-state circuit breaker:

- **Green**: Normal operation
- **Yellow**: Warning — approaching limits
- **Red**: Circuit open — all execution paused, requires human confirmation

Triggers: per-task token/cost limits, consecutive failures, zero-information-gain loops.

### 7. Evolution Loop (`memory/learning/` + `safety/recovery/`)

Nightly batch pipeline:

1. **Turn Scoring**: Score each turn's trajectory
2. **Deep Evolution**: Identify high-value patterns
3. **Skill Forge**: Crystallize successful patterns into new skills
4. **Rule Extractor**: Extract avoidance rules from failures
5. **Promotion Applier**: Promote shadow → canary → public skills

All evolution runs offline via Batch API. New skills must pass shadow validation before canary.

### 8. A/B Experiments (`safety/experiments/`)

- **Camouflage Scheduler**: Run prompt variants in parallel
- **Auto Retire**: Automatically retire underperforming variants
- **Prompt Evolver/Mutator/Optimizer**: Generate and test prompt variations

### 9. Realtime Protocol (`protocol/`)

JSON-RPC 2.0 over WebSocket (`/api/realtime`):

- **Notification**: One-way events
- **Request/Response**: Paired calls (used for approval flow)
- **Item Model**: Each observable output is a typed Item with lifecycle (started → delta → completed)

Persistence: append-only JSONL per thread. Resume rebuilds state from disk.

---

## Configuration

Main config: `config.yaml` (see `config.example.yaml`).

Key sections:

```yaml
# Model routing
models:
  default: anthropic/claude-sonnet-4-20250514
  planner: anthropic/claude-sonnet-4-20250514

# Safety
safety:
  enable_llm_judge: false    # Optional: second LLM pass on outbound
  constitution_profile: normal  # strict / normal / lax

# Immunity
immunity:
  enable_adaptive: false     # z-score anomaly detection
  attack_memory_path: ./data/immunity/attacks.db

# Evolution
regeneration:
  trajectory:
    sample_rate: 1.0
  evaluator:
    mode: batch
    schedule: "0 2 * * *"
```

---

## Deployment

- **Docker**: `docker-compose.yml` (single node) / `docker-compose.full.yml` (with Redis)
- **K8s**: `deploy/k8s/` (deployment, service, ingress, PVC)
- **CLI**: `octopus serve` (dev), `octopus run` (headless)

---

## Related Documents

| Document | Purpose |
|---|---|
| [implementation-status.md](../implementation-status.md) | Per-mechanism implementation status with code evidence |
| [vision/biomimetic-architecture.md](../vision/biomimetic-architecture.md) | Biomimetic vision and future architecture |
| [vision/biomimetic-map.md](../vision/biomimetic-map.md) | Organ name → code path mapping |
| [constitution.md](../constitution.md) | Agent behavior constraints |
| [protocols/](../../protocols/) | Protocol specifications |
