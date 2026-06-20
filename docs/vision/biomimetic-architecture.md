# Biomimetic Architecture (Vision)

> This document describes the **full biomimetic vision** for Octopus, including mechanisms that are not yet implemented.
> For what is actually built today, see [guide/architecture.md](../guide/architecture.md).
> For the organ-to-code mapping, see [biomimetic-map.md](biomimetic-map.md).

---

## Design Philosophy

The octopus has ~500 million neurons, with **2/3 distributed in its 8 arms** rather than centralized in the brain. Each arm can independently taste, grasp, and solve local problems without consulting the central brain. A severed arm continues executing commands for hours.

We mirror this physiology: **the central brain only plans and arbitrates; execution intelligence is pushed down to the arms.**

Three invariants:

1. **Decentralized intelligence** — Cerebrum never calls tools directly; Sucker actions are decided by Ganglia
2. **Clear organ boundaries** — Each module maps to one biological organ, single responsibility, replaceable
3. **Self-adaptive evolution** — Regeneration (regrow), Camouflage (mimic), Ink (escape)

> **Biology gives us the PATTERN, not the NUMBER.**
> "3 hearts / 9 brains / 8 arms / 2000 suckers" are mnemonics and marketing, **never engineering constraints**.

---

## Organ → Module Mapping

| Organ | Biological Trait | Module | Engineering Role | Status |
|---|---|---|---|---|
| Cerebrum | 1/3 neurons, slow-path planning | `core/cerebrum/` | Task decomposition, routing, arbitration | **Implemented** |
| Spinal Cord | Reflex without brain (fast path) | `core/nerves/reflex/` | Rules/cache/small model, bypass LLM | **Implemented** |
| Ganglia ×8 | Each arm has its own mini-brain | — | Distributed arm controller | **Not implemented** |
| Arms ×8 | Semi-autonomous, can act independently | `execution/arms/` | Worker agent instances | **Partial** (tool executor, no autonomy) |
| Tentacle | Reach to edge devices | `tentacle/` | Mobile / cross-device connector | **Implemented** |
| Suckers | Execution points with taste/touch | `execution/suckers/` | Skill library (SKILL.md) | **Implemented** |
| Beak | Only hard tool, crushes prey | `execution/tool_engine/` | Tool execution engine | **Implemented** |
| Mantle | Protective sheath around organs | `safety/sandboxing/` | Sandbox / security boundary | **Implemented** |
| Siphon | Jet propulsion, respiration, waste | `protocol/` + `platform/ui/` | I/O pipeline, SSE, compression | **Implemented** |
| Eyes | W-shaped pupil, wide-angle sensing | `sensing/model_router/` | Input parsing, multimodal, model adapter | **Implemented** |
| Skin | Photoreceptors, sense only | — | Pure perception layer | **Not implemented** |
| Nerves | Pathways connecting organs | `core/nerves/` | Message bus, workflow graph | **Implemented** (in-process only) |
| Chromatophores | Signal + muscle dual function | `safety/chromatophores/` | Pub/sub state broadcast + Boids arbitration | **Implemented** |
| Ink Sac | Emergency ink spray (inflammation) | `safety/budget_breaker/` | Circuit breaker, budget ceiling, emergency stop | **Implemented** |
| Immunity | B/T cells, antibody memory | `safety/auth/` | Identity + attack memory + adaptive risk | **Partial** (adaptive layer inert) |
| Hearts ×3 | Systemic + 2 branchial, physically isolated | `core/hearts/` | Dual-loop isolation, HA scheduling | **Partial** (distributed lock only) |
| Genome | DNA + hereditary information | `safety/recovery/genome_registry.py` | Editable DNA + long-term memory | **Partial** (registry only, no evolution) |
| Hemolymph | Copper-based blue blood, circulatory | `memory/hemolymph/` | Per-turn context flow | **Implemented** (composer) |
| Camouflage | Instant morphological disguise | `safety/experiments/` | Strategy switching, A/B experiments | **Implemented** |
| Regeneration | Arm regrows when severed | `safety/recovery/` + `memory/learning/` | Reflection, self-evolution, skill forging | **Implemented** |

---

## Distributed Orchestration Topology (Vision)

```
                            ┌──────────────┐
                            │   Cerebrum   │   Central brain — planning / arbitration
                            └──────┬───────┘
                                   │
                         Nerves message bus
                                   │
         ┌──────────┬──────────┬───┴───┬──────────┬──────────┐
         │          │          │       │          │          │
      Ganglion₁  Ganglion₂  Ganglion₃  …       Ganglion₇  Ganglion₈
         │          │          │                  │          │
        Arm₁       Arm₂       Arm₃     ……        Arm₇       Arm₈
         │          │          │                  │          │
     [Suckers]  [Suckers]  [Suckers]          [Suckers]  [Suckers]

         └──── Chromatophores gossip (inter-arm) ────┘
                                   │
                    Hearts × 3 (HA scheduling / heartbeat rhythm)
                                   │
              Ink Sac (circuit breaker) ·  Mantle (sandbox)
```

### Three Core Pathways

1. **Vertical command chain**: Cerebrum → Ganglion → Arm → Sucker (planning downstream)
2. **Horizontal inter-arm**: Arm ↔ Chromatophores ↔ Arm (arms communicate directly, no central routing)
3. **Perception upstream**: Eyes/Skin → Hemolymph → Cerebrum (environment signals converge to planner)

### Why Beyond Lead+Sub-agents

> ⚠️ Status: **Not implemented**

Lead+Sub is still centralized — the Lead must drive every Sub action.
In this architecture, each Arm has its own Ganglion and can continue executing long tasks when Cerebrum is silent.
Chromatophores let Arm₃ tell Arm₇ "I've got it" without routing through the center.
**This is the upgrade from tree orchestration to mesh orchestration.**

---

## Key Vision Mechanisms

### Ganglia — Distributed Arm Controllers

> ⚠️ Status: **Not implemented**

Each Arm has an independent Ganglion (separate process/thread):
- Translates ArmTask into Sucker call sequences
- Has local Checkpointer (shared Genome) and local budget ceiling (shared Ink)
- **Disconnect autonomy**: when Cerebrum is unavailable, Ganglion continues running accepted tasks

### Hearts — Dual-Loop Isolation

> ⚠️ Status: **Partial** — only distributed lock, no dual-loop scheduling

Octopus has 3 hearts: 1 systemic + 2 branchial.
- **Systemic heart**: main scheduling loop (drives Cerebrum each tick)
- **Branchial hearts ×2**: manage rhythm for 4 arms each, HA mutual backup
- Any heart stop → other two take over — no single point of failure
- Hearts also serve as **cost rhythm regulators**: lower frequency when budget is tight, accelerate reflection pipeline when idle

### Genome — Editable DNA

> ⚠️ Status: **Partial** — registry exists, evolution loop not built

```python
OctopusGenome = {
    "cortex_policy":     CortexPolicy,     # Cerebrum planning strategy
    "scheduler_policy":  SchedulerPolicy,  # Hearts rhythm + routing
    "memory_policy":     MemoryPolicy,     # Hemolymph context ratio + Blackboard TTL
    "arm_registry":      list[ArmSpec],    # Which arms exist
    "tool_affinity_map": dict[str, list],  # Sucker → Arm routing
    "risk_profile":      RiskProfile,      # Immunity + Ink strictness
    "event_topology":    EventTopology,    # Chromatophores topic map + Boids weights
    "learning_rate":     float,            # Regeneration step size
}
```

Evolution mechanisms:
- **Mutation**: Random small change to one Genome field
- **Crossover**: Combine halves from two parent Genomes
- **Selection**: Fitness function scores each Genome variant
- **Expression**: Translate Genome into runtime behavior

Population concept: multiple Genome versions coexist, compete, mate, and are retired based on fitness.

### Skin — Pure Perception Layer

> ⚠️ Status: **Not implemented**

Skin is a **sense-only** layer: it reports signals but never decides, routes, or calls.
- System metrics, environment variables, file changes, external webhooks
- All signals flow into Hemolymph for next planning round
- **Hard constraint**: Skin code must never import decision-making modules

### Inter-Arm Gossip

> ⚠️ Status: **Not implemented** (Chromatophores provides pub/sub primitives, but Arm↔Arm direct collaboration path not built)

Arms subscribe to Chromatophores topics:
- `arm.busy` / `arm.idle` / `sucker.grabbed` / `alert.budget` / `alert.loop`
- Avoid reporting everything to Cerebrum
- Implementation via Redis pub/sub or NATS subject

---

## Six Sustainable Evolution Modules

| Evolution Layer | Organ Mapping | Implementation Module | Key Output |
|---|---|---|---|
| ① Long-task engine | Cerebrum + Ganglia + Genome/Checkpoint | `core/cerebrum/` + `execution/arms/` + `memory/journal/` | Checkpoint resume, multi-session recovery |
| ② Workflow | Nerves pathways | `core/nerves/` | DAG executor, node/edge types |
| ③ Skills | Suckers | `execution/suckers/` | SKILL.md + progressive disclosure |
| ④ Context/Memory | Genome + Hemolymph | `memory/` | Long-term memory + per-turn context flow |
| ⑤ Reflection/Evolution | Regeneration | `memory/learning/` + `safety/recovery/` | Trajectory→Eval→Skill Forge |
| ⑥ Cost governance | Ink Sac + Hearts | `safety/budget_breaker/` + `core/hearts/` | Budget circuit breaker + rhythm throttling |

### Evolution Loop (nightly batch)

```
Arms' daily trajectory
    → Hemolymph feeds into Genome/Journal
    → Regeneration/Evaluator scores via Batch API
    → Regeneration/Skill Forge crystallizes high-frequency success paths into new Suckers
    → New Sucker attaches to corresponding Arm, reusable next day
    → Hearts adjusts Ganglion call rhythm based on cost curve
```

---

## Three Philosophical Shifts

### From "Design" to "Evolution"
```
Before: Hard-code system architecture
Now:    Define evolution space (which dimensions are variable + boundaries + fitness)
```

### From "Tuning" to "Selection"
```
Before: Manually tune scheduler parameters
Now:    Define fitness, let the system select
```

### From "Single Version" to "Population"
```
Multiple Genomes coexist / compete / mate / are retired
Architecture itself becomes a Thompson Sampling bandit
```

---

## Evolution Roadmap

- **Phase 0**: Fork skeleton (2 weeks) — MCP / sandbox / graph executor / model adapter usable
- **Phase 1**: Single Cerebrum + single Arm can run tasks (1 month)
- **Phase 2**: Multi-Arm + Chromatophores + Ink (1.5 months)
- **Phase 3**: Regeneration reflection pipeline online (1 month)
- **Phase 4**: Hearts HA + Camouflage A/B (1 month)

~4–5 months to a demonstrable MVP.

---

## See Also

- [guide/architecture.md](../guide/architecture.md) — Engineering-only architecture reference
- [biomimetic-map.md](biomimetic-map.md) — Organ → code path mapping table
- [implementation-status.md](../implementation-status.md) — Per-mechanism implementation status
- [protocols/](../../protocols/) — Protocol specifications
