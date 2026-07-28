// Client-side replay of the persisted per-thread event log.
//
// The server rebuilds thread state from an append-only JSONL log
// (``runtime/memory/threads/event_log.py``); this module gives the client
// the same capability. It does NOT re-implement replay semantics — it
// translates each persisted ``LoggedEvent`` into the notification shapes
// the realtime reducer already understands and folds them through
// ``reduce()``, so the live path and the replay path can never diverge in
// state-construction logic.
//
// Translation table (persisted kind → reducer method):
//
//   thread_started   → thread/started
//   turn_started     → turn/started          (synthesizes an inProgress Turn)
//   turn_completed   → turn/finalized        (status/completedAt/error only)
//   turn_updated     → turn/grounding and/or turn/plan/updated (per field)
//   turn_compacted   → turn/compacted
//   item_started     → item/started
//   item_completed   → item/completed
//   item_delta       → per payload.kind:
//       agentMessage    → item/agentMessage/delta
//       reasoning       → item/reasoning/textDelta
//       plan            → item/plan/delta
//       commandOutput   → item/commandExecution/outputDelta
//       fileChangeHunk  → item/fileChange/hunkDelta
//       mcpToolProgress → item/mcpToolCall/progress
//       (unknown kinds are dropped, mirroring the Python "ignored" policy)
//
// Semantic anchors on the Python side: ``_apply_event``, ``_merge_delta``,
// ``_apply_turn_update`` in ``runtime/memory/threads/event_log.py``. Keep
// this module aligned with them — the golden conformance test
// (``__fixtures__/replay-golden.*``) fails when either side drifts.

import {
  emptyConversation,
  type Conversation,
  type FileHunk,
  type GroundingSource,
  type Item,
  type McpToolProgress,
  type Turn,
  type TurnStatus,
} from "./items";
import {
  materializeStreamedItems,
  reduce,
  type ConversationEvent,
  type ReducerDiagnosticHandler,
} from "./reducer";

/** Wire shape of one persisted log line (camelCase preserved by Pydantic
 * alias settings server-side). Intentionally loose — the Python schema is
 * forward-compatible and new fields must not break older readers. */
export interface LoggedEvent {
  event: string;
  eventId?: string | null;
  threadId: string;
  ts?: string | null;
  turnId?: string | null;
  payload?: Record<string, unknown>;
}

/** A ``LoggedEvent`` carrying its one-based physical log cursor, as
 * returned by ``thread/events`` (or a locally cached copy of it). */
export interface SequencedLoggedEvent extends LoggedEvent {
  sequence: number;
}

export interface ReplayOptions {
  /** Thread id for the base state when ``base`` is omitted. Defaults to the
   * first event's ``threadId``. */
  threadId?: string;
  /** Start from an existing conversation (incremental replay after a
   * cursor). Defaults to an empty conversation. */
  base?: Conversation;
  onDiagnostic?: ReducerDiagnosticHandler;
}

export interface ReplayResult {
  conversation: Conversation;
  /** Highest sequence consumed (0 when no sequenced events were given). */
  cursor: number;
  /** Events that produced at least one reducer event. */
  replayed: number;
  /** Persisted events skipped as no-ops (unknown kinds, unknown delta
   * kinds) — forward compatibility, not an error. */
  skipped: number;
}

// ── Field decoders ────────────────────────────────────────────
//
// The payload is opaque JSON; each decoder validates exactly what the
// Python replay validates and tolerates everything else by dropping it.

function asRecord(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** Python: ``TurnStatus[status_str.upper()]`` with KeyError → COMPLETED. */
function decodeTurnStatus(raw: unknown): TurnStatus {
  switch (String(raw ?? "completed").toLowerCase()) {
    case "inprogress":
      return "inProgress";
    case "interrupted":
      return "interrupted";
    case "failed":
      return "failed";
    default:
      return "completed";
  }
}

function decodeStringArray(raw: unknown): string[] {
  return Array.isArray(raw) ? raw.filter((v): v is string => typeof v === "string") : [];
}

// ── Normalization ─────────────────────────────────────────────

/**
 * Translate one persisted event into zero or more reducer events.
 * An empty array means the persisted event is a no-op for client state
 * (unknown kinds, malformed payloads) — matching the Python replay, which
 * silently ignores what it cannot decode.
 */
export function normalizeEvent(evt: LoggedEvent): ConversationEvent[] {
  const threadId = evt.threadId;
  const turnId = evt.turnId ?? null;
  const payload = evt.payload ?? {};

  switch (evt.event) {
    case "thread_started":
      return [{ method: "thread/started", params: { thread: { id: threadId } } }];

    case "turn_started": {
      if (!turnId) return [];
      // The log records no full Turn here (params live outside the TS
      // model) — synthesize the inProgress shell Python builds.
      const turn: Turn = {
        id: turnId,
        threadId,
        status: "inProgress",
        startedAt: evt.ts ?? "",
        completedAt: null,
        items: [],
        error: null,
      };
      return [{ method: "turn/started", params: { threadId, turn } }];
    }

    case "turn_completed": {
      if (!turnId) return [];
      return [
        {
          method: "turn/finalized",
          params: {
            threadId,
            turnId,
            status: decodeTurnStatus(payload.status),
            completedAt: evt.ts ?? null,
            error: asRecord(payload.error),
          },
        },
      ];
    }

    case "turn_updated": {
      if (!turnId) return [];
      const events: ConversationEvent[] = [];
      // Field set mirrors ``_apply_turn_update``: grounding, phases,
      // workspaceFocus, workbenchSnapshot — each applied independently.
      const grounding = Array.isArray(payload.grounding)
        ? (payload.grounding.filter((g) => asRecord(g) !== null) as GroundingSource[])
        : null;
      if (grounding && grounding.length > 0) {
        events.push({
          method: "turn/grounding",
          params: { threadId, turnId, sources: grounding },
        });
      }
      const planParams: {
        threadId: string;
        turnId: string;
        phases?: Turn["phases"];
        workspaceFocus?: Turn["workspaceFocus"];
        workbenchSnapshot?: Turn["workbenchSnapshot"];
      } = { threadId, turnId };
      let hasPlanFields = false;
      if (Array.isArray(payload.phases)) {
        planParams.phases = payload.phases as Turn["phases"];
        hasPlanFields = true;
      }
      if ("workspaceFocus" in payload) {
        planParams.workspaceFocus =
          (asRecord(payload.workspaceFocus) as Turn["workspaceFocus"]) ?? null;
        hasPlanFields = true;
      }
      if ("workbenchSnapshot" in payload) {
        planParams.workbenchSnapshot =
          (asRecord(payload.workbenchSnapshot) as Turn["workbenchSnapshot"]) ??
          null;
        hasPlanFields = true;
      }
      if (hasPlanFields) {
        events.push({ method: "turn/plan/updated", params: planParams });
      }
      return events;
    }

    case "turn_compacted": {
      const summaryTurn = asRecord(payload.summaryTurn) as Turn | null;
      if (!summaryTurn) return [];
      return [
        {
          method: "turn/compacted",
          params: {
            threadId,
            supersededTurnIds: decodeStringArray(payload.supersededTurnIds),
            summaryTurn,
          },
        },
      ];
    }

    case "item_started": {
      if (!turnId) return [];
      const item = asRecord(payload.item) as Item | null;
      if (!item) return [];
      return [{ method: "item/started", params: { threadId, turnId, item } }];
    }

    case "item_completed": {
      if (!turnId) return [];
      const item = asRecord(payload.item) as Item | null;
      if (!item) return [];
      return [{ method: "item/completed", params: { threadId, turnId, item } }];
    }

    case "item_delta": {
      if (!turnId) return [];
      const itemId = payload.itemId;
      const kind = payload.kind;
      const delta = payload.delta;
      if (typeof itemId !== "string" || typeof kind !== "string") return [];
      switch (kind) {
        case "agentMessage":
          return typeof delta === "string"
            ? [{ method: "item/agentMessage/delta", params: { threadId, turnId, itemId, delta } }]
            : [];
        case "reasoning":
          return typeof delta === "string"
            ? [{ method: "item/reasoning/textDelta", params: { threadId, turnId, itemId, delta, contentIndex: 0 } }]
            : [];
        case "plan":
          return typeof delta === "string"
            ? [{ method: "item/plan/delta", params: { threadId, turnId, itemId, delta } }]
            : [];
        case "commandOutput":
          return typeof delta === "string"
            ? [{ method: "item/commandExecution/outputDelta", params: { threadId, turnId, itemId, delta } }]
            : [];
        case "fileChangeHunk": {
          // Shape mirrors ``_merge_file_change_hunk``: {path, op, hunk}.
          const h = asRecord(delta);
          const path = h?.path;
          const op = h?.op;
          const hunk = asRecord(h?.hunk) as FileHunk | null;
          if (
            typeof path !== "string" ||
            (op !== "create" && op !== "update" && op !== "delete") ||
            !hunk
          ) {
            return [];
          }
          return [
            {
              method: "item/fileChange/hunkDelta",
              params: { threadId, turnId, itemId, path, op, hunk },
            },
          ];
        }
        case "mcpToolProgress": {
          const progress = asRecord(delta) as McpToolProgress | null;
          return progress
            ? [{ method: "item/mcpToolCall/progress", params: { threadId, turnId, itemId, progress } }]
            : [];
        }
        default:
          // Unknown delta kind — the Python replay ignores these too.
          return [];
      }
    }

    default:
      return [];
  }
}

// ── Replay ────────────────────────────────────────────────────

/**
 * Fold a persisted event log into client Conversation state.
 *
 * Events must be in append order (the JSONL order). Folding goes through
 * ``reduce()`` in replay mode so live-only heuristics (interrupt grace
 * windows) are bypassed and the result is deterministic — replaying the
 * same log twice yields identical state.
 *
 * After the fold, every remaining in-flight chunk buffer is materialized
 * into the items' wire fields, so the returned Conversation is
 * self-contained: safe to persist, serialize, or read without
 * ``itemStreamText``.
 *
 * Performance note: this folds event-by-event (O(events) intermediate
 * states). A batched draft-based fold is a planned optimization
 * (client-replay-design.md §2.6); the conformance test pins the
 * event-by-event semantics any batching must reproduce.
 */
export function replayEvents(
  events: readonly (LoggedEvent | SequencedLoggedEvent)[],
  options?: ReplayOptions,
): ReplayResult {
  let state =
    options?.base ??
    emptyConversation(options?.threadId ?? events[0]?.threadId ?? "");
  let cursor = 0;
  let replayed = 0;
  let skipped = 0;

  for (const evt of events) {
    const sequence = (evt as SequencedLoggedEvent).sequence;
    if (typeof sequence === "number" && sequence > cursor) {
      cursor = sequence;
    }
    const normalized = normalizeEvent(evt);
    if (normalized.length === 0) {
      skipped += 1;
      continue;
    }
    replayed += 1;
    for (const reducerEvent of normalized) {
      state = reduce(state, reducerEvent, options?.onDiagnostic, {
        mode: "replay",
      }).next;
    }
  }

  state = materializeStreamedItems(state);
  if (state.resumeState !== "resumed") {
    state = { ...state, resumeState: "resumed" };
  }
  return { conversation: state, cursor, replayed, skipped };
}
