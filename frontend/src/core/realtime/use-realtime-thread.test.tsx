// Approval lifecycle of useRealtimeThread: client-side expiry mirrors
// the server timeout (params.timeoutMs), and a socket drop clears all
// pending approval dialogs (the server cancelled their futures, so the
// request ids are dead).

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JsonRpcRequest } from "./envelope";
import { useRealtimeThread } from "./use-realtime-thread";

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
    const resumeParams: Record<string, unknown>[] = [];
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
          if (method !== "thread/resume") return Promise.resolve({});
          resumeCount += 1;
          resumeParams.push(params ?? {});
          return Promise.resolve({
            thread: { id: "th" },
            turns: [
              resumeCount === 1
                ? turn("t-live", "inProgress")
                : turn("t-live", "completed"),
            ],
            hasMore: false,
            incremental: resumeCount > 1,
            nextEventSequence: resumeCount === 1 ? 10 : 14,
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
    expect(resumeCount).toBe(2);
    expect(resumeParams[1]).toMatchObject({
      afterSequence: 10,
      eventStreamId: "stream-a",
    });
  });

  it("replaces the timeline when the server resets the event stream", async () => {
    const handles: FakeClientHandles[] = [];
    const resumeParams: Record<string, unknown>[] = [];
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
    expect(resumeParams[1]).toMatchObject({
      afterSequence: 3,
      eventStreamId: "stream-old",
    });
  });

  it("preserves the timeline when an incremental resume has no changes", async () => {
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
          if (method !== "thread/resume") return Promise.resolve({});
          resumeCount += 1;
          return Promise.resolve(
            resumeCount === 1
              ? {
                  thread: { id: "th" },
                  turns: [turn("t-stable", "completed")],
                  hasMore: true,
                  incremental: false,
                  nextEventSequence: 20,
                }
              : {
                  thread: { id: "th" },
                  turns: [],
                  incremental: true,
                  nextEventSequence: 20,
                },
          );
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

    await waitFor(() => expect(resumeCount).toBe(2));
    expect(rendered.result.current.state.turns[0]?.id).toBe("t-stable");
    expect(rendered.result.current.state.hasMoreTurns).toBe(true);
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

    await waitFor(() => expect(resumeCount).toBe(1));
    expect(rendered.result.current.state.resumeState).toBe("needsResume");

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
