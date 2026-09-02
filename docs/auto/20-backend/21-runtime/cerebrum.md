---
type: "RuntimeSubsystem"
title: "Cerebrum · 规划器"
description: "LLM Planner + Static Planner · 把自然语言意图拆成 TaskGraph。"
tags: ["backend", "runtime"]
tier: "core"
---
# Cerebrum · 规划器

> LLM Planner + Static Planner · 把自然语言意图拆成 TaskGraph。

**Source**: `runtime/core/cerebrum/`

## Exports

- `LLMPlanner`
- `PlannerError`
- `StaticPlanner`

## Modules

| Module | Summary |
| --- | --- |
| `_planner_helpers.py` | Pure helper functions extracted from :mod:`runtime.core.cerebrum.llm_planner`. |
| `_planner_parse.py` | Plan-JSON extraction + node validation for :class:`LLMPlanner`. |
| `_react_context_attachments.py` | User-message content assembly (attachments, images, JSONL manifest), message checkpoint (de)serialization helpers, and related-file prefetching. |
| `_react_context_code.py` | Code-context prelude and mode/workflow/signals prompt builders. |
| `_react_context_helpers.py` | Token estimation, context-compression helpers, and skill-catalog formatting for the ReAct loop. |
| `_react_context_project.py` | Project rules / git status / project-profile prompt builders. |
| `_react_execution_dispatch.py` | Tool dispatch / execution helpers for the ReAct loop. |
| `_react_execution_phase6d.py` | PHASE 6d — action dispatch + observation for the ReAct loop. |
| `_react_execution_phase6g.py` | PHASE 6g + 6d — loop-tail housekeeping and pre-dispatch guard cluster for the ReAct loop. |
| `_react_execution_progress.py` | Working-set / phase / progress-summary helpers and trajectory persistence + planner learning throttles for the ReAct loop. |
| `_react_execution_results.py` | Tool-result / observation shaping for the ReAct loop. |
| `_react_failure_classification.py` | Classification of failed tool executions for readable failure surfacing. |
| `_react_loop_reexports.py` | Lazy compatibility exports for helpers historically owned by react_loop. |
| `_react_parsing_codequality.py` | Code-quality detectors for ReAct write steps. |
| `_react_parsing_core.py` | Core ReAct text parsing + incremental Thought streaming. |
| `_react_parsing_testquality.py` | Test-correctness + production-hygiene detectors for ReAct write steps. |
| `_react_parsing_tools.py` | Tool-call / XML action parsing helpers for the ReAct trajectory. |
| `_react_parsing_verification.py` | Verification-trail detection helpers for ReAct steps. |
| `_react_prompt_assembly_bootstrap.py` | PHASE 1-2 turn bootstrap: entry guards + router / native-gate resolution, plus PHASE 4/4.5 start events + agent auto-delegation short-circuit. |
| `_react_prompt_assembly_guidance.py` | System-prompt guidance + tool / capability / skill-catalog sections for the PHASE 3 assembly. |
| `_react_prompt_assembly_sections.py` | Early PHASE 3 sections: date / public-orientation / work-mode / read-only / grounding / browser-operation / iteration & budget / todo-protocol resolution. |
| `_react_prompt_assembly_state.py` | Shared mutable assembly state for the PHASE 3 prompt-assembly split, plus the final ``messages`` composition and the memory / identity / team-roster sections. |
| `_visibility_trace.py` | 决策点 → 依据 → 结论 的可见性 trace（visibility trace）记录模块。 |
| `agent_auto_delegate.py` | Auto-delegate to pinned agents on the first ReAct step. |
| `agent_auto_parallel.py` | Auto-decompose + run subtasks in parallel for the first ReAct turn. |
| `ai_mode.py` | AI Mode — Marvis-style two-mode wrapper over the 3-tier router. |
| `capability_router.py` | — |
| `checkpoint_integrity.py` | — |
| `checkpoint_mirror.py` | Distributed checkpoint mirror — P3 fourth slice. |
| `completion_decision.py` | — |
| `completion_receipt.py` | — |
| `env_health.py` | Startup execution-health canary. |
| `guard_model_policy.py` | Model-aware guard routing — apply code-smell guards only to cheap models. |
| `input_mentions.py` | Parse @plugin/@skill/@agent and runtime surface mentions from prompts. |
| `leader.py` | Leader Process · single-owner supervisor for long-running tasks. |
| `live_steering.py` | Shared prompt contract for user messages received during an active turn. |
| `llm_planner.py` | — |
| `output_styles.py` | Per-turn output style overlays for the ReAct system prompt. |
| `pause_control.py` | — |
| `planner.py` | — |
| `plugin_auto_load.py` | Auto-activate pinned plugins/skill-packs from user mentions. |
| `prompt_persistence.py` | — |
| `react_action_outcomes.py` | Action outcome bookkeeping for the ReAct loop. |
| `react_auto_inspect.py` | Runtime-side salvage for announce-only project inspection turns. |
| `react_auto_verify.py` | Runtime-side auto-verification salvage for final-answer guard deadlocks. |
| `react_browser_guards.py` | Browser-interaction and mixed-mode completion guards. |
| `react_browser_iteration.py` | Browser-surface gating and per-task iteration limits for the ReAct loop. |
| `react_checkpointing.py` | Periodic auto-checkpoint + distributed mirror for the ReAct loop. |
| `react_code_mode_guards.py` | Code-mode completion, write, inspection and tool-availability guards. |
| `react_code_smell_guards.py` | Code-smell guards (post-step / pre-Final-Answer gates). |
| `react_concurrency_guards.py` | Concurrency / path-boundary semantic guards (single-flight family). |
| `react_context.py` | ReAct context assembly: token budget, compression, prompt building. |
| `react_convergence.py` | Deterministic evidence-to-answer convergence for bounded ReAct turns. |
| `react_execution.py` | Execution / tool-dispatch helpers for the ReAct loop. |
| `react_execution_receipts.py` | Server-owned provenance for ReAct execution receipts. |
| `react_explicit_reads.py` | Explicit-read goal predicates and bounded read recovery. |
| `react_final_answer_content_guards.py` | Final-answer content guards (post-step / pre-Final-Answer gates). |
| `react_final_answer_guards.py` | Final-answer guard plumbing for the ReAct loop. |
| `react_goal_analysis.py` | Goal-intent and evidence-path analysis for ReAct guards. |
| `react_guard_types.py` | Core types for the ReAct final-answer guard registry. |
| `react_guards.py` | ReAct trajectory guards: post-step / pre-Final-Answer quality gates. |
| `react_in_flight_nudges.py` | In-flight nudges for the ReAct main loop (PHASE 6e, first half). |
| `react_loop.py` | — |
| `react_loop_controls.py` | Operator controls + run-budget knobs for the ReAct loop. |
| `react_loop_state.py` | Shared per-turn state for the ReAct main-loop phases (Wave 2). |
| `react_model_deadlines.py` | Model-call deadline machinery for the ReAct loop. |
| `react_model_stream.py` | PHASE 6b — LLM call + Final-Answer anchor streaming for the ReAct loop. |
| `react_native.py` | Native tool-use path for the single-agent ReAct loop. |
| `react_parallel_dispatch.py` | Concurrent multi-action dispatcher for the ReAct loop (口子 2). |
| `react_parsing.py` | ReAct trajectory parsing + post-step quality checks. |
| `react_phase_6c.py` | PHASE 6c of the ReAct main loop: parse step / format-violation check. |
| `react_prompt_assembly.py` | PHASE 3 — system + volatile prompt assembly for the ReAct loop. |
| `react_public_updates.py` | Public progress-update plumbing for the ReAct loop. |
| `react_quiet_evidence.py` | Quiet-evidence accumulation for the ReAct loop's public narrative. |
| `react_repeat_tool_guards.py` | Repeat tool call detection guards. |
| `react_resume.py` | Resume/checkpoint-rebuild helpers for the ReAct loop. |
| `react_security_detectors.py` | Security + quality detectors for ReAct trajectory steps. |
| `react_security_guards.py` | Security + quality guards (post-step / pre-Final-Answer gates). |
| `react_step_evaluator.py` | Deterministic, bounded repair hints for production ReAct turns. |
| `react_terminal.py` | Post-loop terminal handling + finalization for the ReAct loop. |
| `react_test_quality_guards.py` | Test-quality guards: cheats that satisfy coverage letter, not spirit. |
| `react_timeout_guards.py` | Tool timeout detection and policy guards. |
| `react_todo_protocol_guards.py` | Todo-protocol and completion-phrase guards. |
| `react_types.py` | — |
| `react_verification_guards.py` | Verification-completeness guards for ReAct code-mode turns. |
| `reply_styles.py` | Reply-style registry: user-facing response decoration is a selectable dimension, mirroring WorkBuddy's ``style/`` template set (professional / friendly / socratic / ...) and Codex's four-part personality templates (personality / values / tone / escalation). |
| `resume_cli.py` | CLI for inspecting + driving ReAct checkpoint resume (P3 long-task durability). |
| `rewind.py` | Turn-scoped rewind · roll a task back to a prior checkpoint anchor. |
| `rules_persistence.py` | — |
| `run_state.py` | — |
| `stable_prompt.py` | Cache-stable prompt builder. |
| `thinking_mode.py` | Structured thinking-mode helpers. |
| `todo_protocol.py` | Shared rules for the user-visible task checklist protocol. |
| `token_juicer.py` | Token compression for tool observations before they enter the LLM message stream. |
| `tool_output_sink.py` | Compatibility re-export for the lightweight process output sink. |
| `turn_complexity.py` | Three-tier smart model routing. |
| `verification_policy.py` | — |
| `work_mode.py` | Unified work-mode resolution — one model for "what kind of work is this turn". |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `_planner_parse.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def extract_plan_json(text)` | Extract the LLM's JSON plan from free-form text. |
| func | `def validate_plan_nodes(nodes, registry, max_nodes)` | Validate the LLM's raw plan nodes against the skill registry. |

### `_react_context_helpers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def context_budget_tokens_for_model(model)` | Return the coarse context budget used by pressure + compression. |

### `_react_execution_results.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def classify_turn_failure(steps)` | Classify the turn's latest tool failure into a readable taxonomy. |

### `_react_failure_classification.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def classify_tool_failure(tool_name, detail)` | Classify a failed tool execution into ``{kind, code, readable}``. |

### `_react_parsing_core.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def extract_streamable_thought(joined, cursor, in_thought, tail_margin)` | Pull newly decodable Thought prose out of a growing LLM buffer. |

### `_visibility_trace.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class VisibilityEntry` | 单个决策点的可见性记录：决策点 → 结论 → 依据。 |
| class | `class VisibilityTrace` | 线程安全的决策 trace 容器。 |
| func | `def new_trace()` | 创建新的 trace 实例（turn 构建期由调用方持有并显式传入决策函数）。 |
| func | `def active_trace()` | 返回当前上下文中的默认 trace；未设置时返回 None。 |
| func | `def set_active_trace(trace)` | 把默认 trace 槽位设到当前上下文；返回可传给 reset_active_trace 的 token。 |
| func | `def reset_active_trace(token)` | 撤销 set_active_trace 的副作用；token 为 None 时 no-op。绝不抛出。 |
| func | `def record_visibility(decision_point, conclusion, basis, **details)` | 经当前上下文的默认槽位记录；未设置时 no-op。绝不抛出。 |

### `agent_auto_delegate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class AgentDelegationPlan` | Recommended single-agent delegation, or empty when none fits. |
| func | `def plan_auto_delegation(prompt, registry)` | Decide whether this prompt should auto-delegate to one agent. |

### `agent_auto_parallel.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class AutoParallelPlan` | A resolved decomposition plan, or empty when no split fits. |
| func | `def build_thread_memory_summary(user_context, max_turns, max_chars)` | Best-effort cross-turn memory summary from the conversation history. |
| func | `def plan_auto_parallel(goal, context, max_subtasks, model_name)` | Decide whether this goal should be auto-decomposed and run in parallel. |
| func | `def set_auto_parallel_orchestrator(orchestrator)` | Inject the orchestrator used for dispatch (tests / app wiring). |
| func | `def get_auto_parallel_orchestrator()` | Return the shared orchestrator, creating one wired to real sub-agents. |
| func | `def run_auto_parallel(plan, thread_id, turn_id, model_name, context, owner_id, timeout_s, on_batch_started)` | Dispatch the plan's subtasks in parallel and aggregate the results. |

### `ai_mode.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def current_ai_mode()` | Return the persisted AI mode, defaulting to ``efficiency``. |
| func | `def set_ai_mode(mode)` | Persist the chosen AI mode. |
| class | `class DeviceSummary` |  |
| func | `def detect_device_summary()` | Run the full detection battery. Each probe is bounded so the call totals at most a few seconds even on a misconfigured box. |
| func | `def recommend_mode(summary)` | Pick a recommended mode based on device summary. |
| func | `def apply_ai_mode_override(verdict)` | Map a complexity verdict through the active AI mode. |

### `capability_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def isolated_code_ui_regression(user_context)` | Return whether UI verification should use the isolated browser lane. |
| func | `def filter_surface_compatible_skills(names, user_context)` | Remove tools that are incompatible with the active runtime surface. |
| class | `class CapabilityActivation` |  |
| func | `def capability_index()` | A lightweight "capability map" for the prompt, shown when no capability is activated for the turn (e.g. a vague goal). It lists each capabil |
| func | `def activate_capabilities(goal, user_context, registry)` |  |
| func | `def order_skill_names(names, activation, goal, user_context, registry)` |  |

### `checkpoint_integrity.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CheckpointIntegrity` |  |
| func | `def validate_checkpoint_state(state, iteration)` |  |
| func | `def validate_trace_checkpoint(checkpoint)` |  |

### `checkpoint_mirror.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CheckpointMirror` | Best-effort distributed mirror of latest checkpoint per task. |
| func | `def build_checkpoint_mirror_from_url(url)` | Build a CheckpointMirror backed by a real Redis client at ``url``. |

### `completion_decision.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CompletionDecision` | Canonical semantic outcome for one ReAct turn. |
| func | `def decide_completion(terminated_reason, effective_success, blocked_on_user)` | Resolve raw loop signals into one stable, protocol-facing outcome. |

### `completion_receipt.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CompletionReceipt` | Machine-readable proof that a run reached a defensible terminal state. |
| func | `def build_completion_receipt(statuses, contract_issues, contract_warnings, artifact_count, output_present)` |  |

### `env_health.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def set_execution_canary(degraded)` | Record the startup probe result (True = execution degraded). |
| func | `def execution_canary()` | Return the recorded startup probe result, or None if never probed. |
| func | `def execution_canary_degraded()` | Whether the startup probe found execution degraded (False if unknown). |
| func | `def probe_execution_health(cwd, timeout_s)` | Run one harmless command through the configured sandbox backend. |
| func | `def run_startup_canary(cwd)` | Probe and record execution health; return the degraded flag. |

### `guard_model_policy.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def classify_model_tier(model)` | Classify model into 'premium', 'cheap', or 'unknown'. |
| func | `def should_apply_code_smell_guards(model)` | Return whether code-smell guards should run for this model. |
| func | `def guard_categories_for_model(model, base_categories)` | Return the guard categories that should apply to this model. |
| func | `def explain_guard_policy(model)` | Human-readable explanation of guard policy for a model. |

### `input_mentions.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class InputMention` | A single @-mention extracted from user input. |
| class | `class InputMentions` | Container holding the mentions found in a single prompt. |
| func | `def parse_input_mentions(text)` | Extract typed mentions and known runtime surface mentions. |

### `leader.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class LeaderError(RuntimeError)` | Base error for leader-related failures. |
| class | `class LeaderNotRunning(LeaderError)` | No leader process is reachable on the socket. |
| class | `class LeaderAlreadyRunning(LeaderError)` | Another live leader owns the socket. |
| class | `class LeaderState` | In-memory state the leader exposes to clients. |
| class | `class LeaderProcess` | Single-owner supervisor serving JSON-RPC over local IPC. |
| class | `class LeaderClient` | Thin JSON-RPC client over local IPC. |
| func | `def ensure_leader(socket_path, pid_path)` | Connect to the running leader, starting it first if needed. |
| func | `def main(argv)` | CLI entry: ``python -m runtime.core.cerebrum.leader serve``. |

### `live_steering.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def append_live_steering_messages(messages, texts)` | Append one priority protocol marker followed by exact user messages. |
| func | `def insert_live_steering_protocol(messages)` | Place the protocol immediately before the current user follow-up. |

### `llm_planner.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class LLMPlanner` | LLM-driven task planner: takes a parsed intent, emits a TaskGraph. |

### `output_styles.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def render_output_style(style)` | Return the style-overlay block, or ``""`` for None / default / unknown. |

### `pause_control.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def turn_wall_time_cap_s(goal_mode, research_mode, swarm_mode)` | Resolve the wall-clock hard cap for a turn (audit T-05). |
| class | `class ActiveTask` |  |
| class | `class PauseRequest` |  |
| class | `class PauseController` |  |
| func | `def get_pause_controller()` |  |

### `planner.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PlannerError(RuntimeError)` |  |
| class | `class Rule` |  |
| class | `class StaticPlanner` |  |

### `plugin_auto_load.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PluginActivation` | Outcome of trying to load + start a single pinned plugin. |
| class | `class PluginActivationReport` | Aggregate report rendered for the model's next observation. |
| func | `def auto_load_pinned_plugins(plugin_ids, hub)` | Try to load + start each plugin in ``plugin_ids``. |

### `prompt_persistence.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def dump_section(path, section, label)` |  |
| func | `def load_section(path)` |  |

### `react_convergence.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EvidenceConvergence` |  |
| class | `class ExplicitReadScopeConstraint` |  |
| func | `def ordered_explicit_read_groups(goal)` | Recover user-authored read batches while preserving textual order. |
| func | `def constrain_explicit_read_scope(goal, steps, actions, read_only, enforce_order)` | Filter duplicate and out-of-scope reads after explicit coverage begins. |
| func | `def read_only_evidence_convergence(goal, steps, read_only)` | Return terminal evidence coverage for a bounded read-only request. |
| func | `def build_evidence_digest(decision, steps, max_chars_per_target)` | Build a bounded per-target digest for the direct-answer round. |
| func | `def build_direct_answer_directive(goal, decision, steps)` | Keep the original task next to bounded evidence during synthesis. |
| func | `def evidence_answer_conflicts_with_goal(goal, answer)` | Reject a synthesis answer that falsely claims there was no task. |

### `react_final_answer_guards.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def guard_stall_kind(steps)` | Classify *why* a guard keeps rejecting: ``action_deficit`` vs ``evidence``. |

### `react_goal_analysis.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def derive_effective_execution_goal(current_goal, conversation_messages)` | Carry an explicitly requested unfinished execution contract across turns. |

### `react_guard_types.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class GuardContext` | Everything a guard might need to evaluate a candidate final answer. |
| class | `class GuardSpec` | One registry entry: a guard plus its metadata. |

### `react_guards.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def guard_disposition(label, category)` | Return ``hard``, ``repair`` or ``advisory`` for a guard finding. |
| func | `def evaluate_guards(ctx, registry, recorder, disabled_labels, categories)` | Walk the registry in priority order; return the first ``(label, message)`` that fires, or ``None`` if all pass. |

### `react_loop.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def stream_react_loop(stack, intent, agent, model, max_iterations, temperature, enable_tools, resume_task_id, thread_id, max_tokens_budget, max_usd_budget, approval_provider, output_chunk_sink, step_evaluator, planning_mode, reasoning_effort, steering_drain, on_auto_parallel_batch)` | Drive one parent ReAct turn (see ``_stream_react_loop_impl``). |
| func | `def run_react_loop(stack, intent, agent, model, max_iterations, temperature, enable_tools, resume_task_id, thread_id, max_tokens_budget, max_usd_budget, approval_provider)` |  |

### `react_loop_controls.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def pick_react_variant(task_id)` |  |
| func | `def record_react_variant_result(variant_name, success)` |  |
| func | `def get_react_variant_stats()` |  |

### `react_native.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def native_tool_use_flag_enabled()` | Read ``OCTOPUS_NATIVE_TOOLUSE`` fresh each call (operator can flip without a restart). |
| func | `def model_supports_tool_use(router, model)` | Whether ``router`` can serve ``model`` via native tool-use. |
| func | `def native_tool_use_active(router, model)` | Combined gate: flag on AND the resolved model advertises tool-use. |
| func | `def build_loop_tool_specs(executor, agent, goal, user_context, strict_explicit_reads)` | Build the native ``ToolSpec`` catalog from the loop's skill registry. |
| func | `def require_public_update_on_tool_specs(specs, evidence_round)` | Require one model-authored public sentence on every native tool round. |
| func | `def step_from_tool_calls(tool_calls, text, thinking, iteration, evidence_round)` | Synthesise a ``ReActStep`` from native ``tool_calls``. |
| func | `def trim_text_protocol_for_native(system_prompt)` | Phase 1: drop the redundant text-protocol scaffolding for native mode. |

### `react_step_evaluator.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class StepEvaluation` | One advisory repair decision; it never authorizes tool execution. |
| class | `class RuntimeStepEvaluator` | Turn-local evaluator with bounded, digest-only deduplication. |
| func | `def build_runtime_step_evaluator()` | Return fresh turn-local evaluator state for one ReAct invocation. |

### `react_types.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ReActStep` |  |
| class | `class ReActResult` |  |
| class | `class ReActRecipe` |  |

### `reply_styles.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def reply_style_prompt(style)` | Return the ``<reply-style>`` section for ``style`` (four-part personality module), or ``None`` when the style is unset/unknown. |
| func | `def is_reply_style(name)` | True when ``name`` is a registered style. |

### `resume_cli.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def main(argv)` |  |

### `rewind.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RewindPoint` | A single rewind anchor — one ``react_checkpoint`` event. |
| class | `class RewindResult` | Outcome of a rewind operation. |
| func | `def list_rewind_points(journal, task_id)` | Enumerate every checkpoint anchor for ``task_id``, oldest-first. |
| func | `def rewind_to_checkpoint(journal, task_id, target_iteration, project_root, dry_run)` | Roll a task back to the state captured at ``target_iteration``. |
| func | `def latest_rewind_point(journal, task_id)` | Convenience: the most recent checkpoint for a task, or None. |

### `rules_persistence.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def dump_rules_to_yaml(rules)` |  |
| func | `def dump_rules_to_file(rules, path)` |  |
| func | `def load_rules_from_yaml(text)` |  |
| func | `def load_rules_from_file(path)` |  |

### `run_state.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RunStateSummary` |  |
| func | `def converge_run_state(statuses)` |  |

### `stable_prompt.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class StablePromptBuilder` | Compose a system prompt with explicit cache-stability separation. |
| func | `def render_volatile_as_user_message(volatile_text)` | Wrap volatile content for injection as a synthetic user message before the real conversation starts. |

### `thinking_mode.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ThinkingPlanStep` |  |
| class | `class ThinkingPlan` |  |
| func | `def is_thinking_mode(mode)` |  |
| func | `def build_thinking_plan(goal, user_context, mode)` | Build a visible, serializable plan for a structured thinking turn. |
| func | `def update_thinking_plan_status(plan, iteration, final)` | Return a copy of ``plan`` with visible step status advanced. |
| func | `def render_thinking_guidance(plan)` | Render non-template guidance for system prompts. |

### `todo_protocol.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def context_mode(user_context)` | Return the best-effort runtime mode from a thread context. |
| func | `def should_require_todo_protocol(goal, user_context)` | Whether the turn has an explicit contract requiring a checklist. |
| func | `def render_todo_protocol_guidance(required, mode)` | Render a compact system guidance block for checklist behavior. |

### `token_juicer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class JuiceStats` | Before/after char counts for a single compression pass. |
| func | `def juice(text, max_chars, enable_html, enable_url, enable_dedup, enable_array, enable_code, enable_cap)` | Apply the compression pipeline. Returns (compressed_text, stats). |
| func | `def is_enabled()` | Feature flag. Default ON — compression has been validated to reduce token usage without losing sentinel patterns. The protected- pattern gua |

### `turn_complexity.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def is_smart_routing_enabled()` |  |
| func | `def resolve_tier_model(tier)` | Public alias for :func:`_resolve_tier_model`. |
| func | `def get_tier_config()` | Snapshot of the operator-configured tier → model map. |
| func | `def estimate_turn_complexity(text, has_explicit_model, has_topology, is_code_mode, is_swarm_mode, is_research_mode, is_goal_mode, looks_tool_intent, requires_todo_protocol)` | Return a three-tier verdict for the turn. |
| func | `def select_model_for_complexity(verdict, user_model, is_code_mode)` | Map a verdict to the actual model name to call. |

### `verification_policy.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class VerificationRequirement` | A deterministic verification obligation derived from touched files. |
| class | `class ProjectVerificationProfile` | Verification commands discovered from the current project. |
| func | `def normalize_policy_path(path)` |  |
| func | `def classify_path(path)` | Classify a touched path into the verification policy bucket. |
| func | `def project_verification_profile(project_root)` |  |
| func | `def verification_requirements_for_paths(paths, project_root)` | Return de-duplicated required checks for the touched path set. |
| func | `def required_verification_keys_for_paths(paths, project_root)` |  |
| func | `def command_satisfies_requirement(text, requirement)` | Whether a tool action/observation text satisfies one requirement. |
| func | `def summarize_requirements(requirements)` |  |

### `work_mode.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class WorkMode` | The resolved work-type/scope of a single turn (one source of truth). |
| func | `def resolve_work_mode(user_context)` | Fold the scattered per-turn mode signals into one :class:`WorkMode`. |


## Who imports this

**60** file(s) reference this package:

- **`runtime/cli_code.py/`** · 1 file(s)
  - `runtime/cli_code.py`
- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_guard_health.py/`** · 1 file(s)
  - `runtime/cli_guard_health.py`
- **`runtime/cli_reflect.py/`** · 1 file(s)
  - `runtime/cli_reflect.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/cli_serve.py/`** · 1 file(s)
  - `runtime/cli_serve.py`
- **`runtime/core/`** · 1 file(s)
  - `runtime/core/graph_runtime/runtime.py`
- **`runtime/execution/`** · 9 file(s)
  - `runtime/execution/codex_backend/dynamic_tools.py`
  - `runtime/execution/codex_backend/role_context.py`
  - `runtime/execution/loops/_controller_attempt.py`
  - `runtime/execution/misc/parallel_runner.py`
  - `runtime/execution/parallel_agents/_orchestrator_models.py`
  - _… and 4 more_
- **`runtime/memory/`** · 4 file(s)
  - `runtime/memory/cowork/turn_plan.py`
  - `runtime/memory/diagnostics/_trace_store_recovery.py`
  - `runtime/memory/threads/compaction.py`
  - `runtime/memory/threads/llm_summariser.py`
- **`runtime/platform/`** · 7 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/lifecycle/demo.py`
  - `runtime/platform/ui/_app_collab.py`
  - `runtime/platform/ui/_app_parallel.py`
  - `runtime/platform/ui/_app_stack.py`
  - _… and 2 more_
- **`runtime/safety/`** · 4 file(s)
  - `runtime/safety/experiments/prompt_optimizer.py`
  - `runtime/safety/recovery/gepa_bridge.py`
  - `runtime/safety/recovery/workflow_applier.py`
  - `runtime/safety/validation/trust_signal.py`
- **`runtime/sensing/`** · 26 file(s)
  - `runtime/sensing/gateway/_agents_endpoints.py`
  - `runtime/sensing/gateway/_agents_endpoints_conversations.py`
  - `runtime/sensing/gateway/_agents_endpoints_tasks.py`
  - `runtime/sensing/gateway/_config_endpoints_system.py`
  - `runtime/sensing/gateway/_observability_journal.py`
  - _… and 21 more_
- **`runtime/tentacle/`** · 2 file(s)
  - `runtime/tentacle/coordinator.py`
  - `runtime/tentacle/mobile/cerebrum_adapter.py`
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

