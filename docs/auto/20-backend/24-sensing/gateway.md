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
| `account_usage_router.py` | — |
| `agent_market_sources/financial-services/agent-plugins/model-builder/skills/dcf-model/scripts/validate_dcf.py` | DCF Model Validation Script Validates Excel DCF models for formula errors and common DCF mistakes |
| `agent_market_sources/financial-services/agent-plugins/pitch-agent/skills/dcf-model/scripts/validate_dcf.py` | DCF Model Validation Script Validates Excel DCF models for formula errors and common DCF mistakes |
| `agent_market_sources/financial-services/agent-plugins/pitch-agent/skills/ib-check-deck/scripts/extract_numbers.py` | Extract numerical values from presentation content for consistency checking. |
| `agent_modes_router.py` | Agent project/code mode detection endpoints. |
| `agent_trace_router.py` | Read-only API for the durable agent trace store. |
| `agent_world_router.py` | Agent Market router · local agent marketplace. |
| `agents_local_partner.py` | LocalPartner subsystem — detection + secure registration. |
| `agents_models.py` | Pydantic wire models for ``agents_router``. |
| `agents_router.py` | — |
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
| `computer_router.py` | Computer automation API. |
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
| `openai_gateway/tool_converter.py` | — |
| `openai_gateway_router.py` | — |
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
| `realtime_gateway.py` | Realtime gateway — JSON-RPC 2.0 over WebSocket. |
| `realtime_local_partner.py` | Direct execution of LocalPartner agents on the realtime path. |
| `realtime_react_stream.py` | Single-agent stream drivers for the realtime runtime. |
| `realtime_team_stream.py` | Multi-agent team-topology stream driver for the realtime runtime. |
| `realtime_thread_history.py` | Realtime turn ↔ legacy conversation history adapters. |
| `realtime_thread_ops.py` | Thread maintenance operations for the realtime runtime. |
| `realtime_turn_input.py` | Turn-input shaping for the realtime runtime. |
| `realtime_turn_lifecycle.py` | Turn lifecycle orchestration for the realtime runtime. |
| `realtime_turn_outcome.py` | Turn outcome inspection for the realtime runtime. |
| `realtime_turn_routing.py` | Turn-routing helpers for the realtime runtime. |
| `realtime_workbench.py` | Workbench snapshot + workspace-focus helpers for the realtime runtime. |
| `registry_consumer_router.py` | 资产 Registry 消费路由(母体接 registry · 只读浏览 + 安装 prompt-skill)。 |
| `remote_backends_router.py` | Remote backends router · ``/api/remote-backends/*``. |
| `remote_transport.py` | Remote Transport · connect a desktop session to a remote octopus-agent runtime over SSH-tunneled HTTP. |
| `retrieve_router.py` | Retrieval router · ``/api/retrieve/rank``. |
| `searxng_supervisor.py` | One-click local SearXNG for the private web-search backend. |
| `skill_market_router.py` | — |
| `slash_command_expansion.py` | Slash-command expansion for realtime chat input. |
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
| `workspaces_router.py` | Workspace manifest API. |

## Who imports this

**7** file(s) reference this package:

- **`runtime/cli.py/`** · 1 file(s)
  - `runtime/cli.py`
- **`runtime/cli_serve.py/`** · 1 file(s)
  - `runtime/cli_serve.py`
- **`runtime/platform/`** · 5 file(s)
  - `runtime/platform/ui/app.py`
  - `runtime/platform/ui/health_router.py`
  - `runtime/platform/ui/searxng_router.py`
  - `runtime/platform/ui/state.py`
  - `runtime/platform/ui/thread_routes.py`

