// Approval lifecycle of useRealtimeThread: client-side expiry mirrors
// the server timeout (params.timeoutMs), and a socket drop clears all
// pending approval dialogs (the server cancelled their futures, so the
// request ids are dead).

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JsonRpcRequest } from "./envelope";
import { emptyConversation } from "./items";
import {
  useRealtimeThread,
  visibleConversationForThread,
} from "./use-realtime-thread";

describe("visibleConversationForThread", () => {
  it("hides the previous task during a thread route transition", () => {
    const previous = emptyConversation("previous-thread");

    expect(visibleConversationForThread(previous, "next-thread")).toEqual(
      emptyConversation("next-thread"),
    );
    expect(visibleConversationForThread(previous, "previous-thread")).toBe(
      previous,
    );
  });
});

type IncomingRequestFn = (req: JsonRpcRequest) => Promise<unknown>;

interface FakeClientHandles {
  emitRequest: (req: JsonRpcRequest) => Promise<unknown>;
  emitOpen: () => void;
  emitClose: (code: number, reason: string) => void;
}

function makeFakeClientFactory(handles: FakeClientHandles[]) {
  return (deps: {
    onIncomingRequest: IncomingRequestFn;
    onNotification: (n: {
      method: string;
      params: Record<string, unknown>;
    }) => void;
    onOpen?: () => void;
    onClose?: (code: number, reason: string) => void;
  }) => {
    handles.push({
      emitRequest: (req) => deps.onIncomingRequest(req),
      emitOpen: () => deps.onOpen?.(),
      emitClose: (code, reason) => deps.onClose?.(code, reason),
    });
    return {
      connect: () => {
        deps.onOpen?.();
      },
      close: () => {},
      // thread/resume resolves empty so the hook settles immediately.
      request: () => Promise.resolve({ thread: { id: "th" }, turns: [] }),
      notify: () => {},
    };
  };
}

describe("useRealtimeThread approval lifecycle", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  function setup() {
    const handles: FakeClientHandles[] = [];
    const factory = makeFakeClientFactory(handles);
    const rendered = renderHook(() =>
      useRealtimeThread({
        threadId: "th",
        clientFactory: factory as never,
      }),
    );
    const handle = handles[0]!;
    return { rendered, handle };
  }

  it("expires a pending approval after params.timeoutMs", async () => {
    const { rendered, handle } = setup();

    let reply: unknown = null;
    act(() => {
      void handle
        .emitRequest({
          jsonrpc: "2.0",
          id: 7,
          method: "item/commandExecution/requestApproval",
          params: { tool: "exec_shell", timeoutMs: 5_000 },
        } as JsonRpcRequest)
        .then((decision) => {
          reply = decision;
        });
    });
    expect(rendered.result.current.state.pendingApprovals).toHaveLength(1);

    act(() => {
      vi.advanceTimersByTime(5_001);
    });

    expect(rendered.result.current.state.pendingApprovals).toHaveLength(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(reply).toMatchObject({ action: "decline", reason: "timeout" });
  });

  it("a user resolution cancels the expiry timer", async () => {
    const { rendered, handle } = setup();

    let reply: unknown = null;
    act(() => {
      void handle
        .emitRequest({
          jsonrpc: "2.0",
          id: 8,
          method: "item/commandExecution/requestApproval",
          params: { tool: "exec_shell", timeoutMs: 5_000 },
        } as JsonRpcRequest)
        .then((decision) => {
          reply = decision;
        });
    });

    act(() => {
      rendered.result.current.resolveApproval(8, true);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(reply).toMatchObject({ action: "accept" });
    expect(rendered.result.current.state.pendingApprovals).toHaveLength(0);

    // The timer must not fire a second resolution later.
    act(() => {
      vi.advanceTimersByTime(10_000);
    });
    expect(reply).toMatchObject({ action: "accept" });
  });

  it("drops all pending approvals when the socket closes", () => {
    const { rendered, handle } = setup();

    act(() => {
      void handle.emitRequest({
        jsonrpc: "2.0",
        id: 9,
        method: "item/commandExecution/requestApproval",
        params: { tool: "exec_shell", timeoutMs: 60_000 },
      } as JsonRpcRequest);
    });
    expect(rendered.result.current.state.pendingApprovals).toHaveLength(1);

    act(() => {
      handle.emitClose(1006, "abnormal");
    });

    expect(rendered.result.current.state.pendingApprovals).toHaveLength(0);
  });
});

describe("useRealtimeThread reconnect reconciliation", () => {
  function turn(id: string, status: "inProgress" | "completed") {
    return {
      id,
      threadId: "th",
      status,
      items: [],
      startedAt: "2026-01-01T00:00:00.000Z",
      ...(status === "completed"
        ? { completedAt: "2026-01-01T00:00:05.000Z" }
        : {}),
    };
  }

  it("keeps live state until incremental server truth arrives", async () => {
    const handles: FakeClientHandles[] = [];
    let resumeCount = 0;
    const eventsParams: Record<string, unknown>[] = [];
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => {
      handles.push({
        emitRequest: (req) => deps.onIncomingRequest(req),
        emitOpen: () => deps.onOpen?.(),
        emitClose: (code, reason) => deps.onClose?.(code, reason),
      });
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string, params?: Record<string, unknown>) => {
          // Incremental reconnects go through thread/events (event mode).
          if (method === "thread/events") {
            eventsParams.push(params ?? {});
            return Promise.resolve({
              thread: { id: "th" },
              events: [
                {
                  sequence: 11,
                  event: "turn_completed",
                  eventId: "evt_done",
                  threadId: "th",
                  turnId: "t-live",
                  ts: "2026-01-01T00:00:05.000Z",
                  payload: { status: "completed", error: null },
                },
              ],
              cursor: 11,
              streamId: "stream-a",
              requiresReset: false,
              hasMore: false,
              turnCount: 1,
              lastTurnId: "t-live",
              lastTurnStatus: "completed",
            });
          }
          if (method !== "thread/resume") return Promise.resolve({});
          resumeCount += 1;
          return Promise.resolve({
            thread: { id: "th" },
            turns: [turn("t-live", "inProgress")],
            hasMore: false,
            incremental: false,
            nextEventSequence: 10,
            eventStreamId: "stream-a",
          });
        },
      };
    };

    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );

    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.status).toBe("inProgress"),
    );

    act(() => {
      handles[0]!.emitClose(1006, "network lost");
    });
    expect(rendered.result.current.connected).toBe(false);
    expect(rendered.result.current.state.turns[0]?.status).toBe("inProgress");

    act(() => {
      handles[0]!.emitOpen();
    });

    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.status).toBe("completed"),
    );
    expect(resumeCount).toBe(1);
    // thread/events sees the background backfill (afterSequence 0) AND the
    // incremental reconnect fetch — assert on the incremental one.
    expect(eventsParams[eventsParams.length - 1]).toMatchObject({
      afterSequence: 10,
      eventStreamId: "stream-a",
    });
  });

  it("replaces the timeline when the server resets the event stream", async () => {
    const handles: FakeClientHandles[] = [];
    const resumeParams: Record<string, unknown>[] = [];
    const eventsParams: Record<string, unknown>[] = [];
    let resumeCount = 0;
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => {
      handles.push({
        emitRequest: (req) => deps.onIncomingRequest(req),
        emitOpen: () => deps.onOpen?.(),
        emitClose: (code, reason) => deps.onClose?.(code, reason),
      });
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string, params?: Record<string, unknown>) => {
          // The server reports a foreign stream: event mode defers to the
          // snapshot path, which replaces the whole timeline.
          if (method === "thread/events") {
            eventsParams.push(params ?? {});
            return Promise.resolve({
              thread: { id: "th" },
              events: [],
              cursor: 3,
              streamId: "stream-new",
              requiresReset: true,
              hasMore: false,
              turnCount: 1,
              lastTurnId: "t-new",
              lastTurnStatus: "completed",
            });
          }
          if (method !== "thread/resume") return Promise.resolve({});
          resumeCount += 1;
          resumeParams.push(params ?? {});
          return Promise.resolve(
            resumeCount === 1
              ? {
                  thread: { id: "th" },
                  turns: [turn("t-old", "completed")],
                  hasMore: false,
                  incremental: false,
                  nextEventSequence: 3,
                  eventStreamId: "stream-old",
                }
              : {
                  thread: { id: "th" },
                  turns: [turn("t-new", "completed")],
                  hasMore: false,
                  incremental: false,
                  nextEventSequence: 3,
                  eventStreamId: "stream-new",
                },
          );
        },
      };
    };

    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );
    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t-old"),
    );

    act(() => {
      handles[0]!.emitClose(1006, "network lost");
      handles[0]!.emitOpen();
    });

    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t-new"),
    );
    expect(rendered.result.current.state.turns).toHaveLength(1);
    // Event mode was attempted against the old stream (among background
    // backfill calls, which use afterSequence 0)...
    expect(eventsParams).toContainEqual(
      expect.objectContaining({
        afterSequence: 3,
        eventStreamId: "stream-old",
      }),
    );
    // ...then the snapshot fallback ran WITHOUT the stale cursor.
    expect(resumeCount).toBe(2);
    expect(resumeParams[1]).not.toHaveProperty("afterSequence");
  });

  it("preserves the timeline when an incremental resume has no changes", async () => {
    const handles: FakeClientHandles[] = [];
    const eventsParams: Record<string, unknown>[] = [];
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => {
      handles.push({
        emitRequest: (req) => deps.onIncomingRequest(req),
        emitOpen: () => deps.onOpen?.(),
        emitClose: (code, reason) => deps.onClose?.(code, reason),
      });
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string, params?: Record<string, unknown>) => {
          if (method === "thread/events") {
            eventsParams.push(params ?? {});
            return Promise.resolve({
              thread: { id: "th" },
              events: [],
              cursor: 20,
              streamId: "stream-b",
              requiresReset: false,
              hasMore: false,
              turnCount: 1,
              lastTurnId: "t-stable",
              lastTurnStatus: "completed",
            });
          }
          if (method !== "thread/resume") return Promise.resolve({});
          return Promise.resolve({
            thread: { id: "th" },
            turns: [turn("t-stable", "completed")],
            hasMore: true,
            incremental: false,
            nextEventSequence: 20,
          });
        },
      };
    };

    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );
    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t-stable"),
    );

    act(() => {
      handles[0]!.emitClose(1006, "network lost");
      handles[0]!.emitOpen();
    });

    // The incremental reconnect fetch uses the durable cursor (the other
    // thread/events call with afterSequence 0 is the background backfill).
    await waitFor(() =>
      expect(eventsParams).toContainEqual(
        expect.objectContaining({ afterSequence: 20 }),
      ),
    );
    expect(rendered.result.current.state.turns[0]?.id).toBe("t-stable");
    expect(rendered.result.current.state.hasMoreTurns).toBe(true);
  });

  it("does not double-apply an event delivered live before the log fold", async () => {
    const handles: FakeClientHandles[] = [];
    let emitNotification:
      | ((n: { method: string; params: Record<string, unknown> }) => void)
      | undefined;
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => {
      emitNotification = deps.onNotification;
      handles.push({
        emitRequest: (req) => deps.onIncomingRequest(req),
        emitOpen: () => deps.onOpen?.(),
        emitClose: (code, reason) => deps.onClose?.(code, reason),
      });
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string) => {
          if (method === "thread/events") {
            // The log slice CONTAINS the delta the client already applied
            // live — the shared eventId must make the fold a no-op.
            return Promise.resolve({
              thread: { id: "th" },
              events: [
                {
                  sequence: 11,
                  event: "item_delta",
                  eventId: "evt_dup",
                  threadId: "th",
                  turnId: "t-live",
                  ts: "2026-01-01T00:00:01.000Z",
                  payload: { itemId: "i1", kind: "agentMessage", delta: "abc" },
                },
              ],
              cursor: 11,
              streamId: "stream-a",
              requiresReset: false,
              hasMore: false,
              turnCount: 1,
              lastTurnId: "t-live",
              lastTurnStatus: "inProgress",
            });
          }
          if (method !== "thread/resume") return Promise.resolve({});
          return Promise.resolve({
            thread: { id: "th" },
            turns: [
              {
                ...turn("t-live", "inProgress"),
                items: [
                  {
                    id: "i1",
                    type: "agentMessage",
                    status: "inProgress",
                    createdAt: "2026-01-01T00:00:00.000Z",
                    text: "",
                  },
                ],
              },
            ],
            hasMore: false,
            incremental: false,
            nextEventSequence: 10,
            eventStreamId: "stream-a",
          });
        },
      };
    };

    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );
    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t-live"),
    );

    // Live delivery of the delta, stamped with its persisted eventId.
    act(() => {
      emitNotification?.({
        method: "item/agentMessage/delta",
        params: {
          threadId: "th",
          turnId: "t-live",
          itemId: "i1",
          delta: "abc",
          eventId: "evt_dup",
        },
      });
    });

    act(() => {
      handles[0]!.emitClose(1006, "network lost");
      handles[0]!.emitOpen();
    });

    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("resumed"),
    );
    const item = rendered.result.current.state.turns[0]?.items[0];
    expect(item?.type === "agentMessage" && item.text).toBe("abc");
  });

  it("falls back to a snapshot resume when the event fold diverges", async () => {
    const handles: FakeClientHandles[] = [];
    let resumeCount = 0;
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => {
      handles.push({
        emitRequest: (req) => deps.onIncomingRequest(req),
        emitOpen: () => deps.onOpen?.(),
        emitClose: (code, reason) => deps.onClose?.(code, reason),
      });
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string) => {
          if (method === "thread/events") {
            // Authoritative tail disagrees with the folded state — the
            // client must distrust the event path entirely.
            return Promise.resolve({
              thread: { id: "th" },
              events: [],
              cursor: 5,
              streamId: "stream-a",
              requiresReset: false,
              hasMore: false,
              turnCount: 7,
              lastTurnId: "t-elsewhere",
              lastTurnStatus: "completed",
            });
          }
          if (method !== "thread/resume") return Promise.resolve({});
          resumeCount += 1;
          return Promise.resolve(
            resumeCount === 1
              ? {
                  thread: { id: "th" },
                  turns: [turn("t-x", "completed")],
                  hasMore: false,
                  incremental: false,
                  nextEventSequence: 5,
                  eventStreamId: "stream-a",
                }
              : {
                  thread: { id: "th" },
                  turns: [turn("t-fixed", "completed")],
                  hasMore: false,
                  incremental: false,
                  nextEventSequence: 42,
                  eventStreamId: "stream-a",
                },
          );
        },
      };
    };

    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );
    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t-x"),
    );

    act(() => {
      handles[0]!.emitClose(1006, "network lost");
      handles[0]!.emitOpen();
    });

    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t-fixed"),
    );
    expect(resumeCount).toBe(2);
  });

  it("resumes on first socket open after the startup resume request failed", async () => {
    const handles: FakeClientHandles[] = [];
    let resumeCount = 0;
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => {
      handles.push({
        emitRequest: (req) => deps.onIncomingRequest(req),
        emitOpen: () => deps.onOpen?.(),
        emitClose: (code, reason) => deps.onClose?.(code, reason),
      });
      return {
        connect: () => {},
        close: () => {},
        notify: () => {},
        request: (method: string) => {
          if (method !== "thread/resume") return Promise.resolve({});
          resumeCount += 1;
          if (resumeCount === 1) {
            return Promise.reject(new Error("backend not ready"));
          }
          return Promise.resolve({
            thread: { id: "th" },
            turns: [turn("t-ready", "completed")],
            hasMore: false,
          });
        },
      };
    };

    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );

    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("needsResume"),
    );
    expect(resumeCount).toBe(1);

    act(() => {
      handles[0]!.emitOpen();
    });

    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t-ready"),
    );
    expect(rendered.result.current.state.resumeState).toBe("resumed");
    expect(resumeCount).toBe(2);
  });
});

describe("useRealtimeThread turn/start delivery anchoring", () => {
  // The server holds the turn/start response until the turn completes,
  // so a mid-turn socket drop rejects the pending request. Once the
  // turn/started notification was observed the send is known-delivered
  // and startTurn must not surface the transport rejection.

  interface DeliveryHandles {
    emitNotification: (n: {
      method: string;
      params: Record<string, unknown>;
    }) => void;
    rejectTurnStart: (err: Error) => void;
  }

  function setupDelivery() {
    const handles: Partial<DeliveryHandles> = {};
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => {
      handles.emitNotification = (n) => deps.onNotification(n);
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string) => {
          if (method === "turn/start") {
            return new Promise((_resolve, reject) => {
              handles.rejectTurnStart = reject;
            });
          }
          return Promise.resolve({ thread: { id: "th" }, turns: [] });
        },
      };
    };
    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );
    return { rendered, handles: handles as DeliveryHandles };
  }

  function watchSettlement(promise: Promise<void>) {
    const outcome: { value: "resolved" | "rejected" | null } = { value: null };
    promise.then(
      () => {
        outcome.value = "resolved";
      },
      () => {
        outcome.value = "rejected";
      },
    );
    return outcome;
  }

  it("resolves startTurn when turn/started arrived before the socket-drop rejection", async () => {
    const { rendered, handles } = setupDelivery();
    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("resumed"),
    );

    let outcome!: ReturnType<typeof watchSettlement>;
    act(() => {
      outcome = watchSettlement(
        rendered.result.current.startTurn({ input: "hello" }),
      );
    });

    act(() => {
      handles.emitNotification({
        method: "turn/started",
        params: {
          threadId: "th",
          turn: {
            id: "t-live",
            threadId: "th",
            status: "inProgress",
            items: [],
            startedAt: "2026-01-01T00:00:00.000Z",
            completedAt: null,
            error: null,
          },
        },
      });
    });
    act(() => {
      handles.rejectTurnStart(new Error("websocket closed (1006 no reason)"));
    });

    await waitFor(() => expect(outcome.value).toBe("resolved"));
  });

  it("rejects startTurn when the socket drops before turn/started", async () => {
    const { rendered, handles } = setupDelivery();
    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("resumed"),
    );

    let outcome!: ReturnType<typeof watchSettlement>;
    act(() => {
      outcome = watchSettlement(
        rendered.result.current.startTurn({ input: "hello" }),
      );
    });
    act(() => {
      handles.rejectTurnStart(new Error("websocket closed (1006 no reason)"));
    });

    await waitFor(() => expect(outcome.value).toBe("rejected"));
  });

  it("ignores turn/started from other threads when anchoring delivery", async () => {
    const { rendered, handles } = setupDelivery();
    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("resumed"),
    );

    let outcome!: ReturnType<typeof watchSettlement>;
    act(() => {
      outcome = watchSettlement(
        rendered.result.current.startTurn({ input: "hello" }),
      );
    });

    act(() => {
      handles.emitNotification({
        method: "turn/started",
        params: {
          threadId: "other-thread",
          turn: {
            id: "t-foreign",
            threadId: "other-thread",
            status: "inProgress",
            items: [],
            startedAt: "2026-01-01T00:00:00.000Z",
            completedAt: null,
            error: null,
          },
        },
      });
    });
    act(() => {
      handles.rejectTurnStart(new Error("websocket closed (1006 no reason)"));
    });

    await waitFor(() => expect(outcome.value).toBe("rejected"));
  });
});

describe("useRealtimeThread live steering", () => {
  it("targets the active turn with a durable client item id", async () => {
    const requests: Array<{ method: string; params: Record<string, unknown> }> =
      [];
    let emitNotification!: (n: {
      method: string;
      params: Record<string, unknown>;
    }) => void;
    const factory = (deps: {
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
    }) => {
      emitNotification = deps.onNotification;
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string, params: Record<string, unknown>) => {
          requests.push({ method, params });
          if (method === "thread/resume") {
            return Promise.resolve({ thread: { id: "th" }, turns: [] });
          }
          return Promise.resolve({ accepted: true });
        },
      };
    };
    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );
    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("resumed"),
    );
    act(() => {
      emitNotification({
        method: "turn/started",
        params: {
          threadId: "th",
          turn: {
            id: "turn-live",
            threadId: "th",
            status: "inProgress",
            items: [],
            startedAt: "2026-01-01T00:00:00.000Z",
            completedAt: null,
            error: null,
          },
        },
      });
    });

    await act(async () => {
      await rendered.result.current.steer({ input: "  换一种实现  " });
    });

    const request = requests.find((entry) => entry.method === "turn/steer");
    expect(request?.params).toMatchObject({
      threadId: "th",
      turnId: "turn-live",
      text: "换一种实现",
    });
    expect(request?.params.itemId).toMatch(/^itm_steer_/);
  });
});

describe("useRealtimeThread interrupt approvals", () => {
  it("declines and removes approvals owned by the stopped turn", async () => {
    let emitNotification!: (n: {
      method: string;
      params: Record<string, unknown>;
    }) => void;
    let emitRequest!: (req: JsonRpcRequest) => Promise<unknown>;
    const methods: string[] = [];
    const factory = (deps: {
      onIncomingRequest: (req: JsonRpcRequest) => Promise<unknown>;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
    }) => {
      emitNotification = deps.onNotification;
      emitRequest = deps.onIncomingRequest;
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string) => {
          methods.push(method);
          if (method === "thread/resume") {
            return Promise.resolve({ thread: { id: "th" }, turns: [] });
          }
          return Promise.resolve({ interrupted: true });
        },
      };
    };
    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );
    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("resumed"),
    );
    act(() => {
      emitNotification({
        method: "turn/started",
        params: {
          threadId: "th",
          turn: {
            id: "turn-live",
            threadId: "th",
            status: "inProgress",
            items: [],
            startedAt: "2026-01-01T00:00:00.000Z",
            completedAt: null,
            error: null,
          },
        },
      });
    });
    let decision: unknown;
    act(() => {
      void emitRequest({
        jsonrpc: "2.0",
        id: 91,
        method: "item/commandExecution/requestApproval",
        params: { threadId: "th", turnId: "turn-live" },
      }).then((value) => {
        decision = value;
      });
    });
    expect(rendered.result.current.state.pendingApprovals).toHaveLength(1);

    await act(async () => {
      await rendered.result.current.interrupt();
    });

    await waitFor(() =>
      expect(rendered.result.current.state.pendingApprovals).toHaveLength(0),
    );
    expect(decision).toEqual({ action: "decline", reason: "turn interrupted" });
    expect(methods).toContain("turn/interrupt");
  });
});

describe("useRealtimeThread backwards pagination", () => {
  function turn(id: string) {
    return {
      id,
      threadId: "th",
      status: "completed",
      items: [],
      startedAt: new Date().toISOString(),
    };
  }

  function makePagingFactory() {
    const requests: Array<{ method: string; params: Record<string, unknown> }> =
      [];
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => ({
      connect: () => deps.onOpen?.(),
      close: () => {},
      notify: () => {},
      request: (method: string, params: Record<string, unknown>) => {
        requests.push({ method, params });
        if (method !== "thread/resume") return Promise.resolve({});
        if (params.beforeTurnId === "t-8") {
          return Promise.resolve({
            turns: [turn("t-6"), turn("t-7")],
            hasMore: false,
          });
        }
        return Promise.resolve({
          thread: { id: "th" },
          turns: [turn("t-8"), turn("t-9")],
          hasMore: true,
        });
      },
    });
    return { factory, requests };
  }

  it("resumes with a limit and pages older turns in front", async () => {
    const { factory, requests } = makePagingFactory();
    const rendered = renderHook(() =>
      useRealtimeThread({ threadId: "th", clientFactory: factory as never }),
    );

    await waitFor(() =>
      expect(rendered.result.current.state.resumeState).toBe("resumed"),
    );
    expect(rendered.result.current.state.turns.map((t) => t.id)).toEqual([
      "t-8",
      "t-9",
    ]);
    expect(rendered.result.current.state.hasMoreTurns).toBe(true);
    const initialResume = requests.find((r) => r.method === "thread/resume");
    expect(initialResume?.params.limit).toBeGreaterThan(0);

    await act(async () => {
      await rendered.result.current.loadOlderTurns();
    });

    expect(rendered.result.current.state.turns.map((t) => t.id)).toEqual([
      "t-6",
      "t-7",
      "t-8",
      "t-9",
    ]);
    expect(rendered.result.current.state.hasMoreTurns).toBe(false);

    // Exhausted — further calls are no-ops, no extra RPC.
    const callCount = requests.length;
    await act(async () => {
      await rendered.result.current.loadOlderTurns();
    });
    expect(requests.length).toBe(callCount);
  });
});

describe("useRealtimeThread cold-start replay cache", () => {
  const TS = "2026-07-28T00:00:00.000Z";

  function cachedLog() {
    return [
      {
        sequence: 1,
        event: "thread_started",
        eventId: "e1",
        threadId: "th",
        ts: TS,
        turnId: null,
        payload: {},
      },
      {
        sequence: 2,
        event: "turn_started",
        eventId: "e2",
        threadId: "th",
        ts: TS,
        turnId: "t-cached",
        payload: {},
      },
      {
        sequence: 3,
        event: "item_started",
        eventId: "e3",
        threadId: "th",
        ts: TS,
        turnId: "t-cached",
        payload: {
          item: {
            id: "u1",
            type: "userMessage",
            status: "completed",
            createdAt: TS,
            text: "cached question",
          },
        },
      },
      {
        sequence: 4,
        event: "turn_completed",
        eventId: "e4",
        threadId: "th",
        ts: TS,
        turnId: "t-cached",
        payload: { status: "completed", error: null },
      },
    ];
  }

  it("hydrates from the cache and resumes in event mode", async () => {
    const { createMemoryReplayCache } = await import("./replay-cache");
    const cache = createMemoryReplayCache();
    await cache.append("th", cachedLog(), { streamId: "s-cache", cursor: 4 });

    const handles: FakeClientHandles[] = [];
    const requests: { method: string; params?: Record<string, unknown> }[] =
      [];
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => {
      handles.push({
        emitRequest: (req) => deps.onIncomingRequest(req),
        emitOpen: () => deps.onOpen?.(),
        emitClose: (code, reason) => deps.onClose?.(code, reason),
      });
      return {
        connect: () => deps.onOpen?.(),
        close: () => {},
        notify: () => {},
        request: (method: string, params?: Record<string, unknown>) => {
          requests.push({ method, params });
          if (method === "thread/events") {
            return Promise.resolve({
              thread: { id: "th" },
              events: [
                {
                  sequence: 5,
                  event: "turn_started",
                  eventId: "e5",
                  threadId: "th",
                  ts: TS,
                  turnId: "t-new",
                  payload: {},
                },
                {
                  sequence: 6,
                  event: "turn_completed",
                  eventId: "e6",
                  threadId: "th",
                  ts: TS,
                  turnId: "t-new",
                  payload: { status: "completed", error: null },
                },
              ],
              cursor: 6,
              streamId: "s-cache",
              requiresReset: false,
              hasMore: false,
              turnCount: 2,
              lastTurnId: "t-new",
              lastTurnStatus: "completed",
            });
          }
          return Promise.resolve({});
        },
      };
    };

    const rendered = renderHook(() =>
      useRealtimeThread({
        threadId: "th",
        clientFactory: factory as never,
        replayCache: cache,
      }),
    );

    // Cached content renders from the local log...
    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t-cached"),
    );
    // ...then the incremental fold appends what changed since the cursor.
    await waitFor(() =>
      expect(rendered.result.current.state.turns[1]?.id).toBe("t-new"),
    );

    // Event mode only: the snapshot RPC was never needed.
    const methods = requests.map((r) => r.method);
    expect(methods).not.toContain("thread/resume");
    expect(requests[0]).toMatchObject({
      method: "thread/events",
      params: { afterSequence: 4, eventStreamId: "s-cache" },
    });

    // The fetched slice was written back for the next cold start.
    const cached = await cache.load("th");
    expect(cached?.events.map((e) => e.sequence)).toEqual([1, 2, 3, 4, 5, 6]);
    expect(cached?.cursor).toBe(6);
  });

  it("starts with a snapshot resume when the cache is empty", async () => {
    const { createMemoryReplayCache } = await import("./replay-cache");
    const cache = createMemoryReplayCache();
    const requests: string[] = [];
    const factory = (deps: {
      onIncomingRequest: IncomingRequestFn;
      onNotification: (n: {
        method: string;
        params: Record<string, unknown>;
      }) => void;
      onOpen?: () => void;
      onClose?: (code: number, reason: string) => void;
    }) => ({
      connect: () => deps.onOpen?.(),
      close: () => {},
      notify: () => {},
      request: (method: string, params?: Record<string, unknown>) => {
        requests.push(method);
        if (method === "thread/resume") {
          return Promise.resolve({
            thread: { id: "th" },
            turns: [
              {
                id: "t1",
                threadId: "th",
                status: "completed",
                items: [],
                startedAt: TS,
                completedAt: TS,
              },
            ],
            hasMore: false,
            incremental: false,
            nextEventSequence: 9,
            eventStreamId: "s1",
          });
        }
        if (method === "thread/events") {
          // Background backfill after the snapshot lands.
          return Promise.resolve({
            thread: { id: "th" },
            events: cachedLog(),
            cursor: 4,
            streamId: "s1",
            requiresReset: false,
            hasMore: false,
            turnCount: 1,
            lastTurnId: "t1",
            lastTurnStatus: "completed",
          });
        }
        void params;
        return Promise.resolve({});
      },
    });

    const rendered = renderHook(() =>
      useRealtimeThread({
        threadId: "th",
        clientFactory: factory as never,
        replayCache: cache,
      }),
    );

    await waitFor(() =>
      expect(rendered.result.current.state.turns[0]?.id).toBe("t1"),
    );
    expect(requests[0]).toBe("thread/resume");

    // Backfill populated the cache for the next open.
    await waitFor(async () => {
      const cached = await cache.load("th");
      expect(cached?.events.length).toBeGreaterThan(0);
    });
  });
});
