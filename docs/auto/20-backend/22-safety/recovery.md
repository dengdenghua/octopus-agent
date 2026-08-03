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
- `ForgeConfig`
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
| `_gepa_failures.py` | Failure-sample collectors extracted from ``gepa_bridge.py``. |
| `_gepa_helpers.py` | Private helpers extracted from ``gepa_bridge.py``. |
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

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `_gepa_failures.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def collect_failures_from_journal(journal, recipe_id, limit)` | Pull failed trajectories · optionally filter by recipe. |
| func | `def collect_failures_from_ledger(ledger_path, recipe_id, limit)` | Pull realtime failed-turn records from ProposalLedger. |

### `evolution_constraints.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EvolutionConstraintResult` |  |
| class | `class EvolutionConstraintConfig` |  |
| class | `class EvolutionConstraintValidator` | Validate evolved planner/system-prompt candidates. |
| func | `def serialize_constraint_results(results)` |  |

### `evolution_dataset.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EvolutionExample` | One normalized example for evolution/eval. |
| class | `class EvolutionDataset` | Split dataset used by prompt evolution and downstream evals. |
| class | `class FailureCluster` | Repeated failure pattern used to prioritize reflection. |
| class | `class EvolutionDatasetBuilder` | Build datasets from the failure samples Octopus already collects. |

### `evolution_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EvolutionVerdict` | The router's decision for one candidate. |
| class | `class EvolutionRouter` | Classify evolution candidates into reflex vs skill paths. |

### `external_importers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ImportedSessionSample` |  |
| class | `class SessionImportReport` |  |
| func | `def discover_external_session_roots(paths)` |  |
| func | `def import_external_sessions(paths, limit, max_file_bytes)` |  |
| func | `def collect_external_session_failures(paths, limit)` |  |
| func | `def build_external_session_dataset(paths, limit)` |  |

### `forge_auto_tick.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TickResult` | One tick's outcome · per-recipe actions + timing. |
| class | `class SchedulerState` | Singleton state for the scheduler · exposed to the admin endpoint so the panel can show when the next tick is. |
| func | `def bind_stack(stack)` | Called once at backend startup · gives the scheduler access to the journal + planner router. Safe to call repeatedly · last binding wins. |
| func | `def run_tick(min_uses, min_lead, apply, journal)` |  |
| func | `def enable(interval_hours, min_uses, min_lead)` | Start the scheduler thread · idempotent (repeat calls adjust config without spawning a new thread). |
| func | `def disable()` | Signal the scheduler to stop · non-blocking (returns immediately · thread exits on next stop-event check, at most 5 seconds later). |
| func | `def get_status()` |  |

### `genome_registry.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class GenomeRegistryConfig` |  |
| class | `class GenomeRegistry` |  |

### `gepa_addendum_store.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def addendum_path(recipe_id)` |  |
| func | `def legacy_global_path()` | Single-file global addendum path · returns the current name (``data/forge_planner_addendum.md``). Also auto-migrates the old ``data/gepa_pla |
| func | `def load_for_recipe(recipe_id)` | Return the per-recipe addendum content as a string · ``""`` when no file exists OR ``recipe_id`` is None / empty. |
| func | `def load_global()` | Return the legacy global addendum · ``""`` when not present. Kept separate from ``load_for_recipe`` so the planner can deliberately concaten |
| func | `def save_for_recipe(recipe_id, content)` | Atomic write · tmp file + rename. Caller already added the "## GEPA-optimized addendum" header + metadata · we just persist the bytes. |
| func | `def delete_for_recipe(recipe_id)` | Remove a per-recipe addendum · returns True if a file was deleted, False if there was nothing there to begin with. |
| func | `def list_all()` | Return one entry per stored addendum (per-recipe + legacy global). Each entry has enough metadata for the panel to render a row without furt |

### `gepa_bridge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def write_applied_winner_sidecar(recipe_id, candidate_id, proposal_id, canary_key, avg_score, variant_id, metadata_root)` |  |
| func | `def resolve_applied_winner_sidecar(recipe_hash, metadata_root)` |  |
| func | `def mark_winner_proposal_applied(recipe_id, candidate_id, variant_id, proposal_id, canary_key, ledger_path, metadata_root, fitness_after)` |  |
| func | `def record_winner_canary_outcome(recipe_hash, success, metadata_root, canary_config)` |  |
| func | `def record_winner_proposal_and_canary(result, recipe_id, trigger, ledger_path, canary_config, run_ts, require_improvement, min_score_delta, baseline_prompt, failures, positive_dataset, replay_report, sandbox_replay_report, turn_replay_report, llm_replay_report, min_replay_score, min_sandbox_replay_score, min_turn_replay_score, min_llm_replay_score)` | Materialize the optimizer winner as an auditable proposal. |
| func | `def optimize_for_recipe(seed_prompt, journal, router, recipe_id, judge_model, mutator_model, n_iter, eval_tasks, ledger_path, trigger, record_winner)` | End-to-end · pulls failures, builds eval_fn, runs gepa. |
| func | `def persist_winner(result, section_path)` | Write the best candidate's prompt to ``section_path`` · LLMPlanner picks it up via ``load_section`` on next instance. |
| func | `def propose_for_losing_recipes(journal, router, seed_prompt, judge_model, mutator_model, n_iter, eval_tasks, max_recipes, ledger_path)` |  |

### `gepa_optimizer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PromptCandidate` | One member of the optimization population. |
| func | `def dominates(a, b)` | ``a`` Pareto-dominates ``b`` iff a is no-worse on every task AND strictly better on at least one. Standard Pareto definition. |
| func | `def pareto_front(pop)` | Return non-dominated members. O(N²) is fine since populations are small (typically <30 candidates). |
| class | `class MutationContext` | Inputs to the LLM mutator · keeps the call site terse. |
| func | `def llm_mutate(parent, ctx, router, model, iter_idx)` | One mutation call · returns a new candidate or None on LLM failure. Defensive against malformed JSON · the GEPA loop treats None as "skip th |
| class | `class GepaConfig` |  |
| class | `class GepaResult` |  |
| func | `def gepa_optimize(seed_prompt, eval_fn, failure_sampler, router, model, config)` | Run the loop. Caller-supplied ``eval_fn`` makes this generic enough to optimize any prompt as long as you can score it. |

### `gepa_runs.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class GepaRunRecord` | One persisted GEPA run · summarised so the store stays small. |
| class | `class GepaRunStore` | Bounded ring buffer of recent runs · accessible from anywhere via ``get_default_store``. Records are immutable except for ``mark_applied`` w |
| func | `def get_default_store()` | Return the process-wide store · lazy-init from env. |
| func | `def record_from_result(result, trigger, recipe_id)` | Convert a ``GepaResult`` (loose-typed via Any to avoid an import cycle) into a compact record. Trims history to 30 entries so a long run doe |
| func | `def enrich_run_records(runs, ledger_path, canary_config)` | Attach current proposal/canary lifecycle state to run rows. |

### `gepa_variants.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def variant_path(recipe_id, variant_id)` | ``data/gepa_addendums/<recipe>__<variant>.md`` |
| func | `def manifest_path(recipe_id)` |  |
| class | `class VariantEntry` | One row in a recipe's variant manifest. |
| class | `class VariantManifest` | Per-recipe manifest · what variants exist, their weights, plus ``default_weight`` (the "no addendum" control group). |
| func | `def load_manifest(recipe_id)` |  |
| func | `def save_manifest(m)` | Atomic write · tmp + rename. Caller bumps ``updated_at`` before calling so a reader can detect 'manifest changed since last poll' if it cach |
| func | `def add_variant(recipe_id, variant_id, content, weight, candidate_id, rationale, avg_score)` | Save a variant file + register in manifest. If the variant_id already exists, REPLACES the content + updates metadata (existing weight is pr |
| func | `def remove_variant(recipe_id, variant_id)` | Drop a variant · removes the file AND the manifest entry. Returns True when something was actually removed. |
| func | `def set_weights(recipe_id, weights, default_weight)` | Bulk-update weights · operator's "shift more traffic to vB" knob. ``weights`` is ``{variant_id: new_weight}`` for each one you want to chang |
| func | `def list_variants(recipe_id)` | Return manifest + per-variant content preview for the UI. |
| func | `def select_variant(recipe_id, conversation_id)` | Pick a variant for this turn · returns (variant_id, content). |
| func | `def list_all_manifests()` | Scan the addendum dir for every ``*_manifest.json`` · return one summary per recipe with a live manifest. Powers the "all recipes with A/B r |

### `intel_collector.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class IntelSource(BaseModel)` |  |
| class | `class IntelRunReport(BaseModel)` |  |
| class | `class CollectorConfig` |  |
| class | `class IntelCollector` |  |

### `kg_updater.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class KGUpdateReport(BaseModel)` |  |
| class | `class KGUpdater` |  |
| func | `def persist_kg_from_journal(journal, kg_db_path, multi_valued_predicates)` | Distil triples from a journal and PERSIST them to a durable KG. |

### `lightweight_shadow.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ShadowConfig` |  |
| class | `class ShadowResult` |  |
| func | `def lightweight_shadow_validate(candidate, registry, config)` |  |

### `memory_consolidator.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ConsolidatedMemory(BaseModel)` |  |
| class | `class ConsolidationReport(BaseModel)` |  |
| class | `class ConsolidatorConfig` |  |
| class | `class MemoryConsolidator` |  |
| func | `def filter_memories_for_agent(memories, agent_id, groups)` |  |
| func | `def format_memories_for_prompt(memories, header, max_total_chars, only_hot)` |  |

### `native_evolution_eval.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class NativeEvolutionWeights` |  |
| class | `class NativeEvolutionScore` |  |
| func | `def score_candidate_native(candidate, baseline_prompt, failures, positive_dataset, weights, validator)` |  |
| func | `def evaluate_front_native(candidates, baseline_prompt, failures, positive_dataset)` |  |

### `native_llm_replay.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class LLMReplayCaseResult` |  |
| class | `class LLMReplayCandidateReport` |  |
| class | `class LLMReplayReport` |  |
| func | `def replay_llm_candidates(candidates, router, model, failures, cases, workspace_root, max_cases, max_tool_rounds, min_case_score)` |  |

### `native_replay.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ReplayCase` |  |
| class | `class ReplayCaseResult` |  |
| class | `class ReplayCandidateReport` |  |
| class | `class ReplayReport` |  |
| func | `def build_replay_cases(failures, positive_dataset, failure_limit, positive_limit)` |  |
| func | `def replay_candidate(candidate, cases, baseline_prompt, failures, positive_dataset)` |  |
| func | `def replay_candidates(candidates, baseline_prompt, failures, positive_dataset, failure_limit, positive_limit)` |  |

### `native_replay_sandbox.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SandboxReplayCaseResult` |  |
| class | `class SandboxReplayCandidateReport` |  |
| class | `class SandboxReplayReport` |  |
| func | `def run_sandbox_replay(candidates, failures, positive_dataset, cases, baseline_prompt, workspace_root, keep_workspaces, min_pass_score)` |  |

### `native_turn_replay.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TurnReplayCase` |  |
| class | `class TurnReplayCaseResult` |  |
| class | `class TurnReplayCandidateReport` |  |
| class | `class TurnReplayReport` |  |
| func | `def build_turn_replay_cases(failures, limit)` |  |
| func | `def replay_turn_candidates(candidates, failures, cases, min_case_score)` |  |

### `optimizer_backends.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OptimizerRunConfig` |  |
| class | `class OptimizerRunContext` |  |
| class | `class OptimizerBackend(Protocol)` |  |
| class | `class NativeGepaBackend` |  |
| class | `class DspyGepaBackend` |  |
| class | `class ExternalGepaBackend` |  |
| func | `def available_optimizer_backends()` |  |
| func | `def get_optimizer_backend(name)` |  |
| func | `def optimize_with_backend(seed_prompt, journal, router, config)` |  |

### `recipe_evaluator.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RecipeScore(BaseModel)` |  |
| class | `class RecipeEvaluationReport(BaseModel)` |  |
| class | `class RecipeEvaluatorConfig` |  |
| class | `class RecipeEvaluator` |  |
| func | `def format_recipe_report(report, max_rows)` |  |

### `reflex_forge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ForgedReflexCandidate(BaseModel)` | One proposed reflex rule derived from a prompt-reply cluster. |
| class | `class ReflexForgeResult(BaseModel)` | Outcome of one ``ReflexForge.run()`` tick. |
| class | `class ReflexForgeConfig` |  |
| class | `class ReflexForge` | Forge reflex rules from FuzzyCacheTier (prompt, reply) pairs. |

### `rule_extractor.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class LearnedRule(BaseModel)` |  |
| class | `class RuleExtractionReport(BaseModel)` |  |
| class | `class ExtractorConfig` |  |
| class | `class RuleExtractor` |  |
| func | `def format_rules_for_prompt(rules, header, max_total_chars)` |  |

### `scheduler.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SchedulerConfig` |  |
| class | `class RegenerationScheduler` |  |
| func | `def get_scheduler()` |  |

### `skill_forge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def pattern_signature(traj)` |  |
| func | `def path_of(traj)` |  |
| class | `class ForgedSkillCandidate(BaseModel)` |  |
| class | `class SkillForgeResult(BaseModel)` |  |
| class | `class UnsafeSkillPromotionError(ValueError)` | Raised when a forged public skill would wrap dangerous tools. |
| class | `class ForgeConfig` |  |
| class | `class SkillForge` |  |

### `variant_evaluator.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class VariantStat` | Per-variant aggregate · one entry per (base_recipe, variant). |
| class | `class VariantComparison` | All variants sharing one base recipe · the comparison the operator (or auto-promote) reasons over. |
| func | `def collect_variant_stats(journal, base_recipe_id)` | Scan trajectory events · group by (base, variant) · return one comparison per base recipe. |
| class | `class PromoteProposal` | Suggested weight reshuffle · returned to the operator who decides whether to call ``set_weights`` to commit. |
| func | `def propose_weights(comparison, min_uses, min_lead)` | Look at the per-variant stats and decide whether the data supports promoting a winner. Returns None when the comparison isn't actionable (in |

### `workflow_applier.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ApplyOutcome` |  |
| class | `class ApplyResult` |  |
| func | `def apply_proposals_to_rules(rules, proposals, min_confidence, min_severity, priority_policy, priority_step)` |  |

### `workflow_rewriter.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RewriteProposal(BaseModel)` |  |
| class | `class RewriteReport(BaseModel)` |  |
| class | `class RewriterConfig` |  |
| class | `class WorkflowRewriter` |  |
| func | `def format_proposals_for_review(proposals, header, max_total_chars)` |  |


## Who imports this

**28** file(s) reference this package:

- **`runtime/_cli_commands.py/`** · 1 file(s)
  - `runtime/_cli_commands.py`
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
- **`runtime/platform/`** · 6 file(s)
  - `runtime/platform/ui/_app_stack.py`
  - `runtime/platform/ui/_reflex_admin_gepa_apply.py`
  - `runtime/platform/ui/_reflex_admin_gepa_autotick.py`
  - `runtime/platform/ui/_reflex_admin_gepa_run.py`
  - `runtime/platform/ui/_reflex_admin_gepa_runs.py`
  - `runtime/platform/ui/_reflex_admin_gepa_variants.py`
- **`runtime/safety/`** · 4 file(s)
  - `runtime/safety/evolution/auto_trigger.py`
  - `runtime/safety/evolution/drift_monitor.py`
  - `runtime/safety/evolution/replay_latency_budget.py`
  - `runtime/safety/experiments/prompt_optimizer.py`
- **`runtime/sensing/`** · 10 file(s)
  - `runtime/sensing/gateway/_agents_endpoints_system.py`
  - `runtime/sensing/gateway/_observability_helpers.py`
  - `runtime/sensing/gateway/_observability_journal.py`
  - `runtime/sensing/gateway/_observability_kg.py`
  - `runtime/sensing/gateway/_observability_rollback_panels.py`
  - _… and 5 more_

