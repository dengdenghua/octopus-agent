---
type: "SensingSubsystem"
title: "Sensing · Gateway (HTTP API)"
description: "全部 FastAPI router · openai_gateway / meta / mcp / config / channels / thread_compat / …"
tags: ["backend", "sensing"]
tier: "standard"
---
# Sensing · Gateway (HTTP API)

> 全部 FastAPI router · openai_gateway / meta / mcp / config / channels / thread_compat / …

**Source**: `runtime/sensing/gateway/`

## Exports

- `StreamingJournal`
- `create_evolution_ops_router`
- `create_openai_router`
- `create_parallel_agents_router`
- `create_thread_state_router`

## Modules

| Module | Summary |
| --- | --- |
| `_agent_trace_router_approvals.py` | Approval, trust-denial, token-usage, checkpoint, and resume endpoint handlers for the agent trace router. |
| `_agent_trace_router_promotion.py` | Promotion and policy-review endpoint handlers for the agent trace router. |
| `_agent_trace_router_review.py` | Review, experience-ledger, and review-queue endpoint handlers for the agent trace router. |
| `_agent_trace_router_stores.py` | Shared store singletons, dependency container, and planning helpers for the agent trace router. |
| `_agent_trace_router_trace.py` | Trace-read endpoint handlers for the agent trace router. |
| `_agent_world_helpers.py` | Helper functions and data for ``agent_world_router``. |
| `_agents_endpoints.py` | Endpoint handlers for the agents router. |
| `_agents_endpoints_conversations.py` | Conversation (journal) endpoints for the agents router. |
| `_agents_endpoints_crud.py` | Agent CRUD + visual + reload endpoints for the agents router. |
| `_agents_endpoints_groups.py` | Agent-group endpoints for the agents router. |
| `_agents_endpoints_local_partners.py` | LocalPartner endpoints for the agents router. |
| `_agents_endpoints_shared.py` | Shared types for the ``_agents_endpoints`` submodules. |
| `_agents_endpoints_system.py` | System-level endpoints (regeneration status + capabilities) for the agents router. |
| `_agents_endpoints_tasks.py` | Task (pause/resume) endpoints for the agents router. |
| `_agents_endpoints_tools.py` | Arms + tool-registry endpoints for the agents router. |
| `_agents_helpers.py` | Pure helper functions for the agents router. |
| `_agents_local_partner_doctor.py` | Doctor-style readiness summary for LocalPartner. |
| `_agents_local_partner_guidance.py` | UX guidance / command hints / diagnostics for the LocalPartner connect dialog. |
| `_agents_local_partner_security.py` | Security primitives for LocalPartner detection + registration. |
| `_agents_local_partner_specs.py` | Registry of supported LocalPartner CLI specs. |
| `_agents_local_partner_writer.py` | SOUL.md template + agent writer for LocalPartner registration. |
| `_channels_constructors.py` | — |
| `_channels_models.py` | — |
| `_channels_persist.py` | — |
| `_config_endpoints.py` | Endpoint handlers for the config router. |
| `_config_endpoints_custom_models.py` | Custom-model lifecycle endpoints for the config router. |
| `_config_endpoints_local_models.py` | Local-model discovery + one-click import endpoints for the config router. |
| `_config_endpoints_models.py` | Model listing & compatibility endpoints for the config router. |
| `_config_endpoints_security.py` | Security & safety config endpoints for the config router. |
| `_config_endpoints_system.py` | System / runtime-config endpoints for the config router. |
| `_config_helpers.py` | Pure helper functions for the config router. |
| `_config_models.py` | Pydantic response models for the config router. |
| `_event_bridge_tool_items.py` | Tool-event → item/description builders for the realtime bridge. |
| `_evolution_helpers.py` | — |
| `_evolution_models.py` | — |
| `_fs_router_diff.py` | Unified-diff parsing / reverse-apply helpers for the filesystem router. |
| `_fs_router_endpoints.py` | Endpoint handlers for the filesystem router. |
| `_fs_router_helpers.py` | Shared helpers for the filesystem router factory. |
| `_fs_router_models.py` | Response models and shared constants for the filesystem router. |
| `_fs_router_paths.py` | Path / root-resolution helpers for the filesystem router. |
| `_meta_mentions.py` | @-mention autocomplete builder for the meta router. |
| `_meta_models.py` | Pydantic response models for the meta router. |
| `_meta_skill_install.py` | Skill install / uninstall filesystem helpers for the meta router. |
| `_meta_skill_metadata.py` | Skill metadata assembly for the meta router. |
| `_observability_auth.py` | Router-level auth helpers shared by the observability endpoint groups. |
| `_observability_helpers.py` | Shared helpers for the observability router factory. |
| `_observability_journal.py` | Journal, reflect, evolution and tool-effect endpoints for the observability router. |
| `_observability_kg.py` | Knowledge-graph endpoints for the observability router. |
| `_observability_progress_stream.py` | Progress and SSE-stream endpoints for the observability router. |
| `_observability_rollback_panels.py` | File-rollback, rewind, blackboard, hemolymph, regeneration, budget and run endpoints. |
| `_observability_router_factory.py` | Factory for the observability router. |
| `_observability_state.py` | Shared state container for the observability router endpoint groups. |
| `_openai_gateway_router_helpers.py` | — |
| `_openai_gateway_router_ratelimit.py` | — |
| `_openai_gateway_router_run.py` | — |
| `_openai_gateway_router_synthesize.py` | — |
| `_realtime_cerebrum_project_os.py` | Project OS bridge for the realtime runtime. |
| `_realtime_cerebrum_requests.py` | JSON-RPC method dispatch for the realtime runtime. |
| `_realtime_cerebrum_steering.py` | Active-turn lease + steering management for the realtime runtime. |
| `_realtime_cerebrum_thread.py` | Thread/session + emit helpers for the realtime runtime. |
| `_realtime_gateway_approval.py` | Per-connection approval manager and gateway-wide interrupt registry. |
| `_realtime_gateway_connection.py` | Per-WebSocket RPC connection (``RpcConnection``). |
| `_realtime_gateway_frame.py` | Last-ditch frame-size guard so no single WS frame exceeds the ceiling. |
| `_realtime_gateway_types.py` | Shared types, protocols, exceptions and constants for the realtime gateway. |
| `_realtime_orchestrator_bridge.py` | Bridge a ``ParallelAgentOrchestrator`` batch stream onto a realtime turn. |
| `_realtime_react_stream_apply.py` | Reducer that maps bridge events to ``item/*`` notifications. |
| `_realtime_react_stream_drive.py` | ReAct loop stream driver. |
| `_realtime_react_stream_helpers.py` | Shared helpers & reactive predicates for the realtime stream drivers. |
| `_realtime_react_stream_reflection.py` | Direct-LLM reflection fast-path stream driver. |
| `_realtime_team_stream_mesh.py` | Mesh swarm stream driver — auto-selecting swarm (mesh vs team) + fallback. |
| `_realtime_turn_lifecycle_helpers.py` | Shared helpers for the realtime turn lifecycle. |
| `_realtime_turn_lifecycle_resume.py` | Resume-intent persistence for the realtime turn lifecycle. |
| `_team_stream_group_fanout.py` | Group fan-out stream driver — 蜂群 / 冒泡 cowork dispatch. |
| `_team_stream_topology.py` | Multi-agent team-topology stream driver — topology resolution + bridge. |
| `_team_tasks_helpers.py` | Module-level helpers for the persistent team tasks router. |
| `_team_tasks_models.py` | Pydantic wire models for the persistent team tasks API. |
| `_tool_bridge_exec.py` | Tool execution + semantic error + XML recovery helpers. |
| `_tool_bridge_loop.py` | The native agentic tool loop (``stream_agentic_fallback``). |
| `_tool_bridge_native.py` | Native model stream + timeout + tool-call fingerprint/dedup helpers. |
| `_tool_bridge_policy.py` | Goal / scope / budget / shell policy helpers for the native tool loop. |
| `_tool_bridge_protocol.py` | Public checkpoint / protocol-tag cleaning + narration helpers. |
| `_tool_bridge_scoring.py` | Per-turn quality scoring + auto-evolution tick helpers. |
| `_tool_bridge_session.py` | Session metadata + browser operation guidance helpers. |
| `account_usage_router.py` | — |
| `agent_market_sources/financial-services/agent-plugins/model-builder/skills/dcf-model/scripts/validate_dcf.py` | DCF Model Validation Script Validates Excel DCF models for formula errors and common DCF mistakes |
| `agent_market_sources/financial-services/agent-plugins/pitch-agent/skills/dcf-model/scripts/validate_dcf.py` | DCF Model Validation Script Validates Excel DCF models for formula errors and common DCF mistakes |
| `agent_market_sources/financial-services/agent-plugins/pitch-agent/skills/ib-check-deck/scripts/extract_numbers.py` | Extract numerical values from presentation content for consistency checking. |
| `agent_modes_router.py` | Agent project/code mode detection endpoints. |
| `agent_trace_dependencies.py` | State factories and promotion helpers for the agent-trace API. |
| `agent_trace_router.py` | Read-only API for the durable agent trace store. |
| `agent_world_router.py` | Agent Market router · local agent marketplace. |
| `agents_local_partner.py` | LocalPartner subsystem — detection + secure registration. |
| `agents_models.py` | Pydantic wire models for ``agents_router``. |
| `agents_router.py` | Agents router · public factory for the ``/api/agents`` surface. |
| `ambient_suggestions_router.py` | Ambient Suggestions router · ``/api/ambient-suggestions/*``. |
| `android_router.py` | Android device HTTP API — server-side counterpart to Octopus Mobile. |
| `anthropic_compat/event_adapter.py` | Map internal ReAct loop events to Anthropic Managed Agents event shapes. |
| `anthropic_compat/models.py` | Pydantic models for the Anthropic Managed Agents compat layer. |
| `anthropic_compat/router.py` | Anthropic Managed Agents REST + SSE router. |
| `anthropic_compat/session_manager.py` | Session lifecycle manager for the Anthropic compat layer. |
| `apps_router.py` | — |
| `channels_router.py` | — |
| `cli_team_router.py` | CLI-team router · ``/api/cli-team/*``. |
| `completion_router.py` | Inline code completion endpoint — Tab-complete skeleton. |
| `computer_actions.py` | Action normalization/execution/preview-contract + UIA goal-planning for the computer-automation router. |
| `computer_control_session.py` | Control-session bookkeeping and activity/replay logging for the computer-automation router. |
| `computer_diagnostics.py` | Diagnostic / capability payload builders for the computer-automation router family. |
| `computer_lease.py` | Exclusive-operator lease management for the computer-automation router. |
| `computer_replay_evidence.py` | Replay-evidence summary for the computer-automation router family. |
| `computer_router.py` | Computer automation API. |
| `computer_router_state.py` | Shared mutable state for the computer-automation router family. |
| `computer_runtime_readiness.py` | Runtime-readiness aggregation for the computer-automation router. |
| `computer_vision.py` | Vision-model config resolution + OpenAI-compatible vision call for the computer-automation router. |
| `config_router.py` | Config router · identity-lock + providers + custom-models. |
| `control_sessions_router.py` | Unified control-session API. |
| `cowork_group_router.py` | Thread-group API: WeChat-style membership + mode + shared blackboard. |
| `cron_router.py` | Cron settings compatibility router. |
| `dag_debugger_router.py` | — |
| `debug_router.py` | Debug diagnostics router · ``/api/debug/session-info``. |
| `deep_research_router.py` | Deep research API router. |
| `deployments_router.py` | — |
| `enterprise_assets_router.py` | Agent 消费企业版角色资产库(数字分身归并 C · 消费侧,只读)。 |
| `evolution_ops/budget.py` | Budget subsystem for evolution operators. |
| `evolution_ops/curriculum.py` | Curriculum subsystem for evolution operators. |
| `evolution_ops/framework_benchmarks.py` | Framework benchmarks subsystem for evolution operators. |
| `evolution_ops/mcp_ops.py` | MCP subsystem for evolution operators. |
| `evolution_ops/protocol_drift.py` | Protocol drift subsystem for evolution operators. |
| `evolution_ops/recipe_forge.py` | RecipeForge subsystem for evolution operators. |
| `evolution_ops/skill_forge.py` | SkillForge subsystem for evolution operators. |
| `evolution_ops/utils.py` | Shared utility functions for evolution operator subsystems. |
| `evolution_ops_router.py` | Evolution operator console control-plane routes. |
| `evolution_router.py` | — |
| `fs_router.py` | Filesystem router · ``/api/fs/{tree,read,write}``. |
| `index_router.py` | Code index router · ``/api/index/*``. |
| `intelligence_router.py` | — |
| `invariants_router.py` | Invariants router · catalog of the 34-rule constitution and which functions enforce each rule. |
| `journal_router.py` | Journal query router · ``/api/journal/*``. |
| `local_brain.py` | One-glance local-brain readiness for the work-mode setup wizard. |
| `local_brain_router.py` | Local-brain setup router · ``/api/local-brain/*``. |
| `loop_router.py` | — |
| `lsp_router.py` | Thin HTTP wrapper around the registered LSP skills. |
| `mcp_router.py` | MCP router · declare / enable / disable MCP servers at runtime. |
| `media_router.py` | Media (video understanding) web API. |
| `memory_router.py` | Local memory compatibility API. |
| `meta_router.py` | Meta router · feedback / skills / auth-provider listing. |
| `meta_skill_router.py` | FastAPI router for the 能力包 / Meta-Skill catalog. |
| `metrics_router.py` | Metrics router — Prometheus text export of the in-process registry. |
| `observability_router.py` | Observability router · journal / reflect / kg / progress / stream / run. |
| `openai_formatting.py` | Pure-function formatters for the OpenAI-compat gateway. |
| `openai_gateway/context_manager.py` | — |
| `openai_gateway/mix.py` | Octopus Mix — a mixture-of-agents virtual model for the OpenAI gateway. |
| `openai_gateway/request_parser.py` | — |
| `openai_gateway/response_formatter.py` | — |
| `openai_gateway/stream_handler.py` | — |
| `openai_gateway/synthesis.py` | Final-answer synthesis for completed non-streaming gateway runs. |
| `openai_gateway/tool_converter.py` | — |
| `openai_gateway_router.py` | — |
| `org_router.py` | Organization API router (阶段一 企业协作 · 组织 API 路由). |
| `organizations_router.py` | REST endpoints for team-topology management. |
| `parallel_agents_router.py` | — |
| `plugin_hub_router.py` | PluginHub management REST API. |
| `plugins_router.py` | — |
| `projects_router.py` | Project OS API — drive milestone-driven projects over HTTP. |
| `prompts_router.py` | Prompts router · ``/api/prompts/*``. |
| `realtime_approval.py` | Approval bridge between the blocking react loop and the async gateway. |
| `realtime_cerebrum.py` | Cerebrum-backed realtime runtime. |
| `realtime_echo.py` | Echo runtime — reference :class:`RealtimeRuntime` implementation. |
| `realtime_event_bridge.py` | React-event → ``item/*`` bridge state for the realtime runtime. |
| `realtime_frame_bounds.py` | Last-resort frame bounding for realtime WebSocket notifications. |
| `realtime_gateway.py` | Realtime gateway — JSON-RPC 2.0 over WebSocket. |
| `realtime_local_partner.py` | Direct execution of LocalPartner agents on the realtime path. |
| `realtime_react_policy.py` | Routing policy and event translation for realtime agent streams. |
| `realtime_react_stream.py` | Single-agent stream drivers for the realtime runtime. |
| `realtime_team_stream.py` | Multi-agent team-topology stream driver for the realtime runtime. |
| `realtime_thread_history.py` | Realtime turn ↔ legacy conversation history adapters. |
| `realtime_thread_ops.py` | Thread maintenance operations for the realtime runtime. |
| `realtime_turn_input.py` | Turn-input shaping for the realtime runtime. |
| `realtime_turn_lifecycle.py` | Realtime turn validation, dispatch, resume handling, and finalization. |
| `realtime_turn_outcome.py` | Turn outcome inspection for the realtime runtime. |
| `realtime_turn_routing.py` | Turn-routing helpers for the realtime runtime. |
| `realtime_turn_support.py` | Observable-output, cowork-context, and resume-intent helpers. |
| `realtime_workbench.py` | Workbench snapshot + workspace-focus helpers for the realtime runtime. |
| `registry_consumer_router.py` | 资产 Registry 消费路由(母体接 registry · 只读浏览 + 安装 prompt-skill)。 |
| `remote_backends_router.py` | Remote backends router · ``/api/remote-backends/*``. |
| `remote_transport.py` | Remote Transport · connect a desktop session to a remote octopus-agent runtime over SSH-tunneled HTTP. |
| `retrieve_router.py` | Retrieval router · ``/api/retrieve/rank``. |
| `searxng_supervisor.py` | One-click local SearXNG for the private web-search backend. |
| `skill_market_router.py` | — |
| `slash_command_expansion.py` | Slash-command expansion for realtime chat input. |
| `storage_proxy_router.py` | Same-origin gateway for the private octopus-storage service. |
| `storage_supervisor.py` | Optional co-launch of the octopus-storage sibling service. |
| `streaming_journal.py` | — |
| `stub_router.py` | — |
| `subagents_router.py` | Subagent FastAPI router. |
| `system_router.py` | System-level local maintenance endpoints. |
| `task_runs_router.py` | — |
| `teach_repeat_router.py` | Teach & Repeat API. |
| `team_role_models_router.py` | Team role-model settings router · ``/api/team/role-models``. |
| `team_rooms_router.py` | Persistent team rooms API. |
| `team_rooms_ws.py` | Realtime Team Room WebSocket handler. |
| `team_speaker_policy.py` | Pure team-room governance helpers. |
| `team_tasks_router.py` | Persistent team tasks API. |
| `tentacle_join_router.py` | Tentacle join router · ``/api/tentacle/join-info``. |
| `terminal_router.py` | terminal_router · WebSocket-based persistent shell sessions. |
| `thread_state_router.py` | Thread state HTTP router used by the realtime UI. |
| `tool_bridge.py` | tool_bridge · the agentic-loop helper that turns Octopus skills into Claude-native ``tool_use`` calls and loops result → next turn. |
| `turn_session.py` | Turn session metadata assembly for realtime execution. |
| `uploads_router.py` | Thread uploads / artifacts router. |
| `verify_router.py` | Verification router · ``/api/verify/*``. |
| `wiki_generic.py` | Project-agnostic wiki generator · scans an arbitrary user-selected folder and writes a navigable static documentation tree under ``<root>/.octopus-wiki/``. |
| `wiki_router.py` | — |
| `workspace_api_router.py` | Workspace HTTP API · ``/api/workspaces/*``. |
| `workspaces_router.py` | Workspace manifest API. |

## Key classes & functions

> AST 自动提取 · 仅列公开顶层 class / function · 签名与真实代码一致。

### `_agent_trace_router_approvals.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_approvals_endpoints(router, deps)` |  |

### `_agent_trace_router_promotion.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_promotion_endpoints(router, deps)` |  |

### `_agent_trace_router_review.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_review_endpoints(router, deps)` |  |

### `_agent_trace_router_stores.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RouterDeps` | Container of the dependencies threaded through the endpoint handlers. |

### `_agent_trace_router_trace.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_trace_endpoints(router, deps)` |  |

### `_agents_local_partner_doctor.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def doctor_summary(partners)` | Aggregate local partner readiness into a doctor-style report. |

### `_agents_local_partner_security.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def validate_alias(value)` | Reject aliases that could pollute SOUL.md / IDENTITY.md or DoS disk. |
| func | `def identity_has_admin_role(identity)` | Conservative admin check. |
| func | `def safe_executable(executable_path)` | Reject executables that resolve into the current working directory subtree. Defense against the most common PATH-poisoning scenario: an atta |

### `_agents_local_partner_writer.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def soul_template(alias, partner_name, command)` | Render the SOUL.md persona block for a registered partner. |
| func | `def write_partner_agent(spec, alias, command, executable, runtime, registry)` | Write a LocalPartner agent's profile + SOUL/IDENTITY/AGENTS docs to disk and register it in the agent registry. Returns the loaded Agent ins |

### `_channels_constructors.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_channel_constructor(platform, constructor)` |  |

### `_fs_router_endpoints.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_endpoints(router, ctx)` |  |

### `_observability_auth.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def make_auth_dep(ctx)` | Router-level auth gate · mirrors create_browser_router. These endpoints expose the journal (file diffs, absolute paths, task history) over / |

### `_observability_journal.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_journal_endpoints(router, ctx)` | Register journal / reflect / evolution / tool-effect endpoints. |

### `_observability_kg.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_kg_endpoints(router, ctx)` | Register the knowledge-graph / knowledge endpoints. |

### `_observability_progress_stream.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_progress_stream_endpoints(router, ctx)` | Register the progress + SSE stream endpoints. |

### `_observability_rollback_panels.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def register_rollback_panels_endpoints(router, ctx)` | Register the rollback / rewind / panel / budget / run endpoints. |

### `_observability_router_factory.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_observability_router(journal, registry, planner, effect_store, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build the router. |

### `_observability_state.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ObservabilityContext` | Shared runtime state threaded through the observability builders. |

### `_openai_gateway_router_synthesize.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def synthesize_reply(stack, goal, trajectory, model, agent, conversation_messages, profile_memories, user_context, usage_out)` |  |

### `_realtime_gateway_approval.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ApprovalManager` | Tracks server→client requests awaiting a client response. |
| class | `class SharedTurnInterrupts` | Gateway-wide interrupt registry, shared by every connection. |

### `_realtime_gateway_connection.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RpcConnection` | One client. Owns the WS, the approval manager, and a write lock. |

### `_realtime_gateway_types.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EventEmitter(Protocol)` | Sink the runtime uses to push events out to a client. |
| class | `class RealtimeRuntime(Protocol)` | The contract turn loops implement to plug into the gateway. |

### `_realtime_orchestrator_bridge.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `async def bridge_orchestrator_batch(orchestrator, batch_id, turn, log, emitter)` | Stream ``batch_id``'s tasks onto ``turn`` as live ``SubagentItem`` tiles. |

### `_team_tasks_models.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TaskAssigneeWire(BaseModel)` | Who the task is assigned to. Polymorphic so a task can target AI roster members AND human participants in the same field. |
| class | `class TeamTaskWire(BaseModel)` |  |
| class | `class CreateTeamTaskRequest(BaseModel)` |  |
| class | `class UpdateTeamTaskRequest(BaseModel)` |  |

### `_tool_bridge_loop.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def stream_agentic_fallback(stack, intent, agent, model, sub_event_queue, steering_drain)` | Agentic streaming · same ``(kind, delta, final)`` shape as ``_stream_direct_llm_fallback`` so the SSE loop can consume both paths identicall |

### `_tool_bridge_protocol.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def strip_leaked_protocol_tags(text)` | Remove structural protocol tags that leaked into literal text. |

### `account_usage_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_account_usage_router(journal, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `agent_market_sources/financial-services/agent-plugins/model-builder/skills/dcf-model/scripts/validate_dcf.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class DCFModelValidator` | Validates DCF models for errors and quality issues |
| func | `def validate_dcf_model(excel_path)` | Validate a DCF model Excel file |
| func | `def main()` | Command-line interface |

### `agent_market_sources/financial-services/agent-plugins/pitch-agent/skills/dcf-model/scripts/validate_dcf.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class DCFModelValidator` | Validates DCF models for errors and quality issues |
| func | `def validate_dcf_model(excel_path)` | Validate a DCF model Excel file |
| func | `def main()` | Command-line interface |

### `agent_market_sources/financial-services/agent-plugins/pitch-agent/skills/ib-check-deck/scripts/extract_numbers.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class NumberInstance` | A numerical value found in the presentation. |
| func | `def normalize_number(value_str, unit)` | Convert a number string with unit to a normalized float value. |
| func | `def detect_category(context, unit)` | Detect the category of a number based on context and unit. |
| func | `def extract_numbers(content)` | Extract all numbers from presentation content. |
| func | `def find_inconsistencies(numbers)` | Find potential inconsistencies in extracted numbers. |
| func | `def main()` |  |

### `agent_modes_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_agent_modes_router()` |  |

### `agent_trace_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_agent_trace_router(store, db_path, experience_ledger, experience_ledger_path, review_queue, review_queue_path, promotion_audit_path, proposal_ledger_path, approval_policy_path, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `agent_world_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_agent_world_router(registry, runtime, skill_registry, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `agents_local_partner.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def readiness_for_partner(partner_id, command, executable)` | Explain whether a detected local partner is actually dispatchable. |
| func | `def partner_model(partner_id)` | Read a local CLI partner's own configured default model — its namespace (e.g. codex ``gpt-5.5``), NOT octopus's — so the UI can display it i |
| func | `def resolve_local_command(command)` |  |
| func | `def which_command(commands)` | Probe a list of candidate commands; return (name, path) for the first match, or (None, None) if none found. |
| func | `def dir_registered(agent_id)` | True iff ``agents/<agent_id>/profile.jsonc`` exists on disk. |
| func | `def to_wire(spec, registry, which_fn)` | Materialize a partner spec into its current-state wire form. |
| func | `def probe_partner(partner_id, command, executable, timeout, runner)` | Run a small real health probe against a detected local partner. |

### `agents_models.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CreateAgentRequest(BaseModel)` |  |
| class | `class UpdateAgentRequest(BaseModel)` |  |
| class | `class GenerateAgentVisualsRequest(BaseModel)` |  |
| class | `class AgentVisualsWire(BaseModel)` |  |
| class | `class AgentWire(BaseModel)` |  |
| class | `class ArmWire(BaseModel)` |  |
| class | `class AgentDetailWire(AgentWire)` |  |
| class | `class ArmOptionWire(BaseModel)` |  |
| class | `class ToolRegistryWire(BaseModel)` |  |
| class | `class CapabilitiesWire(BaseModel)` |  |
| class | `class LocalPartnerCommandHint(BaseModel)` |  |
| class | `class LocalPartnerDiagnosticItem(BaseModel)` |  |
| class | `class LocalPartnerWire(BaseModel)` |  |
| class | `class LocalPartnerDoctorGroup(BaseModel)` |  |
| class | `class LocalPartnerDoctorResponse(BaseModel)` |  |
| class | `class LocalPartnerRegisterItem(BaseModel)` |  |
| class | `class LocalPartnerRegisterRequest(BaseModel)` |  |
| class | `class LocalPartnerRegisterResult(BaseModel)` |  |
| class | `class LocalPartnerRegisterResponse(BaseModel)` |  |
| class | `class LocalPartnerProbeResponse(BaseModel)` |  |
| class | `class PauseTaskBody(BaseModel)` |  |
| class | `class ResumeTaskBody(BaseModel)` |  |
| class | `class GroupCreate(BaseModel)` |  |
| class | `class GroupUpdate(BaseModel)` |  |
| class | `class GroupWire(BaseModel)` |  |

### `agents_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_agents_router(registry, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, journal, group_registry, runtime, thread_store)` |  |

### `ambient_suggestions_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_ambient_suggestions_router(base_dir)` | Factory. ``base_dir`` override is for tests; production uses ``<data>/ambient_suggestions/`` via the module default. |

### `android_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_android_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `anthropic_compat/event_adapter.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def turn_started_event()` |  |
| func | `def turn_completed_event(interrupted)` |  |
| func | `def requires_action_event(blocking_event_ids)` |  |
| func | `def adapt_react_event(event)` | Convert a single ReAct event dict into Anthropic-shaped events. |

### `anthropic_compat/models.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SessionStatus(StrEnum)` |  |
| class | `class UsageInfo(BaseModel)` |  |
| class | `class CreateSessionRequest(BaseModel)` |  |
| class | `class SessionResponse(BaseModel)` |  |
| class | `class UserMessageContent(BaseModel)` |  |
| class | `class UserMessageEvent(BaseModel)` |  |
| class | `class UserInterruptEvent(BaseModel)` |  |
| class | `class UserToolConfirmationEvent(BaseModel)` |  |
| class | `class UserCustomToolResultEvent(BaseModel)` |  |
| class | `class SendEventsRequest(BaseModel)` |  |
| class | `class StopReason(BaseModel)` |  |
| class | `class OutboundEvent(BaseModel)` | Base for all server-emitted events. |
| class | `class SessionStatusEvent(OutboundEvent)` |  |
| class | `class SessionErrorEvent(OutboundEvent)` |  |
| class | `class AgentMessageEvent(OutboundEvent)` |  |
| class | `class AgentThinkingEvent(OutboundEvent)` |  |
| class | `class AgentToolUseEvent(OutboundEvent)` |  |
| class | `class AgentToolResultEvent(OutboundEvent)` |  |
| class | `class AgentCustomToolUseEvent(OutboundEvent)` |  |

### `anthropic_compat/router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_anthropic_compat_router(stack, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, agent_registry)` | Build the ``/v1/sessions`` FastAPI router. |

### `anthropic_compat/session_manager.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SessionState` |  |
| class | `class SessionManager` | In-memory session registry. |

### `apps_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def discover_apps(roots)` |  |
| func | `def create_apps_router(app_roots, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `channels_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class LocalChannelManager` | Small channel manager for dashboard-only sessions. |
| func | `def create_channels_router(manager, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, state_path)` |  |

### `cli_team_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CliTeamRunRequest(BaseModel)` |  |
| func | `def create_cli_team_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build + return the router. ``app.include_router(create_cli_team_router())``. |

### `completion_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_completion_router(stack, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `computer_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_computer_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `computer_router_state.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ComputerRouterState` |  |

### `config_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ConfigRouter` | Bundle returned by ``create_config_router``. |
| func | `def create_config_router(stack, custom_models_path, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build the FastAPI router + state bundle. |

### `control_sessions_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ControlSessionBody(BaseModel)` |  |
| class | `class ControlSessionStateBody(BaseModel)` |  |
| class | `class ControlActionBody(BaseModel)` |  |
| class | `class ControlActionUpdateBody(BaseModel)` |  |
| class | `class ControlEvidenceBody(BaseModel)` |  |
| func | `def create_control_sessions_router(store, base_dir, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Create the unified ``/api/control-sessions/*`` router. |

### `cowork_group_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class GrantBody(BaseModel)` |  |
| class | `class InviteBody(BaseModel)` |  |
| class | `class ModeBody(BaseModel)` |  |
| class | `class BoardBody(BaseModel)` |  |
| class | `class AssignBody(BaseModel)` |  |
| class | `class CompleteBody(BaseModel)` |  |
| class | `class BreakoutBody(BaseModel)` |  |
| class | `class MergeBody(BaseModel)` |  |
| class | `class ReadBody(BaseModel)` |  |
| class | `class HeartbeatBody(BaseModel)` |  |
| class | `class LinkRoomBody(BaseModel)` |  |
| class | `class RoomMessageBody(BaseModel)` |  |
| class | `class EnsureRoomBody(BaseModel)` |  |
| class | `class CollabTaskBody(BaseModel)` |  |
| func | `def create_cowork_group_router(store, async_store, collaboration_store, room_message_store, team_rooms_state_path, team_tasks_state_path, team_rooms_router, team_tasks_router, runtime, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Create the ``/api/cowork/*`` thread-group router. |

### `cron_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_cron_router(jobs_path, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Create the ``/api/cron`` compatibility router. |

### `dag_debugger_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_dag_debugger_router(journal, planner)` |  |

### `debug_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_debug_router(store, stack, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `deep_research_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_deep_research_router(orchestrator, workspace_root, upload_root, agents_root, job_store_path, review_queue_path, prefetcher, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Create `/api/research/deep/*` endpoints. |

### `deployments_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_deployments_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `enterprise_assets_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_enterprise_assets_router(registry, runtime, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `evolution_ops_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_evolution_ops_router(journal, registry, planner, forged_skill_dir, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, jwt_leeway_seconds)` | Create evolution operator control-plane routes. |

### `evolution_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_evolution_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `fs_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_fs_router(thread_store, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, workspace_store, lease_store, mount_registry, group_store)` | Build the FastAPI router. State is per-request (the path parameter); auth, when an identity store is wired and ``require_auth`` is set, is e |

### `index_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_index_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `intelligence_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def run_enabled_subscriptions_once(store_path, search_fn, fetch_fn, remember_reports, include_disabled, due_only, max_subscriptions, max_results_per_query)` |  |
| func | `def create_intelligence_router(store_path, search_fn, fetch_fn, remember_reports, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `invariants_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_invariants_router(stack, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build the FastAPI router for the invariants catalog. |

### `journal_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_journal_router(db_path, default_jsonl_path, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Factory. |

### `local_brain.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def ollama_url()` |  |
| func | `def probe_ollama()` | List local Ollama models via ``/api/tags``; ``None`` when not running. |
| func | `def local_brain_status(ollama_probe, storage_probe, embed_info, index_db)` | Build the plain-language readiness checklist. All external lookups are injectable (defaults probe the real services). |

### `local_brain_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_local_brain_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build + return the router. Call site: ``app.include_router(create_local_brain_router())``. |

### `loop_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_loop_router(store, controller, dispatcher, task_supervisor, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `lsp_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_lsp_router(registry)` |  |

### `mcp_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class McpRouter` | Package the router with the state dicts callers need to introspect. Keeps the external ``app.include_router`` pattern while still giving app |
| func | `def create_mcp_router(registry, initial_mcp_servers, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build the MCP router. |

### `media_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class VideoIndexRequest(BaseModel)` |  |
| class | `class VideoWatchRequest(BaseModel)` |  |
| class | `class VideoSearchRequest(BaseModel)` |  |
| class | `class VideoFaceSearchRequest(BaseModel)` |  |
| class | `class VideoClassifyRequest(BaseModel)` |  |
| class | `class VideoSpeechSearchRequest(BaseModel)` |  |
| class | `class VideoImageSearchRequest(BaseModel)` |  |
| class | `class VideoOcrRequest(BaseModel)` |  |
| func | `def create_media_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `memory_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_memory_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `meta_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_meta_router(registry, tool_registry, mobile_skills_root, feedback_path, skill_library_dirs, include_default_skill_library, molili_config, oct_config, local_auth_config, identity_store, molili_jwt_secret, jwt_issuer, jwt_audience, require_auth)` | Build the FastAPI router. |

### `meta_skill_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_meta_skill_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build a FastAPI router over the MetaSkill catalog. |

### `metrics_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_metrics_router(registry)` | Build the FastAPI router exposing process metrics. |

### `openai_formatting.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def chat_completion_envelope(reply, model, actor, agent, extra)` | Wrap a plain assistant reply string in the OpenAI-compat ``chat.completion`` response shape. |

### `openai_gateway/mix.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def is_mix_model(model)` | True if ``model`` selects the Mix virtual model. |
| func | `def mix_model_ids()` | Virtual-model ids to advertise on /v1/models. |
| func | `def load_mix_config()` | User-configured Mix preset (proposer pool / aggregator / count). |
| func | `def save_mix_config(cfg)` | Validate + persist the Mix preset; returns the cleaned config. |
| func | `def run_mix_chat(stack, intent, requested_model, default_arm, actor, agent, run_chat, optimizer)` | Answer ``intent`` via mixture-of-agents and return a chat.completion. |
| func | `def mix_sse_frames(result, model)` | Wrap a finished Mix completion as OpenAI-standard streaming SSE. |

### `openai_gateway/synthesis.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def synthesize_reply(stack, goal, trajectory, model, agent, conversation_messages, profile_memories, user_context, usage_out)` |  |

### `openai_gateway_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_openai_router(stack, default_arm, reflex_router, prompt_optimizer, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, jwt_leeway_seconds, agent_registry, max_concurrent_completions_per_actor, max_completions_per_minute_per_actor)` |  |

### `org_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_org_router(org_store, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, audit_chain_path, audit_chain_secret)` |  |

### `organizations_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_organizations_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, agent_registry)` |  |

### `parallel_agents_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_parallel_agents_router(orchestrator, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `plugin_hub_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_plugin_hub_router(hub, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Create a FastAPI router with PluginHub management endpoints. |

### `plugins_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def is_public_plugin_asset_request(method, path)` |  |
| func | `def create_plugins_router(plugin_roots, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, approval_policy_path, promotion_audit_path, publisher_trust_store_path, plugin_registry_path)` |  |

### `projects_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class PlanBody(BaseModel)` |  |
| class | `class MoveThreadBody(BaseModel)` |  |
| class | `class RunBody(BaseModel)` |  |
| class | `class RecoverBody(BaseModel)` |  |
| class | `class TaskInterventionBody(BaseModel)` |  |
| class | `class FromGroupBody(BaseModel)` |  |
| func | `def create_projects_router(store, group_store, collaboration_store, thread_store, model_router, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Create the ``/api/projects/*`` router. |

### `prompts_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_prompts_router(registry, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Factory. Bind a router to a specific ``PromptRegistry`` instance. |

### `realtime_approval.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class GatewayApprovalProvider(ApprovalProvider)` | Blocking provider that delegates to a running asyncio gateway. |

### `realtime_cerebrum.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CerebrumRuntime` | Realtime runtime backed by the project's ReAct planner. |

### `realtime_echo.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class EchoRuntime` | Single-process runtime with file-backed event logs. |

### `realtime_gateway.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RealtimeGateway` | Mountable FastAPI router exposing a single WebSocket endpoint. |

### `realtime_local_partner.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def agent_is_local_partner(agent)` | True when ``agent`` should be driven by spawning its registered coding-agent CLI directly rather than the LLM loop. |
| func | `async def drive_local_partner(runtime, turn, log, emitter, intent, agent, provider, text)` | Dispatch the turn to the agent's external coding-agent CLI (``claude -p`` / ``codex exec``). The CLI's answer comes back as one plain agentM |

### `realtime_react_policy.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def agentic_stream_event_to_react_event(kind, delta, final)` | Translate native tool-loop tuple events into realtime bridge events. |
| func | `def should_use_native_tool_loop(stack, intent, planning_mode)` | Return whether a turn should use protocol-native tool calls first. |

### `realtime_thread_ops.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `async def compact_thread(runtime, thread_id, emitter)` | Manually compact a thread using the same durable event-log path as automatic compaction. |

### `realtime_turn_routing.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def looks_like_plain_chat(goal)` | Return true for turns that are safe to answer without tools. |
| func | `def looks_like_tool_intent(goal)` | Return true when a turn should enter tool-capable execution. |
| func | `def looks_like_contextual_tool_followup(goal, conversation_messages)` | Detect short follow-ups that confirm a prior tool/research offer. |
| func | `def local_non_tool_reply(goal)` | Last-resort reply when no model router exists for simple chat. |

### `realtime_turn_support.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def turn_has_observable_output(turn)` | Return true once the runtime produced visible output beyond input. |
| func | `def inject_cowork_turn_plan(runtime, thread_id, text, intent)` | Attach cowork planning and context-grant diagnostics to an intent. |
| func | `async def record_pending_resume_intent(runtime, thread_id, resume_intent)` |  |
| func | `async def consume_confirmed_resume_intent(runtime, thread_id, text)` |  |

### `registry_consumer_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_registry_consumer_router(skill_registry, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, registry_base, skills_root, plugin_root, publisher_trust_store_path)` |  |

### `remote_backends_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_remote_backends_router(store_path, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Factory. ``store_path`` defaults to ``<data>/remote_backends.json``; tests pass a tmp path. |

### `remote_transport.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SshTunnel` | SSH transport descriptor. Mirrors ``SshBackend`` config so an existing SSH-trusted host can be reused without re-entering credentials. |
| class | `class RemoteBackend` | One named remote octopus-agent runtime. |
| class | `class BackendRegistry` | Process-wide cache of registered remote backends, persisted to ``<data>/remote_backends.json``. |
| func | `def health_check(backend, timeout_seconds, http_client)` | Hit ``<url>/api/health`` and return (status, detail). |
| func | `def proxy_request(backend, method, path, json, timeout_seconds, http_client)` | Forward a request to a remote backend. |
| func | `async def proxy_websocket(backend, client_ws, path, upstream_factory)` | Bidirectionally relay a WebSocket session to the remote backend's realtime gateway. |

### `retrieve_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RankRequest(BaseModel)` |  |
| func | `def create_retrieve_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build the router. ``app.include_router(create_retrieve_router())``. |

### `searxng_supervisor.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def searxng_status()` | Snapshot for a status endpoint / UI light. Heartbeat-cached when running, else probes once. ``docker_present`` is a cheap PATH check (no dae |
| func | `def enable_searxng()` | One-click deploy of a local SearXNG. Returns immediately with a status (``docker_missing`` / ``docker_not_running`` / ``already_running`` /  |
| func | `def disable_searxng()` | Stop the managed container (kept, not removed, so re-enable is instant) and release ``SEARXNG_URL`` if we set it (never clobbers an external |
| func | `def maybe_start_searxng()` | Boot-time autostart (opt-in via ``OCTOPUS_SEARXNG_AUTOSTART``). Conservative: if ``SEARXNG_URL`` is already set (external instance), defers  |
| func | `def start_searxng_heartbeat()` | Start the supervision heartbeat once (idempotent, daemon thread). No-op unless we manage a local container — an external SearXNG is observed |

### `skill_market_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_skill_market_router(skill_market, skills_dir, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `slash_command_expansion.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def maybe_expand_slash_command(goal)` | Expand a leading ``/<name>`` command into its configured template. |

### `storage_proxy_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_storage_proxy_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, http_client)` |  |

### `storage_supervisor.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def resolve_storage_command()` | Resolve the argv that launches ``octopus-storage serve``, or ``None`` if it can't be found. Priority: ``OCTOPUS_STORAGE_CMD`` (explicit) → t |
| func | `def storage_status()` | Snapshot of storage liveness for a status endpoint / UI light. Returns the heartbeat-cached value when the heartbeat is running; otherwise p |
| func | `def maybe_start_storage()` | Co-launch storage when opt-in + not already up + resolvable. Returns a status: ``disabled`` / ``already_running`` / ``not_found`` / ``starte |
| func | `def start_storage_heartbeat()` | Start the ongoing supervision heartbeat once (idempotent, daemon thread). |
| func | `def stop_storage()` | Terminate the co-launched child (if we started one). Idempotent. |

### `streaming_journal.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class StreamingJournal(Journal)` |  |

### `stub_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_stub_router(enabled, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `subagents_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class SubagentDispatchRequest(BaseModel)` |  |
| func | `def create_subagents_router(registry, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `system_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_system_router(project_root, user_home, identity_store, memory_reset_callback, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `task_runs_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TaskApprovalDecisionRequest(BaseModel)` |  |
| class | `class TaskTakeoverRequest(BaseModel)` |  |
| func | `def create_task_runs_router(supervisor, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `teach_repeat_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class StartRecordingRequest(BaseModel)` |  |
| class | `class StopRecordingRequest(BaseModel)` |  |
| class | `class TemplateUpdateRequest(BaseModel)` |  |
| func | `def create_teach_repeat_router(journal, registry, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `team_role_models_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class RoleModelsBody(BaseModel)` |  |
| func | `def create_team_role_models_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build + return the router. |

### `team_rooms_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TeamMemberWire(BaseModel)` |  |
| class | `class TeamParticipantWire(BaseModel)` |  |
| class | `class TeamRoomWire(BaseModel)` |  |
| class | `class CreateTeamRoomRequest(BaseModel)` |  |
| class | `class JoinInviteRequest(BaseModel)` |  |
| class | `class CreateTeamInviteRequest(BaseModel)` |  |
| class | `class UpdateTeamParticipantRequest(BaseModel)` |  |
| class | `class UpdateSpeakerPolicyRequest(BaseModel)` |  |
| class | `class UpdateDelegationRequest(BaseModel)` |  |
| func | `def create_team_rooms_router(state_path, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, reset_callback, room_message_store, room_projection, room_delete_projection, room_message_projection, room_message_provider, twin_responder)` | Create `/api/teams/*` routes. |

### `team_rooms_ws.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class TeamRoomWsContext` | The room store, lock, live-socket registry, and the router's broadcast/persistence/auth helpers — everything the WS handler needs to operate |
| func | `async def team_room_ws(ctx, ws, team_id)` | Realtime Team Room presence and lightweight event broadcast. |

### `team_speaker_policy.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def apply_floor_request(team, participant_id)` | Queue a raised hand for the moderator (``moderated`` policy only). None when there's nothing to do — no room, wrong policy, or the hand is a |
| func | `def apply_floor_yield(team, participant_id)` | Release the floor ``participant_id`` holds: round_robin advances to the next seat, the other turn modes re-open the floor. None when the cal |
| func | `def apply_floor_grant(team, actor_participant, target)` | Moderator hands the floor to ``target`` (None re-opens it). roll_call + moderated only. None when the policy doesn't apply OR the caller isn |
| func | `def advance_round_robin(team, participant_id)` | Hand the round_robin floor to the next eligible speaker after ``participant_id`` — called once a message lands. |

### `team_tasks_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_team_tasks_router(state_path, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience, reset_callback, team_event_broadcaster, task_projection, task_delete_projection, runner_factory, room_membership_resolver, max_concurrent_runs)` | Create ``/api/team-tasks/*`` routes. |

### `tentacle_join_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_tentacle_join_router(ws_port, auth_token)` | Build the router. ``ws_port``/``auth_token`` come from the coordinator the main app started. |

### `terminal_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class ShellSession` | One persistent shell process bound to a session_id. |
| func | `def get_session(session_id, cwd)` |  |
| func | `async def kill_session(session_id)` |  |
| func | `async def reap_sessions(exclude_id)` | Drop dead/idle terminal sessions to bound ``_sessions`` growth. |
| func | `def mount_terminal_routes(app, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Attach /api/terminal/ws/{session_id} to a FastAPI app. |

### `thread_state_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_thread_state_router(store, logs_root, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `turn_session.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def build_turn_metadata(thread_id, body, store)` | Merge per-turn context with persisted thread metadata. |
| func | `def build_turn_session(actor, agent, thread_id, body, store)` | Assemble the per-turn ``Session`` object from request and state. |

### `uploads_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_uploads_router(thread_store, workspace_root, legacy_upload_root, upload_root, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build the FastAPI router. |

### `verify_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_verify_router(identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |

### `wiki_generic.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def wiki_dir(root)` |  |
| func | `def status(root)` | Cheap check used by the frontend to decide between "show generate CTA" vs "load docs". |
| func | `def list_docs(root)` | Flat listing the WikiPanel renders into a tree. |
| func | `def read_doc(root, rel)` | Read a doc, with traversal protection. |
| func | `def generate(root)` | Walk, summarize, write. Returns a manifest dict. |
| func | `def get_settings(root)` | Return the autosync flag etc. · safe defaults when file missing. |
| func | `def set_settings(root, autosync)` | Persist per-project wiki settings. |
| func | `def watcher_set(root, on)` | Idempotent · True if the desired state is now active. |
| func | `def watcher_status(root)` |  |
| func | `def boot_existing_watchers(search_dirs)` | Scan a list of candidate workspace dirs at backend startup · re-arm watchers for any whose ``settings.json`` has ``autosync=true``. |

### `wiki_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_wiki_router(model_router, model, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Build + return the FastAPI router. Call site: ``app.include_router(create_wiki_router(model_router=..., model=...))``. |

### `workspace_api_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| class | `class CreateWorkspaceBody(BaseModel)` |  |
| class | `class AddMemberBody(BaseModel)` |  |
| class | `class AcquireLeaseBody(BaseModel)` |  |
| class | `class RenewLeaseBody(BaseModel)` |  |
| func | `def create_workspace_api_router(workspace_store, lease_store, registry, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` | Create the ``/api/workspaces/*`` router for the Workspace entity. |
| func | `def register_workspace_api_router(app, **kwargs)` | Build the router and attach it to ``app``. |

### `workspaces_router.py`

| Kind | Symbol | Doc |
| --- | --- | --- |
| func | `def create_workspaces_router(workspace_root, thread_store, identity_store, require_auth, jwt_secret, jwt_issuer, jwt_audience)` |  |


## Who imports this

**14** file(s) reference this package:

- **`runtime/_cli_commands.py/`** · 1 file(s)
  - `runtime/_cli_commands.py`
- **`runtime/cli_serve.py/`** · 1 file(s)
  - `runtime/cli_serve.py`
- **`runtime/platform/`** · 12 file(s)
  - `runtime/platform/ui/_app_agents.py`
  - `runtime/platform/ui/_app_collab.py`
  - `runtime/platform/ui/_app_health.py`
  - `runtime/platform/ui/_app_meta.py`
  - `runtime/platform/ui/_app_parallel.py`
  - _… and 7 more_

