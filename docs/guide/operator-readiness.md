# Operator Readiness Guide

This guide is the stable handoff page for running Octopus as a coding and
governed agent workspace. It ties the day-to-day operator loop to the runtime
surfaces that must stay documented: code mode, permissions, replay gates, and
plugins.

## Code Mode

Code mode should follow a small, repeatable loop:

1. Inspect the repository state before editing.
2. Edit the smallest set of files needed for the request.
3. Verify with targeted tests, linters, or runtime probes.
4. Report the exact checks that passed or failed.

The main runtime path is:

- `runtime/core/cerebrum/react_loop.py` plans and resumes coding turns.
- `runtime/execution/tool_engine/executor.py` executes tools.
- `runtime/sensing/gateway/realtime_turn_outcome.py` records outcomes.
- `runtime/safety/evolution/auto_verifier_metrics.py` tracks verifier quality.

Operator signal:

- The operator panel should show recent task runs, process timelines, replay
  gate state, auto-verifier drift, and scorecard gaps.
- Repeated verifier failures should become repair-route backlog items instead
  of being hidden in logs.

## Permissions

Permissions are the contract between autonomy and local safety. A high-quality
run must make approval, sandbox, and override state visible.

Core expectations:

- Tool calls pass through trust, path, approval, and sandbox checks.
- Risky actions require approval or an explicit operator override.
- Overrides need a reason and should be written to governance audit records.
- Policy review proposals should be replay-backed before becoming rules.

Relevant implementation paths:

- `runtime/safety/hooks/tool_edge_hooks.py`
- `runtime/safety/audit/trust_gateway.py`
- `runtime/safety/evolution/policy_review_rules.py`
- `runtime/sensing/gateway/agent_trace_router.py`

## Replay Gates

Replay gates keep promotion from becoming guesswork. A memory, policy, or
evolution change should cite evidence that can be inspected later.

Promotion readiness should answer:

- Which replay case supports the change?
- Did the replay gate pass?
- Was an override used?
- Which audit entry records the decision?

Operator surfaces:

- `/api/agent-trace/replay-gate`
- `/api/agent-trace/review-queue/promotions/apply`
- `/api/agent-trace/review-queue/promotions/audit/summary`
- `/api/evolution/agent-scorecard`

## Plugins

Plugins extend the runtime, so plugin maturity depends on smoke checks,
permission review, and hook governance.

Minimum plugin readiness:

- A plugin exposes at least one useful capability.
- Local smoke checks pass or produce a clear review-required reason.
- Permission review happens before high-risk plugin actions.
- Lifecycle hook behavior is auditable like ordinary tool hooks.

Operator surfaces:

- `/api/plugins`
- `/api/plugins/smoke-summary`
- `/api/plugin-hub/plugins`
- The operator panel `Plugin health` card

## Release Checklist

Before raising the ecosystem maturity score, confirm:

- Code mode has an inspect/edit/verify loop with a visible process timeline.
- Permission and sandbox outcomes are visible in the operator panel.
- Replay gate failures block promotion unless a reasoned override is recorded.
- Plugin smoke summary is green or has explicit review-required rows.
- The competitor scorecard shows the relevant evidence checklist.
