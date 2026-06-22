// Conversation reducer — applies server-pushed events to Conversation state.
//
// Pure function. No I/O. No React. Each call returns a new Conversation
// (never mutates the input) so React state setters trigger re-render
// only when the slice actually changes. The function is exported as the
// single recombinator the WebSocket client uses; tests target it
// directly without spinning up a server.

import type {
  AgentPhaseSnapshot,
  Conversation,
  FileHunk,
  GroundingSource,
  Item,
  McpToolProgress,
  Turn,
  WorkbenchSnapshotV2,
  WorkspaceFocus,
} from "./items";

let errorItemSeq = 0;

// All events the reducer understands. The set is closed: anything not
// listed here is a no-op (useful — server adds new methods without
// breaking older clients), but the type unions a developer should
// review when bumping the protocol.

export type ConversationEvent =
  | { method: "thread/started"; params: { thread: { id: string } } }
  | {
      method: "thread/status/changed";
      params: {
        threadId: string;
        status: { type: string; activeFlags?: string[] };
      };
    }
  | {
      method: "thread/tokenUsage/updated";
      params: { threadId: string; tokenUsage: Record<string, unknown> };
    }
  | { method: "turn/started"; params: { threadId: string; turn: Turn } }
  | {
      method: "turn/completed";
      params: { threadId: string; turn: Turn };
    }
  | {
      method: "turn/interrupted";
      params: { threadId: string; turnId: string; completedAt?: string };
    }
  | {
      method: "turn/diff/updated";
      params: { threadId: string; turnId: string; diff: unknown };
    }
  | {
      method: "turn/plan/updated";
      params: {
        threadId: string;
        turnId: string;
        phases: AgentPhaseSnapshot[];
        workspaceFocus?: WorkspaceFocus | null;
        workbenchSnapshot?: WorkbenchSnapshotV2 | null;
      };
    }
  | {
      method: "workbench/snapshot";
      params: {
        threadId: string;
        turnId: string;
        snapshot: WorkbenchSnapshotV2;
      };
    }
  | {
      // Lightweight keepalive for long-running swarm/cluster roles.
      // The reducer doesn't need to track state from this event — its
      // purpose is to prevent the frontend's pong-timeout (70s) from
      // killing the WS during roles that don't produce text deltas.
      method: "turn/heartbeat";
      params: {
        threadId: string;
        turnId: string;
        role?: string;
        agentId?: string;
        elapsedS?: number;
      };
    }
  | {
      // Soft hand-off hint emitted at turn start when the user's
      // prompt strongly matches a 能力包 / Meta-Skill. Reducer
      // attaches the hint to the matching turn so the chat page
      // can render a dismissible chip linking to the catalog. The
      // hint is informational — ReAct still runs in parallel.
      method: "turn/metaSkill/hint";
      params: {
        threadId: string;
        turnId: string;
        name: string;
        description: string;
        kind: string;
        affinity: string[];
        stepCount: number;
      };
    }
  | {
      // Codebase grounding: the project docs/chunks a code/project turn
      // folded into its prompt. Reducer attaches them to the matching turn;
      // the realtime adapter bridges them onto the AI reply's
      // ``additional_kwargs.grounding`` so the chat shows a grounding chip.
      method: "turn/grounding";
      params: {
        threadId: string;
        turnId: string;
        sources: GroundingSource[];
      };
    }
  | {
      method: "item/started";
      params: { threadId: string; turnId: string; item: Item };
    }
  | {
      method: "item/completed";
      params: { threadId: string; turnId: string; item: Item };
    }
  | {
      method: "item/agentMessage/delta";
      params: {
        threadId: string;
        turnId: string;
        itemId: string;
        delta: string;
      };
    }
  | {
      method: "item/reasoning/textDelta";
      params: {
        threadId: string;
        turnId: string;
        itemId: string;
        delta: string;
        contentIndex: number;
      };
    }
  | {
      method: "item/plan/delta";
      params: {
        threadId: string;
        turnId: string;
        itemId: string;
        delta: string;
      };
    }
  | {
      method: "item/commandExecution/outputDelta";
      params: {
        threadId: string;
        turnId: string;
        itemId: string;
        delta: string;
      };
    }
  | {
      method: "item/fileChange/hunkDelta";
      params: {
        threadId: string;
        turnId: string;
        itemId: string;
        path: string;
        op: "create" | "update" | "delete";
        hunk: FileHunk;
        workspaceFocus?: WorkspaceFocus | null;
      };
    }
  | {
      method: "item/mcpToolCall/progress";
      params: {
        threadId: string;
        turnId: string;
        itemId: string;
        progress: McpToolProgress;
        workspaceFocus?: WorkspaceFocus | null;
      };
    }
  | {
      method: "item/fileChange/hunkDecision";
      params: {
        threadId: string;
        turnId: string;
        itemId: string;
        hunkId: string;
        decision: "accepted" | "rejected";
        path: string;
      };
    }
  | {
      method: "error";
      params: {
        threadId: string;
        turnId?: string;
        error: { message: string };
        willRetry: boolean;
      };
    };

export interface PendingApprovalRequest {
  requestId: string | number;
  method: string;
  params: Record<string, unknown>;
}

// Event flag set returned alongside a reduced state so callers know what
// just happened without diffing the entire conversation. Avoids
// re-running expensive selectors when only a token landed.
export interface ReducerOutput {
  next: Conversation;
  changedTurnIds: string[];
  changedItemIds: string[];
}

export function reduce(
  state: Conversation,
  evt: ConversationEvent,
): ReducerOutput {
  switch (evt.method) {
    case "thread/started":
      return {
        next: { ...state, resumeState: "resumed" },
        changedTurnIds: [],
        changedItemIds: [],
      };
    case "thread/tokenUsage/updated":
      return {
        next: { ...state, tokenUsage: evt.params.tokenUsage },
        changedTurnIds: [],
        changedItemIds: [],
      };
    case "thread/status/changed":
      return { next: state, changedTurnIds: [], changedItemIds: [] };
    case "turn/started": {
      const incoming = evt.params.turn;
      const idx = state.turns.findIndex((t) => t.id === incoming.id);
      const turns =
        idx === -1
          ? [...state.turns, incoming]
          : state.turns.map((t) =>
              t.id === incoming.id ? { ...t, ...incoming } : t,
            );
      return {
        next: { ...state, turns },
        changedTurnIds: [incoming.id],
        changedItemIds: [],
      };
    }
    case "turn/completed": {
      const incoming = evt.params.turn;
      const changedItemIds: string[] = [];
      const turns = state.turns.map((t) => {
        if (t.id !== incoming.id) return t;
        const merged = mergeCompletedTurn(t, incoming);
        for (const item of merged.items) {
          const previous = t.items.find((it) => it.id === item.id);
          if (
            previous?.status === "inProgress" &&
            item.status !== "inProgress"
          ) {
            changedItemIds.push(item.id);
          }
        }
        return merged;
      });
      return {
        next: { ...state, turns },
        changedTurnIds: [incoming.id],
        changedItemIds,
      };
    }
    case "turn/interrupted": {
      const changedItemIds: string[] = [];
      const completedAt = evt.params.completedAt ?? new Date().toISOString();
      const turns = state.turns.map((t) => {
        if (t.id !== evt.params.turnId) return t;
        const items = t.items.map((item) => {
          if (item.status !== "inProgress") return item;
          changedItemIds.push(item.id);
          return { ...item, status: "interrupted" } as Item;
        });
        return { ...t, status: "interrupted" as const, completedAt, items };
      });
      return {
        next: { ...state, turns },
        changedTurnIds: [evt.params.turnId],
        changedItemIds,
      };
    }
    case "turn/diff/updated":
      return {
        next: state,
        changedTurnIds: [evt.params.turnId],
        changedItemIds: [],
      };
    case "turn/plan/updated":
      return applyPlanUpdate(
        state,
        evt.params.turnId,
        evt.params.phases,
        evt.params.workspaceFocus,
        "workspaceFocus" in evt.params,
        evt.params.workbenchSnapshot,
        "workbenchSnapshot" in evt.params,
      );
    case "workbench/snapshot":
      return applyWorkbenchSnapshot(
        state,
        evt.params.turnId,
        evt.params.snapshot,
      );
    case "turn/heartbeat":
      // No state change — purely a keepalive signal to prevent WS timeout.
      return { next: state, changedTurnIds: [], changedItemIds: [] };
    case "turn/metaSkill/hint": {
      // Attach the hint to the matching turn. If the turn isn't in
      // state yet (race against turn/started) we silently drop —
      // the hint is best-effort UX, not a contract.
      const { turnId, threadId, name, description, kind, affinity, stepCount } =
        evt.params;
      let touched = false;
      const turns = state.turns.map((t) => {
        if (t.id !== turnId) return t;
        touched = true;
        return {
          ...t,
          metaSkillHint: { name, description, kind, affinity, stepCount },
        };
      });
      if (!touched) {
        return { next: state, changedTurnIds: [], changedItemIds: [] };
      }
      void threadId;
      return {
        next: { ...state, turns },
        changedTurnIds: [turnId],
        changedItemIds: [],
      };
    }
    case "turn/grounding": {
      // Attach the consulted project docs/chunks to the matching turn.
      // Same race tolerance as the meta-skill hint: drop if the turn isn't
      // in state yet — grounding is best-effort UX, not a contract.
      const { turnId, threadId, sources } = evt.params;
      if (!Array.isArray(sources) || sources.length === 0) {
        return { next: state, changedTurnIds: [], changedItemIds: [] };
      }
      let touched = false;
      const turns = state.turns.map((t) => {
        if (t.id !== turnId) return t;
        touched = true;
        return { ...t, grounding: sources };
      });
      if (!touched) {
        return { next: state, changedTurnIds: [], changedItemIds: [] };
      }
      void threadId;
      return {
        next: { ...state, turns },
        changedTurnIds: [turnId],
        changedItemIds: [],
      };
    }
    case "item/started":
      return upsertItem(state, evt.params.turnId, evt.params.item, "started");
    case "item/completed":
      return upsertItem(state, evt.params.turnId, evt.params.item, "completed");
    case "item/agentMessage/delta":
      return mergeDelta(
        state,
        evt.params.turnId,
        evt.params.itemId,
        "agentMessage",
        evt.params.delta,
      );
    case "item/reasoning/textDelta":
      return mergeDelta(
        state,
        evt.params.turnId,
        evt.params.itemId,
        "reasoning",
        evt.params.delta,
      );
    case "item/plan/delta":
      return mergeDelta(
        state,
        evt.params.turnId,
        evt.params.itemId,
        "plan",
        evt.params.delta,
      );
    case "item/commandExecution/outputDelta":
      return mergeDelta(
        state,
        evt.params.turnId,
        evt.params.itemId,
        "commandOutput",
        evt.params.delta,
      );
    case "item/fileChange/hunkDelta":
      return applyFileChangeHunkDelta(
        state,
        evt.params.turnId,
        evt.params.itemId,
        evt.params.path,
        evt.params.op,
        evt.params.hunk,
        evt.params.workspaceFocus,
        "workspaceFocus" in evt.params,
      );
    case "item/mcpToolCall/progress":
      return applyMcpToolProgress(
        state,
        evt.params.turnId,
        evt.params.itemId,
        evt.params.progress,
        evt.params.workspaceFocus,
        "workspaceFocus" in evt.params,
      );
    case "item/fileChange/hunkDecision":
      return applyHunkDecision(
        state,
        evt.params.turnId,
        evt.params.itemId,
        evt.params.hunkId,
        evt.params.decision,
      );
    case "error": {
      // Surface as a transient errorItem on the active turn (if any).
      // We do *not* mutate turn.status here — turn/completed authoritatively
      // sets that. Same convention as the server.
      const turnId =
        evt.params.turnId ?? state.turns[state.turns.length - 1]?.id;
      if (!turnId)
        return { next: state, changedTurnIds: [], changedItemIds: [] };
      const errorItem: Item = {
        id: `err_${Date.now()}_${++errorItemSeq}`,
        type: "error",
        status: "failed",
        createdAt: new Date().toISOString(),
        message: evt.params.error.message,
        willRetry: evt.params.willRetry,
        errorInfo: null,
      };
      return upsertItem(state, turnId, errorItem, "started");
    }
    default:
      return { next: state, changedTurnIds: [], changedItemIds: [] };
  }
}

// ── Helpers ──────────────────────────────────────────────────

// Shared no-op result: same state reference, nothing flagged as changed.
// Returning the *same* reference matters — callers (and React setters)
// use identity to skip re-renders, so dropped deltas must not allocate.
function unchanged(state: Conversation): ReducerOutput {
  return { next: state, changedTurnIds: [], changedItemIds: [] };
}

// Copy ``arr`` with index ``idx`` replaced. Single allocation, no
// per-element predicate — the indexed counterpart of ``.map()`` for
// the hot single-item update paths below.
function replaceAt<T>(arr: readonly T[], idx: number, value: T): T[] {
  const next = arr.slice();
  next[idx] = value;
  return next;
}

// Rebuild Conversation with one item of one turn swapped out. Every
// streaming delta lands here, so the work is two indexed copies —
// no full-array scans beyond the initial findIndex at the call site.
function replaceTurnItem(
  state: Conversation,
  turn: Turn,
  turnIdx: number,
  itemIdx: number,
  item: Item,
  turnPatch?: Partial<Turn>,
): Conversation {
  const nextTurn: Turn = {
    ...turn,
    ...turnPatch,
    items: replaceAt(turn.items, itemIdx, item),
  };
  return { ...state, turns: replaceAt(state.turns, turnIdx, nextTurn) };
}

function mergeCompletedTurn(existing: Turn, incoming: Turn): Turn {
  const incomingItems = Array.isArray(incoming.items) ? incoming.items : [];
  const incomingById = new Map(incomingItems.map((item) => [item.id, item]));
  const terminalStatus = itemTerminalStatus(incoming.status);
  const existingItems = existing.items.map((item) => {
    const replacement = incomingById.get(item.id);
    if (replacement) return replacement;
    if (item.status === "inProgress") {
      return { ...item, status: terminalStatus } as Item;
    }
    return item;
  });
  const existingIds = new Set(existing.items.map((item) => item.id));
  const appended = incomingItems.filter((item) => !existingIds.has(item.id));
  return { ...existing, ...incoming, items: [...existingItems, ...appended] };
}

function itemTerminalStatus(turnStatus: Turn["status"]): Item["status"] {
  if (turnStatus === "failed") return "failed";
  if (turnStatus === "interrupted") return "interrupted";
  return "completed";
}

function upsertItem(
  state: Conversation,
  turnId: string,
  item: Item,
  phase: "started" | "completed",
): ReducerOutput {
  const turnIdx = state.turns.findIndex((t) => t.id === turnId);
  const turn = state.turns[turnIdx];
  if (!turn) {
    return unchanged(state);
  }
  const idx = turn.items.findIndex((it) => it.id === item.id);
  let nextItems: Item[];
  if (idx === -1) {
    nextItems = [...turn.items, item];
  } else {
    // ``completed`` snapshots replace; ``started`` after ``completed`` is
    // a no-op (out-of-order delivery from a buffered queue).
    const existing = turn.items[idx];
    if (phase === "completed" || existing?.status === "inProgress") {
      nextItems = replaceAt(turn.items, idx, item);
    } else {
      return unchanged(state);
    }
  }
  const nextTurn: Turn = { ...turn, items: nextItems };
  return {
    next: { ...state, turns: replaceAt(state.turns, turnIdx, nextTurn) },
    changedTurnIds: [turnId],
    changedItemIds: [item.id],
  };
}

type DeltaKind = "agentMessage" | "reasoning" | "plan" | "commandOutput";

function mergeDelta(
  state: Conversation,
  turnId: string,
  itemId: string,
  kind: DeltaKind,
  delta: string,
): ReducerOutput {
  const turnIdx = state.turns.findIndex((t) => t.id === turnId);
  const turn = state.turns[turnIdx];
  if (!turn) {
    return unchanged(state);
  }
  const itemIdx = turn.items.findIndex((x) => x.id === itemId);
  const it = turn.items[itemIdx];
  if (!it) {
    return unchanged(state);
  }
  // Drop deltas that arrive after the item is already completed.
  // Without this, the RAF-batched delta queue can flush AFTER an
  // ``item/completed`` snapshot lands in the reducer (item/* is
  // dispatched immediately, deltas are deferred to next frame),
  // and we end up appending those deltas to the already-final
  // ``text`` — doubling content. Status check is the simplest gate.
  if (it.status !== "inProgress") {
    return unchanged(state);
  }
  let updated: Item | null = null;
  if (kind === "agentMessage" && it.type === "agentMessage") {
    updated = { ...it, text: it.text + delta };
  } else if (kind === "reasoning" && it.type === "reasoning") {
    updated = { ...it, content: it.content + delta };
  } else if (kind === "plan" && it.type === "plan") {
    updated = { ...it, text: it.text + delta };
  } else if (kind === "commandOutput" && it.type === "commandExecution") {
    updated = { ...it, aggregatedOutput: it.aggregatedOutput + delta };
  }
  if (updated === null) {
    return unchanged(state);
  }
  return {
    next: replaceTurnItem(state, turn, turnIdx, itemIdx, updated),
    changedTurnIds: [turnId],
    changedItemIds: [itemId],
  };
}

function applyPlanUpdate(
  state: Conversation,
  turnId: string,
  phases: AgentPhaseSnapshot[],
  workspaceFocus: WorkspaceFocus | null | undefined,
  hasWorkspaceFocus: boolean,
  workbenchSnapshot: WorkbenchSnapshotV2 | null | undefined,
  hasWorkbenchSnapshot: boolean,
): ReducerOutput {
  let touched = false;
  const turns = state.turns.map((turn) => {
    if (turn.id !== turnId) return turn;
    touched = true;
    return {
      ...turn,
      phases,
      ...(hasWorkspaceFocus ? { workspaceFocus: workspaceFocus ?? null } : {}),
      ...(hasWorkbenchSnapshot
        ? { workbenchSnapshot: workbenchSnapshot ?? null }
        : {}),
    };
  });
  if (!touched) {
    return { next: state, changedTurnIds: [], changedItemIds: [] };
  }
  return {
    next: { ...state, turns },
    changedTurnIds: [turnId],
    changedItemIds: [],
  };
}

function applyWorkbenchSnapshot(
  state: Conversation,
  turnId: string,
  snapshot: WorkbenchSnapshotV2,
): ReducerOutput {
  let touched = false;
  const turns = state.turns.map((turn) => {
    if (turn.id !== turnId) return turn;
    touched = true;
    return {
      ...turn,
      workbenchSnapshot: snapshot,
      phases: snapshot.phases,
      ...(snapshot.workspaceFocus !== undefined
        ? { workspaceFocus: snapshot.workspaceFocus ?? null }
        : {}),
    };
  });
  if (!touched) {
    return { next: state, changedTurnIds: [], changedItemIds: [] };
  }
  return {
    next: { ...state, turns },
    changedTurnIds: [turnId],
    changedItemIds: [],
  };
}

function applyMcpToolProgress(
  state: Conversation,
  turnId: string,
  itemId: string,
  progress: McpToolProgress,
  workspaceFocus: WorkspaceFocus | null | undefined,
  hasWorkspaceFocus: boolean,
): ReducerOutput {
  const turnIdx = state.turns.findIndex((t) => t.id === turnId);
  const turn = state.turns[turnIdx];
  if (!turn) {
    return unchanged(state);
  }
  const itemIdx = turn.items.findIndex(
    (item) => item.id === itemId && item.type === "mcpToolCall",
  );
  const existing = turn.items[itemIdx];
  if (!existing) {
    return unchanged(state);
  }
  const updated = { ...existing, progress } as Item;
  const turnPatch = hasWorkspaceFocus
    ? { workspaceFocus: workspaceFocus ?? null }
    : undefined;
  return {
    next: replaceTurnItem(state, turn, turnIdx, itemIdx, updated, turnPatch),
    changedTurnIds: [turnId],
    changedItemIds: [itemId],
  };
}

function applyFileChangeHunkDelta(
  state: Conversation,
  turnId: string,
  itemId: string,
  path: string,
  op: "create" | "update" | "delete",
  hunk: FileHunk,
  workspaceFocus: WorkspaceFocus | null | undefined,
  hasWorkspaceFocus: boolean,
): ReducerOutput {
  const turnIdx = state.turns.findIndex((t) => t.id === turnId);
  const turn = state.turns[turnIdx];
  if (!turn) {
    return unchanged(state);
  }
  const itemIdx = turn.items.findIndex(
    (entry) => entry.id === itemId && entry.type === "fileChange",
  );
  const item = turn.items[itemIdx];
  if (!item || item.type !== "fileChange") {
    return unchanged(state);
  }
  const changeIndex = item.changes.findIndex((change) => change.path === path);
  const change = item.changes[changeIndex];
  let changes;
  if (!change) {
    changes = [...item.changes, { path, op, hunks: [hunk] }];
  } else {
    const hunks = change.hunks ?? [];
    const hunkIndex = hunks.findIndex((existing) => existing.id === hunk.id);
    const nextHunks =
      hunkIndex === -1 ? [...hunks, hunk] : replaceAt(hunks, hunkIndex, hunk);
    changes = replaceAt(item.changes, changeIndex, {
      ...change,
      op: change.op ?? op,
      hunks: nextHunks,
    });
  }
  const updated = { ...item, changes } as Item;
  const turnPatch = hasWorkspaceFocus
    ? { workspaceFocus: workspaceFocus ?? null }
    : undefined;
  return {
    next: replaceTurnItem(state, turn, turnIdx, itemIdx, updated, turnPatch),
    changedTurnIds: [turnId],
    changedItemIds: [itemId],
  };
}

function applyHunkDecision(
  state: Conversation,
  turnId: string,
  itemId: string,
  hunkId: string,
  decision: "accepted" | "rejected",
): ReducerOutput {
  const turnIdx = state.turns.findIndex((t) => t.id === turnId);
  const turn = state.turns[turnIdx];
  if (!turn) return unchanged(state);
  const itemIdx = turn.items.findIndex(
    (it) => it.id === itemId && it.type === "fileChange",
  );
  const item = turn.items[itemIdx];
  if (!item || item.type !== "fileChange") return unchanged(state);
  let hit = false;
  const changes = item.changes.map((ch) => {
    if (!ch.hunks) return ch;
    const hunkIndex = ch.hunks.findIndex((h) => h.id === hunkId);
    const target = ch.hunks[hunkIndex];
    if (!target) return ch;
    hit = true;
    return {
      ...ch,
      hunks: replaceAt(ch.hunks, hunkIndex, { ...target, decision }),
    };
  });
  if (!hit) return unchanged(state);
  const updated = { ...item, changes } as Item;
  return {
    next: replaceTurnItem(state, turn, turnIdx, itemIdx, updated),
    changedTurnIds: [turnId],
    changedItemIds: [itemId],
  };
}
