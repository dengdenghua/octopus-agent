// React hook bridging RealtimeClient + reducer to component state.
//
// Usage:
//
//   const { state, startTurn, resolveApproval } = useRealtimeThread({
//     threadId: "thread-abc",
//   });
//
// State is a Conversation; ``startTurn`` returns when the server emits
// turn/completed for that turn — or, if the socket drops mid-turn after
// the turn was confirmed started (turn/started observed), it resolves
// early and leaves turn-state recovery to reconnect + resume. It only
// rejects when the turn was never delivered. Approvals show up as
// ``state.pendingApprovals`` and are resolved via ``resolveApproval``.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { getBackendBaseURL } from "@/core/config";
import { getToken } from "@/core/auth/api";
import type { SandboxPolicy } from "@/core/permissions";
import type { ReasoningEffort } from "@/core/threads";

import { createDefaultClient, type RealtimeClient } from "./client";
import type { JsonRpcRequest } from "./envelope";
import {
  type Conversation,
  emptyConversation,
  type PendingApproval,
} from "./items";
import { type ConversationEvent, reduce } from "./reducer";
import {
  applyVitalNotification,
  emptyVitalsMarks,
  seedVitalsFromResumedTurn,
  type StreamVitals,
  type VitalsMarks,
} from "./stream-vitals";
import { useStreamVitals } from "./use-stream-vitals";
import {
  appendStreamTelemetry,
  createStreamTurnTelemetry,
  type StreamTurnOutcome,
} from "./stream-telemetry";

// Item types that represent the agent actively doing work — a running one
// keeps a silent turn out of the "slow / maybe-stuck" bucket (a 60s command
// or a busy subagent produces no deltas yet is plainly still working).
const WORK_ITEM_TYPES = new Set<string>([
  "commandExecution",
  "fileChange",
  "mcpToolCall",
  "subagent",
]);

export interface UseRealtimeThreadArgs {
  threadId: string;
  // Inject for tests. Defaults to a real client backed by getBackendBaseURL().
  clientFactory?: (deps: {
    onIncomingRequest: (req: JsonRpcRequest) => Promise<unknown>;
    onNotification: (n: {
      method: string;
      params: Record<string, unknown>;
    }) => void;
  }) => RealtimeClient;
}

export interface UseRealtimeThreadValue {
  state: Conversation;
  connected: boolean;
  startTurn: (params: {
    input: string;
    attachments?: Record<string, unknown>[];
    approvalPolicy?: "never" | "on-request" | "untrusted";
    sandboxPolicy?: SandboxPolicy;
    planningMode?: boolean;
    model?: string;
    effort?: ReasoningEffort;
    metadata?: Record<string, unknown>;
    /** Optional topology id for callers that explicitly need the
     * runtime to route through the team topology path instead of
     * single-agent ReAct. The unified chat workspace sets this when
     * collaborators are pulled into the current task in 集群 mode.
     */
    topologyId?: string;
  }) => Promise<void>;
  resolveApproval: (requestId: string | number, accept: boolean) => void;
  /** Live streaming vitals for the active turn (TTFT, delta cadence, stall
   * detection). Lets the status strip tell "model still working" apart
   * from "connection stuck". ``phase: "idle"`` between turns. */
  vitals: StreamVitals;
  resume: () => Promise<void>;
  /** Page backwards: prepend the next batch of turns older than the
   * current `state.turns[0]`. No-op when `state.hasMoreTurns` is
   * false or a load is already in flight. */
  loadOlderTurns: () => Promise<void>;
  /** Cancel the turn that's currently in progress, if any. No-op when
   * no turn is live. The returned promise resolves once the server has
   * acknowledged the interrupt RPC — not when the turn actually ends;
   * watch ``state.turns[last].status === "interrupted"`` for that. */
  interrupt: () => Promise<void>;
  /** Persist a compacted summary turn for older history, then refresh. */
  compact: () => Promise<{
    compacted: boolean;
    reason?: string;
    turnCount?: number;
    keepRecent?: number;
  }>;
  /** Accept or reject a single hunk on a FileChange item. Rejection
   * reverse-applies that hunk's diff on the server; acceptance is
   * informational (the file already has the patched form). The
   * server broadcasts ``item/fileChange/hunkDecision`` so every
   * connected client updates uniformly. */
  decideHunk: (args: {
    turnId: string;
    itemId: string;
    hunkId: string;
    path: string;
    decision: "accepted" | "rejected";
    diff?: string;
  }) => Promise<void>;
}

// Newest turns fetched per thread/resume page. Large threads resume
// with the most recent window; older history pages in on demand via
// loadOlderTurns().
const RESUME_TURN_LIMIT = 50;

interface ResumeResponse {
  thread?: { id: string; path?: string };
  turns: Conversation["turns"];
  hasMore?: boolean;
  totalTurns?: number;
  incremental?: boolean;
  nextEventSequence?: number;
  eventStreamId?: string | null;
}

/** Replace changed turn snapshots without disturbing the surrounding
 * timeline. The server returns whole snapshots for affected turns, so
 * reconnect recovery never has to replay individual deltas in the UI. */
function mergeTurnSnapshots(
  existing: Conversation["turns"],
  changed: Conversation["turns"],
): Conversation["turns"] {
  if (changed.length === 0) return existing;
  const changedById = new Map(changed.map((turn) => [turn.id, turn]));
  const existingIds = new Set(existing.map((turn) => turn.id));
  return [
    ...existing.map((turn) => changedById.get(turn.id) ?? turn),
    ...changed.filter((turn) => !existingIds.has(turn.id)),
  ];
}

export function useRealtimeThread(
  args: UseRealtimeThreadArgs,
): UseRealtimeThreadValue {
  const [state, setState] = useState<Conversation>(() =>
    emptyConversation(args.threadId),
  );
  const [connected, setConnected] = useState(false);

  // Pending approvals are surfaced through state, but the resolution
  // map (requestId → resolver) lives here so we can reply on the
  // socket without round-tripping through React render cycles.
  const approvalResolvers = useRef<
    Map<string | number, (decision: { action: string }) => void>
  >(new Map());
  // Client-side expiry timers, keyed like the resolvers. The server
  // denies on its own timeout (params.timeoutMs); these keep the
  // dialog from outliving that decision as a zombie prompt.
  const approvalTimers = useRef<
    Map<string | number, ReturnType<typeof setTimeout>>
  >(new Map());
  const clientRef = useRef<RealtimeClient | null>(null);
  // Streaming-vitals timestamps, mutated off the notification stream (no
  // re-render) and read by a ticking hook. A ref so the ``onNotification``
  // closure sees the live object across reconnects.
  const vitalsMarksRef = useRef<VitalsMarks>(emptyVitalsMarks());
  // Latest reduced snapshot for callbacks that don't want React's stale
  // closure semantics. Updated synchronously alongside ``setState``.
  const stateRef = useRef<Conversation>(state);
  // One-based physical event-log cursor returned by thread/resume. It is
  // intentionally independent of rendered item sequence: reconnect asks
  // only for turns changed after this durable server position.
  const resumeCursorRef = useRef<number | null>(null);
  // Stable identity of the append-only stream behind the numeric cursor.
  // If a log is replaced or restored, the server returns a full snapshot
  // instead of interpreting the old cursor inside unrelated history.
  const resumeStreamIdRef = useRef<string | null>(null);
  // Delivery watches for in-flight turn/start requests. The server holds
  // the turn/start RPC response until the whole turn has run to
  // completion, so ANY mid-turn socket drop rejects the pending request
  // even though the turn was accepted and the user message persisted.
  // A turn/started notification observed after the request went out is
  // the real delivery signal — ``startTurn`` uses it to swallow later
  // transport rejections (reconnect + resume recover the turn state).
  const turnDeliveryWatchesRef = useRef<Set<{ delivered: boolean }>>(new Set());

  const persistTurnTelemetry = useCallback(
    (turnId: string, outcome: StreamTurnOutcome, completedAt = Date.now()) => {
      const record = createStreamTurnTelemetry({
        threadId: args.threadId,
        turnId,
        outcome,
        marks: vitalsMarksRef.current,
        completedAt,
      });
      if (record) appendStreamTelemetry(record);
    },
    [args.threadId],
  );

  const applyEvent = useCallback((evt: ConversationEvent) => {
    setState((prev) => {
      // Second line of defense: reject events that belong to a different
      // thread than the one currently held in state. This guards against
      // any in-flight notifications from a previous thread's WebSocket
      // that slip through between cleanup and the socket actually closing.
      const eventThreadId =
        "threadId" in evt.params ? evt.params.threadId : evt.params.thread.id;
      if (
        typeof eventThreadId === "string" &&
        eventThreadId !== prev.threadId
      ) {
        return prev;
      }
      const { next } = reduce(prev, evt);
      stateRef.current = next;
      return next;
    });
  }, []);

  // Build/teardown the client when threadId changes.
  useEffect(() => {
    setState(emptyConversation(args.threadId));
    stateRef.current = emptyConversation(args.threadId);
    resumeCursorRef.current = null;
    resumeStreamIdRef.current = null;
    vitalsMarksRef.current = emptyVitalsMarks();
    const resolvers = approvalResolvers.current;
    const timers = approvalTimers.current;
    const onIncomingRequest = async (req: JsonRpcRequest): Promise<unknown> =>
      new Promise((resolve) => {
        const pending: PendingApproval = {
          requestId: req.id,
          method: req.method,
          params: req.params,
          createdAt: new Date().toISOString(),
        };
        setState((prev) => {
          const next: Conversation = {
            ...prev,
            pendingApprovals: [...prev.pendingApprovals, pending],
          };
          stateRef.current = next;
          return next;
        });
        approvalResolvers.current.set(req.id, (decision) => {
          // Strip from pendingApprovals once resolved.
          setState((prev) => {
            const next: Conversation = {
              ...prev,
              pendingApprovals: prev.pendingApprovals.filter(
                (p) => p.requestId !== req.id,
              ),
            };
            stateRef.current = next;
            return next;
          });
          approvalResolvers.current.delete(req.id);
          const timer = approvalTimers.current.get(req.id);
          if (timer !== undefined) {
            clearTimeout(timer);
            approvalTimers.current.delete(req.id);
          }
          resolve(decision);
        });
        // Expire in lockstep with the server: once its timeout lapses
        // the request id is dead — the server already denied — so a
        // reply would go nowhere. Auto-decline locally to drop the
        // dialog and settle the promise (an unsettled promise here
        // leaks the client's reply tracker entry forever).
        const timeoutMs =
          typeof req.params?.timeoutMs === "number" && req.params.timeoutMs > 0
            ? req.params.timeoutMs
            : 600_000;
        approvalTimers.current.set(
          req.id,
          setTimeout(() => {
            approvalResolvers.current.get(req.id)?.({
              action: "decline",
              reason: "timeout",
            } as { action: string });
          }, timeoutMs),
        );
      });

    let resumeSeq = 0;
    let resumeInFlight = false;
    const requestResume = (
      client: RealtimeClient,
      mode: "preserve-live" | "replace",
    ): void => {
      const seq = ++resumeSeq;
      resumeInFlight = true;
      const afterSequence = resumeCursorRef.current;
      const eventStreamId = resumeStreamIdRef.current;
      void client
        .request<ResumeResponse>("thread/resume", {
          threadId: args.threadId,
          limit: RESUME_TURN_LIMIT,
          ...(afterSequence !== null ? { afterSequence } : {}),
          ...(afterSequence !== null && eventStreamId ? { eventStreamId } : {}),
        })
        .then((result) => {
          if (cancelled || seq !== resumeSeq) return;
          resumeInFlight = false;
          if (
            typeof result.nextEventSequence === "number" &&
            Number.isFinite(result.nextEventSequence) &&
            result.nextEventSequence >= 0
          ) {
            resumeCursorRef.current = result.nextEventSequence;
          }
          if (typeof result.eventStreamId === "string") {
            resumeStreamIdRef.current = result.eventStreamId;
          }
          setState((prev) => {
            const serverTurns = result.turns ?? [];
            const turns =
              result.incremental === true
                ? mergeTurnSnapshots(prev.turns, serverTurns)
                : mode === "preserve-live" &&
                    prev.turns.length > 0 &&
                    (!result.thread?.id || prev.threadId === result.thread.id)
                  ? mergeTurnSnapshots(serverTurns, prev.turns)
                  : serverTurns;
            const next: Conversation = {
              ...prev,
              turns,
              resumeState: "resumed",
              hasMoreTurns:
                result.incremental === true
                  ? prev.hasMoreTurns
                  : result.hasMore === true,
            };
            const resumedActive = [...turns]
              .reverse()
              .find((turn) => turn.status === "inProgress");
            seedVitalsFromResumedTurn(
              vitalsMarksRef.current,
              resumedActive ?? null,
              Date.now(),
            );
            stateRef.current = next;
            return next;
          });
        })
        .catch(() => {
          if (cancelled || seq !== resumeSeq) return;
          resumeInFlight = false;
          setState((prev) => {
            const next: Conversation = { ...prev, resumeState: "needsResume" };
            stateRef.current = next;
            return next;
          });
        });
    };

    const onNotification = (note: {
      method: string;
      params: Record<string, unknown>;
    }): void => {
      if (cancelled) return;
      const belongsToThread = note.params?.threadId === args.threadId;
      // Record liveness telemetry before the reducer runs. Cheap, pure,
      // ref-mutating — never triggers a render on its own.
      if (belongsToThread) {
        applyVitalNotification(vitalsMarksRef.current, note, Date.now());
      }
      if (belongsToThread && note.method === "turn/completed") {
        const turn = note.params?.turn as
          | { id?: unknown; status?: unknown }
          | undefined;
        const outcome = turn?.status;
        if (
          typeof turn?.id === "string" &&
          (outcome === "completed" ||
            outcome === "interrupted" ||
            outcome === "failed")
        ) {
          persistTurnTelemetry(turn.id, outcome);
        }
      } else if (belongsToThread && note.method === "turn/interrupted") {
        const turnId = note.params?.turnId;
        if (typeof turnId === "string") {
          persistTurnTelemetry(turnId, "interrupted");
        }
      }
      if (
        note.method === "turn/started" &&
        note.params?.threadId === args.threadId
      ) {
        // Historical turns replay through the thread/resume *response*,
        // never through this notification path, so a turn/started seen
        // here means a live turn actually began after the watched
        // turn/start request went out on this connection. The server
        // runs turns sequentially per thread, so starts pair FIFO with
        // in-flight requests — mark only the oldest undelivered watch,
        // not all of them (an overlapping second send must not inherit
        // the first turn's start).
        for (const watch of turnDeliveryWatchesRef.current) {
          if (!watch.delivered) {
            watch.delivered = true;
            break;
          }
        }
      }
      // ``ConversationEvent`` is a discriminated union over a closed
      // method set. Cast through ``unknown`` because the wire side is
      // open-ended; the reducer no-ops anything it doesn't recognize.
      applyEvent(note as unknown as ConversationEvent);
    };

    const onClose = (_code: number, _reason: string): void => {
      if (cancelled) return;
      // The socket is gone — flip ``connected`` to false so the UI
      // can show a "reconnecting..." pill. The auto-reconnect logic
      // inside ``RealtimeClient`` will call onOpen again when the
      // new socket is up.
      setConnected(false);
      // The server cancels every pending approval future when the
      // connection drops (ApprovalManager.cancel_all), so the request
      // ids are dead. Drop the dialogs and timers now — replying after
      // reconnect would target a request the server no longer knows.
      for (const timer of approvalTimers.current.values()) {
        clearTimeout(timer);
      }
      approvalTimers.current.clear();
      approvalResolvers.current.clear();
      if (stateRef.current.pendingApprovals.length > 0) {
        setState((prev) => {
          const next: Conversation = { ...prev, pendingApprovals: [] };
          stateRef.current = next;
          return next;
        });
      }
      // Do not invent a turn outcome from a transport failure. The server
      // owns turn lifecycle and may still be running or may have persisted
      // an interruption. Keep the live timeline intact while disconnected;
      // incremental resume reconciles the authoritative snapshot on reopen.
    };

    const onOpen = (): void => {
      if (cancelled) return;
      // Real socket open — only now can the client actually send /
      // receive. Previously we set ``connected`` true the moment
      // ``client.connect()`` returned, which was optimistic: the
      // promise resolves before the WebSocket handshake completes,
      // so a startup screen could "look connected" while sends were
      // queueing in the outbox. Drive the flag from the actual
      // socket open event instead.
      setConnected(true);
      const client = clientRef.current;
      if (
        client &&
        (openedOnce ||
          (stateRef.current.resumeState !== "resumed" && !resumeInFlight))
      ) {
        requestResume(client, "replace");
      } else {
        openedOnce = true;
      }
      openedOnce = true;
    };

    const factory =
      args.clientFactory ??
      ((deps: {
        onIncomingRequest: (req: JsonRpcRequest) => Promise<unknown>;
        onNotification: (n: {
          method: string;
          params: Record<string, unknown>;
        }) => void;
        onOpen?: () => void;
        onClose?: (code: number, reason: string) => void;
      }) =>
        createDefaultClient({
          baseURL: getBackendBaseURL(),
          authToken: () => getToken(),
          onIncomingRequest: deps.onIncomingRequest,
          onNotification: deps.onNotification,
          onOpen: deps.onOpen,
          onClose: deps.onClose,
        }));

    let cancelled = false;
    let openedOnce = false;
    const client = factory({
      onIncomingRequest,
      onNotification,
      onOpen,
      onClose,
    });
    clientRef.current = client;
    requestResume(client, "preserve-live");
    client.connect();
    // Note: do NOT setConnected(true) here. The previous optimistic
    // flag has been replaced — onOpen drives it now (see comment on
    // ``onOpen`` above).

    return () => {
      cancelled = true;
      client.close();
      clientRef.current = null;
      resolvers.clear();
      for (const timer of timers.values()) {
        clearTimeout(timer);
      }
      timers.clear();
      setConnected(false);
    };
  }, [args.threadId, args.clientFactory, applyEvent, persistTurnTelemetry]);

  const startTurn = useCallback<UseRealtimeThreadValue["startTurn"]>(
    async (input) => {
      const client = clientRef.current;
      if (!client) throw new Error("realtime client not ready");
      const watch = { delivered: false };
      turnDeliveryWatchesRef.current.add(watch);
      try {
        await client.request("turn/start", {
          threadId: args.threadId,
          input: [
            {
              type: "text",
              text: input.input,
              ...(input.attachments && input.attachments.length > 0
                ? { attachments: input.attachments }
                : {}),
              ...(input.metadata ? { metadata: input.metadata } : {}),
            },
          ],
          approvalPolicy: input.approvalPolicy ?? "on-request",
          ...(input.sandboxPolicy
            ? { sandboxPolicy: input.sandboxPolicy }
            : {}),
          ...(input.planningMode ? { planningMode: input.planningMode } : {}),
          ...(input.effort ? { effort: input.effort } : {}),
          model: input.model,
          ...(input.topologyId ? { topologyId: input.topologyId } : {}),
        });
      } catch (err) {
        // The turn/start response only arrives once the whole turn has
        // finished, so a disconnect at any point of a long turn rejects
        // the pending request even though the message was delivered and
        // persisted server-side. If turn/started was observed after this
        // request went out, resolve normally: surfacing the rejection
        // would make callers flag a successful send as failed (error
        // banner + draft restore → duplicate sends). Turn state is
        // recovered by the reconnect/resume path.
        if (!watch.delivered) throw err;
      } finally {
        turnDeliveryWatchesRef.current.delete(watch);
      }
    },
    [args.threadId],
  );

  const resolveApproval = useCallback<
    UseRealtimeThreadValue["resolveApproval"]
  >((requestId, accept) => {
    const resolver = approvalResolvers.current.get(requestId);
    if (!resolver) return;
    resolver({ action: accept ? "accept" : "decline" });
  }, []);

  const resume = useCallback(async () => {
    const client = clientRef.current;
    if (!client) return;
    const afterSequence = resumeCursorRef.current;
    const eventStreamId = resumeStreamIdRef.current;
    const result = await client.request<ResumeResponse>("thread/resume", {
      threadId: args.threadId,
      limit: RESUME_TURN_LIMIT,
      ...(afterSequence !== null ? { afterSequence } : {}),
      ...(afterSequence !== null && eventStreamId ? { eventStreamId } : {}),
    });
    if (
      typeof result.nextEventSequence === "number" &&
      Number.isFinite(result.nextEventSequence) &&
      result.nextEventSequence >= 0
    ) {
      resumeCursorRef.current = result.nextEventSequence;
    }
    if (typeof result.eventStreamId === "string") {
      resumeStreamIdRef.current = result.eventStreamId;
    }
    setState((prev) => {
      const turns =
        result.incremental === true
          ? mergeTurnSnapshots(prev.turns, result.turns ?? [])
          : (result.turns ?? []);
      const next: Conversation = {
        ...prev,
        turns,
        resumeState: "resumed",
        hasMoreTurns:
          result.incremental === true
            ? prev.hasMoreTurns
            : result.hasMore === true,
      };
      const resumedActive = [...turns]
        .reverse()
        .find((turn) => turn.status === "inProgress");
      seedVitalsFromResumedTurn(
        vitalsMarksRef.current,
        resumedActive ?? null,
        Date.now(),
      );
      stateRef.current = next;
      return next;
    });
  }, [args.threadId]);

  // Guards concurrent backwards-pagination; a ref (not state) because
  // double-invocation protection must be synchronous.
  const loadingOlderRef = useRef(false);

  const loadOlderTurns = useCallback(async () => {
    const client = clientRef.current;
    if (!client) return;
    if (loadingOlderRef.current) return;
    const current = stateRef.current;
    if (!current.hasMoreTurns) return;
    const oldest = current.turns[0];
    if (!oldest) return;
    loadingOlderRef.current = true;
    try {
      type ResumeResponse = {
        turns: Conversation["turns"];
        hasMore?: boolean;
      };
      const result = await client.request<ResumeResponse>("thread/resume", {
        threadId: args.threadId,
        limit: RESUME_TURN_LIMIT,
        beforeTurnId: oldest.id,
      });
      setState((prev) => {
        // Drop any overlap defensively (the cursor is exclusive, but a
        // concurrent full resume may have already prepended them).
        const known = new Set(prev.turns.map((t) => t.id));
        const older = (result.turns ?? []).filter((t) => !known.has(t.id));
        const next: Conversation = {
          ...prev,
          turns: [...older, ...prev.turns],
          hasMoreTurns: result.hasMore === true,
        };
        stateRef.current = next;
        return next;
      });
    } finally {
      loadingOlderRef.current = false;
    }
  }, [args.threadId]);

  const interrupt = useCallback<
    UseRealtimeThreadValue["interrupt"]
  >(async () => {
    const client = clientRef.current;
    if (!client) return;
    // Pull the active turn id off the latest state. If there is no
    // active turn we silently skip — clicking "stop" on a finished
    // conversation should not throw.
    const turns = stateRef.current.turns;
    const active = turns.length ? turns[turns.length - 1] : null;
    if (!active || active.status !== "inProgress") return;
    await client.request("turn/interrupt", {
      threadId: args.threadId,
      turnId: active.id,
    });
    persistTurnTelemetry(active.id, "interrupted");
    applyEvent({
      method: "turn/interrupted",
      params: {
        threadId: args.threadId,
        turnId: active.id,
        completedAt: new Date().toISOString(),
      },
    });
  }, [args.threadId, applyEvent, persistTurnTelemetry]);

  const compact = useCallback<UseRealtimeThreadValue["compact"]>(async () => {
    const client = clientRef.current;
    if (!client) throw new Error("realtime client not ready");
    const result = await client.request<{
      compacted: boolean;
      reason?: string;
      turnCount?: number;
      keepRecent?: number;
    }>("thread/compact", {
      threadId: args.threadId,
    });
    await resume();
    return result;
  }, [args.threadId, resume]);

  const decideHunk = useCallback<UseRealtimeThreadValue["decideHunk"]>(
    async ({ turnId, itemId, hunkId, path, decision, diff }) => {
      const client = clientRef.current;
      if (!client) throw new Error("realtime client not ready");
      await client.request("item/fileChange/hunkDecide", {
        threadId: args.threadId,
        turnId,
        itemId,
        hunkId,
        path,
        decision,
        diff,
      });
    },
    [args.threadId],
  );

  // Derive the two state-dependent inputs the vitals classifier needs.
  const activeTurn = state.turns[state.turns.length - 1];
  const turnActive = activeTurn?.status === "inProgress";
  const hasRunningWork = useMemo(() => {
    if (!activeTurn || activeTurn.status !== "inProgress") return false;
    return activeTurn.items.some(
      (it) => it.status === "inProgress" && WORK_ITEM_TYPES.has(it.type),
    );
  }, [activeTurn]);

  const vitals = useStreamVitals({
    marksRef: vitalsMarksRef,
    connected,
    turnActive,
    hasRunningWork,
  });

  return useMemo(
    () => ({
      state,
      connected,
      vitals,
      startTurn,
      resolveApproval,
      resume,
      loadOlderTurns,
      interrupt,
      compact,
      decideHunk,
    }),
    [
      state,
      connected,
      vitals,
      startTurn,
      resolveApproval,
      resume,
      loadOlderTurns,
      interrupt,
      compact,
      decideHunk,
    ],
  );
}
