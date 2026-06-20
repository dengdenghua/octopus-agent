# Biomimetic Map — Organ → Code Mapping

> One-page reference: which biological organ name maps to which code path, and what's actually there.
> Status labels: **Implemented** / **Partial** / **Not implemented**

---

## Quick Reference

| Organ | Code Path | What It Actually Is | Status |
|---|---|---|---|
| Cerebrum | `runtime/core/cerebrum/` | ReAct loop + Planner + security detectors (30+ files) | **Implemented** |
| Spinal Cord | `runtime/core/nerves/reflex/` | Rule engine + auto-reply + git track + test runner | **Implemented** |
| Ganglia | — | No independent module exists | **Not implemented** |
| Arms | `runtime/execution/arms/` | Worker pool + skill routing + shell state (no autonomy logic) | **Partial** |
| Tentacle | `runtime/tentacle/` | Mobile/cross-device connector + MCP server | **Implemented** |
| Suckers | `runtime/execution/suckers/` | Skill loader + 60+ skill implementations | **Implemented** |
| Beak | `runtime/execution/tool_engine/executor.py` | Tool execution engine | **Implemented** |
| Mantle | `runtime/safety/sandboxing/` | Sandbox (local + Docker backends) | **Implemented** |
| Siphon | `runtime/protocol/` + `runtime/platform/ui/` | JSON-RPC WebSocket + SSE streaming | **Implemented** |
| Eyes | `runtime/sensing/model_router/` | LLM provider routing + device management | **Implemented** |
| Skin | — | No independent module exists | **Not implemented** |
| Nerves | `runtime/core/nerves/` | In-process typed event bus + hooks (no cross-process bus) | **Implemented** |
| Chromatophores | `runtime/safety/chromatophores/` | Signal bus + Boids arbitration | **Implemented** |
| Ink Sac | `runtime/safety/budget_breaker/` | Three-state circuit breaker | **Implemented** |
| Immunity | `runtime/safety/auth/` | Trust engine + attack memory + adaptive immunity (single file) | **Partial** |
| Hearts | `runtime/core/hearts/` | Coordinator + etcd/redis backends (distributed lock only) | **Partial** |
| Genome | `runtime/safety/recovery/genome_registry.py` | Version registry (single file, no evolution loop) | **Partial** |
| Hemolymph | `runtime/memory/hemolymph/composer.py` | Context composer (single file) | **Implemented** |
| Camouflage | `runtime/safety/experiments/` | A/B scheduler + prompt evolver + auto-retire | **Implemented** |
| Regeneration | `runtime/safety/recovery/` + `runtime/memory/learning/` | Skill forge + rule extractor + turn scoring + deep evolution | **Implemented** |

---

## Detailed Mapping

### Cerebrum → `runtime/core/cerebrum/`

| File | Purpose |
|---|---|
| `react_loop.py` | Main ReAct loop: plan → guard → execute → observe → repeat |
| `planner.py` | Task decomposition and routing |
| `llm_planner.py` | LLM-based planning with model selection |
| `react_security_detectors.py` | Per-step security scanning |
| `react_guards.py` | Loop detection and budget guards |
| `react_checkpointing.py` | Checkpoint save/restore within ReAct loop |
| `react_context.py` | Context window management |
| `token_juicer.py` | Context compression and budget allocation |
| `pause_control.py` | Pause/resume control for long tasks |
| `output_styles.py` | Output formatting modes |
| `ai_mode.py` | AI-assisted mode switching |
| `capability_router.py` | Route tasks to appropriate capabilities |
| `input_mentions.py` | @-mention parsing for agents |
| `plugin_auto_load.py` | Auto-load plugins on startup |
| `stable_prompt.py` | Prompt versioning and cache management |
| `thinking_mode.py` | Extended thinking mode support |
| `turn_complexity.py` | Adaptive complexity estimation |
| `verification_policy.py` | Post-action verification rules |

### Arms → `runtime/execution/arms/`

| File | Purpose |
|---|---|
| `base.py` | ArmPool — worker pool management |
| `presets.py` | Predefined arm configurations |
| `lazy_loader.py` | LazyArmPool — on-demand arm loading |
| `extension_registry.py` | Register external arm extensions |
| `tool_registry.py` | Map tools to arms |
| `shell_state.py` | Shell state tracking per arm |
| `promise_gate.py` | Concurrency control for arm tasks |
| `output_buffer.py` | Buffered output for streaming |

### Suckers → `runtime/execution/suckers/`

| File | Purpose |
|---|---|
| `builtins.py` | Built-in skill registration |
| `registry.py` | Skill registry and lookup |
| `loader/md_loader.py` | Load skills from SKILL.md files |
| `hub/installer.py` | Skill hub installer |
| `browser_skills.py` | Playwright-based browsing skills |
| `browser_act_skills.py` | Electron webview skills |
| `code_edit_skills.py` | File editing skills |
| `web_skills.py` | Web search and fetch skills |
| `memory_skills.py` | Memory store/recall skills |
| `delegation_skills.py` | Sub-agent delegation skills |
| `cron_skills.py` | Scheduled task skills |
| `plan_mode.py` | Planning mode skill |
| `fs_search_skills.py` | Filesystem search skills |
| `lsp_skills.py` | LSP-based code intelligence skills |
| `kg_skill.py` | Knowledge graph query skill |
| `testing.py` | Test execution skill |
| `verify_skills.py` | Output verification skills |
| `write_skills.py` | File writing skills |
| `forged_persistence.py` | Persist forged (auto-generated) skills |
| `layers.py` | Skill layer management |
| `search.py` | Skill search and discovery |
| `rate_limit.py` | Per-skill rate limiting |
| `capability_skills.py` | Dynamic capability registration |
| `blackboard_skills.py` | Blackboard read/write skills |
| `computer_skills.py` | Computer use (screen) skills |
| `computer_api_skills.py` | Computer API skills |
| `computer_uia_skills.py` | UI automation skills |
| `crawler_skills.py` | Web crawling skills |
| `desktop_grounding.py` | Desktop UI grounding |
| `ephemeral_agents.py` | Short-lived agent skills |
| `market_skills.py` | Skill marketplace skills |
| `notebook_skills.py` | Jupyter notebook skills |
| `agent_doc_skills.py` | Agent documentation skills |
| `agent_meta_skills.py` | Meta-skill management |
| `skill_library_skills.py` | Skill library management |

### Hearts → `runtime/core/hearts/`

| File | Purpose |
|---|---|
| `hearts.py` | Hearts context manager + snapshot |
| `coordinator.py` | Process coordination (main entry) |
| `coordinator_health.py` | Health check endpoints |
| `etcd_coordinator.py` | etcd-based distributed coordination |
| `redis_coordinator.py` | Redis-based distributed coordination |

**Note**: No "3-heart HA scheduling loop" exists. Actual consumers are distributed locks and health checks.

### Nerves → `runtime/core/nerves/`

| File | Purpose |
|---|---|
| `bus.py` | TypedEventBus — in-process typed event bus |
| `hooks.py` | Pre/post action hooks |
| `reflex/` | Reflex rule engine (fast path) |

**Note**: Cross-process NATS/Redis bus was removed (zero consumers).

### Immunity → `runtime/safety/auth/`

| File | Purpose |
|---|---|
| `trust_engine.py` | Three-layer trust check (tolerance → innate+memory → adaptive) |
| `attack_memory.py` | Attack pattern crystallization and lookup |
| `adaptive_immunity.py` | z-score behavioral anomaly scoring |
| `identity.py` | Identity management |
| `path_guard.py` | Sensitive path protection |
| `path_denylist.py` | Denied path patterns |
| `file_safety.py` | Credential file name blacklist |
| `url_guard.py` | URL safety checking |
| `tool_guardrails.py` | Tool-level guardrails |

### Regeneration → `runtime/safety/recovery/` + `runtime/memory/learning/`

**recovery/**:

| File | Purpose |
|---|---|
| `skill_forge.py` | Crystallize successful patterns into new skills |
| `rule_extractor.py` | Extract avoidance rules from failures |
| `genome_registry.py` | Genome version registry |
| `scheduler.py` | RegenerationScheduler — nightly batch trigger |
| `native_evolution_eval.py` | Native evaluation of evolution candidates |
| `native_replay.py` | Replay trajectories for evaluation |
| `recipe_evaluator.py` | Evaluate recipe quality |
| `variant_evaluator.py` | Evaluate Genome variants |
| `lightweight_shadow.py` | Shadow validation for new skills |
| `forge_auto_tick.py` | Auto-tick forge pipeline |
| `gepa_bridge.py` | GEPA optimizer bridge |
| `optimizer_backends.py` | Multiple optimizer backends |
| `workflow_rewriter.py` | Workflow optimization |
| `memory_consolidator.py` | Memory consolidation |
| `kg_updater.py` | Knowledge graph updates from evolution |

**learning/**:

| File | Purpose |
|---|---|
| `turn_scoring.py` | Score each turn's trajectory |
| `deep_evolution.py` | Deep evolution pipeline |
| `experience_ledger.py` | Experience tracking and ledger |
| `review_queue.py` | Review queue for evolution candidates |
| `promotion_applier.py` | Promote shadow → canary → public |
| `soul_holdout.py` | Holdout set for evaluation integrity |

---

## Naming Convention

In code, organ names appear in three places:

1. **Directory names**: `cerebrum/`, `hearts/`, `nerves/`, `arms/`, `suckers/`, `hemolymph/`, `chromatophores/`, `tentacle/`
2. **Class names**: `CerebrumRuntime`, `Hearts`, `ArmPool`, `NervesEvent`, `Tentacle`, `AdaptiveImmunity`, `CamouflageScheduler`, `GenomeRegistry`
3. **Config keys**: `immunity.*`, `regeneration.*`

Organs that exist **only as documentation concepts** (no code presence):
- Ganglia, Skin, Beak (as a named module), Siphon (as a named module), Eyes (as a named module)

These concepts are implemented under engineering-named modules:
- Ganglia → not implemented
- Skin → not implemented
- Beak → `tool_engine/executor.py`
- Siphon → `protocol/` + `platform/ui/`
- Eyes → `sensing/model_router/`
