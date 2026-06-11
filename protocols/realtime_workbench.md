# Realtime Workbench Snapshot Protocol

This document defines how the realtime runtime publishes the workbench's
current frame. The goal is simple: the right-side workbench renders the
latest meaningful state, while replay and refresh recover the same state
without rebuilding it from historical tool rows.

## Events

### `turn/plan/updated`

Backward-compatible phase update.

Payload:

- `threadId`: thread id
- `turnId`: turn id
- `phases`: server-authored phase list
- `workspaceFocus`: optional focus target
- `workbenchSnapshot`: optional `WorkbenchSnapshotV2`

Clients that only understand phases can keep using `phases` and
`workspaceFocus`. New clients should prefer `workbenchSnapshot` when it is
present.

### `workbench/snapshot`

First-class current-frame update.

Payload:

- `threadId`: thread id
- `turnId`: turn id
- `snapshot`: `WorkbenchSnapshotV2`

This event is not a high-frequency token stream. It should be reduced
immediately instead of being coalesced with message deltas.

## `WorkbenchSnapshotV2`

Fields:

- `schemaVersion`: always `2`
- `version`: monotonic per turn, incremented by the runtime
- `status`: `pending | running | done | error | waiting_approval`
- `phases`: server-authored phase snapshots
- `currentPhaseId`: phase that should be highlighted
- `currentItemId`: item/tool that should be shown as the current frame
- `workspaceFocus`: optional view hint for terminal/diff/file/subagent/etc.
- `updatedAt`: server timestamp

## Invariants

1. `workbench/snapshot.snapshot` and
   `turn/plan/updated.workbenchSnapshot` use the same schema.
2. `thread/resume` returns the last durable `Turn.workbenchSnapshot`.
3. The UI must prefer `workbenchSnapshot` for current phase and current
   frame selection; local derivation is only a fallback for old logs.
4. When a successful turn has no running background tools, the runtime
   emits a terminal snapshot where active phases are marked `done`.
5. Historical tool rows may remain available for replay, but the desktop
   workbench view must render the current frame, not a stacked history.

