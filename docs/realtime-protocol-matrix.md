# Realtime Protocol Matrix

This matrix is the working contract for `/api/realtime`.

## Active notifications

These server notifications are expected to be reduced by
`frontend/src/core/realtime/reducer.ts`.

| Method | Frontend handling |
| --- | --- |
| `thread/started` | resume state |
| `thread/status/changed` | accepted no-op placeholder |
| `thread/tokenUsage/updated` | token usage state |
| `turn/started` | turn insert/update |
| `turn/completed` | authoritative turn snapshot |
| `turn/diff/updated` | accepted no-op placeholder |
| `item/started` | item insert/update |
| `item/completed` | authoritative item snapshot |
| `item/agentMessage/delta` | append agent text |
| `item/reasoning/textDelta` | append reasoning text |
| `item/commandExecution/outputDelta` | append command output |
| `item/fileChange/hunkDecision` | update hunk decision |
| `error` | transient error item |

## Reserved notifications

These method names are part of the protocol vocabulary but are not
currently emitted. Emitting any of them should land in the same change as
frontend reducer, rendering, and tests.

| Method | Intended unlock |
| --- | --- |
| `turn/plan/updated` | first-class turn plan state |
| `item/plan/delta` | streaming plan item |
| `item/fileChange/outputDelta` | streaming file edit output |
| `item/fileChange/hunkDelta` | streaming per-hunk diff UI |
| `item/mcpToolCall/progress` | long-running MCP progress |
| `model/rerouted` | visible model fallback/routing trace |

## Server-initiated requests

These ride over JSON-RPC request/response and should either create or be
mirrored by an `approval` item when durable replay is needed.

| Method |
| --- |
| `item/commandExecution/requestApproval` |
| `item/fileChange/requestApproval` |
| `item/permissions/requestApproval` |
| `item/tool/requestUserInput` |
| `mcpServer/elicitation/request` |
| `item/planMode/exitRequest` |

## First-class control items

The protocol now has frontend/backend type support and basic rendering for
these items, even though not every producer emits them yet.

| Item type | Purpose |
| --- | --- |
| `subagent` | delegated agent lifecycle without magic MCP markers |
| `approval` | replayable human-in-the-loop decision state |
| `verification` | coding validation command/result |
| `artifact` | generated file with preview/render/validation state |

The regression guard lives in `tests/test_realtime_protocol_contract.py`.
