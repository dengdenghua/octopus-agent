---
name: octopus-agent-subagent-model-routing
description: How sub-agent model selection flows; ephemeral runner is the only live path; stub-runner tests give false confidence
metadata: 
  node_type: memory
  type: project
  originSessionId: ced61573-455f-4325-acb5-c4cddc8dfce2
  modified: 2026-08-12T03:50:13.374Z
---

Sub-agent (delegation) model selection in octopus-agent:

- The per-dispatch model flows as `context["model_name"]`. The bridge
  (`runtime/execution/subagents/bridge.py` `_dispatch`) sets it from: explicit
  caller `context={"model_name": ...}`, a registered definition's `.model`, OR
  `use_cheap_model` (injects the resolved cheap default). It then passes context
  into `run_ephemeral_role` / `run_ephemeral_definition` →
  `EphemeralCall.context`.
- The model string is the routing lever: `ModelDispatchRouter._resolve(request.model)`
  (`runtime/sensing/model_router/dispatch_router.py`) picks the provider/router/host
  from `request.model` (exact, then `provider/` prefix, then fallback). So changing
  `ModelRequest.model` is what reaches a different backend host.
- **The ephemeral runner is the ONLY live sub-agent runner in prod.** The
  non-ephemeral `_RUNNER` path (`set_sub_agent_runner`) is installed only in tests —
  no production call site sets it, so `_RUNNER` stays None and that branch returns
  "runner not configured". `make_llm_ephemeral_runner` (wired in
  `runtime/platform/ui/app.py` with `default_model = stack.planner.planner_model`)
  is what actually runs `reviewer`/`researcher`/registry-defined sub-agents.

**Testing pitfall (extends [[octopus-agent-audit-verification-lesson]]):** the
cheap-routing tests in `tests/test_subagent_cheap_routing.py` STUB the ephemeral
runner and only assert the bridge *injected* `context["model_name"]` — they do NOT
prove the real runner *uses* it. A bug where the runner ignored the override
(2026-06: fixed via `_select_call_model` in `ephemeral_runner.py`) passed every
one of those tests for both explicit override and `use_cheap_model`.
**How to apply:** to verify sub-agent model routing, assert on
`router.call_log[0].model` with the REAL `make_llm_ephemeral_runner` wired (see
`TestModelOverride` / `TestDispatchModelOverrideEndToEnd` in
`tests/test_ephemeral_runner.py`), or use the live network-host check
(`lsof -nP -iTCP -a -p <pid> -sTCP:ESTABLISHED` → which `:443` host). LLM
self-identity is unreliable. Related: [[octopus-agent-multiagent-gap]].

**New root cause (2026-08-12, df896661):** research-style sub-agents were 404ing
0.2–0.3s every call with Volcengine "agent plan" error. Chain: `_coerce_parallel_specs`
auto-cheaps `researcher`/`explorer`/`reviewer` → `_resolve_cheap_subagent_model()`
returned hard-coded `glm-4-flash` → no such entry in custom_models.json → dispatch
fell back to `build_fallback_router_from_custom_models(planner_model=kimi-k3)` which
selects the kimi-k3 entry → base_url `ark.cn-beijing.volces.com/api/plan/v3` (a
single-model Agent-Plan endpoint) → any model id outside its allowlist 404s.
**This is NOT the "kimi key 欠费/未激活" story from [[kimi-k3-volcengine-agent-plan]] —
it is a fallback-endpoint-selection trap:** configuring a Volcengine Agent-Plan
endpoint in custom_models.json makes it the fallback target for EVERY unknown model,
so cheap subagents (glm-4-flash) died system-wide. Fix: `_resolve_cheap_subagent_model`
now, when env/config unset, picks the first OpenAI-compatible custom entry that has a
base_url and is NOT an Agent-Plan endpoint (`_is_agent_plan_endpoint` excludes
`/plan/`/`/api/plan`/`agent-plan`). **Cheapness is an EXPLICIT operator
declaration, not a heuristic (2026-08-12, uncommitted):** `_resolve_cheap_custom_model`
only accepts entries with `"tier": "cheap"` in custom_models.json. The previous
pick was the alphabetically-first OpenAI-compatible entry — the system had NO real
price signal (usage_pricing.price() only knows 8 official OpenAI/Anthropic models;
classify_model_tier() is a name-substring heuristic used only for code-smell guards).
Dictionary order could have routed cheap subagents onto an expensive "a"-prefixed
model. agnes-2.5-flash now carries `"tier": "cheap"` (it's genuinely free — the
display_name always said "(免费)"). On dangbei's box that resolves to
`agnes-2.5-flash`. **The hard-coded `glm-4-flash` last resort was REMOVED
(2026-08-12, uncommitted):** `_resolve_cheap_subagent_model` now returns `None`
when env/config/custom_models all resolve to nothing, the bridge's `if cheap:`
skips injection, and `_select_call_model` in `ephemeral_runner.py` falls back to
`default_model = stack.planner.planner_model` — the planner/main model. A model id
the operator never declared would only 404, so none is invented. Real-runner proof:
`TestDispatchModelOverrideEndToEnd::test_cheap_with_no_resolvable_model_falls_back_to_planner`
asserts `call_log[0].model == planner-default` with env unset + custom_models patched
to None. Tier-gate regression: `test_resolve_ignores_openai_model_without_tier_declaration`
(red on pre-tier code). Related frontend false-positive fixed in fdf7df2b:
`REPORT_DELIVERABLE_PATTERN` `/research/i` matched `"researcher"` inside
run_orchestration input → pet error on completed turns; now word-bounded
(`/\b(?:report|docx|pptx|pdf|research|swarm)\b|deep[-_]research/i`).

**Three-tier cost tags land (2026-08-12, uncommitted):** `custom_models.json`
entries now carry an explicit `tier` tag on a `performance / balanced / economy`
scale (user's call, mirroring Trae-style multiplier tiers). Both routing lanes
consume it:
- `_resolve_cheap_subagent_model` → `_resolve_cheap_custom_model` accepts ONLY
  `economy` (legacy `cheap` accepted) — a `balanced`/`performance` tag is NOT a
  cheap candidate; no economy entry → None → planner-model fallback.
- `turn_complexity._auto_derive_tier_from_custom_models` is tagged-first:
  performance→`performance`-tagged entries (`models[-1]` slot), value/local→
  `economy`-tagged entries strictly preferred (`models[0]` slot), falling back
  to `balanced` only when no economy exists (a balanced model must NOT steal the
  cheap slot from a declared-economy one). Untagged catalogs still use the
  legacy position heuristic (first=cheap, last=strongest).
- dangbei's `data/custom_models.json`: agnes-2.5-flash=economy (free),
  kimi-k3/ark-code-latest=performance, deepseek-v4-flash/gpt-5.6-luna=balanced.
  Smoke: cheap→agnes, value/local→agnes, performance→ark-code-latest.
- **performance→ark-code-latest is intentional, not a bug:** `select_model_for_complexity`
  (turn_complexity.py) only rewrites `request.model` when `user_model` is a
  sentinel (`auto`/`octopus-agent`/empty); a pinned model (kimi-k3) returns
  None untouched. So the performance pick only affects auto-mode complex
  requests, and ark-code-latest is itself Volcengine's "Auto 路由" (auto
  semantics) — the right performance-slot citizen. `is_smart_routing_enabled`
  defaults ON unless env/config says otherwise.


