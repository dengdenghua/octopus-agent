---
type: "SafetySubsystem"
title: "Safety · Recovery"
description: "MemoryConsolidator · SkillForge · KG updater · 从 trajectory 反哺记忆 / 技能 / 图谱。"
tags: ["backend", "safety"]
tier: "core"
---
# Safety · Recovery

> MemoryConsolidator · SkillForge · KG updater · 从 trajectory 反哺记忆 / 技能 / 图谱。

**Source**: `runtime/safety/recovery/`

## Package summary

Self-evolution subsystem — biomimetic alias: *Regeneration*.

## Exports

- `CollectorConfig`
- `ExtractorConfig`
- `EvolutionPath`
- `EvolutionRouter`
- `EvolutionVerdict`
- `ForgeConfig`
- `ForgedReflexCandidate`
- `ForgedSkillCandidate`
- `GenomeRegistry`
- `GenomeRegistryConfig`
- `IntelCollector`
- `IntelRunReport`
- `IntelSource`
- `ConsolidatedMemory`
- `ConsolidationReport`
- `ConsolidatorConfig`
- `EvolutionConstraintConfig`
- `EvolutionConstraintResult`
- `EvolutionConstraintValidator`
- `EvolutionDataset`
- `EvolutionDatasetBuilder`
- `EvolutionExample`
- `FailureCluster`
- `ImportedSessionSample`
- `KGUpdater`
- `KGUpdateReport`
- `LearnedRule`
- `persist_kg_from_journal`
- `MemoryConsolidator`
- `MemoryScope`
- `LLMReplayCandidateReport`
- `LLMReplayCaseResult`
- `LLMReplayReport`
- `NativeEvolutionScore`
- `NativeEvolutionWeights`
- `OptimizerBackend`
- `OptimizerRunConfig`
- `OptimizerRunContext`
- `ReplayCandidateReport`
- `ReplayCase`
- `ReplayCaseResult`
- `ReplayReport`
- `SandboxReplayCandidateReport`
- `SandboxReplayCaseResult`
- `SandboxReplayReport`
- `SessionImportReport`
- `TurnReplayCandidateReport`
- `TurnReplayCase`
- `TurnReplayCaseResult`
- `TurnReplayReport`
- `filter_memories_for_agent`
- `format_memories_for_prompt`
- `ReflexForge`
- `ReflexForgeConfig`
- `ReflexForgeResult`
- `RuleExtractionReport`
- `RuleExtractor`
- `ShadowConfig`
- `ShadowResult`
- `SkillForge`
- `SkillForgeResult`
- `UnsafeSkillPromotionError`
- `RecipeEvaluationReport`
- `RecipeEvaluator`
- `RecipeEvaluatorConfig`
- `RecipeScore`
- `RewriteProposal`
- `RewriteReport`
- `RewriterConfig`
- `WorkflowRewriter`
- `ApplyOutcome`
- `ApplyResult`
- `apply_proposals_to_rules`
- `available_optimizer_backends`
- `build_external_session_dataset`
- `format_proposals_for_review`
- `format_recipe_report`
- `format_rules_for_prompt`
- `get_optimizer_backend`
- `evaluate_front_native`
- `build_replay_cases`
- `build_turn_replay_cases`
- `collect_external_session_failures`
- `discover_external_session_roots`
- `import_external_sessions`
- `lightweight_shadow_validate`
- `optimize_with_backend`
- `pattern_signature`
- `score_candidate_native`
- `replay_llm_candidates`
- `replay_candidate`
- `replay_candidates`
- `replay_turn_candidates`
- `run_sandbox_replay`
- `serialize_constraint_results`

## Modules

| Module | Summary |
| --- | --- |
| `evolution_constraints.py` | — |
| `evolution_dataset.py` | Unified dataset builder for regeneration and prompt evolution. |
| `evolution_router.py` | EvolutionRouter · route evolution candidates to the right forge. |
| `external_importers.py` | — |
| `forge_auto_tick.py` | RecipeForge auto-promote scheduler · the last-mile autonomy knob. |
| `genome_registry.py` | Genome Registry — versioned JSON snapshot store for system configuration. |
| `gepa_addendum_store.py` | — |
| `gepa_bridge.py` | Bridge between Octopus's existing reflection layer and the GEPA prompt optimizer. |
| `gepa_optimizer.py` | GEPA-style prompt optimizer · 7th reflection path. |
| `gepa_runs.py` | — |
| `gepa_variants.py` | Multi-variant per-recipe addendums · turns GEPA from "one optimized prompt per recipe" into "N candidate prompts per recipe, traffic- split by weight, sticky per conversation". |
| `intel_collector.py` | — |
| `kg_updater.py` | — |
| `lightweight_shadow.py` | — |
| `memory_consolidator.py` | — |
| `native_evolution_eval.py` | — |
| `native_llm_replay.py` | — |
| `native_replay.py` | — |
| `native_replay_sandbox.py` | — |
| `native_turn_replay.py` | — |
| `optimizer_backends.py` | Pluggable prompt-optimizer backends for Octopus evolution. |
| `recipe_evaluator.py` | — |
| `reflex_forge.py` | ReflexForge · auto-generate reflex rules from successful turns. |
| `rule_extractor.py` | — |
| `scheduler.py` | — |
| `skill_forge.py` | — |
| `variant_evaluator.py` | — |
| `workflow_applier.py` | — |
| `workflow_rewriter.py` | — |

## Who imports this

**19** file(s) reference this package:

- **`runtime/cli.py/`** · 1 file(s)
  - `runtime/cli.py`
- **`runtime/cli_reflect.py/`** · 1 file(s)
  - `runtime/cli_reflect.py`
- **`runtime/cli_serve.py/`** · 1 file(s)
  - `runtime/cli_serve.py`
- **`runtime/core/`** · 3 file(s)
  - `runtime/core/cerebrum/llm_planner.py`
  - `runtime/core/cerebrum/planner.py`
  - `runtime/core/graph_runtime/runtime.py`
- **`runtime/memory/`** · 2 file(s)
  - `runtime/memory/diagnostics/wiki_compiler.py`
  - `runtime/memory/learning/promotion_applier.py`
- **`runtime/platform/`** · 2 file(s)
  - `runtime/platform/ui/app.py`
  - `runtime/platform/ui/reflex_admin_router.py`
- **`runtime/safety/`** · 3 file(s)
  - `runtime/safety/evolution/auto_trigger.py`
  - `runtime/safety/evolution/drift_monitor.py`
  - `runtime/safety/experiments/prompt_optimizer.py`
- **`runtime/sensing/`** · 6 file(s)
  - `runtime/sensing/gateway/agents_router.py`
  - `runtime/sensing/gateway/evolution_ops/recipe_forge.py`
  - `runtime/sensing/gateway/evolution_ops/skill_forge.py`
  - `runtime/sensing/gateway/evolution_ops/utils.py`
  - `runtime/sensing/gateway/evolution_ops_router.py`
  - `runtime/sensing/gateway/observability_router.py`

