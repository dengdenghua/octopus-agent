---
type: "RuntimeSubsystem"
title: "Suckers · 技能注册"
description: "Skill 注册表 · 原子层 · 沙箱 · 测试 tier。"
tags: ["backend", "runtime"]
tier: "core"
---
# Suckers · 技能注册

> Skill 注册表 · 原子层 · 沙箱 · 测试 tier。

**Source**: `runtime/execution/suckers/`

## Package summary

Suckers = skill pool.

## Exports

- `ATOMIC_SKILL_NAMES`
- `DEFAULT_CAPACITY`
- `DEFAULT_REFILL_RATE`
- `Skill`
- `SkillNotFound`
- `SkillRateLimiter`
- `SkillRegistry`
- `SkillSearcher`
- `SkillExpect`
- `SkillTestCase`
- `SkillTester`
- `SkillTestReport`
- `SkillTestResult`
- `SkillTestsFailed`
- `SkillTestTier`
- `TIER_THRESHOLDS`
- `TfIdfSkillSearcher`
- `dump_forged_skill_to_md`
- `is_atomic`
- `load_forged_skills_from_dir`

## Modules

| Module | Summary |
| --- | --- |
| `_browser_skills_handlers.py` | Registrar for browser_skills · extracted from browser_skills.py. |
| `_browser_skills_helpers.py` | Helpers for browser_skills · extracted from browser_skills.py. |
| `_code_intel_handlers.py` | Registrar for code_intelligence_skills · extracted from code_intelligence_skills.py. |
| `_code_intel_helpers.py` | Pure helper functions for code_intelligence_skills · extracted from code_intelligence_skills.py to keep the parent file under 1000 lines. |
| `_delegation_skills_agent.py` | ``_call_agent`` · single isolated subagent delegation. |
| `_delegation_skills_common.py` | Shared leaf helpers for delegation_skills · extracted from delegation_skills.py. |
| `_delegation_skills_judge.py` | ``_run_verdict_repair`` / ``_run_tournament`` / ``_run_cli_team`` · judge panels. |
| `_delegation_skills_orchestration.py` | ``_run_orchestration`` · deterministic multi-round discovery loop. |
| `_delegation_skills_parallel.py` | ``_call_agent_parallel`` · concurrent fan-out + graceful-degradation envelope. |
| `_delegation_skills_pipeline.py` | ``_run_pipeline`` · ordered per-item stage chains, run concurrently. |
| `_delegation_skills_vote.py` | ``_call_agent_vote`` · the consensus / vote gate. |
| `_ephemeral_events.py` | Event emission helpers for ephemeral sub-agent runs. |
| `_ephemeral_tool_exec.py` | Tool execution helpers for ephemeral sub-agent runs. |
| `_lsp_candidates.py` | Seed a language server with the files a reference search must cover. |
| `_memory_skills_handlers.py` | Registrar for memory_skills · extracted from memory_skills.py. |
| `_write_skills_background.py` | Background-process machinery for write_skills · extracted from write_skills.py. |
| `_write_skills_common.py` | Shared helpers & constants for write_skills · extracted from write_skills.py. |
| `_write_skills_exec.py` | Shell execution skills for write_skills · extracted from write_skills.py. |
| `_write_skills_file.py` | File write / append / edit primitives for write_skills · extracted from write_skills.py. |
| `_write_skills_git.py` | Git core skills for write_skills · extracted from write_skills.py. |
| `_write_skills_git_network.py` | Git network / branch-switch skills for write_skills · extracted from write_skills.py. |
| `_write_skills_quality.py` | Code quality skills for write_skills · extracted from write_skills.py. |
| `agent_doc_skills.py` | Agent documentation skills loaded from ``skills/public``. |
| `agent_meta_skills.py` | — |
| `ask_user_question.py` | ask_user_question · pause-and-ask skill. |
| `blackboard_skills.py` | blackboard_skills · expose the turn-scoped shared dict as 3 skills. |
| `browser_act_skills.py` | — |
| `browser_backend.py` | Unified browser automation backend — the seam over three tracks. |
| `browser_backends.py` | Real BrowserBackend adapters over the three automation tracks. |
| `browser_backends_mock.py` | Mock browser backend — scripted, deterministic, no runtime needed. |
| `browser_dom_js.py` | Shared in-page JavaScript for browser perception. |
| `browser_launch.py` | Launching chromium when only some of its builds are installed. |
| `browser_session_worker.py` | Persistent, thread-affine browser sessions for agent browser skills. |
| `browser_skills.py` | — |
| `builtins.py` | — |
| `capability_skills.py` | — |
| `code_edit_skills.py` | AST-aware code editing skills · tree-sitter powered. |
| `code_intelligence_skills.py` | — |
| `code_navigation.py` | Cross-file symbol lookup and Python import-graph analysis. |
| `codex_plugin_skills.py` | — |
| `computer_api_skills.py` | Agent-facing computer automation skills. |
| `computer_skills.py` | — |
| `computer_uia_skills.py` | — |
| `computer_use_loop.py` | — |
| `computer_use_record.py` | Record a successful computer-use loop as a journal Trajectory. |
| `crawler_skills.py` | — |
| `cron_skills.py` | cron_skills · let the agent self-schedule a future turn from inside a turn. |
| `delegation_budget.py` | Smart per-turn delegation budget. |
| `delegation_skills.py` | — |
| `desktop_grounding.py` | Semantic grounding for the desktop vision loop. |
| `echo_skills.py` | ECHO Universe Engine 叙事 Ganglion 接入. |
| `enterprise_skills.py` | Octopus Enterprise 企业服务 Arm 接入. |
| `ephemeral_agents.py` | Ephemeral sub-agent roles · lightweight personas for one-shot delegation tasks (``researcher`` / ``debugger`` / ``reviewer`` / …). |
| `ephemeral_injection_gate.py` | Prompt-injection taint gate for ephemeral sub-agent tool calls. |
| `ephemeral_limits.py` | Round, truncation, and model-selection policy for ephemeral agents. |
| `ephemeral_runner.py` | LLM-backed runner for ephemeral sub-agent roles. |
| `forged_persistence.py` | — |
| `fs_search_skills.py` | — |
| `history_skill.py` | history_skill · cross-thread conversation history retrieval. |
| `hub/installer.py` | — |
| `image_album_skills.py` | Image album skills (local AI photo library). |
| `image_search_backends.py` | Image-search provider backends for the kimi-compat skill group. |
| `image_semantic_skills.py` | Image semantic-search skills (local image library). |
| `kg_skill.py` | — |
| `kimi_compat_skills.py` | — |
| `layers.py` | — |
| `loader/md_loader.py` | — |
| `lsp_skills.py` | LSP (Language Server Protocol) integration skills. |
| `market_skills.py` | — |
| `memory_file_ops.py` | Low-level append operations for Markdown-backed agent memory. |
| `memory_skills.py` | memory_skills · per-agent long-term memory / user-profile / diary skills. |
| `notebook_skills.py` | — |
| `plan_mode.py` | — |
| `rate_limit.py` | Per-skill rate limiter — runaway-loop protection for LLM agents. |
| `registry.py` | — |
| `search.py` | Semantic skill search — TF-IDF-based skill discovery. |
| `skill_library_skills.py` | skill_library_skills · expose Kimi-style "learned skills" as 3 skills. |
| `storage_skills.py` | File Agent document search via the octopus-storage sibling service. |
| `sub_agent.py` | Legacy compatibility shim for subagent dispatch. |
| `testing.py` | — |
| `verdict_repair.py` | Verdict-gated repair loop — the closed-loop orchestration octopus lacked. |
| `verify_skills.py` | Project verification · detect project type and run checks. |
| `video_album_skills.py` | Video album skills (local AI video library). |
| `web_skills.py` | — |
| `write_skills.py` | — |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `_browser_skills_handlers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_browser_skills(registry, verify_tests)` |  |

### `_code_intel_handlers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_code_intelligence_skills(registry)` |  |

### `_delegation_skills_common.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def orchestration_progress_scope(callback)` | Install a progress callback for orchestrations run inside the scope. |

### `_lsp_candidates.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def identifier_at(path, line, character)` | Read the identifier under a 1-based line/character position. |
| func | `def candidate_files(name, root, extensions, limit)` | Files that mention ``name``, plus whether the list was truncated. |

### `_memory_skills_handlers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_memory_skills(registry)` | Register remember / recall / note_user / diary_write. |

### `_write_skills_background.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def recover_background_processes()` | Scan persisted background jobs and converge stale metadata. |
| func | `def background_process_identity_matches(metadata)` | Fail closed if a recovered PID no longer belongs to our process group. |

### `agent_doc_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_agent_doc_skills(registry)` |  |

### `agent_meta_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_agent_meta_skills(registry)` | Register the agent-meta skills. Returns the count registered. |

### `ask_user_question.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_ask_user_question_skill(registry)` | Register the ask_user_question skill. Returns 1. |

### `blackboard_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_blackboard_skills(registry)` | Register bb_read / bb_write / bb_keys. Returns count. |

### `browser_act_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def set_artifact_emitter(emitter)` | Install ``emitter`` as the active SSE artifact callback. |
| func | `def clear_artifact_emitter(token)` | Reset the artifact emitter ContextVar to its prior value. |
| func | `def register_browser_act_skills(registry)` |  |

### `browser_backend.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class Track(StrEnum)` | Which automation implementation served (or should serve) a call. |
| class | `class BrowserResult` | Normalized action result. ``raw`` keeps the track's full dict so nothing is lost while call sites migrate. |
| class | `class BrowserBackend(Protocol)` | The contract a unified browser track must satisfy. |
| func | `def resolve_backend(backends, prefer)` | Pick the highest-priority *available* backend. |

### `browser_backends.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def browser_relay_diagnostics()` |  |
| class | `class ElectronBackend` |  |
| class | `class PlaywrightBackend` |  |
| class | `class ExtensionBackend` |  |

### `browser_backends_mock.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class MockBrowserBackend` | Records every call and returns scripted results. |

### `browser_dom_js.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def dom_state_iife_js(max_items)` | Self-executing snippet for the Electron bridge's execute-JS channel. Adds url/title/text_length, which the bridge cannot get any other way. |
| func | `def dom_snapshot_function_js()` | ``(limit) => {...}`` function source for Playwright's ``page.evaluate(fn, max_items)``. url/title/status come from the Page object on the Py |

### `browser_launch.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def launch_chromium(chromium, **kwargs)` | ``chromium.launch(**kwargs)``, falling back to the full browser build. |
| func | `def launch_persistent_chromium(chromium, **kwargs)` | Same fallback for ``launch_persistent_context``. |

### `browser_session_worker.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class BrowserSessionWorker` | A dedicated thread owning one persistent browser page. |
| class | `class BrowserSessionPool` | Keyed pool of :class:`BrowserSessionWorker` with idle reaping + a cap. |
| func | `def get_browser_session_pool()` | Process-wide lazy singleton pool. |

### `builtins.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_builtins(registry)` |  |
| func | `def register_all(registry)` |  |

### `capability_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def list_capability_entries(registry)` |  |
| func | `def register_capability_skills(registry)` |  |

### `code_edit_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_code_edit_skills(registry)` | Register AST-aware code editing skills. |

### `code_navigation.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def find_symbol(symbol, directory, extensions, **_kw)` |  |
| func | `def dependency_graph(directory, package, **_kw)` |  |

### `codex_plugin_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def plugin_action_name(plugin_id, skill_name)` | Return the runtime action name for a Codex plugin skill. |
| func | `def action_tail(action_name)` |  |
| class | `class CodexPluginSkillLoad` |  |
| class | `class CodexPluginSkillLoadReport` |  |
| func | `def load_codex_plugin_skills(registry, plugin_ids, roots, verify_tests)` | Register prompt actions from Codex-format plugins for this registry. |

### `computer_api_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_computer_api_skills(registry)` |  |

### `computer_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_computer_skills(registry, verify_tests)` |  |

### `computer_uia_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def uia_replay_assertion_for_action(action)` |  |
| func | `def register_computer_uia_skills(registry)` |  |

### `computer_use_loop.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class VisionPlanner(Protocol)` |  |
| class | `class MockVisionPlanner` |  |
| class | `class ModelRouterVisionPlanner` |  |
| func | `def make_computer_use_loop_skill(planner, journal, default_screenshot_dir, default_sandbox_dir, default_max_iterations, default_wait_between_ms, default_stop_on_error)` |  |
| func | `def register_computer_use_loop(registry, planner, **kwargs)` |  |

### `computer_use_record.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def loop_result_to_trajectory(loop_result)` | Convert a *successful* computer-use loop result into a Trajectory. |
| func | `def record_successful_loop(journal, loop_result)` | Write a successful loop to the journal so SkillForge can distil it. |
| func | `def record_failed_loop(loop_result, review_queue_path)` | Capture a *failed* computer-use loop into the review queue. |

### `crawler_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_crawler_skills(registry)` |  |

### `cron_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_cron_skills(registry)` | Register schedule_task / list_scheduled_tasks / cancel_scheduled_task. |

### `delegation_budget.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class OrchestrationBudget` | A bounded total spawn budget for one orchestration. Thread-safe so the parallel fan-out workers can charge it concurrently. |
| func | `def current_orchestration_budget()` | The orchestration budget for the current context, or None. |
| func | `def orchestration_budget_scope(max_spawns)` | Run an orchestration under a bounded total spawn budget, replacing the flat per-turn delegation cap for the duration of the scope. |
| func | `def max_spawns_for_token_budget(token_budget, tokens_per_spawn, floor, ceiling)` | Translate a token budget into an orchestration spawn cap. |
| func | `def operator_orchestration_token_budget()` | Operator-set deployment-wide orchestration token budget, or ``None``. |
| func | `def ultracode_token_budget()` | Server-side token grant for one ``audit.ultracode`` turn. |
| func | `def compute_fingerprint(agent_id, prompt)` | Normalize and hash a delegation spec so repeated identical attempts (modulo whitespace / case) share the same fingerprint. |
| func | `def check_absolute_cap(turn_id, budget)` | Check if we're under the spawn cap. |
| func | `def record_delegation(turn_id, fingerprint, succeeded, budget)` | Record a delegation attempt. |
| func | `def bump_and_check(turn_id)` | Legacy compat shim: pre-check the absolute cap. |

### `delegation_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_delegation_skills(registry)` | Register `call_agent` for sub-agent delegation. Returns count. |

### `desktop_grounding.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def window_grounding(max_windows)` | Return a compact on-screen window list, or ``""`` if unavailable. |
| func | `def ax_control_grounding(max_elements, max_depth)` | Return the frontmost app's actionable UI elements (role/label @ center), or ``""`` if unavailable. macOS Accessibility (AXUIElement) only; n |
| func | `def uia_control_grounding(max_elements, max_depth)` | Windows counterpart of ``ax_control_grounding`` — the foreground app's actionable UIA controls (kind label @ center). ``""`` off Windows or  |
| func | `def combined_grounding()` | Window list + frontmost-app actionable controls, for the vision loop. Each part is best-effort and contributes nothing (``""``) when unavail |

### `echo_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_echo_skills(registry)` | 注册 ECHO 宇宙引擎 skill。始终注册;服务不可达时自报告。 |

### `enterprise_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_enterprise_skills(registry)` | 注册企业版 skill。始终注册;服务不可达时自报告。 |

### `ephemeral_agents.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EphemeralRoleDef` | Everything needed to spin up an ephemeral sub-agent turn. |
| func | `def get_ephemeral_role_ids()` | Stable view for dispatch lookup. |
| class | `class EphemeralCall` | Everything the runner needs to execute a role turn. |
| func | `def set_ephemeral_role_runner(runner)` | Install the runner that executes one ephemeral role turn. |
| func | `def get_ephemeral_role_runner()` |  |
| func | `def is_ephemeral_role(agent_id)` | True iff ``agent_id`` refers to an ephemeral role (vs a registered agent directory). |
| func | `def run_ephemeral_definition(role, user_prompt, session, context, timeout_s)` | Execute one isolated subagent role definition. |
| func | `def run_ephemeral_role(role_id, user_prompt, session, context, timeout_s)` | Execute one built-in ephemeral role turn. |

### `ephemeral_injection_gate.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def mark_inherited_ephemeral_taint(context)` | Re-mark the spawning parent's prompt-injection taint inside an ephemeral sub-agent run, reading it from the sub-agent ``context``. |
| func | `def ephemeral_injection_taint_block(call, tool_name)` | Fail-closed taint gate. Returns a block message when a risky tool must be refused because the delegating turn is injection-tainted, else ``N |
| func | `def scan_and_escalate_ephemeral_taint(tool_name, affinity, rendered)` | Raise the turn taint if an untrusted tool returned injection-flagged content, so a later risky tool in the same ephemeral run is gated too. |

### `ephemeral_limits.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EphemeralRoundCapExceeded(RuntimeError)` | Raised when a sub-agent fails to converge within its round cap. |
| func | `def is_length_limited_finish(reason)` |  |
| func | `def looks_truncated_text(text, output_tokens, max_tokens)` | Best-effort fallback when a provider omits a truncation finish reason. |
| func | `def select_call_model(default_model, context)` | Honor one call's explicit model override, falling back to the factory model. |

### `ephemeral_runner.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EphemeralRoundCapExceeded(RuntimeError)` | Raised when the ephemeral sub-agent loop hits its round cap. |
| func | `def make_llm_ephemeral_runner(router, registry, default_model, max_tokens, temperature, system_provider, token_budget)` | Build an ephemeral runner that calls ``router.call(request)`` per invocation. |

### `forged_persistence.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def dump_forged_skill_to_md(candidate, out_dir)` |  |
| func | `def load_forged_skills_from_dir(dir_path, registry, skip_missing_subskills)` |  |

### `fs_search_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_fs_search_skills(registry)` | Register glob_files / grep_text / tree / read_file_range. |

### `history_skill.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def set_default_thread_store(store)` | Inject the runtime's live ThreadStateStore (called at app boot). |
| func | `def register_history_skill(registry)` |  |

### `hub/installer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ArchiveSafetyError(ValueError)` |  |
| func | `def safe_extract_zip(archive_bytes, dest_dir, max_entry_bytes, max_total_bytes)` |  |
| func | `def install_from_archive(archive_bytes, dest_dir, overwrite, max_entry_bytes, max_total_bytes)` |  |

### `image_album_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_image_album_skills(registry)` |  |

### `image_search_backends.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def search_image_by_text(query, max_results, backend, **_)` |  |
| func | `def search_image_by_image(image_url, image_path, **_)` |  |

### `image_semantic_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_image_semantic_skills(registry)` |  |

### `kg_skill.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def set_default_kg(kg)` |  |
| func | `def register_kg_skill(registry)` |  |

### `kimi_compat_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_kimi_compat_skills(registry)` |  |

### `layers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def is_atomic(skill_name)` |  |
| func | `def as_skill_ids()` |  |
| func | `def select_tool_specs(allowlist, all_specs)` | Pick which tool specs an ephemeral sub-agent may use (by ``spec.name``). |

### `loader/md_loader.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SkillLoadError(ValueError)` |  |
| func | `def load_skill_from_md(md_path)` |  |
| func | `def load_skills_from_dir(dir_path, glob, recursive, skip_errors)` |  |

### `lsp_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_lsp_skills(registry)` | Register the 4 LSP navigation skills. Returns the count registered. |

### `market_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_market_skills(registry, all_skills_dir, respect_enabled_flag, verify_tests)` |  |
| func | `def load_single_market_skill(registry, skill_id, all_skills_dir, ignore_frontmatter_enabled, verify_tests)` |  |

### `memory_file_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def iso_now()` |  |
| func | `def append_memory_line(path, fact, tags)` | Append one timestamped fact, removing the empty scaffold marker. |

### `notebook_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_notebook_skills(registry)` | Register notebook_read / notebook_edit. Returns 2. |

### `plan_mode.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_plan_mode_skill(registry)` | Add ``exit_plan_mode`` to the given SkillRegistry. |

### `rate_limit.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SkillRateLimiter` | Per-(skill, caller) token bucket rate limiter. |

### `registry.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class Skill(BaseModel)` |  |
| class | `class SkillNotFound(KeyError)` |  |
| class | `class SkillRegistry` |  |

### `search.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SkillSearcher(ABC)` | Abstract skill-search interface. |
| class | `class TfIdfSkillSearcher(SkillSearcher)` | TF-IDF-based semantic search over the registry's skill index. |

### `skill_library_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_skill_library_skills(registry)` |  |

### `storage_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def storage_manifest(timeout)` | Probe Storage's ``/v1/manifest`` — ``None`` when the service is down. |
| func | `def storage_alive(timeout)` | Liveness probe: True when Storage RESPONDS at all — including an auth error. A 401/403 means the server is up and answering (restarting it w |
| func | `def register_storage_skills(registry)` | Register the File Agent document-search skill. Always registered; it self-reports at call time when Storage isn't available. |

### `sub_agent.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_sub_agent_skill(registry)` | Deprecated opt-in shim that registers ``call_agent`` as a legacy skill. |

### `testing.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SkillExpect(BaseModel)` |  |
| class | `class SkillTestCase(BaseModel)` |  |
| class | `class SkillTestResult(BaseModel)` |  |
| class | `class SkillTestReport(BaseModel)` |  |
| class | `class SkillTestsFailed(RuntimeError)` |  |
| class | `class SkillTester` |  |

### `verdict_repair.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class Verdict` | A judge's ruling on one attempt. ``passed`` ends the loop; ``critique`` is the reason a failed attempt was rejected — fed into the next prod |
| class | `class RepairRound` |  |
| class | `class RepairResult` |  |
| func | `def run_verdict_repair(produce, judge, max_repairs)` | Run ``produce`` then ``judge``; while the verdict is a failure and repairs remain, re-``produce`` with the critique and re-``judge``. Stops  |

### `verify_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def classify_environment_gap(output)` |  |
| func | `def output_indicates_missing_tool(output)` |  |
| class | `class ProjectProfile` |  |
| class | `class CheckResult` |  |
| func | `def detect_project(workspace)` |  |
| func | `def run_checks(profile, timeout_per_check, max_output, sandbox_dir)` |  |

### `video_album_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_video_album_skills(registry)` |  |

### `web_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_web_skills(registry)` |  |

### `write_skills.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_write_skills(registry)` |  |
| func | `def register_git_skills(registry)` |  |
| func | `def register_exec_skill(registry)` |  |
| func | `def register_git_network_skills(registry)` | Register git network/branch skills · opt-in · dangerous. |
| func | `def register_code_quality_skills(registry)` | Register code quality skills · lint / test / format. |


## Who imports this

**63** file(s) reference this package:

- **`runtime/_cli_commands.py/`** · 1 file(s)
  - `runtime/_cli_commands.py`
- **`runtime/adapters/`** · 1 file(s)
  - `runtime/adapters/mcp_client/bridge.py`
- **`runtime/cli_core.py/`** · 1 file(s)
  - `runtime/cli_core.py`
- **`runtime/cli_reflect.py/`** · 1 file(s)
  - `runtime/cli_reflect.py`
- **`runtime/cli_run.py/`** · 1 file(s)
  - `runtime/cli_run.py`
- **`runtime/core/`** · 7 file(s)
  - `runtime/core/cerebrum/_react_context_helpers.py`
  - `runtime/core/cerebrum/_react_context_project.py`
  - `runtime/core/cerebrum/_react_execution_dispatch.py`
  - `runtime/core/cerebrum/_react_prompt_assembly_guidance.py`
  - `runtime/core/cerebrum/capability_router.py`
  - _… and 2 more_
- **`runtime/execution/`** · 9 file(s)
  - `runtime/execution/all_skills/__init__.py`
  - `runtime/execution/arms/base.py`
  - `runtime/execution/loops/verifiers.py`
  - `runtime/execution/misc/skill_policy.py`
  - `runtime/execution/subagents/_bridge_trace.py`
  - _… and 4 more_
- **`runtime/memory/`** · 3 file(s)
  - `runtime/memory/cowork/runtime.py`
  - `runtime/memory/hemolymph/composer.py`
  - `runtime/memory/learning/deep_evolution.py`
- **`runtime/platform/`** · 8 file(s)
  - `runtime/platform/config/builder.py`
  - `runtime/platform/lifecycle/demo.py`
  - `runtime/platform/plugins/bundled/whale_eye/__init__.py`
  - `runtime/platform/ui/_app_stack.py`
  - `runtime/platform/ui/_browser_artifact_path.py`
  - _… and 3 more_
- **`runtime/research/`** · 2 file(s)
  - `runtime/research/pipeline.py`
  - `runtime/research/prefetch.py`
- **`runtime/safety/`** · 6 file(s)
  - `runtime/safety/evolution/_recipes_evidence.py`
  - `runtime/safety/evolution/auto_trigger.py`
  - `runtime/safety/evolution/browser_desktop_quality.py`
  - `runtime/safety/hooks/tool_edge_hooks.py`
  - `runtime/safety/recovery/intel_collector.py`
  - `runtime/safety/recovery/skill_forge.py`
- **`runtime/sensing/`** · 22 file(s)
  - `runtime/sensing/gateway/_agent_world_helpers.py`
  - `runtime/sensing/gateway/_meta_mentions.py`
  - `runtime/sensing/gateway/_realtime_react_stream_drive.py`
  - `runtime/sensing/gateway/_realtime_react_stream_helpers.py`
  - `runtime/sensing/gateway/_team_stream_group_fanout.py`
  - _… and 17 more_
- **`runtime/tour.py/`** · 1 file(s)
  - `runtime/tour.py`

