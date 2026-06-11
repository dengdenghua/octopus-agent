// React hook bridging RealtimeClient + reducer to component state.
//
// Usage:
//
//   const { state, startTurn, resolveApproval } = useRealtimeThread({
//     threadId: "thread-abc",
//   });
//
// State is a Conversation; ``startTurn`` returns when the server emits
// turn/completed for that turn. Approvals show up as
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
     * runtime to route through ``_drive_team_topology`` instead of
     * single-agent ReAct.
     *
     * NO CURRENT UI CALLER sets this — the swarm mode picker that
     * used to map ``mode → topologyId`` was removed in 2026-06 along
     * with the rest of the swarm deprecation. Field is preserved
     * because the runtime still honors ``topologyId`` for the cowork
     * path; if no caller sets it within 6 weeks of cowork shipping,
     * delete this field entirely.
     */
    topologyId?: string;
  }) => Promise<void>;
  resolveApproval: (requestId: string | number, accept: boolean) => void;
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
  // Latest reduced snapshot for callbacks that don't want React's stale
  // closure semantics. Updated synchronously alongside ``setState``.
  const stateRef = useRef<Conversation>(state);

  const applyEvent = useCallback((evt: ConversationEvent) => {
    setState((prev) => {
      const { next } = reduce(prev, evt);
      stateRef.current = next;
      return next;
    });
  }, []);

  // Build/teardown the client when threadId changes.
  useEffect(() => {
    setState(emptyConversation(args.threadId));
    stateRef.current = emptyConversation(args.threadId);

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

    const onNotification = (note: {
      method: string;
      params: Record<string, unknown>;
    }): void => {
      // ``ConversationEvent`` is a discriminated union over a closed
      // method set. Cast through ``unknown`` because the wire side is
      // open-ended; the reducer no-ops anything it doesn't recognize.
      applyEvent(note as unknown as ConversationEvent);
    };

    const onClose = (code: number, _reason: string): void => {
      // The websocket dropped while a turn was streaming. Without
      // this, the UI keeps showing "thinking..." indefinitely because
      // the reducer never observes a ``turn/completed`` envelope —
      // the only place ``turn.status`` flips out of ``inProgress``.
      // Synthesize a turn/interrupted so ``isLoading`` and the
      // "stop" button drop, the user sees an interrupted-turn marker,
      // and the auto-reconnect path can resume cleanly.
      //
      // Skip when the close was a planned client-side teardown
      // (code 1000 with no reason and the hook tearing down) — that
      // path already cleans up via the unmount effect.
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
      const turns = stateRef.current.turns;
      const active = turns[turns.length - 1];
      if (!active || active.status !== "inProgress") return;
      applyEvent({
        method: "turn/interrupted",
        params: {
          threadId: args.threadId,
          turnId: active.id,
          completedAt: new Date().toISOString(),
          reason: `connection lost (code ${code})`,
        },
      } as unknown as ConversationEvent);
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
    const client = factory({
      onIncomingRequest,
      onNotification,
      onOpen,
      onClose,
    });
    clientRef.current = client;
    client.connect();
    // Note: do NOT setConnected(true) here. The previous optimistic
    // flag has been replaced — onOpen drives it now (see comment on
    // ``onOpen`` above).

    type ResumeResponse = {
      thread: { id: string; path?: string };
      turns: Conversation["turns"];
      hasMore?: boolean;
      totalTurns?: number;
    };
    void client
      .request<ResumeResponse>("thread/resume", {
        threadId: args.threadId,
        limit: RESUME_TURN_LIMIT,
      })
      .then((result) => {
        if (cancelled) return;
        setState((prev) => {
          if (prev.turns.length > 0) {
            const next: Conversation = { ...prev, resumeState: "resumed" };
            stateRef.current = next;
            return next;
          }
          const next: Conversation = {
            ...prev,
            turns: result.turns ?? [],
            resumeState: "resumed",
            hasMoreTurns: result.hasMore === true,
          };
          stateRef.current = next;
          return next;
        });
      })
      .catch(() => {
        if (cancelled) return;
        setState((prev) => {
          const next: Conversation = { ...prev, resumeState: "needsResume" };
          stateRef.current = next;
          return next;
        });
      });

    return () => {
      cancelled = true;
      client.close();
      clientRef.current = null;
      approvalResolvers.current.clear();
      for (const timer of approvalTimers.current.values()) {
        clearTimeout(timer);
      }
      approvalTimers.current.clear();
      setConnected(false);
    };
  }, [args.threadId, args.clientFactory, applyEvent]);

  const startTurn = useCallback<UseRealtimeThreadValue["startTurn"]>(
    async (input) => {
      const client = clientRef.current;
      if (!client) throw new Error("realtime client not ready");
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
        ...(input.sandboxPolicy ? { sandboxPolicy: input.sandboxPolicy } : {}),
        ...(input.planningMode ? { planningMode: input.planningMode } : {}),
        ...(input.effort ? { effort: input.effort } : {}),
        model: input.model,
        ...(input.topologyId ? { topologyId: input.topologyId } : {}),
      });
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
    type ResumeResponse = {
      thread: { id: string; path?: string };
      turns: Conversation["turns"];
      hasMore?: boolean;
      totalTurns?: number;
    };
    const result = await client.request<ResumeResponse>("thread/resume", {
      threadId: args.threadId,
      limit: RESUME_TURN_LIMIT,
    });
    setState((prev) => {
      const next: Conversation = {
        ...prev,
        turns: result.turns ?? [],
        resumeState: "resumed",
        hasMoreTurns: result.hasMore === true,
      };
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
    applyEvent({
      method: "turn/interrupted",
      params: {
        threadId: args.threadId,
        turnId: active.id,
        completedAt: new Date().toISOString(),
      },
    });
  }, [args.threadId, applyEvent]);

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

  return useMemo(
    () => ({
      state,
      connected,
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
