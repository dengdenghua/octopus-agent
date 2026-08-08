# Octopus Protocols

This directory contains design documents for system-level protocols and behavioral contracts.

## Status

Most protocol documents are planned but not yet written. When referenced elsewhere in the documentation, they represent intended future work or architectural concepts under consideration.

## Planned Protocols

The following protocols are referenced in architecture documents but not yet fully specified:

- **digestion.md** — Context ingestion and knowledge extraction
- **evolution.md** — Guard auto-demotion and adaptive policy
- **genome.md** — Agent capability and skill inheritance  
- **recipe.md** — Multi-step workflow composition
- **budget.md** — Token and cost tracking across sessions
- **immunity.md** — Security boundaries and trust signals
- **reflex.md** — Fast-path reactive behaviors
- **swarm.md** — Multi-agent coordination primitives
- **distribution.md** — Work distribution and load balancing
- **workflow_rewrite.md** — Dynamic workflow optimization
- **conflict_resolution.md** — Merge and synchronization strategies
- **knowledge_graph.md** — Semantic relationship modeling
- **memory_consolidation.md** — Long-term memory formation
- **skill_testing.md** — Automated skill validation
- **realtime_workbench.md** — Live collaboration protocols

## Implementation Priority

Protocols are implemented incrementally based on product needs. Not all planned protocols will be built—some may be merged, deferred, or replaced as the system evolves.

For implemented features, see the actual code in `runtime/` with tests in `tests/`.
