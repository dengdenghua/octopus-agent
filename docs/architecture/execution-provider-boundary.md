# Execution Provider Boundary

Octopus owns the durable control plane: conversation, identity, projects,
permissions, approvals, memory, evidence, recovery and evolution. An
execution provider owns only the inner model/tool loop. The user-facing
workspace therefore has product modes (for example, 通用 and 设计), not a
visible Codex/Native engine switch.

## Contract

Every provider must project the same lifecycle events through
`_record_react_trace_event`:

- one `turn_id` and one ordered event stream;
- tool start/end pairs with a stable call id;
- terminal status and an explicit outcome reason;
- file changes and verification evidence;
- tenant and owner scope from the authenticated session;
- provider/engine metadata on every trace event.

Codex App Server notifications already cross the anti-corruption adapter in
`runtime/execution/codex_backend/events.py`; Native ReAct uses the same bridge.
The bridge now tags both streams with `engine` and the effective model so
evaluation and replay do not infer execution from UI state.

## Learning boundary

Provider-specific loops must not own the only self-evolution hook. Native and
Codex terminal turns use the same coarse score writer in
`runtime/sensing/gateway/_tool_bridge_scoring.py`. The writer is idempotent by
`turn_id`, preserves the authenticated tenant scope, and runs the existing
zero-cost regression tick. Fine-grained skill promotion should consume the
same durable trace stream once Codex tool receipts are available to the
journal adapter.

## Routing policy

- Codex is the default provider for code and complex tool work.
- Native Lite remains for local/offline or domestic-model execution, device
  control, deterministic workflows, and fail-closed fallback before a write
  side effect.
- Shadow comparison is read-only and never runs two mutating providers against
  the same workspace concurrently.
- A provider failure after a side effect is terminal until the effect ledger
  proves an idempotent continuation; it must not silently switch engines.

## Removal gates

The full Native loop can only be reduced after both providers produce complete
traces, verification/repair is provider-neutral, Codex traces enter scoring and
skill promotion, and representative code/design/research/desktop scenarios
pass two release cycles with a rollback route. Until then, Native Lite is a
deliberate execution adapter and experiment surface, not a second product.
